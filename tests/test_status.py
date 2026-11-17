import ast
import json
import os
import re
from pathlib import Path

from radar import calc, pack, schema, schema_analysis, store, verify
from radar.explain import explain
from radar.report.build import build_report
from radar.schema import Problem
from radar.status import list_runs, run_status
from test_report_build import LENSES, ready_run
from helpers import add_fact, add_source, make_run, minimal_analysis, proposal
from fixtures.build_demo_run import build_demo_run

TEXT = "The expansion adds two high-speed syringe lines for customers, starting in 2028."
ORDER = ["collect", "extract", "verify", "checkpoint_lenses", "interpret", "checkpoint_final", "build"]
ENGINE = Path(__file__).parent.parent / "engine" / "radar"


def states(st): return {step["name"]: step["state"] for step in st["steps"]}


def snapshot(folder):
    """Every file under `folder` with its bytes and modification time."""
    return {str(p.relative_to(folder)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(Path(folder).rglob("*")) if p.is_file()}


def test_new_run_starts_at_collect(tmp_path):
    st = run_status(make_run(tmp_path))
    assert [step["name"] for step in st["steps"]] == ORDER
    assert set(states(st).values()) == {"pending"} and st["next"] == "collect" and st["waiting_for_person"] is False
    assert st["run_id"] == "run1" and st["question"] == "Who adds capacity?" and st["mode"] == "public"


def test_half_checked_run_is_in_progress(tmp_path):
    run = make_run(tmp_path); add_source(run, TEXT)
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    add_fact(run, source_id="S1", primary_source=True, quote="two high-speed syringe lines for customers, starting in 2028")
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    st = run_status(run)
    assert (states(st)["collect"], states(st)["extract"], states(st)["verify"]) == ("done", "done", "in_progress")
    assert st["steps"][2]["detail"] == "1 confirmed, 0 uncertain, 0 rejected, 1 still to check" and st["next"] == "verify"
    assert st["steps"][0]["detail"] == "1 source saved, 0 not accessible"
    assert st["steps"][1]["detail"] == "2 facts proposed, 0 sources still to read"


def test_collect_counts_sources_that_could_not_be_saved(tmp_path):
    run = make_run(tmp_path); add_source(run, TEXT)
    add_source(run, "", access="not_accessible", access_reason="http_403", copy_file=None, copy_sha256=None)
    assert run_status(run)["steps"][0]["detail"] == "1 source saved, 1 not accessible"


def test_collect_names_the_saved_pages_that_hold_little_running_text_and_only_when_there_are_any(tmp_path):
    """Plan 2b, Task 10, change F: the clause is added only for a flagged page; the strings above stay as they are."""
    run = make_run(tmp_path); add_source(run, TEXT)
    add_source(run, "", access="not_accessible", access_reason="timeout", copy_file=None, copy_sha256=None)
    assert run_status(run)["steps"][0]["detail"] == "1 source saved, 1 not accessible"
    add_source(run, TEXT, orig_file="copies/S3.orig.html", text_note="little_running_text")
    collect = run_status(run)["steps"][0]
    assert (collect["state"], collect["detail"]) == ("done", "2 sources saved, 1 not accessible, "
                                                             "1 with little running text")
    add_source(run, TEXT, orig_file="copies/S4.orig.html", text_note="little_running_text")
    assert run_status(run)["steps"][0]["detail"] == "3 sources saved, 1 not accessible, 2 with little running text"


def test_run_waits_for_the_person_at_a_checkpoint(tmp_path):
    run = make_run(tmp_path); add_source(run, TEXT)
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    st = run_status(run)
    assert st["next"] == "checkpoint_lenses" and st["waiting_for_person"] is True
    assert st["steps"][3]["detail"] == "waiting for your decision"
    store.record_checkpoint(run, "lenses", "test", "use firm-boundaries")
    st = run_status(run)
    assert st["steps"][3] == {"name": "checkpoint_lenses", "state": "done", "detail": "answered"}
    assert st["next"] == "interpret" and st["waiting_for_person"] is False
    assert st["steps"][4]["detail"] == "not written yet"


def test_finished_run_is_all_done(tmp_path):
    run = ready_run(tmp_path); build_report(run, LENSES)
    st = run_status(run, LENSES)
    assert set(states(st).values()) == {"done"} and st["next"] is None
    assert st["steps"][6]["detail"] == "report built" and st["steps"][4]["detail"] == "analysis written"


def test_a_report_older_than_the_analysis_is_not_done(tmp_path):
    run = ready_run(tmp_path); build_report(run, LENSES)
    stamp = (run / "analysis.json").stat().st_mtime
    os.utime(run / "report" / "report.html", (stamp - 100, stamp - 100))
    st = run_status(run, LENSES)
    assert states(st)["build"] == "pending" and st["steps"][6]["detail"] == "not built yet" and st["next"] == "build"


def test_an_open_gate_with_no_report_yet_is_pending_not_blocked(tmp_path):
    st = run_status(ready_run(tmp_path), LENSES)
    assert states(st)["build"] == "pending" and st["next"] == "build"


def test_gate_problems_block_the_build_step(tmp_path):
    run = ready_run(tmp_path, analysis=minimal_analysis(fact_ids=["F1", "F2"]))
    st = run_status(run, LENSES)
    assert states(st)["build"] == "blocked" and st["steps"][6]["detail"] == "1 problem" and st["next"] == "build"


def test_several_problems_are_counted_in_plural(tmp_path):
    run = ready_run(tmp_path, analysis=minimal_analysis(fact_ids=["F1", "F2"]))
    (run / "copies" / "S1.txt").write_text("changed afterwards, and now much shorter than before", encoding="utf-8")
    assert re.fullmatch(r"[2-9]\d* problems", run_status(run, LENSES)["steps"][6]["detail"])


def test_list_runs_newest_first_and_skips_other_folders(tmp_path):
    store.init_run(tmp_path, "older question", "demo", run_id="20261101-090000")
    store.init_run(tmp_path, "newer question", "demo", run_id="20261112-090000")
    (tmp_path / "notes").mkdir()
    runs = list_runs(tmp_path)
    assert [r["question"] for r in runs] == ["newer question", "older question"] and runs[0]["next"] == "collect"
    assert set(runs[0]) == {"run_dir", "run_id", "question", "mode", "illustrative", "practice", "next"}
    assert runs[0]["run_dir"] == str(tmp_path / "20261112-090000") and runs[0]["mode"] == "public"


def test_list_runs_skips_unreadable_runs_and_missing_roots(tmp_path):
    store.init_run(tmp_path, "fine", "demo", run_id="good")
    broken = tmp_path / "broken"; broken.mkdir(); (broken / "run.json").write_text("{not json", encoding="utf-8")
    not_a_run = tmp_path / "listy"; not_a_run.mkdir(); (not_a_run / "run.json").write_text("[]", encoding="utf-8")
    assert [r["run_id"] for r in list_runs(tmp_path)] == ["good"]
    assert list_runs(tmp_path / "does-not-exist") == []


def test_status_never_writes_to_a_run_folder(tmp_path):
    run = ready_run(tmp_path); build_report(run, LENSES)
    other = ready_run(tmp_path / "second", analysis=minimal_analysis(fact_ids=["F1", "F2"]))
    before = snapshot(tmp_path)
    run_status(run, LENSES); run_status(other, LENSES); run_status(other)
    list_runs(tmp_path); list_runs(tmp_path / "second")
    assert snapshot(tmp_path) == before


def test_known_problems_are_explained_in_plain_words():
    e = explain(Problem("analysis.json", "messages[0].chain[0].fact_ids", "rests on fact F2 with status rejected"))
    assert e == {"known": True, "what": "The analysis uses fact F2, but that fact was rejected.",
                 "why": "It was withdrawn, a quote was not found in its saved source, or the checker judged that the quote does not support it.",
                 "do": "Take F2 out of the analysis, or find a source that supports it and add it as a new fact."}
    e = explain(Problem("analysis.json", "calculations[0]", "result does not match its inputs (computed 6)"))
    assert e["known"] and e["why"] == "The program computed 6 from the facts listed for it."
    e = explain(Problem("sources/S2.json", "data_class", "a publishable report may use public sources only"))
    assert e["why"] == "Source S2 is licensed or internal."


def test_the_pinned_explanations_are_used_word_for_word():
    cases = {
        ("facts/F1.json", "quote not found in saved copy"): (
            "The quote for F1 is not in the saved copy of its source word for word.",
            "The quote was changed, shortened or written from memory, or the saved copy was changed afterwards.",
            "Take the exact wording from the saved copy and add it as a new fact."),
        ("sources/S1.json", "saved copy has changed"): (
            "The saved copy of source S1 is no longer the text that was saved.",
            "The file was edited or replaced after it was saved.",
            "Save the source again as a new source, add its facts again from the new copy, "
            "and take the old facts out of the analysis."),
        ("sources/S1.json", "saved copy is missing"): (
            "The saved copy of a source cannot be found.",
            "It was deleted or moved after it was saved.",
            "Save the source again as a new source, add its facts again from the new copy, "
            "and take the old facts out of the analysis."),
        ("analysis.json", "result does not match its inputs (computed 6)"): (
            "A total in the analysis does not match the figures it is built from.",
            "The program computed 6 from the facts listed for it.",
            "Use the program's figure, or correct the list of facts the total is built from."),
        ("sources/S2.json", "a publishable report may use public sources only"): (
            "This run contains a source that is not public, so its report cannot be published.",
            "Source S2 is licensed or internal.",
            "Build the report without the publishing option, or run the question again in public mode."),
        ("analysis.json", "analysis is missing"): (
            "The analysis has not been written yet.",
            "A report needs the key messages and their reasoning.",
            "Write the analysis once the facts are checked and the lenses are chosen."),
        ("run.json", "checkpoint lenses is not recorded"): (
            "A decision that is yours to make has not been recorded.",
            "The run stops twice for your decision: before the lenses are chosen and before the final report.",
            "Answer the open question for this run. The report is built after that."),
        ("facts/F3.json", "fact was never settled"): (
            "Fact F3 was proposed but never checked to the end.",
            "Either its quote check or its support check is missing.",
            "Run the checks for F3, then settle the facts again."),
    }
    for (file, message), (what, why, do) in cases.items():
        assert explain(Problem(file, None, message)) == {"known": True, "what": what, "why": why, "do": do}


def test_a_fact_that_is_not_rejected_gets_its_own_wording():
    rejected = explain(Problem("analysis.json", "x", "rests on fact F4 with status rejected"))
    proposed = explain(Problem("analysis.json", "x", "rests on fact F4 with status proposed"))
    missing = explain(Problem("analysis.json", "x", "rests on fact F9 with status missing"))
    assert proposed["known"] and proposed["what"] == "The analysis uses fact F4, but that fact has not been checked to the end."
    assert missing["known"] and missing["what"] == "The analysis uses fact F9, but that fact does not exist."
    assert len({rejected["what"].replace("F4", "F"), proposed["what"].replace("F4", "F"),
                missing["what"].replace("F9", "F")}) == 3


def test_unknown_problem_gets_the_generic_explanation():
    e = explain(Problem("facts/F3.json", "x", "something nobody planned for"))
    assert e["known"] is False and e["what"] == "The report could not be built because of a problem in facts/F3.json."
    assert e["why"] == "something nobody planned for"
    assert e["do"] == "Fix the named file or run the step that writes it again."


def test_explain_never_raises_on_an_unexpected_shape():
    for odd in (None, "text", 42, object(), Problem(None, None, None), Problem(7, ["x"], 3.5), Problem("a.json", None, "")):
        e = explain(odd)
        assert e["known"] is False and set(e) == {"known", "what", "why", "do"}
        assert all(isinstance(e[key], str) for key in ("what", "why", "do"))


def test_a_field_placeholder_is_filled_from_the_problem_and_never_raises(monkeypatch):
    from radar import explain as explain_module
    monkeypatch.setattr(explain_module, "_entries", lambda: (
        (re.compile("needs a name"), {"what": "The setting {field} is blank.", "why": "w", "do": "Fill in {field}."}),))
    assert explain(Problem("x.json", "company", "needs a name"))["what"] == "The setting company is blank."
    assert explain(Problem("x.json", "company", "needs a name"))["do"] == "Fill in company."
    for odd in (None, "", 7, ["x"]):
        e = explain(Problem("x.json", odd, "needs a name"))
        assert e["known"] and e["what"] == "The setting this setting is blank." and e["do"] == "Fill in this setting."


def test_braces_in_a_message_are_left_alone():
    e = explain(Problem("analysis.json", "x", "fact {id} does not exist"))
    assert e["known"] and "{id}" in e["what"]


def test_every_problem_the_checks_can_raise_is_known(tmp_path):
    run = ready_run(tmp_path, analysis=minimal_analysis(fact_ids=["F1", "F2"]))
    (run / "copies" / "S1.txt").write_text("changed afterwards, and now much shorter than before", encoding="utf-8")
    data = store.load_run(run); data["checkpoints"] = []; store.save_run(run, data)
    from radar.gate import gate
    problems = gate(run, LENSES, publishable=True)
    assert len(problems) >= 4 and all(explain(p)["known"] for p in problems)


# --- every fixed message in the code has an explanation ---------------------------------

def _module_constants(tree):
    return {node.targets[0].id: node.value.value for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)}


def _text_of(node, constants):
    """The text a message expression produces, with every inserted value shown as X1."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id]
    if isinstance(node, ast.JoinedStr):
        return "".join(part.value if isinstance(part, ast.Constant) else "X1" for part in node.values)
    return None


def _messages_in(path):
    """Every message the module hands to a Problem or a problems list, found by reading the code."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    constants = _module_constants(tree)
    nodes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            if name in ("add", "Problem") and len(node.args) >= 3:
                nodes.append(node.args[2])
            elif name == "append" and isinstance(node.func.value, ast.Name) and node.func.value.id == "problems":
                nodes.append(node.args[0])
            elif name == "CalcResult" and len(node.args) >= 3 and isinstance(node.args[2], ast.List):
                nodes.extend(node.args[2].elts)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "message" for t in node.targets):
            nodes.append(node.value)
    texts = {_text_of(node, constants) for node in nodes}
    texts.discard(None)
    return texts


def test_the_code_reading_helper_finds_the_known_messages():
    found = (_messages_in(ENGINE / "schema.py") | _messages_in(ENGINE / "schema_analysis.py")
             | _messages_in(ENGINE / "gate.py") | _messages_in(ENGINE / "calc.py"))
    for expected in (schema.EMPTY, schema.NOT_ALLOWED, schema.NOT_JSON, "run.json is missing", "analysis is missing",
                     "checkpoint X1 is not recorded", "whole is zero", "input X1 is not a settled capacity move",
                     "result does not match its inputs (computed X1)", "rests on fact X1 with status X1"):
        assert expected in found


def test_every_fixed_message_in_the_code_is_explained():
    unexplained = []
    for module in ("schema.py", "schema_analysis.py", "gate.py", "calc.py", "pack.py", "lenses.py",
                   "recommend.py", "projects.py"):
        for text in sorted(_messages_in(ENGINE / module)):
            if not explain(Problem("analysis.json", None, text))["known"]:
                unexplained.append(f"{module}: {text}")
    assert not unexplained, "add an entry to explanations_en.json for: " + "; ".join(unexplained)


def test_every_constant_message_is_explained():
    for text in (schema.EMPTY, schema.NOT_ALLOWED, schema.NOT_JSON, schema.AT_LEAST_ONE, schema.SCENARIO_COUNT,
                 schema.NOT_A_DATE, schema.NOT_A_PROBABILITY, schema.GROUPED_NUMBER, schema.DEMO_MARK_PROBLEM, schema_analysis.MUST_BE_LIST,
                 schema_analysis.MUST_BE_OBJECT, schema_analysis.MUST_BE_TEXT):
        assert explain(Problem("analysis.json", None, text))["known"], text


def _move(fact_id, size="2", unit="lines", status="confirmed"):
    return {"id": fact_id, "kind": "capacity_move", "status": status, "source_id": "S1",
            "fields": {"size_value": size, "size_unit": unit}}


def test_every_calculation_problem_is_explained():
    facts = {"F1": _move("F1"), "F2": _move("F2", unit="tonnes"), "F3": _move("F3", size="two"),
             "F4": _move("F4", status="rejected"), "F5": _move("F5", size="0")}
    calculations = [
        {"operation": "sum", "unit": "lines", "fact_ids": ["F1", "F1"]},
        {"operation": "sum", "unit": "lines", "fact_ids": ["F2"]},
        {"operation": "sum", "unit": "lines", "fact_ids": ["F3"]},
        {"operation": "sum", "unit": "lines", "fact_ids": ["F4"]},
        {"operation": "share", "unit": "lines", "fact_ids": ["F1"], "of_fact_ids": ["F5"]},
        {"operation": "share", "unit": "lines", "fact_ids": ["F5"], "of_fact_ids": ["F5"]},
        {"operation": "share", "unit": "lines", "fact_ids": ["F1"], "of_fact_ids": []},
        {"operation": "median", "unit": "lines", "fact_ids": ["F1"]},
        {"operation": "sum", "unit": "lines", "fact_ids": "F1"},
        {"operation": "share", "unit": "lines", "fact_ids": ["F1"], "of_fact_ids": "F1"},
        {"operation": "sum", "fact_ids": ["F1"]},
        {"operation": "sum", "unit": "lines", "fact_ids": ["F1", "F6"]},
    ]
    seen = set()
    for calculation in calculations:
        messages = calc.compute(calculation, facts, {"S1": {"type": "company_release"}}).problems
        assert messages, calculation
        seen.update(messages)
    assert len(seen) >= 11
    for message in seen:
        assert explain(Problem("analysis.json", "calculations[0]", message))["known"], message
    stated = explain(Problem("analysis.json", "calculations[0]", 'input F2 is stated in "tonnes", not "lines"'))
    assert "F2" in stated["what"]


# --- the wording rules --------------------------------------------------------------------

def _entries():
    return json.loads((ENGINE / "explanations_en.json").read_text(encoding="utf-8"))


# The one explanation that must say how a pack is named: the pack author handles that file, so it may say "file" and ".json".
PACK_FILE_KEY = pack.ID_FILE
PACK_FILE_ENDING = ".json"


def test_every_entry_has_three_short_plain_parts():
    programmer_words = r"\b(?:json|fields?|records?|schema|null|files?|csv|txt)\b|\.json|\.txt"
    for key, entry in _entries().items():
        assert set(entry) == {"what", "why", "do"}, key
        for part in ("what", "why", "do"):
            text = entry[part].replace("{field}", "X")   # the setting's name is filled in when the text is shown
            banned = programmer_words.replace("files?|", "") if part == "why" else programmer_words
            checked = text.replace(PACK_FILE_ENDING, "") if key == PACK_FILE_KEY else text   # one pack rule names its file
            if key == PACK_FILE_KEY:
                banned = banned.replace("files?|", "").replace(r"|\.json", "")
            assert text and not re.search(banned, checked, re.IGNORECASE), (key, part, text)
            assert len(re.findall(r"[.!?](?:\s|$)", text)) <= 2, (key, part, text)
            assert len(text.split()) <= 32, (key, part, text)


# --- the command ----------------------------------------------------------------------------

def run_command(capsys, *argv):
    from radar.cli import main
    code = main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_status_command_prints_one_run(tmp_path, capsys):
    code, out = run_command(capsys, "status", "--run", str(make_run(tmp_path)))
    assert code == 0 and out["next"] == "collect" and [s["name"] for s in out["steps"]] == ORDER


def test_status_command_lists_the_runs_of_a_folder(tmp_path, capsys):
    store.init_run(tmp_path, "older question", "demo", run_id="20261101-090000")
    store.init_run(tmp_path, "newer question", "demo", run_id="20261112-090000")
    code, out = run_command(capsys, "status", "--root", str(tmp_path))
    assert code == 0 and [r["question"] for r in out["runs"]] == ["newer question", "older question"]


def test_status_command_needs_exactly_one_of_run_and_root(tmp_path, capsys):
    assert run_command(capsys, "status")[0] == 2
    assert run_command(capsys, "status", "--run", str(tmp_path), "--root", str(tmp_path))[0] == 2
    assert run_command(capsys, "status", "--run", str(tmp_path / "nothing"))[0] == 2


def test_gate_command_explains_each_problem_in_order(tmp_path, capsys):
    run = ready_run(tmp_path, analysis=minimal_analysis(fact_ids=["F1", "F2"]))
    code, out = run_command(capsys, "gate", "--run", str(run), "--lenses", str(LENSES))
    assert code == 1 and len(out["problems"]) == len(out["explained"]) == 1
    assert out["problems"][0]["message"] == "rests on fact F2 with status rejected"
    assert out["explained"][0]["what"] == "The analysis uses fact F2, but that fact was rejected."


def test_build_report_command_explains_what_stopped_it(tmp_path, capsys):
    run = ready_run(tmp_path, analysis=minimal_analysis(fact_ids=["F1", "F2"]))
    code, out = run_command(capsys, "build-report", "--run", str(run), "--lenses", str(LENSES))
    assert code == 1 and out["built"] == [] and out["explained"][0]["known"] is True


def test_gate_command_for_an_open_gate_has_no_explanations(tmp_path, capsys):
    code, out = run_command(capsys, "gate", "--run", str(ready_run(tmp_path)), "--lenses", str(LENSES))
    assert code == 0 and out == {"open": True, "problems": [], "explained": []}


def test_a_supporting_quote_and_a_hand_written_reason_have_their_own_explanations():
    e = explain(Problem("facts/F2.json", "supporting[0].quote", "supporting quote not found in saved copy"))
    assert e["known"] and e["what"] == "A supporting quote for F2 is not in the saved copy of its source word for word."
    e = explain(Problem("facts/F2.json", "status_reason", "reason does not follow from the checks"))
    assert e["known"] and e["what"] == "The reason given for the status of fact F2 does not match its checks."



# --- final fix I8: a report counts as built only while nothing it rests on has changed -----------

def test_a_saved_copy_edited_after_the_build_means_the_report_is_not_built(tmp_path):
    run = ready_run(tmp_path); build_report(run, LENSES)
    assert states(run_status(run, LENSES))["build"] == "done"
    copy = run / "copies" / "S1.txt"
    copy.write_text(copy.read_text(encoding="utf-8").replace("2028", "2031"), encoding="utf-8")
    assert states(run_status(run, LENSES))["build"] != "done"


def test_a_fact_changed_after_the_build_means_the_report_is_not_built(tmp_path):
    run = ready_run(tmp_path); build_report(run, LENSES)
    stamp = (run / "report" / "report.html").stat().st_mtime
    os.utime(run / "facts" / "F2.json", (stamp + 10, stamp + 10))   # touched: the gate still passes
    from radar.gate import gate
    assert gate(run, LENSES) == []
    st = run_status(run, LENSES)
    assert states(st)["build"] == "pending" and st["steps"][6]["detail"] == "not built yet"


def test_each_input_of_the_report_counts_for_its_age(tmp_path):
    run = ready_run(tmp_path); build_report(run, LENSES)
    stamp = (run / "report" / "report.html").stat().st_mtime
    store.write_changes(run, {"facts_digest": "x"})
    os.utime(run / "changes.json", (stamp - 10, stamp - 10))
    assert states(run_status(run, LENSES))["build"] != "done"        # the gate refuses the comparison
    (run / "changes.json").unlink()
    for name in ("run.json", "sources/S1.json"):
        os.utime(run / "report" / "report.html", (stamp, stamp))
        os.utime(run / name, (stamp + 10, stamp + 10))
        assert states(run_status(run, LENSES))["build"] == "pending", name
        os.utime(run / name, (stamp - 10, stamp - 10))
    assert states(run_status(run, LENSES))["build"] == "done"


def test_a_recommendation_recorded_after_the_build_means_the_report_is_not_built(tmp_path):
    from radar import recommend
    run = ready_run(tmp_path); build_report(run, LENSES)
    assert states(run_status(run, LENSES))["build"] == "done"
    entry = {"lens": "firm-boundaries", "question_part": "adds capacity", "why": "Two lines for one customer.",
             "facts": ["F1"], "missing": "Nothing found."}
    recommend.record_recommendation(run, LENSES, [entry], None, recommend.ADVISOR)
    stamp = (run / "report" / "report.html").stat().st_mtime
    os.utime(run / recommend.RECORD, (stamp + 10, stamp + 10))
    from radar.gate import gate
    assert gate(run, LENSES) == []   # the gate does not stop on a recommendation: only the report is out of date
    st = run_status(run, LENSES)
    assert states(st)["build"] == "pending" and st["steps"][6]["detail"] == "not built yet" and st["next"] == "build"
    build_report(run, LENSES)
    newer = (run / recommend.RECORD).stat().st_mtime + 10
    os.utime(run / "report" / "report.html", (newer, newer))   # the rebuilt report is newer than everything
    assert states(run_status(run, LENSES))["build"] == "done"
    recommend.record_recommendation(run, LENSES, [entry], None, recommend.ADVISOR)   # recorded again
    os.utime(run / recommend.RECORD, (newer + 10, newer + 10))
    assert states(run_status(run, LENSES))["build"] == "pending"


def test_a_grouping_recorded_after_the_report_makes_the_report_out_of_date(tmp_path):
    from radar import projects
    run = ready_run(tmp_path); build_report(run, LENSES)
    assert states(run_status(run, LENSES))["build"] == "done"
    grouping = [{"name": f"Move {fact_id}", "fact_ids": [fact_id]} for fact_id in projects.moves(run)]
    projects.record_projects(run, grouping, projects.GROUPER)
    stamp = (run / "report" / "report.html").stat().st_mtime
    os.utime(run / projects.RECORD, (stamp + 10, stamp + 10))
    from radar.gate import gate
    assert gate(run, LENSES) == []   # the gate does not stop on a grouping: only the report is out of date
    st = run_status(run, LENSES)
    assert states(st)["build"] == "pending" and st["next"] == "build" and st["grouping"] == "grouped"
    build_report(run, LENSES)
    newer = stamp + 20
    os.utime(run / "report" / "report.html", (newer, newer))
    assert states(run_status(run, LENSES))["build"] == "done"


# --- which sources still have to be read ---------------------------------------------------

def _step(status, name):
    return next(step for step in status["steps"] if step["name"] == name)


def test_a_source_nobody_has_read_keeps_extract_in_progress(tmp_path):
    run = make_run(tmp_path); add_source(run, TEXT); add_source(run, TEXT)      # S1, S2
    store.new_fact(run, proposal(source_id="S1"))
    status = run_status(run)
    assert status["sources_to_read"] == ["S2"]
    assert _step(status, "extract")["state"] == "in_progress"
    assert _step(status, "extract")["detail"] == "1 fact proposed, 1 source still to read"
    assert status["next"] == "extract"


def test_extract_is_pending_while_nothing_has_been_read(tmp_path):
    run = make_run(tmp_path)
    assert run_status(run)["sources_to_read"] == []
    assert _step(run_status(run), "extract")["state"] == "pending"
    add_source(run, TEXT); add_source(run, TEXT)
    status = run_status(run)
    assert status["sources_to_read"] == ["S1", "S2"]
    assert _step(status, "extract")["state"] == "pending"
    assert _step(status, "extract")["detail"] == "0 facts proposed, 2 sources still to read"
    assert status["next"] == "extract"


def test_a_source_read_without_a_fact_is_marked_through_log_excluded(tmp_path):
    run = make_run(tmp_path); add_source(run, TEXT); add_source(run, TEXT)
    store.new_fact(run, proposal(source_id="S1"))
    store.log_excluded(run, "Source S2", "Read in full; nothing on this question.", source_id="S2")
    status = run_status(run)
    assert status["sources_to_read"] == []
    assert _step(status, "extract")["state"] == "done"
    assert _step(status, "extract")["detail"] == "1 fact proposed, 0 sources still to read"


def test_a_source_used_only_as_a_supporting_quote_counts_as_read(tmp_path):
    run = make_run(tmp_path); add_source(run, TEXT); add_source(run, TEXT)
    store.new_fact(run, proposal(source_id="S1", supporting=[
        {"source_id": "S2", "quote": "adds two high-speed syringe lines for customers"}]))
    assert run_status(run)["sources_to_read"] == []
    assert _step(run_status(run), "extract")["state"] == "done"


def test_a_source_whose_only_fact_was_withdrawn_still_counts_as_read(tmp_path):
    run = make_run(tmp_path); add_source(run, TEXT)
    fact = store.new_fact(run, proposal(source_id="S1"))
    verify.withdraw_fact(run, fact["id"], "Duplicate.")
    assert run_status(run)["sources_to_read"] == []


def test_a_source_that_could_not_be_saved_is_not_waited_for(tmp_path):
    run = make_run(tmp_path); add_source(run, TEXT)
    add_source(run, "", access="not_accessible", access_reason="http_403", copy_file=None, copy_sha256=None)
    store.new_fact(run, proposal(source_id="S1"))
    status = run_status(run)
    assert status["sources_to_read"] == [] and _step(status, "extract")["state"] == "done"


def test_only_not_accessible_sources_leave_extract_pending(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "", access="not_accessible", access_reason="http_403", copy_file=None, copy_sha256=None)
    assert _step(run_status(run), "extract")["state"] == "pending"


def test_sources_to_read_are_listed_in_id_order(tmp_path):
    run = make_run(tmp_path)
    for _ in range(11):
        add_source(run, TEXT)
    store.new_fact(run, proposal(source_id="S3"))
    assert run_status(run)["sources_to_read"] == ["S1", "S2"] + [f"S{n}" for n in range(4, 12)]


def test_a_run_whose_sources_hold_no_fact_moves_past_verify(tmp_path):
    run = make_run(tmp_path); add_source(run, TEXT)
    store.log_excluded(run, "Source S1", "Read in full; nothing on this question.", source_id="S1")
    status = run_status(run)
    assert _step(status, "extract")["state"] == "done"
    assert _step(status, "verify") == {"name": "verify", "state": "done", "detail": "no facts to check"}
    assert status["next"] == "checkpoint_lenses"


def test_verify_stays_pending_without_facts_while_a_source_is_unread(tmp_path):
    run = make_run(tmp_path); add_source(run, TEXT)
    status = run_status(run)
    assert _step(status, "verify")["state"] == "pending" and status["next"] == "extract"


def test_an_excluded_entry_without_a_source_does_not_count_as_read(tmp_path):
    run = make_run(tmp_path); add_source(run, TEXT)
    store.log_excluded(run, "a blog post", "no named author")
    assert run_status(run)["sources_to_read"] == ["S1"]


def test_a_hand_edited_excluded_list_cannot_break_status(tmp_path):
    run = make_run(tmp_path); add_source(run, TEXT)
    data = store.load_run(run)
    data["excluded"] = ["text", {"source_id": 7}, {"source_id": ["S1"]}, {"source_id": "S1"}]
    store.save_run(run, data)
    assert run_status(run)["sources_to_read"] == []
    data["excluded"] = "not a list"
    store.save_run(run, data)
    assert run_status(run)["sources_to_read"] == ["S1"]


def test_the_demo_run_has_no_source_left_to_read(tmp_path):
    run = build_demo_run(tmp_path)
    assert run_status(run)["sources_to_read"] == []


def test_status_with_unread_sources_still_never_writes(tmp_path):
    run = make_run(tmp_path); add_source(run, TEXT); add_source(run, TEXT)
    store.new_fact(run, proposal(source_id="S1"))
    store.log_excluded(run, "Source S2", "nothing here", source_id="S2")
    other = make_run(tmp_path / "second"); add_source(other, TEXT)
    before = snapshot(tmp_path)
    assert run_status(run)["sources_to_read"] == [] and run_status(other)["sources_to_read"] == ["S1"]
    list_runs(tmp_path); list_runs(tmp_path / "second")
    assert snapshot(tmp_path) == before


def test_the_data_check_names_an_excluded_entry_with_an_unknown_source(tmp_path):
    run = make_run(tmp_path); add_source(run, TEXT)
    store.log_excluded(run, "Source S1", "nothing", source_id="S1")
    data = store.load_run(run)
    data["excluded"].append({"what": "Source S9", "why": "nothing", "source_id": "S9"})
    store.save_run(run, data)
    problems = [p for p in schema.check_data(run) if p.file == "run.json"]
    assert problems == [Problem("run.json", "excluded[1].source_id", "source S9 does not exist")]
    assert explain(problems[0])["known"]


def test_the_data_check_still_accepts_an_older_excluded_entry_without_a_source(tmp_path):
    run = make_run(tmp_path); add_source(run, TEXT)
    store.log_excluded(run, "a blog post", "no named author")
    assert [p for p in schema.check_data(run) if p.file == "run.json"] == []


def test_an_excluded_source_id_that_is_not_text_is_named_and_never_raises(tmp_path):
    from radar.gate import gate
    run = make_run(tmp_path); add_source(run, TEXT)
    for bad in (["S1"], {"id": "S1"}, 7, None):
        data = store.load_run(run)
        data["excluded"] = [{"what": "w", "why": "y", "source_id": bad}]
        store.save_run(run, data)
        expected = [Problem("run.json", "excluded[0].source_id", "must be text")]
        assert [p for p in schema.check_data(run) if p.file == "run.json"] == expected, bad
        assert [p for p in gate(run) if p.field == "excluded[0].source_id"] == expected, bad
        assert explain(expected[0])["known"]
        run_status(run)   # status must not raise either


def test_an_inaccessible_source_named_by_a_fact_does_not_count_as_reading_the_accessible_one(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "", access="not_accessible", access_reason="http_403", copy_file=None, copy_sha256=None)   # S1
    add_source(run, TEXT)                                                                                       # S2
    store.new_fact(run, proposal(source_id="S1"))
    status = run_status(run)
    assert status["sources_to_read"] == ["S2"] and _step(status, "extract")["state"] == "pending"


# --- Task 9 (carried over): a temporary file left behind by a killed write changes nothing ----------------------

def _leave_temporary_files(run, newer_than):
    """A `.F3.json.ab12.tmp` in facts/ and a `.S9.json.cd34.tmp` in sources/, each a copy of a real record, newer
    than the report, as a write killed after the report was built would leave them."""
    left = []
    for folder, name, record in (("facts", ".F3.json.ab12.tmp", "F1.json"), ("sources", ".S9.json.cd34.tmp", "S1.json")):
        path = run / folder / name
        path.write_bytes((run / folder / record).read_bytes())
        os.utime(path, (newer_than + 50, newer_than + 50))
        left.append(path)
    return left


def test_a_leftover_temporary_file_changes_nothing_in_status_data_check_gate_and_report(tmp_path, capsys):
    from radar.gate import gate
    run = ready_run(tmp_path)
    build_report(run, LENSES)
    report = run / "report"
    kept = {path.name: path.read_bytes() for path in report.iterdir()}
    stamp = (report / "report.html").stat().st_mtime
    expected = (run_status(run, LENSES), schema.check_data(run, LENSES), gate(run, LENSES),
                store.read_facts(run), store.read_sources(run), store.next_id(run, "F"), store.next_id(run, "S"))
    assert states(expected[0])["build"] == "done" and expected[1] == [] and expected[2] == []

    left = _leave_temporary_files(run, stamp)
    assert all(path.exists() for path in left)
    assert (run_status(run, LENSES), schema.check_data(run, LENSES), gate(run, LENSES),
            store.read_facts(run), store.read_sources(run),
            store.next_id(run, "F"), store.next_id(run, "S")) == expected
    assert main_status(run, capsys) == expected[0]            # the command prints the same

    build_report(run, LENSES)
    assert {path.name: path.read_bytes() for path in report.iterdir()} == kept
    assert all(path.exists() for path in left)                 # nothing was removed or renamed


def main_status(run, capsys):
    from radar.cli import main
    capsys.readouterr()
    assert main(["status", "--run", str(run), "--lenses", str(LENSES)]) == 0
    return json.loads(capsys.readouterr().out)


def test_a_hidden_file_in_the_record_folders_does_not_make_the_report_stale(tmp_path):
    run = ready_run(tmp_path)
    build_report(run, LENSES)
    stamp = (run / "report" / "report.html").stat().st_mtime
    for folder in ("facts", "sources"):
        hidden = run / folder / ".DS_Store"
        hidden.write_bytes(b"x")
        os.utime(hidden, (stamp + 50, stamp + 50))
    assert states(run_status(run, LENSES))["build"] == "done"


# --- Part A fix A1, ruling HG6: status does not trust a stored status that no longer follows from the checks ---

SETTLED_DEMO = "6 confirmed, 1 uncertain, 3 rejected, 0 still to check"


def assert_settle_again(st, detail):
    assert st["steps"][2] == {"name": "verify", "state": "in_progress", "detail": detail}
    assert st["next"] == "verify" and st["waiting_for_person"] is False


def test_a_withdrawal_that_was_not_settled_sends_the_run_back_to_verify(tmp_path):
    run = build_demo_run(tmp_path, stage="checked")
    st = run_status(run)
    assert st["steps"][2]["detail"] == SETTLED_DEMO and st["next"] == "checkpoint_lenses"
    verify.withdraw_fact(run, "F1", "the release was retracted")     # an interrupted run: no settle afterwards
    assert_settle_again(run_status(run), SETTLED_DEMO + "; 1 fact must be settled again")
    verify.settle(run)
    st = run_status(run)
    assert st["steps"][2] == {"name": "verify", "state": "done",
                              "detail": "5 confirmed, 1 uncertain, 4 rejected, 0 still to check"}
    assert st["next"] == "checkpoint_lenses" and st["waiting_for_person"] is True


def two_source_run(tmp_path):
    """F1 is confirmed only because S2, a second and independent source, also holds it."""
    run = make_run(tmp_path)
    add_source(run, TEXT, publisher="Competitor A")
    add_source(run, "Competitor A confirmed two new syringe lines will open in 2028, the paper reported.",
               publisher="Trade Paper")
    add_fact(run, source_id="S1", primary_source=False, quote="adds two high-speed syringe lines for customers",
             supporting=[{"source_id": "S2", "quote": "two new syringe lines will open in 2028"}])
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    assert run_status(run)["next"] == "checkpoint_lenses"
    return run


def test_a_link_between_sources_that_was_not_settled_sends_the_run_back_to_verify(tmp_path):
    run = two_source_run(tmp_path)
    store.add_based_on(run, "S2", "S1")
    assert_settle_again(run_status(run), "1 confirmed, 0 uncertain, 0 rejected, 0 still to check; "
                                         "1 fact must be settled again")
    verify.settle(run)
    st = run_status(run)
    assert st["steps"][2]["state"] == "done" and st["next"] == "checkpoint_lenses"


def test_a_fresh_verdict_that_was_not_settled_sends_the_run_back_to_verify(tmp_path):
    run = two_source_run(tmp_path)
    verify.record_support(run, "F1", False, "support-checker", "the paper names another site")
    assert_settle_again(run_status(run), "1 confirmed, 0 uncertain, 0 rejected, 0 still to check; "
                                         "1 fact must be settled again")
    assert verify.settle(run) == {"F1": "rejected"}
    assert states(run_status(run))["verify"] == "done"


def test_several_facts_to_settle_again_are_counted_in_plural_and_a_broken_record_never_breaks_status(tmp_path):
    run = build_demo_run(tmp_path, stage="checked")
    verify.withdraw_fact(run, "F1", "retracted"); verify.withdraw_fact(run, "F2", "retracted")
    assert run_status(run)["steps"][2]["detail"].endswith("; 2 facts must be settled again")
    fact = store.read_facts(run)["F3"]; fact["checks"] = ["not", "an", "object"]; store.write_fact(run, fact)
    assert run_status(run)["steps"][2]["detail"].endswith("; 3 facts must be settled again")


# --- Part A fix A1, M7: the practice-mark explanation never tells the person to remove the mark ------------------

def test_the_practice_mark_explanation_says_to_build_again_or_start_a_new_run():
    explained = explain(Problem("run.json", store.DEMO_MARK, schema.DEMO_MARK_PROBLEM))
    assert explained["do"] == ("Build the practice run again with the demo command, "
                               "or start a new run for your own material.")
    assert "settings" not in explained["do"] and "mark out" not in explained["do"]


# --- Part A fix A2, item 5: the run list says what kind of run each is ------------------------------------------

def test_the_run_list_says_whether_each_run_is_illustrative_and_whether_it_is_the_practice_run(tmp_path, capsys):
    from radar.demo import build_demo_run
    store.init_run(tmp_path, "a real question", "acme", run_id="real")
    store.init_run(tmp_path, "an invented question", "demo", run_id="invented", illustrative=True)
    build_demo_run(tmp_path, private=True, stage="sources")
    odd = store.init_run(tmp_path, "edited by hand", "demo", run_id="odd")
    run = store.load_run(odd); run["illustrative"] = "yes"; store.save_run(odd, run)   # only true counts
    kinds = {entry["run_id"]: (entry["illustrative"], entry["practice"]) for entry in list_runs(tmp_path)}
    assert kinds == {"real": (False, False), "invented": (True, False), "demo-private": (True, True),
                     "odd": (False, False)}
    code, out = run_command(capsys, "status", "--root", str(tmp_path))
    assert code == 0
    for entry in out["runs"]:
        assert list(entry) == ["run_dir", "run_id", "question", "mode", "illustrative", "practice", "next"]
        assert (entry["illustrative"], entry["practice"]) == kinds[entry["run_id"]]


# --- fix wave A23.16: no explanation suggests a private run; the plugin never brings private mode up -----------------

def test_no_explanation_suggests_starting_a_private_run():
    for key, entry in _entries().items():   # what to do never points to a private run; why may say what one is for
        assert "private run" not in entry["do"].lower(), (key, entry["do"])


def test_the_two_refusals_say_what_can_be_done_in_a_public_run():
    entries = _entries()
    compared = entries["a public run may not be compared with a run that holds non-public material"]["do"]
    assert "earlier public run" in compared and "without" in compared
    held = entries["non-public source in a public run"]["do"]
    assert "anyone can read" in held


def test_a_link_between_sources_that_changes_only_the_codes_sends_the_run_back_to_verify(tmp_path):
    from radar.gate import REASONS_DO_NOT_FOLLOW, gate
    run = make_run(tmp_path)
    add_source(run, TEXT, publisher="Competitor A")
    add_source(run, "Competitor A confirmed two new syringe lines will open in 2028, the paper reported.",
               publisher="Trade Paper")
    add_fact(run, source_id="S1", primary_source=False, certainty="tentative", tentative_reason="one report only",
             quote="adds two high-speed syringe lines for customers",
             supporting=[{"source_id": "S2", "quote": "two new syringe lines will open in 2028"}])
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    assert store.read_facts(run)["F1"]["uncertain_reasons"] == ["tentative"]
    store.add_based_on(run, "S2", "S1")   # the status and its reason stay; only the codes change
    fact = store.read_facts(run)["F1"]
    assert (fact["status"], fact["uncertain_reasons"]) == ("uncertain", ["tentative"])
    assert Problem("facts/F1.json", "uncertain_reasons", REASONS_DO_NOT_FOLLOW) in gate(run)
    assert_settle_again(run_status(run), "0 confirmed, 1 uncertain, 0 rejected, 0 still to check; "
                                         "1 fact must be settled again")
    verify.settle(run)
    assert store.read_facts(run)["F1"]["uncertain_reasons"] == ["tentative", "single_source"]
    assert not [p for p in gate(run) if p.field == "uncertain_reasons"]
    assert run_status(run)["steps"][2]["state"] == "done"
