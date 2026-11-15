"""Quote check, support record and settling a fact's status.

A fact only counts when its quote is found word for word in the saved copy and an
independent checker has confirmed that the quote supports the fact. A fact whose quote is not
found is rejected without that confirmation: there is nothing for the checker to judge.
`expected_status` holds the settling rules as a pure function so the gate can re-run them.
"""
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from . import store
from .quotes import find_quote
from .store import _stamp, read_facts, read_sources, sha256_file, write_fact
from .textnorm import normalise

NOT_PRIMARY_REASON = "single source that is not a primary source"
EARLY_SIGNAL_REASON = "an early signal, not an announcement"


# --- independence ----------------------------------------------------------------

def _lineage(source_id: str, sources: dict[str, dict]) -> set[str]:
    """The source plus everything it is based on, followed through every link.

    Ids that point to no record are kept as members. A `based_on` loop ends because
    every id is visited once.
    """
    seen: set[str] = set()
    todo = [source_id]
    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        based_on = (sources.get(current) or {}).get("based_on")
        if isinstance(based_on, list):
            todo.extend(item for item in based_on if isinstance(item, str))
    return seen


def _publisher_key(source: dict) -> str:
    publisher = source.get("publisher")
    return normalise(publisher).casefold() if isinstance(publisher, str) else ""


# A site name typed without its scheme: proper labels (letters, digits, inner hyphens), at least two, the last of
# letters only and not a file ending, so a file name such as annual-report-2025.pdf is never read as a site.
_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?")
_FILE_ENDINGS = frozenset({"pdf", "htm", "html", "txt", "csv", "json", "xml", "md", "doc", "docx", "xls", "xlsx", "ppt",
                           "pptx", "zip", "png", "jpg", "jpeg", "gif"})


def _is_bare_site(address: str) -> bool:
    """Whether an address typed without its scheme starts with a site name, followed by nothing or by a path."""
    labels = address.partition("/")[0].split(".")
    last = labels[-1]
    return (len(labels) >= 2 and all(_LABEL.fullmatch(label) for label in labels)
            and last.isascii() and last.isalpha() and last.lower() not in _FILE_ENDINGS)


def site_of(address) -> str | None:
    """The site an address names: its site name in lower case, without a trailing dot and without one leading `www.`;
    scheme and port do not count. An address typed without its scheme that starts with a site name, followed by
    nothing or by a path (`www.site-a.example/x`), names the site it would name with `https://` in front.
    None when the address is no web address (an `internal://` address, free words, a file name, a damaged address)."""
    if not isinstance(address, str):
        return None
    if _is_bare_site(address):
        address = "https://" + address
    try:
        parts = urlsplit(address)
        host = parts.hostname
    except ValueError:   # a damaged address written by hand
        return None
    if parts.scheme.lower() not in ("http", "https") or not host:
        return None
    host = _encoded(host.rstrip("."))
    return (host[4:] if host.startswith("www.") else host) or None


def _encoded(host: str) -> str:
    """A site name in one encoded form, however it was written, so a name with letters outside ASCII and its xn-- form
    are one site. An xn-- label is first read back into its letters, so that it goes through the same encoding as the
    name written in letters (Python's codec writes a few letters, such as the sharp s, otherwise than a browser does).
    A name that cannot be read or encoded that way (a broken xn-- label, too long a label, a character no name may
    hold) is compared as written."""
    try:
        labels = [_letters(label) for label in host.split(".")]
        name = ".".join(labels)
        if name.isascii():
            return host
        return name.encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError):
        return host


def _letters(label: str) -> str:
    """An xn-- label in its letters; any other label, or one that holds no letter outside ASCII when read back, as
    written. Raises UnicodeError for an xn-- label that cannot be read back."""
    if label[:4].lower() != "xn--":
        return label
    letters = label[4:].encode("ascii").decode("punycode")
    return letters if not letters.isascii() else label


def _site(source: dict) -> str | None:
    """The site a source's copy was saved from: `site_of` its `final_url` when it has one, else of its `url`."""
    final_url = source.get("final_url")
    return site_of(final_url if isinstance(final_url, str) and final_url else source.get("url"))


def evened_text_digest(text: str) -> str:
    """SHA-256 of a text with its white space evened out: every run of white space one space, the ends trimmed."""
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def copy_texts(run_dir: Path, sources: dict[str, dict]) -> dict[str, str]:
    """For each source with a usable saved copy, `evened_text_digest` of that copy: what `independent` compares."""
    texts = {}
    for source_id, source in sources.items():
        if not (isinstance(source, dict) and isinstance(source.get("copy_file"), str)):
            continue
        try:
            text, _ = _read_copy(run_dir, source)
        except (OSError, ValueError):   # a path that cannot be resolved, written by hand
            continue
        if text is not None:
            texts[source_id] = evened_text_digest(text)
    return texts


def _one_source(source_a_id: str, source_b_id: str, sources: dict[str, dict], texts: dict[str, str] | None) -> bool:
    """Whether two source records are really one source: the same saved copy (by its digest, or by its text with
    the white space evened out when `texts` gives it), or copies saved from the same site."""
    source_a, source_b = sources[source_a_id], sources[source_b_id]
    copy_a, copy_b = source_a.get("copy_sha256"), source_b.get("copy_sha256")
    if isinstance(copy_a, str) and copy_a and copy_a == copy_b:
        return True
    if texts and source_a_id in texts and texts.get(source_a_id) == texts.get(source_b_id):
        return True
    site_a, site_b = _site(source_a), _site(source_b)
    return site_a is not None and site_a == site_b


def independent(source_a_id: str, source_b_id: str, sources: dict[str, dict],
                texts: dict[str, str] | None = None) -> bool:
    """True when the publishers differ, neither source's lineage overlaps the other's, and the two are not one source
    (the same copy or text, or the same site). `texts` is `copy_texts` of the run; without it, copies are compared by
    their stored digest only."""
    source_a, source_b = sources.get(source_a_id), sources.get(source_b_id)
    if source_a is None or source_b is None:
        return False
    if _publisher_key(source_a) == _publisher_key(source_b):
        return False
    if _one_source(source_a_id, source_b_id, sources, texts):
        return False
    return not (_lineage(source_a_id, sources) & _lineage(source_b_id, sources))


# --- reading a fact's references ------------------------------------------------------

def text_id(value) -> str | None:
    """A source id as written, or None when it is not text (a hand-written record; the data check names it)."""
    return value if isinstance(value, str) else None


def supporting_entries(fact: dict) -> list[dict]:
    """The fact's supporting entries, each an object. A `supporting` that is not a list counts as one entry, and an
    entry that is not an object as an entry, with neither source nor quote: its quote is never found. The data check
    names such a record."""
    supporting = fact.get("supporting")
    if not supporting:
        return []
    if not isinstance(supporting, list):
        return [{}]
    return [entry if isinstance(entry, dict) else {} for entry in supporting]


# --- what a support verdict was given for ------------------------------------------

def content_digest(fact: dict) -> str:
    """SHA-256 of what a support verdict was given for.

    That is the statement, quotes, the translation of the main quote, sources and fields the checker judged,
    plus the three judgements that decide how far the fact counts: primary_source, certainty and tentative_reason.
    An early signal is covered too; a fact that is not one hashes exactly as it did before the mark existed. So is the
    language of the quote, when one is set; a fact without one hashes as it did before. So is the translation of a
    supporting quote, by the same rule: an entry without one hashes as it did before.
    """
    content = {
        "statement": fact.get("statement"),
        "quote": fact.get("quote"),
        "quote_translation": fact.get("quote_translation"),
        "source_id": fact.get("source_id"),
        "supporting": [_supporting_content(entry) for entry in supporting_entries(fact)],
        "fields": fact.get("fields"),
        "primary_source": fact.get("primary_source"),
        "certainty": fact.get("certainty"),
        "tentative_reason": fact.get("tentative_reason"),
    }
    if _marked(fact):   # only when set, so the digest of every other fact stays as it was
        content["early_signal"] = True
    if fact.get("quote_language") is not None:   # only when set, by the same rule
        content["quote_language"] = fact["quote_language"]
    text = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _supporting_content(entry: dict) -> dict:
    """What a verdict covers of one supporting entry: its source and quote, and its translation when one is set."""
    content = {"source_id": entry.get("source_id"), "quote": entry.get("quote")}
    if entry.get("quote_translation") is not None:
        content["quote_translation"] = entry["quote_translation"]
    return content


# --- settling ----------------------------------------------------------------------

def _supporting_quotes_passed(fact: dict, checks: dict) -> bool:
    """True when every supporting entry has a quote check that passed; an entry without a check has not."""
    entries = checks.get("supporting") or []
    wanted = fact.get("supporting")
    if isinstance(wanted, list) and len(entries) < len(wanted):
        return False
    return all(isinstance(entry, dict) and entry.get("passed") is True for entry in entries)


def is_withdrawn(fact: dict) -> bool:
    return isinstance(fact.get("withdrawn"), dict)


def _marked(fact: dict) -> bool:
    """Whether the fact carries the early-signal mark. Only a missing key, None or False means unset: `0`, `""` and
    `"yes"` count as set, so a value written by hand (the data check names it) can only lower a fact, never raise it."""
    mark = fact.get("early_signal")
    return not (mark is None or mark is False)


def _is_hint(source_id, sources: dict[str, dict]) -> bool:
    """Whether a source is of a type that only hints at a move (a permit, a job posting, a regulator record)."""
    source = sources.get(source_id) if isinstance(source_id, str) else None
    return isinstance(source, dict) and source.get("type") in store.EARLY_SIGNAL_SOURCE_TYPES


def is_early_signal(fact: dict, sources: dict[str, dict] | None = None) -> bool:
    """Whether a fact is an early signal: marked as one, or taken from a permit, a job posting or a regulator record.

    The one place that decides. The source is looked up in `sources` by the fact's `source_id`, or else read from the
    `source` a report model attaches to each fact; with neither, only the mark counts. Never raises.
    """
    if _marked(fact):
        return True
    source_id = fact.get("source_id")
    source = sources.get(source_id) if sources is not None and isinstance(source_id, str) else None
    if source is None:
        source = fact.get("source")
    return isinstance(source, dict) and source.get("type") in store.EARLY_SIGNAL_SOURCE_TYPES


def expected_status(fact: dict, sources: dict[str, dict],
                    texts: dict[str, str] | None = None) -> tuple[str, str | None]:
    """The status and reason a fact's recorded checks entitle it to. A withdrawn fact is rejected whatever its checks.
    `texts` (`copy_texts` of the run) lets two copies with the same text count as one source."""
    if is_withdrawn(fact):
        return "rejected", "withdrawn"
    checks = fact.get("checks") or {}
    quote, support = checks.get("quote"), checks.get("support")
    if quote is None:
        return "proposed", "checks_incomplete"
    if quote.get("passed") is not True:   # nothing to judge: a quote that is not there needs no support verdict
        return "rejected", quote.get("reason")
    if not _supporting_quotes_passed(fact, checks):
        return "rejected", "supporting_quote_not_found"
    if support is None:
        return "proposed", "checks_incomplete"
    if support.get("content_sha256") != content_digest(fact):
        return "proposed", "support_check_outdated"
    if support.get("passed") is not True:
        return "rejected", "not_supported"
    if fact.get("certainty") == "tentative":
        return "uncertain", fact.get("tentative_reason")
    if is_early_signal(fact, sources):   # a hint, never an announcement: whatever else is true, it is not confirmed
        return "uncertain", EARLY_SIGNAL_REASON
    if fact.get("primary_source") is True:
        return "confirmed", None
    main_id = text_id(fact.get("source_id"))
    for entry in checks.get("supporting") or []:
        if _is_hint(entry.get("source_id"), sources):   # a hint is never the second source that confirms
            continue
        if entry.get("passed") is True and independent(main_id, text_id(entry.get("source_id")), sources, texts):
            return "confirmed", None
    return "uncertain", NOT_PRIMARY_REASON


def needs_settling(fact: dict, sources: dict[str, dict], texts: dict[str, str] | None = None) -> bool:
    """Whether a fact with a settled status (confirmed, uncertain or rejected) holds a status that its stored checks
    no longer give it, by `expected_status`: it was withdrawn, given a new verdict, or a source link changed, and
    `settle` has not run since. A record too broken to judge needs settling too. Never raises."""
    if fact.get("status") not in store.COUNTING + ("rejected",):
        return False
    try:
        expected, _ = expected_status(fact, sources, texts)
    except (AttributeError, TypeError):   # checks or entries of the wrong type, written by hand
        return True
    return expected != fact.get("status")


# --- the quote check -----------------------------------------------------------------

def _read_copy(run_dir: Path, source: dict | None) -> tuple[str | None, str | None]:
    """The saved copy's text and its sha256, or (None, None) when there is no usable copy."""
    if not source or source.get("access") != "ok" or not source.get("copy_file"):
        return None, None
    root = Path(run_dir).resolve()
    path = (root / source["copy_file"]).resolve()
    if not path.is_relative_to(root):
        return None, None
    try:
        return path.read_text(encoding="utf-8"), sha256_file(path)
    except (OSError, ValueError):  # missing, unreadable or not UTF-8 text
        return None, None


def quote_found(quote, text: str) -> bool:
    """Whether `quote` is found in `text`. A quote that is not text (a hand-written record) is a quote not found."""
    return isinstance(quote, str) and find_quote(quote, text).passed


def check_quote(quote, text: str | None) -> dict:
    """The quote check of one quote against the text of its saved copy (None: no usable copy), as `checks` stores it:
    passed, mode and reason. The one rule for check-quotes, settle and the gate: a missing quote is too short, a
    quote that is not text (a hand-written record; the data check names it) is not found."""
    if text is None:
        return {"passed": False, "mode": None, "reason": "no_saved_copy"}
    quote = "" if quote is None else quote   # a missing quote is too short, as it always was
    if not isinstance(quote, str):   # a hand-written record: the data check names it, and it is not found
        return {"passed": False, "mode": None, "reason": "not_found"}
    result = find_quote(quote, text)
    return {"passed": result.passed, "mode": result.mode, "reason": result.reason}


# Every function below that rewrites a fact record holds the run lock (`store.locked`) from its first read to its last
# write, so a command running in parallel cannot overwrite what another one wrote in between. The lock cannot be taken
# twice by one process (a second take waits for ever), so each public function takes it once, at the outermost point,
# and calls only the unlocked helper `_check_quotes` inside.

def _run_lock(run_dir: Path):
    """The run lock, after checking that the folder is a run, so no lock file is ever made in another folder."""
    store.require_run(run_dir)
    return store.locked(run_dir)


def check_quotes(run_dir: Path, now: datetime | None = None) -> dict[str, dict]:
    """Check every fact's quotes against the saved copies; write and return `checks`. Holds the run lock throughout."""
    run_dir = Path(run_dir)
    with _run_lock(run_dir):
        return _check_quotes(run_dir, now)


def _check_quotes(run_dir: Path, now: datetime | None = None) -> dict[str, dict]:
    """`check_quotes` without taking the lock: the caller holds it."""
    sources = read_sources(run_dir)
    stamp = _stamp(now)
    results = {}
    for fact_id, fact in read_facts(run_dir).items():
        text, digest = _read_copy(run_dir, sources.get(text_id(fact.get("source_id"))))
        quote = check_quote(fact.get("quote"), text)
        quote.update(checked_at=stamp, copy_sha256=digest)
        supporting = []
        for entry in supporting_entries(fact):   # a damaged reference names no source: no copy, so not found
            entry_id = text_id(entry.get("source_id"))
            support_text, _ = _read_copy(run_dir, sources.get(entry_id))
            supporting.append({"source_id": entry_id, **check_quote(entry.get("quote"), support_text)})
        checks = fact.get("checks") or {}
        checks.update(quote=quote, supporting=supporting)
        checks.setdefault("support", None)
        fact["checks"] = checks
        write_fact(run_dir, fact)
        results[fact_id] = checks
    return results


EMPTY_BY = "Say who gave the verdict: --by must not be empty."
EMPTY_REJECTION_NOTE = ("A verdict that the quote does not support the fact needs a note. "
                        "Say in a sentence why, so the reader sees the reason.")


def record_support(run_dir: Path, fact_id: str, passed: bool, by: str, note: str,
                   now: datetime | None = None) -> None:
    """Record the independent checker's verdict on whether the quote supports the fact. Holds the run lock.

    Refused (ValueError), before anything is written: a verdict that names nobody, and a rejection without a note,
    because the report shows a rejected fact with the checker's reason."""
    if not (isinstance(by, str) and by.strip()):
        raise ValueError(EMPTY_BY)
    if not passed and not (isinstance(note, str) and note.strip()):
        raise ValueError(EMPTY_REJECTION_NOTE)
    with _run_lock(run_dir):
        fact = read_facts(Path(run_dir)).get(fact_id)
        if fact is None:
            raise ValueError(f"unknown fact id: {fact_id}")
        checks = fact.get("checks") or {}
        checks.setdefault("quote", None)
        checks.setdefault("supporting", [])
        checks["support"] = {"passed": bool(passed), "by": by, "note": note, "at": _stamp(now),
                             "content_sha256": content_digest(fact)}
        fact["checks"] = checks
        write_fact(Path(run_dir), fact)


def withdraw_fact(run_dir: Path, fact_id: str, reason: str, now: datetime | None = None) -> None:
    """Mark a fact as withdrawn by the analyst, with the reason. Nothing is deleted; the next settle rejects it.

    The withdrawal is not part of the content digest: withdrawing is not an edit that needs a new support check.
    Holds the run lock.
    """
    if not (isinstance(reason, str) and reason.strip()):
        raise ValueError("give a reason for withdrawing the fact")
    with _run_lock(run_dir):
        fact = read_facts(Path(run_dir)).get(fact_id)
        if fact is None:
            raise ValueError(f"unknown fact id: {fact_id}")
        fact["withdrawn"] = {"reason": reason, "at": _stamp(now)}
        write_fact(Path(run_dir), fact)


def settle(run_dir: Path) -> dict[str, str]:
    """Re-check every quote, then write `status` and `status_reason` into every fact.

    Returns `{fact_id: status}`. Quotes are re-checked first so a stored quote check is never stale. Holds the run
    lock from the first quote check to the last status, so nothing written in parallel is lost or settled half-way.
    """
    run_dir = Path(run_dir)
    with _run_lock(run_dir):
        _check_quotes(run_dir)
        sources = read_sources(run_dir)
        texts = copy_texts(run_dir, sources)
        statuses = {}
        for fact_id, fact in read_facts(run_dir).items():
            fact["status"], fact["status_reason"] = expected_status(fact, sources, texts)
            write_fact(run_dir, fact)
            statuses[fact_id] = fact["status"]
    return statuses
