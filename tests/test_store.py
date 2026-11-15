import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import pytest
from radar import store
from helpers import make_run, add_source, add_fact, proposal

RADAR = Path(__file__).parent.parent / "bin" / "radar"

NOW = datetime(2026, 11, 12, 10, 15, 0, tzinfo=timezone.utc)

def test_init_run_creates_folder_and_run_json(tmp_path):
    run = store.init_run(tmp_path, "Who adds capacity?", "demo", now=NOW)
    assert run.name == "20261112-101500"
    data = store.load_run(run)
    assert data["question"] == "Who adds capacity?" and data["pack"] == "demo"
    assert data["language"] == "en" and data["illustrative"] is False
    assert data["checkpoints"] == [] and data["search_log"] == [] and data["excluded"] == []
    for sub in ("sources", "copies", "facts", "report"):
        assert (run / sub).is_dir()

def test_init_run_refuses_existing_folder(tmp_path):
    store.init_run(tmp_path, "q", "demo", run_id="r1")
    with pytest.raises(FileExistsError):
        store.init_run(tmp_path, "q", "demo", run_id="r1")

def test_public_mode_is_the_default(tmp_path):
    data = store.load_run(store.init_run(tmp_path, "q", "demo", run_id="r1"))
    assert data["mode"] == "public" and data["private_acknowledged_at"] is None

def test_private_mode_needs_acknowledgement_and_hides_itself_from_git(tmp_path):
    with pytest.raises(PermissionError):
        store.init_run(tmp_path, "q", "demo", run_id="r2", mode="private")
    assert not (tmp_path / "r2").exists()
    with pytest.raises(ValueError, match="--acknowledged-words"):   # fix wave A21: the reply comes with the yes
        store.init_run(tmp_path, "q", "demo", run_id="r2", mode="private", acknowledged=True, now=NOW)
    assert not (tmp_path / "r2").exists()
    run = store.init_run(tmp_path, "q", "demo", run_id="r2", mode="private", acknowledged=True, now=NOW,
                         acknowledged_words="Yes, go ahead.")
    data = store.load_run(run)
    assert data["mode"] == "private" and data["private_acknowledged_at"] == "2026-11-12T10:15:00Z"
    assert data["private_acknowledged_words"] == "Yes, go ahead."
    assert (run / ".gitignore").read_text(encoding="utf-8") == "*\n"

def test_ids_count_up_per_kind(tmp_path):
    run = make_run(tmp_path)
    assert store.next_id(run, "S") == "S1"
    add_source(run, "some text")
    assert store.next_id(run, "S") == "S2" and store.next_id(run, "F") == "F1"

def test_new_fact_sets_defaults(tmp_path):
    run = make_run(tmp_path)
    src = add_source(run, "text")
    fact = add_fact(run, source_id=src["id"])
    assert fact["id"] == "F1" and fact["status"] == "proposed"
    assert fact["checks"] == {"quote": None, "supporting": [], "support": None}
    assert store.read_facts(run)["F1"] == fact

def test_records_round_trip_german_text(tmp_path):
    run = make_run(tmp_path)
    src = add_source(run, "text", publisher="Müller & Söhne")
    add_fact(run, source_id=src["id"], quote="„Ausbau der Abfüllung“ schließt 2028 ab")
    raw = (run / "facts" / "F1.json").read_text(encoding="utf-8")
    assert "Abfüllung" in raw and "\\u00fc" not in raw
    assert store.read_sources(run)["S1"]["publisher"] == "Müller & Söhne"

def test_checkpoint_and_logs_append(tmp_path):
    run = make_run(tmp_path)
    store.record_checkpoint(run, "lenses", "test", "use both lenses", now=NOW)
    store.log_search(run, "press room of Competitor A", "2 releases found")
    store.log_excluded(run, "blog post", "no named author")
    data = store.load_run(run)
    assert data["checkpoints"] == [{"name": "lenses", "answered_by": "test",
                                    "answer": "use both lenses", "at": "2026-11-12T10:15:00Z"}]
    assert data["search_log"][0]["place"] == "press room of Competitor A"
    assert data["excluded"][0]["why"] == "no named author"

def test_checkpoint_rejects_unknown_values(tmp_path):
    run = make_run(tmp_path)
    with pytest.raises(ValueError):
        store.record_checkpoint(run, "lenses", "robot", "x")
    with pytest.raises(ValueError):
        store.record_checkpoint(run, "midway", "person", "x")

# --- beyond the brief's nine: behaviour the later tasks rely on ---

def test_new_fact_fills_missing_optional_keys_and_ignores_caller_status(tmp_path):
    run = make_run(tmp_path)
    src = add_source(run, "text")
    fact = store.new_fact(run, {"kind": "general", "statement": "s", "quote": "q",
                                "source_id": src["id"], "status": "confirmed"})
    assert fact["id"] == "F1" and fact["status"] == "proposed" and fact["status_reason"] is None
    assert fact["fields"] is None and fact["supporting"] == []
    assert fact["quote_translation"] is None and fact["tentative_reason"] is None
    assert fact["primary_source"] is None

def test_ids_use_highest_number_not_count(tmp_path):
    run = make_run(tmp_path)
    store.write_source(run, {"id": "S7"})
    assert store.next_id(run, "S") == "S8"
    with pytest.raises(ValueError):
        store.next_id(run, "X")

def test_readers_sort_by_number_and_skip_invalid_json(tmp_path):
    run = make_run(tmp_path)
    for _ in range(10):
        add_source(run, "t")
    (run / "sources" / "S3.json").write_text("{not json", encoding="utf-8")
    (run / "facts" / "F1.json").write_text("", encoding="utf-8")
    ids = list(store.read_sources(run))
    assert ids == ["S1", "S2", "S4", "S5", "S6", "S7", "S8", "S9", "S10"]
    assert store.read_facts(run) == {}

def test_analysis_round_trip(tmp_path):
    run = make_run(tmp_path)
    assert store.read_analysis(run) is None
    path = store.write_analysis(run, {"messages": []})
    assert path == run / "analysis.json"
    assert store.read_analysis(run) == {"messages": []}

def test_sha256_file(tmp_path):
    f = tmp_path / "x.txt"
    f.write_bytes(b"abc")
    assert store.sha256_file(f) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

def test_helpers_produce_complete_records(tmp_path):
    run = make_run(tmp_path)
    src = add_source(run, "hello world")
    assert (run / "copies" / "S1.txt").read_text(encoding="utf-8") == "hello world"
    assert src["copy_sha256"] == store.sha256_file(run / "copies" / "S1.txt")
    assert src["provenance"] is None and src["data_class"] == "public"
    assert src["url"] == "https://s1.example.com/S1" and src["access"] == "ok"
    internal = add_source(run, "x", data_class="internal")
    assert internal["provenance"] == {"supplied_by": "the tester", "basis": "own company document"}
    fact = add_fact(run, source_id="S1", fields={"company": "Other Co"})
    assert fact["kind"] == "capacity_move" and fact["fields"]["company"] == "Other Co"
    assert fact["fields"]["move_type"] == "expansion" and fact["fields"]["stage"] == "announced"

def test_make_run_creates_parents_and_passes_mode(tmp_path):
    run = make_run(tmp_path / "a" / "b", mode="private", acknowledged=True)
    assert store.load_run(run)["mode"] == "private"


# --- final fix I2: commands run in parallel keep every record ------------------------------------

# Each process loads the command the way `python -m radar` does, then waits for one common start time, so the
# commands really run at the same moment instead of one after another as Python starts up.
_DRIVER = ("import sys, time; sys.path.insert(0, sys.argv[1]); from radar.cli import main; "
           "time.sleep(max(0.0, float(sys.argv[2]) - time.time())); sys.exit(main(sys.argv[3:]))")


def run_in_parallel(argvs, delay=1.5, offsets=None):
    """Start every `radar` command at the same moment and wait for all; return (exit code, stdout, stderr) of each.

    `delay` is the time every process has to start up before the common start; many processes need more. `offsets`
    (seconds, one per command) starts a command that much after the common start."""
    start = time.time() + delay
    offsets = offsets or [0.0] * len(argvs)
    engine = RADAR.parent.parent / "engine"
    processes = [subprocess.Popen([sys.executable, "-c", _DRIVER, str(engine), str(start + offset), *argv],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for argv, offset in zip(argvs, offsets)]
    results = []
    for process in processes:
        out, err = process.communicate(timeout=120)
        results.append((process.returncode, out, err))
    return results


def test_twelve_parallel_add_fact_commands_leave_twelve_facts_with_distinct_ids(tmp_path):
    run = make_run(tmp_path / "runs")
    add_source(run, "Competitor A will add a second filling line at Plant North by 2028.")
    file = tmp_path / "proposal.json"
    file.write_text(json.dumps(proposal()), encoding="utf-8")
    results = run_in_parallel([["add-fact", "--run", str(run), "--file", str(file)]] * 12)
    assert [code for code, _, _ in results] == [0] * 12, results
    ids = {json.loads(out)["fact_id"] for _, out, _ in results}
    assert ids == {f"F{n}" for n in range(1, 13)}
    assert set(store.read_facts(run)) == ids
    assert store.load_run(run)["facts_created"] == 12


def test_twelve_parallel_log_search_commands_leave_twelve_entries(tmp_path):
    run = make_run(tmp_path)
    results = run_in_parallel([["log-search", "--run", str(run), "--place", f"place {n}", "--result", "r"]
                               for n in range(12)])
    assert [code for code, _, _ in results] == [0] * 12, results
    assert sorted(entry["place"] for entry in store.load_run(run)["search_log"]) == sorted(f"place {n}" for n in range(12))


COPIES = 16   # copies of one run, each with its own pair of commands, all started together
FACTS = 30
LAST = f"F{FACTS}"
LATER = 0.1   # the second command of each pair starts this many seconds after the first, while that one works


def _slow_run(tmp_path):
    """A finished run whose analysis rests on its last fact, F30. Its one saved copy is long, so settle and
    check-quotes spend a while (half a second or more) on the 29 facts before F30, which they read at the start and
    write at the end. A command that changes F30 in that time is what the run lock must not let them overwrite."""
    from helpers import finish_run
    run = make_run(tmp_path / "runs")
    add_source(run, "An unrelated sentence about the weather on the coast. " * 1500
               + "Competitor A will add a second filling line at Plant North by 2028.")
    for _ in range(FACTS):
        add_fact(run, primary_source=True)
    finish_run(run, [LAST])
    return run


def _copies_of(run, tmp_path):
    copies = [tmp_path / "copies" / f"c{n}" for n in range(COPIES)]
    for copy in copies:
        shutil.copytree(run, copy)
    return copies


def test_withdraw_fact_against_settle_never_loses_the_withdrawal(tmp_path):
    from radar.gate import gate
    run = _slow_run(tmp_path)
    assert gate(run) == []
    copies = _copies_of(run, tmp_path)
    commands = []
    for copy in copies:
        commands += [["settle", "--run", str(copy)],
                     ["withdraw-fact", "--run", str(copy), "--fact", LAST, "--reason", "withdrawn in parallel"]]
    results = run_in_parallel(commands, delay=2.0, offsets=[0.0, LATER] * COPIES)
    assert [code for code, _, _ in results] == [0] * len(commands), results
    lost = [copy.name for copy in copies if not isinstance(store.read_facts(copy)[LAST].get("withdrawn"), dict)]
    assert lost == [], f"the withdrawal was lost in {len(lost)} of {COPIES} copies"
    for copy in copies:
        assert store.read_facts(copy)[LAST]["withdrawn"]["reason"] == "withdrawn in parallel"
    for code, out, _ in run_in_parallel([["gate", "--run", str(copy)] for copy in copies]):   # the real gate, at once
        problems = json.loads(out)["problems"]
        assert code == 1 and any(p["file"] == f"facts/{LAST}.json" or f"fact {LAST} " in p["message"]
                                 for p in problems), problems


def test_record_support_against_check_quotes_never_loses_the_verdict(tmp_path):
    copies = _copies_of(_slow_run(tmp_path), tmp_path)
    last = LAST   # read at the start of check-quotes and written at its end
    commands = []
    for copy in copies:
        commands += [["check-quotes", "--run", str(copy)],
                     ["record-support", "--run", str(copy), "--fact", last, "--passed", "true",
                      "--by", "parallel checker", "--note", "recorded in parallel"]]
    results = run_in_parallel(commands, delay=2.0, offsets=[0.0, LATER] * COPIES)
    assert [code for code, _, _ in results] == [0] * len(commands), results
    lost = [copy.name for copy in copies
            if store.read_facts(copy)[last]["checks"]["support"]["note"] != "recorded in parallel"]
    assert lost == [], f"the verdict was lost in {len(lost)} of {COPIES} copies"
    for copy in copies:
        support = store.read_facts(copy)[last]["checks"]["support"]
        assert (support["by"], support["note"]) == ("parallel checker", "recorded in parallel"), copy


def test_the_fact_changing_commands_wait_for_the_run_lock(tmp_path, capsys):
    from radar import verify
    from radar.cli import main
    run = make_run(tmp_path)
    add_source(run, "Competitor A will add a second filling line at Plant North by 2028.")
    add_fact(run)
    commands = [["check-quotes", "--run", str(run)], ["settle", "--run", str(run)],
                ["withdraw-fact", "--run", str(run), "--fact", "F1", "--reason", "held"],
                ["record-support", "--run", str(run), "--fact", "F1", "--passed", "true", "--by", "c", "--note", "n"]]
    for argv in commands:
        holder = subprocess.Popen([sys.executable, "-c",
                                   "import sys, time; sys.path.insert(0, sys.argv[1]); from radar import store; "
                                   "lock = store.locked(sys.argv[2]); lock.__enter__(); print('held', flush=True); "
                                   "time.sleep(0.6); lock.__exit__(None, None, None)",
                                   str(RADAR.parent.parent / "engine"), str(run)], stdout=subprocess.PIPE, text=True)
        assert holder.stdout.readline().strip() == "held"
        started = time.time()
        assert main(argv) == 0, argv
        assert time.time() - started >= 0.4, argv   # it waited until the holder let go
        holder.wait(timeout=10)
        holder.stdout.close()
        capsys.readouterr()
    assert verify.settle(run) == {"F1": "rejected"}


def test_the_locked_fact_commands_refuse_a_folder_that_is_not_a_run_and_leave_no_lock_there(tmp_path, capsys):
    from radar.cli import main
    not_a_run = tmp_path / "notes"
    not_a_run.mkdir()
    for folder in (not_a_run, tmp_path / "missing"):
        for argv in (["check-quotes"], ["settle"], ["withdraw-fact", "--fact", "F1", "--reason", "r"],
                     ["record-support", "--fact", "F1", "--passed", "true", "--by", "c", "--note", "n"]):
            assert main([argv[0], "--run", str(folder), *argv[1:]]) == 2, argv
            out = json.loads(capsys.readouterr().out)
            assert out == {"error": f"{folder} is not the folder of a run. "
                                    "Give the folder that init-run made for the run."}, argv
    assert list(not_a_run.iterdir()) == [] and not (tmp_path / "missing").exists()


# --- follow-up, ruling HG12: waiting for the run lock has a limit; a dead holder never blocks ---------------------

BUSY = {"error": "Another command is still working on this run. Wait a moment and run this again.",
        "busy": True}   # A2 fix round 1, small point b: a helper tells "run it again" from "used wrongly"


def _holder(run, seconds, name=".lock"):
    """A separate process that takes the lock `name` of `run`, says so, and keeps it for `seconds`."""
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys, time; sys.path.insert(0, sys.argv[1]); from radar import store; "
                               "lock = store.locked(sys.argv[2], sys.argv[4], wait=None); lock.__enter__(); "
                               "print('held', flush=True); time.sleep(float(sys.argv[3]))",
         str(RADAR.parent.parent / "engine"), str(run), str(seconds), name], stdout=subprocess.PIPE, text=True)
    assert process.stdout.readline().strip() == "held"
    return process


def test_a_command_gives_up_after_the_wait_limit_and_changes_nothing(tmp_path, capsys, monkeypatch):
    from radar.cli import main
    monkeypatch.setattr(store, "LOCK_WAIT_SECONDS", 0.5)
    run = make_run(tmp_path)
    add_source(run, "Competitor A will add a second filling line at Plant North by 2028.")
    add_fact(run)
    before = {path.name: path.read_bytes() for path in (run / "facts").iterdir()}
    holder = _holder(run, 30)   # killed below, once every command has given up
    try:
        for argv in (["log-search", "--place", "p", "--result", "r"], ["settle"], ["check-quotes"],
                     ["withdraw-fact", "--fact", "F1", "--reason", "r"],
                     ["record-support", "--fact", "F1", "--passed", "true", "--by", "c", "--note", "n"],
                     ["checkpoint", "--name", "lenses", "--answered-by", "test", "--answer", "a"]):
            started = time.time()
            code = main([argv[0], "--run", str(run), *argv[1:]])
            out = capsys.readouterr().out
            assert (code, json.loads(out), out.count("\n")) == (2, BUSY, 1), argv
            assert 0.5 <= time.time() - started < 2.5, argv          # it waited the limit, then gave up
    finally:
        holder.kill(); holder.wait(); holder.stdout.close()
    assert store.load_run(run)["search_log"] == [] and store.load_run(run)["checkpoints"] == []
    assert {path.name: path.read_bytes() for path in (run / "facts").iterdir()} == before


def test_a_holder_that_was_killed_does_not_block_the_next_command(tmp_path, capsys, monkeypatch):
    from radar.cli import main
    monkeypatch.setattr(store, "LOCK_WAIT_SECONDS", 5)
    run = make_run(tmp_path)
    holder = _holder(run, 60)
    holder.kill(); holder.wait(); holder.stdout.close()                  # killed while it held the lock
    assert (run / ".lock").exists()                                        # the file stays; the lock does not
    started = time.time()
    assert main(["log-search", "--run", str(run), "--place", "p", "--result", "r"]) == 0
    assert time.time() - started < 1.0
    assert store.load_run(run)["search_log"] == [{"place": "p", "result": "r"}]


def test_the_wait_limit_is_sixty_seconds_by_default():
    assert store.LOCK_WAIT_SECONDS == 60


def test_counting_a_written_record_and_the_download_lock_keep_waiting_past_the_limit(tmp_path, monkeypatch):
    from radar import fetch
    monkeypatch.setattr(store, "LOCK_WAIT_SECONDS", 0.2)
    run = make_run(tmp_path)
    (run / "facts" / "F1.json").write_text("{}", encoding="utf-8")
    holder = _holder(run, 1.0)
    try:
        store.record_created(run, "F", "F1")          # the record is written: counting it never gives up
    finally:
        holder.wait(); holder.stdout.close()
    assert store.load_run(run)["facts_created"] == 1
    holder = _holder(run, 1.0, ".fetch.lock")
    try:
        fetch._wait_for_turn(run, "www.example.com", lambda seconds: None, time.time)   # its own behaviour: no limit
    finally:
        holder.wait(); holder.stdout.close()
    assert "www.example.com" in json.loads((run / ".last_fetch.json").read_text(encoding="utf-8"))


def test_mark_demo_run_holds_the_run_lock(tmp_path, monkeypatch):
    run = make_run(tmp_path, illustrative=True, mode="private", acknowledged=True)
    held = []
    original = store.locked

    def watching(run_dir, name=store.LOCK_FILE):
        held.append(name)
        return original(run_dir, name)
    monkeypatch.setattr(store, "locked", watching)
    store.mark_demo_run(run)
    assert held == [store.LOCK_FILE] and store.is_demo_private_run(store.load_run(run))


def test_reserve_id_claims_the_record_file_and_skips_a_taken_one(tmp_path):
    run = make_run(tmp_path)
    assert store.reserve_id(run, "F") == "F1" and (run / "facts" / "F1.json").exists()
    assert store.reserve_id(run, "F") == "F2"
    with pytest.raises(ValueError):
        store.reserve_id(run, "X")


def test_new_records_are_counted_in_run_json(tmp_path):
    run = make_run(tmp_path)
    data = store.load_run(run)
    assert (data["sources_created"], data["facts_created"]) == (0, 0)
    add_source(run, "text"); add_fact(run); add_fact(run)
    data = store.load_run(run)
    assert (data["sources_created"], data["facts_created"]) == (1, 2)


def test_a_run_without_counters_is_left_without_them(tmp_path):
    run = make_run(tmp_path)
    data = store.load_run(run); del data["facts_created"]; store.save_run(run, data)
    add_fact(run)
    assert "facts_created" not in store.load_run(run)


def test_the_lock_is_a_file_in_the_run_folder(tmp_path):
    run = make_run(tmp_path)
    with store.locked(run):
        pass
    assert (run / ".lock").exists()


# --- final fix S1 and S2: ids that stay inside the run folder, copies that stay out of git ---------

@pytest.mark.parametrize("run_id", ["../escaped", "a/b", "..", "x..y", "run one", "r\\1", "é"])
def test_init_run_refuses_a_run_id_that_could_leave_the_root(tmp_path, run_id):
    with pytest.raises(ValueError):
        store.init_run(tmp_path / "root", "q", "demo", run_id=run_id)
    assert not (tmp_path / "escaped").exists()


def test_records_need_an_id_of_their_kind(tmp_path):
    run = make_run(tmp_path)
    for bad in ("../S1", "S1/x", "F1", "S", "s1", None, 7):
        with pytest.raises(ValueError):
            store.write_source(run, {"id": bad})
    for bad in ("../F1", "S1", "F", "F1.json"):
        with pytest.raises(ValueError):
            store.write_fact(run, {"id": bad})
    store.write_source(run, {"id": "S12"}); store.write_fact(run, {"id": "F3"})


def test_init_run_keeps_saved_copies_out_of_git(tmp_path):
    run = make_run(tmp_path)
    assert (run / "copies" / ".gitignore").read_text(encoding="utf-8") == "*\n"


def test_init_run_does_not_preset_the_reading_date(tmp_path):
    assert "sources_read_until" not in store.load_run(make_run(tmp_path))


# --- a file nested too deeply to read is a named problem or a usage error, never a traceback ---------------

def _too_deep() -> str:
    depth = 150000
    return "[" * depth + "]" * depth


def test_a_record_nested_too_deeply_is_reported_as_not_valid_json(tmp_path):
    from radar.gate import gate
    from radar.schema import Problem, check_data
    from helpers import make_run, add_source, add_fact
    run = make_run(tmp_path)
    add_source(run, "The expansion adds two high-speed syringe lines for customers, starting in 2028.")
    add_fact(run, source_id="S1", quote="adds two high-speed syringe lines for customers")
    (run / "facts" / "F1.json").write_text(_too_deep(), encoding="utf-8")
    (run / "sources" / "S1.json").write_text(_too_deep(), encoding="utf-8")
    assert store.read_facts(run) == {} and store.read_sources(run) == {}
    for found in (check_data(run), gate(run)):
        assert Problem("facts/F1.json", None, "not valid JSON") in found
        assert Problem("sources/S1.json", None, "not valid JSON") in found


def test_run_and_analysis_nested_too_deeply_are_not_a_traceback(tmp_path, capsys):
    from helpers import make_run
    from radar.cli import main
    run = make_run(tmp_path)
    (run / "analysis.json").write_text(_too_deep(), encoding="utf-8")
    assert main(["gate", "--run", str(run)]) == 1
    capsys.readouterr()
    (run / "run.json").write_text(_too_deep(), encoding="utf-8")
    assert main(["check-data", "--run", str(run)]) == 1
    capsys.readouterr()
    assert main(["status", "--run", str(run)]) in (1, 2)       # an answer or a usage error, not a traceback


def test_a_proposal_or_option_file_nested_too_deeply_is_a_usage_error(tmp_path, capsys):
    from helpers import make_run, add_source
    from radar.cli import main
    run = make_run(tmp_path)
    add_source(run, "The expansion adds two high-speed syringe lines for customers, starting in 2028.")
    path = tmp_path / "deep.json"
    path.write_text(_too_deep(), encoding="utf-8")
    for command in (["add-fact", "--run", str(run), "--file", str(path)],
                    ["add-facts", "--run", str(run), "--file", str(path)],
                    ["check-data", "--from-json", str(path)]):
        assert main(command) == 2, command
        assert "error" in capsys.readouterr().out
    assert store.read_facts(run) == {}


def test_log_excluded_with_a_source_id_and_the_unknown_source_refusal(tmp_path):
    run = make_run(tmp_path); add_source(run, "text")
    store.log_excluded(run, "Source S1", "nothing usable", source_id="S1")
    assert store.load_run(run)["excluded"] == [{"what": "Source S1", "why": "nothing usable", "source_id": "S1"}]
    with pytest.raises(ValueError):
        store.log_excluded(run, "Source S2", "nothing usable", source_id="S2")
    assert len(store.load_run(run)["excluded"]) == 1


# --- Task 9: the engine's own files stay out of git, and so does a temporary file left behind -------------------

def test_a_public_run_keeps_its_lock_files_out_of_git(tmp_path):
    run = make_run(tmp_path)
    assert (run / ".gitignore").read_text(encoding="utf-8") == ".lock\n.fetch.lock\n.last_fetch.json\n.*.tmp\n"


def test_a_private_run_still_ignores_everything(tmp_path):
    run = make_run(tmp_path, mode="private", acknowledged=True)
    assert (run / ".gitignore").read_text(encoding="utf-8") == "*\n"


def test_git_leaves_out_what_the_program_writes_beside_the_records(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    run = make_run(tmp_path)
    for name in (".lock", ".fetch.lock", ".last_fetch.json"):
        (run / name).write_text("x", encoding="utf-8")
    (run / "facts" / ".F3.json.ab12.tmp").write_text("{}", encoding="utf-8")
    (run / "sources" / ".S1.json.cd34.tmp").write_text("{}", encoding="utf-8")
    add_source(run, "text")
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, env=environment)
    listed = subprocess.run(["git", "-C", str(tmp_path), "status", "--porcelain", "--untracked-files=all"],
                            capture_output=True, text=True, check=True, env=environment).stdout
    paths = [line[3:] for line in listed.splitlines()]
    assert sorted(paths) == ["run1/.gitignore", "run1/run.json", "run1/sources/S1.json"]


def test_a_temporary_file_left_behind_is_not_a_record(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "text")
    add_fact(run, source_id="S1")
    leftovers = [run / "facts" / ".F3.json.ab12.tmp", run / "facts" / ".F1.json.ab12.tmp",
                 run / "sources" / ".S2.json.cd34.tmp", run / "sources" / ".S1.json.cd34.tmp"]
    for path in leftovers:
        path.write_text(json.dumps({"id": path.name.split(".")[1]}), encoding="utf-8")
    assert list(store.read_facts(run)) == ["F1"] and list(store.read_sources(run)) == ["S1"]
    assert store.next_id(run, "F") == "F2" and store.next_id(run, "S") == "S2"
    assert [path.name for _, path in store._numbered_files(run, "F")] == ["F1.json"]
