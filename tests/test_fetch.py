import contextlib
import ipaddress
import json
import socket
import ssl
import threading
import time
import urllib.error
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import radar
from radar import cli, extract_text, fetch, schema, store
from radar.report import model
from radar.status import run_status
from helpers import add_source, make_run, make_pdf

META = {"publisher": "Competitor A", "title": "Expansion", "date": "2026-05-14",
        "type": "company_release", "speaker": "the company", "interest": "wants to look strong",
        "language": "en"}
# An ordinary article page: more than 800 characters of running text, so it is saved without a note (Task 10, change F)
BODY = "<html><body><p>" + "The expansion adds two high-speed syringe lines. " * 17 + "</p></body></html>"

OWN = {"supplied_by": "the tester", "basis": "own company document"}


def no_sleep(_):
    pass


def save(run, url, meta=None, **kw):
    """save_source with the address check opened up: the test server lives on 127.0.0.1."""
    kw.setdefault("sleep", no_sleep)
    kw.setdefault("address_allowed", lambda host: True)
    return fetch.save_source(run, url, META if meta is None else meta, **kw)


def saved_copies(run):
    """The files in copies/, without the .gitignore every run folder has there."""
    return [path for path in (run / "copies").iterdir() if path.name != ".gitignore"]


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    # the tests talk to 127.0.0.1 only; a proxy from the environment must not get in the way
    for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


@contextlib.contextmanager
def _serve():
    """A local test server on 127.0.0.1 serving `routes`: path -> (status, headers, body).

    Keys starting with an underscore are bookkeeping: _seen_paths and _seen_user_agents record
    every request except /robots.txt, which _seen_robots records. Unknown paths answer 404.
    """
    routes = {"_seen_paths": [], "_seen_user_agents": [], "_seen_robots": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/robots.txt":
                routes["_seen_robots"].append(path)
            else:
                routes["_seen_paths"].append(path)
                routes["_seen_user_agents"].append(self.headers.get("User-Agent"))
            status, headers, body = routes.get(path, (404, {}, b"not found"))
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", routes
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def site():
    with _serve() as served:
        yield served


@pytest.fixture
def two_sites():
    with _serve() as first, _serve() as second:
        yield first, second


def test_saves_html_page(tmp_path, site):
    base, routes = site
    routes["/news"] = (200, {"Content-Type": "text/html; charset=utf-8"}, BODY.encode())
    run = make_run(tmp_path)
    rec = save(run, base + "/news")
    assert (rec["id"], rec["access"], rec["saved_by"]) == ("S1", "ok", "program")
    text = (run / rec["copy_file"]).read_text(encoding="utf-8")
    assert "adds two high-speed syringe lines" in text and "<p>" not in text
    assert rec["copy_sha256"] == store.sha256_file(run / rec["copy_file"])
    assert (run / rec["orig_file"]).read_bytes() == BODY.encode()
    assert store.read_sources(run)["S1"] == rec


def test_saved_copy_is_exactly_what_the_extraction_returns(tmp_path, site):
    base, routes = site
    page = "<html><body><p>Größe „Fülllinie“ " + "wächst stark. " * 20 + "</p></body></html>"
    routes["/de"] = (200, {"Content-Type": "text/html; charset=utf-8"}, page.encode())
    run = make_run(tmp_path)
    rec = save(run, base + "/de")
    expected = extract_text.html_to_text(page)
    assert (run / rec["copy_file"]).read_bytes() == expected.encode("utf-8")


def test_record_has_every_key_of_the_format(tmp_path, site):
    base, routes = site
    routes["/news"] = (200, {"Content-Type": "text/html"}, BODY.encode())
    run = make_run(tmp_path)
    add_source(run, "An earlier release that the page repeats.")
    rec = save(run, base + "/news", {**META, "based_on": ["S1"]})
    assert set(rec) == {"id", "url", "publisher", "title", "date", "type", "speaker", "interest",
                        "language", "data_class", "saved_at", "saved_by", "access", "access_reason",
                        "copy_file", "orig_file", "copy_sha256", "based_on", "provenance", "final_url"}
    assert rec["data_class"] == "public" and rec["provenance"] is None
    assert rec["based_on"] == ["S1"] and rec["url"] == base + "/news" and rec["final_url"] is None


def test_saves_pdf(tmp_path, site):
    base, routes = site
    routes["/ar.pdf"] = (200, {"Content-Type": "application/pdf"},
                         make_pdf(["Annual report 2025. " * 3, "Capacity will double by 2028. " * 5]))
    rec = save(make_run(tmp_path), base + "/ar.pdf")
    assert rec["access"] == "ok" and rec["orig_file"].endswith(".orig.pdf")


def test_sends_plain_user_agent(tmp_path, site):
    base, routes = site
    routes["/news"] = (200, {"Content-Type": "text/html"}, BODY.encode())
    save(make_run(tmp_path), base + "/news")
    assert routes["_seen_user_agents"][-1] == "strategy-radar/" + radar.__version__


@pytest.mark.parametrize("route, expected", [
    ((403, {}, b"forbidden"), "http_403"),
    ((404, {}, b"gone"), "http_404"),
    ((200, {"Content-Type": "application/zip"}, b"\x00\x01"), "unsupported_type"),
    ((200, {"Content-Type": "text/html"}, b"<html><body>short</body></html>"), "too_little_text"),
    ((200, {"Content-Type": "application/pdf"}, b"%PDF-1.4 this is not a pdf"), "unreadable_file"),
    ((200, {"Content-Type": "application/pdf"}, make_pdf(["x"])), "no_text_layer"),
])
def test_failures_are_recorded_without_copies(tmp_path, site, route, expected):
    base, routes = site
    routes["/x"] = route
    run = make_run(tmp_path)
    rec = save(run, base + "/x")
    assert (rec["access"], rec["access_reason"]) == ("not_accessible", expected)
    assert rec["copy_file"] is None and saved_copies(run) == []
    assert (rec["orig_file"], rec["copy_sha256"]) == (None, None)
    assert store.read_sources(run)["S1"]["access_reason"] == expected


def test_too_large_is_refused(tmp_path, site):
    base, routes = site
    routes["/big"] = (200, {"Content-Type": "text/html"}, BODY.encode() * 50)
    run = make_run(tmp_path)
    rec = save(run, base + "/big", max_bytes=1000)
    assert rec["access_reason"] == "too_large" and saved_copies(run) == []


def test_exactly_max_bytes_is_accepted(tmp_path, site):
    base, routes = site
    routes["/n"] = (200, {"Content-Type": "text/html"}, BODY.encode())
    rec = save(make_run(tmp_path), base + "/n", max_bytes=len(BODY.encode()))
    assert rec["access"] == "ok"


def test_robots_disallow_is_respected(tmp_path, site):
    base, routes = site
    routes["/robots.txt"] = (200, {"Content-Type": "text/plain"}, b"User-agent: *\nDisallow: /private/\n")
    routes["/private/doc"] = (200, {"Content-Type": "text/html"}, BODY.encode())
    rec = save(make_run(tmp_path), base + "/private/doc")
    assert rec["access_reason"] == "robots" and "/private/doc" not in routes["_seen_paths"]


def test_robots_rule_for_this_agent_is_respected(tmp_path, site):
    base, routes = site
    routes["/robots.txt"] = (200, {"Content-Type": "text/plain"},
                             b"User-agent: strategy-radar\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
    routes["/news"] = (200, {"Content-Type": "text/html"}, BODY.encode())
    rec = save(make_run(tmp_path), base + "/news")
    assert rec["access_reason"] == "robots" and routes["_seen_paths"] == []


def test_robots_allow_lets_the_page_through(tmp_path, site):
    base, routes = site
    routes["/robots.txt"] = (200, {"Content-Type": "text/plain"}, b"User-agent: *\nDisallow: /private/\n")
    routes["/news"] = (200, {"Content-Type": "text/html"}, BODY.encode())
    assert save(make_run(tmp_path), base + "/news")["access"] == "ok"


def test_unreadable_robots_file_allows_fetching(tmp_path, site):
    base, routes = site
    routes["/robots.txt"] = (500, {}, b"oops")
    routes["/news"] = (200, {"Content-Type": "text/html"}, BODY.encode())
    assert save(make_run(tmp_path), base + "/news")["access"] == "ok"


def test_waits_between_requests_to_one_host(tmp_path, site):
    base, routes = site
    routes["/a"] = routes["/b"] = (200, {"Content-Type": "text/html"}, BODY.encode())
    run = make_run(tmp_path)
    waits = []
    t = [1000.0]
    save(run, base + "/a", META, sleep=waits.append, clock=lambda: t[0])
    assert waits == []
    t[0] = 1000.5
    save(run, base + "/b", META, sleep=waits.append, clock=lambda: t[0])
    assert waits and waits[-1] == pytest.approx(1.5)


def test_no_wait_when_enough_time_has_passed(tmp_path, site):
    base, routes = site
    routes["/a"] = routes["/b"] = (200, {"Content-Type": "text/html"}, BODY.encode())
    run = make_run(tmp_path)
    waits = []
    t = [1000.0]
    save(run, base + "/a", META, sleep=waits.append, clock=lambda: t[0])
    t[0] = 1002.5
    save(run, base + "/b", META, sleep=waits.append, clock=lambda: t[0])
    assert waits == []
    assert json.loads((run / ".last_fetch.json").read_text(encoding="utf-8")) == \
        {"127.0.0.1": 1002.5}


def test_a_broken_delay_file_is_ignored(tmp_path, site):
    base, routes = site
    routes["/a"] = (200, {"Content-Type": "text/html"}, BODY.encode())
    run = make_run(tmp_path)
    (run / ".last_fetch.json").write_text("not json", encoding="utf-8")
    assert save(run, base + "/a")["access"] == "ok"


def test_redirect_to_login_on_another_host(tmp_path, site):
    base, routes = site
    other = base.replace("127.0.0.1", "localhost")
    routes["/gated"] = (302, {"Location": other + "/login"}, b"")
    routes["/login"] = (200, {"Content-Type": "text/html"},
                        ("<html><body><form><input type='password'></form><p>" + "Please sign in. " * 20 + "</p></body></html>").encode())
    rec = save(make_run(tmp_path), base + "/gated")
    assert rec["access_reason"] == "login_required" and rec["copy_file"] is None


def test_password_field_on_the_same_host_is_not_a_login_wall(tmp_path, site):
    base, routes = site
    routes["/page"] = (200, {"Content-Type": "text/html"},
                       ("<html><body><form><input type='password'></form><p>" + "Plain text here. " * 20 + "</p></body></html>").encode())
    assert save(make_run(tmp_path), base + "/page")["access"] == "ok"


def test_redirect_to_another_scheme_is_refused(tmp_path, site):
    base, routes = site
    routes["/go"] = (302, {"Location": "file:///etc/passwd"}, b"")
    run = make_run(tmp_path)
    rec = save(run, base + "/go")
    assert rec["access_reason"] == "unsupported_type" and saved_copies(run) == []


def test_redirect_within_http_is_followed(tmp_path, site):
    base, routes = site
    routes["/old"] = (301, {"Location": "/new"}, b"")
    routes["/new"] = (200, {"Content-Type": "text/html"}, BODY.encode())
    assert save(make_run(tmp_path), base + "/old")["access"] == "ok"


def test_unreachable_host_is_network_error(tmp_path):
    rec = save(make_run(tmp_path), "http://127.0.0.1:9/none")
    assert rec["access_reason"] == "network_error"


class _FakeContext:
    def __init__(self, cas):
        self.cas, self.loaded = cas, []

    def cert_store_stats(self):
        return {"x509_ca": self.cas}

    def load_verify_locations(self, **kwargs):
        self.loaded.append(kwargs)


@pytest.mark.parametrize("cas, file_exists, loaded", [(0, True, True), (5, True, False), (0, False, False)])
def test_an_empty_store_falls_back_to_the_system_file(tmp_path, monkeypatch, cas, file_exists, loaded):
    fake = _FakeContext(cas)
    monkeypatch.setattr(ssl, "create_default_context", lambda *a, **k: fake)
    system_file = tmp_path / "cert.pem"
    if file_exists:
        system_file.write_text("x")
    assert fetch.ssl_context(str(system_file)) is fake
    assert fake.loaded == ([{"cafile": str(system_file)}] if loaded else [])


def test_a_failed_certificate_check_is_named(tmp_path, monkeypatch):
    class Opener:
        def open(self, url, timeout=None):
            raise urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed"))

    monkeypatch.setattr(fetch, "_opener", Opener)
    rec = save(make_run(tmp_path), "http://example.com/")
    assert (rec["access"], rec["access_reason"]) == ("not_accessible", "certificate_failed")


def test_silent_server_is_a_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(fetch, "ROBOTS_TIMEOUT_SECONDS", 0.3)   # the robots file is asked for first, with its own limit
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)  # accepts connections into the backlog, never answers
    try:
        url = f"http://127.0.0.1:{listener.getsockname()[1]}/slow"
        rec = save(make_run(tmp_path), url)
    finally:
        listener.close()
    assert rec["access_reason"] == "timeout"


def test_only_http_urls(tmp_path):
    run = make_run(tmp_path)
    with pytest.raises(ValueError):
        save(run, "file:///etc/passwd")
    assert store.read_sources(run) == {}


def test_missing_meta_key_is_refused(tmp_path):
    meta = {k: v for k, v in META.items() if k != "speaker"}
    with pytest.raises(ValueError, match="speaker"):
        save(make_run(tmp_path), "http://127.0.0.1:9/x", meta)


def test_private_file_needs_private_mode(tmp_path):
    page = tmp_path / "review.txt"
    page.write_text("Internal capacity review. " * 20, encoding="utf-8")
    with pytest.raises(PermissionError):
        fetch.add_copy(make_run(tmp_path / "a"), page, "internal capacity review, Q3", META, data_class="internal", **OWN)
    private_run = make_run(tmp_path / "b", mode="private", acknowledged=True)
    rec = fetch.add_copy(private_run, page, "internal capacity review, Q3", META, data_class="internal", **OWN)
    assert (rec["data_class"], rec["saved_by"], rec["url"]) == ("internal", "hand", "internal capacity review, Q3")
    assert rec["provenance"] == {"supplied_by": "the tester", "basis": "own company document"}
    with pytest.raises(ValueError):
        fetch.add_copy(private_run, page, "internal capacity review, Q3", META, data_class="internal")


def test_export_file_as_csv(tmp_path):
    table = tmp_path / "export.csv"
    table.write_text("company,site,lines\n" + "Competitor A,Site X,2\n" * 20, encoding="utf-8")
    run = make_run(tmp_path, mode="private", acknowledged=True)
    rec = fetch.add_copy(run, table, "export from a licensed database, 12 Nov 2026", META, data_class="licensed",
                         supplied_by="the tester", basis="company subscription")
    assert rec["data_class"] == "licensed"
    assert "Competitor A,Site X,2" in (run / rec["copy_file"]).read_text(encoding="utf-8")
    assert (run / rec["orig_file"]).read_bytes() == table.read_bytes()


def test_add_copy_by_hand(tmp_path):
    run = make_run(tmp_path)
    page = tmp_path / "saved.html"
    page.write_text(BODY, encoding="utf-8")
    rec = fetch.add_copy(run, page, "https://example.com/news", META, data_class="public")
    assert (rec["saved_by"], rec["access"]) == ("hand", "ok")
    assert (rec["data_class"], rec["provenance"]) == ("public", None)
    assert (run / rec["copy_file"]).read_text(encoding="utf-8") == extract_text.html_to_text(BODY)
    assert rec["copy_sha256"] == store.sha256_file(run / rec["copy_file"])
    assert store.read_sources(run)["S1"] == rec
    with pytest.raises(ValueError):
        fetch.add_copy(run, tmp_path / "notes.docx", "https://example.com/x", META, data_class="public")


def test_add_copy_refuses_unreadable_pdfs_and_leaves_nothing(tmp_path):
    run = make_run(tmp_path)
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 nothing")
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(make_pdf(["x"]))
    for path in (broken, scan):
        with pytest.raises(ValueError):
            fetch.add_copy(run, path, "https://example.com/x", META, data_class="public")
    assert saved_copies(run) == [] and store.read_sources(run) == {}


def test_add_copy_reads_a_text_pdf(tmp_path):
    run = make_run(tmp_path)
    pdf = tmp_path / "ar.pdf"
    pdf.write_bytes(make_pdf(["Annual report 2025. " * 3, "Capacity will double by 2028. " * 5]))
    rec = fetch.add_copy(run, pdf, "https://example.com/ar.pdf", META, data_class="public")
    assert rec["orig_file"].endswith(".orig.pdf")
    assert "Capacity will double by 2028." in (run / rec["copy_file"]).read_text(encoding="utf-8")


# --- the commands ---------------------------------------------------------

def _meta_args():
    return ["--publisher", "Competitor A", "--title", "Expansion", "--date", "2026-05-14",
            "--type", "company_release", "--speaker", "the company",
            "--interest", "wants to look strong", "--language", "en"]


def test_cli_save_source_prints_the_record_and_exits_0_even_when_not_accessible(tmp_path, site, capsys, monkeypatch):
    monkeypatch.setattr(fetch, "MIN_DELAY_SECONDS", 0)  # the CLI uses the real clock and sleep
    monkeypatch.setattr(fetch, "check_address", lambda host: "public")  # the test server lives on 127.0.0.1
    base, routes = site
    routes["/news"] = (200, {"Content-Type": "text/html"}, BODY.encode())
    run = make_run(tmp_path)
    add_source(run, "An earlier release."); add_source(run, "Another earlier release.")
    code = cli.main(["save-source", "--run", str(run), "--url", base + "/news", "--based-on", "S1,S2",
                     *_meta_args()])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["access"] == "ok" and out["based_on"] == ["S1", "S2"]
    code = cli.main(["save-source", "--run", str(run), "--url", base + "/missing", *_meta_args()])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["access_reason"] == "http_404"


def test_cli_save_source_rejects_other_schemes(tmp_path, capsys):
    code = cli.main(["save-source", "--run", str(make_run(tmp_path)), "--url", "ftp://example.com/x",
                     *_meta_args()])
    assert code == 2 and "error" in json.loads(capsys.readouterr().out)


def test_cli_add_copy(tmp_path, capsys):
    page = tmp_path / "review.txt"
    page.write_text("Internal capacity review. " * 20, encoding="utf-8")
    args = ["add-copy", "--file", str(page), "--url", "internal review", "--data-class", "internal",
            "--supplied-by", "the tester", "--basis", "own document", *_meta_args()]
    public = make_run(tmp_path / "a")
    assert cli.main(args + ["--run", str(public)]) == 2
    assert "error" in json.loads(capsys.readouterr().out)
    private = make_run(tmp_path / "b", mode="private", acknowledged=True)
    assert cli.main(args + ["--run", str(private)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert (out["data_class"], out["saved_by"]) == ("internal", "hand")
    assert out["provenance"] == {"supplied_by": "the tester", "basis": "own document"}




# --- Task 8: addresses inside a private network, and the manners on every hop -----------------

def _answers(*addresses):
    """A fake resolver that answers with the given address texts."""
    return lambda *a, **k: [(None, None, None, "", (address, 0)) for address in addresses]


def _html(body=BODY):
    return (200, {"Content-Type": "text/html"}, body.encode())


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "fe80::1", "0.0.0.0",
    "::ffff:127.0.0.1", "::ffff:10.0.0.5", "100.64.0.1", "224.0.0.1", "240.0.0.1", "::", "fc00::1"])
def test_addresses_inside_a_private_network_are_not_public(address):
    assert fetch.public_address("intranet.example", resolve=_answers(address)) is False


def test_an_ordinary_address_is_public():
    assert fetch.public_address("www.example", resolve=_answers("8.8.8.8")) is True
    assert fetch.public_address("www.example", resolve=_answers("::ffff:8.8.8.8")) is True


def test_a_host_that_does_not_resolve_is_not_public():
    def broken(*args, **kwargs):
        raise socket.gaierror("no such host")

    assert fetch.public_address("nowhere.example", resolve=broken) is False


def test_a_host_with_one_public_and_one_private_address_is_not_public():
    assert fetch.public_address("mixed.example", resolve=_answers("8.8.8.8", "10.0.0.5")) is False
    assert fetch.public_address("mixed.example", resolve=_answers("10.0.0.5", "8.8.8.8")) is False


def test_a_host_that_resolves_to_nothing_is_not_public():
    assert fetch.public_address("empty.example", resolve=_answers()) is False


@pytest.mark.parametrize("text", ["not an address", "", "999.1.1.1", None])
def test_an_answer_that_cannot_be_read_is_not_public(text):
    assert fetch.public_address("odd.example", resolve=_answers(text)) is False


@pytest.mark.parametrize("answer", [[(None, None, None, "", ())], [object()], [None]])
def test_an_answer_of_the_wrong_shape_is_not_public(answer):
    assert fetch.public_address("odd.example", resolve=lambda *a, **k: answer) is False


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "2130706433", "::1"])
def test_the_real_resolver_refuses_the_machine_itself(host):
    assert fetch.public_address(host) is False


def test_a_private_address_is_recorded_as_not_accessible_and_never_opened(tmp_path, site):
    base, routes = site
    routes["/news"] = _html()
    run = make_run(tmp_path)
    rec = fetch.save_source(run, base + "/news", META, sleep=no_sleep)   # the real check
    assert (rec["access"], rec["access_reason"]) == ("not_accessible", "private_address")
    assert routes["_seen_paths"] == [] and routes["_seen_robots"] == []
    assert rec["url"] == base + "/news" and saved_copies(run) == []


def test_the_address_is_checked_after_its_form_and_before_anything_else(tmp_path):
    asked = []

    def refuse(host):
        asked.append(host)
        return False

    run = make_run(tmp_path)
    with pytest.raises(ValueError):
        save(run, "ftp://example.test/x", address_allowed=refuse)
    with pytest.raises(ValueError):
        save(run, "http://user:pw@example.test/x", address_allowed=refuse)
    assert asked == []
    rec = save(run, "http://[::1]:9/x", address_allowed=refuse)
    assert rec["access_reason"] == "private_address" and asked == ["::1"]


def test_a_redirect_into_a_private_network_is_refused(tmp_path, site):
    base, routes = site
    routes["/a"] = (302, {"Location": base.replace("127.0.0.1", "localhost") + "/b"}, b"")
    routes["/b"] = _html()
    rec = save(make_run(tmp_path), base + "/a", address_allowed=lambda host: host == "127.0.0.1")
    assert rec["access_reason"] == "private_address" and routes["_seen_paths"] == ["/a"]
    assert routes["_seen_robots"] == ["/robots.txt"]   # the first host only: nothing at all went to the refused one


def test_a_redirect_target_that_robots_forbids_is_refused(tmp_path, two_sites):
    (base_a, routes_a), (base_b, routes_b) = two_sites
    routes_a["/a"] = (302, {"Location": base_b + "/private/doc"}, b"")
    routes_b["/robots.txt"] = (200, {"Content-Type": "text/plain"}, b"User-agent: *\nDisallow: /private/\n")
    routes_b["/private/doc"] = _html()
    rec = save(make_run(tmp_path), base_a + "/a")
    assert rec["access_reason"] == "robots" and routes_b["_seen_paths"] == []
    assert routes_b["_seen_robots"] == ["/robots.txt"]


def test_the_wait_is_kept_on_the_redirect_target_host(tmp_path, two_sites):
    (base_a, routes_a), (base_b, routes_b) = two_sites
    base_b = base_b.replace("127.0.0.1", "localhost")   # a second host name for the second server
    routes_a["/go"] = (302, {"Location": base_b + "/page"}, b"")
    routes_b["/page"] = _html()
    run = make_run(tmp_path)
    waits = []
    assert save(run, base_b + "/page", sleep=waits.append, clock=lambda: 1000.0)["access"] == "ok"
    assert waits == []
    assert save(run, base_a + "/go", sleep=waits.append, clock=lambda: 1000.5)["access"] == "ok"
    assert waits == [pytest.approx(1.5)]   # nothing for A (first visit), the rest of the two seconds for B
    assert routes_b["_seen_paths"] == ["/page", "/page"]
    notes = json.loads((run / ".last_fetch.json").read_text(encoding="utf-8"))
    assert set(notes) == {"127.0.0.1", "localhost"}   # kept per host name, without the port


def test_the_wait_is_shared_by_one_host_on_two_ports(tmp_path, two_sites):
    (base_a, routes_a), (base_b, routes_b) = two_sites
    routes_a["/page"] = routes_b["/page"] = _html()
    run = make_run(tmp_path)
    waits = []
    save(run, base_a + "/page", sleep=waits.append, clock=lambda: 1000.0)
    save(run, base_b + "/page", sleep=waits.append, clock=lambda: 1000.5)
    assert waits == [pytest.approx(1.5)]


def test_the_wait_is_kept_per_host_name_in_lower_case_without_a_trailing_dot(tmp_path, site):
    base, routes = site
    routes["/page"] = _html()
    run = make_run(tmp_path)
    waits = []
    save(run, base.replace("127.0.0.1", "LocalHost.") + "/page", sleep=waits.append, clock=lambda: 1000.0)
    save(run, base.replace("127.0.0.1", "localhost") + "/page", sleep=waits.append, clock=lambda: 1000.5)
    assert waits == [pytest.approx(1.5)]
    assert set(json.loads((run / ".last_fetch.json").read_text(encoding="utf-8"))) == {"localhost"}


def test_a_wait_file_from_an_earlier_version_with_ports_in_its_keys_does_no_harm(tmp_path, site):
    base, routes = site
    routes["/page"] = _html()
    run = make_run(tmp_path)
    (run / ".last_fetch.json").write_text(json.dumps({base.split("//")[1]: 1000.0}), encoding="utf-8")
    waits = []
    assert save(run, base + "/page", sleep=waits.append, clock=lambda: 1000.5)["access"] == "ok"
    assert waits == []   # the old key is simply not matched
    assert json.loads((run / ".last_fetch.json").read_text(encoding="utf-8"))["127.0.0.1"] == 1000.5


def _chain(routes, hops):
    """/r0 redirects to /r1 and so on; /r<hops> is the page. A chain of `hops` redirects."""
    for number in range(hops):
        routes[f"/r{number}"] = (302, {"Location": f"/r{number + 1}"}, b"")
    routes[f"/r{hops}"] = _html()


def test_five_redirects_are_followed_and_six_are_not(tmp_path, site):
    base, routes = site
    _chain(routes, 5)
    assert save(make_run(tmp_path / "a"), base + "/r0")["access"] == "ok"
    routes["_seen_paths"].clear()
    _chain(routes, 6)
    rec = save(make_run(tmp_path / "b"), base + "/r0")
    assert (rec["access"], rec["access_reason"]) == ("not_accessible", "too_many_redirects")
    assert routes["_seen_paths"] == [f"/r{number}" for number in range(6)]   # the sixth answer is not followed


def test_a_redirect_loop_ends_as_too_many_redirects(tmp_path, site):
    base, routes = site
    routes["/a"] = (302, {"Location": "/b"}, b"")
    routes["/b"] = (302, {"Location": "/a"}, b"")
    rec = save(make_run(tmp_path), base + "/a")
    assert rec["access_reason"] == "too_many_redirects" and len(routes["_seen_paths"]) == 6


def test_a_loop_through_two_hosts_ends_too(tmp_path, two_sites):
    (base_a, routes_a), (base_b, routes_b) = two_sites
    routes_a["/a"] = (301, {"Location": base_b + "/b"}, b"")
    routes_b["/b"] = (301, {"Location": base_a + "/a"}, b"")
    assert save(make_run(tmp_path), base_a + "/a")["access_reason"] == "too_many_redirects"


@pytest.mark.parametrize("location", ["new", "/new", "./new", "/new#part", "../new"])
def test_relative_locations_and_fragments_are_followed(tmp_path, site, location):
    base, routes = site
    routes["/old"] = (302, {"Location": location}, b"")
    routes["/new"] = _html()
    assert save(make_run(tmp_path), base + "/old")["access"] == "ok"
    assert routes["_seen_paths"] == ["/old", "/new"]


@pytest.mark.parametrize("headers", [{}, {"Location": ""}, {"Location": "   "}])
def test_a_redirect_without_a_place_to_go_is_a_refusal_by_the_site(tmp_path, site, headers):
    base, routes = site
    routes["/old"] = (302, headers, b"")
    rec = save(make_run(tmp_path), base + "/old")
    assert (rec["access"], rec["access_reason"]) == ("not_accessible", "http_302")


@pytest.mark.parametrize("location", ["ftp://example.test/x", "http://user:pw@127.0.0.1:9/x", "mailto:a@example.test"])
def test_a_redirect_to_a_bad_address_form_ends_as_an_unsupported_type(tmp_path, site, location):
    base, routes = site
    routes["/old"] = (302, {"Location": location}, b"")
    assert save(make_run(tmp_path), base + "/old")["access_reason"] == "unsupported_type"


def test_a_robots_file_that_redirects_to_a_refused_host_is_not_followed(tmp_path, two_sites):
    (base_a, routes_a), (base_b, routes_b) = two_sites
    other = base_b.replace("127.0.0.1", "localhost")
    routes_a["/robots.txt"] = (302, {"Location": other + "/robots.txt"}, b"")
    routes_a["/news"] = _html()
    routes_b["/robots.txt"] = (200, {"Content-Type": "text/plain"}, b"User-agent: *\nDisallow: /\n")
    rec = save(make_run(tmp_path), base_a + "/news", address_allowed=lambda host: host != "localhost")
    assert routes_b["_seen_robots"] == [] and routes_b["_seen_paths"] == []   # no request went to the second server
    assert rec["access"] == "ok"   # a robots file that cannot be read allows fetching, as before


def test_a_robots_file_that_redirects_to_an_allowed_host_is_followed(tmp_path, two_sites):
    (base_a, routes_a), (base_b, routes_b) = two_sites
    routes_a["/robots.txt"] = (302, {"Location": base_b + "/robots.txt"}, b"")
    routes_a["/news"] = _html()
    routes_b["/robots.txt"] = (200, {"Content-Type": "text/plain"}, b"User-agent: *\nDisallow: /\n")
    assert save(make_run(tmp_path), base_a + "/news")["access_reason"] == "robots"
    assert routes_a["_seen_paths"] == []


def test_a_robots_redirect_loop_does_not_hang_and_allows_fetching(tmp_path, site):
    base, routes = site
    routes["/robots.txt"] = (302, {"Location": "/robots.txt"}, b"")
    routes["/news"] = _html()
    assert save(make_run(tmp_path), base + "/news")["access"] == "ok"
    assert len(routes["_seen_robots"]) == 6


def test_a_name_that_resolves_to_a_private_address_is_never_asked_for_robots_or_a_page(tmp_path, site):
    base, routes = site
    routes["/robots.txt"] = (200, {}, b"User-agent: *\nDisallow:\n")
    routes["/news"] = _html()
    seen = []

    def resolve(host, port, *args, **kwargs):
        seen.append(host)
        return [(None, None, None, "", ("10.1.2.3", 0))]

    rec = save(make_run(tmp_path), base + "/news", address_allowed=lambda host: fetch.public_address(host, resolve))
    assert rec["access_reason"] == "private_address" and seen == ["127.0.0.1"]
    assert routes["_seen_paths"] == [] and routes["_seen_robots"] == []


def test_the_report_has_a_plain_text_for_both_new_reasons():
    labels = model.load_labels()
    assert model.access_reason_text("private_address", labels) == \
        "The address points inside a private network, so it was not opened."
    assert model.access_reason_text("too_many_redirects", labels) == "The site sent the request on too many times."


def test_cli_save_source_refuses_a_private_address(tmp_path, site, capsys):
    base, routes = site
    routes["/news"] = _html()
    code = cli.main(["save-source", "--run", str(make_run(tmp_path)), "--url", base + "/news", *_meta_args()])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["access_reason"] == "private_address" and routes["_seen_paths"] == []


@pytest.mark.parametrize("option", ["--address-allowed", "--allow-private", "--no-address-check",
                                    "--allow-private-addresses", "--address-allowed=true"])
def test_save_source_has_no_switch_that_turns_the_address_check_off(tmp_path, site, capsys, option):
    base, routes = site
    routes["/news"] = _html()
    code = cli.main(["save-source", "--run", str(make_run(tmp_path)), "--url", base + "/news", *_meta_args(), option])
    assert code == 2 and routes["_seen_paths"] == []
    capsys.readouterr()


@pytest.mark.parametrize("key", ["address_allowed", "allow_private", "allow-private", "no_address_check"])
def test_from_json_cannot_turn_the_address_check_off_either(tmp_path, site, capsys, key):
    base, routes = site
    routes["/news"] = _html()
    options = tmp_path / "options.json"
    options.write_text(json.dumps({"run": str(make_run(tmp_path / "r")), "url": base + "/news",
                                   "publisher": "Competitor A", "title": "Expansion", "date": "2026-05-14",
                                   "type": "company_release", "speaker": "the company",
                                   "interest": "wants to look strong", "language": "en", key: True}),
                       encoding="utf-8")
    code = cli.main(["save-source", "--from-json", str(options)])
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and "is not an option" in out["error"] and routes["_seen_paths"] == []


# --- Task 8, fix round 1 ----------------------------------------------------------------------

def _everything_is_public(host):
    """A resolver that answers every name with a public address, as many real ones do: these tests
    must prove the check of the address form, not the resolver."""
    return fetch.check_address(host, resolve=_answers("8.8.8.8"))


BAD_HOSTS = ["127.0.0.%31", "localhos%74", "%31%32%37.0.0.1", "127.0.0.1\\.example.test", "exämple.test",
             "127.0.0.1%2e", "local_host"]


@pytest.mark.parametrize("bad", BAD_HOSTS)
def test_a_host_that_urllib_would_decode_or_read_differently_is_refused_as_a_first_address(tmp_path, site, bad):
    base, routes = site
    port = base.rsplit(":", 1)[1]
    routes["/news"] = _html()
    routes["/robots.txt"] = (200, {}, b"User-agent: *\nDisallow:\n")
    with pytest.raises(ValueError, match="letters a to z, digits, hyphens and dots"):
        save(make_run(tmp_path), f"http://{bad}:{port}/news", address_allowed=_everything_is_public)
    assert routes["_seen_paths"] == [] and routes["_seen_robots"] == []


@pytest.mark.parametrize("bad", BAD_HOSTS)
def test_the_same_host_as_a_redirect_target_ends_as_not_accessible_and_is_never_asked(tmp_path, two_sites, bad):
    (base_a, routes_a), (base_b, routes_b) = two_sites
    port = base_b.rsplit(":", 1)[1]
    routes_a["/go"] = (302, {"Location": f"http://{bad}:{port}/news"}, b"")
    routes_b["/news"] = _html()
    rec = save(make_run(tmp_path), base_a + "/go", address_allowed=_everything_is_public)
    assert (rec["access"], rec["access_reason"]) == ("not_accessible", "unsupported_type")
    assert routes_b["_seen_paths"] == [] and routes_b["_seen_robots"] == []


@pytest.mark.parametrize("bad", BAD_HOSTS)
def test_a_bad_host_in_a_robots_redirect_is_not_followed(tmp_path, two_sites, bad):
    (base_a, routes_a), (base_b, routes_b) = two_sites
    port = base_b.rsplit(":", 1)[1]
    routes_a["/robots.txt"] = (302, {"Location": f"http://{bad}:{port}/robots.txt"}, b"")
    routes_a["/news"] = _html()
    rec = save(make_run(tmp_path), base_a + "/news", address_allowed=_everything_is_public)
    assert rec["access"] == "ok" and routes_b["_seen_robots"] == [] and routes_b["_seen_paths"] == []


@pytest.mark.parametrize("url", ["http://example.com./x", "http://EXAMPLE.com/x", "http://a-b.example.com:8080/x",
                                 "http://127.0.0.1/x", "http://[::1]:8080/x", "http://[2001:db8::1]/x",
                                 "http://2130706433/x", "http://localhost/x?q=%31#f"])
def test_ordinary_forms_of_a_host_are_accepted(url):
    fetch.check_url(url)


@pytest.mark.parametrize("url", ["http://example..com/x", "http://.example.com/x", "http://./x",
                                 "http://exa mple.com/x", "http://exa%6dple.com/x", "http://[::1%25en0]/x",
                                 "http://[g::1]/x", "http://[]/x", "http://example.com:80%38/x",
                                 "http://example.com\\@evil.test/x"])
def test_other_forms_of_a_host_are_refused(url):
    with pytest.raises(ValueError):
        fetch.check_url(url)


def test_the_host_that_is_checked_is_the_host_that_is_requested(tmp_path, site, monkeypatch):
    base, routes = site
    routes["/news"] = _html()
    asked, looked_up = [], []

    def record(host):
        asked.append(host)
        return "public"

    def lookup(host, port, *args, **kwargs):           # the request's name lookup, answered here: no computer's own
        looked_up.append(host)                         # lookup is asked, so the test runs wherever it runs
        if host.lower() != "localhost.":
            raise socket.gaierror(f"{host} is not known here")
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", port))]

    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    url = base.replace("127.0.0.1", "LOCALHOST.") + "/news"
    assert save(make_run(tmp_path), url, address_allowed=record)["access"] == "ok"
    assert asked == ["localhost.", "localhost."]   # robots, then the page
    assert [host.lower() for host in looked_up] == asked                 # the host urllib connects to is the one checked
    assert routes["_seen_paths"] == ["/news"]


def test_check_address_gives_three_answers():
    assert fetch.check_address("a.example", resolve=_answers("8.8.8.8")) == "public"
    assert fetch.check_address("a.example", resolve=_answers("10.0.0.5")) == "private"
    assert fetch.check_address("a.example", resolve=_answers("8.8.8.8", "10.0.0.5")) == "private"
    assert fetch.check_address("a.example", resolve=_answers("not an address")) == "private"
    assert fetch.check_address("a.example", resolve=_answers()) == "unresolved"

    def broken(*args, **kwargs):
        raise socket.gaierror("no such host")

    assert fetch.check_address("a.example", resolve=broken) == "unresolved"
    assert fetch.public_address("a.example", resolve=broken) is False


def test_a_name_that_does_not_resolve_is_a_network_error_and_nothing_is_requested(tmp_path, site):
    base, routes = site
    routes["/news"] = _html()
    rec = save(make_run(tmp_path), base + "/news", address_allowed=lambda host: "unresolved")
    assert (rec["access"], rec["access_reason"]) == ("not_accessible", "network_error")
    assert routes["_seen_paths"] == [] and routes["_seen_robots"] == []


def test_a_redirect_target_that_does_not_resolve_is_a_network_error(tmp_path, site):
    base, routes = site
    routes["/a"] = (302, {"Location": base.replace("127.0.0.1", "localhost") + "/b"}, b"")
    routes["/b"] = _html()
    rec = save(make_run(tmp_path), base + "/a",
               address_allowed=lambda host: "public" if host == "127.0.0.1" else "unresolved")
    assert rec["access_reason"] == "network_error" and routes["_seen_paths"] == ["/a"]


def test_the_default_check_is_looked_up_when_the_call_is_made_and_an_unresolved_name_is_a_network_error(
        tmp_path, site, monkeypatch):
    base, routes = site
    real = fetch.check_address

    def nowhere(*args, **kwargs):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(fetch, "check_address", lambda host: real(host, resolve=nowhere))
    rec = fetch.save_source(make_run(tmp_path), base + "/news", META, sleep=no_sleep)   # no address_allowed given
    assert rec["access_reason"] == "network_error" and routes["_seen_paths"] == [] and routes["_seen_robots"] == []


def test_an_answer_that_is_neither_a_word_nor_true_is_treated_as_private(tmp_path, site):
    base, routes = site
    routes["/news"] = _html()
    for number, answer in enumerate((False, None, "maybe", 0)):
        rec = save(make_run(tmp_path / str(number)), base + "/news", address_allowed=lambda host, a=answer: a)
        assert rec["access_reason"] == "private_address"
    assert routes["_seen_paths"] == []


@pytest.mark.parametrize("address", ["fec0::1", "2002:7f00:1::", "2002:0a00:0005::", "64:ff9b::7f00:1",
                                     "64:ff9b::a00:5", "2001:0:4136:e378:8000:63bf:f5ff:fffa",
                                     "2001:0:5ef5:79fb:8000:63bf:f7f7:f7f7"])
def test_ipv6_forms_that_carry_a_private_or_unusable_address_are_not_public(address):
    # fec0:: is site-local; 2002:: carries a 6to4 address, 64:ff9b:: a NAT64 one; the Teredo forms carry
    # a client address (10.0.0.5, then 8.8.8.8 behind a Teredo prefix that is not global anyway)
    assert fetch.public_address("odd.example", resolve=_answers(address)) is False


@pytest.mark.parametrize("address", ["2002:0808:0808::", "2001:0:808:808:8000:63bf:f7f7:f7f7"])
def test_6to4_and_teredo_forms_are_never_public_whatever_the_inner_address(address):
    # public inner addresses (8.8.8.8, and 8.8.8.8 for both Teredo server and client): still refused, so the
    # answer is the same on every patch level of Python, whatever is_global says there
    assert fetch.public_address("odd.example", resolve=_answers(address)) is False
    assert fetch.check_address("odd.example", resolve=_answers(address)) == "private"


@pytest.mark.parametrize("address", ["2002::", "2002:ffff:ffff:ffff:ffff:ffff:ffff:ffff", "2001:0:1::",
                                     "2001:0:ffff:ffff:ffff:ffff:ffff:ffff"])
def test_the_whole_range_of_each_carrier_form_is_recognised(address):
    assert fetch._is_carrier_form(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", ["2001:db8::1", "2001:1::1", "2003::1", "64:ff9b:1::1", "2606:4700::1", "8.8.8.8",
                                     "64:ff9b::", "64:ff9b::808:808"])
def test_ordinary_addresses_are_not_taken_for_a_carrier_form(address):
    assert not fetch._is_carrier_form(ipaddress.ip_address(address))


def test_a_mapped_address_is_judged_by_the_ipv4_address_inside():
    assert fetch.public_address("odd.example", resolve=_answers("::ffff:8.8.8.8")) is True
    assert fetch.public_address("odd.example", resolve=_answers("::ffff:10.0.0.5")) is False
    assert fetch.public_address("odd.example", resolve=_answers("::ffff:127.0.0.1")) is False


def test_the_robots_file_of_a_site_is_read_once_for_a_chain_on_one_host(tmp_path, site):
    base, routes = site
    _chain(routes, 3)
    assert save(make_run(tmp_path), base + "/r0")["access"] == "ok"
    assert routes["_seen_paths"] == ["/r0", "/r1", "/r2", "/r3"] and routes["_seen_robots"] == ["/robots.txt"]


def test_a_robots_rule_read_once_still_applies_to_every_address_of_the_chain(tmp_path, site):
    base, routes = site
    routes["/robots.txt"] = (200, {}, b"User-agent: *\nDisallow: /private/\n")
    routes["/a"] = (302, {"Location": "/private/doc"}, b"")
    routes["/private/doc"] = _html()
    assert save(make_run(tmp_path), base + "/a")["access_reason"] == "robots"
    assert routes["_seen_robots"] == ["/robots.txt"] and routes["_seen_paths"] == ["/a"]


# --- the address a copy really came from ------------------------------------------------------

def test_a_save_through_a_redirect_to_another_host_records_where_it_ended(tmp_path, two_sites):
    (base_a, routes_a), (base_b, routes_b) = two_sites
    routes_a["/go"] = (301, {"Location": base_b + "/page#top"}, b"")
    routes_b["/page"] = _html()
    run = make_run(tmp_path)
    rec = save(run, base_a + "/go")
    assert rec["access"] == "ok" and rec["url"] == base_a + "/go" and rec["final_url"] == base_b + "/page"
    assert store.read_sources(run)["S1"]["final_url"] == base_b + "/page"


def test_a_save_without_a_redirect_records_no_final_address(tmp_path, site):
    base, routes = site
    routes["/news"] = _html()
    assert save(make_run(tmp_path), base + "/news#part")["final_url"] is None


def test_a_redirect_that_ends_at_the_address_asked_for_records_no_final_address(tmp_path, site, monkeypatch):
    base, routes = site
    answers = [fetch._Redirect("/news#again"), (BODY.encode(), "text/html")]

    def scripted(opener, url, max_bytes):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(fetch, "_download", scripted)
    assert save(make_run(tmp_path), base + "/news#part")["final_url"] is None


def test_a_source_that_was_not_saved_has_no_final_address(tmp_path, two_sites):
    (base_a, routes_a), (base_b, routes_b) = two_sites
    routes_a["/go"] = (302, {"Location": base_b + "/gone"}, b"")
    rec = save(make_run(tmp_path), base_a + "/go")
    assert rec["access"] == "not_accessible" and rec["final_url"] is None


def test_a_copy_added_by_hand_has_no_final_address(tmp_path):
    page = tmp_path / "saved.html"
    page.write_text(BODY, encoding="utf-8")
    assert fetch.add_copy(make_run(tmp_path / "r"), page, "https://example.com/news", META, data_class="public")["final_url"] is None


# --- Task 8, fix round 2 ----------------------------------------------------------------------

def test_the_refusal_of_a_site_name_says_what_is_allowed_and_what_to_do_about_other_letters():
    with pytest.raises(ValueError) as caught:
        fetch.check_url("http://exämple.test/x")
    assert str(caught.value) == ("the site name may hold only the plain letters a to z, digits, hyphens and dots; "
                                 "a name with other letters must be given in its xn-- form")


@pytest.mark.parametrize("url", [
    "http://exam" + chr(9) + "ple.com/", "http://example.com:80" + chr(9) + "80/", "http://example.com/a" + chr(13) + "b",
    "http://example.com/a" + chr(10) + "b", " http://example.com/", "http://example.com/ ", "http://example.com/a b",
    "http://example.com/a" + chr(127), "http://example.com/a" + chr(0), "http://example.com/a" + chr(31),
    chr(9) + "http://example.com/"])
def test_an_address_with_a_space_or_a_control_character_anywhere_is_refused_before_it_is_parsed(url):
    with pytest.raises(ValueError, match="spaces or control characters.*%20"):
        fetch.check_url(url)


def test_a_first_address_with_a_tab_in_the_host_is_refused_and_nothing_is_requested(tmp_path, site):
    base, routes = site
    routes["/news"] = _html()
    port = base.rsplit(":", 1)[1]
    with pytest.raises(ValueError):
        save(make_run(tmp_path), "http://127.0.0.1" + chr(9) + f":{port}/news", address_allowed=_everything_is_public)
    assert routes["_seen_paths"] == [] and routes["_seen_robots"] == []


@pytest.mark.parametrize("location", ["/a" + chr(9) + "b", "/a" + chr(1) + "b", "/a" + chr(127) + "b",
                                      "http://exam" + chr(9) + "ple.test/x"])
def test_a_location_with_a_control_character_is_refused_not_encoded(tmp_path, site, location):
    base, routes = site
    routes["/old"] = (302, {"Location": location}, b"")
    assert save(make_run(tmp_path), base + "/old")["access_reason"] == "unsupported_type"
    assert routes["_seen_paths"] == ["/old"]


@pytest.mark.parametrize("location", ["/a" + chr(13) + "b", "/a" + chr(10) + "b", "/a" + chr(0) + "b"])
def test_the_next_address_refuses_every_control_character_before_it_encodes_anything(location):
    with pytest.raises(ValueError):
        fetch._next_address("http://example.test/x", location)


def test_a_redirect_to_a_path_with_a_space_is_followed_and_the_final_address_is_encoded(tmp_path, site):
    base, routes = site
    routes["/old"] = (302, {"Location": "/doc with space?q=a b"}, b"")
    routes["/doc%20with%20space"] = _html()
    rec = save(make_run(tmp_path), base + "/old")
    assert rec["access"] == "ok" and rec["final_url"] == base + "/doc%20with%20space?q=a%20b"
    assert routes["_seen_paths"] == ["/old", "/doc%20with%20space"]


def test_a_redirect_to_a_path_with_non_ascii_bytes_is_followed_and_encoded(tmp_path, site):
    base, routes = site
    # a server sends the UTF-8 bytes of the letter; the headers are read as latin-1, as http.client does
    routes["/old"] = (302, {"Location": "/caf" + "é".encode("utf-8").decode("latin-1")}, b"")
    routes["/caf%C3%A9"] = _html()
    rec = save(make_run(tmp_path), base + "/old")
    assert rec["access"] == "ok" and rec["final_url"] == base + "/caf%C3%A9"


def test_a_redirect_that_is_already_encoded_is_left_as_it_is(tmp_path, site):
    base, routes = site
    routes["/old"] = (302, {"Location": "/doc%20x%2Fy"}, b"")
    routes["/doc%20x%2Fy"] = _html()
    assert save(make_run(tmp_path), base + "/old")["final_url"] == base + "/doc%20x%2Fy"


def test_a_location_with_a_non_ascii_host_is_still_refused_and_the_target_sees_no_request(tmp_path, two_sites):
    (base_a, routes_a), (base_b, routes_b) = two_sites
    port = base_b.rsplit(":", 1)[1]
    routes_a["/go"] = (302, {"Location": f"http://exämple.test:{port}/news"}, b"")
    routes_b["/news"] = _html()
    rec = save(make_run(tmp_path), base_a + "/go", address_allowed=_everything_is_public)
    assert rec["access_reason"] == "unsupported_type"
    assert routes_b["_seen_paths"] == [] and routes_b["_seen_robots"] == []


# --- final_url must pass the data check and the gate whatever the download recorded ---

def test_what_a_redirect_can_record_as_final_url_passes_the_data_check_and_the_gate(tmp_path, two_sites):
    from radar.gate import gate
    from radar.schema import check_data
    (base_a, routes_a), (base_b, routes_b) = two_sites
    other_host = base_b.replace("127.0.0.1", "localhost")
    wanted = ["/@author/post-1", "/p?mail=a@b.example", other_host + "/@channel"]
    for route, target in zip(("/one", "/two", "/three"), wanted):
        routes_a[route] = (302, {"Location": target}, b"")
    routes_a["/@author/post-1"] = routes_a["/p"] = routes_b["/@channel"] = _html()
    run = make_run(tmp_path)
    for route in ("/one", "/two", "/three"):
        rec = save(run, base_a + route)
        assert rec["access"] == "ok" and rec["final_url"] is not None and "@" in rec["final_url"]
    assert [problem for problem in check_data(run) if problem.file.startswith("sources/")] == []
    assert [problem for problem in gate(run) if problem.file.startswith("sources/")] == []


# --- the same page under another spelling of its address is not a second address ---

def _scripted_redirect(monkeypatch, location):
    answers = [fetch._Redirect(location), (BODY.encode(), "text/html")]

    def scripted(opener, url, max_bytes):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(fetch, "_download", scripted)
    monkeypatch.setattr(fetch, "_read_robots", lambda *args: None)   # nothing is requested at all


@pytest.mark.parametrize("asked, location", [
    ("http://example.test/news", "http://EXAMPLE.Test/news"),
    ("http://example.test/news", "http://example.test:80/news"),
    ("https://example.test/news", "https://example.test:443/news"),
    ("http://example.test/news", "http://example.test./news"),
    ("HTTP://example.test/news", "http://example.test/news"),
    ("http://example.test", "http://example.test/"),
    ("http://example.test:80/news", "http://example.test/news"),
])
def test_a_redirect_that_only_changes_the_spelling_of_the_address_records_no_final_address(
        tmp_path, monkeypatch, asked, location):
    _scripted_redirect(monkeypatch, location)
    assert save(make_run(tmp_path), asked)["final_url"] is None


@pytest.mark.parametrize("asked, location", [
    ("http://example.test/news", "http://example.test/other"),
    ("http://example.test/news", "http://example.test/news?page=2"),
    ("http://example.test:8080/news", "http://example.test/news"),
    ("http://example.test/news", "http://example.test:8080/news"),
    ("http://example.test/news", "https://example.test/news"),
    ("http://example.test/news", "http://other.test/news"),
    ("https://example.test/news", "https://example.test:80/news"),
])
def test_a_redirect_that_leads_somewhere_else_records_the_final_address(tmp_path, monkeypatch, asked, location):
    _scripted_redirect(monkeypatch, location)
    assert save(make_run(tmp_path), asked)["final_url"] == location


# --- final fix I2 and I3: a saved source reserves its id and is counted ---------------------------

def test_a_saved_source_is_counted(tmp_path, site):
    base, routes = site
    routes["/news"] = (200, {"Content-Type": "text/html"}, BODY.encode())
    run = make_run(tmp_path)
    save(run, base + "/news")
    save(run, base + "/missing")
    assert store.load_run(run)["sources_created"] == 2


def test_a_failed_copy_write_leaves_no_record_and_no_reserved_id(tmp_path, monkeypatch):
    run = make_run(tmp_path)
    page = tmp_path / "saved.html"
    page.write_text(BODY, encoding="utf-8")

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(fetch, "_write_copies", broken)
    with pytest.raises(OSError):
        fetch.add_copy(run, page, "https://example.com/news", META, data_class="public")
    assert list((run / "sources").iterdir()) == [] and store.load_run(run)["sources_created"] == 0


def test_the_source_id_is_reserved_before_the_copies_are_written(tmp_path, monkeypatch):
    run = make_run(tmp_path)
    page = tmp_path / "saved.html"
    page.write_text(BODY, encoding="utf-8")
    seen = []
    real = fetch._write_copies

    def spy(run_dir, source_id, *args):
        seen.append((source_id, (run_dir / "sources" / f"{source_id}.json").exists()))
        return real(run_dir, source_id, *args)

    monkeypatch.setattr(fetch, "_write_copies", spy)
    fetch.add_copy(run, page, "https://example.com/news", META, data_class="public")
    assert seen == [("S1", True)]


# --- Task 9 (carried over): what stands in brackets must be an IPv6 address; the refusal of a space says what to do ---

@pytest.mark.parametrize("inside,expected", [
    ("::1", True), ("::ffff:127.0.0.1", True), ("2001:db8::1", True), ("2001:DB8:0:0:0:0:0:1", True),
    ("127.0.0.1", False), ("1.2.3.4", False), ("", False), (":::", False), ("::1::", False), ("g::1", False),
    ("1:2:3:4:5:6:7:8:9", False), ("fe80::1%eth0", False), ("::1%25en0", False), ("1.2.3.4.5", False),
])
def test_what_stands_in_brackets_must_be_an_ipv6_address(inside, expected):
    # judged by the function itself: whether urlsplit refuses a form depends on the Python version
    assert fetch._is_ipv6_literal(inside) is expected


@pytest.mark.parametrize("url", ["http://[127.0.0.1]/x", "http://[1.2.3.4]:80/x", "http://[:::]/x", "http://[1:2]/x"])
def test_a_bracketed_name_that_is_not_an_ipv6_address_is_refused(url):
    with pytest.raises(ValueError):
        fetch.check_url(url)


def test_the_refusal_of_a_space_says_how_a_space_is_written():
    with pytest.raises(ValueError) as caught:
        fetch.check_url("http://example.com/a b")
    assert str(caught.value) == ("The address must not hold spaces or control characters. "
                                 "A space inside an address is written as %20.")


# --- Task 9, fix round 1: a page cannot choose a decoding that shows the quote check other text than a reader sees ---

def test_a_quote_that_exists_only_under_a_hostile_decoding_is_not_found(tmp_path):
    from radar import verify
    from helpers import add_fact
    run = make_run(tmp_path)
    page = tmp_path / "page.html"
    page.write_bytes(b'<html><head><meta charset="utf-7"></head><body><p>Competitor +AEE- will add two new lines '
                     b'at Plant North by 2028, the company said.</p><p>' + b'The rest of this invented page is plain filler. ' * 5 +
                     b'</p></body></html>')   # enough visible text for add-copy (A2 fix round 1)
    source = fetch.add_copy(run, page, "https://www.example.com/hostile", META, data_class="public")
    saved = (run / source["copy_file"]).read_text(encoding="utf-8")
    assert "Competitor +AEE- will add" in saved and "Competitor A will add" not in saved
    add_fact(run, source_id=source["id"], primary_source=True,
             quote="Competitor A will add two new lines at Plant North by 2028")
    verify.check_quotes(run)
    assert store.read_facts(run)["F1"]["checks"]["quote"]["passed"] is False


# --- Part A fix A1, ruling HG4: a based-on id must be a saved source of the run ----------------------------

BAD_BASED_ON = [(["s1"], "a record id must be S followed by digits, not 's1'"),
                (["https://www.example.com/release"],
                 "a record id must be S followed by digits, not 'https://www.example.com/release'"),
                (["S1", "S9"], "source S9 does not exist")]


def _untouched(run):
    """The run as init-run made it plus S1: nothing saved, no download note, no lock for downloads."""
    names = sorted(path.name for path in run.iterdir())
    assert ".fetch.lock" not in names and ".last_fetch.json" not in names
    assert sorted(store.read_sources(run)) == ["S1"] and saved_copies(run) == [run / "copies" / "S1.txt"]


@pytest.mark.parametrize("based_on, message", BAD_BASED_ON)
def test_save_source_refuses_a_based_on_id_that_is_not_a_saved_source_before_any_request(tmp_path, based_on,
                                                                                          message):
    run = make_run(tmp_path)
    add_source(run, "An earlier release.")
    asked = []
    with pytest.raises(ValueError) as refused:
        save(run, "https://www.example.com/news", {**META, "based_on": based_on},
             address_allowed=lambda host: asked.append(host) or "private")   # never a real request
    assert str(refused.value) == message and asked == []
    _untouched(run)


@pytest.mark.parametrize("based_on, message", BAD_BASED_ON)
def test_add_copy_refuses_a_based_on_id_that_is_not_a_saved_source(tmp_path, based_on, message):
    run = make_run(tmp_path)
    add_source(run, "An earlier release.")
    page = tmp_path / "page.txt"
    page.write_text("The expansion adds two high-speed syringe lines. " * 8, encoding="utf-8")
    with pytest.raises(ValueError) as refused:
        fetch.add_copy(run, page, "https://www.example.com/news", {**META, "based_on": based_on}, data_class="public")
    assert str(refused.value) == message
    _untouched(run)


def _no_request(monkeypatch):
    def refuse(host):
        raise AssertionError(f"{host} was looked up")
    monkeypatch.setattr(fetch, "check_address", refuse)


def test_the_commands_refuse_a_bad_based_on_by_switch_and_through_from_json(tmp_path, capsys, monkeypatch):
    _no_request(monkeypatch)
    run = make_run(tmp_path)
    add_source(run, "An earlier release.")
    page = tmp_path / "page.txt"
    page.write_text("The expansion adds two high-speed syringe lines. " * 8, encoding="utf-8")
    meta = {"publisher": "Competitor A", "title": "Expansion", "date": "2026-05-14", "type": "company_release",
            "speaker": "the company", "interest": "wants to look strong", "language": "en"}
    commands = [["save-source", "--run", str(run), "--url", "https://www.example.com/news"],
                ["add-copy", "--data-class", "public", "--run", str(run), "--file", str(page), "--url", "https://www.example.com/news"]]
    for command in commands:
        for based_on, message in (("s1", "not 's1'"), ("S1,S4", "source S4 does not exist")):
            assert cli.main(command + ["--based-on", based_on, *_meta_args()]) == 2
            assert message in json.loads(capsys.readouterr().out)["error"]
        options = tmp_path / "options.json"
        options.write_text(json.dumps({**meta, "based_on": ["https://www.example.com/release"]}), encoding="utf-8")
        assert cli.main(command + ["--from-json", str(options)]) == 2
        assert "not 'https://www.example.com/release'" in json.loads(capsys.readouterr().out)["error"]
    _untouched(run)


# --- Part A fix A1, M5: save-source checks first that the folder is a run -------------------------------------

def test_save_source_into_a_folder_that_is_not_a_run_is_a_plain_usage_error_and_touches_nothing(tmp_path, capsys,
                                                                                                monkeypatch):
    _no_request(monkeypatch)
    not_a_run = tmp_path / "notes"
    not_a_run.mkdir()
    for folder in (not_a_run, tmp_path / "missing"):
        code = cli.main(["save-source", "--run", str(folder), "--url", "https://www.example.com/news", *_meta_args()])
        out = json.loads(capsys.readouterr().out)
        assert code == 2 and out == {"error": f"{folder} is not the folder of a run. "
                                              "Give the folder that init-run made for the run."}
    assert list(not_a_run.iterdir()) == [] and not (tmp_path / "missing").exists()
    with pytest.raises(ValueError, match="is not the folder of a run"):
        save(not_a_run, "ftp://www.example.com/x")          # the folder is checked before anything else


def test_add_copy_into_a_folder_that_is_not_a_run_is_the_same_plain_usage_error(tmp_path, capsys):
    page = tmp_path / "page.txt"
    page.write_text("The expansion adds two high-speed syringe lines. " * 8, encoding="utf-8")
    not_a_run = tmp_path / "notes"
    not_a_run.mkdir()
    for folder in (not_a_run, tmp_path / "missing"):
        for extra in ([], ["--data-class", "internal", "--supplied-by", "me", "--basis", "own document"]):
            code = cli.main(["add-copy", "--data-class", "public", "--run", str(folder), "--file", str(page), "--url",
                             "https://www.example.com/news", *extra, *_meta_args()])
            out = json.loads(capsys.readouterr().out)
            assert code == 2 and out == {"error": f"{folder} is not the folder of a run. "
                                                  "Give the folder that init-run made for the run."}, extra
    assert list(not_a_run.iterdir()) == [] and not (tmp_path / "missing").exists()


# --- Part A fix A1, M6: the refusal of a non-public source reads well for both kinds -------------------------

def test_the_refusal_of_a_non_public_source_in_a_public_run_reads_well(tmp_path):
    page = tmp_path / "review.txt"
    page.write_text("Internal capacity review. " * 20, encoding="utf-8")
    run = make_run(tmp_path / "public")
    for data_class, article in (("internal", "An"), ("licensed", "A")):
        with pytest.raises(PermissionError) as refused:
            fetch.add_copy(run, page, "internal capacity review", META, data_class=data_class, **OWN)
        assert str(refused.value) == (f"This run is in public mode. {article} {data_class} source can only enter "
                                      "a run started in private mode.")


# --- A2 fix round 1, small point a (ruling HG16, second part): invisible characters and letters in an address --------

INVISIBLE = {   # one character of each refused Unicode category, built from its number, never written as itself
    "Zs no-break space": chr(0xA0), "Zs em space": chr(0x2003), "Zl line separator": chr(0x2028),
    "Zp paragraph separator": chr(0x2029), "Cc next line": chr(0x85), "Cc escape": chr(0x1B),
    "Cf zero-width space": chr(0x200B), "Cf left-to-right mark": chr(0x200E), "Cf byte-order mark": chr(0xFEFF),
    "Cf soft hyphen": chr(0xAD), "Cs lone surrogate": chr(0xDCFF)}


@pytest.mark.parametrize("name", sorted(INVISIBLE))
@pytest.mark.parametrize("where", ["host", "path", "query"])
def test_an_address_holding_an_invisible_character_anywhere_is_refused_in_plain_words(tmp_path, monkeypatch,
                                                                                      name, where):
    character = INVISIBLE[name]
    address = {"host": f"https://www.site{character}a.example/x", "path": f"https://www.site-a.example/a{character}b",
               "query": f"https://www.site-a.example/x?q=a{character}b"}[where]
    with pytest.raises(ValueError) as caught:
        fetch.check_url(address)
    assert str(caught.value) in (fetch.SPACE_IN_ADDRESS, fetch.INVISIBLE_IN_ADDRESS)

    def no_lookup(host, *args, **kwargs):
        raise AssertionError(f"{host} was looked up")

    monkeypatch.setattr(fetch, "check_address", no_lookup)
    run = make_run(tmp_path)
    with pytest.raises(ValueError):
        fetch.save_source(run, address, META, sleep=no_sleep)
    assert store.read_sources(run) == {}
    from radar import pack
    path = tmp_path / "demo.json"
    data = json.loads((Path(__file__).parent.parent / "packs" / "demo.json").read_text(encoding="utf-8"))
    data["places"] = [{"kind": "press_room", "name": "A press room (invented)", "url": address}]
    path.write_text(json.dumps(data), encoding="utf-8")
    expected = [("places[0].url", pack.PLACE_ADDRESS)]
    if name.startswith("Cs"):   # a pack holding a lone surrogate anywhere is refused whole: it cannot be saved as text
        expected = [(None, pack.NOT_READABLE)]
    assert [(p.field, p.message) for p in pack.check_pack(path)] == expected


def test_the_refusal_names_invisible_characters_and_keeps_the_space_rule():
    for character in (chr(0x200B), chr(0x2028), chr(0x2029), chr(0x200E), chr(0xDCFF)):
        with pytest.raises(ValueError) as caught:
            fetch.check_url("https://www.site-a.example/a" + character)
        assert str(caught.value) == fetch.INVISIBLE_IN_ADDRESS
    assert fetch.INVISIBLE_IN_ADDRESS == ("The address must not hold invisible characters, such as a zero-width "
                                          "character, a line separator or a direction mark.")
    for character in (" ", chr(0xA0), chr(0x85), chr(9)):
        with pytest.raises(ValueError) as caught:
            fetch.check_url("https://www.site-a.example/a" + character + "b")
        assert str(caught.value) == fetch.SPACE_IN_ADDRESS


def test_a_letter_in_the_path_or_query_of_the_first_address_is_requested_encoded_and_saved_so(tmp_path, site):
    base, routes = site
    letter = chr(0xE4)   # a with diaeresis
    routes["/gesch%C3%A4ftsbericht"] = _html()
    rec = save(make_run(tmp_path), base + "/gesch" + letter + "ftsbericht?jahr=2025&art=gr" + letter + "n")
    assert rec["access"] == "ok"
    assert rec["url"] == base + "/gesch%C3%A4ftsbericht?jahr=2025&art=gr%C3%A4n" and rec["final_url"] is None
    assert routes["_seen_paths"] == ["/gesch%C3%A4ftsbericht"]


def test_the_pack_check_gives_the_download_s_verdict_for_letters_and_invisible_characters(tmp_path):
    from radar import pack
    letter = chr(0xE4)
    for address, accepted in ((f"https://www.site-a.example/gesch{letter}ftsbericht", True),
                              (f"https://www.site-{letter}.example/x", False),
                              ("https://www.site-a.example/a" + chr(0x200B), False)):
        path = tmp_path / "demo.json"
        data = json.loads((Path(__file__).parent.parent / "packs" / "demo.json").read_text(encoding="utf-8"))
        data["places"] = [{"kind": "press_room", "name": "A press room (invented)", "url": address}]
        path.write_text(json.dumps(data), encoding="utf-8")
        assert (pack.check_pack(path) == []) is accepted, address
        try:
            fetch.first_address(address)
            download = True
        except ValueError:
            download = False
        assert download is accepted, address


@pytest.mark.parametrize("character", [chr(0xA0), chr(0x200B), chr(0x2028), chr(0x200E)])
def test_a_location_holding_an_invisible_character_is_not_followed(tmp_path, site, character):
    base, routes = site
    # the server sends the UTF-8 bytes of the character; the headers are read as latin-1, as http.client does
    routes["/old"] = (302, {"Location": "/a" + character.encode("utf-8").decode("latin-1") + "b"}, b"")
    assert save(make_run(tmp_path), base + "/old")["access_reason"] == "unsupported_type"
    assert routes["_seen_paths"] == ["/old"]


def test_a_location_with_a_letter_whose_utf8_bytes_look_like_a_control_character_is_still_encoded():
    # A with ring above: its UTF-8 bytes are C3 85, and 85 read alone is a control character. (Tested on the rule
    # itself: Python's own header reader splits a header line at that byte, so no server could send it whole.)
    letter = chr(0xC5)
    location = "/" + letter.encode("utf-8").decode("latin-1")
    assert fetch._next_address("http://www.site-a.example/x", location) == "http://www.site-a.example/%C3%85"


# --- A2 fix round 2, point 4: a lone surrogate in an address (an argument whose bytes were not UTF-8) ---------------

@pytest.mark.parametrize("address", ["https://www.site-a.example/a" + chr(0xDCFF),
                                     "https://www.site" + chr(0xDCFF) + ".example/a",
                                     "https://www.site-a.example/a?q=" + chr(0xDCFF) + "b", chr(0xDCFF)])
def test_an_address_holding_a_lone_surrogate_is_refused_in_the_plain_sentence(tmp_path, capsys, address):
    for check in (fetch.first_address, fetch.check_url):
        with pytest.raises(ValueError) as caught:
            check(address)
        assert str(caught.value) == fetch.INVISIBLE_IN_ADDRESS
    from radar import cli
    run = make_run(tmp_path)
    before = sorted(str(path) for path in tmp_path.rglob("*"))
    code = cli.main(["save-source", "--run", str(run), "--url", address, "--publisher", "Competitor A", "--title",
                     "Lines", "--date", "2026-05-14", "--type", "company_release", "--speaker", "the company",
                     "--interest", "wants to look strong", "--language", "en"])
    assert code == 2 and json.loads(capsys.readouterr().out) == {"error": fetch.INVISIBLE_IN_ADDRESS}
    assert sorted(str(path) for path in tmp_path.rglob("*")) == before and store.read_sources(run) == {}


# --- fix wave A4: add-copy names the data class of every file; there is no default ---------------------------------

def test_add_copy_without_a_data_class_is_refused_and_saves_nothing(tmp_path, capsys):
    run = make_run(tmp_path)
    page = tmp_path / "export.txt"
    page.write_text("An export from a paid database, illustrative only. " * 10, encoding="utf-8")
    argv = ["add-copy", "--run", str(run), "--file", str(page), "--url", "https://www.example.com/export",
            *_meta_args()]
    assert cli.main(argv) == 2
    out = json.loads(capsys.readouterr().out)
    assert list(out) == ["error"] and "--data-class" in out["error"]
    assert store.read_sources(run) == {} and saved_copies(run) == []
    assert cli.main(argv + ["--data-class", "public"]) == 0
    assert json.loads(capsys.readouterr().out)["data_class"] == "public"


def test_the_library_call_has_no_default_data_class_either(tmp_path):
    import inspect
    assert inspect.signature(fetch.add_copy).parameters["data_class"].default is inspect.Parameter.empty
    run = make_run(tmp_path)
    page = tmp_path / "saved.html"
    page.write_text(BODY, encoding="utf-8")
    with pytest.raises(TypeError):
        fetch.add_copy(run, page, "https://example.com/news", META)
    assert store.read_sources(run) == {}


def test_the_data_class_is_required_in_the_parser():
    add_copy = next(action for action in cli.build_parser()._actions if action.choices).choices["add-copy"]
    option = next(action for action in add_copy._actions if "--data-class" in action.option_strings)
    assert option.required is True and option.default is None and tuple(option.choices) == store.DATA_CLASSES


# --- fix wave A6: a PDF without the PDF add-on is refused in plain words, and nothing is saved -----------------------

def _without_the_pdf_add_on(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "pypdf", None)   # `import pypdf` now fails, as on a Python without it
    with pytest.raises(ImportError):
        import pypdf  # noqa: F401


def test_add_copy_of_a_pdf_without_the_add_on_is_refused_in_one_plain_line(tmp_path, capsys, monkeypatch):
    run = make_run(tmp_path)
    pdf = tmp_path / "ar.pdf"
    pdf.write_bytes(make_pdf(["Annual report 2025. " * 3, "Capacity will double by 2028. " * 5]))
    _without_the_pdf_add_on(monkeypatch)
    code = cli.main(["add-copy", "--run", str(run), "--file", str(pdf), "--url", "https://example.com/ar.pdf",
                     "--data-class", "public", *_meta_args()])
    lines = capsys.readouterr().out.splitlines()
    assert code == 2 and len(lines) == 1 and json.loads(lines[0]) == {"error": fetch.PDF_ADD_ON_MISSING}
    assert "radar setup" in fetch.PDF_ADD_ON_MISSING and "PDF add-on" in fetch.PDF_ADD_ON_MISSING
    assert store.read_sources(run) == {} and saved_copies(run) == []
    assert store.load_run(run)["sources_created"] == 0


def test_save_source_of_a_pdf_without_the_add_on_is_refused_too_and_saves_no_record(tmp_path, site, capsys,
                                                                                     monkeypatch):
    monkeypatch.setattr(fetch, "MIN_DELAY_SECONDS", 0)
    monkeypatch.setattr(fetch, "check_address", lambda host: "public")   # the test server lives on 127.0.0.1
    base, routes = site
    routes["/ar.pdf"] = (200, {"Content-Type": "application/pdf"},
                         make_pdf(["Annual report 2025. " * 3, "Capacity will double by 2028. " * 5]))
    run = make_run(tmp_path)
    _without_the_pdf_add_on(monkeypatch)
    code = cli.main(["save-source", "--run", str(run), "--url", base + "/ar.pdf", *_meta_args()])
    lines = capsys.readouterr().out.splitlines()
    assert code == 2 and len(lines) == 1 and json.loads(lines[0]) == {"error": fetch.PDF_ADD_ON_MISSING}
    assert store.read_sources(run) == {} and saved_copies(run) == []


def test_a_page_that_is_not_a_pdf_is_saved_as_before_without_the_add_on(tmp_path, site, monkeypatch):
    base, routes = site
    routes["/news"] = (200, {"Content-Type": "text/html"}, BODY.encode())
    run = make_run(tmp_path)
    _without_the_pdf_add_on(monkeypatch)
    assert save(run, base + "/news")["access"] == "ok"


# --- fix wave A15: a NAT64 address is judged by the IPv4 address it carries ----------------------------------------
# (replaces the NAT64 part of ruling T8e; on networks that reach IPv4 sites through NAT64 every such site came back
# "inside a private network")

@pytest.mark.parametrize("address, public", [
    ("64:ff9b::808:808", True), ("64:ff9b::0808:0808", True),
    ("64:ff9b::a00:5", False), ("64:ff9b::7f00:1", False), ("64:ff9b::c0a8:101", False),
    ("64:ff9b::a9fe:a9fe", False), ("64:ff9b::", False), ("64:ff9b::ffff:ffff", False), ("64:ff9b::e000:1", False)])
def test_a_nat64_address_is_judged_by_the_ipv4_address_it_carries(address, public):
    inner = ipaddress.IPv4Address(int(ipaddress.ip_address(address)) & 0xFFFFFFFF)
    assert fetch.public_address("odd.example", resolve=_answers(address)) is public
    assert fetch.public_address("odd.example", resolve=_answers(str(inner))) is public   # the same as the address inside
    assert fetch.check_address("odd.example", resolve=_answers(address)) == ("public" if public else "private")


def test_6to4_and_teredo_stay_refused_while_nat64_is_judged_by_what_it_carries():
    carried = "0808:0808"   # a public IPv4 address inside each form
    assert fetch.public_address("x.example", resolve=_answers("64:ff9b::" + carried)) is True
    assert fetch.public_address("x.example", resolve=_answers("2002:" + carried + "::")) is False
    assert fetch.public_address("x.example", resolve=_answers("2001:0:808:808:8000:63bf:f7f7:f7f7")) is False


# --- fix wave A23.14: add-copy's --url is checked for invisible characters too -------------------------------------

def _copy_with_url(tmp_path, url):
    run = make_run(tmp_path / "run")
    page = tmp_path / "saved.html"
    page.write_text(BODY, encoding="utf-8")
    try:
        fetch.add_copy(run, page, url, META, data_class="public")
    except ValueError as refused:
        return str(refused), store.read_sources(run)
    return None, store.read_sources(run)


@pytest.mark.parametrize("name", sorted(INVISIBLE))
def test_a_web_address_given_to_add_copy_is_refused_for_an_invisible_character_as_a_download_is(tmp_path, name):
    character = INVISIBLE[name]
    refused, sources = _copy_with_url(tmp_path, "https://www.example.com/ne" + character + "ws")
    assert refused in (fetch.SPACE_IN_ADDRESS, fetch.INVISIBLE_IN_ADDRESS) and sources == {}
    refused, _ = _copy_with_url(tmp_path / "upper", "HTTPS://www.example.com/a" + character)
    assert refused in (fetch.SPACE_IN_ADDRESS, fetch.INVISIBLE_IN_ADDRESS)


@pytest.mark.parametrize("label", ["internal capacity review" + chr(0x200B) + ", Q3", "memo" + chr(0x202E) + ".txt",
                                   "planning note\nsecond line", "planning\tnote", "internal://memo" + chr(0xFEFF)])
def test_a_label_in_free_words_is_refused_only_for_control_and_format_characters(tmp_path, label):
    refused, sources = _copy_with_url(tmp_path, label)
    assert refused == fetch.INVISIBLE_IN_LABEL and sources == {}


@pytest.mark.parametrize("label", ["internal capacity review, Q3", "Planungsnotiz f" + chr(0xFC) + "r 2027",
                                   "release.txt", "internal://memo", "a note" + chr(0xA0) + "with a no-break space"])
def test_a_label_in_free_words_with_visible_letters_and_spaces_is_kept_as_written(tmp_path, label):
    refused, sources = _copy_with_url(tmp_path, label)
    assert refused is None and sources["S1"]["url"] == label


def test_the_label_refusal_is_a_plain_sentence():
    assert fetch.INVISIBLE_IN_LABEL == ("The place where the document lives must not hold control characters or "
                                        "invisible characters such as a zero-width character or a direction mark.")


# --- Plan 2b, Task 10, change C: the robots file has a shorter limit of its own -------------------------------------

@contextlib.contextmanager
def _never_answers(hanging: str):
    """A stand-in site that never answers on the path `hanging` while the test runs; otherwise robots.txt answers 404
    at once and every other path serves BODY."""
    release, seen = threading.Event(), []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            if self.path == hanging:
                release.wait(60)   # no answer at all: the connection is held open until the test ends
                return
            found = self.path != "/robots.txt"
            body = BODY.encode() if found else b"not found"
            self.send_response(200 if found else 404)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", seen
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join()


def test_the_robots_file_waits_ten_seconds_and_the_page_thirty():
    assert (fetch.ROBOTS_TIMEOUT_SECONDS, fetch.TIMEOUT_SECONDS) == (10, 30)


def test_a_robots_file_that_does_not_answer_ends_the_save_as_a_timeout_and_the_page_is_never_asked_for(
        tmp_path, monkeypatch):
    """The robots file is given up on after its own limit, not the page's: a hanging site no longer costs two waits of
    30 seconds. The page is then not asked for (the safe side), and the reason is the one a page gets."""
    monkeypatch.setattr(fetch, "ROBOTS_TIMEOUT_SECONDS", 0.5)   # TIMEOUT_SECONDS keeps its 30 seconds
    with _never_answers("/robots.txt") as (base, seen):
        started = time.monotonic()
        rec = save(make_run(tmp_path), base + "/news")
        took = time.monotonic() - started
    assert (rec["access"], rec["access_reason"], rec["copy_file"]) == ("not_accessible", "timeout", None)
    assert seen == ["/robots.txt"]   # the page itself was never requested
    assert 0.5 <= took < 5, took     # the robots limit and some slack, far below the page's 30 seconds


def test_a_page_that_does_not_answer_is_given_up_on_after_the_page_s_own_limit(tmp_path, monkeypatch):
    """The mirror of the test above: the robots file answers at once, the page hangs, and the page's limit applies,
    not the robots file's 10 seconds."""
    monkeypatch.setattr(fetch, "TIMEOUT_SECONDS", 0.5)   # ROBOTS_TIMEOUT_SECONDS keeps its 10 seconds
    with _never_answers("/news") as (base, seen):
        started = time.monotonic()
        rec = save(make_run(tmp_path), base + "/news")
        took = time.monotonic() - started
    assert (rec["access"], rec["access_reason"], rec["copy_file"]) == ("not_accessible", "timeout", None)
    assert seen == ["/robots.txt", "/news"]
    assert 0.5 <= took < 5, took


def test_a_wait_that_ran_out_is_told_apart_from_other_failures_in_both_forms_a_request_raises_it():
    assert fetch._is_timeout(TimeoutError("timed out"))                          # no answer to the request
    assert fetch._is_timeout(urllib.error.URLError(TimeoutError("timed out")))   # no answer to the connection
    assert not fetch._is_timeout(urllib.error.URLError(ConnectionRefusedError()))
    assert not fetch._is_timeout(ConnectionResetError())


def test_a_robots_file_that_fails_in_another_way_still_lets_the_page_through(tmp_path, site):
    base, routes = site
    routes["/robots.txt"] = (503, {}, b"busy")
    routes["/news"] = _html()
    rec = save(make_run(tmp_path), base + "/news")
    assert rec["access"] == "ok" and routes["_seen_robots"] == ["/robots.txt"] and routes["_seen_paths"] == ["/news"]


# --- Plan 2b, Task 10, change F: a web page that holds little running text is flagged, never refused ----------------
# Everything here is invented. A line of eight or more words is running text; menu entries, headings and footer links
# are shorter lines.

MENU = ["Home", "About us", "Our company", "Products and services", "Contract manufacturing", "Fill and finish",
        "Quality and compliance", "Sustainability", "Careers", "Open positions", "News and media", "Press releases",
        "Events", "Investors", "Financial reports", "Contact", "Locations", "Customer portal", "Search", "Language"]
FOOTER = ["Imprint", "Privacy notice", "Cookie settings", "Terms of use", "Accessibility", "Sitemap",
          "Copyright 2026 Competitor D, an invented company"]
ARTICLE = [
    "Competitor D, an invented company, said on Tuesday that it will add two filling lines at its Plant East site "
    "before the end of 2027.",
    "The two lines are meant for the company's own injectable products, and the company says that no capacity on them "
    "will be offered to other customers.",
    "According to the release, the building work starts in the spring, and the first line is to be ready for its "
    "qualification runs about one year later.",
    "The company did not state what the expansion costs. It said only that the money comes from its own funds and that "
    "about eighty new jobs are planned at the site.",
    "A spokesperson added that a third line is being looked at for a later stage, but that no decision on it has been "
    "taken yet and none is expected this year.",
    "The invented Plant East site already runs four lines for vials and two for syringes, according to the company's "
    "earlier statements on its own website."]
RELEASE = [
    "Competitor D, an invented company, opens a new warehouse for finished products next to its Plant East site in "
    "the coming month.",
    "The warehouse holds space for about twelve thousand pallets and is cooled for products that must be kept cold. "
    "The company says it shortens the way from its filling lines to its customers.",
    "Twenty people will work there in two shifts. The release names no figure for the cost of the building and no "
    "date for any further step.",
    "The company also says that solar panels on the roof of the warehouse are to cover most of the power that its "
    "cooling needs over a year."]


def _menu(items) -> str:
    return "<ul>" + "".join(f'<li><a href="/x">{item}</a></li>' for item in items) + "</ul>"


def _page(main: str) -> str:
    """An invented company page: a header with a long menu, the main part given, and a footer of links."""
    return ("<!DOCTYPE html><html><head><title>Competitor D: News</title></head><body>"
            f"<header><p>Competitor D</p><nav>{_menu(MENU)}</nav></header>"
            f'<main id="app">{main}</main><footer>{_menu(FOOTER)}</footer></body></html>')


SHELL_PAGE = _page("")   # the article would be built by a script in a browser: the main part is empty
ARTICLE_PAGE = _page("<h1>Competitor D adds two lines</h1>" + "".join(f"<p>{text}</p>" for text in ARTICLE))
RELEASE_PAGE = ("<html><body><h1>Competitor D opens a warehouse</h1>"
                + "".join(f"<p>{text}</p>" for text in RELEASE) + "</body></html>")
SEVEN_LONG_WORDS = " ".join(["Manufacturing-capacity-announcement-of-the-invented-company"] * 7)


def _page_with_running_text(chars: int) -> tuple[str, str]:
    """An invented page whose one line of eight or more words is exactly `chars` long, and the line itself. A heading
    of seven very long words (419 characters) stands above it; it is no running text, so it does not count."""
    sentence = "Competitor D adds filling lines at its invented Plant East site. "
    line = (sentence * (chars // len(sentence) + 1))[:chars]
    line = line[:-1] + "s" if line.endswith(" ") else line
    return f"<html><body><h1>{SEVEN_LONG_WORDS}</h1><p>{line}</p></body></html>", line


def _saved_both_ways(tmp_path, site, page: str) -> list[tuple[Path, dict]]:
    """The page saved by save-source from the stand-in site and added by hand as an .html and an .htm file."""
    base, routes = site
    routes["/page"] = _html(page)
    downloaded = make_run(tmp_path / "downloaded")
    saved = [(downloaded, save(downloaded, base + "/page"))]
    for suffix in (".html", ".htm"):
        run, file = make_run(tmp_path / suffix[1:]), tmp_path / f"saved{suffix}"
        file.write_text(page, encoding="utf-8")
        saved.append((run, fetch.add_copy(run, file, "https://www.competitor-d.example/news", META,
                                          data_class="public")))
    return saved


def test_running_text_is_the_characters_of_the_lines_of_eight_or_more_words():
    text = ("one two three four five six seven eight\n"          # 8 words, 39 characters: counted
            "a b c d e f g\n"                                    # 7 words: not counted
            "   nine ten eleven twelve thirteen fourteen fifteen sixteen   \n"   # stripped: 56 characters, counted
            "\n"
            "Home\nAbout us\n")
    assert fetch.prose_chars(text) == 39 + 56
    assert fetch.prose_chars("") == 0 and fetch._MIN_PROSE_CHARS == 800


def test_a_shell_page_whose_article_a_script_builds_is_saved_and_flagged(tmp_path, site):
    for run, rec in _saved_both_ways(tmp_path, site, SHELL_PAGE):
        copy = (run / rec["copy_file"]).read_text(encoding="utf-8")
        assert len(copy.strip()) >= 300, copy   # menu words enough for the rule of 200 characters to let it through
        assert (rec["access"], rec["access_reason"], rec["text_note"]) == ("ok", None, "little_running_text")
        assert store.read_sources(run)["S1"] == rec and schema.check_data(run) == []


def test_a_page_that_holds_its_article_is_not_flagged(tmp_path, site):
    for run, rec in _saved_both_ways(tmp_path, site, ARTICLE_PAGE):
        assert rec["access"] == "ok" and "text_note" not in rec
        assert "Competitor D, an invented company, said on Tuesday" in (run / rec["copy_file"]).read_text("utf-8")


@pytest.mark.parametrize("chars, flagged", [(799, True), (800, False), (801, False)])
def test_a_page_just_below_the_line_of_800_characters_is_flagged_and_one_at_or_above_it_is_not(tmp_path, site,
                                                                                                chars, flagged):
    page, line = _page_with_running_text(chars)
    assert len(line) == chars and len(line.split()) >= 8 and len(SEVEN_LONG_WORDS) == 419
    for run, rec in _saved_both_ways(tmp_path, site, page):
        assert line in (run / rec["copy_file"]).read_text(encoding="utf-8").splitlines()
        assert rec["access"] == "ok" and ("text_note" in rec) is flagged, (chars, rec)


def test_a_short_press_release_is_flagged_but_saved_and_counted_as_saved(tmp_path, site):
    assert 550 <= sum(len(text) for text in RELEASE) <= 650   # about 600 characters of running text
    base, routes = site
    routes["/release"] = _html(RELEASE_PAGE)
    run = make_run(tmp_path)
    rec = save(run, base + "/release")
    assert (rec["access"], rec["text_note"]) == ("ok", "little_running_text") and (run / rec["copy_file"]).is_file()
    assert run_status(run)["steps"][0] == {"name": "collect", "state": "done",
                                           "detail": "1 source saved, 0 not accessible, 1 with little running text"}
    assert run_status(run)["sources_to_read"] == ["S1"]   # it waits to be read like any saved source


def test_a_pdf_a_text_and_a_table_are_never_flagged(tmp_path, site):
    """Only a web page is judged: the same short lines in a PDF, a plain text or a table get no note."""
    base, routes = site
    lines = MENU + FOOTER[:-1]   # short lines only: no running text at all
    routes["/report.pdf"] = (200, {"Content-Type": "application/pdf"}, make_pdf(lines))
    routes["/notes"] = (200, {"Content-Type": "text/plain; charset=utf-8"}, "\n".join(lines).encode())
    run = make_run(tmp_path / "downloaded")
    for path in ("/report.pdf", "/notes"):
        rec = save(run, base + path)
        assert rec["access"] == "ok" and "text_note" not in rec, rec
    by_hand = make_run(tmp_path / "by-hand")
    files = {"report.pdf": make_pdf(lines), "notes.txt": "\n".join(lines).encode(),
             "table.csv": "\n".join(f"{entry},1" for entry in lines).encode()}
    for name, content in files.items():
        (tmp_path / name).write_bytes(content)
        rec = fetch.add_copy(by_hand, tmp_path / name, "https://www.competitor-d.example/" + name, META,
                             data_class="public")
        assert rec["access"] == "ok" and "text_note" not in rec, (name, rec)
    assert schema.check_data(run) == [] and schema.check_data(by_hand) == []


def test_a_flagged_record_has_the_keys_of_every_record_and_the_note(tmp_path, site):
    base, routes = site
    routes["/news"] = _html(SHELL_PAGE)
    rec = save(make_run(tmp_path), base + "/news")
    assert list(rec)[-1] == "text_note" and set(rec) - {"text_note"} == {
        "id", "url", "publisher", "title", "date", "type", "speaker", "interest", "language", "data_class",
        "saved_at", "saved_by", "access", "access_reason", "copy_file", "orig_file", "copy_sha256", "based_on",
        "provenance", "final_url"}


def test_a_page_that_could_not_be_saved_gets_no_note(tmp_path, site):
    base, _ = site
    rec = save(make_run(tmp_path), base + "/missing")
    assert rec["access_reason"] == "http_404" and "text_note" not in rec
