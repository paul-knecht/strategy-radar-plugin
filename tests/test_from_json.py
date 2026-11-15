"""--from-json, add-facts, add-based-on and record-support --note-stdin: text from outside never goes onto a command
line."""
import io
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from radar import store, verify
from radar.cli import build_parser, main
from helpers import BIN_RADAR, add_fact, add_source, make_run, proposal, radar_env, run_radar

NASTY = 'He said "no" $(touch /tmp/x) `id` ; rm -rf ~ & it\'s fine'

META = {"publisher": "Trade Paper", "date": "2026-05-14", "type": "trade_press",
        "speaker": "a reporter", "interest": "wants readers", "language": "en"}


def run_cli(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    return code, json.loads(out)


def write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def a_copy(tmp_path, text="Competitor A will add a second filling line at Plant North by 2028."):
    path = tmp_path / "page.txt"
    path.write_text(text, encoding="utf-8")
    return str(path)


# --- the option file ---------------------------------------------------------------

def test_from_json_carries_text_no_shell_would_survive(tmp_path, capsys):
    run = make_run(tmp_path)
    args = tmp_path / "args.json"
    args.write_text(json.dumps({"place": NASTY, "result": NASTY}), encoding="utf-8")
    assert main(["log-search", "--run", str(run), "--from-json", str(args)]) == 0
    assert store.load_run(run)["search_log"] == [{"place": NASTY, "result": NASTY}]


def test_from_json_reads_standard_input(tmp_path, capsys, monkeypatch):
    run = make_run(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"run": str(run), "what": NASTY, "why": "too old"})))
    code, out = run_cli(capsys, "log-excluded", "--from-json", "-")
    assert code == 0 and out == {"ok": True}
    assert store.load_run(run)["excluded"] == [{"what": NASTY, "why": "too old"}]


def test_from_json_also_takes_the_equals_form_on_the_command_line(tmp_path, capsys):
    run = make_run(tmp_path)
    args = write_json(tmp_path / "a.json", {"result": "none"})
    assert main(["log-search", f"--from-json={args}", "--place", "Company sites", "--run", str(run)]) == 0
    assert store.load_run(run)["search_log"] == [{"place": "Company sites", "result": "none"}]


def test_from_json_sets_a_flag_and_joins_a_list(tmp_path, capsys):
    args = write_json(tmp_path / "a.json", {"root": str(tmp_path), "question": "Q?", "pack": "demo",
                                            "run-id": "r1", "illustrative": True})
    code, out = run_cli(capsys, "init-run", "--from-json", args)
    assert code == 0 and store.load_run(tmp_path / "r1")["illustrative"] is True
    run = tmp_path / "r1"
    add_source(run, "one")
    add_source(run, "two")
    args = write_json(tmp_path / "b.json", {"run": str(run), "file": a_copy(tmp_path), "url": "https://example.com/x",
                                            "title": "A page", "based-on": ["S1", "S2"], "data-class": "public",
                                            **META})
    code, out = run_cli(capsys, "add-copy", "--from-json", args)
    assert code == 0 and out["based_on"] == ["S1", "S2"]
    assert store.read_sources(run)["S3"]["based_on"] == ["S1", "S2"]


def test_underscores_are_accepted_in_key_names(tmp_path, capsys):
    run = make_run(tmp_path)
    args = write_json(tmp_path / "a.json", {"run": str(run), "name": "lenses", "answered_by": "person", "answer": "yes"})
    assert run_cli(capsys, "checkpoint", "--from-json", args)[0] == 0
    assert store.load_run(run)["checkpoints"][0]["answered_by"] == "person"


def test_numbers_are_passed_as_their_text_and_null_leaves_the_key_out(tmp_path, capsys):
    run = make_run(tmp_path)
    add_fact(run, source_id=add_source(run, "Competitor A will add a second filling line at Plant North by 2028.")["id"])
    args = write_json(tmp_path / "a.json", {"run": str(run), "fact": "F1", "sentences": 2, "open": None})
    code, out = run_cli(capsys, "quote-context", "--from-json", args)
    assert code == 0 and len(out["packets"]) == 1


def test_a_list_is_refused_for_an_option_that_takes_one_value(tmp_path, capsys):
    run = make_run(tmp_path)
    args = write_json(tmp_path / "a.json", {"run": str(run), "place": ["a", "b"], "result": "x"})
    code, out = run_cli(capsys, "log-search", "--from-json", args)
    assert code == 2 and "place" in out["error"]
    assert store.load_run(run)["search_log"] == []


def test_a_list_for_based_on_must_hold_plain_ids(tmp_path, capsys):
    run = make_run(tmp_path)
    for bad in ([["S1"]], [1], ["S1,S2"], [None]):
        args = write_json(tmp_path / "a.json", {"run": str(run), "file": a_copy(tmp_path), "url": "https://example.com/x",
                                                "title": "t", "based-on": bad, "data-class": "public", **META})
        code, out = run_cli(capsys, "add-copy", "--from-json", args)
        assert code == 2 and "based-on" in out["error"], bad
    assert store.read_sources(run) == {}


def test_an_object_is_refused(tmp_path, capsys):
    run = make_run(tmp_path)
    args = write_json(tmp_path / "a.json", {"run": str(run), "place": {"a": 1}, "result": "x"})
    code, out = run_cli(capsys, "log-search", "--from-json", args)
    assert code == 2 and "place" in out["error"]


def test_an_option_given_twice_is_refused(tmp_path, capsys):
    run = make_run(tmp_path)
    args = write_json(tmp_path / "a.json", {"place": "in the file", "result": "x"})
    code, out = run_cli(capsys, "log-search", "--run", str(run), "--place", "on the line", "--from-json", args)
    assert code == 2 and "given twice: --place" in out["error"]
    assert store.load_run(run)["search_log"] == []
    code, out = run_cli(capsys, "log-search", "--run", str(run), "--place=on the line", "--from-json", args)
    assert code == 2 and "given twice: --place" in out["error"]


def test_the_same_option_under_two_spellings_is_given_twice(tmp_path, capsys):
    run = make_run(tmp_path)
    args = write_json(tmp_path / "a.json", {"run": str(run), "name": "lenses", "answered-by": "person",
                                            "answered_by": "test", "answer": "x"})
    code, out = run_cli(capsys, "checkpoint", "--from-json", args)
    assert code == 2 and "given twice: --answered-by" in out["error"]


def test_a_key_that_is_no_option_is_refused(tmp_path, capsys):
    run = make_run(tmp_path)
    args = write_json(tmp_path / "a.json", {"place": "a", "result": "b", "colour": "red"})
    code, out = run_cli(capsys, "log-search", "--run", str(run), "--from-json", args)
    assert code == 2 and "colour" in out["error"]
    assert store.load_run(run)["search_log"] == []


@pytest.mark.parametrize("key", ["from-json", "help", "-h", "--place", "place=x", "", "Place"])
def test_keys_that_would_reach_other_options_are_refused(tmp_path, capsys, key):
    run = make_run(tmp_path)
    args = write_json(tmp_path / "a.json", {"place": "a", "result": "b", key: True})
    code, out = run_cli(capsys, "log-search", "--run", str(run), "--from-json", args)
    assert code == 2 and "error" in out
    assert store.load_run(run)["search_log"] == []


def test_from_json_must_hold_one_object(tmp_path, capsys):
    run = make_run(tmp_path)
    for text in ('[{"place": "a"}]', '"text"', "{nope", "", '{"place": "a", "place": "b"}'):
        path = tmp_path / "a.json"
        path.write_text(text, encoding="utf-8")
        code, out = run_cli(capsys, "log-search", "--run", str(run), "--from-json", str(path))
        assert code == 2 and "error" in out, text


def test_a_missing_option_file_is_a_usage_error(tmp_path, capsys):
    code, out = run_cli(capsys, "log-search", "--from-json", str(tmp_path / "nope.json"))
    assert code == 2 and "error" in out


def test_from_json_needs_a_value(tmp_path, capsys):
    code, out = run_cli(capsys, "log-search", "--from-json")
    assert code == 2 and "error" in out


def test_from_json_given_twice_is_refused(tmp_path, capsys):
    args = write_json(tmp_path / "a.json", {})
    code, out = run_cli(capsys, "doctor", "--from-json", args, "--from-json", args)
    assert code == 2 and "given twice: --from-json" in out["error"]


def test_from_json_on_standard_input_cannot_share_it_with_file_dash(tmp_path, capsys, monkeypatch):
    run = make_run(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"run": str(run)})))
    code, out = run_cli(capsys, "add-fact", "--file", "-", "--from-json", "-")
    assert code == 2 and "standard input" in out["error"]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"run": str(run), "file": "-"})))
    code, out = run_cli(capsys, "add-fact", "--from-json", "-")
    assert code == 2 and "standard input" in out["error"]


def test_every_subcommand_accepts_from_json():
    parser = build_parser()
    commands = next(action for action in parser._actions if action.choices).choices
    assert len(commands) >= 18
    for name, sub in commands.items():
        assert "--from-json" in sub._option_string_actions, name


# --- a false never switches anything on ---------------------------------------------

def test_a_false_flag_is_the_same_as_leaving_it_out(tmp_path, capsys):
    args = write_json(tmp_path / "a.json", {"root": str(tmp_path / "runs"), "question": "Q", "pack": "demo",
                                            "mode": "private", "acknowledge-data-flow": False})
    code, out = run_cli(capsys, "init-run", "--from-json", args)
    assert code == 2 and out["notice"] == store.PRIVATE_NOTICE_TEXT
    code_without, out_without = run_cli(capsys, "init-run", "--root", str(tmp_path / "runs"), "--question", "Q",
                                        "--pack", "demo", "--mode", "private")
    assert (code, out) == (code_without, out_without)
    assert not (tmp_path / "runs").exists()


def test_a_null_flag_is_left_out_too(tmp_path, capsys):
    args = write_json(tmp_path / "a.json", {"root": str(tmp_path / "runs"), "question": "Q", "pack": "demo",
                                            "mode": "private", "acknowledge-data-flow": None})
    assert run_cli(capsys, "init-run", "--from-json", args)[0] == 2
    assert not (tmp_path / "runs").exists()


def test_a_true_flag_switches_it_on(tmp_path, capsys):
    args = write_json(tmp_path / "a.json", {"root": str(tmp_path), "question": "Q", "pack": "demo", "run-id": "p1",
                                            "mode": "private", "acknowledge-data-flow": True,
                                            "acknowledged-words": "Yes, go ahead."})
    assert run_cli(capsys, "init-run", "--from-json", args)[0] == 0
    assert store.load_run(tmp_path / "p1")["mode"] == "private"


def test_a_text_that_says_false_does_not_switch_a_flag_on(tmp_path, capsys):
    args = write_json(tmp_path / "a.json", {"root": str(tmp_path / "runs"), "question": "Q", "pack": "demo",
                                            "mode": "private", "acknowledge-data-flow": "false"})
    assert run_cli(capsys, "init-run", "--from-json", args)[0] == 2
    assert not (tmp_path / "runs").exists()


# --- Part A fix A1, M3: an option whose values are the texts true and false takes JSON true and false -----------

@pytest.mark.parametrize("value, passed", [(True, True), (False, False), ("true", True), ("false", False)])
def test_record_support_takes_json_true_and_false_for_passed(tmp_path, capsys, value, passed):
    run = make_run(tmp_path)
    add_fact(run, source_id=add_source(run, "Competitor A will add a second filling line at Plant North by 2028.")["id"])
    args = write_json(tmp_path / "a.json", {"run": str(run), "fact": "F1", "passed": value,
                                            "by": "support checker", "note": NASTY})
    assert run_cli(capsys, "record-support", "--from-json", args) == (0, {"ok": True})
    support = store.read_facts(run)["F1"]["checks"]["support"]
    assert support["passed"] is passed and support["note"] == NASTY


def test_a_json_true_or_false_still_names_a_text_option_given_twice(tmp_path, capsys):
    run = make_run(tmp_path)
    add_fact(run, source_id=add_source(run, "Competitor A will add a second filling line at Plant North by 2028.")["id"])
    args = write_json(tmp_path / "a.json", {"run": str(run), "fact": "F1", "passed": False, "by": "c", "note": "n"})
    code, out = run_cli(capsys, "record-support", "--passed", "true", "--from-json", args)
    assert code == 2 and "given twice: --passed" in out["error"]
    assert store.read_facts(run)["F1"]["checks"]["support"] is None


# --- hostile values ------------------------------------------------------------------

HOSTILE = [
    "-starts-with-a-dash",
    "--run=/somewhere/else",
    "--from-json=/etc/passwd",
    'double "quotes" and \'single\' quotes',
    "$(touch x)",
    "`touch x`",
    "line one\nline two; touch x\r\nline three",
    "; rm -rf ~ & echo done | cat > x",
    "-",
    "--",
]


@pytest.mark.parametrize("value", HOSTILE)
def test_a_hostile_value_arrives_exactly_as_written(tmp_path, capsys, monkeypatch, value):
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    run = make_run(tmp_path / "runs")
    other = make_run(tmp_path / "other")
    args = write_json(tmp_path / "a.json", {"run": str(run), "file": a_copy(tmp_path), "url": "https://example.com/x",
                                            "title": value, "publisher": value, "speaker": value, "interest": value,
                                            "date": "2026-05-14", "type": "other", "language": "en",
                                            "data-class": "public"})
    code, out = run_cli(capsys, "add-copy", "--from-json", args)
    assert code == 0
    source = store.read_sources(run)["S1"]
    assert (source["title"], source["publisher"], source["speaker"], source["interest"]) == (value,) * 4
    assert source["url"] == "https://example.com/x" and source["type"] == "other"
    assert list(work.iterdir()) == []                     # nothing was created next to the caller
    assert store.read_sources(other) == {} and store.load_run(other)["search_log"] == []


@pytest.mark.parametrize("value", HOSTILE)
def test_a_hostile_value_in_a_log_entry_changes_no_option(tmp_path, capsys, monkeypatch, value):
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    run = make_run(tmp_path)
    args = write_json(tmp_path / "a.json", {"run": str(run), "place": value, "result": value})
    assert run_cli(capsys, "log-search", "--from-json", args)[0] == 0
    assert store.load_run(run)["search_log"] == [{"place": value, "result": value}]
    assert list(work.iterdir()) == []


def test_the_real_command_takes_hostile_text_from_standard_input(tmp_path):
    run = make_run(tmp_path)
    body = json.dumps({"run": str(run), "place": NASTY, "result": "--run=/elsewhere\n$(touch hit)"})
    done = run_radar("log-search", "--from-json", "-", home=tmp_path, input=body, cwd=tmp_path)
    assert done.returncode == 0 and json.loads(done.stdout) == {"ok": True}
    assert store.load_run(run)["search_log"] == [{"place": NASTY, "result": "--run=/elsewhere\n$(touch hit)"}]
    assert not (tmp_path / "hit").exists()


# --- add-facts -----------------------------------------------------------------------

def facts_run(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "Competitor A will add a second filling line at Plant North by 2028.")
    return run


def test_add_facts_writes_the_good_ones_and_names_the_bad_ones(tmp_path, capsys):
    run = facts_run(tmp_path)
    short = proposal(quote="only three words")
    file = write_json(tmp_path / "all.json", [proposal(), short, proposal(statement=NASTY)])
    code, out = run_cli(capsys, "add-facts", "--run", str(run), "--file", file)
    assert code == 1
    assert out["added"] == [{"index": 0, "fact_id": "F1"}, {"index": 2, "fact_id": "F2"}]
    assert out["refused"] == [{"index": 1, "reasons": ["quote: quote must have 5 to 50 words"]}]
    assert sorted(store.read_facts(run)) == ["F1", "F2"]
    assert store.read_facts(run)["F2"]["statement"] == NASTY
    assert store.read_facts(run)["F2"]["status"] == "proposed"


def test_add_facts_with_nothing_refused_exits_0(tmp_path, capsys):
    run = facts_run(tmp_path)
    code, out = run_cli(capsys, "add-facts", "--run", str(run), "--file", write_json(tmp_path / "a.json", [proposal()]))
    assert code == 0 and out == {"added": [{"index": 0, "fact_id": "F1"}], "refused": []}
    code, out = run_cli(capsys, "add-facts", "--run", str(run), "--file", write_json(tmp_path / "b.json", []))
    assert code == 0 and out == {"added": [], "refused": []}


def test_add_facts_refuses_a_proposal_that_is_not_an_object_and_one_with_an_unknown_source(tmp_path, capsys):
    run = facts_run(tmp_path)
    file = write_json(tmp_path / "a.json", ["text", proposal(source_id="S9")])
    code, out = run_cli(capsys, "add-facts", "--run", str(run), "--file", file)
    assert code == 1 and out["added"] == []
    assert [entry["index"] for entry in out["refused"]] == [0, 1]
    assert all(entry["reasons"] for entry in out["refused"])
    assert store.read_facts(run) == {}


def test_add_facts_reads_standard_input(tmp_path, capsys, monkeypatch):
    run = facts_run(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps([proposal()])))
    code, out = run_cli(capsys, "add-facts", "--run", str(run), "--file", "-")
    assert code == 0 and out["added"] == [{"index": 0, "fact_id": "F1"}]


def test_add_facts_needs_a_list(tmp_path, capsys):
    run = facts_run(tmp_path)
    for text in (json.dumps(proposal()), "{nope", '"text"'):
        path = tmp_path / "a.json"
        path.write_text(text, encoding="utf-8")
        code, out = run_cli(capsys, "add-facts", "--run", str(run), "--file", str(path))
        assert code == 2 and "error" in out
    code, out = run_cli(capsys, "add-facts", "--run", str(run), "--file", str(tmp_path / "missing.json"))
    assert code == 2 and "error" in out
    assert store.read_facts(run) == {}


def test_add_facts_takes_its_options_from_a_file_too(tmp_path, capsys):
    run = facts_run(tmp_path)
    args = write_json(tmp_path / "args.json", {"run": str(run), "file": write_json(tmp_path / "all.json", [proposal()])})
    code, out = run_cli(capsys, "add-facts", "--from-json", args)
    assert code == 0 and out["added"] == [{"index": 0, "fact_id": "F1"}]


# --- add-based-on --------------------------------------------------------------------

def three_sources(tmp_path):
    run = make_run(tmp_path)
    for text in ("one", "two", "three"):
        add_source(run, text)
    return run


def test_add_based_on_adds_and_never_removes(tmp_path, capsys):
    run = three_sources(tmp_path)
    code, out = run_cli(capsys, "add-based-on", "--run", str(run), "--source", "S3", "--on", "S1")
    assert code == 0 and out == {"ok": True, "based_on": ["S1"]}
    code, out = run_cli(capsys, "add-based-on", "--run", str(run), "--source", "S3", "--on", "S2")
    assert out == {"ok": True, "based_on": ["S1", "S2"]}
    code, out = run_cli(capsys, "add-based-on", "--run", str(run), "--source", "S3", "--on", "S1")
    assert code == 0 and out == {"ok": True, "based_on": ["S1", "S2"]}      # no duplicate
    assert store.read_sources(run)["S3"]["based_on"] == ["S1", "S2"]
    assert store.read_sources(run)["S1"]["based_on"] == []


def test_add_based_on_refuses_a_loop_and_an_unknown_source(tmp_path, capsys):
    run = three_sources(tmp_path)
    assert run_cli(capsys, "add-based-on", "--run", str(run), "--source", "S2", "--on", "S1")[0] == 0
    assert run_cli(capsys, "add-based-on", "--run", str(run), "--source", "S3", "--on", "S2")[0] == 0
    before = {key: store.read_sources(run)[key]["based_on"] for key in ("S1", "S2", "S3")}
    for source, on in (("S1", "S3"), ("S1", "S2"), ("S1", "S1"), ("S4", "S1"), ("S1", "S4"), ("x", "S1"), ("S1", "")):
        code, out = run_cli(capsys, "add-based-on", "--run", str(run), "--source", source, "--on", on)
        assert code == 2 and "error" in out, (source, on)
    assert {key: store.read_sources(run)[key]["based_on"] for key in ("S1", "S2", "S3")} == before


def test_add_based_on_leaves_the_rest_of_the_source_alone(tmp_path):
    run = three_sources(tmp_path)
    before = store.read_sources(run)["S2"]
    assert store.add_based_on(run, "S2", "S1") == ["S1"]
    assert store.read_sources(run)["S2"] == {**before, "based_on": ["S1"]}


def test_add_based_on_takes_its_options_from_a_file(tmp_path, capsys):
    run = three_sources(tmp_path)
    args = write_json(tmp_path / "a.json", {"run": str(run), "source": "S2", "on": "S1"})
    assert run_cli(capsys, "add-based-on", "--from-json", args) == (0, {"ok": True, "based_on": ["S1"]})


TEXT_A = "The expansion adds two high-speed syringe lines for customers, starting in 2028."
TEXT_B = "Competitor A confirmed two new syringe lines will open in 2028, the paper reported."


def test_a_fact_confirmed_by_a_second_source_becomes_uncertain_once_that_source_is_based_on_the_first(tmp_path):
    run = make_run(tmp_path)
    add_source(run, TEXT_A, publisher="Competitor A")
    add_source(run, TEXT_B, publisher="Trade Paper")
    add_fact(run, source_id="S1", primary_source=False, quote="adds two high-speed syringe lines for customers",
             supporting=[{"source_id": "S2", "quote": "two new syringe lines will open in 2028"}])
    verify.check_quotes(run)
    verify.record_support(run, "F1", True, "support-checker", "")
    assert verify.settle(run) == {"F1": "confirmed"}
    store.add_based_on(run, "S2", "S1")
    assert verify.settle(run) == {"F1": "uncertain"}


# --- the private-mode notice ---------------------------------------------------------

def test_a_private_run_without_the_acknowledgement_prints_the_notice_in_plain_words(tmp_path, capsys):
    assert main(["init-run", "--root", str(tmp_path), "--question", "Q", "--pack", "demo", "--mode", "private"]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["notice"] == store.PRIVATE_NOTICE_TEXT
    assert out["notice"].endswith("allow this.") and "--" not in out["notice"]
    assert out["error"] == store.PRIVATE_NOTICE
    assert not any(tmp_path.iterdir())                                   # no run folder was made


def test_the_full_notice_is_the_text_plus_the_sentence_about_the_flag():
    assert store.PRIVATE_NOTICE == store.PRIVATE_NOTICE_TEXT + " Re-run with --acknowledge-data-flow to continue."
    assert store.PRIVATE_NOTICE_TEXT.startswith("Private mode sends the content of your documents")


# --- fix round 1 ---------------------------------------------------------------------

def test_a_false_in_the_file_still_counts_as_given(tmp_path, capsys):
    args = write_json(tmp_path / "a.json", {"acknowledge-data-flow": False})
    code, out = run_cli(capsys, "init-run", "--root", str(tmp_path / "runs"), "--question", "Q", "--pack", "demo",
                        "--mode", "private", "--acknowledge-data-flow", "--from-json", args)
    assert code == 2 and "given twice: --acknowledge-data-flow" in out["error"]
    assert not (tmp_path / "runs").exists()


def test_a_null_in_the_file_still_counts_as_given(tmp_path, capsys):
    run = make_run(tmp_path)
    args = write_json(tmp_path / "a.json", {"place": None, "result": "r"})
    code, out = run_cli(capsys, "log-search", "--run", str(run), "--place", "x", "--from-json", args)
    assert code == 2 and "given twice: --place" in out["error"]
    assert store.load_run(run)["search_log"] == []


@pytest.mark.parametrize("flag", ["--from", "--from-j", "--from-jso"])
def test_an_abbreviation_of_from_json_is_refused_and_changes_nothing(tmp_path, capsys, flag):
    args = write_json(tmp_path / "a.json", {"illustrative": True})
    code, out = run_cli(capsys, "init-run", "--root", str(tmp_path / "runs"), "--question", "Q", "--pack", "demo",
                        flag, args)
    assert code == 2 and "error" in out
    assert not (tmp_path / "runs").exists()
    gate_args = write_json(tmp_path / "g.json", {"publishable": True})
    code, out = run_cli(capsys, "gate", "--run", str(tmp_path), flag, gate_args)
    assert code == 2 and "error" in out


def test_abbreviations_of_other_options_are_refused_too(tmp_path, capsys):
    code, out = run_cli(capsys, "init-run", "--root", str(tmp_path / "runs"), "--question", "Q", "--pack", "demo",
                        "--mode", "private", "--ack")
    assert code == 2 and "error" in out and not (tmp_path / "runs").exists()
    run = make_run(tmp_path)
    code, out = run_cli(capsys, "log-search", "--ru", str(run), "--place", "a", "--result", "b")
    assert code == 2 and "error" in out
    assert store.load_run(run)["search_log"] == []
    code, out = run_cli(capsys, "--vers")
    assert code == 2 and "error" in out


def test_the_exact_names_still_work_beside_the_abbreviation_ban(tmp_path, capsys):
    run = make_run(tmp_path)
    args = write_json(tmp_path / "a.json", {"result": "r"})
    assert main(["log-search", "--run", str(run), "--place", "p", "--from-json", args]) == 0
    assert main(["log-search", "--run", str(run), "--place=q", f"--from-json={args}"]) == 0
    capsys.readouterr()
    assert [entry["place"] for entry in store.load_run(run)["search_log"]] == ["p", "q"]


def test_a_parsed_file_option_that_was_not_applied_stops_the_command(tmp_path, capsys, monkeypatch):
    from radar import cli
    monkeypatch.setattr(cli, "_expand_from_json", lambda parser, argv: argv)
    args = write_json(tmp_path / "a.json", {"illustrative": True})
    code, out = run_cli(capsys, "init-run", "--root", str(tmp_path / "runs"), "--question", "Q", "--pack", "demo",
                        "--from-json", args)
    assert code == 2 and "from-json" in out["error"]
    assert not (tmp_path / "runs").exists()


LONE_SURROGATE_FILE = '{"place": "\\ud800", "result": "r"}'   # the JSON escape of a lone surrogate, plain ASCII


def test_a_lone_surrogate_in_the_option_file_is_refused_and_run_json_is_untouched(tmp_path, capsys):
    run = make_run(tmp_path)
    before = (run / "run.json").read_bytes()
    args = tmp_path / "a.json"
    args.write_bytes(LONE_SURROGATE_FILE.encode("ascii"))
    code, out = run_cli(capsys, "log-search", "--run", str(run), "--from-json", str(args))
    assert code == 2 and "UTF-8" in out["error"]
    assert (run / "run.json").read_bytes() == before


def test_a_lone_surrogate_in_a_proposal_is_refused_and_no_fact_file_is_made(tmp_path, capsys):
    run = facts_run(tmp_path)
    before = (run / "run.json").read_bytes()
    text = json.dumps([proposal()]).replace("Competitor A will add", "\\ud800 will add", 1)
    assert "\\ud800" in text
    file = tmp_path / "all.json"
    file.write_bytes(text.encode("ascii"))
    code, out = run_cli(capsys, "add-facts", "--run", str(run), "--file", str(file))
    assert code == 2 and "UTF-8" in out["error"]
    one = tmp_path / "one.json"
    one.write_bytes(json.dumps(proposal(statement="x")).replace('"x"', '"\\ud800"').encode("ascii"))
    code, out = run_cli(capsys, "add-fact", "--run", str(run), "--file", str(one))
    assert code == 2 and "UTF-8" in out["error"]
    assert list((run / "facts").iterdir()) == []
    assert (run / "run.json").read_bytes() == before


def test_a_failed_write_leaves_the_old_file_whole(tmp_path):
    path = tmp_path / "record.json"
    store._write_json(path, {"a": 1})
    before = path.read_bytes()
    with pytest.raises(ValueError):
        store._write_json(path, {"a": chr(0xD800)})
    assert path.read_bytes() == before
    assert [entry.name for entry in tmp_path.iterdir()] == ["record.json"]   # no temporary file stays


def test_a_failed_log_entry_leaves_run_json_whole(tmp_path):
    run = make_run(tmp_path)
    before = (run / "run.json").read_bytes()
    with pytest.raises(ValueError):
        store.log_search(run, chr(0xD800), "r")
    assert (run / "run.json").read_bytes() == before


def test_a_failed_write_of_a_new_fact_leaves_no_empty_file_behind(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "text")
    with pytest.raises(ValueError):
        store.new_fact(run, proposal(statement=chr(0xD800)))
    assert list((run / "facts").iterdir()) == []
    assert store.new_fact(run, proposal())["id"] == "F1"          # the id was given back


def test_a_failed_save_of_a_source_leaves_no_empty_record_or_copy(tmp_path):
    from radar import fetch
    run = make_run(tmp_path)
    meta = {**META, "title": chr(0xD800), "based_on": []}
    with pytest.raises(ValueError):
        fetch.add_copy(run, Path(a_copy(tmp_path)), "https://example.com/x", meta, data_class="public")
    assert list((run / "sources").iterdir()) == []
    assert sorted(entry.name for entry in (run / "copies").iterdir()) == [".gitignore"]


def test_the_write_still_replaces_a_reserved_empty_file(tmp_path):
    run = make_run(tmp_path)
    source_id = store.reserve_id(run, "S")
    assert (run / "sources" / f"{source_id}.json").read_bytes() == b""
    store.write_source(run, {"id": source_id, "title": "t"})
    assert store.read_sources(run)[source_id]["title"] == "t"
    assert store.reserve_id(run, "S") == "S2"


def test_numbers_arrive_exactly_as_written(tmp_path, capsys):
    run = make_run(tmp_path)
    args = tmp_path / "a.json"
    args.write_text('{"run": "%s", "place": 2.50, "result": 1e3}' % run, encoding="utf-8")
    assert main(["log-search", "--from-json", str(args)]) == 0
    capsys.readouterr()
    assert store.load_run(run)["search_log"] == [{"place": "2.50", "result": "1e3"}]


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_a_number_that_is_no_number_is_refused(tmp_path, capsys, constant):
    run = make_run(tmp_path)
    args = tmp_path / "a.json"
    args.write_text('{"run": "%s", "place": %s, "result": "r"}' % (run, constant), encoding="utf-8")
    code, out = run_cli(capsys, "log-search", "--from-json", str(args))
    assert code == 2 and "error" in out
    assert store.load_run(run)["search_log"] == []


def test_a_number_is_no_id_in_a_list(tmp_path, capsys):
    run = make_run(tmp_path)
    args = tmp_path / "a.json"
    args.write_text(json.dumps({"run": str(run), "file": a_copy(tmp_path), "url": "https://example.com/x",
                                "title": "t", "data-class": "public", **META}).replace('"title"', '"based-on": [1], "title"'),
                    encoding="utf-8")
    code, out = run_cli(capsys, "add-copy", "--from-json", str(args))
    assert code == 2 and "based-on" in out["error"]


# --- PM1: record-support takes its note as plain text on standard input -------------------------------------------

STATED = "Competitor A will add a second filling line at Plant North by 2028."


def a_fact(tmp_path, name="run"):
    """A run of its own under tmp_path/name with one proposed fact, F1."""
    run = make_run(tmp_path / name)
    add_fact(run, source_id=add_source(run, STATED)["id"])
    return run


def standard_input(monkeypatch, data):
    """Standard input as a real one is: bytes under a text layer."""
    raw = data if isinstance(data, bytes) else data.encode("utf-8")
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8"))


def by_note_stdin(capsys, run, *more):
    return run_cli(capsys, "record-support", "--run", str(run), "--fact", "F1", "--passed", "false",
                   "--by", "support-checker", "--note-stdin", *more)


def stored(run):
    return store.read_facts(run)["F1"]["checks"]["support"]


def test_a_note_on_standard_input_is_stored_exactly_as_the_same_note_on_the_command_line(tmp_path, capsys,
                                                                                        monkeypatch):
    on_the_line, on_input = a_fact(tmp_path, "line"), a_fact(tmp_path, "input")
    assert run_cli(capsys, "record-support", "--run", str(on_the_line), "--fact", "F1", "--passed", "false",
                   "--by", "support-checker", "--note", NASTY) == (0, {"ok": True})
    standard_input(monkeypatch, NASTY + "\n")
    assert by_note_stdin(capsys, on_input) == (0, {"ok": True})
    line_fact, input_fact = store.read_facts(on_the_line)["F1"], store.read_facts(on_input)["F1"]
    assert input_fact["checks"]["support"]["note"] == NASTY
    for fact in (line_fact, input_fact):
        assert fact["checks"]["support"].pop("at")          # the time of recording is the one thing that differs
    assert input_fact == line_fact


@pytest.mark.parametrize("sent, note", [
    ("The quote says 2028.\n", "The quote says 2028."),
    ("  \n\t The quote says 2028. \n\n", "The quote says 2028."),              # white space around it is trimmed
    ("The quote says 2028.\nThe fact says 2029.\n", "The quote says 2028. The fact says 2029."),
    ("One.\r\nTwo.\rThree.\nFour.", "One. Two. Three. Four."),                 # every kind of line end is one space
    ("One.\n\nTwo.", "One.  Two."),                                            # one space for each line end
    ("A tab\tstays inside.", "A tab\tstays inside."),
    ('It says "not" (twice), costs 5% and is the company\'s: {a} `b` $(c) $HOME',
     'It says "not" (twice), costs 5% and is the company\'s: {a} `b` $(c) $HOME'),
    ("Der Satz sagt " + chr(0x201E) + "nicht" + chr(0x201C) + ", " + chr(0xFC) + "ber alles.",
     "Der Satz sagt " + chr(0x201E) + "nicht" + chr(0x201C) + ", " + chr(0xFC) + "ber alles."),
    ("--run /elsewhere --passed true", "--run /elsewhere --passed true"),       # text, never an option
])
def test_the_note_is_the_text_trimmed_with_its_line_ends_as_spaces(tmp_path, capsys, monkeypatch, sent, note):
    run = a_fact(tmp_path)
    standard_input(monkeypatch, sent)
    assert by_note_stdin(capsys, run) == (0, {"ok": True})
    assert stored(run)["note"] == note and stored(run)["passed"] is False and stored(run)["by"] == "support-checker"


def test_an_empty_note_is_kept_for_a_pass_and_refused_for_a_rejection_on_the_line_and_on_standard_input(
        tmp_path, capsys, monkeypatch):
    # Fix wave A3: a rejection is shown to the reader with the checker's reason, so it must have one.
    run = a_fact(tmp_path)
    assert run_cli(capsys, "record-support", "--run", str(run), "--fact", "F1", "--passed", "true",
                   "--by", "support-checker", "--note", "") == (0, {"ok": True})     # a pass needs no reason
    assert stored(run)["note"] == ""
    for number, sent in enumerate(("", "\n", "  \r\n\t\n  ")):
        run = a_fact(tmp_path, f"empty-{number}")
        standard_input(monkeypatch, sent)
        code, out = by_note_stdin(capsys, run)                                       # --passed false
        assert code == 2 and list(out) == ["error"] and out["error"] == verify.EMPTY_REJECTION_NOTE
        assert stored(run) is None
    for note in ("", "   ", "\t"):
        run = a_fact(tmp_path, f"line-{len(note)}-{note == chr(9)}")
        code, out = run_cli(capsys, "record-support", "--run", str(run), "--fact", "F1", "--passed", "false",
                            "--by", "support-checker", "--note", note)
        assert (code, out) == (2, {"error": verify.EMPTY_REJECTION_NOTE}) and stored(run) is None


@pytest.mark.parametrize("by", ["", " ", "\t ", "\n"])
def test_a_verdict_must_say_who_gave_it(tmp_path, capsys, by):
    run = a_fact(tmp_path)
    code, out = run_cli(capsys, "record-support", "--run", str(run), "--fact", "F1", "--passed", "true",
                        "--by", by, "--note", "The quote states it.")
    assert (code, out) == (2, {"error": verify.EMPTY_BY}) and stored(run) is None
    args = tmp_path / "verdict.json"
    args.write_text(json.dumps({"run": str(run), "fact": "F1", "passed": False, "by": by, "note": "No."}),
                    encoding="utf-8")
    assert run_cli(capsys, "record-support", "--from-json", str(args)) == (2, {"error": verify.EMPTY_BY})
    assert stored(run) is None


def test_the_two_verdict_refusals_are_plain_sentences():
    assert verify.EMPTY_BY == "Say who gave the verdict: --by must not be empty."
    assert verify.EMPTY_REJECTION_NOTE == ("A verdict that the quote does not support the fact needs a note. "
                                           "Say in a sentence why, so the reader sees the reason.")


@pytest.mark.parametrize("sent", [
    b"The quote says 2028 \xff.", b"\xc3", b"caf\xc3\xa9 \xe9t\xe9", b"\xed\xa0\x80 half of a pair",
])
def test_a_note_that_is_not_utf8_is_refused_in_plain_words_and_nothing_is_stored(tmp_path, capsys, monkeypatch,
                                                                                 sent):
    run = a_fact(tmp_path)
    standard_input(monkeypatch, sent)
    code, out = by_note_stdin(capsys, run)
    assert code == 2 and "UTF-8" in out["error"] and "note" in out["error"]
    assert stored(run) is None


@pytest.mark.parametrize("character", [chr(0), chr(0x07), chr(0x0B), chr(0x0C), chr(0x1B), chr(0x1F), chr(0x7F),
                                       chr(0x85), chr(0x9F)])
def test_a_note_with_a_control_character_is_refused_in_plain_words_and_nothing_is_stored(tmp_path, capsys,
                                                                                        monkeypatch, character):
    for number, sent in enumerate(("The quote" + character + " says 2028.", character + "The quote says 2028.\n")):
        run = a_fact(tmp_path, f"control-{number}")
        standard_input(monkeypatch, sent)
        code, out = by_note_stdin(capsys, run)
        assert code == 2 and "control character" in out["error"] and "note" in out["error"]
        assert stored(run) is None


def test_a_note_from_a_text_stream_without_bytes_is_read_too(tmp_path, capsys, monkeypatch):
    run = a_fact(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(" The quote says 2028.\n"))
    assert by_note_stdin(capsys, run) == (0, {"ok": True})
    assert stored(run)["note"] == "The quote says 2028."
    run = a_fact(tmp_path, "half")
    monkeypatch.setattr("sys.stdin", io.StringIO("half of a pair " + chr(0xD800)))
    code, out = by_note_stdin(capsys, run)
    assert code == 2 and "UTF-8" in out["error"] and stored(run) is None


def test_note_stdin_and_note_together_or_neither_are_wrong_use(tmp_path, capsys, monkeypatch):
    run = a_fact(tmp_path)
    standard_input(monkeypatch, "The quote says 2028.")
    code, out = by_note_stdin(capsys, run, "--note", "The quote says 2028.")
    assert code == 2 and "--note" in out["error"] and "--note-stdin" in out["error"]
    code, out = run_cli(capsys, "record-support", "--run", str(run), "--fact", "F1", "--passed", "true",
                        "--by", "support-checker")
    assert code == 2 and "--note" in out["error"] and "--note-stdin" in out["error"]
    assert stored(run) is None


def test_note_stdin_cannot_share_standard_input_with_the_options(tmp_path, capsys, monkeypatch):
    run = a_fact(tmp_path)
    options = {"run": str(run), "fact": "F1", "passed": "true", "by": "support-checker"}
    standard_input(monkeypatch, json.dumps(options))
    code, out = run_cli(capsys, "record-support", "--note-stdin", "--from-json", "-")
    assert code == 2 and "standard input" in out["error"]
    for key in ("note-stdin", "note_stdin"):
        standard_input(monkeypatch, json.dumps({**options, key: True}))
        code, out = run_cli(capsys, "record-support", "--from-json", "-")
        assert code == 2 and "standard input" in out["error"]
    assert stored(run) is None


def test_note_stdin_goes_with_options_from_a_file(tmp_path, capsys, monkeypatch):
    run = a_fact(tmp_path)
    args = write_json(tmp_path / "a.json", {"run": str(run), "fact": "F1", "passed": False, "by": "support-checker",
                                            "note-stdin": True})
    standard_input(monkeypatch, "The quote says 2028.\n")
    assert run_cli(capsys, "record-support", "--from-json", args) == (0, {"ok": True})
    assert stored(run)["note"] == "The quote says 2028." and stored(run)["passed"] is False
    args = write_json(tmp_path / "b.json", {"run": str(run), "fact": "F1", "passed": True, "by": "support-checker",
                                            "note": "Also here."})
    standard_input(monkeypatch, "The quote says 2028.\n")
    code, out = run_cli(capsys, "record-support", "--note-stdin", "--from-json", args)
    assert code == 2 and "--note-stdin" in out["error"]
    assert stored(run)["passed"] is False


def test_note_stdin_is_a_switch_and_record_support_s_other_options_stay_as_they_are():
    record = next(action for action in build_parser()._actions if action.choices).choices["record-support"]
    actions = {name: action for name, action in record._option_string_actions.items() if name.startswith("--")}
    assert actions["--note-stdin"].nargs == 0 and not actions["--note-stdin"].required
    assert not actions["--note"].required
    assert all(actions[name].required for name in ("--run", "--fact", "--passed", "--by"))
    assert sorted(actions) == ["--by", "--fact", "--from-json", "--help", "--note", "--note-stdin", "--passed", "--run"]


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_the_checker_s_here_document_reaches_the_note_through_the_real_launcher(tmp_path):
    run = a_fact(tmp_path)
    note = 'The sentence around the quote says "not": the company\'s plan (2028) is 50% for itself.'
    script = ('radar record-support --run "$RUN" --fact F1 --passed false --by support-checker --note-stdin '
              "<<'RADAR_NOTE'\n" + note + "\nRADAR_NOTE\n")
    env = radar_env(tmp_path, PATH=str(BIN_RADAR.parent) + os.pathsep + os.environ["PATH"], RUN=str(run))
    done = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
    assert (done.returncode, done.stdout, done.stderr) == (0, '{"ok": true}\n', "")
    assert stored(run)["note"] == note and stored(run)["by"] == "support-checker"


# --- DH1 small points: the same note rule both ways, a size limit, no silent wait on a terminal -------------------

def by_note_on_the_line(capsys, run, note):
    return run_cli(capsys, "record-support", "--run", str(run), "--fact", "F1", "--passed", "false",
                   "--by", "support-checker", "--note", note)


@pytest.mark.parametrize("separator", [chr(0x2028), chr(0x2029)])
def test_a_line_or_paragraph_separator_in_a_note_becomes_one_space_both_ways(tmp_path, capsys, monkeypatch,
                                                                            separator):
    sent = "The quote says 2028." + separator + "The fact says 2029." + separator
    on_input, on_the_line = a_fact(tmp_path, "input"), a_fact(tmp_path, "line")
    standard_input(monkeypatch, sent)
    assert by_note_stdin(capsys, on_input) == (0, {"ok": True})
    assert by_note_on_the_line(capsys, on_the_line, sent) == (0, {"ok": True})
    assert stored(on_input)["note"] == stored(on_the_line)["note"] == "The quote says 2028. The fact says 2029."


@pytest.mark.parametrize("character", [chr(0x202E), chr(0x200B), chr(0xFEFF), chr(0x00AD), chr(0x200D),
                                       chr(0x2066)])
def test_a_format_character_in_a_note_is_refused_like_a_control_character_both_ways(tmp_path, capsys,
                                                                                   monkeypatch, character):
    for number, sent in enumerate(("The quote" + character + " says 2028.", character + "The quote says 2028.\n")):
        run = a_fact(tmp_path, f"input-{number}")
        standard_input(monkeypatch, sent)
        code, out = by_note_stdin(capsys, run)
        assert code == 2 and "control character" in out["error"] and "note" in out["error"]
        assert stored(run) is None
        run = a_fact(tmp_path, f"line-{number}")
        code, out = by_note_on_the_line(capsys, run, sent)
        assert code == 2 and "control character" in out["error"] and "note" in out["error"]
        assert stored(run) is None


@pytest.mark.parametrize("character", [chr(0), chr(0x07), chr(0x1B), chr(0x7F), chr(0x85)])
def test_a_control_character_in_a_note_on_the_command_line_is_refused_too(tmp_path, capsys, character):
    run = a_fact(tmp_path)
    code, out = by_note_on_the_line(capsys, run, "The quote" + character + " says 2028.")
    assert code == 2 and "control character" in out["error"] and "note" in out["error"]
    assert stored(run) is None


@pytest.mark.parametrize("sent, note", [
    ("  \n\t The quote says 2028. \n\n", "The quote says 2028."),
    ("One.\r\nTwo.\rThree.\nFour.", "One. Two. Three. Four."),
    ("A tab\tstays inside.", "A tab\tstays inside."),
    (NASTY, NASTY),
])
def test_a_note_on_the_command_line_is_stored_by_the_same_rule_as_one_on_standard_input(tmp_path, capsys,
                                                                                       monkeypatch, sent, note):
    on_input, on_the_line = a_fact(tmp_path, "input"), a_fact(tmp_path, "line")
    standard_input(monkeypatch, sent)
    assert by_note_stdin(capsys, on_input) == (0, {"ok": True})
    assert by_note_on_the_line(capsys, on_the_line, sent) == (0, {"ok": True})
    assert stored(on_input)["note"] == stored(on_the_line)["note"] == note


def test_a_note_longer_than_two_thousand_characters_is_refused_in_plain_words_both_ways(tmp_path, capsys,
                                                                                       monkeypatch):
    longest, too_long = "a" * 2000, "a" * 2001
    run = a_fact(tmp_path, "longest-input")
    standard_input(monkeypatch, "\n " + longest + " \n")                  # the white space around it does not count
    assert by_note_stdin(capsys, run) == (0, {"ok": True}) and stored(run)["note"] == longest
    run = a_fact(tmp_path, "longest-line")
    assert by_note_on_the_line(capsys, run, longest) == (0, {"ok": True}) and stored(run)["note"] == longest
    run = a_fact(tmp_path, "too-long-input")
    standard_input(monkeypatch, too_long + "\n")
    code, out = by_note_stdin(capsys, run)
    assert code == 2 and "2,000 characters" in out["error"] and "note" in out["error"] and stored(run) is None
    run = a_fact(tmp_path, "too-long-line")
    code, out = by_note_on_the_line(capsys, run, too_long)
    assert code == 2 and "2,000 characters" in out["error"] and "note" in out["error"] and stored(run) is None


def test_the_limit_counts_the_note_as_stored_and_the_reference_says_so(tmp_path, capsys, monkeypatch):
    reference = (Path(__file__).parent.parent / "docs" / "engine.md").read_text(encoding="utf-8")
    assert ("a note longer than 2,000 characters as stored, after trimming and after its line ends have become "
            "spaces") in reference
    run = a_fact(tmp_path, "fits")                         # 2,001 characters sent: CR LF becomes one space
    standard_input(monkeypatch, "a" * 1998 + "\r\n" + "b")
    assert by_note_stdin(capsys, run) == (0, {"ok": True}) and len(stored(run)["note"]) == 2000
    run = a_fact(tmp_path, "too-long")
    standard_input(monkeypatch, "a" * 1999 + "\r\n" + "b")
    code, out = by_note_stdin(capsys, run)
    assert code == 2 and "2,000 characters" in out["error"] and stored(run) is None


class Terminal:
    """Standard input that is a terminal: reading it would wait for someone to type."""

    def __init__(self):
        self.buffer = self

    def isatty(self):
        return True

    def read(self, *size):
        raise AssertionError("the note was waited for on a terminal")


def test_note_stdin_from_a_terminal_is_refused_at_once_in_plain_words(tmp_path, capsys, monkeypatch):
    run = a_fact(tmp_path)
    monkeypatch.setattr("sys.stdin", Terminal())
    code, out = by_note_stdin(capsys, run)
    assert code == 2 and "the note is expected on standard input" in out["error"]
    assert stored(run) is None
