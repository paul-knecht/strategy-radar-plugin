"""The reference in docs/engine.md names every option and every printed key exactly, and stays exact.

Part B's skills and helpers are written from the section "Reference: what each command takes and prints". Each command
has one block there, fenced as ```reference, in a fixed form a program can read:

    radar <command>
      --option VALUE        required, and what it means      (VALUE in capitals takes a value)
      --choice {a,b}        default a                        (the allowed values, as the parser has them)
      --switch              switch                           (no value)
    prints: key, list[key, key], object{key, key}, by_id{ID: key, key}
        key, key                                         (a line indented by four spaces continues the one above)
    prints (exit 1, a case): key, key
    exit: what each exit code means

A `prints` line without a label is what the command prints with exit code 0; a label that starts with "exit N" is a
case that ends with that exit code; any other label names an option that changes what is printed. The `exit:` line is
`exit: 0 <when>; 1 <when>; 2 <when>`, naming each code the command can end with. Every command also takes
--from-json FILE (stated once above the blocks).

What is pinned, in both directions: the options of every command against `radar.cli.build_parser()` (name, value or
switch, required, allowed values, default); the printed keys, in the order they are printed, one level down and further
where the block names them, against what the commands really print on the invented demo run; the exit code of every
case run here against the codes the block's `exit:` line names, with at least one refusal case for every command and its
printed shape; and the three proposal tables against what the program's own proposal check accepts and refuses. Every
key of a table is tried in four proposals (the base: a capacity move, quote in English, firm; a quote in another
language; a tentative fact; a general fact, which holds no `fields`): left out, it is refused exactly where its
Required cell (yes, no, "when `K` is `V`", "when `K` is not `V`"; any other form fails) says it is required, and a
conditional cell must be seen both applying and not applying; a value of the documented type is accepted (where the key
is required, or in the base for a key that never is) and a value of every other basic type (text, number, true or
false, list, object) is refused; null is accepted exactly where the type says "or null" and the key is not required;
the Values cell lists exactly the program's values. The prose around the blocks is not checked by a program.
Everything here is invented.
"""
import contextlib
import io
import json
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from radar import fetch, schema, setup_env, status, store
from radar.cli import build_parser, main
from radar.demo import LENSES, build_demo_run

ROOT = Path(__file__).parent.parent
DOC = ROOT / "docs" / "engine.md"
SECTION = "## Reference: what each command takes and prints"
PACK = ROOT / "packs" / "demo.json"


# --- reading the reference ------------------------------------------------------------------------------------------

def reference() -> str:
    text = DOC.read_text(encoding="utf-8")
    start = text.index(SECTION)
    end = text.find("\n## ", start + len(SECTION))
    return text[start:] if end == -1 else text[start:end]


_BLOCK = re.compile(r"^```reference\n(.*?)^```$", re.M | re.S)
_OPTION = re.compile(r"^  (--[a-z][a-z-]*)(?: (\{[^}]*\}|[A-Z][A-Z-]*))?(?: {2,}(\S.*))?$")
_PRINTS = re.compile(r"^prints(?: \(([^)]+)\))?: (.+)$")
_TOKEN = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_-]*|[\[\]{},:])")


def _shape(text: str) -> dict:
    """Parse `key, list[key], object{key}, by_id{ID: key}, by_id{ID}` into {name: None | (kind, inner)}."""
    tokens, position = [], 0
    while position < len(text):
        found = _TOKEN.match(text, position)
        assert found, f"cannot read the printed keys at: {text[position:]!r}"
        tokens.append(found.group(1))
        position = found.end()
        while position < len(text) and text[position].isspace():
            position += 1

    def items(at: int, closer: str | None) -> tuple[dict, int]:
        result = {}
        while True:
            name = tokens[at]
            assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", name), (text, name)
            at += 1
            spec = None
            if at < len(tokens) and tokens[at] == "[":
                inner, at = items(at + 1, "]")
                spec = ("list", inner)
            elif at < len(tokens) and tokens[at] == "{":
                if tokens[at + 1] == "ID" and tokens[at + 2] in (":", "}"):
                    if tokens[at + 2] == "}":
                        spec, at = ("ids", None), at + 3
                    else:
                        inner, at = items(at + 3, "}")
                        spec = ("ids", inner)
                else:
                    inner, at = items(at + 1, "}")
                    spec = ("object", inner)
            assert name not in result, (text, name)
            result[name] = spec
            if at == len(tokens):
                assert closer is None, text
                return result, at
            if tokens[at] == ",":
                at += 1
                continue
            assert tokens[at] == closer, (text, tokens[at])
            return result, at + 1

    shape, end = items(0, None)
    assert end == len(tokens), text
    return shape


def _block(lines: list[str]) -> dict:
    options, prints, exits = {}, {}, None
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("  --"):
            found = _OPTION.match(line)
            assert found, f"an option line that is not in the fixed form: {line!r}"
            name, value, remark = found.groups()
            assert name not in options, line
            default = re.search(r"\bdefault (\S+?)(?=[:;,]?(?:\s|$))", remark or "")
            options[name] = {"switch": value is None,
                             "choices": value[1:-1].split(",") if value and value.startswith("{") else None,
                             "required": (remark or "").split(" ")[0].rstrip(",;:") == "required",
                             "default": default.group(1) if default else None}
        elif line.startswith("prints"):
            found = _PRINTS.match(line)
            assert found, f"a prints line that is not in the fixed form: {line!r}"
            label, text = found.groups()
            while index + 1 < len(lines) and lines[index + 1].startswith("    "):   # a continued prints line
                index += 1
                text += " " + lines[index].strip()
            assert label not in prints, line
            prints[label] = _shape(text)
        elif line.startswith("exit: "):
            exits = line[len("exit: "):]
        else:
            raise AssertionError(f"a line of a reference block that is not in the fixed form: {line!r}")
        index += 1
    return {"options": options, "prints": prints, "exit": exits}


def blocks() -> dict[str, dict]:
    found = {}
    for body in _BLOCK.findall(reference()):
        lines = body.splitlines()
        assert lines[0].startswith("radar "), lines[0]
        command = lines[0][len("radar "):].strip()
        assert command not in found, f"two blocks for {command}"
        found[command] = _block(lines[1:])
    return found


def subcommands() -> dict:
    parser = build_parser()
    return next(action.choices for action in parser._actions if isinstance(getattr(action, "choices", None), dict))


def parser_options(subparser) -> dict[str, dict]:
    options = {}
    for action in subparser._actions:
        name = next((text for text in action.option_strings if text.startswith("--")), None)
        if name is None or name == "--help":
            continue
        default = action.default if action.default not in (None, False) else None
        options[name] = {"switch": action.nargs == 0,
                         "choices": None if action.choices is None else [str(choice) for choice in action.choices],
                         "required": action.required,
                         "default": None if default is None else str(default)}
    return options


# --- (a) the options -------------------------------------------------------------------------------------------------

def test_the_reference_has_one_block_for_each_command_and_for_the_version_and_nothing_else():
    assert sorted(blocks()) == sorted([*subcommands(), "--version"])


def test_the_reference_says_once_that_every_command_takes_from_json():
    assert "Every command also takes `--from-json FILE`" in reference()
    for name, subparser in subcommands().items():
        assert "--from-json" in parser_options(subparser), name


@pytest.mark.parametrize("command", sorted(subcommands()))
def test_the_documented_options_are_the_options_of_the_command(command):
    documented = blocks()[command]["options"]
    real = parser_options(subcommands()[command])
    real.pop("--from-json")
    assert sorted(documented) == sorted(real), command
    for name, expected in real.items():
        assert documented[name] == expected, (command, name)


def test_the_version_block_names_the_one_option_of_radar_itself():
    real = parser_options(build_parser())
    assert sorted(real) == ["--version"] and blocks()["--version"]["options"] == {}


def exit_codes(block: dict) -> set[int]:
    """The codes an `exit:` line names: `exit: 0 <when>; 1 <when>; 2 <when>`."""
    return {int(code) for code in re.findall(r"(?:^|; )([012]) ", block["exit"] or "")}


def test_every_block_says_what_its_exit_codes_mean():
    for command, block in blocks().items():
        assert 0 in exit_codes(block), command
        for label in block["prints"]:
            if label and label.startswith("exit "):
                assert re.match(r"exit [012]\b", label) and int(label[5]) in exit_codes(block), (command, label)


# --- (b) the printed keys --------------------------------------------------------------------------------------------

def radar(*argv) -> tuple[int, dict]:
    """Run one command through the engine's own `main`; it must print exactly one JSON object on one line."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main([str(part) for part in argv])
    text = buffer.getvalue()
    assert text.endswith("\n") and text.count("\n") == 1, (argv, text)
    printed = json.loads(text)
    assert isinstance(printed, dict), (argv, text)
    return code, printed


@contextlib.contextmanager
def _local_site():
    """An invented page on a server on 127.0.0.1; robots.txt and everything else answer 404."""
    page = ("<html><body><p>" + "Competitor A adds two filling lines at Plant North (invented). " * 6 +
            "</p></body></html>").encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            found = self.path == "/news"
            self.send_response(200 if found else 404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            body = page if found else b"not found"
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


META = ["--publisher", "Competitor A", "--title", "Lines", "--date", "2026-05-14", "--type", "company_release",
        "--speaker", "its press office", "--interest", "wants to look strong", "--language", "en"]
GOOD_PROPOSAL = {"kind": "general", "statement": "Competitor A says the new lines are for its own products.",
                 "quote": "The two new lines will fill only Competitor A's own injectable products",
                 "quote_language": "en", "source_id": "S1", "primary_source": True, "certainty": "firm"}


class World:
    """The invented runs the commands are run on, each built when first asked for."""

    def __init__(self, root: Path, monkeypatch) -> None:
        self.root, self.monkeypatch, self._built = root, monkeypatch, {}

    def demo(self, name: str, **kwargs) -> Path:
        if name not in self._built:
            self._built[name] = build_demo_run(self.root / name, **kwargs)
        return self._built[name]

    def file(self, name: str, content) -> Path:
        path = self.root / "files" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
        return path

    def save_source(self) -> tuple[int, dict]:
        self.monkeypatch.setattr(fetch, "check_address", lambda host, resolve=None: fetch.PUBLIC)   # 127.0.0.1
        for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
            self.monkeypatch.delenv(name, raising=False)
        self.monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
        with _local_site() as base:
            code, printed = radar("save-source", "--run", self.demo("checked", stage="checked"),
                                  "--url", base + "/news", *META)
        assert printed["access"] == "ok", printed
        return code, printed

    def damaged(self) -> Path:
        """An extracted demo run whose fact F1 was edited by hand to an empty statement."""
        run = self.demo("damaged", stage="extracted")
        path = run / "facts" / "F1.json"
        fact = json.loads(path.read_text(encoding="utf-8"))
        fact["statement"] = ""
        path.write_text(json.dumps(fact), encoding="utf-8")
        return run

    def private_run(self) -> Path:
        """A private run that is not the practice run, so it takes an internal document."""
        if "private" not in self._built:
            self._built["private"] = Path(radar(
                "init-run", "--root", self.root / "private-runs", "--question", "Who builds?", "--pack", "demo",
                "--illustrative", "--mode", "private", "--acknowledge-data-flow", "--acknowledged-words",
                "Yes, go ahead (an invented reply).", "--run-id", "p1")[1]["run_dir"])
        return self._built["private"]

    def setup(self) -> tuple[int, dict]:
        original = setup_env.setup

        def fake_run(command, **kwargs):   # no download: both commands of setup answer as if they had worked
            return subprocess.CompletedProcess(command, 0, "", "")

        self.monkeypatch.setattr(setup_env, "setup", lambda home, python: original(home, python, run=fake_run))
        return radar("setup", "--home", self.root / "radar-home")

    def note_on_standard_input(self, *argv) -> tuple[int, dict]:
        """record-support with its note on standard input, the way the support checker sends it."""
        note = io.TextIOWrapper(io.BytesIO(b"The quote says what the fact says.\n"), encoding="utf-8")
        self.monkeypatch.setattr("sys.stdin", note)
        return radar("record-support", "--run", self.demo("checked", stage="checked"), "--passed", "true",
                     "--by", "support-checker", "--note-stdin", *argv)


def _cases(w: World) -> dict:
    """(command, label) -> list of (exit code, a function that runs the command and returns what it printed)."""
    complete = lambda: w.demo("complete")                       # noqa: E731
    checked = lambda: w.demo("checked", stage="checked")        # noqa: E731
    run = lambda *argv: (lambda: radar(*argv))                  # noqa: E731
    return {
        ("--version", None): [(0, run("--version"))],
        ("init-run", None): [(0, lambda: radar("init-run", "--root", w.root / "runs", "--question", "Who builds?",
                                               "--pack-file", PACK, "--run-id", "r1")),
                             (0, lambda: radar("init-run", "--root", w.root / "runs", "--question", "Who builds?",
                                               "--pack", "demo", "--run-id", "r2"))],
        ("init-run", "exit 1, the pack file has problems"): [
            (1, lambda: radar("init-run", "--root", w.root / "runs", "--question", "Q",
                              "--pack-file", w.file("bad.json", {"id": "bad"})))],
        ("init-run", "exit 2, private mode not acknowledged"): [
            (2, lambda: radar("init-run", "--root", w.root / "runs", "--question", "Q", "--pack", "demo",
                              "--mode", "private"))],
        ("add-fact", None): [(0, lambda: radar("add-fact", "--run", checked(),
                                               "--file", w.file("proposal.json", GOOD_PROPOSAL)))],
        ("add-facts", None): [(0, lambda: radar("add-facts", "--run", checked(),
                                                "--file", w.file("proposals.json", [GOOD_PROPOSAL]))),
                              (1, lambda: radar("add-facts", "--run", checked(), "--file", w.file(
                                  "mixed.json", [GOOD_PROPOSAL, {**GOOD_PROPOSAL, "quote": "too short"}])))],
        ("checkpoint", None): [(0, lambda: radar("checkpoint", "--run", checked(), "--name", "lenses",
                                                 "--answered-by", "test", "--answer", "Use both lenses."))],
        ("log-search", None): [(0, lambda: radar("log-search", "--run", checked(), "--place", "Company websites",
                                                 "--result", "Found one release"))],
        ("log-excluded", None): [(0, lambda: radar("log-excluded", "--run", checked(), "--what", "Source S4",
                                                   "--why", "Nothing on this question.", "--source", "S4"))],
        ("save-source", None): [(0, w.save_source)],
        ("add-copy", None): [(0, lambda: radar("add-copy", "--run", checked(), "--file", w.file(
            "note.txt", "A text saved by hand for the reference check, long enough to be read as a source."),
            "--url", "https://www.site-a.example/note", "--data-class", "public", *META)),
                             (0, lambda: radar("add-copy", "--run", w.private_run(), "--file", w.file(
                                 "memo.txt", "An invented internal memo, long enough to be read as a source here."),
                                 "--url", "internal://memo", "--data-class", "internal", "--supplied-by", "the tester",
                                 "--basis", "own company document", *META))],
        ("add-copy", "exit 2, the practice run refuses non-public material"): [
            (2, lambda: radar("add-copy", "--run", w.demo("practice", private=True, stage="sources"),
                              "--file", w.file("memo.txt", "An invented internal memo."), "--url", "internal://memo",
                              "--data-class", "internal", "--supplied-by", "the tester", "--basis", "own memo",
                              *META))],
        ("add-based-on", None): [(0, lambda: radar("add-based-on", "--run", checked(), "--source", "S5",
                                                   "--on", "S1"))],
        ("check-data", None): [(0, lambda: radar("check-data", "--run", complete(), "--lenses", LENSES)),
                               (1, lambda: radar("check-data", "--run", w.damaged()))],
        ("check-quotes", None): [(0, lambda: radar("check-quotes", "--run", checked()))],
        ("record-support", None): [(0, lambda: radar("record-support", "--run", checked(), "--fact", "F1",
                                                     "--passed", "true", "--by", "support checker",
                                                     "--note", "The quote says what the fact says.")),
                                   (0, lambda: w.note_on_standard_input("--fact", "F2"))],
        ("withdraw-fact", None): [(0, lambda: radar("withdraw-fact", "--run", checked(), "--fact", "F2",
                                                    "--reason", "Duplicate of F1."))],
        ("quote-context", None): [(0, lambda: radar("quote-context", "--run", checked(), "--fact", "F1")),
                                  (0, lambda: radar("quote-context", "--run", w.demo("extracted", stage="extracted"),
                                                    "--open", "--sentences", "2"))],
        ("settle", None): [(0, lambda: radar("settle", "--run", checked()))],
        ("gate", None): [(0, lambda: radar("gate", "--run", complete(), "--lenses", LENSES)),
                         (1, lambda: radar("gate", "--run", w.demo("tampered", tampered=True), "--lenses", LENSES))],
        ("build-report", None): [(0, lambda: radar("build-report", "--run", complete(), "--lenses", LENSES))],
        ("build-report", "exit 1, the gate refuses"): [
            (1, lambda: radar("build-report", "--run", w.demo("tampered", tampered=True), "--lenses", LENSES))],
        ("status", "--run"): [(0, lambda: radar("status", "--run", complete(), "--lenses", LENSES))],
        ("status", "--root"): [(0, lambda: (complete(), radar("status", "--root", w.root / "complete"))[1])],
        ("calc", None): [(0, lambda: radar("calc", "--run", complete(), "--operation", "share", "--unit", "lines",
                                           "--facts", "F4", "--of", "F1,F2,F3,F4,F6")),
                         (1, lambda: radar("calc", "--run", complete(), "--operation", "sum", "--unit", "lines",
                                           "--facts", "F8"))],
        ("compare", None): [(0, lambda: radar("compare", "--previous", complete(),
                                              "--current", w.demo("changed", changed=True), "--today", "2029-01-01"))],
        ("compare", "exit 2, the runs may not be compared"): [
            (2, lambda: radar("compare", "--previous", w.demo("practice", private=True, stage="sources"),
                              "--current", w.demo("changed", changed=True)))],
        ("check-pack", None): [(0, lambda: radar("check-pack", "--file", PACK, "--today", "2026-11-12")),
                               (1, lambda: radar("check-pack", "--file", w.file("broken.json", {"id": "broken"}))),
                               (1, lambda: radar("check-pack", "--file", w.file("empty.json", "")))],
        ("demo", None): [(0, lambda: radar("demo", "--root", w.root / "demo-command"))],
        ("demo", "--variant private"): [(0, lambda: radar("demo", "--root", w.root / "demo-command",
                                                          "--variant", "private", "--stage", "sources"))],
        ("doctor", None): [(0, run("doctor"))],
        ("setup", None): [(0, w.setup)],
        ("setup", "--dry-run"): [(0, lambda: radar("setup", "--home", w.root / "radar-home", "--dry-run"))],
    }


def _matches(shape: dict, value, where: str, seen: set) -> list[str]:
    if not isinstance(value, dict):
        return [f"{where}: expected an object, got {value!r}"]
    problems = []
    if list(value) != list(shape):   # the same keys, in the order the command prints them
        problems.append(f"{where}: printed {list(value)}, documented {list(shape)}")
    for name, spec in shape.items():
        if name in value and spec is not None:
            problems += _check(spec, value[name], f"{where}.{name}", seen)
    return problems


def _check(spec, value, where: str, seen: set) -> list[str]:
    kind, inner = spec
    if kind == "list":
        if not isinstance(value, list):
            return [f"{where}: expected a list, got {value!r}"]
        if value:
            seen.add(where)
        return [problem for item in value for problem in _matches(inner, item, where + "[]", seen)]
    if kind == "object":
        if value is None:   # an object the reference says may be null
            return []
        seen.add(where)
        return _matches(inner, value, where, seen)
    if not isinstance(value, dict):
        return [f"{where}: expected an object keyed by ids, got {value!r}"]
    problems = []
    for key, item in value.items():
        if inner is not None and item is not None:
            seen.add(where)
            problems += _matches(inner, item, f"{where}{{ID}}", seen)
    return problems


def _nested(shape: dict, where: str) -> set[str]:
    """Every nested path the reference documents below `where`."""
    paths = set()
    for name, spec in shape.items():
        if spec is None or spec[1] is None:
            continue
        kind, inner = spec
        path = f"{where}.{name}"
        paths.add(path)
        paths |= _nested(inner, path + ("[]" if kind == "list" else "{ID}" if kind == "ids" else ""))
    return paths


# Nested parts the demo cannot fill, each with the reason. They are still documented.
NOT_FILLED_BY_THE_DEMO = {
    "compare.possible_matches": "no fact of the changed demo differs from an earlier one in exactly one key field",
    "compare.source_unavailable": "every source of the changed demo could be read",
}


def test_every_documented_output_is_what_the_command_prints(tmp_path, monkeypatch):
    world, documented = World(tmp_path, monkeypatch), blocks()
    cases = _cases(world)
    lines = {(command, label) for command, block in documented.items() for label in block["prints"]}
    assert sorted(lines, key=str) == sorted(cases, key=str), "every prints line has its case here, and the other way"
    problems, seen, wanted = [], set(), set()
    for (command, label), runs in cases.items():
        shape = documented[command]["prints"][label]
        where = command if label is None else f"{command} ({label})"
        wanted |= {path.replace(where, command, 1) for path in _nested(shape, where)}
        expected_exit = int(label[5]) if label and label.startswith("exit ") else None
        for code, call in runs:
            assert code == (expected_exit if expected_exit is not None else code), (command, label)
            got_code, printed = call()
            if got_code != code:
                problems.append(f"{where}: exit {got_code}, expected {code}: {printed}")
            if got_code not in exit_codes(documented[command]):
                problems.append(f"{where}: exit {got_code} is not named on the exit line")
            found = set()
            problems += _matches(shape, printed, where, found)
            seen |= {path.replace(where, command, 1) for path in found}
    assert problems == []
    assert wanted - seen == set(NOT_FILLED_BY_THE_DEMO)


def _refusals(w: World, monkeypatch) -> dict:
    """command -> list of (exit code, call, shape): shape is a prints label of the command's block, None for its
    plain prints line, "error" or "error busy" for the general rules of the reference."""
    not_a_run = w.root / "not-a-run"
    not_a_run.mkdir(exist_ok=True)
    complete = lambda: w.demo("complete")                       # noqa: E731
    checked = lambda: w.demo("checked", stage="checked")        # noqa: E731

    def unreadable_record(name: str) -> Path:
        """An extracted demo run whose run.json was emptied."""
        run = w.demo(name, stage="extracted")
        (run / "run.json").write_bytes(b"")
        return run

    def busy():
        run = w.demo("busy", stage="sources")
        monkeypatch.setattr(store, "LOCK_WAIT_SECONDS", 0.2)
        with store.locked(run, wait=None):   # another holder keeps the run busy
            return radar("log-search", "--run", run, "--place", "p", "--result", "r")

    def no_pdf_library():
        import sys
        monkeypatch.setitem(sys.modules, "pypdf", None)   # import pypdf now fails
        return radar("doctor")

    usual = {command: [(2, lambda command=command: radar(command, "--run", not_a_run, *extra), "error")]
             for command, extra in {
                 "add-fact": ["--file", PACK], "add-facts": ["--file", PACK], "check-quotes": [], "settle": [],
                 "check-data": [], "gate": [], "status": [], "quote-context": ["--open"],
                 "build-report": ["--lenses", LENSES], "calc": ["--operation", "count", "--facts", "F1"],
                 "record-support": ["--fact", "F1", "--passed", "true", "--by", "b", "--note", "n"],
                 "withdraw-fact": ["--fact", "F1", "--reason", "r"],
                 "checkpoint": ["--name", "lenses", "--answered-by", "test", "--answer", "a"],
                 "log-search": ["--place", "p", "--result", "r"], "log-excluded": ["--what", "w", "--why", "y"],
                 "add-based-on": ["--source", "S2", "--on", "S1"],
                 "save-source": ["--url", "https://www.site-a.example/x", *META],
                 "add-copy": ["--file", PACK, "--url", "https://www.site-a.example/x", "--data-class", "public",
                              *META]}.items()}
    more = {
        "init-run": [(1, lambda: radar("init-run", "--root", w.root / "runs", "--question", "Q",
                                       "--pack-file", w.file("bad.json", {"id": "bad"})),
                      "exit 1, the pack file has problems"),
                     (2, lambda: radar("init-run", "--root", w.root / "runs", "--question", "Q", "--pack", "demo",
                                       "--mode", "private"), "exit 2, private mode not acknowledged"),
                     (2, lambda: radar("init-run", "--root", w.root / "runs", "--question", "Q", "--pack", "demo",
                                       "--pack-file", PACK), "error")],
        "add-fact": [(2, lambda: radar("add-fact", "--run", checked(), "--file", w.file(
            "short.json", {**GOOD_PROPOSAL, "quote": "too short"})), "error")],
        "add-facts": [(1, lambda: radar("add-facts", "--run", checked(), "--file", w.file(
            "unknown-source.json", [{**GOOD_PROPOSAL, "source_id": "S99"}])), None)],
        "add-copy": [(2, lambda: radar("add-copy", "--run", w.demo("practice", private=True, stage="sources"),
                                       "--file", w.file("memo.txt", "An invented internal memo."),
                                       "--url", "internal://memo", "--data-class", "internal",
                                       "--supplied-by", "the tester", "--basis", "own memo", *META),
                      "exit 2, the practice run refuses non-public material")],
        "save-source": [(2, lambda: radar("save-source", "--run", checked(), "--url", "ftp://www.site-a.example/x",
                                          *META), "error")],
        "check-quotes": [], "settle": [(2, lambda: radar("settle", "--run", unreadable_record("no-record")), "error")],
        "record-support": [(2, lambda: radar("record-support", "--run", checked(), "--fact", "F99", "--passed",
                                             "false", "--by", "b", "--note", "n"), "error"),
                           (2, lambda: w.note_on_standard_input("--fact", "F1", "--note", "n"), "error")],
        "withdraw-fact": [(2, lambda: radar("withdraw-fact", "--run", checked(), "--fact", "F1", "--reason", " "),
                           "error")],
        "quote-context": [(2, lambda: radar("quote-context", "--run", checked(), "--fact", "F1", "--open"), "error")],
        "checkpoint": [(2, lambda: radar("checkpoint", "--run", checked(), "--name", "other", "--answered-by", "test",
                                         "--answer", "a"), "error")],
        "log-search": [(2, busy, "error busy")],
        "log-excluded": [(2, lambda: radar("log-excluded", "--run", checked(), "--what", "w", "--why", "y",
                                           "--source", "S99"), "error")],
        "add-based-on": [(2, lambda: radar("add-based-on", "--run", checked(), "--source", "S1", "--on", "S1"),
                          "error")],
        "check-data": [(1, lambda: radar("check-data", "--run", w.damaged()), None),
                       (1, lambda: radar("check-data", "--run", unreadable_record("no-record")), None)],
        "gate": [(1, lambda: radar("gate", "--run", w.demo("tampered", tampered=True), "--lenses", LENSES), None),
                 (1, lambda: radar("gate", "--run", unreadable_record("no-record")), None)],
        "build-report": [(1, lambda: radar("build-report", "--run", w.demo("tampered", tampered=True),
                                           "--lenses", LENSES), "exit 1, the gate refuses")],
        "status": [(2, lambda: radar("status", "--run", complete(), "--root", w.root), "error"),
                   (2, lambda: radar("status", "--run", unreadable_record("no-record")), "error")],
        "calc": [(1, lambda: radar("calc", "--run", complete(), "--operation", "sum", "--unit", "lines",
                                   "--facts", "F99"), None),
                 (2, lambda: radar("calc", "--run", complete(), "--operation", "sum", "--facts", ","), "error")],
        "compare": [(2, lambda: radar("compare", "--previous", w.demo("practice", private=True, stage="sources"),
                                      "--current", w.demo("changed", changed=True)),
                     "exit 2, the runs may not be compared"),
                    (2, lambda: radar("compare", "--previous", not_a_run, "--current", complete()), "error")],
        "check-pack": [(1, lambda: radar("check-pack", "--file", w.file("broken.json", {"id": "broken"})), None),
                       (2, lambda: radar("check-pack", "--file", w.root / "missing.json"), "error")],
        "demo": [(2, lambda: (complete(), radar("demo", "--root", w.root / "complete"))[1], "error")],
        "doctor": [(1, no_pdf_library, None)],
        "setup": [(2, lambda: radar("setup", "--home", PACK, "--dry-run"), "error")],
    }
    cases = {command: list(runs) for command, runs in usual.items()}
    for command, runs in more.items():
        cases.setdefault(command, []).extend(runs)
    return cases


def test_every_refusal_ends_with_a_code_its_block_names_and_prints_the_shape_the_reference_gives(tmp_path,
                                                                                                    monkeypatch):
    world, documented = World(tmp_path, monkeypatch), blocks()
    cases = _refusals(world, monkeypatch)
    assert sorted(cases) == sorted(subcommands()), "every command has its refusal cases here"
    assert all(cases[command] for command in cases), [command for command in cases if not cases[command]]
    general = {"error": {"error": None}, "error busy": {"error": None, "busy": None}}
    assert 'prints `{"error": "..."}` with exit code 2' in reference()
    assert '"busy": true' in reference()
    assert ("`The record of the run in <folder> cannot be read: its file run.json is damaged or cannot be opened. "
            "Nothing was changed.`") in reference()
    assert ("`gate` and `check-data` report such a record as a problem (`run.json`: `run.json may not be opened` "
            "when this user may not open it, otherwise `not valid JSON`") in reference()
    problems = []
    for command, runs in cases.items():
        for code, call, shape_name in runs:
            got_code, printed = call()
            if got_code != code:
                problems.append(f"{command} ({shape_name}): exit {got_code}, expected {code}: {printed}")
            if got_code not in exit_codes(documented[command]):
                problems.append(f"{command} ({shape_name}): exit {got_code} is not named on the exit line")
            shape = general.get(shape_name) if shape_name in general else documented[command]["prints"][shape_name]
            problems += _matches(shape, printed, f"{command} ({shape_name})", set())
    assert problems == []


# --- what else the reference must state exactly --------------------------------------------------------------------

def test_help_prints_usage_text_not_json_and_exits_0(capsys):
    for argv in (["--help"], ["init-run", "--help"], ["quote-context", "--help"]):
        assert main(argv) == 0
        text = capsys.readouterr().out
        assert text.startswith("usage: radar") and not text.lstrip().startswith("{")
    assert "`--help` prints usage text, not JSON, and exits with 0" in reference()


def test_the_status_steps_and_state_words_are_named_exactly():
    text = reference()
    assert "`" + "`, `".join(status.STEPS) + "`" in text
    assert "`done`, `in_progress`, `pending` or `blocked`" in text


def test_the_status_command_prints_only_the_documented_state_words(tmp_path):
    states = set()
    for stage in ("sources", "extracted", "checked", "complete"):
        run = build_demo_run(tmp_path / stage, stage=stage)
        printed = status.run_status(run, LENSES)
        assert [step["name"] for step in printed["steps"]] == list(status.STEPS)
        states |= {step["state"] for step in printed["steps"]}
    run = build_demo_run(tmp_path / "tampered", tampered=True)
    states |= {step["state"] for step in status.run_status(run, LENSES)["steps"]}
    run = build_demo_run(tmp_path / "withdrawn", stage="checked")
    store_fact = store.read_facts(run)["F1"]
    store_fact["withdrawn"] = {"reason": "Duplicate.", "at": "2026-11-13T10:00:00Z"}   # not settled again since
    store.write_fact(run, store_fact)
    states |= {step["state"] for step in status.run_status(run, LENSES)["steps"]}
    assert states == {"done", "in_progress", "pending", "blocked"}


def _table(header: str) -> dict[str, dict]:
    """The table in the reference whose header row starts with `| <header> |`: key -> type, required, values."""
    lines = reference().splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith(f"| {header} |"))
    assert [cell.strip() for cell in lines[start].split("|")[2:5]] == ["Type", "Required", "Values"], header
    rows = {}
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        rows[cells[0].strip("`")] = {"type": cells[1], "required": cells[2],
                                     "values": re.findall(r"`([^`]+)`", cells[3])}
    return rows


# Each documented type: the basic type of value the key takes, and whether null is allowed too.
TYPES = {"text": ("text", False), "text or null": ("text", True), "true or false": ("true or false", False),
         "list": ("list", False), "list or null": ("list", True), "object or null": ("object", True)}
# One value of each basic type. A key takes its documented type and refuses each of the others.
OTHER_TYPES = {"text": "An invented text.", "number": 5, "true or false": True, "list": ["x"], "object": {"x": "y"}}
CHOICES = {"kind": schema.FACT_KINDS, "certainty": store.CERTAINTY, "move_type": store.MOVE_TYPES,
           "stage": store.STAGES, "access": store.ACCESS, "delivery": store.DELIVERY}
QUOTE = "Competitor A will add a second filling line at Plant North by 2028."
# The kinds of proposal every row is tried in: the base (a capacity move, quote in English, firm) and one for each
# condition a Required cell may name. Each is a complete proposal that the program accepts; `...` leaves a key out.
CONTEXTS = {
    "base": {},
    "a quote in another language": {"quote_language": "de", "quote_translation": "The quote in English (invented)."},
    "a tentative fact": {"certainty": "tentative", "tentative_reason": "An invented reason."},
    "a general fact": {"kind": "general", "fields": ...},
}


@pytest.fixture
def proposal_run(tmp_path):
    from helpers import add_source, make_run
    run = make_run(tmp_path)
    add_source(run, QUOTE)
    add_source(run, QUOTE + " The paper said so.", publisher="Trade Paper")
    return run


def _base():
    from helpers import proposal
    return proposal(supporting=[{"source_id": "S2", "quote": QUOTE}])


def _target(proposal: dict, table: str):
    """The object of the proposal that holds the keys of the given table; None when the proposal has none."""
    return (proposal if table == "proposal" else proposal["supporting"][0] if table == "supporting"
            else proposal.get("fields"))


def _in_context(context: dict) -> dict:
    proposal = _base()
    for name, item in context.items():
        if item is ...:
            proposal.pop(name, None)
        else:
            proposal[name] = item
    return proposal


def _field(table: str, key: str) -> str:
    return {"proposal": key, "supporting": f"supporting[0].{key}", "fields": f"fields.{key}"}[table]


def _refused(run, proposal: dict, table: str, key: str) -> bool:
    return any(problem.field == _field(table, key) for problem in schema.check_proposal(run, proposal))


_WHEN = re.compile(r"when `(\w+)` is (not )?`(\w+)`")


def _is_required(cell: str, proposal: dict) -> bool:
    """What a Required cell says about one proposal. The cell is one of four fixed forms; any other fails."""
    if cell in ("yes", "no"):
        return cell == "yes"
    found = _WHEN.fullmatch(cell)
    assert found, f"a Required cell that is not in one of the fixed forms: {cell!r}"
    key, negated, value = found.groups()
    return (proposal.get(key) != value) if negated else (proposal.get(key) == value)


def _samples(row: dict, current) -> list:
    """Values of the type the row documents that the key must take: the one the base proposal holds, one of the
    listed values, or a plain one."""
    basic = TYPES[row["type"]][0]
    if basic == "true or false":
        return [True, False]
    if basic == "list":
        return [[], current] if isinstance(current, list) else [[]]
    if basic == "object":
        return [current] if isinstance(current, dict) else [{}]
    if row["values"]:
        return list(row["values"])
    return [current if isinstance(current, str) else OTHER_TYPES["text"]]


TABLES = {"proposal": "Key of a proposal", "supporting": "Key of a supporting entry", "fields": "Key inside `fields`"}


def _table_problems(run, table: str, rows: dict[str, dict]) -> list[str]:
    """Everything the table says about a key that the program's own proposal check does not do."""
    problems = []
    for name, context in CONTEXTS.items():
        assert schema.check_proposal(run, _in_context(context)) == [], name

    def tried(context: dict, key: str, value) -> dict | None:
        """The proposal of the context with the key set to the value (`...` leaves it out); None when the proposal
        has no place for the key (a general fact holds no `fields`)."""
        proposal = _in_context(context)
        target = _target(proposal, table)
        if target is None:
            return None
        if value is ...:
            target.pop(key, None)
        else:
            target[key] = value
        return proposal

    for key, row in rows.items():
        if row["type"] not in TYPES:
            problems.append(f"{key}: a Type cell that is not in one of the fixed forms: {row['type']!r}")
            continue
        basic, null_allowed = TYPES[row["type"]]
        applies = set()   # whether the key was seen required, and seen not required
        for name, context in CONTEXTS.items():
            left_out = tried(context, key, ...)
            if left_out is None:
                continue
            required = _is_required(row["required"], left_out)
            applies.add(required)
            where = f"{key} in {name}"
            if _refused(run, left_out, table, key) != required:   # left out: refused exactly where it is required
                problems.append(f"{where}: left out is {'accepted' if required else 'refused'}, "
                                f"the Required cell says {row['required']!r}")
            null_refused = _refused(run, tried(context, key, None), table, key)
            if required and not null_refused:
                problems.append(f"{where}: null is accepted where the key is required")
            if not required and null_refused == null_allowed:   # null: taken exactly where the type says "or null"
                problems.append(f"{where}: null is {'refused' if null_refused else 'accepted'}, "
                                f"the Type cell says {row['type']!r}")
            for other, value in OTHER_TYPES.items():   # a value of every other basic type: refused
                if other != basic and not _refused(run, tried(context, key, value), table, key):
                    problems.append(f"{where}: a value of the type {other} is accepted, "
                                    f"the Type cell says {row['type']!r}")
        if row["required"] not in ("yes", "no") and applies != {True, False}:
            problems.append(f"{key}: the Required cell {row['required']!r} is not tried both where it applies and "
                            f"where it does not")
        if null_allowed and False not in applies:
            problems.append(f"{key}: the Type cell {row['type']!r} allows null, but the key is always required")
        # The contexts in which a value of the documented type is tried: where the key is required, or else the base.
        homes = [context for context in CONTEXTS.values() if tried(context, key, ...) is not None
                 and _is_required(row["required"], tried(context, key, ...))] or [CONTEXTS["base"]]
        for context in homes:
            current = _target(_in_context(context), table).get(key)
            for value in _samples(row, current):   # a value of the documented type: accepted
                if _refused(run, tried(context, key, value), table, key):
                    problems.append(f"{key}: the value {value!r} is refused, the Type cell says {row['type']!r}")
            if row["values"] and not _refused(run, tried(context, key, "not_one_of_them"), table, key):
                problems.append(f"{key}: a value the Values cell does not list is accepted")
        if sorted(row["values"]) != sorted(CHOICES.get(key, ())):
            problems.append(f"{key}: the Values cell lists {row['values']}, the program {list(CHOICES.get(key, ()))}")
    return problems


@pytest.mark.parametrize("table", sorted(TABLES))
def test_the_proposal_tables_name_every_key_and_its_type_required_and_values_as_the_program_checks_them(
        proposal_run, table):
    rows = _table(TABLES[table])
    expected = {"proposal": set(schema.FACT_KEYS) - set(schema.PROGRAM_KEYS), "supporting": set(schema.SUPPORTING_KEYS),
                "fields": set(schema.CAPACITY_MOVE_FIELDS)}[table]
    assert set(rows) == expected
    assert _table_problems(proposal_run, table, rows) == []
    for key in schema.PROGRAM_KEYS:
        assert f"`{key}`" in reference(), key


def _changed(rows: dict, key: str, **cells) -> dict:
    return {**rows, key: {**rows[key], **cells}}


@pytest.mark.parametrize("table, key, cells", [
    ("proposal", "quote_translation", {"required": "no"}),
    ("proposal", "quote_translation", {"required": "yes"}),
    ("proposal", "quote_translation", {"required": "when `quote_language` is `en`"}),
    ("proposal", "tentative_reason", {"required": "no"}),
    ("proposal", "tentative_reason", {"required": "when `certainty` is not `tentative`"}),
    ("proposal", "tentative_reason", {"required": "when `certainty` is `likely`"}),   # a value never tried
    ("proposal", "fields", {"required": "no"}),
    ("proposal", "supporting", {"required": "yes"}),
    ("proposal", "primary_source", {"type": "text"}),
    ("proposal", "supporting", {"type": "text"}),
    ("proposal", "supporting", {"type": "text or null"}),
    ("proposal", "quote_translation", {"type": "text"}),
    ("fields", "site", {"type": "text"}),
    ("fields", "company", {"type": "text or null"}),
    ("proposal", "statement", {"type": "true or false"}),
    ("proposal", "statement", {"type": "text or null"}),
    ("proposal", "fields", {"type": "list"}),
    ("proposal", "early_signal", {"type": "text or null"}),
    ("proposal", "certainty", {"values": ["firm"]}),
    ("supporting", "quote", {"required": "no"}),
    ("supporting", "quote", {"type": "list"}),
    ("supporting", "quote_translation", {"required": "when `quote_language` is not `en`"}),
    ("fields", "site", {"required": "yes"}),
    ("fields", "company", {"required": "no"}),
    ("fields", "size_value", {"type": "list"}),
    ("fields", "delivery", {"type": "true or false"}),
])
def test_a_table_that_says_something_else_than_the_program_does_is_caught(proposal_run, table, key, cells):
    rows = _table(TABLES[table])
    assert _table_problems(proposal_run, table, rows) == []
    assert _table_problems(proposal_run, table, _changed(rows, key, **cells)) != []


@pytest.mark.parametrize("cell", ["sometimes", "when `kind` is general", "yes, when `kind` is `general`", ""])
def test_a_required_cell_in_an_unknown_form_fails(proposal_run, cell):
    rows = _table(TABLES["proposal"])
    with pytest.raises(AssertionError, match="not in one of the fixed forms"):
        _table_problems(proposal_run, "proposal", _changed(rows, "statement", required=cell))


def test_a_type_cell_in_an_unknown_form_is_a_problem(proposal_run):
    rows = _table(TABLES["proposal"])
    problems = _table_problems(proposal_run, "proposal", _changed(rows, "statement", type="number"))
    assert problems == ["statement: a Type cell that is not in one of the fixed forms: 'number'"]


def test_the_access_reasons_of_a_source_are_all_named():
    code = (ROOT / "engine" / "radar" / "fetch.py").read_text(encoding="utf-8")
    reasons = set(re.findall(r'_Refused\("([a-z_]+)"\)', code))
    assert len(reasons) == 11 and 'f"http_{exc.code}"' in code
    for reason in reasons | {"http_404"}:
        assert f"`{reason}`" in reference(), reason


# --- A2 fix round 1, IMPORTANT 5: an example never starts a run on the invented pack without its mark -------------

def test_every_init_run_example_that_names_the_demo_pack_uses_the_pack_file():
    examples = [line for line in DOC.read_text(encoding="utf-8").splitlines()
                if re.search(r"\bradar init-run\b.*--pack", line)]
    assert examples, "the notes hold init-run examples"
    for line in examples:
        names_demo = re.search(r"--pack(?:-file)?[ =](?:\S*/)?demo(?:\.json)?\b", line)
        if names_demo:
            assert "--pack-file packs/demo.json" in line and not re.search(r"--pack[ =]demo\b", line), line
