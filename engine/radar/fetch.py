"""Save a source: the only place the engine touches the network.

The saved text copy is exactly what extract_text returns for the downloaded bytes: no model,
no summarising, no editing. Everything downloaded is untrusted data: parsed, never executed.
Nothing is sent but the user agent and what urllib adds by default (no cookies, no credentials).
"""
import http.client
import ipaddress
import json
import re
import socket
import string
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urldefrag, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from . import store
from .extract_text import NoTextLayer, PdfAddOnMissing, decode_bytes, html_to_text, pdf_to_text, sniff_kind

USER_AGENT = "strategy-radar/0.1"
MIN_DELAY_SECONDS = 2.0
MAX_BYTES = 50_000_000
TIMEOUT_SECONDS = 30
MAX_REDIRECTS = 5

_MIN_TEXT_CHARS = 200
PDF_ADD_ON_MISSING = ("The PDF add-on is not installed, so a PDF cannot be read and nothing was saved. "
                      "Run: radar setup, then try again.")
TOO_LITTLE_TEXT = ("The page shows a reader too little text to quote from (too_little_text), so it was not saved. "
                   "Text the page hides from its readers does not count.")
_MAX_ROBOTS_BYTES = 1_000_000
_SCHEMES = ("http", "https")
_META_KEYS = ("publisher", "title", "date", "type", "speaker", "interest", "language")
_HAND_EXTENSIONS = (".pdf", ".html", ".htm", ".txt", ".csv")
_PASSWORD_FIELD = re.compile(r"<input\b[^>]*\btype\s*=\s*[\"']?password", re.IGNORECASE)


class _Refused(Exception):
    """The source cannot be saved; `reason` goes into access_reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Redirect(Exception):
    """The site answered with a redirect; `location` is what it said, not yet checked."""

    def __init__(self, location: str) -> None:
        super().__init__(location)
        self.location = location


class _StopAtRedirects(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: hand back where it points, so every hop can be checked first."""

    def http_error_302(self, req, fp, code, msg, headers):
        location = (headers.get("location") or headers.get("uri") or "").strip()
        if not location:
            return None   # a redirect that goes nowhere is an ordinary refusal by the site
        fp.close()
        raise _Redirect(location)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _opener() -> urllib.request.OpenerDirector:
    # No cookie processor and no auth handlers: nothing is remembered or sent besides the agent.
    opener = urllib.request.build_opener(_StopAtRedirects)
    opener.addheaders = [("User-Agent", USER_AGENT)]
    return opener


PUBLIC, PRIVATE, UNRESOLVED = "public", "private", "unresolved"
_CARRIER_FORMS = tuple(ipaddress.ip_network(text) for text in
                       ("2002::/16",        # 6to4
                        "2001:0::/32"))     # Teredo
_NAT64 = ipaddress.ip_network("64:ff9b::/96")   # the well-known NAT64 prefix: the last 32 bits are an IPv4 address


def _is_plain_public(address) -> bool:
    return bool(address.is_global) and not (
        address.is_loopback or address.is_private or address.is_link_local or address.is_reserved
        or address.is_multicast or address.is_unspecified or getattr(address, "is_site_local", False))


def _is_carrier_form(address) -> bool:
    """Whether an IPv6 address is a 6to4 or Teredo form, which carries an IPv4 address inside it.

    Recognised here by range and not left to `is_global`, whose answer for these ranges differs between
    patch levels of Python."""
    return address.version == 6 and any(address in network for network in _CARRIER_FORMS)


def _is_public(address) -> bool:
    """An address that carries an IPv4 address by mapping (::ffff:10.0.0.5) or by the NAT64 prefix (64:ff9b::a00:5)
    is judged by that IPv4 address, by the same rules as any IPv4 address: a network that reaches IPv4 sites through
    NAT64 answers every name with such an address. A 6to4 or Teredo address is never public, whatever address it
    carries: ordinary websites are not reached through these forms, and the answer is then the same on every Python."""
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    elif address.version == 6 and address in _NAT64:
        address = ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return not _is_carrier_form(address) and _is_plain_public(address)


def check_address(host: str, resolve=socket.getaddrinfo) -> str:
    """`"public"` when `host` resolves and every address it resolves to is public; `"private"` when it resolved and at
    least one address is not public (or its text cannot be read); `"unresolved"` when it did not resolve or gave nothing.

    Not guarded: a name can resolve differently when the check runs and when the page is downloaded (DNS rebinding),
    and when the computer is set to use a proxy the request goes to the proxy, which looks the name up itself, so this
    check does not cover what the proxy can reach. The check stops addresses that are plainly inside a network on this
    computer's side, not an attacker who runs the name server and not a proxy that reaches further than the computer.
    """
    try:
        answers = list(resolve(host, None))
    except (OSError, ValueError, TypeError):   # no such host, or a name that cannot be looked up
        return UNRESOLVED
    if not answers:
        return UNRESOLVED
    for answer in answers:
        try:
            address = ipaddress.ip_address(answer[4][0])
        except (ValueError, IndexError, TypeError):
            return PRIVATE
        if not _is_public(address):
            return PRIVATE
    return PUBLIC


def public_address(host: str, resolve=socket.getaddrinfo) -> bool:
    """True only when `host` resolves and every address it resolves to belongs to the public internet."""
    return check_address(host, resolve) == PUBLIC


def _state(answer) -> str:
    """What an `address_allowed` answer means: True is public, one of the three words is itself, all else is private."""
    if answer is True:
        return PUBLIC
    return answer if isinstance(answer, str) and answer in (PUBLIC, PRIVATE, UNRESOLVED) else PRIVATE


SPACE_IN_ADDRESS = ("The address must not hold spaces or control characters. "
                    "A space inside an address is written as %20.")
INVISIBLE_IN_ADDRESS = ("The address must not hold invisible characters, such as a zero-width character, a line "
                        "separator or a direction mark.")
INVISIBLE_IN_LABEL = ("The place where the document lives must not hold control characters or invisible characters "
                      "such as a zero-width character or a direction mark.")
# Characters an address may not hold anywhere: spaces and separators, control and format characters, and half of a
# character pair standing alone (Unicode Zs, Zl, Zp, Cc, Cf, Cs; the last is what an argument holds whose bytes were
# not UTF-8). A reader cannot see most of them, and a page requested with one is not the page that was named.
_SPACE_OR_CONTROL = ("Zs", "Cc")
_INVISIBLE = ("Zl", "Zp", "Cf", "Cs")


def _refuse_invisible(text: str) -> None:
    """Refuse, in plain words, an address holding a space, a separator, a control or a format character."""
    for char in text:
        category = unicodedata.category(char)
        if category in _SPACE_OR_CONTROL:
            raise ValueError(SPACE_IN_ADDRESS)
        if category in _INVISIBLE:
            raise ValueError(INVISIBLE_IN_ADDRESS)


def check_copy_address(url: str) -> None:
    """The `--url` of add-copy: a web address (http or https) is refused for every character a downloaded address may
    not hold; a label in free words (`internal://memo`, a file name, a description) only for a control or format
    character, which a reader cannot see."""
    try:
        scheme = urlsplit(url).scheme.lower()
    except ValueError:   # a damaged address written by hand is kept as a label, as before
        scheme = ""
    if scheme in _SCHEMES:
        _refuse_invisible(url)
    elif any(unicodedata.category(char) in ("Cc", "Cf") for char in url):
        raise ValueError(INVISIBLE_IN_LABEL)


def first_address(url: str) -> str:
    """The address given to save-source, as it is requested and recorded: an invisible character is refused (never
    encoded), a letter outside ASCII in the path or query is percent-encoded as UTF-8, then the form is checked."""
    _refuse_invisible(url)
    url = encode_letters(url)
    check_url(url)
    return url


def encode_letters(url: str) -> str:
    """The address with every character outside ASCII percent-encoded as UTF-8, as a browser sends it; ASCII is left as
    it is. A letter in the site name is encoded too, so the site-name rule of `check_url` still refuses it."""
    return url if url.isascii() else quote(url, safe=string.punctuation, encoding="utf-8")
_HOST_NAME = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.?")   # no empty label but one trailing dot


def _is_ipv6_literal(text: str) -> bool:
    """True when `text`, the part of a site name written in square brackets, is an IPv6 address. Hex digits, colons
    and dots are not enough: `127.0.0.1` and `:::` are made of them too, and an IPv4 address is never written in
    brackets. A zone name after a percent sign is not accepted."""
    if not text or "%" in text:
        return False
    try:
        ipaddress.IPv6Address(text)
    except ValueError:
        return False
    return True


def check_url(url: str) -> None:
    """Only the plain form of an address is accepted (a `ValueError` otherwise). urllib decodes a percent sign in a
    host name before it connects, so the host that was checked would not be the host that is requested; the host part
    is therefore restricted to what means the same to every program. The same function checks the first address, every
    hop and, in the data check, the `final_url` of a record, so what the download can record always passes the check.

    A space, separator, control or format character anywhere in the text is refused before it is parsed: urlsplit
    would silently drop a tab, a carriage return or a line feed, and the form check must not rest on that."""
    _refuse_invisible(url)
    parts = urlsplit(url)
    if parts.scheme.lower() not in _SCHEMES or not parts.hostname:
        raise ValueError("only http and https URLs can be saved")
    if parts.username is not None or parts.password is not None:
        raise ValueError("the URL must not contain a user name or password")
    netloc = parts.netloc
    if netloc.startswith("["):
        host, _, rest = netloc[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else rest
        plain = _is_ipv6_literal(host) and (rest == "" or rest.startswith(":"))
    else:
        host, _, port = netloc.partition(":")
        plain = bool(_HOST_NAME.fullmatch(host))
    if not (netloc.isascii() and plain):
        raise ValueError("the site name may hold only the plain letters a to z, digits, hyphens and dots; "
                         "a name with other letters must be given in its xn-- form")
    if not (port.isascii() and port.isdigit() or port == ""):
        raise ValueError("the port of the address must be a number")
    if port and not 1 <= int(port) <= 65535:
        raise ValueError("the port of the address must be a number from 1 to 65535")


def _check_meta(meta: dict, run_dir: Path) -> list:
    """The description of a new source, checked; returns its based_on list. Every id in it must be a saved source of
    the run, refused in the words `add-based-on` uses, so no link to a source that does not exist is ever stored."""
    missing = [key for key in _META_KEYS if key not in meta]
    if missing:
        raise ValueError("meta is missing: " + ", ".join(missing))
    based_on = meta.get("based_on") or []
    if not isinstance(based_on, list):
        raise ValueError("based_on must be a list of source ids")
    saved = None
    for source_id in based_on:
        store._check_id("S", source_id)
        saved = store.read_sources(run_dir) if saved is None else saved
        if source_id not in saved:
            raise ValueError(f"source {source_id} does not exist")
    return list(based_on)


# --- network --------------------------------------------------------------

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _next_address(current: str, location: str) -> str:
    """Where a redirect from `current` leads. In this order: a control character in the `Location` is refused; a
    space and non-ASCII bytes are percent-encoded as the standard library's redirect handler did (so a path with a
    space still works; a host with such characters then fails the form check, which is the host rule); the address
    is joined to the current one and its fragment dropped; and the form is checked (`check_url`)."""
    if _CONTROL.search(location):
        raise ValueError("the address must not hold spaces or control characters")
    # The header was read as latin-1; its bytes are judged as the UTF-8 text a server sends. A plain space is encoded
    # below, as before; any other space, separator, control or format character refuses the hop.
    _refuse_invisible(location.encode("iso-8859-1", "replace").decode("utf-8", "surrogateescape").replace(" ", ""))
    encoded = quote(location, encoding="iso-8859-1", safe=string.punctuation)
    target = urldefrag(urljoin(current, encoded))[0]
    check_url(target)
    return target


_DEFAULT_PORTS = {"http": 80, "https": 443}


def _spelling(url: str) -> tuple:
    """An address with the differences that do not name another page taken out: the case of the scheme and of the site
    name, a trailing dot of the site name, the default port, an empty path and the fragment."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    try:
        port = parts.port
    except ValueError:
        port = parts.netloc   # not a usable port: compared as written
    if port == _DEFAULT_PORTS.get(scheme):
        port = None
    return scheme, (parts.hostname or "").rstrip("."), port, parts.path or "/", parts.query


def _read_robots(opener, url: str, address_allowed) -> RobotFileParser | None:
    """The robots rules of the site `url` is on, or None when the file cannot be read (which allows fetching).

    It is fetched one hop at a time, and a hop to a host that does not pass the address check is not requested."""
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        for _ in range(MAX_REDIRECTS + 1):
            if _state(address_allowed(urlsplit(robots_url).hostname)) != PUBLIC:
                return None
            try:
                status, _, raw = _open_once(opener, robots_url, _MAX_ROBOTS_BYTES)
            except _Redirect as hop:
                robots_url = _next_address(robots_url, hop.location)
                continue
            if status != 200:
                return None
            break
        else:
            return None
    except (OSError, http.client.HTTPException, ValueError):
        return None   # no usable robots.txt: fetching is allowed
    parser = RobotFileParser()
    parser.parse(raw[:_MAX_ROBOTS_BYTES].decode("utf-8", errors="replace").splitlines())
    return parser


def _host_key(url: str) -> str:
    """The host name of an address: lower case, without a trailing dot and without the port."""
    return (urlsplit(url).hostname or "").rstrip(".")


def _wait_for_turn(run_dir: Path, host: str, sleep, clock) -> None:
    """Wait until MIN_DELAY_SECONDS have passed since the last page download from `host` (a host name, no port),
    then note now. Keys written by an earlier version held the port; they are simply never matched."""
    path = run_dir / ".last_fetch.json"
    with store.locked(run_dir, ".fetch.lock", wait=None):   # a command saving in parallel waits its turn, unlimited
        try:
            last = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            last = {}
        if not isinstance(last, dict):
            last = {}
        previous = last.get(host)
        if isinstance(previous, (int, float)) and not isinstance(previous, bool):
            wait = min(previous + MIN_DELAY_SECONDS - clock(), MIN_DELAY_SECONDS)
            if wait > 0:
                sleep(wait)
        last[host] = clock()
        path.write_text(json.dumps(last), encoding="utf-8")


def _open_once(opener, url: str, limit: int) -> tuple[int, str | None, bytes]:
    """One request, no redirect followed: (status, content type, up to limit + 1 bytes). A redirect raises _Redirect."""
    with opener.open(url, timeout=TIMEOUT_SECONDS) as response:
        return response.status, response.headers.get("Content-Type"), response.read(limit + 1)


def _download(opener, url: str, max_bytes: int) -> tuple[bytes, str | None]:
    try:
        _, content_type, data = _open_once(opener, url, max_bytes)
    except _Redirect:
        raise
    except urllib.error.HTTPError as exc:
        raise _Refused(f"http_{exc.code}") from exc
    except urllib.error.URLError as exc:
        raise _Refused("timeout" if isinstance(exc.reason, TimeoutError) else "network_error") from exc
    except TimeoutError as exc:
        raise _Refused("timeout") from exc
    except (OSError, http.client.HTTPException, ValueError) as exc:
        raise _Refused("network_error") from exc
    if len(data) > max_bytes:
        raise _Refused("too_large")
    return data, content_type


# --- text -----------------------------------------------------------------

def _text_from_download(data: bytes, content_type: str | None, same_host: bool) -> tuple[str, str]:
    """Return (text, extension of the original) or raise _Refused."""
    kind = sniff_kind(data, content_type)
    if kind == "unknown":
        raise _Refused("unsupported_type")
    if kind == "pdf":
        try:
            text = pdf_to_text(data)
        except NoTextLayer as exc:
            raise _Refused("no_text_layer") from exc
        except ValueError as exc:
            raise _Refused("unreadable_file") from exc
        extension = "pdf"
    else:
        decoded = decode_bytes(data, content_type)
        if kind == "html":
            if not same_host and _PASSWORD_FIELD.search(decoded):
                raise _Refused("login_required")
            text, extension = html_to_text(decoded), "html"
        else:
            text, extension = decoded, "txt"
    if len(text.strip()) < _MIN_TEXT_CHARS:
        raise _Refused("too_little_text")
    return text, extension


def _encode(text: str) -> bytes:
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _Refused("unreadable_file") from exc


# --- records --------------------------------------------------------------

def _write_copies(run_dir: Path, source_id: str, extension: str, original: bytes, text: bytes) -> tuple[str, str]:
    """Write both copy files, or none: a failed write removes what was written."""
    orig_rel, copy_rel = f"copies/{source_id}.orig.{extension}", f"copies/{source_id}.txt"
    written = []
    try:
        for rel, content in ((orig_rel, original), (copy_rel, text)):
            (run_dir / rel).write_bytes(content)
            written.append(run_dir / rel)
    except OSError:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return orig_rel, copy_rel


def _record(run_dir: Path, url: str, meta: dict, based_on: list, *, data_class: str, saved_by: str,
            now: datetime | None, provenance: dict | None, access_reason: str | None = None,
            extension: str | None = None, original: bytes | None = None, text: bytes | None = None,
            final_url: str | None = None) -> dict:
    source_id = store.reserve_id(run_dir, "S")   # claimed before any copy is written under its name
    orig_file = copy_file = copy_sha256 = None
    if access_reason is None:
        try:
            orig_file, copy_file = _write_copies(run_dir, source_id, extension, original, text)
            copy_sha256 = store.sha256_file(run_dir / copy_file)
        except OSError:
            (run_dir / "sources" / f"{source_id}.json").unlink(missing_ok=True)
            raise
    record = {
        "id": source_id,
        "url": url,
        "final_url": final_url,   # where the copy came from, when a redirect led somewhere else than the address asked for
        **{key: meta[key] for key in _META_KEYS},
        "data_class": data_class,
        "saved_at": store._stamp(now),
        "saved_by": saved_by,
        "access": "ok" if access_reason is None else "not_accessible",
        "access_reason": access_reason,
        "copy_file": copy_file,
        "orig_file": orig_file,
        "copy_sha256": copy_sha256,
        "based_on": based_on,
        "provenance": provenance,
    }
    try:
        store.write_source(run_dir, record)
    except BaseException:   # no empty record and no copy stays under the id
        for name in (f"sources/{source_id}.json", orig_file, copy_file):
            if name:
                (run_dir / name).unlink(missing_ok=True)
        raise
    store.record_created(run_dir, "S", source_id)
    return record


# --- public entry points --------------------------------------------------

def save_source(run_dir: Path, url: str, meta: dict, *, sleep=time.sleep, clock=time.time,
                now: datetime | None = None, max_bytes: int = MAX_BYTES, address_allowed=None) -> dict:
    """Download `url` and save it. Redirects are followed here, one hop at a time (at most MAX_REDIRECTS).

    For the first address and for every hop, in this order: the form of the address, then
    `address_allowed(host)` (default: `check_address`, looked up when the call is made; it may answer
    True or False, or one of "public", "private", "unresolved"), then the robots rules of that host (read once
    per save), then the wait for that host. Nothing is requested from a host that fails. `final_url` of the
    record is the address the copy came from when that is a different address than the one asked for (the
    same page under another spelling of the address does not count), else None.
    """
    run_dir = Path(run_dir)
    store.require_run(run_dir)   # before anything else: nothing is asked for, and no lock or note is made elsewhere
    url = first_address(url)
    based_on = _check_meta(meta, run_dir)
    if address_allowed is None:
        address_allowed = check_address
    common = dict(data_class="public", saved_by="program", now=now, provenance=None)
    opener = _opener()
    robots = {}   # the rules of each site, read once for this save
    try:
        current = url
        for hops in range(MAX_REDIRECTS + 1):
            state = _state(address_allowed(urlsplit(current).hostname))
            if state == PRIVATE:
                raise _Refused("private_address")
            if state == UNRESOLVED:
                raise _Refused("network_error")
            site = (urlsplit(current).scheme.lower(), urlsplit(current).netloc.lower())
            if site not in robots:
                robots[site] = _read_robots(opener, current, address_allowed)
            if robots[site] is not None and not robots[site].can_fetch(USER_AGENT, current):
                raise _Refused("robots")
            _wait_for_turn(run_dir, _host_key(current), sleep, clock)
            try:
                data, content_type = _download(opener, current, max_bytes)
                break
            except _Redirect as hop:
                if hops == MAX_REDIRECTS:
                    raise _Refused("too_many_redirects") from None
                try:
                    current = _next_address(current, hop.location)
                except ValueError:
                    raise _Refused("unsupported_type") from None
        final_url = current if hops and _spelling(current) != _spelling(url) else None
        same_host = urlsplit(current).hostname == urlsplit(url).hostname
        text, extension = _text_from_download(data, content_type, same_host)
        encoded = _encode(text)
    except _Refused as refusal:
        return _record(run_dir, url, meta, based_on, access_reason=refusal.reason, **common)
    except PdfAddOnMissing:   # not a fault of the page: nothing is recorded, and the person is told what to do
        raise ValueError(PDF_ADD_ON_MISSING) from None
    return _record(run_dir, url, meta, based_on, extension=extension, original=data, text=encoded,
                   final_url=final_url, **common)


def add_copy(run_dir: Path, file: Path, url: str, meta: dict, *, data_class: str,
             supplied_by: str | None = None, basis: str | None = None,
             now: datetime | None = None) -> dict:
    """Save a file the person saved or exported as a source. `data_class` has no default: a file of the person's own
    (an export from a paid database) must never land in a run as public because nobody said what it is."""
    run_dir, file = Path(run_dir), Path(file)
    store.require_run(run_dir)   # before anything else, as for save-source: nothing is made in another folder
    if data_class not in store.DATA_CLASSES:
        raise ValueError(f"data_class must be one of {', '.join(store.DATA_CLASSES)}")
    if data_class != "public" and store.is_demo_private_run(store.load_run(run_dir)):
        raise store.DemoRunRefused(store.DEMO_RUN_REFUSAL)
    if data_class != "public" and store.load_run(run_dir).get("mode") == "public":
        article = "An" if data_class[0] in "aeiou" else "A"   # an internal source, a licensed source
        raise PermissionError(f"This run is in public mode. {article} {data_class} source can only enter a run "
                              "started in private mode.")
    if data_class != "public" and not store.keeps_out_of_git(run_dir):
        raise store.PrivateRunNotIgnored(store.PRIVATE_NOT_IGNORED)
    based_on = _check_meta(meta, run_dir)
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must say where the document comes from")
    check_copy_address(url)
    provenance = None
    if data_class != "public":
        if not (supplied_by and supplied_by.strip() and basis and basis.strip()):
            raise ValueError("supplied_by and basis are required for a source that is not public")
        provenance = {"supplied_by": supplied_by, "basis": basis}
    extension = file.suffix.lower()
    if extension not in _HAND_EXTENSIONS:
        raise ValueError("the file must be one of: " + ", ".join(_HAND_EXTENSIONS))
    data = file.read_bytes()
    if extension == ".pdf":
        try:
            text = pdf_to_text(data)
        except NoTextLayer as exc:
            raise ValueError("the PDF has no usable text layer (a scan?)") from exc
        except PdfAddOnMissing:
            raise ValueError(PDF_ADD_ON_MISSING) from None
    elif extension in (".html", ".htm"):
        text = html_to_text(decode_bytes(data, None))
        if len(text.strip()) < _MIN_TEXT_CHARS:   # the rule save-source uses: a page a reader sees almost nothing of
            raise ValueError(TOO_LITTLE_TEXT)
    else:  # .txt, and .csv kept as text
        text = decode_bytes(data, None)
    try:
        encoded = _encode(text)
    except _Refused as exc:
        raise ValueError("the text of the file cannot be saved as UTF-8") from exc
    return _record(run_dir, url, meta, based_on, data_class=data_class, saved_by="hand", now=now,
                   provenance=provenance, extension=extension[1:], original=data, text=encoded)
