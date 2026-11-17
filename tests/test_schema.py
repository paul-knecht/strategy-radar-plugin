import json
from pathlib import Path

from radar.schema import check_data, Problem
from radar import store
from radar.cli import main
from helpers import lens_folder_with_level, make_run, add_source, add_fact, minimal_analysis, unreadable_file


def clean_run(tmp_path):
    run = make_run(tmp_path)
    src = add_source(run, "The expansion adds two high-speed syringe lines for customers in 2028.")
    add_fact(run, source_id=src["id"], quote="adds two high-speed syringe lines for customers")
    return run


def test_non_public_source_in_public_run_is_a_problem(tmp_path):
    run = clean_run(tmp_path)
    src = store.read_sources(run)["S1"]; src["data_class"] = "internal"; store.write_source(run, src)
    assert Problem("sources/S1.json", "data_class", "non-public source in a public run") in check_data(run)


def test_non_public_source_needs_provenance(tmp_path):
    run = make_run(tmp_path, mode="private", acknowledged=True)
    add_source(run, "Internal capacity review. " * 20, data_class="internal", provenance=None)
    assert Problem("sources/S1.json", "provenance", "provenance is required for non-public sources") in check_data(run)


def test_based_on_must_exist_and_not_loop(tmp_path):
    run = clean_run(tmp_path)
    add_source(run, "A trade article written from the press release, with enough words to count.", based_on=["S1"])
    s1 = store.read_sources(run)["S1"]; s1["based_on"] = ["S2"]; store.write_source(run, s1)
    assert Problem("sources/S1.json", "based_on", "based_on must not form a loop") in check_data(run)
    s1["based_on"] = ["S8"]; store.write_source(run, s1)
    assert Problem("sources/S1.json", "based_on", "source S8 does not exist") in check_data(run)


def test_clean_run_has_no_problems(tmp_path):
    assert check_data(clean_run(tmp_path)) == []


def test_invalid_json_is_a_problem_not_a_crash(tmp_path):
    run = clean_run(tmp_path)
    (run / "facts" / "F1.json").write_text("{not json", encoding="utf-8")
    (run / "sources" / "S9.json").write_text("", encoding="utf-8")
    problems = check_data(run)
    assert Problem("facts/F1.json", None, "not valid JSON") in problems
    assert Problem("sources/S9.json", None, "not valid JSON") in problems


def test_missing_field_names_file_and_field(tmp_path):
    run = clean_run(tmp_path)
    fact = store.read_facts(run)["F1"]; fact["statement"] = ""
    store.write_fact(run, fact)
    assert Problem("facts/F1.json", "statement", "must not be empty") in check_data(run)


def test_fact_pointing_to_missing_source(tmp_path):
    run = clean_run(tmp_path)
    fact = store.read_facts(run)["F1"]; fact["source_id"] = "S7"
    store.write_fact(run, fact)
    assert Problem("facts/F1.json", "source_id", "source S7 does not exist") in check_data(run)


def test_changed_copy_is_detected(tmp_path):
    run = clean_run(tmp_path)
    (run / "copies" / "S1.txt").write_text("edited afterwards", encoding="utf-8")
    assert Problem("sources/S1.json", "copy_sha256", "saved copy has changed") in check_data(run)


def test_tentative_needs_reason_and_german_needs_translation(tmp_path):
    run = clean_run(tmp_path)
    fact = store.read_facts(run)["F1"]
    fact.update(certainty="tentative", tentative_reason=None, quote_language="de", quote_translation=None)
    store.write_fact(run, fact)
    fields = {p.field for p in check_data(run)}
    assert {"tentative_reason", "quote_translation"} <= fields


def test_analysis_must_reference_existing_facts(tmp_path):
    run = clean_run(tmp_path)
    analysis = minimal_analysis(fact_ids=["F1"])
    analysis["messages"][0]["chain"][0]["fact_ids"] = ["F1", "F99"]
    store.write_analysis(run, analysis)
    assert Problem("analysis.json", "messages[0].chain[0].fact_ids", "fact F99 does not exist") in check_data(run)


# --- beyond the brief's list: run.json, broken files, fact and source rules, analysis, lenses, CLI ---

def edit_fact(run, **changes):
    """Change F1 and write it back to facts/F1.json, even when the change alters its id."""
    fact = store.read_facts(run)["F1"]
    fact.update(changes)
    (run / "facts" / "F1.json").write_text(json.dumps(fact), encoding="utf-8")


def edit_source(run, **changes):
    """Change S1 and write it back to sources/S1.json, even when the change alters its id."""
    source = store.read_sources(run)["S1"]
    source.update(changes)
    (run / "sources" / "S1.json").write_text(json.dumps(source), encoding="utf-8")


def test_unset_proposal_fields_are_flagged(tmp_path):
    run = clean_run(tmp_path)
    edit_fact(run, certainty=None, primary_source=None, quote_language=None)
    problems = check_data(run)
    assert Problem("facts/F1.json", "certainty", "not an allowed value") in problems
    assert Problem("facts/F1.json", "primary_source", "not an allowed value") in problems
    assert Problem("facts/F1.json", "quote_language", "must not be empty") in problems
    assert not any(p.field == "quote_translation" for p in problems)


def test_run_json_missing_empty_or_broken_is_one_problem(tmp_path):
    run = clean_run(tmp_path)
    (run / "run.json").write_text("", encoding="utf-8")
    assert [p for p in check_data(run) if p.file == "run.json"] == [Problem("run.json", None, "not valid JSON")]
    (run / "run.json").unlink()
    assert [p for p in check_data(run) if p.file == "run.json"] == [Problem("run.json", None, "run.json is missing")]


def test_a_run_record_this_user_may_not_open_is_named_as_such(tmp_path):
    # Not damaged: it only lacks the right to be read. The fix is to allow reading it, not to restore it.
    run = clean_run(tmp_path)
    with unreadable_file(run / "run.json"):
        assert [p for p in check_data(run) if p.file == "run.json"] == [Problem("run.json", None, "run.json may not be opened")]
    assert [p for p in check_data(run) if p.file == "run.json"] == []        # readable again: no problem
    (run / "run.json").write_text("{not json", encoding="utf-8")             # readable and not JSON: as before
    assert [p for p in check_data(run) if p.file == "run.json"] == [Problem("run.json", None, "not valid JSON")]
    (run / "run.json").unlink()
    (run / "run.json").mkdir()                                               # a folder of that name: as before
    assert [p for p in check_data(run) if p.file == "run.json"] == [Problem("run.json", None, "not valid JSON")]


def test_the_explanation_of_a_run_record_this_user_may_not_open_says_how_to_allow_it():
    from radar.explain import explain
    told = explain(Problem("run.json", None, "run.json may not be opened"))
    assert told["known"] is True
    assert "may not open" in told["what"] and "basic details" in told["what"]
    assert "who may read" in told["why"]
    assert told["do"].startswith("Allow your user account to read") and "backup" not in told["do"]
    assert explain(Problem("run.json", None, "not valid JSON"))["what"] == "A saved item of this run cannot be read."


def test_non_object_json_is_not_valid(tmp_path):
    run = clean_run(tmp_path)
    (run / "facts" / "F1.json").write_text("[1, 2]", encoding="utf-8")
    (run / "analysis.json").write_text("null", encoding="utf-8")
    problems = check_data(run)
    assert Problem("facts/F1.json", None, "not valid JSON") in problems
    assert Problem("analysis.json", None, "not valid JSON") in problems


def test_deeply_nested_and_binary_files_do_not_crash(tmp_path):
    run = clean_run(tmp_path)
    (run / "facts" / "F1.json").write_text("[" * 100000, encoding="utf-8")
    (run / "sources" / "S1.json").write_bytes(b"\xff\xfe\x00\x80")
    problems = check_data(run)
    assert Problem("facts/F1.json", None, "not valid JSON") in problems
    assert Problem("sources/S1.json", None, "not valid JSON") in problems


def test_run_json_rules(tmp_path):
    run = clean_run(tmp_path)
    data = store.load_run(run)
    data.update(question="", pack=None, run_id=" ", language="de", mode="secret",
                checkpoints=[{"name": "nope", "answered_by": "robot"}])
    store.save_run(run, data)
    problems = check_data(run)
    for field, message in [("question", "must not be empty"), ("pack", "must not be empty"),
                           ("run_id", "must not be empty"), ("language", "not an allowed value"),
                           ("mode", "not an allowed value"),
                           ("checkpoints[0].name", "not an allowed value"),
                           ("checkpoints[0].answered_by", "not an allowed value")]:
        assert Problem("run.json", field, message) in problems


def test_private_run_needs_acknowledgement_time(tmp_path):
    run = make_run(tmp_path, mode="private", acknowledged=True)
    data = store.load_run(run); data["private_acknowledged_at"] = None; store.save_run(run, data)
    assert check_data(run) == [Problem("run.json", "private_acknowledged_at", "must not be empty")]


def test_private_run_with_provenance_is_clean(tmp_path):
    run = make_run(tmp_path, mode="private", acknowledged=True)
    add_source(run, "Internal capacity review. " * 20, data_class="internal")
    assert check_data(run) == []


def test_based_on_self_reference_is_a_loop(tmp_path):
    run = clean_run(tmp_path)
    edit_source(run, based_on=["S1"])
    assert Problem("sources/S1.json", "based_on", "based_on must not form a loop") in check_data(run)


def test_source_file_name_and_required_fields(tmp_path):
    run = clean_run(tmp_path)
    edit_source(run, id="S4", url="", type="blog", saved_by="robot", date=None)
    problems = check_data(run)
    for field, message in [("id", "file name does not match id"), ("url", "must not be empty"),
                           ("date", "must not be empty"), ("type", "not an allowed value"),
                           ("saved_by", "not an allowed value")]:
        assert Problem("sources/S1.json", field, message) in problems


def test_missing_copy_and_copy_outside_run_folder(tmp_path):
    run = clean_run(tmp_path)
    (run / "copies" / "S1.txt").unlink()
    assert Problem("sources/S1.json", "copy_file", "saved copy is missing") in check_data(run)
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    edit_source(run, copy_file="../../outside.txt")
    assert Problem("sources/S1.json", "copy_file", "not an allowed value") in check_data(run)


def test_not_accessible_source_needs_a_reason_and_no_copy(tmp_path):
    run = clean_run(tmp_path)
    edit_source(run, access="not_accessible", access_reason=None, copy_file=None, copy_sha256=None)
    assert check_data(run) == [Problem("sources/S1.json", "access_reason", "must not be empty")]
    edit_source(run, access="not_accessible", access_reason="HTTP 403")
    assert check_data(run) == []
    edit_source(run, access="maybe")
    assert Problem("sources/S1.json", "access", "not an allowed value") in check_data(run)


def test_fact_rules(tmp_path):
    run = clean_run(tmp_path)
    edit_fact(run, id="F3", kind="rumour", status="maybe", certainty="sure", status_reason=None,
              supporting=[{"source_id": "S6", "quote": "x"}])
    problems = check_data(run)
    for field, message in [("id", "file name does not match id"), ("kind", "not an allowed value"),
                           ("status", "not an allowed value"), ("certainty", "not an allowed value"),
                           ("supporting[0].source_id", "source S6 does not exist")]:
        assert Problem("facts/F1.json", field, message) in problems


def test_uncertain_and_rejected_need_a_reason(tmp_path):
    run = clean_run(tmp_path)
    for status in ("uncertain", "rejected"):
        edit_fact(run, status=status, status_reason=None)
        assert Problem("facts/F1.json", "status_reason", "must not be empty") in check_data(run)
        edit_fact(run, status=status, status_reason="two sources disagree")
        assert check_data(run) == []


def test_quote_length_is_five_to_fifty_words(tmp_path):
    run = clean_run(tmp_path)
    message = "quote must have 5 to 50 words"
    edit_fact(run, quote="four words only here")
    assert Problem("facts/F1.json", "quote", message) in check_data(run)
    edit_fact(run, quote="word " * 51)
    assert Problem("facts/F1.json", "quote", message) in check_data(run)
    edit_fact(run, quote="word " * 50)
    assert Problem("facts/F1.json", "quote", message) not in check_data(run)
    edit_fact(run, quote="word " * 5)
    assert Problem("facts/F1.json", "quote", message) not in check_data(run)


def test_chinese_quote_counts_two_characters_as_one_word(tmp_path):
    run = clean_run(tmp_path)
    edit_fact(run, quote="公司将在二零二八年扩建工厂", quote_language="zh", quote_translation="The company will expand")
    assert check_data(run) == []


def test_capacity_move_fields_are_checked(tmp_path):
    run = clean_run(tmp_path)
    fact = store.read_facts(run)["F1"]
    fact["fields"].update(company="", what_added=None, announced="", move_type="x", stage="y", access="z",
                          delivery="soon")
    store.write_fact(run, fact)
    problems = check_data(run)
    for field, message in [("fields.company", "must not be empty"), ("fields.what_added", "must not be empty"),
                           ("fields.announced", "must not be empty"),
                           ("fields.move_type", "not an allowed value"), ("fields.stage", "not an allowed value"),
                           ("fields.access", "not an allowed value"),
                           ("fields.delivery", "not an allowed value")]:
        assert Problem("facts/F1.json", field, message) in problems
    fact["fields"].update(company="A", what_added="x", announced="2026", move_type="expansion",
                          stage="announced", access="open", delivery=None)
    store.write_fact(run, fact)
    assert check_data(run) == []


def test_capacity_move_without_fields_and_general_with_fields(tmp_path):
    run = clean_run(tmp_path)
    edit_fact(run, fields=None)
    assert Problem("facts/F1.json", "fields", "must not be empty") in check_data(run)
    edit_fact(run, kind="general", fields={"company": "A"})
    assert Problem("facts/F1.json", "fields", "not an allowed value") in check_data(run)
    edit_fact(run, kind="general", fields=None)
    assert check_data(run) == []


def test_analysis_with_no_messages_is_fine_but_broken_json_is_not(tmp_path):
    run = clean_run(tmp_path)
    analysis = minimal_analysis(["F1"]); analysis["messages"] = []
    store.write_analysis(run, analysis)
    assert check_data(run) == []
    (run / "analysis.json").write_text("{", encoding="utf-8")
    assert Problem("analysis.json", None, "not valid JSON") in check_data(run)


def test_message_fields_and_chain_shape(tmp_path):
    run = clean_run(tmp_path)
    analysis = minimal_analysis(["F1"])
    message = analysis["messages"][0]
    message.update(text="", counter_view=None, would_change="", confidence="certain")
    message["chain"] = [{"kind": "reasoning", "text": "x", "fact_ids": [], "lens_id": None},
                        {"kind": "conclusion", "text": "a", "fact_ids": [], "lens_id": None},
                        {"kind": "conclusion", "text": "b", "fact_ids": [], "lens_id": None}]
    store.write_analysis(run, analysis)
    problems = check_data(run)
    for field, text in [("messages[0].text", "must not be empty"),
                        ("messages[0].counter_view", "must not be empty"),
                        ("messages[0].would_change", "must not be empty"),
                        ("messages[0].confidence", "not an allowed value"),
                        ("messages[0].chain", "chain must have at least one fact step"),
                        ("messages[0].chain", "chain must have exactly one conclusion step")]:
        assert Problem("analysis.json", field, text) in problems


def test_fact_ids_are_checked_everywhere_in_analysis(tmp_path):
    run = clean_run(tmp_path)
    analysis = minimal_analysis(["F1"])
    analysis["demand_signals"] = [{"text": "t", "fact_ids": ["F40"]}]
    analysis["decision_options"]["framing_fact_ids"] = ["F41"]
    analysis["decision_options"]["options"] = [{"name": "n", "for": [{"text": "t", "fact_ids": ["F42"]}],
                                                "against": []}]
    analysis["messages"][0]["outside_view"]["fact_ids"] = ["F43"]
    store.write_analysis(run, analysis)
    problems = check_data(run)
    for field, fid in [("demand_signals[0].fact_ids", "F40"), ("decision_options.framing_fact_ids", "F41"),
                       ("decision_options.options[0].for[0].fact_ids", "F42"),
                       ("messages[0].outside_view.fact_ids", "F43")]:
        assert Problem("analysis.json", field, f"fact {fid} does not exist") in problems


def test_decision_framing_must_be_allowed(tmp_path):
    run = clean_run(tmp_path)
    analysis = minimal_analysis(["F1"]); analysis["decision_options"]["framing"] = "boss"
    store.write_analysis(run, analysis)
    assert Problem("analysis.json", "decision_options.framing", "not an allowed value") in check_data(run)


def write_lens(lenses, lens_id, questions=("a", "b", "c"), levels=("original_read",)):
    """A lens that the lens check passes, unless `questions` or `levels` are changed."""
    lenses.mkdir(exist_ok=True)
    (lenses / f"{lens_id}.json").write_text(json.dumps({
        "id": lens_id, "name": "n", "idea": "i", "suggests": "s", "limits": "l", "competing_idea": "c",
        "questions": list(questions),
        "originals": [{"reference": "r", "level": level, "link": None} for level in levels]}), encoding="utf-8")


def test_lenses_are_only_checked_when_a_lens_dir_is_given(tmp_path):
    run = clean_run(tmp_path)
    analysis = minimal_analysis(["F1"], lens_id="firm-boundaries")
    analysis["lens_notes"] = [{"lens_id": "other", "here": "x"}]
    store.write_analysis(run, analysis)
    assert check_data(run) == []
    lenses = tmp_path / "lenses"; lenses.mkdir()
    problems = check_data(run, lenses)
    assert Problem("analysis.json", "messages[0].chain[1].lens_id", "lens firm-boundaries does not exist") in problems
    assert Problem("analysis.json", "lens_notes[0].lens_id", "lens other does not exist") in problems


def test_lens_files_are_checked(tmp_path):
    run = clean_run(tmp_path)
    analysis = minimal_analysis(["F1"], lens_id="good")
    analysis["lens_notes"] = [{"lens_id": "bad", "here": "x"}, {"lens_id": "broken", "here": "x"},
                              {"lens_id": "../escape", "here": "x"}]
    store.write_analysis(run, analysis)
    lenses = tmp_path / "lenses"
    write_lens(lenses, "good")
    write_lens(lenses, "bad", questions=("a", "b"), levels=("original_read", "hearsay"))
    (lenses / "broken.json").write_text("{", encoding="utf-8")
    problems = check_data(run, lenses)
    assert not any(p.file == "lenses/good.json" for p in problems)
    assert Problem("lenses/bad.json", "questions", "lens must have exactly 3 questions") in problems
    assert Problem("lenses/bad.json", "originals[1].level",
                   "a lens level must be original_read, course_slides, secondary_source_read or reference_confirmed") in problems
    assert Problem("lenses/broken.json", None, "a lens cannot be read") in problems
    assert Problem("analysis.json", "lens_notes[2].lens_id", "lens ../escape does not exist") in problems


def test_a_lens_that_rests_on_course_slides_passes_the_lens_check(tmp_path):
    run = clean_run(tmp_path)
    store.write_analysis(run, minimal_analysis(["F1"], lens_id="firm-boundaries"))
    lenses = lens_folder_with_level(tmp_path / "lenses", "course_slides")
    assert check_data(run, lenses) == []


def test_empty_lens_note_id_is_a_problem(tmp_path):
    run = clean_run(tmp_path)
    analysis = minimal_analysis(["F1"]); analysis["lens_notes"] = [{"lens_id": None, "here": "x"}]
    store.write_analysis(run, analysis)
    assert Problem("analysis.json", "lens_notes[0].lens_id", "must not be empty") in check_data(run)


def test_problems_come_in_a_stable_order(tmp_path):
    run = clean_run(tmp_path)
    for i in (10, 2):
        (run / "sources" / f"S{i}.json").write_text("", encoding="utf-8")
        (run / "facts" / f"F{i}.json").write_text("", encoding="utf-8")
    store.write_analysis(run, {"messages": "x"})
    data = store.load_run(run); data["question"] = ""; store.save_run(run, data)
    files = list(dict.fromkeys(p.file for p in check_data(run)))
    assert files == ["run.json", "sources/S2.json", "sources/S10.json", "facts/F2.json", "facts/F10.json",
                     "analysis.json"]


def run_cli(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    return code, json.loads(out)


def test_cli_check_data_clean_and_broken(tmp_path, capsys):
    run = clean_run(tmp_path)
    assert run_cli(capsys, "check-data", "--run", str(run)) == (0, {"problems": [], "explained": []})
    edit_fact(run, statement="")
    code, out = run_cli(capsys, "check-data", "--run", str(run))
    assert code == 1
    assert out["problems"] == [{"file": "facts/F1.json", "field": "statement", "message": "must not be empty"}]


def test_cli_check_data_with_lenses(tmp_path, capsys):
    run = clean_run(tmp_path)
    store.write_analysis(run, minimal_analysis(["F1"], lens_id="nope"))
    lenses = tmp_path / "lenses"; lenses.mkdir()
    assert run_cli(capsys, "check-data", "--run", str(run))[0] == 0
    code, out = run_cli(capsys, "check-data", "--run", str(run), "--lenses", str(lenses))
    assert code == 1 and out["problems"][0]["message"] == "lens nope does not exist"



# --- final fix I3: a rejected fact no longer blocks, a deleted record is noticed --------------------

def test_quote_length_is_not_checked_for_a_rejected_fact(tmp_path):
    run = clean_run(tmp_path)
    edit_fact(run, quote="two syringe lines", status="rejected", status_reason="quote_too_short")
    assert check_data(run) == []
    edit_fact(run, status="proposed", status_reason=None)
    assert Problem("facts/F1.json", "quote", "quote must have 5 to 50 words") in check_data(run)


def test_a_deleted_fact_or_source_file_is_reported(tmp_path):
    run = clean_run(tmp_path)
    add_fact(run, source_id="S1", quote="adds two high-speed syringe lines for customers")
    add_source(run, "A second source with enough words to be a source.")
    (run / "facts" / "F1.json").unlink()
    (run / "sources" / "S2.json").unlink()
    problems = check_data(run)
    assert Problem("run.json", "facts_created", "fact F1 is missing") in problems
    assert Problem("run.json", "sources_created", "source S2 is missing") in problems


def test_a_run_without_counters_is_not_checked_for_gaps(tmp_path):
    run = clean_run(tmp_path)
    data = store.load_run(run); del data["facts_created"]; del data["sources_created"]; store.save_run(run, data)
    (run / "facts" / "F1.json").unlink()
    assert check_data(run) == []


def test_a_counter_that_is_not_a_count_is_named(tmp_path):
    run = clean_run(tmp_path)
    for value in ("3", -1, True, 10 ** 12):
        data = store.load_run(run); data["facts_created"] = value; store.save_run(run, data)
        assert Problem("run.json", "facts_created", "not an allowed value") in check_data(run), value


def test_a_withdrawal_needs_a_reason(tmp_path):
    run = clean_run(tmp_path)
    edit_fact(run, withdrawn={"reason": " ", "at": "2026-11-12T10:15:00Z"})
    assert Problem("facts/F1.json", "withdrawn.reason", "must not be empty") in check_data(run)
    edit_fact(run, withdrawn="yes")
    assert Problem("facts/F1.json", "withdrawn", "not an allowed value") in check_data(run)
    edit_fact(run, withdrawn=None)
    assert check_data(run) == []



# --- final fix I4: analysis sections of the wrong shape are named, never a crash ------------------

import pytest
from radar.report.build import GateRefused, build_report
from radar.schema_analysis import MUST_BE_LIST, MUST_BE_OBJECT, MUST_BE_TEXT

from radar.demo import LENSES


def _set(path, value):
    """A change to the minimal analysis: set the value at `path` (keys and list positions)."""
    def change(analysis):
        target = analysis
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return change


def _step(kind, text="t"):
    return {"kind": kind, "text": text, "fact_ids": ["F1"] if kind == "fact" else [], "lens_id": None}


WRONG_SHAPES = [
    (_set(["demand_signals"], ["Orders rise"]), "demand_signals[0]", MUST_BE_OBJECT),
    (_set(["demand_signals"], "Orders rise"), "demand_signals", MUST_BE_LIST),
    (_set(["watch_items"], ["Watch Plant North"]), "watch_items[0]", MUST_BE_OBJECT),
    (_set(["watch_items"], [{"text": ["x"], "trigger": "t"}]), "watch_items[0].text", MUST_BE_TEXT),
    (_set(["audit_flags"], ["a flag"]), "audit_flags[0]", MUST_BE_OBJECT),
    (_set(["audit_flags"], [{"check": "framing", "text": {"a": 1}}]), "audit_flags[0].text", MUST_BE_TEXT),
    (_set(["contradictions"], "two facts disagree"), "contradictions", MUST_BE_LIST),
    (_set(["contradictions"], ["two facts disagree"]), "contradictions[0]", MUST_BE_OBJECT),
    (_set(["not_found"], "nothing on prices"), "not_found", MUST_BE_LIST),
    (_set(["not_found"], [["nested"]]), "not_found[0]", MUST_BE_TEXT),
    (_set(["lens_notes"], ["firm-boundaries"]), "lens_notes[0]", MUST_BE_OBJECT),
    (_set(["lens_notes"], [{"lens_id": "firm-boundaries", "here": ["x"]}]), "lens_notes[0].here", MUST_BE_TEXT),
    (_set(["decision_options"], ["Build"]), "decision_options", MUST_BE_OBJECT),
    (_set(["decision_options", "options"], ["Build"]), "decision_options.options[0]", MUST_BE_OBJECT),
    (_set(["decision_options", "options"], "Build"), "decision_options.options", MUST_BE_LIST),
    (_set(["decision_options", "options"], [{"name": ["Build"], "for": [], "against": []}]),
     "decision_options.options[0].name", MUST_BE_TEXT),
    (_set(["decision_options", "options"], [{"name": "Build", "for": "cheaper", "against": []}]),
     "decision_options.options[0].for", MUST_BE_LIST),
    (_set(["decision_options", "options"], [{"name": "Build", "for": ["cheaper"], "against": []}]),
     "decision_options.options[0].for[0]", MUST_BE_OBJECT),
    (_set(["decision_options", "options"], [{"name": "Build", "for": [], "against": [{"text": 3, "fact_ids": []}]}]),
     "decision_options.options[0].against[0].text", MUST_BE_TEXT),
    (_set(["decision_options", "internal_questions"], "Why now?"), "decision_options.internal_questions", MUST_BE_LIST),
    (_set(["decision_options", "internal_questions"], [{"q": 1}]), "decision_options.internal_questions[0]", MUST_BE_TEXT),
    (_set(["decision_options", "question"], ["What now?"]), "decision_options.question", MUST_BE_TEXT),
    (_set(["messages", 0, "chain"], "first this, then that"), "messages[0].chain", MUST_BE_LIST),
    (_set(["messages", 0, "chain"], ["a step", _step("fact"), _step("conclusion")]), "messages[0].chain[0]", MUST_BE_OBJECT),
    (_set(["messages", 0, "chain"], [_step("fact", text=["x"]), _step("conclusion")]), "messages[0].chain[0].text", MUST_BE_TEXT),
    (_set(["messages", 0, "chain"], [_step("fact"), _step("aside"), _step("conclusion")]), "messages[0].chain[1].kind",
     "not an allowed value"),
    (_set(["messages", 0, "outside_view"], "Expansions often slip."), "messages[0].outside_view", MUST_BE_OBJECT),
    (_set(["messages", 0, "outside_view"], {"text": 7, "fact_ids": []}), "messages[0].outside_view.text", MUST_BE_TEXT),
    (_set(["messages", 0, "id"], ""), "messages[0].id", "must not be empty"),
]


@pytest.mark.parametrize("change, field, message", WRONG_SHAPES, ids=[case[1] + " " + case[2] for case in WRONG_SHAPES])
def test_a_wrong_shape_is_a_named_problem_and_never_a_crash(tmp_path, change, field, message):
    run = clean_run(tmp_path)
    from radar import verify
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    for name in store.CHECKPOINTS:
        store.record_checkpoint(run, name, "test", "ok")
    analysis = minimal_analysis(["F1"])
    change(analysis)
    store.write_analysis(run, analysis)
    assert Problem("analysis.json", field, message) in check_data(run, LENSES)
    with pytest.raises(GateRefused):
        build_report(run, LENSES)


def test_message_ids_must_be_unique(tmp_path):
    run = clean_run(tmp_path)
    analysis = minimal_analysis(["F1"])
    analysis["messages"].append(dict(analysis["messages"][0]))
    store.write_analysis(run, analysis)
    assert Problem("analysis.json", "messages[1].id", "id M1 is used more than once") in check_data(run)


def test_the_minimal_analysis_has_the_right_shape(tmp_path):
    run = clean_run(tmp_path)
    store.write_analysis(run, minimal_analysis(["F1"]))
    assert check_data(run, LENSES) == []


def test_an_audit_check_must_be_one_of_the_named_checks(tmp_path):
    run = clean_run(tmp_path)
    analysis = minimal_analysis(["F1"])
    analysis["audit_flags"] = [{"check": "single_source", "text": "One unnamed source."},
                               {"check": "independence", "text": "One unnamed source."}]
    store.write_analysis(run, analysis)
    assert [p for p in check_data(run) if p.field.startswith("audit_flags")] == \
        [Problem("analysis.json", "audit_flags[0].check", "not an allowed value")]
    assert len(store.AUDIT_CHECKS) == 10 and "evidence_symmetry" in store.AUDIT_CHECKS


# --- early signals, their source types and competitor baselines ---------------------------------

from radar.schema import check_proposal
from helpers import PERMIT_TEXT, early_signal_proposal, proposal



def early_run(tmp_path, source_type="permit"):
    run = make_run(tmp_path)
    add_source(run, PERMIT_TEXT, type=source_type, publisher="Planning Office")
    return run


def test_an_early_signal_must_be_tentative_and_general(tmp_path):
    run = early_run(tmp_path)
    messages = [p.message for p in check_proposal(run, proposal(early_signal=True))]   # a firm capacity move
    assert "an early signal must be marked tentative" in messages
    assert "an early signal must be a general fact" in messages


def test_a_tentative_general_early_signal_is_accepted(tmp_path):
    run = early_run(tmp_path)
    assert check_proposal(run, early_signal_proposal()) == []


def test_an_early_signal_stored_with_a_firm_certainty_is_named_by_the_data_check(tmp_path):
    run = early_run(tmp_path)
    store.new_fact(run, early_signal_proposal())
    assert check_data(run) == []
    fact = store.read_facts(run)["F1"]
    fact["certainty"] = "firm"; fact["tentative_reason"] = None
    store.write_fact(run, fact)
    assert Problem("facts/F1.json", "certainty", "an early signal must be marked tentative") in check_data(run)


def test_a_firm_fact_that_is_not_an_early_signal_is_still_accepted(tmp_path):
    run = early_run(tmp_path, source_type="company_release")
    assert check_proposal(run, proposal(early_signal=False)) == []
    assert check_proposal(run, proposal()) == []   # a proposal without the key defaults to false


def test_early_signal_must_be_true_or_false(tmp_path):
    run = early_run(tmp_path)
    for bad in ("yes", 1, None):
        problems = check_proposal(run, early_signal_proposal(early_signal=bad))
        assert Problem("proposal", "early_signal", "not an allowed value") in problems, bad


def test_a_fact_stored_before_early_signals_existed_still_passes_the_data_check(tmp_path):
    run = clean_run(tmp_path)
    fact = store.read_facts(run)["F1"]
    fact.pop("early_signal", None)
    store.write_fact(run, fact)
    assert "early_signal" not in store.read_facts(run)["F1"]
    assert check_data(run) == []


def test_a_new_fact_carries_early_signal_false_by_default():
    assert store.proposed_fact({})["early_signal"] is False
    assert store.proposed_fact({"early_signal": True})["early_signal"] is True


def test_the_three_early_signal_source_types_are_allowed(tmp_path):
    assert store.SOURCE_TYPES[-4:] == ("permit", "job_posting", "regulator_record", "other")
    for source_type in ("permit", "job_posting", "regulator_record"):
        run = make_run(tmp_path / source_type)
        add_source(run, PERMIT_TEXT, type=source_type)
        assert check_data(run) == [], source_type
    run = make_run(tmp_path / "bad")
    add_source(run, PERMIT_TEXT, type="rumour")
    assert Problem("sources/S1.json", "type", "not an allowed value") in check_data(run)


WORDING = "a baseline takes its wording from its facts"


def test_a_baseline_needs_a_company_and_a_fact_and_has_no_text_of_its_own(tmp_path):
    run = clean_run(tmp_path)
    analysis = minimal_analysis(["F1"]); analysis["baselines"] = [{"company": "Competitor A", "fact_ids": ["F1"]}]
    store.write_analysis(run, analysis)
    assert check_data(run, LENSES) == []
    analysis["baselines"] = [{"company": " ", "fact_ids": []}, {"company": "B"}, "not an object"]
    store.write_analysis(run, analysis)
    problems = check_data(run, LENSES)
    for expected in (Problem("analysis.json", "baselines[0].company", "must not be empty"),
                     Problem("analysis.json", "baselines[0].fact_ids", "must have at least one entry"),
                     Problem("analysis.json", "baselines[1].fact_ids", "must have at least one entry"),
                     Problem("analysis.json", "baselines[2]", "not an allowed value")):
        assert expected in problems
    analysis["baselines"] = "none"
    store.write_analysis(run, analysis)
    assert Problem("analysis.json", "baselines", "not an allowed value") in check_data(run, LENSES)


def test_a_baseline_with_figures_of_its_own_is_refused(tmp_path):
    run = clean_run(tmp_path)
    analysis = minimal_analysis(["F1"])
    analysis["baselines"] = [{"company": "Competitor A", "fact_ids": ["F1"],
                              "text": "Nine plants, 4000 staff and 300 million invested."}]
    store.write_analysis(run, analysis)
    assert Problem("analysis.json", "baselines[0].text", WORDING) in check_data(run, LENSES)
    with pytest.raises(GateRefused):
        build_report(run, LENSES)
    analysis["baselines"][0]["text"] = ""          # even an empty text is a key the baseline may not have
    store.write_analysis(run, analysis)
    assert Problem("analysis.json", "baselines[0].text", WORDING) in check_data(run, LENSES)
    analysis["baselines"] = "none"
    store.write_analysis(run, analysis)
    assert Problem("analysis.json", "baselines", "not an allowed value") in check_data(run, LENSES)


def test_a_baseline_that_rests_on_a_missing_fact_is_named(tmp_path):
    run = clean_run(tmp_path)
    analysis = minimal_analysis(["F1"])
    analysis["baselines"] = [{"company": "Competitor A", "fact_ids": ["F9"]}]
    store.write_analysis(run, analysis)
    assert Problem("analysis.json", "baselines[0].fact_ids", "fact F9 does not exist") in check_data(run, LENSES)


# --- a fact from a permit, a job posting or a regulator record is an early signal ----------------------------

SOURCE_RULE = "a fact from a permit, a job posting or a regulator record must be marked as an early signal"


def test_the_early_signal_source_types_are_one_constant():
    assert store.EARLY_SIGNAL_SOURCE_TYPES == ("permit", "job_posting", "regulator_record")


def test_a_capacity_move_from_a_job_posting_without_the_mark_is_refused(tmp_path):
    run = early_run(tmp_path, source_type="job_posting")
    assert Problem("proposal", "early_signal", SOURCE_RULE) in check_proposal(run, proposal(primary_source=True))
    assert Problem("proposal", "early_signal", SOURCE_RULE) in check_proposal(run, proposal(early_signal=False))


def test_every_early_signal_source_type_needs_the_mark(tmp_path):
    for source_type in store.EARLY_SIGNAL_SOURCE_TYPES:
        run = early_run(tmp_path / source_type, source_type=source_type)
        unmarked = early_signal_proposal(early_signal=False)
        assert Problem("proposal", "early_signal", SOURCE_RULE) in check_proposal(run, unmarked), source_type
        assert check_proposal(run, early_signal_proposal()) == [], source_type


def test_a_marked_tentative_general_fact_from_a_job_posting_still_works(tmp_path):
    run = early_run(tmp_path, source_type="job_posting")
    assert check_proposal(run, early_signal_proposal()) == []


def test_a_fact_from_an_ordinary_company_release_is_unaffected(tmp_path):
    run = make_run(tmp_path)
    add_source(run, PERMIT_TEXT, type="company_release")
    unmarked = early_signal_proposal(early_signal=False, certainty="firm", tentative_reason=None)
    assert check_proposal(run, unmarked) == []
    assert check_proposal(run, proposal(source_id="S1", quote="an application for a new filling hall at Plant North")) == []


def test_only_the_main_source_decides(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "Competitor A will add a second filling line at Plant North by 2028.", type="company_release")
    add_source(run, PERMIT_TEXT, type="permit")
    backed = proposal(supporting=[{"source_id": "S2", "quote": "an application for a new filling hall at Plant North"}])
    assert check_proposal(run, backed) == []


def test_add_fact_and_add_facts_refuse_the_probe(tmp_path, capsys):
    run = early_run(tmp_path, source_type="job_posting")
    probe = proposal(primary_source=True)
    path = run / "probe.json"
    path.write_text(json.dumps(probe), encoding="utf-8")
    assert main(["add-fact", "--run", str(run), "--file", str(path)]) == 2
    assert SOURCE_RULE in capsys.readouterr().out
    path.write_text(json.dumps([probe, early_signal_proposal()]), encoding="utf-8")
    assert main(["add-facts", "--run", str(run), "--file", str(path)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert [item["index"] for item in out["added"]] == [1]
    assert any(SOURCE_RULE in reason for reason in out["refused"][0]["reasons"])
    assert list(store.read_facts(run)) == ["F1"]


def test_a_stored_fact_from_a_permit_without_the_mark_is_named_by_the_data_check(tmp_path):
    run = early_run(tmp_path)
    store.new_fact(run, early_signal_proposal())
    assert check_data(run) == []
    fact = store.read_facts(run)["F1"]
    fact["early_signal"] = False
    store.write_fact(run, fact)
    assert Problem("facts/F1.json", "early_signal", SOURCE_RULE) in check_data(run)
    fact.pop("early_signal")
    store.write_fact(run, fact)
    assert Problem("facts/F1.json", "early_signal", SOURCE_RULE) in check_data(run)


# --- final_url: where a copy really came from ------------------------------------------------

def test_a_source_record_without_final_url_is_not_a_problem(tmp_path):
    run = clean_run(tmp_path)
    assert "final_url" not in store.read_sources(run)["S1"]   # as written before the key existed
    assert check_data(run) == []


def test_final_url_may_be_null_or_a_web_address(tmp_path):
    run = clean_run(tmp_path)
    for value in (None, "https://other.example/page", "HTTP://other.example:8080/a?b=c#d",
                  "https://other.example/@author/post-1", "https://other.example/p?mail=a@b.example",
                  "http://www.example.test:8080/@channel", "https://other.example/doc%20with%20space"):
        edit_source(run, final_url=value)
        assert check_data(run) == []


def test_final_url_that_is_not_a_web_address_is_an_explained_problem(tmp_path):
    from radar.explain import explain
    run = clean_run(tmp_path)
    for value in ("", "   ", "ftp://other.example/x", "javascript:alert(1)", "other.example/page", "https:///x",
                  "https://user:pw@other.example/", 5, ["https://other.example/"], {},
                  "https://oth%65r.example/", "https://other.example/a b",
                  "https://other.example/a" + chr(9) + "b", "plain text", "https://exämple.test/"):
        edit_source(run, final_url=value)
        problems = check_data(run)
        assert problems == [Problem("sources/S1.json", "final_url", "not an allowed value")], value
        assert explain(problems[0])["known"]


def test_a_damaged_final_url_is_a_problem_and_never_an_exception(tmp_path):
    run = clean_run(tmp_path)
    for value in ("https://[x/", "https://[::1]x/", "https://[127.0.0.1]/"):
        edit_source(run, final_url=value)
        assert check_data(run) == [Problem("sources/S1.json", "final_url", "not an allowed value")], value


def test_the_data_check_judges_final_url_with_the_form_check_of_the_download(tmp_path):
    from radar import fetch
    run = clean_run(tmp_path)
    for value in ("https://other.example/@a", "https://user:pw@other.example/", "https://o%74her.example/",
                  "http://other.example:99999x/", "https://other.example:8080/", "ftp://other.example/"):
        try:
            fetch.check_url(value)
            accepted = True
        except ValueError:
            accepted = False
        edit_source(run, final_url=value)
        assert (check_data(run) == []) is accepted, value


# --- Part A fix A1, ruling HG3: a proposal is checked as strictly as every later command --------------------

from helpers import proposal   # noqa: E402
from radar.schema import SIZE_AS_TEXT   # noqa: E402

GOOD_QUOTE = "adds two high-speed syringe lines for customers"
STRICT_CASES = [
    (proposal(early_singal=True), "early_singal", "the key early_singal is not known"),
    (proposal(note="from the call"), "note", "the key note is not known"),
    (proposal(supporting=[{"source_id": "S1", "quote": 42}]), "supporting[0].quote", "must be text"),       # point 7
    (proposal(supporting=[{"source_id": "S1", "quote": ["adds", "two", "lines"]}]), "supporting[0].quote",
     "must be text"),
    (proposal(quote=42), "quote", "must be text"),                                                      # the same rule
    (proposal(supporting=[{"source_id": "S1"}]), "supporting[0].quote", "must not be empty"),
    (proposal(supporting=[{"source_id": "S1", "quote": "two new lines"}]), "supporting[0].quote",
     "quote must have 5 to 50 words"),
    (proposal(supporting=[{"source_id": "S1", "quote": " ".join(["word"] * 51)}]), "supporting[0].quote",
     "quote must have 5 to 50 words"),
    (proposal(supporting=[{"source_id": "S1", "quote": GOOD_QUOTE, "note": "x"}]), "supporting[0].note",
     "the key note is not known"),
    (proposal(supporting=[{"source_id": "S1", "quote": GOOD_QUOTE, "quote_translation": 5}]),
     "supporting[0].quote_translation", "not an allowed value"),
    (proposal(fields={"size_value": 2.5}), "fields.size_value", SIZE_AS_TEXT),
    (proposal(fields={"size_value": 2}), "fields.size_value", SIZE_AS_TEXT),
    (proposal(fields={"colour": "red"}), "fields.colour", "the key colour is not known"),
]


def strict_run(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "The expansion adds two high-speed syringe lines for customers in 2028.")
    return run


def test_add_fact_refuses_each_proposal_that_breaks_a_strict_rule(tmp_path, capsys):
    run = strict_run(tmp_path)
    for bad, field, message in STRICT_CASES:
        path = tmp_path / "proposal.json"
        path.write_text(json.dumps(bad), encoding="utf-8")
        assert main(["add-fact", "--run", str(run), "--file", str(path)]) == 2, field
        out = json.loads(capsys.readouterr().out)
        assert f"{field}: {message}" in out["error"], (field, out)
    assert store.read_facts(run) == {} and store.load_run(run)["facts_created"] == 0


def test_add_facts_from_json_names_each_strict_rule_and_writes_only_the_good_proposal(tmp_path, capsys):
    run = strict_run(tmp_path)
    proposals = [bad for bad, _, _ in STRICT_CASES] + [proposal()]
    file = tmp_path / "all.json"
    file.write_text(json.dumps(proposals), encoding="utf-8")
    options = tmp_path / "options.json"
    options.write_text(json.dumps({"run": str(run), "file": str(file)}), encoding="utf-8")
    assert main(["add-facts", "--from-json", str(options)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["added"] == [{"index": len(STRICT_CASES), "fact_id": "F1"}]
    for index, (_, field, message) in enumerate(STRICT_CASES):
        assert out["refused"][index]["index"] == index
        assert f"{field}: {message}" in out["refused"][index]["reasons"], (field, out["refused"][index])
    assert sorted(store.read_facts(run)) == ["F1"]


def test_a_proposal_within_the_strict_rules_is_accepted(tmp_path, capsys):
    run = strict_run(tmp_path)
    good = [proposal(supporting=[{"source_id": "S1", "quote": GOOD_QUOTE}]),
            proposal(supporting=[{"source_id": "S1", "quote": GOOD_QUOTE, "quote_translation": "a translation"}]),
            proposal(supporting=[{"source_id": "S1", "quote": GOOD_QUOTE, "quote_translation": None}]),
            proposal(fields={"size_value": "2.5"}), proposal(fields={"size_value": None}),
            proposal(kind="general", fields=None)]
    for index, fine in enumerate(good):
        path = tmp_path / "proposal.json"
        path.write_text(json.dumps(fine), encoding="utf-8")
        assert main(["add-fact", "--run", str(run), "--file", str(path)]) == 0, index
        capsys.readouterr()


def test_the_data_check_names_a_stored_fact_that_breaks_a_strict_rule(tmp_path):
    from radar.gate import gate
    run = strict_run(tmp_path)
    fact = add_fact(run, source_id="S1", quote=GOOD_QUOTE)
    fact.update(early_singal=True, supporting=[{"source_id": "S1", "quote": 42, "page": 3}])
    fact["fields"] = {**fact["fields"], "size_value": 2, "colour": "red"}
    store.write_fact(run, fact)
    expected = [Problem("facts/F1.json", "early_singal", "the key early_singal is not known"),
                Problem("facts/F1.json", "supporting[0].quote", "must be text"),
                Problem("facts/F1.json", "supporting[0].page", "the key page is not known"),
                Problem("facts/F1.json", "fields.size_value", SIZE_AS_TEXT),
                Problem("facts/F1.json", "fields.colour", "the key colour is not known")]
    found = check_data(run)
    assert all(problem in found for problem in expected), found
    assert all(problem in gate(run) for problem in expected)


def test_the_strict_rules_are_explained_in_plain_words():
    from radar.explain import explain
    for message in (SIZE_AS_TEXT, "the key early_singal is not known"):
        explained = explain(Problem("facts/F1.json", None, message))
        assert explained["known"] is True, message
    assert "early_singal" in explain(Problem("facts/F1.json", None, "the key early_singal is not known"))["what"]


def test_the_ten_demo_proposals_and_the_variants_still_pass(tmp_path):
    from radar.demo import build_demo_run
    for name, variant in (("base", {}), ("changed", {"changed": True}), ("private", {"private": True})):
        run = build_demo_run(tmp_path / name, stage="extracted", **variant)
        assert len(store.read_facts(run)) == (11 if name == "private" else 10)
        assert check_data(run) == []


# --- follow-up, point 6: a proposal never carries a key the program sets itself ---------------------------------

PROGRAM_SET = {"id": "F7", "checks": {"quote": {"passed": True}}, "status": "confirmed", "status_reason": None,
               "withdrawn": {"reason": "x"}}


def test_add_fact_and_add_facts_refuse_a_key_the_program_sets_and_name_it(tmp_path, capsys):
    run = strict_run(tmp_path)
    for key, value in PROGRAM_SET.items():
        path = tmp_path / "proposal.json"
        path.write_text(json.dumps(proposal(**{key: value})), encoding="utf-8")
        assert main(["add-fact", "--run", str(run), "--file", str(path)]) == 2, key
        error = json.loads(capsys.readouterr().out)["error"]
        assert f"{key}: the key {key} is set by the program, not by a proposal" in error, error
    file = tmp_path / "all.json"
    file.write_text(json.dumps([proposal(**{key: value}) for key, value in PROGRAM_SET.items()] + [proposal()]),
                    encoding="utf-8")
    assert main(["add-facts", "--run", str(run), "--file", str(file)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["added"] == [{"index": len(PROGRAM_SET), "fact_id": "F1"}]
    for index, key in enumerate(PROGRAM_SET):
        assert f"{key}: the key {key} is set by the program, not by a proposal" in out["refused"][index]["reasons"]
    assert store.read_facts(run)["F1"]["status"] == "proposed"


def test_a_stored_fact_keeps_the_keys_the_program_set_without_a_problem(tmp_path):
    run = strict_run(tmp_path)
    add_fact(run, source_id="S1", quote=GOOD_QUOTE)
    from radar import verify
    verify.check_quotes(run); verify.withdraw_fact(run, "F1", "a duplicate"); verify.settle(run)
    assert check_data(run) == []


def test_the_program_key_message_is_explained():
    from radar.explain import explain
    explained = explain(Problem("proposal", "status", "the key status is set by the program, not by a proposal"))
    assert explained["known"] is True and "status" in explained["what"]


# --- follow-up, point 7: a quote that is not text is named as such --------------------------------------------

def test_must_be_text_is_explained_for_a_fact_as_well_as_for_the_analysis():
    from radar.explain import explain
    explained = explain(Problem("facts/F1.json", "supporting[0].quote", "must be text"))
    assert explained["known"] is True and "analysis" not in explained["what"]


# --- follow-up, point 5: the advice for damage only a hand edit can make is what is true --------------------------

def test_the_data_check_still_names_a_withdrawn_fact_s_hand_damage(tmp_path):
    from radar import verify
    run = strict_run(tmp_path)
    fact = add_fact(run, source_id="S1", quote=GOOD_QUOTE)
    fact["early_singal"] = True; store.write_fact(run, fact)
    verify.withdraw_fact(run, "F1", "damaged by hand"); verify.settle(run)
    assert Problem("facts/F1.json", "early_singal", "the key early_singal is not known") in check_data(run)


def test_the_advice_for_hand_damage_says_what_is_true():
    from radar.explain import explain
    for message in ("the key early_singal is not known", SIZE_AS_TEXT, "an early signal must be marked tentative"):
        do = explain(Problem("facts/F1.json", None, message))["do"]
        assert "withdraw" not in do.lower() and "new fact" not in do and "new one" not in do, do
        assert do.startswith("This fact was changed outside the program.") and "start a new run" in do, do


# --- Part A fix A2, item 6: check-data explains its problems as the gate does ---------------------------------

def test_check_data_explains_each_problem_in_the_form_the_gate_uses(tmp_path, capsys):
    from radar.explain import explain
    run = clean_run(tmp_path)
    assert run_cli(capsys, "check-data", "--run", str(run)) == (0, {"problems": [], "explained": []})
    edit_fact(run, statement="", supporting=[{"source_id": "S9", "quote": "a quote in a source that is not there"}])
    code, out = run_cli(capsys, "check-data", "--run", str(run))
    assert code == 1 and list(out) == ["problems", "explained"] and len(out["problems"]) == 2
    assert out["explained"] == [explain(Problem(**problem)) for problem in out["problems"]]
    assert all(entry["known"] for entry in out["explained"])
    assert "S9" in out["explained"][1]["what"]


# --- fix wave A2: a "Fact" step names a fact, and a chain ends with its conclusion ---------------------------------

from radar.explain import explain   # noqa: E402
from radar.gate import gate   # noqa: E402

FACT_STEP_EMPTY = "a fact step must name at least one fact"
CONCLUSION_NOT_LAST = "the last step of a chain must be its conclusion"


def test_a_fact_step_that_names_no_fact_is_refused_by_the_data_check_and_the_gate(tmp_path):
    run = clean_run(tmp_path)
    analysis = minimal_analysis(["F1"])
    analysis["messages"][0]["chain"].insert(1, {"kind": "fact", "text": "Competitor Q is building three plants.",
                                                "fact_ids": [], "lens_id": None})
    analysis["messages"][0]["chain"].insert(2, {"kind": "fact", "text": "Competitor Q hired a manager.",
                                                "lens_id": None})   # no fact_ids at all
    store.write_analysis(run, analysis)
    expected = [Problem("analysis.json", "messages[0].chain[1].fact_ids", FACT_STEP_EMPTY),
                Problem("analysis.json", "messages[0].chain[2].fact_ids", FACT_STEP_EMPTY)]
    assert [p for p in check_data(run) if p.message == FACT_STEP_EMPTY] == expected
    assert [p for p in gate(run) if p.message == FACT_STEP_EMPTY] == expected


def test_a_chain_whose_conclusion_is_not_its_last_step_is_refused(tmp_path):
    run = clean_run(tmp_path)
    analysis = minimal_analysis(["F1"])
    chain = analysis["messages"][0]["chain"]
    chain.append({"kind": "reasoning", "text": "So Competitor Q will win.", "fact_ids": [], "lens_id": None})
    store.write_analysis(run, analysis)
    assert Problem("analysis.json", "messages[0].chain", CONCLUSION_NOT_LAST) in check_data(run)
    assert Problem("analysis.json", "messages[0].chain", CONCLUSION_NOT_LAST) in gate(run)


def test_the_two_chain_rules_are_quiet_for_a_good_chain_and_do_not_repeat_the_conclusion_count(tmp_path):
    run = clean_run(tmp_path)
    store.write_analysis(run, minimal_analysis(["F1"]))
    assert check_data(run) == []
    analysis = minimal_analysis(["F1"])
    analysis["messages"][0]["chain"] = analysis["messages"][0]["chain"][:2]   # no conclusion at all
    store.write_analysis(run, analysis)
    messages = [p.message for p in check_data(run)]
    assert "chain must have exactly one conclusion step" in messages and CONCLUSION_NOT_LAST not in messages


def test_the_demo_keeps_both_chain_rules(tmp_path):
    from radar.demo import build_demo_run
    run = build_demo_run(tmp_path)
    assert check_data(run, LENSES) == []


def test_the_two_chain_rules_are_explained_in_plain_words():
    for message in (FACT_STEP_EMPTY, CONCLUSION_NOT_LAST):
        explained = explain(Problem("analysis.json", "messages[0].chain", message))
        assert explained["known"] is True and explained["what"] and explained["do"], message


# --- fix wave A20: a private run's ignore file is checked again ----------------------------------------------------

from radar import fetch   # noqa: E402

NOT_IGNORED = "the ignore file of a private run must keep the whole run out of git"


@pytest.mark.parametrize("ignore", [None, "", "copies/\n", "# *\n", "*.tmp\n", "!*\n", "*\n!copies/\n"])
def test_a_private_run_whose_ignore_file_no_longer_holds_the_star_is_named_by_the_data_check_and_the_gate(
        tmp_path, ignore):
    run = make_run(tmp_path, mode="private", acknowledged=True)
    assert Problem(".gitignore", None, NOT_IGNORED) not in check_data(run)
    if ignore is None:
        (run / ".gitignore").unlink()
    else:
        (run / ".gitignore").write_text(ignore, encoding="utf-8")
    assert Problem(".gitignore", None, NOT_IGNORED) in check_data(run)
    assert Problem(".gitignore", None, NOT_IGNORED) in gate(run)


@pytest.mark.parametrize("ignore", ["*\n", "*", "  *  \n", "# kept out\n*\n", "*\n.lock\n"])
def test_a_star_on_a_line_of_its_own_keeps_a_private_run_out_of_git(tmp_path, ignore):
    run = make_run(tmp_path, mode="private", acknowledged=True)
    (run / ".gitignore").write_text(ignore, encoding="utf-8")
    assert Problem(".gitignore", None, NOT_IGNORED) not in check_data(run)


def test_a_public_run_s_ignore_file_is_not_judged_by_this_rule(tmp_path):
    run = make_run(tmp_path)
    (run / ".gitignore").unlink()
    assert Problem(".gitignore", None, NOT_IGNORED) not in check_data(run)


def test_add_copy_of_non_public_material_into_a_private_run_that_git_could_take_is_refused(tmp_path, capsys):
    run = make_run(tmp_path, mode="private", acknowledged=True)
    (run / ".gitignore").write_text(".lock\n", encoding="utf-8")
    memo = tmp_path / "memo.txt"
    memo.write_text("An invented internal memo about two new lines, illustrative only. " * 4, encoding="utf-8")
    argv = ["add-copy", "--run", str(run), "--file", str(memo), "--url", "internal://memo", "--publisher", "P",
            "--title", "T", "--date", "2026-05-14", "--type", "other", "--speaker", "S", "--interest", "I",
            "--language", "en", "--supplied-by", "the tester", "--basis", "own memo"]
    for data_class in ("internal", "licensed"):
        assert main(argv + ["--data-class", data_class]) == 2
        out = json.loads(capsys.readouterr().out)
        assert out["error"] == NOT_IGNORED and out["explained"][0]["known"] is True
    assert store.read_sources(run) == {}
    assert main(argv + ["--data-class", "public"]) == 0            # public material may still come in
    capsys.readouterr()
    (run / ".gitignore").write_text("*\n", encoding="utf-8")
    assert main(argv + ["--data-class", "internal"]) == 0


def test_the_explanation_says_what_to_do_in_plain_words():
    from radar.explain import explain
    explained = explain(Problem(".gitignore", None, NOT_IGNORED))
    assert explained["known"] is True and "*" in explained["do"]


# --- fix wave A23.7: an audit flag is exactly a check and a text that says something -------------------------------

@pytest.mark.parametrize("flag, field, message", [
    ({"check": "framing", "text": "The question is the company's own.", "severity": "high"},
     "audit_flags[0].severity", "the key severity is not known in a flag"),   # ruling FWA-5a: a flag's own message
    ({"check": "framing", "text": "The question is the company's own.", "fact_ids": ["F1"]},
     "audit_flags[0].fact_ids", "the key fact_ids is not known in a flag"),
    ({"check": "framing", "text": ""}, "audit_flags[0].text", "must not be empty"),
    ({"check": "framing", "text": "   "}, "audit_flags[0].text", "must not be empty"),
    ({"check": "framing"}, "audit_flags[0].text", "must not be empty"),
])
def test_an_audit_flag_with_an_extra_key_or_no_text_is_refused_by_the_data_check_and_the_gate(tmp_path, flag, field,
                                                                                            message):
    run = clean_run(tmp_path)
    analysis = minimal_analysis(["F1"])
    analysis["audit_flags"] = [flag]
    store.write_analysis(run, analysis)
    assert Problem("analysis.json", field, message) in check_data(run)
    assert Problem("analysis.json", field, message) in gate(run)


def test_a_good_audit_flag_passes(tmp_path):
    run = clean_run(tmp_path)
    analysis = minimal_analysis(["F1"])
    analysis["audit_flags"] = [{"check": "framing", "text": "The question is the company's own."}]
    store.write_analysis(run, analysis)
    assert check_data(run) == []


# --- a flag names the messages it is about (decision D10) -----------------------------------------------------------

def _run_with_flag(tmp_path, flag):
    run = clean_run(tmp_path)
    analysis = minimal_analysis(["F1"])
    analysis["audit_flags"] = [flag]
    store.write_analysis(run, analysis)
    return run


def test_a_flag_may_name_the_messages_it_is_about(tmp_path):
    run = _run_with_flag(tmp_path, {"check": "framing", "text": "The question is the company's own.",
                                    "message_ids": ["M1"]})
    assert check_data(run) == []


def test_a_flag_about_no_message_has_an_empty_list(tmp_path):
    run = _run_with_flag(tmp_path, {"check": "framing", "text": "The question is the company's own.",
                                    "message_ids": []})
    assert check_data(run) == []


def test_a_flag_that_names_a_message_that_does_not_exist_is_named(tmp_path):
    run = _run_with_flag(tmp_path, {"check": "framing", "text": "The question is the company's own.",
                                    "message_ids": ["M1", "M9"]})
    problem = Problem("analysis.json", "audit_flags[0].message_ids", "a flag names message M9, which does not exist")
    assert problem in check_data(run)
    assert problem in gate(run)


def test_message_ids_must_be_a_list(tmp_path):
    run = _run_with_flag(tmp_path, {"check": "framing", "text": "The question is the company's own.",
                                    "message_ids": "M1"})
    assert Problem("analysis.json", "audit_flags[0].message_ids", MUST_BE_LIST) in check_data(run)


def test_each_message_id_must_be_text(tmp_path):
    run = _run_with_flag(tmp_path, {"check": "framing", "text": "The question is the company's own.",
                                    "message_ids": [1]})
    assert Problem("analysis.json", "audit_flags[0].message_ids[0]", MUST_BE_TEXT) in check_data(run)


def test_a_flag_without_message_ids_is_still_accepted(tmp_path):
    run = _run_with_flag(tmp_path, {"check": "framing", "text": "The question is the company's own."})
    assert check_data(run) == []
    assert not [p for p in gate(run) if p.field.startswith("audit_flags")]


# --- fix wave A23.9: a source, fact, analysis or copy this user may not open is named as such ------------------------

from helpers import unreadable_file   # noqa: E402

LOCKED = "may not be opened by this user"


@pytest.mark.parametrize("name, field", [("sources/S1.json", None), ("facts/F1.json", None),
                                         ("analysis.json", None), ("copies/S1.txt", "copy_file")])
def test_an_item_this_user_may_not_open_is_named_so_and_not_as_damaged_or_missing(tmp_path, name, field):
    from radar.explain import explain
    run = clean_run(tmp_path)
    store.write_analysis(run, minimal_analysis(["F1"]))
    with unreadable_file(run / name):
        problems = check_data(run)
    named = "sources/S1.json" if name.startswith("copies/") else name
    assert Problem(named, field, LOCKED) in problems
    assert all(p.message not in ("not valid JSON", "saved copy is missing") for p in problems if p.file == named)
    explained = explain(Problem(named, field, LOCKED))
    assert explained["known"] is True and "may not open" in explained["what"]


# --- Plan 2b, Task 10, change F: the note on a web page that holds little running text ------------------------------

def flagged_run(tmp_path, orig="copies/S1.orig.html"):
    """A clean run whose S1 is a saved web page with the note, as save-source writes it (the page itself invented)."""
    run = clean_run(tmp_path)
    (run / orig).write_text("<html><body><p>Home</p></body></html>", encoding="utf-8")
    edit_source(run, orig_file=orig, text_note="little_running_text")
    return run


def test_the_data_check_and_the_gate_accept_a_saved_web_page_with_the_note(tmp_path):
    from radar.gate import gate
    for orig in ("copies/S1.orig.html", "copies/S1.orig.htm"):
        run = flagged_run(tmp_path / orig[-4:], orig)
        assert check_data(run) == [], orig
        assert not [p for p in gate(run) if p.file.startswith("sources/")], orig
    assert store.TEXT_NOTES == ("little_running_text",)


def test_a_record_without_the_note_stays_valid(tmp_path):
    run = clean_run(tmp_path)
    assert "text_note" not in store.read_sources(run)["S1"] and check_data(run) == []


def test_the_note_holds_its_one_value_or_is_left_out(tmp_path):
    run = flagged_run(tmp_path)
    for value in ("mostly_menu_text", "", None, True, ["little_running_text"], {"note": "little_running_text"}):
        edit_source(run, text_note=value)
        assert check_data(run) == [Problem("sources/S1.json", "text_note", "not an allowed value")], value


NOTE_ON_A_PAGE_ONLY = "only a saved web page can have the note little_running_text"


def test_the_note_on_anything_but_a_saved_web_page_is_a_problem(tmp_path):
    from radar.gate import gate
    run = flagged_run(tmp_path)
    for changes in ({"orig_file": "copies/S1.orig.pdf"}, {"orig_file": "copies/S1.orig.txt"},
                    {"orig_file": "copies/S1.orig.csv"}, {"orig_file": None}):
        edit_source(run, **changes)
        assert check_data(run) == [Problem("sources/S1.json", "text_note", NOTE_ON_A_PAGE_ONLY)], changes
        assert Problem("sources/S1.json", "text_note", NOTE_ON_A_PAGE_ONLY) in gate(run), changes
    edit_source(run, orig_file=None, access="not_accessible", access_reason="timeout", copy_file=None,
                copy_sha256=None)
    assert check_data(run) == [Problem("sources/S1.json", "text_note", NOTE_ON_A_PAGE_ONLY)]


def test_the_note_problem_is_explained_in_plain_words():
    from radar.explain import explain
    explained = explain(Problem("sources/S4.json", "text_note", NOTE_ON_A_PAGE_ONLY))
    assert explained["known"] is True and "S4" in explained["what"]
    assert "little running text" in explained["what"] and "by hand" in explained["why"]
    assert "menu" not in " ".join(explained[part] for part in ("what", "why", "do"))   # fix round 1: as measured
    assert explain(Problem("sources/S4.json", "text_note", "not an allowed value"))["known"] is True


# --- why a fact is uncertain: the codes -----------------------------------------------------------------------------

def test_a_proposal_may_not_set_the_codes(tmp_path):
    run = strict_run(tmp_path)
    problems = check_proposal(run, proposal(uncertain_reasons=["single_source"]))
    assert Problem("proposal", "uncertain_reasons",
                   "the key uncertain_reasons is set by the program, not by a proposal") in problems


def test_stored_codes_must_be_known(tmp_path):
    run = clean_run(tmp_path)
    for bad in (["unclear"], "single_source", ["single_source", 3], None):
        fact = store.read_facts(run)["F1"]
        fact["uncertain_reasons"] = bad
        store.write_fact(run, fact)
        assert Problem("facts/F1.json", "uncertain_reasons", "not an allowed value") in check_data(run), bad
    for good in ([], ["single_source"], ["tentative", "early_signal"]):
        fact = store.read_facts(run)["F1"]
        fact["uncertain_reasons"] = good
        store.write_fact(run, fact)
        assert check_data(run) == [], good


def _problems_of_companies(tmp_path, companies):
    run = clean_run(tmp_path)
    data = store.load_run(run)
    data["companies"] = companies
    store.save_run(run, data)
    return [p for p in check_data(run) if p.file == "run.json"]


def test_a_run_may_hold_companies_in_the_recorded_shape(tmp_path):
    good = [{"name": "Example Pharma", "other_names": ["Example Pharma Group"], "home": True},
            {"name": "Competitor A", "other_names": [], "home": False}]
    assert _problems_of_companies(tmp_path, good) == []
    assert _problems_of_companies(tmp_path / "b", []) == []
    from radar import schema
    assert schema.COMPANY_KEYS == ("name", "other_names", "home")


def test_a_run_names_companies_of_the_wrong_shape(tmp_path):
    def one(companies, sub):
        return _problems_of_companies(tmp_path / sub, companies)
    home = {"name": "A", "other_names": [], "home": False}
    assert one("x", "a") == [Problem("run.json", "companies", "not an allowed value")]
    assert one(["x"], "b") == [Problem("run.json", "companies[0]", "not an allowed value")]
    assert one([{**home, "size": 1}], "c") == [Problem("run.json", "companies[0].size", "not an allowed value")]
    assert one([{"name": "A", "other_names": []}], "d") == [Problem("run.json", "companies[0].home", "not an allowed value")]
    assert one([{**home, "name": " "}], "e") == [Problem("run.json", "companies[0].name", "must not be empty")]
    assert one([{**home, "other_names": "x"}], "f") == [Problem("run.json", "companies[0].other_names", "not an allowed value")]
    assert one([{**home, "other_names": ["ok", "", 3]}], "g") == [
        Problem("run.json", "companies[0].other_names[1]", "must not be empty"),
        Problem("run.json", "companies[0].other_names[2]", "must not be empty")]
    assert one([{**home, "home": "yes"}], "h") == [Problem("run.json", "companies[0].home", "not an allowed value")]


def test_a_run_may_have_at_most_one_own_company(tmp_path):
    two = [{"name": "A", "other_names": [], "home": True}, {"name": "B", "other_names": [], "home": True}]
    problems = _problems_of_companies(tmp_path, two)
    assert problems == [Problem("run.json", "companies", "at most one company of a run is its own company")]


def test_the_message_about_two_own_companies_is_explained():
    from radar.explain import explain
    told = explain(Problem("run.json", "companies", "at most one company of a run is its own company"))
    assert told["known"] is True and told["what"] and told["why"] and told["do"]



# --- the company a fact is about, and its connections ---------------------------------------------------------------

def _general(**over):
    from helpers import proposal
    result = proposal(kind="general", fields=None, statement="Competitor A sells syringes to Drug maker B.",
                      quote="The expansion adds two high-speed syringe lines for customers")
    result.update(over)
    return result


def test_a_general_fact_may_name_the_company_it_is_about(tmp_path):
    from radar.schema import check_proposal
    run = strict_run(tmp_path)
    connection = {"party": "Drug maker B", "tie": "customer", "description": None}
    assert check_proposal(run, _general(about_company="Competitor A", connections=[connection])) == []
    assert check_proposal(run, _general(about_company=None, connections=None)) == []
    assert check_proposal(run, _general()) == []   # both keys left out
    assert Problem("proposal", "about_company", "must be text") in check_proposal(run, _general(about_company=5))
    assert Problem("proposal", "about_company", "must not be empty") in check_proposal(run, _general(about_company=""))


def test_a_capacity_move_takes_no_about_company(tmp_path):
    from radar.schema import ABOUT_ON_A_MOVE, check_proposal
    from helpers import proposal
    run = strict_run(tmp_path)
    assert ABOUT_ON_A_MOVE == "a capacity move names its company in fields.company"
    assert check_proposal(run, proposal(about_company="Competitor A")) == [
        Problem("proposal", "about_company", ABOUT_ON_A_MOVE)]
    assert check_proposal(run, proposal(about_company=None)) == []
    connection = {"party": "Drug maker B", "tie": "buyer", "description": None}
    assert check_proposal(run, proposal(connections=[connection])) == []   # a move may name its connections


def test_a_connection_has_a_known_tie_and_a_party_or_a_description(tmp_path):
    from radar.schema import NOT_ALLOWED, UNNAMED_PARTY, UNNAMED_PROPOSED_PARTY, check_proposal
    run = strict_run(tmp_path)
    assert UNNAMED_PROPOSED_PARTY == ("a connection names its other party; leave out a tie whose party the source "
                                      "does not name")
    assert UNNAMED_PARTY == "a connection that names no party must describe it"
    assert store.CONNECTION_TIES == ("buyer", "seller", "customer", "partner")

    def problems(*connections):
        return check_proposal(run, _general(about_company="Competitor A", connections=list(connections)))

    for tie in store.CONNECTION_TIES:
        assert problems({"party": "Drug maker B", "tie": tie, "description": None}) == [], tie
    assert problems({"party": None, "tie": "seller", "description": "a large drug maker"}) == [
        Problem("proposal", "connections[0].party", UNNAMED_PROPOSED_PARTY)]
    assert problems({"party": "Drug maker B", "tie": "supplier", "description": None}) == [
        Problem("proposal", "connections[0].tie", NOT_ALLOWED)]
    assert problems({"party": None, "tie": "buyer", "description": None}) == [
        Problem("proposal", "connections[0].party", UNNAMED_PROPOSED_PARTY)]
    assert problems({"tie": "buyer", "description": " "}) == [
        Problem("proposal", "connections[0].party", UNNAMED_PROPOSED_PARTY)]
    assert problems({"party": "Drug maker B", "tie": "buyer", "description": None, "share": "40%"}) == [
        Problem("proposal", "connections[0].share", "the key share is not known")]
    assert problems({"party": 5, "tie": "buyer", "description": None}) == [
        Problem("proposal", "connections[0].party", "must be text")]
    assert problems({"party": " ", "tie": "buyer", "description": None}) == [
        Problem("proposal", "connections[0].party", "must not be empty")]
    assert problems({"party": "Drug maker B", "tie": "buyer", "description": 5}) == [
        Problem("proposal", "connections[0].description", "must be text")]
    assert problems("Drug maker B") == [Problem("proposal", "connections[0]", NOT_ALLOWED)]
    assert check_proposal(run, _general(connections="Drug maker B")) == [
        Problem("proposal", "connections", NOT_ALLOWED)]


def test_a_stored_fact_with_an_unnamed_party_still_passes_the_data_check(tmp_path):
    from radar.schema import UNNAMED_PARTY
    run = clean_run(tmp_path)
    fact = store.read_facts(run)["F1"]
    fact["connections"] = [{"party": None, "tie": "buyer", "description": "a buyer it did not name"}]
    store.write_fact(run, fact)
    assert check_data(run) == []
    fact["connections"] = [{"party": None, "tie": "buyer", "description": None}]
    store.write_fact(run, fact)
    assert [p.message for p in check_data(run)] == [UNNAMED_PARTY]


def test_a_stored_fact_without_the_new_keys_is_fine(tmp_path):
    run = clean_run(tmp_path)
    fact = store.read_facts(run)["F1"]
    assert fact["about_company"] is None and fact["connections"] == []
    del fact["about_company"], fact["connections"]
    store.write_fact(run, fact)
    assert check_data(run) == []


def test_the_messages_about_a_fact_s_company_and_connections_are_explained():
    from radar.explain import explain
    from radar.schema import ABOUT_ON_A_MOVE, UNNAMED_PARTY, UNNAMED_PROPOSED_PARTY
    for field, message in (("about_company", ABOUT_ON_A_MOVE), ("connections[0].description", UNNAMED_PARTY),
                           ("connections[0].party", UNNAMED_PROPOSED_PARTY)):
        told = explain(Problem("facts/F1.json", field, message))
        assert told["known"] is True and told["what"] and told["why"] and told["do"], message


# --- whether a move falls inside the question -----------------------------------------------------------------------

def test_a_proposed_move_must_say_whether_it_falls_inside_the_question(tmp_path):
    run = strict_run(tmp_path)
    assert store.IN_QUESTION == ("yes", "no")
    assert check_proposal(run, proposal(fields={"in_question": "no"})) == []
    assert Problem("proposal", "fields.in_question", "not an allowed value") in \
        check_proposal(run, proposal(fields={"in_question": "maybe"}))
    missing = proposal()
    del missing["fields"]["in_question"]
    [problem] = [p for p in check_proposal(run, missing) if p.field == "fields.in_question"]
    assert problem == Problem("proposal", "fields.in_question",
                              "in_question is missing; it must be yes or no, set by the extractor")
    from radar.explain import explain
    assert "extractor" in explain(problem)["do"] and explain(problem)["known"] is True


def test_a_move_stored_before_the_field_existed_still_passes_the_data_check(tmp_path):
    run = clean_run(tmp_path)
    fact = store.read_facts(run)["F1"]
    del fact["fields"]["in_question"]
    store.write_fact(run, fact)
    assert check_data(run) == []
    fact["fields"]["in_question"] = "maybe"
    store.write_fact(run, fact)
    assert Problem("facts/F1.json", "fields.in_question", "not an allowed value") in check_data(run)


def test_a_message_may_name_its_memo_part_and_only_an_allowed_one(tmp_path):
    """A screening run's messages say which part of the memo they belong to (design 2026-11-17); other runs leave it out."""
    run = clean_run(tmp_path)
    for value, problems in (("team", []), ("people", ["not an allowed value"]), (3, ["not an allowed value"])):
        analysis = minimal_analysis(["F1"])
        analysis["messages"][0]["memo_part"] = value
        store.write_analysis(run, analysis)
        found = [p.message for p in check_data(run) if p.field == "messages[0].memo_part"]
        assert found == problems, value
    store.write_analysis(run, minimal_analysis(["F1"]))
    assert [p for p in check_data(run) if "memo_part" in (p.field or "")] == []
