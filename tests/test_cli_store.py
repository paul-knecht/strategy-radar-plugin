import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from radar import cli, store
from radar.cli import main
from helpers import make_run, add_source, add_fact, proposal, read_only_folder, unreadable_file

ROOT = Path(__file__).parent.parent


def run_cli(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr().out
    assert out.count("\n") == 1  # exactly one line
    return code, json.loads(out)


def test_init_run_prints_run_dir(tmp_path, capsys):
    code, out = run_cli(capsys, "init-run", "--root", str(tmp_path), "--question", "Q?",
                        "--pack", "demo", "--run-id", "r1", "--illustrative", "--home-company", "Acme")
    assert code == 0 and out == {"run_dir": str(tmp_path / "r1")}
    data = store.load_run(tmp_path / "r1")
    assert data["illustrative"] is True and data["home_company"] == "Acme"


def test_init_run_private_needs_flag(tmp_path, capsys):
    code, out = run_cli(capsys, "init-run", "--root", str(tmp_path), "--question", "Q",
                        "--pack", "demo", "--run-id", "r1", "--mode", "private")
    assert code == 2 and out == {"error": store.PRIVATE_NOTICE, "notice": store.PRIVATE_NOTICE_TEXT}
    assert not (tmp_path / "r1").exists()
    code, out = run_cli(capsys, "init-run", "--root", str(tmp_path), "--question", "Q",
                        "--pack", "demo", "--run-id", "r1", "--mode", "private", "--acknowledge-data-flow",
                        "--acknowledged-words", "Yes, go ahead.")
    assert code == 0 and (tmp_path / "r1" / ".gitignore").exists()


def test_init_run_existing_folder_is_error_json(tmp_path, capsys):
    args = ("init-run", "--root", str(tmp_path), "--question", "Q", "--pack", "demo", "--run-id", "r1")
    assert run_cli(capsys, *args)[0] == 0
    code, out = run_cli(capsys, *args)
    assert code == 2 and "error" in out


def test_add_fact_from_file_and_stdin(tmp_path, capsys, monkeypatch):
    run = make_run(tmp_path)
    src = add_source(run, "text")
    general = proposal(kind="general", fields=None, source_id=src["id"])
    f = tmp_path / "p.json"
    f.write_text(json.dumps(general), encoding="utf-8")
    code, out = run_cli(capsys, "add-fact", "--run", str(run), "--file", str(f))
    assert code == 0 and out == {"fact_id": "F1"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(general)))
    code, out = run_cli(capsys, "add-fact", "--run", str(run), "--file", "-")
    assert code == 0 and out == {"fact_id": "F2"}
    assert store.read_facts(run)["F2"]["status"] == "proposed"


def test_add_fact_bad_json_is_error(tmp_path, capsys):
    run = make_run(tmp_path)
    f = tmp_path / "p.json"
    f.write_text("{nope", encoding="utf-8")
    code, out = run_cli(capsys, "add-fact", "--run", str(run), "--file", str(f))
    assert code == 2 and "error" in out


def test_checkpoint_and_logs(tmp_path, capsys):
    run = make_run(tmp_path)
    assert run_cli(capsys, "checkpoint", "--run", str(run), "--name", "lenses",
                   "--answered-by", "test", "--answer", "both") == (0, {"ok": True})
    assert run_cli(capsys, "log-search", "--run", str(run), "--place", "p", "--result", "r") == (0, {"ok": True})
    assert run_cli(capsys, "log-excluded", "--run", str(run), "--what", "w", "--why", "y") == (0, {"ok": True})
    data = store.load_run(run)
    assert data["checkpoints"][0]["name"] == "lenses"
    assert data["search_log"] == [{"place": "p", "result": "r"}]
    assert data["excluded"] == [{"what": "w", "why": "y"}]


def test_checkpoint_value_error_is_usage_error(tmp_path, capsys):
    run = make_run(tmp_path)
    code, out = run_cli(capsys, "checkpoint", "--run", str(run), "--name", "lenses",
                        "--answered-by", "robot", "--answer", "x")
    assert code == 2 and "error" in out



# --- final fix I3: a bad proposal is refused before anything is written ---------------------------

def add_fact_cli(capsys, run, tmp_path, proposal_dict):
    f = tmp_path / "proposal.json"
    f.write_text(json.dumps(proposal_dict), encoding="utf-8")
    return run_cli(capsys, "add-fact", "--run", str(run), "--file", str(f))


def test_add_fact_refuses_a_proposal_that_breaks_the_fact_rules(tmp_path, capsys):
    run = make_run(tmp_path)
    add_source(run, "text")
    long_quote = " ".join(["word"] * 51)
    without_company = proposal(); del without_company["fields"]["company"]
    cases = [
        (proposal(statement=""), "statement"),
        ({k: v for k, v in proposal().items() if k != "quote_language"}, "quote_language"),
        (proposal(kind="rumour"), "kind"),
        (proposal(fields={"move_type": "takeover"}), "fields.move_type"),
        (without_company, "fields.company"),
        (proposal(quote="two new lines"), "quote"),
        (proposal(quote=long_quote), "quote"),
        (proposal(source_id="S9"), "source S9 does not exist"),
    ]
    for bad, named in cases:
        code, out = add_fact_cli(capsys, run, tmp_path, bad)
        assert code == 2 and named in out["error"], (named, out)
    assert store.read_facts(run) == {} and list((run / "facts").iterdir()) == []
    assert store.load_run(run)["facts_created"] == 0


def test_add_fact_accepts_a_complete_proposal(tmp_path, capsys):
    run = make_run(tmp_path)
    add_source(run, "text")
    assert add_fact_cli(capsys, run, tmp_path, proposal()) == (0, {"fact_id": "F1"})


# --- final fix I3: withdrawing a fact -------------------------------------------------------------

def test_withdraw_fact_records_the_reason_and_keeps_the_fact(tmp_path, capsys):
    run = make_run(tmp_path)
    add_source(run, "text"); add_fact(run)
    code, out = run_cli(capsys, "withdraw-fact", "--run", str(run), "--fact", "F1", "--reason", "duplicate of F2")
    assert code == 0 and out == {"ok": True}
    withdrawn = store.read_facts(run)["F1"]["withdrawn"]
    assert withdrawn["reason"] == "duplicate of F2" and withdrawn["at"].endswith("Z")


def test_withdraw_fact_needs_a_known_fact_and_a_reason(tmp_path, capsys):
    run = make_run(tmp_path)
    add_source(run, "text"); add_fact(run)
    for fact, reason in (("F9", "gone"), ("F1", ""), ("F1", "   ")):
        code, out = run_cli(capsys, "withdraw-fact", "--run", str(run), "--fact", fact, "--reason", reason)
        assert code == 2 and "error" in out
    assert "withdrawn" not in store.read_facts(run)["F1"]


def test_init_run_with_an_escaping_run_id_exits_2_and_creates_nothing_outside_the_root(tmp_path, capsys):
    root = tmp_path / "root"
    code, out = run_cli(capsys, "init-run", "--root", str(root), "--question", "Q", "--pack", "demo",
                        "--run-id", "../escaped")
    assert code == 2 and "error" in out
    assert not (tmp_path / "escaped").exists()


def test_log_excluded_with_a_source_records_it(tmp_path, capsys):
    run = make_run(tmp_path); add_source(run, "text of the source")
    assert run_cli(capsys, "log-excluded", "--run", str(run), "--what", "Source S1", "--why", "nothing usable",
                   "--source", "S1") == (0, {"ok": True})
    assert store.load_run(run)["excluded"] == [{"what": "Source S1", "why": "nothing usable", "source_id": "S1"}]


def test_log_excluded_refuses_an_unknown_source(tmp_path, capsys):
    run = make_run(tmp_path); add_source(run, "text of the source")
    for bad in ("S2", "s1", "1", "S1; rm"):
        code, out = run_cli(capsys, "log-excluded", "--run", str(run), "--what", "w", "--why", "y",
                            f"--source={bad}")
        assert code == 2 and "error" in out
    assert store.load_run(run)["excluded"] == []


def test_log_excluded_takes_the_source_through_from_json(tmp_path, capsys):
    run = make_run(tmp_path); add_source(run, "text of the source")
    options = tmp_path / "o.json"
    options.write_text(json.dumps({"run": str(run), "what": "Source S1", "why": "nothing", "source": "S1"}),
                       encoding="utf-8")
    assert run_cli(capsys, "log-excluded", "--from-json", str(options)) == (0, {"ok": True})
    assert store.load_run(run)["excluded"][0]["source_id"] == "S1"


# --- a root that is a file, or lies under a file, is a usage error ---------------------------------

def _file_roots(tmp_path):
    afile = tmp_path / "afile"
    afile.write_text("not a folder", encoding="utf-8")
    return [afile, afile / "sub"]


def test_init_run_refuses_a_root_that_is_a_file_or_lies_under_one(tmp_path, capsys):
    for root in _file_roots(tmp_path):
        code, out = run_cli(capsys, "init-run", "--root", str(root), "--question", "Q",
                            "--pack", "demo", "--run-id", "r1")
        assert code == 2 and list(out) == ["error"] and "is a file" in out["error"], root
    assert sorted(p.name for p in tmp_path.iterdir()) == ["afile"]


# --- Task 9: output on a terminal that is not set to UTF-8 --------------------------------------------------

def _radar_on_an_ascii_terminal(*argv):
    code = "import sys; from radar.cli import main; sys.exit(main())"
    return subprocess.run([sys.executable, "-c", code, *argv], capture_output=True,
                          env={**os.environ, "PYTHONPATH": str(ROOT / "engine"), "PYTHONIOENCODING": "ascii"})


def test_output_survives_a_terminal_that_is_not_utf8(tmp_path):
    run = make_run(tmp_path, question="Wer baut Kapazität für Spritzen?")
    result = _radar_on_an_ascii_terminal("status", "--run", str(run))
    assert result.returncode == 0, result.stderr
    assert result.stderr == b""
    assert json.loads(result.stdout.decode("utf-8"))["question"] == "Wer baut Kapazität für Spritzen?"


def test_a_usage_error_survives_a_terminal_that_is_not_utf8():
    result = _radar_on_an_ascii_terminal("Größe")          # not a command: the error text holds the word
    assert result.returncode == 2 and result.stderr == b""
    assert result.stdout.endswith(b"\n") and result.stdout.count(b"\n") == 1
    assert "Größe" in json.loads(result.stdout.decode("utf-8"))["error"]


class _ByteStream:
    """Standard output as a terminal gives it: text goes through a byte buffer, set to whatever encoding it likes."""
    def __init__(self):
        self.buffer = io.BytesIO()

    def write(self, text):
        raise UnicodeEncodeError("ascii", text, 0, 1, "this stream is not UTF-8")

    def flush(self):
        pass


LINE_BREAKS = chr(0x85) + chr(0x2028) + chr(0x2029)


def test_emit_writes_utf8_bytes_when_the_stream_has_a_buffer(monkeypatch):
    stream = _ByteStream()
    monkeypatch.setattr(sys, "stdout", stream)
    cli._emit({"text": "Größe „A“ 工場" + LINE_BREAKS})
    data = stream.buffer.getvalue()
    assert data.endswith(b"\n") and data.count(b"\n") == 1
    assert "Größe „A“ 工場".encode("utf-8") in data          # written as it is, not as escapes
    assert json.loads(data.decode("utf-8")) == {"text": "Größe „A“ 工場" + LINE_BREAKS}
    for raw in (chr(0x85), chr(0x2028), chr(0x2029)):          # the one line stays one line
        assert raw.encode("utf-8") not in data


def test_emit_prints_ascii_when_the_stream_has_no_buffer(monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stream)
    cli._emit({"text": "Größe „A“ 工場" + LINE_BREAKS})
    text = stream.getvalue()
    assert text.isascii() and text.endswith("\n") and text.count("\n") == 1
    assert json.loads(text) == {"text": "Größe „A“ 工場" + LINE_BREAKS}


@pytest.mark.parametrize("stream_class", [_ByteStream, io.StringIO])
def test_emit_never_raises_on_text_that_cannot_be_encoded(monkeypatch, stream_class):
    stream = stream_class()
    monkeypatch.setattr(sys, "stdout", stream)
    cli._emit({"text": "a" + chr(0xD800) + "b"})              # a lone surrogate
    data = stream.buffer.getvalue().decode("utf-8") if hasattr(stream, "buffer") else stream.getvalue()
    assert data.count("\n") == 1 and json.loads(data) == {"text": "a" + chr(0xD800) + "b"}


def test_emit_keeps_text_written_before_it_in_order(capsys):
    print("first")
    cli._emit({"second": 1})
    assert capsys.readouterr().out == 'first\n{"second": 1}\n'


# --- Task 9 (carried over): a run folder that exists, and a folder that cannot be written to --------------------

def test_init_run_into_an_existing_run_folder_says_so_in_plain_words(tmp_path, capsys):
    args = ("init-run", "--root", str(tmp_path), "--question", "Q", "--pack", "demo", "--run-id", "r1")
    assert run_cli(capsys, *args)[0] == 0
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in sorted(tmp_path.rglob("*")) if p.is_file()}
    code, out = run_cli(capsys, *args)
    assert code == 2
    assert out == {"error": f"The run folder {tmp_path / 'r1'} already exists, "
                            "so choose another run name or another folder."}
    assert "Errno" not in out["error"]
    assert before == {str(p.relative_to(tmp_path)): p.read_bytes() for p in sorted(tmp_path.rglob("*")) if p.is_file()}


def test_init_run_on_a_read_only_folder_says_so_in_plain_words(tmp_path, capsys):
    with read_only_folder(tmp_path) as folder:
        for root in (folder, folder / "runs"):
            code, out = run_cli(capsys, "init-run", "--root", str(root), "--question", "Q", "--pack", "demo",
                                "--run-id", "r1")
            assert code == 2
            assert out == {"error": f"The folder {folder} cannot be written to, "
                                    "so choose another folder for the run."}
        assert list(folder.iterdir()) == []


# --- Part A fix A1, M4: a folder where a file is expected, and any other system error, is one plain line ---------

COPY_META = ["--publisher", "Competitor A", "--title", "Expansion", "--date", "2026-05-14", "--type",
             "company_release", "--speaker", "the company", "--interest", "wants to look strong", "--language", "en"]


def test_add_copy_given_a_folder_names_it_in_one_plain_line(tmp_path, capsys):
    run = make_run(tmp_path)
    folder = tmp_path / "export.txt"
    folder.mkdir()
    code, out = run_cli(capsys, "add-copy", "--data-class", "public", "--run", str(run), "--file", str(folder), "--url",
                        "https://www.example.com/news", *COPY_META)
    assert code == 2 and out == {"error": f"{folder} is a folder, not a file. Give the path of a file."}
    assert store.read_sources(run) == {} and sorted(p.name for p in (run / "copies").iterdir()) == [".gitignore"]


def test_any_other_system_error_ends_as_one_line_with_exit_2(tmp_path, capsys, monkeypatch):
    run = make_run(tmp_path)

    def disk_full(*args, **kwargs):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(store, "log_search", disk_full)
    code, out = run_cli(capsys, "log-search", "--run", str(run), "--place", "p", "--result", "r")
    assert code == 2 and out == {"error": "[Errno 28] No space left on device"}

    def odd(*args, **kwargs):
        raise OSError()
    monkeypatch.setattr(store, "log_search", odd)
    assert run_cli(capsys, "log-search", "--run", str(run), "--place", "p", "--result", "r") == (2, {"error": "OSError"})


# --- Part A fix A2, item 4: init-run --pack-file ---------------------------------------------------------------

def _pack_file(tmp_path, name="demo", **over):
    """A copy of the illustrative pack in `tmp_path/packs`, with keys replaced; None removes a key."""
    data = json.loads((ROOT / "packs" / "demo.json").read_text(encoding="utf-8"))
    for key, value in over.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    folder = tmp_path / "packs"
    folder.mkdir(exist_ok=True)
    path = folder / f"{name}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _init(capsys, tmp_path, *extra):
    return run_cli(capsys, "init-run", "--root", str(tmp_path / "runs"), "--question", "Q", "--run-id", "r1", *extra)


def test_init_run_with_a_pack_file_takes_the_pack_id_and_its_illustrative_mark(tmp_path, capsys):
    code, out = _init(capsys, tmp_path, "--pack-file", str(_pack_file(tmp_path)))
    assert code == 0 and out == {"run_dir": str(tmp_path / "runs" / "r1")}
    run = store.load_run(tmp_path / "runs" / "r1")
    assert run["pack"] == "demo" and run["illustrative"] is True   # without --illustrative


@pytest.mark.parametrize("flag,expected", [((), False), (("--illustrative",), True)])
def test_a_pack_that_is_not_illustrative_leaves_the_choice_to_the_switch(tmp_path, capsys, flag, expected):
    path = _pack_file(tmp_path, name="acme-real", id="acme-real", illustrative=False)
    code, _ = _init(capsys, tmp_path, "--pack-file", str(path), *flag)
    run = store.load_run(tmp_path / "runs" / "r1")
    assert code == 0 and run["pack"] == "acme-real" and run["illustrative"] is expected


@pytest.mark.parametrize("over,field", [({"company": ""}, "company"), ({"illustrative": "yes"}, "illustrative"),
                                        ({"id": "other"}, "id"), ({"places": []}, "places")])
def test_a_pack_file_with_problems_is_refused_and_nothing_is_made(tmp_path, capsys, over, field):
    from radar.explain import explain
    from radar.schema import Problem
    code, out = _init(capsys, tmp_path, "--pack-file", str(_pack_file(tmp_path, **over)))
    assert code == 1 and list(out) == ["problems", "explained"]
    assert [problem["field"] for problem in out["problems"]] == [field]
    assert out["explained"] == [explain(Problem(**problem)) for problem in out["problems"]]
    assert all(entry["known"] for entry in out["explained"])
    assert not (tmp_path / "runs").exists()


def test_a_pack_file_that_cannot_be_read_is_refused_and_nothing_is_made(tmp_path, capsys):
    from radar import pack
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    code, out = _init(capsys, tmp_path, "--pack-file", str(broken))
    assert code == 1 and [problem["message"] for problem in out["problems"]] == [pack.NOT_READABLE]
    assert out["explained"][0]["known"] is True and not (tmp_path / "runs").exists()
    code, out = _init(capsys, tmp_path, "--pack-file", str(tmp_path / "missing.json"))   # no file at all: wrong use
    assert code == 2 and list(out) == ["error"] and not (tmp_path / "runs").exists()


@pytest.mark.parametrize("extra", [("--pack", "demo", "--pack-file", "PACK"), ()])
def test_pack_and_pack_file_together_or_neither_are_a_usage_error(tmp_path, capsys, extra):
    path = _pack_file(tmp_path)
    code, out = _init(capsys, tmp_path, *[str(path) if part == "PACK" else part for part in extra])
    assert code == 2 and list(out) == ["error"] and "--pack" in out["error"]
    assert not (tmp_path / "runs").exists()


def test_pack_alone_works_as_before(tmp_path, capsys):
    code, _ = _init(capsys, tmp_path, "--pack", "any words at all")
    run = store.load_run(tmp_path / "runs" / "r1")
    assert code == 0 and run["pack"] == "any words at all" and run["illustrative"] is False


def test_the_pack_file_can_come_through_from_json_and_private_mode_still_needs_the_acknowledgement(tmp_path, capsys):
    options = tmp_path / "options.json"
    options.write_text(json.dumps({"root": str(tmp_path / "runs"), "question": "Q", "run-id": "r1",
                                   "pack-file": str(_pack_file(tmp_path)), "mode": "private"}), encoding="utf-8")
    code, out = run_cli(capsys, "init-run", "--from-json", str(options))
    assert code == 2 and out["notice"] == store.PRIVATE_NOTICE_TEXT and not (tmp_path / "runs").exists()
    code, out = run_cli(capsys, "init-run", "--from-json", str(options), "--acknowledge-data-flow",
                        "--acknowledged-words", "Yes, go ahead.")
    run = store.load_run(tmp_path / "runs" / "r1")
    assert code == 0 and (run["pack"], run["illustrative"], run["mode"]) == ("demo", True, "private")


# --- A2 fix round 1, IMPORTANT 1 (ruling HG13): a folder that is not a run, and a named file that is not there ------

def _other_options(tmp_path) -> dict[str, list]:
    """For each command that takes --run, the rest of a command line that would be fine on a real run."""
    files = tmp_path / "files"
    files.mkdir(exist_ok=True)
    one = files / "proposal.json"
    one.write_text(json.dumps(proposal()), encoding="utf-8")
    many = files / "proposals.json"
    many.write_text(json.dumps([proposal()]), encoding="utf-8")
    text = files / "note.txt"
    text.write_text("An invented note that was saved by hand.", encoding="utf-8")
    lenses = files / "lenses"
    lenses.mkdir(exist_ok=True)
    recommendation = files / "recommendation.json"
    recommendation.write_text(json.dumps({"entries": [], "note": "No lens fits."}), encoding="utf-8")
    grouping = files / "projects.json"
    grouping.write_text(json.dumps({"projects": []}), encoding="utf-8")
    return {
        "add-fact": ["--file", one], "add-facts": ["--file", many],
        "join-proposals": ["--sources", "S1", "--out", files / "all.json"],
        "checkpoint": ["--name", "lenses", "--answered-by", "test", "--answer", "Use both."],
        "log-search": ["--place", "Company websites", "--result", "Nothing"],
        "log-excluded": ["--what", "A forecast", "--why", "Paywall"],
        "save-source": ["--url", "https://www.site-a.example/x", *COPY_META],
        "add-copy": ["--file", text, "--url", "https://www.site-a.example/x", "--data-class", "public",
                     *COPY_META],
        "add-based-on": ["--source", "S2", "--on", "S1"],
        "check-data": [], "check-quotes": [], "settle": [], "gate": [], "status": [],
        "record-support": ["--fact", "F1", "--passed", "true", "--by", "a checker", "--note", "Fine."],
        "withdraw-fact": ["--fact", "F1", "--reason", "Duplicate."],
        "quote-context": ["--open"],
        "build-report": ["--lenses", lenses],
        "calc": ["--operation", "count", "--facts", "F1"],
        "record-lens-recommendation": ["--lenses", lenses, "--by", "lens-advisor", "--file", recommendation],
        "lens-advisor-input": ["--lenses", lenses],
        "lens-link-context": ["--lenses", lenses],
        "lens-view": ["--lenses", lenses],
        "record-link-check": ["--lens", "firm-boundaries", "--fact", "F1", "--verdict", "bears",
                              "--by", "lens-link-reader", "--note", ""],
        "project-grouper-input": [],
        "record-projects": ["--by", "project-grouper", "--file", grouping],
        "claim-matcher-input": ["--sources", "S1"],
        "record-claim-groups": ["--sources", "S1", "--by", "claim-matcher", "--list-stdin"],
    }


def test_the_table_below_covers_every_command_that_takes_run(tmp_path):
    parser = cli.build_parser()
    commands = next(action.choices for action in parser._actions if isinstance(getattr(action, "choices", None), dict))
    takes_run = {name for name, sub in commands.items() if "--run" in sub._option_string_actions}
    assert takes_run == set(_other_options(tmp_path)) == set(TAKES_RUN)


def _snapshot(folder):
    return sorted(str(path.relative_to(folder)) for path in folder.rglob("*"))


TAKES_RUN = ["add-fact", "add-facts", "join-proposals", "checkpoint", "log-search", "log-excluded", "save-source",
             "add-copy", "add-based-on", "check-data", "check-quotes", "settle", "gate", "status", "record-support",
             "withdraw-fact", "quote-context", "build-report", "calc", "record-lens-recommendation",
             "lens-advisor-input", "lens-link-context", "lens-view", "record-link-check", "project-grouper-input",
             "record-projects", "claim-matcher-input", "record-claim-groups"]


@pytest.mark.parametrize("command", TAKES_RUN)
@pytest.mark.parametrize("kind", ["a plain folder", "a missing folder"])
def test_every_command_that_takes_run_refuses_a_folder_that_is_not_a_run_and_makes_nothing(
        tmp_path, capsys, monkeypatch, command, kind):
    from radar import fetch

    def no_lookup(host, *args, **kwargs):
        raise AssertionError(f"{host} was looked up")

    monkeypatch.setattr(fetch, "check_address", no_lookup)
    other = _other_options(tmp_path)[command]
    folder = tmp_path / "work" / "not-a-run"
    if kind == "a plain folder":
        folder.mkdir(parents=True)
    before = _snapshot(tmp_path)
    code, out = run_cli(capsys, command, "--run", str(folder), *[str(part) for part in other])
    assert code == 2 and list(out) == ["error"], (command, out)
    assert out["error"] == f"{folder} is not the folder of a run. Give the folder that init-run made for the run."
    assert _snapshot(tmp_path) == before   # no .lock, no record, nothing anywhere


@pytest.mark.parametrize("which", ["--previous", "--current"])
@pytest.mark.parametrize("kind", ["a plain folder", "a missing folder"])
def test_compare_refuses_a_folder_that_is_not_a_run_on_either_side(tmp_path, capsys, which, kind):
    run = make_run(tmp_path / "runs")
    folder = tmp_path / "work" / "not-a-run"
    if kind == "a plain folder":
        folder.mkdir(parents=True)
    before = _snapshot(tmp_path)
    sides = {"--previous": str(run), "--current": str(run), which: str(folder)}
    code, out = run_cli(capsys, "compare", *[part for pair in sides.items() for part in pair])
    assert code == 2 and out == {
        "error": f"{folder} is not the folder of a run. Give the folder that init-run made for the run."}
    assert _snapshot(tmp_path) == before


def test_a_run_folder_whose_run_record_was_deleted_is_not_a_run_for_gate_and_check_data(tmp_path, capsys):
    run = make_run(tmp_path)
    (run / "run.json").unlink()
    for command in ("gate", "check-data", "status", "build-report"):
        extra = ["--lenses", str(tmp_path)] if command == "build-report" else []
        code, out = run_cli(capsys, command, "--run", str(run), *extra)
        assert code == 2 and "is not the folder of a run" in out["error"], command


@pytest.mark.parametrize("kind", ["missing", "a folder"])
def test_a_named_file_that_is_missing_or_a_folder_is_wrong_use(tmp_path, capsys, kind):
    run = make_run(tmp_path / "runs")
    path = tmp_path / "named.json"
    if kind == "a folder":
        path.mkdir()
    message = (f"{path} is a folder, not a file. Give the path of a file." if kind == "a folder"
               else f"{path} does not exist. Give the path of a file.")
    lines = [
        ["add-fact", "--run", run, "--file", path],
        ["add-facts", "--run", run, "--file", path],
        ["add-copy", "--data-class", "public", "--run", run, "--file", path, "--url", "https://www.site-a.example/x", *COPY_META],
        ["check-pack", "--file", path],
        ["init-run", "--root", tmp_path / "new", "--question", "Q", "--pack-file", path],
    ]
    for argv in lines:
        code, out = run_cli(capsys, *[str(part) for part in argv])
        assert (code, out) == (2, {"error": message}), argv
    assert not (tmp_path / "new").exists() and store.read_sources(run) == {} and store.read_facts(run) == {}
    code, out = run_cli(capsys, "log-search", "--from-json", str(path))
    assert code == 2 and list(out) == ["error"]


@pytest.mark.parametrize("kind", ["missing", "a file"])
def test_a_lens_folder_that_is_missing_or_a_file_is_wrong_use(tmp_path, capsys, kind):
    run = make_run(tmp_path / "runs")
    path = tmp_path / "lenses"
    if kind == "a file":
        path.write_text("not a folder", encoding="utf-8")
    message = (f"{path} is a file, not a folder. Give the folder of the lens files." if kind == "a file"
               else f"{path} does not exist. Give the folder of the lens files.")
    for command in ("check-data", "gate", "build-report", "status"):
        code, out = run_cli(capsys, command, "--run", str(run), "--lenses", str(path))
        assert (code, out) == (2, {"error": message}), command


def test_a_pack_file_that_exists_but_has_problems_still_gives_problems_with_exit_1(tmp_path, capsys):
    from radar import pack
    path = tmp_path / "demo.json"
    path.write_text("{not json", encoding="utf-8")
    code, out = run_cli(capsys, "check-pack", "--file", str(path))
    assert code == 1 and [p["message"] for p in out["problems"]] == [pack.NOT_READABLE]
    code, out = run_cli(capsys, "init-run", "--root", str(tmp_path / "new"), "--question", "Q", "--pack-file", str(path))
    assert code == 1 and [p["message"] for p in out["problems"]] == [pack.NOT_READABLE]


# --- A2 fix round 2, point 5 (ruling HG18): a run whose record cannot be read ----------------------------------------

def _damage(run, kind: str) -> None:
    """Make the run's record unreadable in one of the ways that also work for a user who may read every file."""
    record = run / "run.json"
    if kind == "empty":
        record.write_bytes(b"")
    elif kind == "not JSON":
        record.write_text('{"question": "Who adds capacity?", ', encoding="utf-8")
    elif kind == "not an object":
        record.write_text('["a", "list"]', encoding="utf-8")
    elif kind == "not UTF-8":
        record.write_bytes(b'{"question": "\xff\xfe"}')
    elif kind == "a folder":
        record.unlink()
        record.mkdir()
    else:
        raise AssertionError(kind)


def _contents(folder) -> dict:
    """Every path under the folder with what can be seen of it, so "nothing was made or changed" can be checked.

    For each path: its kind, permissions, size and modification time (a folder's change when a file is made or
    removed in it, even for a moment), and what a file holds when this user may read it. A file nobody may read
    (see `unreadable_file`) is compared by everything but its contents."""
    import stat
    seen = {}
    for path in sorted(folder.rglob("*")):
        info = path.lstat()
        try:
            held = path.read_bytes() if stat.S_ISREG(info.st_mode) else None
        except PermissionError:
            held = "may not be read"
        seen[str(path.relative_to(folder))] = (stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode), info.st_size,
                                               info.st_mtime_ns, held)
    return seen


def _record_unreadable(run) -> str:
    return (f"The record of the run in {run} cannot be read: its file run.json is damaged or cannot be opened. "
            "Nothing was changed.")


DAMAGE = ["empty", "not JSON", "not an object", "not UTF-8", "a folder"]
REPORT_DAMAGE = ("gate", "check-data")   # finding damage is their job


NOT_JSON_EXPLAINED = {"known": True, "what": "A saved item of this run cannot be read.",
                      "why": "It is empty or damaged, often after a manual edit or an interrupted save.",
                      "do": "Restore it from a backup, or run the step that writes it again."}
NOT_OPENED_EXPLAINED = {
    "known": True, "what": "This run's basic details are saved, but your user account on this computer may not open them.",
    "why": "The setting for who may read the file was changed, often by hand or when the run was copied from another "
           "account or computer.",
    "do": "Allow your user account to read them again, for example in the run folder's settings for who may read each "
          "item, then check the run again."}


def _damaged_run_case(tmp_path, capsys, monkeypatch, command, damage, problem="not valid JSON", explained=None):
    from radar import fetch

    def no_lookup(host, *args, **kwargs):
        raise AssertionError(f"{host} was looked up")

    monkeypatch.setattr(fetch, "check_address", no_lookup)
    other = _other_options(tmp_path)[command]
    run = make_run(tmp_path / "runs")
    add_source(run, "Competitor A will add a second filling line at Plant North by 2028.")
    add_fact(run)
    with damage(run):
        before = _contents(tmp_path)
        code, out = run_cli(capsys, command, "--run", str(run), *[str(part) for part in other])
        after = _contents(tmp_path)
    assert after == before, command                     # no .lock, no record, no changed file
    if command in REPORT_DAMAGE:
        assert code == 1 and list(out)[-2:] == ["problems", "explained"], (command, out)
        place = out["problems"].index({"file": "run.json", "field": None, "message": problem})
        assert out["explained"][place] == (explained or NOT_JSON_EXPLAINED), (command, out)
        whole = [p for p in out["problems"] if p["file"] == "run.json" and p["field"] is None]
        assert whole == [out["problems"][place]], (command, out)            # the record is named by one message
    else:
        assert (code, out) == (2, {"error": _record_unreadable(run)}), (command, out)


@pytest.mark.parametrize("command", TAKES_RUN)
@pytest.mark.parametrize("kind", DAMAGE)
def test_a_run_whose_record_cannot_be_read_is_not_a_run_and_nothing_is_made_or_changed(
        tmp_path, capsys, monkeypatch, command, kind):
    import contextlib

    @contextlib.contextmanager
    def damage(run):
        _damage(run, kind)
        yield

    _damaged_run_case(tmp_path, capsys, monkeypatch, command, damage)


@pytest.mark.parametrize("command", TAKES_RUN)
def test_a_run_whose_record_may_not_be_opened_is_not_a_run_either(tmp_path, capsys, monkeypatch, command):
    # gate and check-data name it as what it is: the record is there, only this user may not open it
    _damaged_run_case(tmp_path, capsys, monkeypatch, command, lambda run: unreadable_file(run / "run.json"),
                      problem="run.json may not be opened", explained=NOT_OPENED_EXPLAINED)


@pytest.mark.parametrize("which", ["--previous", "--current"])
@pytest.mark.parametrize("kind", DAMAGE)
def test_compare_refuses_a_run_whose_record_cannot_be_read_on_either_side(tmp_path, capsys, which, kind):
    run = make_run(tmp_path / "runs")
    damaged = make_run(tmp_path / "runs", run_id="run2")
    _damage(damaged, kind)
    before = _contents(tmp_path)
    sides = {"--previous": str(run), "--current": str(run), which: str(damaged)}
    code, out = run_cli(capsys, "compare", *[part for pair in sides.items() for part in pair])
    assert (code, out) == (2, {"error": _record_unreadable(damaged)})
    assert _contents(tmp_path) == before


@pytest.mark.parametrize("which", ["--previous", "--current"])
def test_compare_refuses_a_run_whose_record_may_not_be_opened_on_either_side(tmp_path, capsys, which):
    run = make_run(tmp_path / "runs")
    damaged = make_run(tmp_path / "runs", run_id="run2")
    with unreadable_file(damaged / "run.json"):
        before = _contents(tmp_path)
        sides = {"--previous": str(run), "--current": str(run), which: str(damaged)}
        code, out = run_cli(capsys, "compare", *[part for pair in sides.items() for part in pair])
        after = _contents(tmp_path)
    assert (code, out) == (2, {"error": _record_unreadable(damaged)})
    assert after == before


def test_the_run_list_leaves_out_a_run_whose_record_may_not_be_opened(tmp_path, capsys):
    make_run(tmp_path / "runs")
    damaged = make_run(tmp_path / "runs", run_id="run2")
    with unreadable_file(damaged / "run.json"):
        before = _contents(tmp_path)
        code, out = run_cli(capsys, "status", "--root", str(tmp_path / "runs"))
        after = _contents(tmp_path)
    assert code == 0 and [entry["run_id"] for entry in out["runs"]] == ["run1"]
    assert after == before


@pytest.mark.parametrize("kind", DAMAGE)
def test_the_run_list_leaves_out_a_run_whose_record_cannot_be_read(tmp_path, capsys, kind):
    make_run(tmp_path / "runs")
    damaged = make_run(tmp_path / "runs", run_id="run2")
    _damage(damaged, kind)
    before = _contents(tmp_path)
    code, out = run_cli(capsys, "status", "--root", str(tmp_path / "runs"))
    assert code == 0 and [entry["run_id"] for entry in out["runs"]] == ["run1"]
    assert _contents(tmp_path) == before


def test_the_sentence_for_a_run_without_a_record_stays_as_it_was(tmp_path, capsys):
    run = make_run(tmp_path)
    (run / "run.json").unlink()
    code, out = run_cli(capsys, "settle", "--run", str(run))
    assert (code, out) == (2, {
        "error": f"{run} is not the folder of a run. Give the folder that init-run made for the run."})


# --- A2 fix round 2, point 6: a --from-json file that is missing or a folder is named as --file is -------------------

@pytest.mark.parametrize("kind, message", [("missing", "{path} does not exist. Give the path of a file."),
                                           ("a folder", "{path} is a folder, not a file. Give the path of a file.")])
@pytest.mark.parametrize("form", ["two words", "one word"])
def test_a_from_json_file_that_is_missing_or_a_folder_is_named_in_the_words_used_for_file(
        tmp_path, capsys, kind, message, form):
    run = make_run(tmp_path / "runs")
    path = tmp_path / "options.json"
    if kind == "a folder":
        path.mkdir()
    before = _contents(tmp_path)
    option = ["--from-json", str(path)] if form == "two words" else [f"--from-json={path}"]
    code, out = run_cli(capsys, "log-search", "--run", str(run), *option)
    assert (code, out) == (2, {"error": message.format(path=path)})
    assert _contents(tmp_path) == before


# --- fix wave A21: the person's own reply to the private-mode notice is stored and shown ---------------------------

WORDS = 'Yes, go ahead. Our licence allows it ("internal use"), I checked $(today).'


def _init_with_reply(capsys, tmp_path, *more):
    code = main(["init-run", "--root", str(tmp_path / "runs"), "--question", "Q?", "--pack", "acme-made-up",
                 "--run-id", "p1", *more])
    return code, json.loads(capsys.readouterr().out)


def test_a_private_run_stores_the_person_s_reply_word_for_word(tmp_path, capsys):
    code, out = _init_with_reply(capsys, tmp_path, "--mode", "private", "--acknowledge-data-flow", "--acknowledged-words", WORDS)
    assert code == 0
    record = store.load_run(Path(out["run_dir"]))
    assert record["private_acknowledged_words"] == WORDS and record["private_acknowledged_at"]


def test_the_reply_comes_through_from_json_as_the_lead_passes_it(tmp_path, capsys):
    options = tmp_path / "start.json"
    options.write_text(json.dumps({"root": str(tmp_path / "runs"), "question": "Q?", "pack": "acme-made-up",
                                   "run-id": "p1", "mode": "private", "acknowledge-data-flow": True,
                                   "acknowledged-words": WORDS}), encoding="utf-8")
    assert run_cli(capsys, "init-run", "--from-json", str(options))[0] == 0
    assert store.load_run(tmp_path / "runs" / "p1")["private_acknowledged_words"] == WORDS


@pytest.mark.parametrize("words", [None, "", "   ", "\n"])
def test_a_private_run_without_the_reply_is_not_made(tmp_path, capsys, words):
    more = [] if words is None else ["--acknowledged-words", words]
    code, out = _init_with_reply(capsys, tmp_path, "--mode", "private", "--acknowledge-data-flow", *more)
    assert code == 2 and list(out) == ["error"] and "--acknowledged-words" in out["error"]
    assert not (tmp_path / "runs").exists()


def test_the_reply_belongs_to_the_acknowledgement_and_the_notice_still_comes_first(tmp_path, capsys):
    code, out = _init_with_reply(capsys, tmp_path, "--mode", "private", "--acknowledged-words", WORDS)
    assert code == 2 and out["notice"] == store.PRIVATE_NOTICE_TEXT          # no acknowledgement: the notice
    for more in (["--acknowledged-words", WORDS], ["--mode", "public", "--acknowledged-words", WORDS]):
        code, out = _init_with_reply(capsys, tmp_path, *more)
        assert code == 2 and "--acknowledged-words" in out["error"], more
    assert not (tmp_path / "runs").exists()
    code, out = _init_with_reply(capsys, tmp_path)
    assert code == 0 and store.load_run(Path(out["run_dir"]))["private_acknowledged_words"] is None


def test_the_data_check_names_a_private_run_without_the_reply(tmp_path):
    from radar.schema import Problem, check_data
    run = make_run(tmp_path, mode="private", acknowledged=True)
    assert check_data(run) == []
    store.save_run(run, dict(store.load_run(run), private_acknowledged_words=" "))
    assert Problem("run.json", "private_acknowledged_words", "must not be empty") in check_data(run)


# --- fix wave A23.8: a run.json that lacks what every run record has is not a run ------------------------------------

HOLLOW = {
    "an empty object": {},
    "no checkpoints": "checkpoints",
    "no search log": "search_log",
    "no list of what was left out": "excluded",
    "checkpoints that are no list": ("checkpoints", {"lenses": "yes"}),
    "a search log that is no list": ("search_log", "Company websites"),
}


def _hollow(run, kind):
    how = HOLLOW[kind]
    record = store.load_run(run)
    if how == {}:
        record = {}
    elif isinstance(how, str):
        record.pop(how)
    else:
        record[how[0]] = how[1]
    (run / "run.json").write_text(json.dumps(record), encoding="utf-8")


@pytest.mark.parametrize("command", [c for c in TAKES_RUN if c not in REPORT_DAMAGE])
@pytest.mark.parametrize("kind", sorted(HOLLOW))
def test_a_run_record_that_lacks_what_every_run_record_has_is_not_a_run(tmp_path, capsys, monkeypatch, command, kind):
    import contextlib

    @contextlib.contextmanager
    def damage(run):
        _hollow(run, kind)
        yield

    _damaged_run_case(tmp_path, capsys, monkeypatch, command, damage)


@pytest.mark.parametrize("kind", sorted(HOLLOW))
def test_the_checks_name_a_hollow_record_and_the_run_list_leaves_it_out(tmp_path, capsys, kind):
    run = make_run(tmp_path / "runs")
    _hollow(run, kind)
    for command in REPORT_DAMAGE:
        code, out = run_cli(capsys, command, "--run", str(run))
        assert code == 1 and out["problems"], (command, out)
    code, out = run_cli(capsys, "status", "--root", str(tmp_path / "runs"))
    assert (code, out) == (0, {"runs": []})


# --- fix wave A23.12: init-run checks that its texts can be saved before it makes anything ----------------------------

@pytest.mark.parametrize("option", ["--question", "--home-company", "--pack"])
def test_init_run_with_text_that_cannot_be_saved_makes_nothing(tmp_path, capsys, option):
    argv = {"--question": "Who builds?", "--home-company": "Example Pharma", "--pack": "acme-made-up"}
    argv[option] = "Example " + chr(0xDCFF) + " Pharma"            # what an argument holds whose bytes were not UTF-8
    code = main(["init-run", "--root", str(tmp_path / "runs"), "--run-id", "r1",
                 *[part for pair in argv.items() for part in pair]])
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and list(out) == ["error"] and "cannot be saved" in out["error"]
    assert "codec" not in out["error"]
    assert not (tmp_path / "runs").exists()


def test_init_run_through_the_launcher_with_bytes_that_are_not_utf8_makes_nothing(tmp_path):
    from helpers import BIN_RADAR, radar_env
    done = subprocess.run([b"/bin/sh", bytes(BIN_RADAR), b"init-run", b"--root", bytes(tmp_path / "runs"),
                           b"--question", b"Who builds \xff?", b"--pack", b"demo", b"--run-id", b"r1"],
                          capture_output=True, env=radar_env(tmp_path))
    assert done.returncode == 2 and b"cannot be saved" in done.stdout and done.stderr == b""
    assert not (tmp_path / "runs").exists()


def test_init_run_with_a_pack_file_records_its_companies(tmp_path, capsys):
    path = _pack_file(tmp_path, other_names=["Example Pharma Group"])
    code, _ = _init(capsys, tmp_path, "--pack-file", str(path))
    run = store.load_run(tmp_path / "runs" / "r1")
    assert code == 0
    assert run["companies"][0] == {"name": "Example Pharma", "other_names": ["Example Pharma Group"], "home": True}
    assert [c["name"] for c in run["companies"]] == ["Example Pharma", "Competitor A", "Competitor B", "Competitor C",
                                                     "Competitor D", "Drug maker B"]
    assert run["home_company"] is None      # the run's own setting stays as it was given


def test_init_run_on_a_shipped_pack_records_its_companies_too(tmp_path, capsys):
    code, _ = _init(capsys, tmp_path, "--pack", "demo", "--home-company", "Example Pharma")
    run = store.load_run(tmp_path / "runs" / "r1")
    assert code == 0 and run["companies"][0]["name"] == "Example Pharma" and run["home_company"] == "Example Pharma"


def test_init_run_without_a_pack_file_records_no_companies(tmp_path, capsys):
    code, _ = _init(capsys, tmp_path, "--pack", "acme-real")      # no pack file is read: none by that name ships
    assert code == 0 and "companies" not in store.load_run(tmp_path / "runs" / "r1")


def test_init_run_keeps_the_companies_it_is_given_and_only_those(tmp_path):
    companies = [{"name": "Example Pharma", "other_names": [], "home": True}]
    run = store.load_run(store.init_run(tmp_path, "Q", "demo", run_id="a", companies=companies))
    assert run["companies"] == companies
    assert "companies" not in store.load_run(store.init_run(tmp_path, "Q", "demo", run_id="b"))



def test_a_screening_pack_marks_the_run_and_a_company_pack_leaves_the_key_out(tmp_path, capsys):
    startup = ROOT / "tests" / "fixtures" / "startup-pack.json"
    code, _ = run_cli(capsys, "init-run", "--root", str(tmp_path), "--question", "Q?", "--pack-file", str(startup),
                      "--run-id", "s1")
    data = store.load_run(tmp_path / "s1")
    assert code == 0 and data["screening"] is True and data["illustrative"] is True
    code, _ = run_cli(capsys, "init-run", "--root", str(tmp_path), "--question", "Q?",
                      "--pack-file", str(ROOT / "packs" / "demo.json"), "--run-id", "c1")
    assert code == 0 and "screening" not in store.load_run(tmp_path / "c1")
    code, out = run_cli(capsys, "check-data", "--run", str(tmp_path / "s1"))
    assert code == 0 and out["problems"] == []


def test_a_screening_pack_starts_an_unattended_run_and_a_company_pack_an_attended_one(tmp_path, capsys):
    startup = ROOT / "tests" / "fixtures" / "startup-pack.json"
    code, _ = run_cli(capsys, "init-run", "--root", str(tmp_path), "--question", "Q?", "--pack-file", str(startup),
                      "--run-id", "s1")
    assert code == 0 and store.load_run(tmp_path / "s1")["unattended"] is True
    code, _ = run_cli(capsys, "init-run", "--root", str(tmp_path), "--question", "Q?",
                      "--pack-file", str(ROOT / "packs" / "demo.json"), "--run-id", "c1")
    assert code == 0 and "unattended" not in store.load_run(tmp_path / "c1")
