import json

from radar import calc, store, verify
from radar.cli import main
from radar.gate import gate
from radar.schema import Problem
from helpers import make_run, add_source, add_fact, minimal_analysis

TEXT = "The expansion adds two high-speed syringe lines for customers, starting in 2028."
OTHER = "Competitor A confirmed two new syringe lines will open in 2028, the paper reported."


def passing_run(tmp_path, **run_over):
    run = make_run(tmp_path, **run_over)
    src = add_source(run, TEXT)
    add_fact(run, source_id=src["id"], primary_source=True, quote="adds two high-speed syringe lines for customers")
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    store.write_analysis(run, minimal_analysis(fact_ids=["F1"]))
    store.record_checkpoint(run, "lenses", "test", "ok"); store.record_checkpoint(run, "final_report", "test", "ok")
    return run


def add_rejected_fact(run):
    add_fact(run, source_id="S1", primary_source=True, quote="adds nine high-speed syringe lines for customers")
    verify.check_quotes(run); verify.record_support(run, "F2", True, "support-checker", ""); verify.settle(run)


def messages(problems):
    return [p.message for p in problems]


def edit_fact(run, fact_id, **changes):
    fact = store.read_facts(run)[fact_id]
    fact.update(changes)
    store.write_fact(run, fact)


def snapshot(run):
    return {str(p.relative_to(run)): p.read_bytes() for p in sorted(run.rglob("*")) if p.is_file()}


# --- the brief's tests -------------------------------------------------------------

def test_passing_run_opens_the_gate(tmp_path):
    assert gate(passing_run(tmp_path)) == []


def test_missing_analysis_and_checkpoints(tmp_path):
    run = passing_run(tmp_path)
    (run / "analysis.json").unlink()
    data = store.load_run(run); data["checkpoints"] = data["checkpoints"][:1]; store.save_run(run, data)
    problems = gate(run)
    assert Problem("analysis.json", None, "analysis is missing") in problems
    assert Problem("run.json", "checkpoints", "checkpoint final_report is not recorded") in problems


def test_hand_edited_status_is_caught(tmp_path):
    run = passing_run(tmp_path)
    add_fact(run, source_id="S1", primary_source=True, quote="adds nine high-speed syringe lines for customers")
    fact = store.read_facts(run)["F2"]
    fact.update(status="confirmed", checks={"quote": {"passed": True, "mode": "exact", "reason": None,
                "checked_at": "x", "copy_sha256": "x"}, "supporting": [],
                "support": {"passed": True, "by": "x", "note": "", "at": "x"}})
    store.write_fact(run, fact)
    assert Problem("facts/F2.json", "quote", "quote not found in saved copy") in gate(run)


def test_analysis_resting_on_rejected_fact_is_refused(tmp_path):
    run = passing_run(tmp_path)
    add_rejected_fact(run)
    store.write_analysis(run, minimal_analysis(fact_ids=["F1", "F2"]))
    problems = gate(run)
    assert "rests on fact F2 with status rejected" in messages(problems)
    assert Problem("analysis.json", "messages[0].chain[0].fact_ids",
                   "rests on fact F2 with status rejected") in problems


def test_rejected_fact_that_nothing_rests_on_is_fine(tmp_path):
    run = passing_run(tmp_path)
    add_rejected_fact(run)
    assert gate(run) == []


def test_publishable_gate_refuses_non_public_sources(tmp_path):
    run = passing_run(tmp_path, mode="private", acknowledged=True)
    add_source(run, "Internal capacity review. " * 20, data_class="internal", url="internal capacity review")
    assert gate(run) == []
    assert Problem("sources/S2.json", "data_class", "a publishable report may use public sources only") \
        in gate(run, publishable=True)


def test_unsettled_fact_blocks(tmp_path):
    run = passing_run(tmp_path)
    add_fact(run, source_id="S1", quote="adds two high-speed syringe lines for customers")
    assert Problem("facts/F2.json", "status", "fact was never settled") in gate(run)


def test_copy_changed_after_checking_blocks(tmp_path):
    run = passing_run(tmp_path)
    (run / "copies" / "S1.txt").write_text("something else entirely, now much shorter", encoding="utf-8")
    found = messages(gate(run))
    assert "saved copy has changed" in found and "quote not found in saved copy" in found


# --- the gate recomputes and does not write ----------------------------------------

def test_the_gate_leaves_every_file_byte_for_byte_unchanged(tmp_path):
    run = passing_run(tmp_path)
    add_rejected_fact(run)
    add_fact(run, source_id="S1", quote="adds two high-speed syringe lines for customers")  # unsettled
    store.write_analysis(run, minimal_analysis(fact_ids=["F1", "F2", "F3"]))
    (run / "copies" / "S1.txt").write_text("something else entirely, now much shorter", encoding="utf-8")
    before = snapshot(run)
    assert gate(run, publishable=True)  # the gate is closed, and still writes nothing
    assert snapshot(run) == before
    assert main(["gate", "--run", str(run)]) == 1
    assert snapshot(run) == before


def test_the_gate_does_not_trust_a_stored_quote_check(tmp_path):
    run = passing_run(tmp_path)
    (run / "copies" / "S1.txt").write_text("something else entirely, now much shorter", encoding="utf-8")
    stored = store.read_facts(run)["F1"]
    assert stored["checks"]["quote"]["passed"] is True  # the stale record still says it passed
    problems = gate(run)
    assert Problem("facts/F1.json", "quote", "quote not found in saved copy") in problems
    assert Problem("facts/F1.json", "status", "status does not follow from the checks") in problems


def test_support_check_not_passed_is_reported(tmp_path):
    run = passing_run(tmp_path)
    fact = store.read_facts(run)["F1"]
    fact["checks"]["support"]["passed"] = False
    store.write_fact(run, fact)
    problems = gate(run)
    assert Problem("facts/F1.json", "checks.support", "support check not passed") in problems
    assert Problem("facts/F1.json", "status", "status does not follow from the checks") in problems


def test_missing_support_check_is_reported(tmp_path):
    run = passing_run(tmp_path)
    fact = store.read_facts(run)["F1"]
    fact["checks"]["support"] = None
    store.write_fact(run, fact)
    assert Problem("facts/F1.json", "checks.support", "support check not passed") in gate(run)


def test_hand_edited_status_without_the_checks_behind_it_is_caught(tmp_path):
    run = passing_run(tmp_path)
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    edit_fact(run, "F2", status="confirmed")  # never checked, never supported
    problems = gate(run)
    assert Problem("facts/F2.json", "checks.support", "support check not passed") in problems
    assert Problem("facts/F2.json", "status", "status does not follow from the checks") in problems


def test_stored_confirmed_that_the_rules_would_now_call_uncertain_is_caught(tmp_path):
    run = make_run(tmp_path)
    add_source(run, TEXT, publisher="Competitor A")
    add_source(run, OTHER, publisher="Trade Paper")
    add_fact(run, source_id="S1", quote="adds two high-speed syringe lines for customers",
             supporting=[{"source_id": "S2", "quote": "two new syringe lines will open in 2028"}])
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    store.write_analysis(run, minimal_analysis(fact_ids=["F1"]))
    store.record_checkpoint(run, "lenses", "test", "ok"); store.record_checkpoint(run, "final_report", "test", "ok")
    assert store.read_facts(run)["F1"]["status"] == "confirmed"
    assert gate(run) == []
    (run / "copies" / "S2.txt").write_text("a different report that says nothing of the kind", encoding="utf-8")
    problems = gate(run)
    assert Problem("facts/F1.json", "status", "status does not follow from the checks") in problems
    assert Problem("facts/F1.json", "quote", "quote not found in saved copy") not in problems


def test_uncertain_fact_that_still_follows_from_its_checks_passes(tmp_path):
    run = make_run(tmp_path)
    add_source(run, TEXT)
    add_fact(run, source_id="S1", quote="adds two high-speed syringe lines for customers")  # not primary
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    assert store.read_facts(run)["F1"]["status"] == "uncertain"
    store.write_analysis(run, minimal_analysis(fact_ids=["F1"]))
    store.record_checkpoint(run, "lenses", "test", "ok"); store.record_checkpoint(run, "final_report", "test", "ok")
    assert gate(run) == []


def test_changing_primary_source_after_the_support_check_blocks(tmp_path):
    run = make_run(tmp_path)
    add_source(run, TEXT)
    add_fact(run, source_id="S1", quote="adds two high-speed syringe lines for customers")  # not primary
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    store.write_analysis(run, minimal_analysis(fact_ids=["F1"]))
    store.record_checkpoint(run, "lenses", "test", "ok"); store.record_checkpoint(run, "final_report", "test", "ok")
    edit_fact(run, "F1", primary_source=True, status="confirmed", status_reason=None)
    assert Problem("facts/F1.json", "status", "status does not follow from the checks") in gate(run)


def test_edited_statement_after_the_support_check_blocks(tmp_path):
    run = passing_run(tmp_path)
    edit_fact(run, "F1", statement="Competitor A will add ten lines.")
    assert Problem("facts/F1.json", "status", "status does not follow from the checks") in gate(run)


def test_analysis_resting_on_a_proposed_fact_is_refused(tmp_path):
    run = passing_run(tmp_path)
    add_fact(run, source_id="S1", quote="adds two high-speed syringe lines for customers")
    store.write_analysis(run, minimal_analysis(fact_ids=["F1", "F2"]))
    assert "rests on fact F2 with status proposed" in messages(gate(run))


def test_analysis_resting_on_a_missing_fact_is_refused_with_its_field_path(tmp_path):
    run = passing_run(tmp_path)
    analysis = minimal_analysis(fact_ids=["F1"])
    analysis["demand_signals"] = [{"text": "t", "fact_ids": ["F9"]}]
    store.write_analysis(run, analysis)
    problems = gate(run)
    assert Problem("analysis.json", "demand_signals[0].fact_ids", "fact F9 does not exist") in problems
    assert Problem("analysis.json", "demand_signals[0].fact_ids", "rests on fact F9 with status missing") in problems


def test_problems_come_in_a_stable_order(tmp_path):
    run = passing_run(tmp_path, mode="private", acknowledged=True)
    add_source(run, "Internal capacity review. " * 20, data_class="internal", url="internal capacity review")
    add_rejected_fact(run)
    add_fact(run, source_id="S1", quote="adds two high-speed syringe lines for customers")  # F3, unsettled
    store.write_analysis(run, minimal_analysis(fact_ids=["F1", "F2"]))
    data = store.load_run(run); data["checkpoints"] = []; store.save_run(run, data)
    (run / "copies" / "S1.txt").write_text("something else entirely, now much shorter", encoding="utf-8")
    expected = [
        Problem("sources/S1.json", "copy_sha256", "saved copy has changed"),  # check_data first
        Problem("run.json", "checkpoints", "checkpoint lenses is not recorded"),
        Problem("run.json", "checkpoints", "checkpoint final_report is not recorded"),
        Problem("facts/F1.json", "quote", "quote not found in saved copy"),
        Problem("facts/F1.json", "status", "status does not follow from the checks"),
        Problem("analysis.json", "messages[0].chain[0].fact_ids", "rests on fact F2 with status rejected"),
        Problem("facts/F3.json", "status", "fact was never settled"),
        Problem("run.json", "mode", "a publishable report may not be built from a private run"),
        Problem("sources/S2.json", "data_class", "a publishable report may use public sources only"),
    ]
    assert gate(run, publishable=True) == expected
    assert gate(run, publishable=True) == expected


# --- hand-edited and broken records never make the gate raise ----------------------

def test_broken_files_become_problems_not_tracebacks(tmp_path):
    run = passing_run(tmp_path)
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    (run / "facts" / "F2.json").write_text("", encoding="utf-8")
    (run / "sources" / "S2.json").write_text("{not json", encoding="utf-8")
    (run / "analysis.json").write_text("[1, 2]", encoding="utf-8")
    problems = gate(run)
    assert Problem("facts/F2.json", None, "not valid JSON") in problems
    assert Problem("sources/S2.json", None, "not valid JSON") in problems
    assert Problem("analysis.json", None, "not valid JSON") in problems


def test_missing_or_broken_run_json_does_not_raise(tmp_path):
    run = passing_run(tmp_path)
    (run / "run.json").write_text("", encoding="utf-8")
    assert Problem("run.json", None, "not valid JSON") in gate(run)
    (run / "run.json").unlink()
    assert Problem("run.json", None, "run.json is missing") in gate(run)
    (run / "run.json").write_text(json.dumps({"checkpoints": {"name": "lenses"}}), encoding="utf-8")
    assert Problem("run.json", "checkpoints", "checkpoint lenses is not recorded") in gate(run)
    (run / "run.json").write_text(json.dumps({"checkpoints": [7, None, {"name": ["x"]}]}), encoding="utf-8")
    assert Problem("run.json", "checkpoints", "checkpoint final_report is not recorded") in gate(run)


def test_fact_with_garbage_in_every_field_does_not_raise(tmp_path):
    run = passing_run(tmp_path)
    fact = store.read_facts(run)["F1"]
    fact.update(checks="garbage", supporting="abc", source_id=["S1"], quote=5, fields=[1], certainty=3,
                primary_source="yes")
    store.write_fact(run, fact)
    problems = gate(run)
    assert Problem("facts/F1.json", "quote", "quote not found in saved copy") in problems
    assert Problem("facts/F1.json", "checks.support", "support check not passed") in problems


def test_fact_with_odd_checks_and_supporting_entries_does_not_raise(tmp_path):
    run = passing_run(tmp_path)
    fact = store.read_facts(run)["F1"]
    fact["supporting"] = [None, "x", {"source_id": {"a": 1}, "quote": 3}, {"source_id": "S9", "quote": "q"}]
    fact["checks"] = {"quote": [], "supporting": "no", "support": "passed"}
    store.write_fact(run, fact)
    problems = gate(run)
    assert Problem("facts/F1.json", "checks.support", "support check not passed") in problems


def test_source_with_garbage_copy_file_does_not_raise(tmp_path):
    run = passing_run(tmp_path)
    for value in (5, None, ["copies/S1.txt"], "../../etc/passwd", "copies/S1\x00.txt", "copies"):
        source = store.read_sources(run)["S1"]
        source["copy_file"] = value
        store.write_source(run, source)
        assert Problem("facts/F1.json", "quote", "quote not found in saved copy") in gate(run)


def test_analysis_with_garbage_references_does_not_raise(tmp_path):
    run = passing_run(tmp_path)
    analysis = minimal_analysis(fact_ids=["F1"])
    analysis["demand_signals"] = [{"text": "t", "fact_ids": "F1"}, {"text": "t", "fact_ids": [3, None, ["F1"], "F1"]}]
    analysis["messages"].append("not a message")
    store.write_analysis(run, analysis)
    problems = gate(run)
    assert Problem("analysis.json", "demand_signals[0].fact_ids", "not an allowed value") in problems
    assert not [p for p in problems if p.message.startswith("rests on")]


def test_run_folder_without_any_records_does_not_raise(tmp_path):
    run = make_run(tmp_path)
    assert messages(gate(run)) == ["analysis is missing", "checkpoint lenses is not recorded",
                                   "checkpoint final_report is not recorded"]


# --- the command ---------------------------------------------------------------------

def run_cli(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    return code, json.loads(out)


def test_cli_gate_open(tmp_path, capsys):
    run = passing_run(tmp_path)
    assert run_cli(capsys, "gate", "--run", str(run)) == (0, {"open": True, "problems": [], "explained": []})


def test_cli_gate_closed_lists_problems(tmp_path, capsys):
    run = passing_run(tmp_path)
    (run / "analysis.json").unlink()
    code, out = run_cli(capsys, "gate", "--run", str(run))
    assert code == 1 and out["open"] is False
    assert {"file": "analysis.json", "field": None, "message": "analysis is missing"} in out["problems"]


def test_cli_gate_publishable_flag(tmp_path, capsys):
    run = passing_run(tmp_path, mode="private", acknowledged=True)
    add_source(run, "Internal capacity review. " * 20, data_class="internal", url="internal capacity review")
    assert run_cli(capsys, "gate", "--run", str(run))[0] == 0
    code, out = run_cli(capsys, "gate", "--run", str(run), "--publishable")
    assert code == 1
    assert {"file": "sources/S2.json", "field": "data_class",
            "message": "a publishable report may use public sources only"} in out["problems"]


def test_cli_gate_lenses_option(tmp_path, capsys):
    run = passing_run(tmp_path)
    store.write_analysis(run, minimal_analysis(fact_ids=["F1"], lens_id="no-such-lens"))
    lenses = tmp_path / "lenses"; lenses.mkdir()
    assert run_cli(capsys, "gate", "--run", str(run))[0] == 0
    code, out = run_cli(capsys, "gate", "--run", str(run), "--lenses", str(lenses))
    assert code == 1 and any("no-such-lens" in p["message"] for p in out["problems"])


# --- final fix C1 and I6: supporting quotes, and every settled status and reason re-derived ---

INVENTED = "five new syringe lines will open in 2031"


def run_with_supported_fact(tmp_path, supporting_quote, primary_source=True):
    """A passing run (F1 on S1) plus F2 on S1 whose supporting entry quotes S2 (from another publisher)."""
    run = passing_run(tmp_path)
    add_source(run, OTHER, publisher="Trade Paper")
    add_fact(run, source_id="S1", primary_source=primary_source, quote="adds two high-speed syringe lines for customers",
             supporting=[{"source_id": "S2", "quote": supporting_quote}])
    verify.check_quotes(run); verify.record_support(run, "F2", True, "support-checker", ""); verify.settle(run)
    return run


def test_a_hand_edited_confirmed_on_a_fact_with_an_invented_supporting_quote_is_refused(tmp_path):
    run = run_with_supported_fact(tmp_path, INVENTED)
    assert store.read_facts(run)["F2"]["status"] == "rejected"
    assert gate(run) == []
    edit_fact(run, "F2", status="confirmed", status_reason=None)
    problems = gate(run)
    assert Problem("facts/F2.json", "status", "status does not follow from the checks") in problems
    assert Problem("facts/F2.json", "supporting[0].quote", "supporting quote not found in saved copy") in problems


def test_a_supporting_copy_changed_after_settling_is_caught(tmp_path):
    run = run_with_supported_fact(tmp_path, "two new syringe lines will open in 2028")
    assert store.read_facts(run)["F2"]["status"] == "confirmed" and gate(run) == []
    (run / "copies" / "S2.txt").write_text("a different report that says nothing of the kind", encoding="utf-8")
    problems = gate(run)
    assert Problem("facts/F2.json", "supporting[0].quote", "supporting quote not found in saved copy") in problems
    assert Problem("facts/F2.json", "status", "status does not follow from the checks") in problems


def test_a_hand_written_reason_on_an_uncertain_fact_is_refused(tmp_path):
    run = passing_run(tmp_path)
    add_fact(run, source_id="S1", quote="adds two high-speed syringe lines for customers")   # not primary
    verify.check_quotes(run); verify.record_support(run, "F2", True, "support-checker", ""); verify.settle(run)
    assert store.read_facts(run)["F2"]["status"] == "uncertain" and gate(run) == []
    edit_fact(run, "F2", status_reason="two independent analysts agree")
    assert gate(run) == [Problem("facts/F2.json", "status_reason", "reason does not follow from the checks")]


def test_a_hand_written_reason_on_a_rejected_fact_is_refused(tmp_path):
    run = passing_run(tmp_path)
    add_rejected_fact(run)
    assert store.read_facts(run)["F2"]["status_reason"] == "not_found" and gate(run) == []
    edit_fact(run, "F2", status_reason="not_supported")
    assert gate(run) == [Problem("facts/F2.json", "status_reason", "reason does not follow from the checks")]


def test_a_hand_set_rejected_on_a_fact_whose_checks_pass_is_refused(tmp_path):
    run = passing_run(tmp_path)
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    verify.check_quotes(run); verify.record_support(run, "F2", True, "support-checker", ""); verify.settle(run)
    assert gate(run) == []
    edit_fact(run, "F2", status="rejected", status_reason="not_found")
    assert gate(run) == [Problem("facts/F2.json", "status", "status does not follow from the checks")]


# --- final fix C3: the comparison with an earlier run is checked like everything else ---

def compare(previous, current):
    assert main(["compare", "--previous", str(previous), "--current", str(current)]) == 0


def test_a_comparison_against_a_private_run_is_refused_for_publishing(tmp_path, capsys):
    from radar.report.build import build_report
    from test_report_build import LENSES
    previous = passing_run(tmp_path / "prev", mode="private", acknowledged=True)
    add_source(previous, "Internal capacity review. " * 20, data_class="internal", url="internal capacity review")
    current = passing_run(tmp_path / "cur", mode="private", acknowledged=True)   # a public run is refused (HG1)
    compare(previous, current)
    assert gate(current) == []
    assert gate(current, publishable=True) == [Problem("run.json", "mode", "a publishable report may not be built from a private run"), Problem(
        "changes.json", "previous_confidential",
        "a publishable report may not compare against a run with non-public sources")]
    build_report(current, LENSES)
    assert "Confidential." in (current / "report" / "report.md").read_text(encoding="utf-8")
    assert (current / "report" / "facts-confidential.csv").exists()


def test_a_comparison_that_is_not_an_object_is_refused(tmp_path, capsys):
    run = passing_run(tmp_path)
    (run / "changes.json").write_text("[1, 2]", encoding="utf-8")
    assert Problem("changes.json", None, "not valid JSON") in gate(run)
    (run / "changes.json").write_text("{not json", encoding="utf-8")
    assert Problem("changes.json", None, "not valid JSON") in gate(run)


def test_a_comparison_without_a_digest_is_out_of_date(tmp_path, capsys):
    run = passing_run(tmp_path)
    store.write_changes(run, {"previous_run": "r0", "current_run": "run1", "new": [{"fact_id": "F1"}]})
    assert gate(run) == [Problem("changes.json", None, "the comparison is out of date"),
                         Problem("changes.json", None, "the comparison was changed after it was made"),
                         Problem("changes.json", "previous_illustrative",
                                 "the comparison was made by an earlier version of the program")]


def test_a_fact_rejected_after_the_comparison_makes_it_out_of_date(tmp_path, capsys):
    previous = passing_run(tmp_path / "prev")
    current = passing_run(tmp_path / "cur")
    add_fact(current, source_id="S1", primary_source=True, quote="two high-speed syringe lines for customers, starting in 2028",
             fields={"site": "Plant South"})
    verify.check_quotes(current); verify.record_support(current, "F2", True, "support-checker", ""); verify.settle(current)
    compare(previous, current)
    assert gate(current) == []
    verify.record_support(current, "F2", False, "support-checker", "the year is not stated for Plant South")
    verify.settle(current)
    assert gate(current) == [Problem("changes.json", None, "the comparison is out of date")]
    compare(previous, current)
    assert gate(current) == []


def test_a_comparison_made_before_settling_is_out_of_date_after_settling(tmp_path, capsys):
    previous = passing_run(tmp_path / "prev")
    current = passing_run(tmp_path / "cur")
    add_fact(current, source_id="S1", primary_source=True, quote="two high-speed syringe lines for customers, starting in 2028",
             fields={"site": "Plant South"})
    verify.check_quotes(current); verify.record_support(current, "F2", True, "support-checker", "")
    compare(previous, current)                       # F2 is still proposed, so it is not compared
    verify.settle(current)
    assert Problem("changes.json", None, "the comparison is out of date") in gate(current)
    compare(previous, current)
    assert gate(current) == []



# --- final fix I3: a withdrawn fact stops counting, and a bad proposal no longer blocks for good ---

def test_after_withdraw_and_settle_the_gate_refuses_an_analysis_that_rests_on_the_fact(tmp_path, capsys):
    run = passing_run(tmp_path)
    assert main(["withdraw-fact", "--run", str(run), "--fact", "F1", "--reason", "the release was retracted"]) == 0
    assert Problem("facts/F1.json", "status", "status does not follow from the checks") in gate(run)
    verify.settle(run)
    assert store.read_facts(run)["F1"]["status"] == "rejected"
    assert gate(run) == [Problem("analysis.json", "messages[0].chain[0].fact_ids",
                                 "rests on fact F1 with status rejected")]


def test_a_proposal_with_a_short_quote_can_be_withdrawn_so_it_stops_blocking(tmp_path):
    run = passing_run(tmp_path)
    add_fact(run, source_id="S1", primary_source=True, quote="two syringe lines")   # written before add-fact checked it
    assert Problem("facts/F2.json", "quote", "quote must have 5 to 50 words") in gate(run)
    verify.withdraw_fact(run, "F2", "the quote is too short to check")
    verify.settle(run)
    assert gate(run) == []


def test_a_deleted_fact_file_closes_the_gate(tmp_path):
    run = passing_run(tmp_path)
    add_rejected_fact(run)
    (run / "facts" / "F2.json").unlink()
    assert gate(run) == [Problem("run.json", "facts_created", "fact F2 is missing")]


def test_a_fact_withdrawn_after_the_comparison_makes_it_out_of_date(tmp_path, capsys):
    previous = passing_run(tmp_path / "prev")
    current = passing_run(tmp_path / "cur")
    add_fact(current, source_id="S1", primary_source=True, quote="two high-speed syringe lines for customers, starting in 2028",
             fields={"site": "Plant South"})
    verify.check_quotes(current); verify.record_support(current, "F2", True, "support-checker", ""); verify.settle(current)
    compare(previous, current)
    verify.withdraw_fact(current, "F2", "Plant South was a typing error")
    verify.settle(current)
    assert gate(current) == [Problem("changes.json", None, "the comparison is out of date")]
    compare(previous, current)
    assert gate(current) == []


# --- an early signal never passes the gate as confirmed --------------------------------------------

def early_signal_run(tmp_path):
    from helpers import PERMIT_TEXT, add_early_signal
    run = make_run(tmp_path)
    add_source(run, PERMIT_TEXT, type="permit", publisher="Planning Office")
    add_early_signal(run)
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    store.write_analysis(run, minimal_analysis(fact_ids=["F1"]))
    store.record_checkpoint(run, "lenses", "test", "ok"); store.record_checkpoint(run, "final_report", "test", "ok")
    return run


def test_a_settled_early_signal_opens_the_gate_as_uncertain(tmp_path):
    run = early_signal_run(tmp_path)
    assert store.read_facts(run)["F1"]["status"] == "uncertain"
    assert gate(run) == []


def test_a_hand_edited_early_signal_cannot_pass_as_confirmed(tmp_path):
    run = early_signal_run(tmp_path)
    # made firm by hand, a fresh support check recorded for the new content, and the status set to confirmed
    edit_fact(run, "F1", certainty="firm", tentative_reason=None, status="confirmed", status_reason=None)
    verify.record_support(run, "F1", True, "support-checker", "")
    found = gate(run)
    assert Problem("facts/F1.json", "certainty", "an early signal must be marked tentative") in found
    assert Problem("facts/F1.json", "status", "status does not follow from the checks") in found
    # even with the certainty left tentative, the status alone cannot be raised
    edit_fact(run, "F1", certainty="tentative", tentative_reason="a planning application", status="confirmed",
              status_reason=None)
    verify.record_support(run, "F1", True, "support-checker", "")
    assert Problem("facts/F1.json", "status", "status does not follow from the checks") in gate(run)


# --- a fact from a job posting, permit or regulator record is an early signal even without the mark ------------

SOURCE_RULE = "a fact from a permit, a job posting or a regulator record must be marked as an early signal"


def job_posting_probe_run(tmp_path):
    """The probe: a capacity move whose only source is a job posting, with no early_signal key and a primary source."""
    run = make_run(tmp_path)
    add_source(run, TEXT, type="job_posting", publisher="Careers Page")
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    fact = store.read_facts(run)["F1"]
    fact.pop("early_signal", None)                       # as a hand edit or an older proposal would leave it
    store.write_fact(run, fact)
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    analysis = minimal_analysis(fact_ids=["F1"])
    analysis["calculations"] = [{"id": "C1", "label": "Lines", "operation": "sum", "unit": "lines",
                                 "fact_ids": ["F1"], "of_fact_ids": [], "result": "2"}]
    store.write_analysis(run, analysis)
    store.record_checkpoint(run, "lenses", "test", "ok"); store.record_checkpoint(run, "final_report", "test", "ok")
    return run


def test_the_probe_settles_uncertain_and_the_gate_refuses_it(tmp_path):
    run = job_posting_probe_run(tmp_path)
    fact = store.read_facts(run)["F1"]
    assert (fact["status"], fact["status_reason"]) == ("uncertain", verify.EARLY_SIGNAL_REASON)   # never confirmed
    found = gate(run)
    assert Problem("facts/F1.json", "early_signal", SOURCE_RULE) in found
    assert not any(p.message == "status does not follow from the checks" for p in found)      # settled correctly
    fact["status"], fact["status_reason"] = "confirmed", None                                  # raised by hand
    store.write_fact(run, fact)
    assert Problem("facts/F1.json", "status", "status does not follow from the checks") in gate(run)


def test_a_total_over_the_probe_is_refused(tmp_path):
    run = job_posting_probe_run(tmp_path)
    assert Problem("analysis.json", "calculations[0]", "input F1 is not a settled capacity move") in gate(run)
    result = calc.compute({"operation": "sum", "unit": "lines", "fact_ids": ["F1"]}, store.read_facts(run),
                          store.read_sources(run))
    assert result.value is None and result.problems == ["input F1 is not a settled capacity move"]
    assert main(["calc", "--run", str(run), "--operation", "sum", "--unit", "lines", "--facts", "F1"]) == 1


def test_a_marked_early_signal_is_not_a_calculation_input_either(tmp_path):
    run = early_signal_run(tmp_path)
    facts = store.read_facts(run)
    assert facts["F1"]["status"] == "uncertain"
    facts["F1"]["kind"] = "capacity_move"
    facts["F1"]["fields"] = {"size_value": "2", "size_unit": "lines"}
    facts["F1"]["certainty"] = "firm"
    result = calc.compute({"operation": "count", "fact_ids": ["F1"]}, facts, store.read_sources(run))
    assert result.problems == ["input F1 is not a settled capacity move"]


def test_a_baseline_resting_on_a_rejected_fact_is_refused(tmp_path):
    run = passing_run(tmp_path)
    add_rejected_fact(run)
    analysis = minimal_analysis(fact_ids=["F1"])
    analysis["baselines"] = [{"company": "Competitor A", "fact_ids": ["F1", "F2"]}]
    store.write_analysis(run, analysis)
    assert Problem("analysis.json", "baselines[0].fact_ids", "rests on fact F2 with status rejected") in gate(run)
    analysis["baselines"] = [{"company": "Competitor A", "fact_ids": ["F1"]}]
    store.write_analysis(run, analysis)
    assert gate(run) == []


def test_a_baseline_never_rests_on_an_early_signal_by_mark_or_by_source(tmp_path):
    from helpers import PERMIT_TEXT, add_early_signal
    from radar.explain import explain
    from radar.schema import check_data
    run = passing_run(tmp_path)
    add_source(run, PERMIT_TEXT, type="permit", publisher="Planning Office")              # S2, a permit
    add_early_signal(run, source_id="S2")                                                  # F2, marked
    add_fact(run, source_id="S2", kind="general", fields=None, primary_source=True, early_signal=False,
             certainty="tentative", tentative_reason="a planning application",
             quote="an application for a new filling hall at Plant North")   # F3: unmarked, a hint by its source
    analysis = minimal_analysis(fact_ids=["F1"])
    analysis["baselines"] = [{"company": "Competitor A", "fact_ids": ["F1", "F2"]},
                             {"company": "Planning Office", "fact_ids": ["F3"]}]
    store.write_analysis(run, analysis)
    problems = check_data(run)
    assert Problem("analysis.json", "baselines[0].fact_ids", "a baseline may not rest on F2, an early signal") in problems
    assert Problem("analysis.json", "baselines[1].fact_ids", "a baseline may not rest on F3, an early signal") in problems
    assert not any("rest on F1" in p.message for p in problems)
    explained = explain(Problem("analysis.json", "baselines[0].fact_ids", "a baseline may not rest on F12, an early signal"))
    assert explained["known"] is True and "rests on F12, which" in explained["what"]
    analysis["baselines"] = [{"company": "Competitor A", "fact_ids": ["F1"]}]
    store.write_analysis(run, analysis)
    assert not any("baseline" in p.message for p in check_data(run))


# --- fix round 2: calc needs sources; a hint never confirms a fact -------------------------------------

import pytest

SUM_F1 = {"operation": "sum", "unit": "lines", "fact_ids": ["F1"]}


def test_compute_cannot_be_called_without_sources(tmp_path):
    run = job_posting_probe_run(tmp_path)
    with pytest.raises(TypeError):
        calc.compute(SUM_F1, store.read_facts(run))


def test_an_input_whose_source_record_is_missing_is_refused(tmp_path):
    run = make_run(tmp_path)
    add_source(run, TEXT, type="company_release")
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    facts = store.read_facts(run)
    assert calc.compute(SUM_F1, facts, store.read_sources(run)).value == "2"          # the same fact, with its source
    for sources in ({}, {"S9": {"type": "company_release"}}):
        result = calc.compute(SUM_F1, facts, sources)
        assert (result.value, result.problems) == (None, ["input F1 is not a settled capacity move"])
    facts["F1"]["source_id"] = ["S1"]                                                  # never raises on a bad id
    assert calc.compute(SUM_F1, facts, store.read_sources(run)).problems == ["input F1 is not a settled capacity move"]


def test_the_probe_is_refused_when_its_job_posting_source_is_passed(tmp_path):
    run = job_posting_probe_run(tmp_path)
    result = calc.compute(SUM_F1, store.read_facts(run), store.read_sources(run))
    assert (result.value, result.problems) == (None, ["input F1 is not a settled capacity move"])


def independence_run(tmp_path, *supporting_types):
    """F1: a capacity move from trade press (not a primary source), backed by one supporting source per type given."""
    run = make_run(tmp_path)
    add_source(run, TEXT, type="trade_press", publisher="Trade Paper")
    backing = {"job_posting": ("Careers: we are hiring operators for the new syringe lines opening in 2028.",
                               "hiring operators for the new syringe lines opening in 2028", "Careers Page"),
               "company_release": ("Competitor B confirmed that the two new syringe lines will open in 2028.",
                                   "two new syringe lines will open in 2028", "Competitor B")}
    supporting = []
    for number, source_type in enumerate(supporting_types, start=2):
        text, quote, publisher = backing[source_type]
        add_source(run, text, type=source_type, publisher=publisher)
        supporting.append({"source_id": f"S{number}", "quote": quote})
    add_fact(run, source_id="S1", primary_source=False, supporting=supporting,
             quote="adds two high-speed syringe lines for customers")
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    store.write_analysis(run, minimal_analysis(fact_ids=["F1"]))
    store.record_checkpoint(run, "lenses", "test", "ok"); store.record_checkpoint(run, "final_report", "test", "ok")
    return run


def state(run):
    fact = store.read_facts(run)["F1"]
    return fact["status"], fact["status_reason"]


def test_a_job_posting_never_confirms_a_fact_and_the_gate_refuses_a_hand_set_confirmed(tmp_path):
    run = independence_run(tmp_path, "job_posting")
    assert state(run) == ("uncertain", verify.NOT_PRIMARY_REASON)        # the same as with no second source at all
    assert gate(run) == []
    edit_fact(run, "F1", status="confirmed", status_reason=None)
    assert Problem("facts/F1.json", "status", "status does not follow from the checks") in gate(run)


def test_an_independent_company_release_still_confirms(tmp_path):
    run = independence_run(tmp_path, "company_release")
    assert state(run) == ("confirmed", None)
    assert gate(run) == []


def test_a_fact_with_both_kinds_of_supporting_source_is_confirmed_through_the_ordinary_one(tmp_path):
    run = independence_run(tmp_path, "job_posting", "company_release")
    assert state(run) == ("confirmed", None)
    assert gate(run) == []


def test_a_failing_quote_of_a_job_posting_supporting_source_still_rejects_the_fact(tmp_path):
    run = independence_run(tmp_path, "job_posting")
    fact = store.read_facts(run)["F1"]
    fact["supporting"][0]["quote"] = "a sentence that the job posting does not contain at all"
    store.write_fact(run, fact)
    verify.check_quotes(run); verify.settle(run)
    assert state(run) == ("rejected", "supporting_quote_not_found")


def test_a_baseline_names_a_repeated_fact_once(tmp_path):
    run = passing_run(tmp_path)
    analysis = minimal_analysis(fact_ids=["F1"])
    analysis["baselines"] = [{"company": "Competitor A", "fact_ids": ["F1", "F1"]}]
    store.write_analysis(run, analysis)
    assert gate(run) == []
    from radar.report.model import build_model
    from radar.demo import LENSES
    model = build_model(run, LENSES)
    assert [fact["id"] for fact in model["competitors"][0]["baseline"]] == ["F1"]


def test_the_gate_opens_for_a_source_record_without_final_url_and_for_one_with_it(tmp_path):
    run = passing_run(tmp_path)
    source = store.read_sources(run)["S1"]
    assert "final_url" not in source
    assert gate(run) == []
    store.write_source(run, {**source, "final_url": "https://other.example/page"})
    assert gate(run) == []
    store.write_source(run, {**source, "final_url": "ftp://other.example/page"})
    assert Problem("sources/S1.json", "final_url", "not an allowed value") in gate(run)


# --- Task 9: a fingerprint over the whole comparison file ---

def two_compared_runs(tmp_path):
    previous = passing_run(tmp_path / "prev")
    current = passing_run(tmp_path / "cur")
    compare(previous, current)
    return current


def test_a_comparison_as_the_program_wrote_it_passes(tmp_path, capsys):
    current = two_compared_runs(tmp_path)
    assert "file_digest" in store._read_json(current / "changes.json")
    assert gate(current) == []


def test_a_hand_edited_comparison_is_refused(tmp_path, capsys):
    current = two_compared_runs(tmp_path)
    changes = store._read_json(current / "changes.json")
    changes["unchanged"] = changes["unchanged"] + 5          # facts_digest is kept as it was
    store.write_changes(current, changes)
    assert "the comparison was changed after it was made" in messages(gate(current))
    assert gate(current) == [Problem("changes.json", None, "the comparison was changed after it was made")]


def test_a_comparison_with_a_wrong_digest_is_refused(tmp_path, capsys):
    current = two_compared_runs(tmp_path)
    changes = store._read_json(current / "changes.json")
    for wrong in ("0" * 64, None, 5, ""):
        store.write_changes(current, dict(changes, file_digest=wrong))
        assert gate(current) == [Problem("changes.json", None, "the comparison was changed after it was made")], wrong


def test_a_comparison_from_an_earlier_version_has_no_digest_and_is_refused(tmp_path, capsys):
    current = two_compared_runs(tmp_path)
    changes = store._read_json(current / "changes.json")
    del changes["file_digest"]
    store.write_changes(current, changes)
    assert gate(current) == [Problem("changes.json", None, "the comparison was changed after it was made")]
    compare(tmp_path / "prev" / "run1", current)             # the remedy named in the explanation
    assert gate(current) == []


# --- Part A fix A1, ruling HG1: the gate re-derives the public-run rule from changes.json --------------------

def _hand_placed_comparison(run, **values):
    """A changes.json as compare would write it for `run`, with `values` set and both digests made to match."""
    from radar import diff
    changes = {"previous_run": "r0", "current_run": "run1", "new": [], "changed": [], "source_changed": [],
               "source_unavailable": [], "not_found_again": [], "possible_matches": [], "predictions_due": [],
               "unchanged": 1, "previous_confidential": False, "previous_illustrative": False,
               "facts_digest": diff.facts_digest(store.read_facts(run))}
    changes.update(values)
    changes = {key: value for key, value in changes.items() if value is not _LEFT_OUT}
    changes["file_digest"] = diff.file_digest(changes)
    store.write_changes(run, changes)


_LEFT_OUT = object()   # a value for _hand_placed_comparison that leaves the key out, as an older file would


def test_a_public_run_with_a_hand_placed_confidential_comparison_is_refused(tmp_path):
    from radar.diff import PRIVATE_INTO_PUBLIC
    from radar.explain import explain
    run = passing_run(tmp_path)
    _hand_placed_comparison(run)
    assert gate(run) == []
    _hand_placed_comparison(run, previous_confidential=True)
    problems = gate(run)
    assert problems == [Problem("changes.json", "previous_confidential", PRIVATE_INTO_PUBLIC)]
    assert gate(run, publishable=True) == problems
    assert explain(problems[0])["known"] is True


def test_a_private_run_with_a_confidential_comparison_is_refused_only_for_publishing(tmp_path):
    private = passing_run(tmp_path, mode="private", acknowledged=True)
    _hand_placed_comparison(private, previous_confidential=True)
    assert gate(private) == []
    assert gate(private, publishable=True) == [Problem("run.json", "mode", "a publishable report may not be built from a private run"), Problem(
        "changes.json", "previous_confidential",
        "a publishable report may not compare against a run with non-public sources")]


# --- follow-up, ruling HG11: a comparison copied into another run is refused ---------------------------------

def test_a_comparison_of_two_invented_runs_copied_into_a_real_run_is_refused(tmp_path, capsys):
    from radar.diff import ILLUSTRATIVE_MIX
    from radar.explain import explain
    from radar.gate import COMPARISON_FOR_ANOTHER_RUN
    from radar.report.build import GateRefused, build_report
    from test_report_build import LENSES
    invented = []
    for name in ("earlier", "later"):   # two invented runs whose facts hold no capacity move
        run = make_run(tmp_path / name, run_id=f"invented-{name}", illustrative=True)
        add_source(run, TEXT)
        add_fact(run, source_id="S1", kind="general", fields=None, primary_source=True,
                 quote="adds two high-speed syringe lines for customers")
        verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
        invented.append(run)
    analysis = minimal_analysis(fact_ids=["F1"])
    analysis["predictions"] = [{"id": "P1", "message_id": "M1", "statement": "An invented line opens by 2026.",
                                "by": "2026-01-01", "resolves_when": "x", "probability": 50}]
    store.write_analysis(invented[0], analysis)
    compare(invented[0], invented[1])
    real = make_run(tmp_path / "real")                                  # run1: a real public run
    add_source(real, TEXT)
    add_fact(real, source_id="S1", kind="general", fields=None, primary_source=True,
             quote="adds two high-speed syringe lines for customers")
    verify.check_quotes(real); verify.record_support(real, "F1", True, "support-checker", ""); verify.settle(real)
    store.write_analysis(real, minimal_analysis(fact_ids=["F1"]))
    store.record_checkpoint(real, "lenses", "test", "ok"); store.record_checkpoint(real, "final_report", "test", "ok")
    assert gate(real) == []
    (real / "changes.json").write_bytes((invented[1] / "changes.json").read_bytes())   # copied by hand
    problems = gate(real)
    assert problems == [Problem("changes.json", "previous_illustrative", ILLUSTRATIVE_MIX),
                        Problem("changes.json", "current_run", COMPARISON_FOR_ANOTHER_RUN)]
    assert all(explain(problem)["known"] for problem in problems)
    try:
        build_report(real, LENSES)
        raise AssertionError("the report was built")
    except GateRefused:
        pass
    assert not (real / "report" / "report.md").exists()


def test_a_comparison_whose_kind_differs_from_the_run_is_refused_either_way(tmp_path):
    from radar.diff import ILLUSTRATIVE_MIX
    real = passing_run(tmp_path / "real")
    _hand_placed_comparison(real, previous_illustrative=True)
    assert gate(real) == [Problem("changes.json", "previous_illustrative", ILLUSTRATIVE_MIX)]
    invented = passing_run(tmp_path / "invented", illustrative=True)
    _hand_placed_comparison(invented)
    assert gate(invented) == [Problem("changes.json", "previous_illustrative", ILLUSTRATIVE_MIX)]
    _hand_placed_comparison(invented, previous_illustrative=True)
    assert gate(invented) == []


def test_a_comparison_made_for_another_run_is_refused(tmp_path):
    from radar.gate import COMPARISON_FOR_ANOTHER_RUN
    run = passing_run(tmp_path)
    _hand_placed_comparison(run, current_run="run2")
    assert gate(run) == [Problem("changes.json", "current_run", COMPARISON_FOR_ANOTHER_RUN)]


def test_a_comparison_from_an_earlier_version_without_the_kind_is_refused(tmp_path):
    from radar.explain import explain
    from radar.gate import COMPARISON_FROM_EARLIER_VERSION
    run = passing_run(tmp_path)
    _hand_placed_comparison(run, previous_illustrative=_LEFT_OUT)
    assert gate(run) == [Problem("changes.json", "previous_illustrative", COMPARISON_FROM_EARLIER_VERSION)]
    assert explain(gate(run)[0])["known"] is True
    for odd in ("yes", None, 1):
        _hand_placed_comparison(run, previous_illustrative=odd)
        assert gate(run) == [Problem("changes.json", "previous_illustrative", COMPARISON_FROM_EARLIER_VERSION)], odd
    compare(passing_run(tmp_path / "prev"), run)                          # the remedy: run the comparison again
    assert gate(run) == []

# --- fix wave A10: no version to publish is built from any private run ----------------------------------------------

PRIVATE_NOT_PUBLISHABLE = "a publishable report may not be built from a private run"


def test_a_private_run_that_holds_only_public_sources_is_refused_for_publishing(tmp_path, capsys):
    from radar.explain import explain
    from radar.report.build import build_report
    from test_report_build import LENSES
    run = passing_run(tmp_path, mode="private", acknowledged=True)
    assert all(source["data_class"] == "public" for source in store.read_sources(run).values())
    assert gate(run) == []
    assert gate(run, publishable=True) == [Problem("run.json", "mode", PRIVATE_NOT_PUBLISHABLE)]
    explained = explain(Problem("run.json", "mode", PRIVATE_NOT_PUBLISHABLE))
    assert explained["known"] is True and "public run" in explained["do"]
    code = main(["build-report", "--run", str(run), "--lenses", str(LENSES), "--publishable"])
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and out["built"] == [] and out["problems"] == [
        {"file": "run.json", "field": "mode", "message": PRIVATE_NOT_PUBLISHABLE}]
    assert list((run / "report").iterdir()) == []
    assert [p.name for p in build_report(run, LENSES)][:2] == ["report.md", "report.html"]   # without it: built


def test_a_public_run_is_still_publishable_and_a_broken_mode_is_not(tmp_path):
    run = passing_run(tmp_path)
    assert gate(run, publishable=True) == []
    store.save_run(run, dict(store.load_run(run), mode="secret"))
    assert Problem("run.json", "mode", PRIVATE_NOT_PUBLISHABLE) in gate(run, publishable=True)


# --- fix wave A11: one quote check for settle and the gate ----------------------------------------------------------

@pytest.mark.parametrize("quote", [42, ["adds two high-speed syringe lines"], {"text": "x"}, True, None, ""])
def test_a_quote_settle_and_the_gate_judge_alike_whatever_was_written_by_hand(tmp_path, quote):
    run = passing_run(tmp_path)
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    edit_fact(run, "F2", quote=quote)
    verify.settle(run)
    fact = store.read_facts(run)["F2"]
    assert fact["status"] == "rejected"
    expected = "quote_too_short" if quote in (None, "") else "not_found"
    assert fact["status_reason"] == expected and fact["checks"]["quote"]["reason"] == expected
    gate_says = [(p.file, p.message) for p in gate(run) if p.file == "facts/F2.json"]
    assert ("facts/F2.json", "reason does not follow from the checks") not in gate_says
    assert ("facts/F2.json", "status does not follow from the checks") not in gate_says


def test_the_gate_and_settle_share_one_quote_check():
    import radar.gate as gate_module
    assert gate_module.check_quote is verify.check_quote
    for quote, text, reason in ((42, "anything", "not_found"), (None, "x", "quote_too_short"),
                                ("", "x", "quote_too_short"), ("adds two lines", None, "no_saved_copy"),
                                ([1], "x", "not_found")):
        assert verify.check_quote(quote, text) == {"passed": False, "mode": None, "reason": reason}


# --- fix wave A17: a fact named in a text of the analysis must count ------------------------------------------------

def _texts_naming(run, where_and_text):
    analysis = store.read_analysis(run)
    for path, text in where_and_text:
        target = analysis
        for step in path[:-1]:
            target = target[step]
        target[path[-1]] = text
    store.write_analysis(run, analysis)
    return [p for p in gate(run) if p.message.startswith("a text names fact")]


def test_a_text_that_names_a_rejected_missing_or_unsettled_fact_is_refused(tmp_path):
    run = passing_run(tmp_path)
    add_rejected_fact(run)                                                         # F2, rejected
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")  # F3
    found = _texts_naming(run, [
        (["messages", 0, "text"], "As F2 shows, Competitor A is adding capacity."),
        (["messages", 0, "chain", 1, "text"], "F9 and F3 say the same."),
        (["not_found"], ["No source names the price; F2 tried to."]),
    ])
    assert found == [
        Problem("analysis.json", "messages[0].text", "a text names fact F2 with status rejected"),
        Problem("analysis.json", "messages[0].chain[1].text", "a text names fact F9 with status missing"),
        Problem("analysis.json", "messages[0].chain[1].text", "a text names fact F3 with status proposed"),
        Problem("analysis.json", "not_found[0]", "a text names fact F2 with status rejected"),
    ]


def test_a_text_that_names_a_withdrawn_fact_is_refused_also_before_it_is_settled_again(tmp_path):
    run = passing_run(tmp_path)
    found = _texts_naming(run, [(["messages", 0, "counter_view"], "F1 may be delayed.")])
    assert found == []                                                            # F1 counts
    verify.withdraw_fact(run, "F1", "Duplicate.")
    assert Problem("analysis.json", "messages[0].counter_view", "a text names fact F1 with status withdrawn") \
        in gate(run)


def test_only_a_fact_id_standing_on_its_own_is_read_and_the_id_lists_are_left_to_their_own_rule(tmp_path):
    run = passing_run(tmp_path)
    found = _texts_naming(run, [
        (["messages", 0, "text"], "The F2X line, form XF2 and F2a are no fact ids; neither is F."),
        (["messages", 0, "would_change"], "A notice that cites F1, or (F1)."),
    ])
    assert found == []
    assert gate(run) == []


def test_every_text_naming_an_unusable_fact_has_its_explanation():
    from radar.explain import explain
    for status in ("rejected", "proposed", "missing", "withdrawn", "uncertain-ish"):
        explained = explain(Problem("analysis.json", "messages[0].text", f"a text names fact F7 with status {status}"))
        assert explained["known"] is True and "F7" in explained["what"], status


def test_the_demo_s_analysis_names_no_fact_in_its_texts_that_does_not_count(tmp_path):
    from radar.demo import LENSES as DEMO_LENSES, build_demo_run
    for variant in ({}, {"private": True}, {"changed": True}):
        run = build_demo_run(tmp_path / str(len(variant)) / "x" if variant else tmp_path / "base", **variant)
        assert [p for p in gate(run, DEMO_LENSES) if p.message.startswith("a text names fact")] == []


# --- ruling FWA-4: a flag of the bias audit may name any fact that exists ----------------------------------------------

def _with_flag(run, text):
    analysis = store.read_analysis(run)
    analysis["audit_flags"] = [{"check": "independence", "text": text}]
    store.write_analysis(run, analysis)


def test_a_flag_may_name_a_fact_that_does_not_count_while_the_analysis_s_own_texts_may_not(tmp_path):
    """A flag points at what the analysis leans on, a rejected fact too ("M1 leans on F2."); the lead may not change a
    flag, so the gate must not close on it at the build."""
    run = passing_run(tmp_path)
    add_rejected_fact(run)                                                         # F2, rejected
    _with_flag(run, "M1 leans on F2, which was rejected, and on F1.")
    assert gate(run) == []
    found = _texts_naming(run, [(["messages", 0, "text"], "As F2 shows, it is so.")])
    assert found == [Problem("analysis.json", "messages[0].text", "a text names fact F2 with status rejected")]


def test_a_flag_that_names_a_fact_this_run_does_not_have_is_named_by_the_data_check(tmp_path):
    """At step 8 the gate is still closed (no final decision), so the data check must report it there."""
    from radar.explain import explain
    from radar.schema import check_data
    run = passing_run(tmp_path)
    _with_flag(run, "M1 leans on F99 and on F1.")
    flagged = Problem("analysis.json", "audit_flags[0].text", "a flag names fact F99, which does not exist")
    assert check_data(run) == [flagged]
    assert [p for p in gate(run) if "F99" in p.message] == [flagged]             # once, not also as a text
    explained = explain(flagged)
    assert explained["known"] is True and "F99" in explained["what"] and "flag" in explained["what"]
    assert "again" in explained["do"]


def test_only_the_flags_themselves_are_left_to_the_data_check(tmp_path):
    """Ruling FWB-3.5: a key that merely begins like the flags (written by hand) is judged like any other text."""
    run = passing_run(tmp_path)
    add_rejected_fact(run)                                                         # F2, rejected
    analysis = store.read_analysis(run)
    analysis["audit_flagsX"] = [{"text": "As F2 shows, it is so."}]
    store.write_analysis(run, analysis)
    assert Problem("analysis.json", "audit_flagsX[0].text", "a text names fact F2 with status rejected") in gate(run)


# --- ruling FWA-5a: an unknown key is explained for a fact and for a flag alike -----------------------------------------

def test_an_unknown_key_in_a_flag_has_its_own_message_and_explanation(tmp_path):
    """A flag was copied from the auditor, not changed outside the program, so the fact's advice does not fit it."""
    from radar.explain import explain
    from radar.schema import check_data
    run = passing_run(tmp_path)
    analysis = store.read_analysis(run)
    analysis["audit_flags"] = [{"check": "independence", "text": "M1 leans on F1.", "severity": "high"}]
    store.write_analysis(run, analysis)
    problem = Problem("analysis.json", "audit_flags[0].severity", "the key severity is not known in a flag")
    assert check_data(run) == [problem]
    explained = explain(problem)
    assert explained["known"] is True and explained["what"].startswith("A flag of the look for bias holds"), explained
    assert "severity" in explained["what"] and "again" in explained["do"], explained
    fact = explain(Problem("facts/F1.json", "note", "the key note is not known"))
    assert fact["what"].startswith("A fact holds") and fact["do"].startswith("This fact was changed outside")
