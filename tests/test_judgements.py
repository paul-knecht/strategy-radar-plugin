from decimal import Decimal
from radar.calc import parse_number, compute as compute_with_sources
from radar.schema import check_data, Problem
from radar.gate import gate
from radar import store
from helpers import make_run, add_source, add_fact, finish_run, minimal_analysis

TEXT = ("Competitor A adds two syringe lines in 2028. Competitor B adds four syringe lines in 2028. "
        "Competitor C invests 300 million euros in a new site for its customers.")

def compute(calculation, facts):
    """`radar.calc.compute` with an ordinary source record for every fact (a fact without a source gets S1)."""
    for fact in facts.values():
        if isinstance(fact, dict):
            fact.setdefault("source_id", "S1")
    sources = {fact["source_id"]: {"type": "company_release"} for fact in facts.values()
               if isinstance(fact, dict) and isinstance(fact["source_id"], str)}
    return compute_with_sources(calculation, facts, sources)

def three_moves(tmp_path, **f3_over):
    run = make_run(tmp_path)
    add_source(run, TEXT)
    add_fact(run, source_id="S1", primary_source=True, quote="Competitor A adds two syringe lines in 2028",
             fields={"company": "Competitor A", "size_value": "2", "size_unit": "lines"})
    add_fact(run, source_id="S1", primary_source=True, quote="Competitor B adds four syringe lines in 2028",
             fields={"company": "Competitor B", "size_value": "4", "size_unit": "Lines"})
    add_fact(run, source_id="S1", primary_source=True, quote="Competitor C invests 300 million euros in a new site",
             fields={"company": "Competitor C", "size_value": "300", "size_unit": "EUR million"}, **f3_over)
    return run

def calc(operation, fact_ids, of=(), unit="lines", result="0"):
    return {"id": "C1", "label": "Lines announced for 2028", "operation": operation, "unit": unit,
            "fact_ids": list(fact_ids), "of_fact_ids": list(of), "result": result}

def test_parse_number_accepts_only_plain_numbers():
    assert parse_number("2") == Decimal("2") and parse_number("2.5") == Decimal("2.5")
    for bad in ("1,200", "1.200.000", "about 2", "2 lines", "", None):
        assert parse_number(bad) is None


# --- final fix I1: a grouped number is never read as a decimal ----------------------------------

def test_a_grouped_number_is_never_parsed():
    for grouped in ("1.200", "1,200", "1.200.000", "12.500", "999,999"):
        assert parse_number(grouped) is None, grouped
    assert parse_number("1.5") == Decimal("1.5") and parse_number("1200") == Decimal("1200")
    assert parse_number("1.2000") == Decimal("1.2000")     # four digits after the point is no grouping


def test_check_data_names_a_grouped_size(tmp_path):
    for grouped in ("1.200", "1,200", "1.200.000"):
        run = make_run(tmp_path / grouped)
        add_source(run, TEXT)
        add_fact(run, source_id="S1", quote="Competitor A adds two syringe lines in 2028", fields={"size_value": grouped})
        assert Problem("facts/F1.json", "fields.size_value", "write the number without thousands separators") \
            in check_data(run), grouped
    for plain in ("1.5", "1200"):
        run = make_run(tmp_path / plain)
        add_source(run, TEXT)
        add_fact(run, source_id="S1", quote="Competitor A adds two syringe lines in 2028", fields={"size_value": plain})
        assert check_data(run) == [], plain


def test_the_gate_refuses_a_sum_over_a_grouped_number(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "Competitor A builds a warehouse of 1.200 square metres. Competitor B builds one of 800 square metres.")
    add_fact(run, source_id="S1", primary_source=True, quote="Competitor A builds a warehouse of 1.200 square metres",
             fields={"size_value": "1.200", "size_unit": "square metres"})
    add_fact(run, source_id="S1", primary_source=True, quote="Competitor B builds one of 800 square metres",
             fields={"company": "Competitor B", "size_value": "800", "size_unit": "square metres"})
    analysis = minimal_analysis(fact_ids=["F1"])
    analysis["calculations"] = [calc("sum", ["F1", "F2"], unit="square metres", result="801.2")]
    finish_run(run, ["F1"], analysis=analysis)
    problems = gate(run)
    assert Problem("facts/F1.json", "fields.size_value", "write the number without thousands separators") in problems
    assert Problem("analysis.json", "calculations[0]", "input F1 has no plain number") in problems

def test_sum_of_same_unit_ignores_case_of_the_unit(tmp_path):
    run = three_moves(tmp_path); finish_run(run, ["F1"])
    r = compute(calc("sum", ["F1", "F2"]), store.read_facts(run))
    assert (r.value, r.includes_uncertain, r.problems) == ("6", False, [])

def test_sum_refuses_mixed_units(tmp_path):
    run = three_moves(tmp_path); finish_run(run, ["F1"])
    r = compute(calc("sum", ["F1", "F3"]), store.read_facts(run))
    assert r.value is None and r.problems == ['input F3 is stated in "EUR million", not "lines"']

def test_share_is_a_whole_percent_of_the_whole(tmp_path):
    run = three_moves(tmp_path); finish_run(run, ["F1"])
    facts = store.read_facts(run)
    assert compute(calc("share", ["F1"], of=["F1", "F2"]), facts).value == "33"
    assert compute(calc("share", ["F1"], of=["F2"]), facts).problems == ["share inputs must be part of the whole"]

def test_count_and_uncertain_flag(tmp_path):
    run = three_moves(tmp_path, certainty="tentative", tentative_reason="one unnamed source"); finish_run(run, ["F1"])
    r = compute(calc("count", ["F1", "F2", "F3"], unit=None), store.read_facts(run))
    assert (r.value, r.includes_uncertain) == ("3", True)

def test_rejected_fact_cannot_be_an_input(tmp_path):
    run = three_moves(tmp_path)
    add_fact(run, source_id="S1", primary_source=True, quote="Competitor D adds nine syringe lines in 2028",
             fields={"company": "Competitor D", "size_value": "9", "size_unit": "lines"})
    finish_run(run, ["F1"])
    assert compute(calc("sum", ["F1", "F4"]), store.read_facts(run)).problems == ["input F4 is not a settled capacity move"]

def test_gate_refuses_a_total_that_does_not_match(tmp_path):
    run = three_moves(tmp_path)
    analysis = minimal_analysis(fact_ids=["F1"]); analysis["calculations"] = [calc("sum", ["F1", "F2"], result="7")]
    finish_run(run, ["F1"], analysis=analysis)
    assert gate(run) == [Problem("analysis.json", "calculations[0]", "result does not match its inputs (computed 6)")]
    analysis["calculations"][0]["result"] = "6"; store.write_analysis(run, analysis)
    assert gate(run) == []

def test_scenarios_need_two_to_four_and_existing_assumptions(tmp_path):
    run = three_moves(tmp_path)
    analysis = minimal_analysis(fact_ids=["F1"])
    analysis["assumptions"] = [{"id": "A1", "text": "Demand keeps growing", "support": "partial", "if_wrong": "Capacity stays unused", "fact_ids": []}]
    analysis["scenarios"] = [{"id": "SC1", "name": "Tight market", "description": "Demand outruns supply",
                              "assumption_ids": ["A1", "A9"], "signposts": [{"text": "Lead times rise", "fact_ids": []}]}]
    finish_run(run, ["F1"], analysis=analysis)
    problems = check_data(run)
    assert Problem("analysis.json", "scenarios", "use no scenarios or between two and four") in problems
    assert Problem("analysis.json", "scenarios[0].assumption_ids", "assumption A9 does not exist") in problems

def test_prediction_needs_a_date_and_a_probability(tmp_path):
    run = three_moves(tmp_path)
    analysis = minimal_analysis(fact_ids=["F1"])
    analysis["predictions"] = [{"id": "P1", "message_id": "M1", "statement": "Both lines operate by the end of 2028",
                                "by": "end of 2028", "resolves_when": "The company reports them as operating", "probability": 100}]
    finish_run(run, ["F1"], analysis=analysis)
    problems = check_data(run)
    assert Problem("analysis.json", "predictions[0].by", "must be a date like 2027-12-31") in problems
    assert Problem("analysis.json", "predictions[0].probability", "must be a whole number from 1 to 99") in problems

# --- beyond the brief: arithmetic edge cases -------------------------------------------------

def facts_with(*sizes, unit="lines"):
    """Settled capacity moves F1.. with the given size values."""
    return {f"F{i}": {"id": f"F{i}", "kind": "capacity_move", "status": "confirmed",
                      "fields": {"size_value": value, "size_unit": unit}}
            for i, value in enumerate(sizes, start=1)}

def test_decimals_are_exact_and_written_without_trailing_zeros():
    facts = facts_with("1.5", "1.0", "0.1", "0.2", "300", "200", "0", "0.0")
    assert compute(calc("sum", ["F1", "F2"]), facts).value == "2.5"
    assert compute(calc("sum", ["F3", "F4"]), facts).value == "0.3"   # a float would give 0.30000000000000004
    assert compute(calc("sum", ["F5", "F6"]), facts).value == "500"   # never 5E+2
    assert compute(calc("sum", ["F7", "F8"]), facts).value == "0"

def test_share_rounds_half_up():
    facts = facts_with("1", "7", "1", "39", "2", "3")
    assert compute(calc("share", ["F1"], of=["F1", "F2"]), facts).value == "13"   # 12.5
    assert compute(calc("share", ["F3"], of=["F3", "F4"]), facts).value == "3"    # 2.5
    assert compute(calc("share", ["F5"], of=["F5", "F6"]), facts).value == "40"
    assert compute(calc("share", ["F5", "F6"], of=["F5", "F6"]), facts).value == "100"

def test_share_with_a_whole_of_zero():
    r = compute(calc("share", ["F1"], of=["F1", "F2"]), facts_with("0", "0"))
    assert (r.value, r.problems) == (None, ["whole is zero"])

def test_count_ignores_the_unit_and_needs_no_numbers():
    facts = {"F1": {"status": "confirmed", "kind": "capacity_move", "fields": {}},
             "F2": {"status": "uncertain", "kind": "capacity_move", "fields": None}}
    r = compute(calc("count", ["F1", "F2"], unit=None), facts)
    assert (r.value, r.includes_uncertain, r.problems) == ("2", True, [])

def test_general_proposed_and_unknown_facts_are_not_settled_capacity_moves():
    facts = {"F1": {"status": "confirmed", "kind": "general", "fields": None},
             "F2": {"status": "proposed", "kind": "capacity_move", "fields": {}}}
    r = compute(calc("count", ["F1", "F2", "F9"], unit=None), facts)
    assert r.value is None
    assert r.problems == ["input F1 is not a settled capacity move", "input F2 is not a settled capacity move",
                          "input F9 is not a settled capacity move"]

def test_a_repeated_input_is_a_problem_not_a_double_count():
    facts = facts_with("2", "4")
    twice = "input F1 is listed more than once"
    for operation, ids, whole in (("sum", ["F1", "F1"], ()), ("count", ["F1", "F1"], ()),
                                  ("share", ["F1", "F1"], ["F1", "F2"]), ("share", ["F1"], ["F1", "F1", "F2"])):
        r = compute(calc(operation, ids, of=whole), facts)
        assert (r.value, r.problems) == (None, [twice]), operation
    both = compute(calc("share", ["F1", "F1"], of=["F1", "F1", "F2"]), facts)
    assert (both.value, both.problems) == (None, [twice])           # repeated in both lists: said once
    several = compute(calc("count", ["F1", "F2", "F1", "F2", "F1"], unit=None), facts)
    assert several.problems == [twice, "input F2 is listed more than once"]
    assert compute(calc("share", ["F1"], of=["F1", "F2"]), facts).value == "33"   # in both lists once each is fine

def test_each_input_is_judged_once_even_when_listed_twice():
    facts = facts_with("1")
    facts["F1"]["status"] = "rejected"
    r = compute(calc("share", ["F1"], of=["F1"]), facts)
    assert r.problems == ["input F1 is not a settled capacity move"]

def test_inputs_without_a_plain_number_are_named():
    facts = facts_with("1,200", "4")
    r = compute(calc("sum", ["F1", "F2"]), facts)
    assert (r.value, r.problems) == (None, ["input F1 has no plain number"])
    del facts["F2"]["fields"]["size_value"]
    assert compute(calc("sum", ["F2"]), facts).problems == ["input F2 has no plain number"]

def test_share_checks_the_whole_the_same_way():
    facts = facts_with("1", "2")
    facts["F2"]["fields"]["size_unit"] = "tons"
    r = compute(calc("share", ["F1"], of=["F1", "F2"]), facts)
    assert r.problems == ['input F2 is stated in "tons", not "lines"']

def test_uncertain_input_is_flagged_even_when_the_calculation_fails():
    facts = facts_with("1", "x")
    facts["F1"]["status"] = "uncertain"
    r = compute(calc("sum", ["F1", "F2"]), facts)
    assert (r.value, r.includes_uncertain) == (None, True)

def test_compute_never_raises_on_hand_edited_calculations():
    facts = facts_with("1")
    assert compute(calc("average", ["F1"]), facts).problems == ["operation is not an allowed value"]
    assert compute({"operation": None}, facts).problems == ["operation is not an allowed value"]
    assert compute([1, 2], facts).problems == ["operation is not an allowed value"]
    bad = calc("sum", ["F1"]); bad["fact_ids"] = "F1"
    assert compute(bad, facts).problems == ["fact_ids must be a list"]
    del bad["fact_ids"]
    assert compute(bad, facts).problems == ["fact_ids must be a list"]
    assert compute(calc("sum", ["F1"], unit=None), facts).problems == ["unit is required"]
    assert compute(calc("sum", ["F1"], unit=5), facts).problems == ["unit is required"]
    assert compute(calc("share", ["F1"], of=["F1"], unit=" "), facts).problems == ["unit is required"]
    odd = calc("share", ["F1"]); odd["of_fact_ids"] = "F1"
    assert compute(odd, facts).problems == ["of_fact_ids must be a list"]
    unhashable = compute(calc("count", [["F1"], {"a": 1}, 7], unit=None), facts)
    assert unhashable.value is None and len(unhashable.problems) == 3
    del odd["of_fact_ids"]
    assert compute(odd, facts).problems == ["share inputs must be part of the whole"]   # a missing whole is empty

def test_numbers_too_large_to_add_exactly_become_a_problem():
    facts = facts_with("9" * 500, "1")
    r = compute(calc("sum", ["F1", "F2"]), facts)
    assert r.value is None and len(r.problems) == 1
    assert compute(calc("share", ["F2"], of=["F1", "F2"]), facts).value in (None, "0")

# --- beyond the brief: the judgement records -------------------------------------------------

def valid_judgements():
    """An analysis with every new section filled in correctly (two scenarios, one of each other record)."""
    analysis = minimal_analysis(fact_ids=["F1"])
    analysis["assumptions"] = [
        {"id": "A1", "text": "Demand keeps growing", "support": "partial", "if_wrong": "Capacity stays unused", "fact_ids": ["F1"]},
        {"id": "A2", "text": "Lines open on time", "support": "weak", "if_wrong": "Supply arrives late", "fact_ids": []}]
    analysis["scenarios"] = [
        {"id": "SC1", "name": "Tight market", "description": "Demand outruns supply",
         "assumption_ids": ["A1"], "signposts": [{"text": "Lead times rise", "fact_ids": []}]},
        {"id": "SC2", "name": "Loose market", "description": "Supply outruns demand",
         "assumption_ids": ["A1", "A2"], "signposts": [{"text": "Prices fall", "fact_ids": ["F2"]}]}]
    analysis["watch_items"] = [{"text": "Lead times", "trigger": "Above 20 weeks", "scenario_id": "SC1"},
                               {"text": "Prices", "trigger": "Falling for a quarter"}]
    analysis["predictions"] = [{"id": "P1", "message_id": "M1", "statement": "Both lines operate by the end of 2028",
                                "by": "2028-12-31", "resolves_when": "The company reports them as operating", "probability": 65}]
    analysis["calculations"] = [calc("sum", ["F1", "F2"], result="6")]
    return analysis

def run_with(tmp_path, mutate=None):
    run = three_moves(tmp_path)
    analysis = valid_judgements()
    if mutate:
        mutate(analysis)
    finish_run(run, ["F1"], analysis=analysis)
    return run

def test_complete_judgements_are_clean_and_pass_the_gate(tmp_path):
    run = run_with(tmp_path)
    assert check_data(run) == []
    assert gate(run) == []

def test_no_scenarios_and_empty_sections_are_fine(tmp_path):
    run = three_moves(tmp_path); finish_run(run, ["F1"])
    assert check_data(run) == [] and gate(run) == []

def test_old_analysis_without_the_new_sections_is_still_valid(tmp_path):
    run = three_moves(tmp_path)
    analysis = minimal_analysis(["F1"])
    for section in ("assumptions", "scenarios", "predictions", "calculations"):
        del analysis[section]
    finish_run(run, ["F1"], analysis=analysis)
    assert check_data(run) == [] and gate(run) == []

def test_two_to_four_scenarios_are_accepted_and_one_or_five_are_not(tmp_path):
    problem = Problem("analysis.json", "scenarios", "use no scenarios or between two and four")
    for n, ok in ((1, False), (2, True), (4, True), (5, False)):
        def mutate(analysis):
            base = analysis["scenarios"][0]
            analysis["scenarios"] = [dict(base, id=f"SC{i}") for i in range(1, n + 1)]
        run = run_with(tmp_path / str(n), mutate)
        assert (problem not in check_data(run)) is ok

def test_assumption_rules(tmp_path):
    def mutate(analysis):
        analysis["assumptions"] = [
            {"id": "A1", "text": " ", "support": "partial", "if_wrong": "", "fact_ids": ["F9"]},
            {"id": "A1", "text": "Fine", "support": "certain", "if_wrong": "Fine", "fact_ids": []},
            "not an object"]
        analysis["scenarios"] = []
    problems = check_data(run_with(tmp_path, mutate))
    assert Problem("analysis.json", "assumptions[0].text", "must not be empty") in problems
    assert Problem("analysis.json", "assumptions[0].if_wrong", "must not be empty") in problems
    assert Problem("analysis.json", "assumptions[0].fact_ids", "fact F9 does not exist") in problems
    assert Problem("analysis.json", "assumptions[1].id", "id A1 is used more than once") in problems
    assert Problem("analysis.json", "assumptions[1].support", "not an allowed value") in problems
    assert Problem("analysis.json", "assumptions[2]", "not an allowed value") in problems

def test_assumption_without_an_id_is_a_problem(tmp_path):
    def mutate(analysis):
        analysis["assumptions"] = [{"text": "x", "support": "weak", "if_wrong": "y", "fact_ids": []}]
        analysis["scenarios"] = []
    assert Problem("analysis.json", "assumptions[0].id", "must not be empty") in check_data(run_with(tmp_path, mutate))

def test_scenario_rules(tmp_path):
    def mutate(analysis):
        analysis["scenarios"][0].update(name="", description=" ", assumption_ids=[], signposts=[])
        analysis["scenarios"][1].update(assumption_ids="A1", signposts=[{"text": "", "fact_ids": []}, "x"])
    problems = check_data(run_with(tmp_path, mutate))
    assert Problem("analysis.json", "scenarios[0].name", "must not be empty") in problems
    assert Problem("analysis.json", "scenarios[0].description", "must not be empty") in problems
    assert Problem("analysis.json", "scenarios[0].assumption_ids", "must have at least one entry") in problems
    assert Problem("analysis.json", "scenarios[0].signposts", "must have at least one entry") in problems
    assert Problem("analysis.json", "scenarios[1].assumption_ids", "not an allowed value") in problems
    assert Problem("analysis.json", "scenarios[1].signposts[0].text", "must not be empty") in problems
    assert Problem("analysis.json", "scenarios[1].signposts[1]", "not an allowed value") in problems

def test_scenario_ids_must_be_unique(tmp_path):
    def mutate(analysis):
        analysis["scenarios"][1]["id"] = "SC1"
    problems = check_data(run_with(tmp_path, mutate))
    assert Problem("analysis.json", "scenarios[1].id", "id SC1 is used more than once") in problems

def test_watch_item_scenario_is_optional_but_must_exist(tmp_path):
    def mutate(analysis):
        analysis["watch_items"][0]["scenario_id"] = "SC9"
    problems = check_data(run_with(tmp_path, mutate))
    assert Problem("analysis.json", "watch_items[0].scenario_id", "scenario SC9 does not exist") in problems
    assert not [p for p in problems if p.field == "watch_items[1].scenario_id"]

def test_prediction_rules(tmp_path):
    ok = {"message_id": "M1", "statement": "ok", "by": "2028-12-31", "resolves_when": "ok", "probability": 65}
    def mutate(analysis):
        analysis["predictions"] = [
            {"id": "P1", "message_id": "M7", "statement": "", "by": "2028-02-30", "resolves_when": " ", "probability": 0},
            dict(ok, id="P1", probability=True),
            dict(ok, id="P3", by=2028, probability=65.5),
            dict(ok, id="P4", probability="65"),
            dict(ok, id="P5", probability=99),
            dict(ok, id="P6", probability=1)]
    problems = check_data(run_with(tmp_path, mutate))
    date, prob = "must be a date like 2027-12-31", "must be a whole number from 1 to 99"
    assert Problem("analysis.json", "predictions[0].message_id", "message M7 does not exist") in problems
    assert Problem("analysis.json", "predictions[0].statement", "must not be empty") in problems
    assert Problem("analysis.json", "predictions[0].resolves_when", "must not be empty") in problems
    assert Problem("analysis.json", "predictions[0].by", date) in problems
    assert Problem("analysis.json", "predictions[0].probability", prob) in problems
    assert Problem("analysis.json", "predictions[1].id", "id P1 is used more than once") in problems
    for index in (1, 2, 3):
        assert Problem("analysis.json", f"predictions[{index}].probability", prob) in problems
    assert Problem("analysis.json", "predictions[2].by", date) in problems
    assert not [p for p in problems if p.field in ("predictions[4].probability", "predictions[5].probability")]

def test_prediction_date_must_be_the_iso_form(tmp_path):
    def mutate(analysis):
        base = analysis["predictions"][0]
        dates = ("2028-1-5", "20281231", "2028-12-31 ", "2028-12-31T10:00", "2028-12-31")
        analysis["predictions"] = [dict(base, id=f"P{i}", by=by) for i, by in enumerate(dates)]
    problems = check_data(run_with(tmp_path, mutate))
    bad = [p.field for p in problems if p.message == "must be a date like 2027-12-31"]
    assert bad == ["predictions[0].by", "predictions[1].by", "predictions[2].by", "predictions[3].by"]

def test_calculation_rules(tmp_path):
    base = {"label": "x", "operation": "sum", "unit": "lines", "of_fact_ids": [], "result": "1"}
    def mutate(analysis):
        analysis["calculations"] = [
            dict(base, id="C1", label="", operation="average", fact_ids=[], result=" "),
            dict(base, id="C1", fact_ids=["F9"]),
            dict(base, id="C3", fact_ids="F1"),
            "nope"]
    problems = check_data(run_with(tmp_path, mutate))
    assert Problem("analysis.json", "calculations[0].label", "must not be empty") in problems
    assert Problem("analysis.json", "calculations[0].result", "must not be empty") in problems
    assert Problem("analysis.json", "calculations[0].operation", "not an allowed value") in problems
    assert Problem("analysis.json", "calculations[0].fact_ids", "must have at least one entry") in problems
    assert Problem("analysis.json", "calculations[1].id", "id C1 is used more than once") in problems
    assert Problem("analysis.json", "calculations[1].fact_ids", "fact F9 does not exist") in problems
    assert Problem("analysis.json", "calculations[2].fact_ids", "not an allowed value") in problems
    assert Problem("analysis.json", "calculations[3]", "not an allowed value") in problems
    assert [p for p in problems if p.field == "calculations[2].fact_ids"] == \
        [Problem("analysis.json", "calculations[2].fact_ids", "not an allowed value")]

def test_wrong_typed_sections_are_problems_not_crashes(tmp_path):
    for section in ("assumptions", "scenarios", "predictions", "calculations"):
        run = three_moves(tmp_path / section)
        analysis = minimal_analysis(["F1"]); analysis[section] = "oops"
        finish_run(run, ["F1"], analysis=analysis)
        assert Problem("analysis.json", section, "not an allowed value") in check_data(run)
        assert Problem("analysis.json", section, "not an allowed value") in gate(run)
    run = three_moves(tmp_path / "watch")
    analysis = minimal_analysis(["F1"]); analysis["watch_items"] = ["x", {"text": "t", "trigger": "g", "scenario_id": 5}]
    finish_run(run, ["F1"], analysis=analysis)
    assert Problem("analysis.json", "watch_items[1].scenario_id", "scenario 5 does not exist") in check_data(run)

# --- beyond the brief: gate rule 8 -----------------------------------------------------------

def test_gate_names_every_compute_problem_for_the_right_calculation(tmp_path):
    def mutate(analysis):
        analysis["calculations"] = [calc("sum", ["F1", "F2"], result="6"), calc("sum", ["F1", "F3"], result="3"),
                                    calc("average", ["F1"]), "nope",
                                    calc("count", ["F1", "F2", "F3"], unit=None, result="3")]
    problems = gate(run_with(tmp_path, mutate))
    assert Problem("analysis.json", "calculations[1]", 'input F3 is stated in "EUR million", not "lines"') in problems
    assert Problem("analysis.json", "calculations[2]", "operation is not an allowed value") in problems
    assert not [p for p in problems if p.field in ("calculations[0]", "calculations[4]")]
    assert not [p for p in problems if "does not match" in p.message]

def test_gate_does_not_compare_a_result_when_the_calculation_failed(tmp_path):
    def mutate(analysis):
        analysis["calculations"] = [calc("sum", ["F1", "F3"], result="999")]
    problems = [p for p in gate(run_with(tmp_path, mutate)) if p.field == "calculations[0]"]
    assert [p.message for p in problems] == ['input F3 is stated in "EUR million", not "lines"']

def test_gate_compares_the_result_as_the_engine_writes_numbers(tmp_path):
    def mutate(analysis):
        analysis["calculations"] = [calc("sum", ["F1", "F2"], result="6.0")]
    problems = gate(run_with(tmp_path, mutate))
    assert Problem("analysis.json", "calculations[0]", "result does not match its inputs (computed 6)") in problems

def test_gate_refuses_a_calculation_that_lists_a_fact_twice(tmp_path):
    def mutate(analysis):
        analysis["calculations"] = [calc("sum", ["F1", "F1"], result="4")]   # the doubled figure
    problems = [p for p in gate(run_with(tmp_path, mutate)) if p.field == "calculations[0]"]
    assert problems == [Problem("analysis.json", "calculations[0]", "input F1 is listed more than once")]

def test_gate_refuses_a_calculation_resting_on_a_rejected_fact(tmp_path):
    run = three_moves(tmp_path)
    add_fact(run, source_id="S1", primary_source=True, quote="Competitor D adds nine syringe lines in 2028",
             fields={"company": "Competitor D", "size_value": "9", "size_unit": "lines"})
    analysis = minimal_analysis(["F1"]); analysis["calculations"] = [calc("sum", ["F1", "F4"], result="11")]
    finish_run(run, ["F1"], analysis=analysis)
    problems = gate(run)
    assert Problem("analysis.json", "calculations[0]", "input F4 is not a settled capacity move") in problems
    assert Problem("analysis.json", "calculations[0].fact_ids", "rests on fact F4 with status rejected") in problems

def test_gate_rule_8_sits_after_the_fact_rules_and_before_the_publishable_rule(tmp_path):
    run = three_moves(tmp_path)
    add_source(run, "Internal note about capacity.", data_class="internal", url="internal note")
    store.save_run(run, dict(store.load_run(run), mode="private", private_acknowledged_at="2026-11-12T10:00:00Z",
                             private_acknowledged_words="Yes (an invented reply)."))
    (run / ".gitignore").write_text("*\n", encoding="utf-8")          # a private run is kept out of git whole
    analysis = minimal_analysis(["F1"]); analysis["calculations"] = [calc("sum", ["F1", "F2"], result="7")]
    finish_run(run, ["F1"], analysis=analysis)
    add_fact(run, source_id="S1", quote="Competitor B adds four syringe lines in 2028")  # F4, never settled
    found = [(p.file, p.field) for p in gate(run, publishable=True)]
    assert found == [("facts/F4.json", "status"), ("analysis.json", "calculations[0]"), ("run.json", "mode"),
                     ("sources/S2.json", "data_class")]

def test_gate_with_judgements_does_not_write_anything(tmp_path):
    run = run_with(tmp_path, lambda analysis: analysis["calculations"][0].update(result="7"))
    def snapshot():
        return {str(p.relative_to(run)): p.read_bytes() for p in sorted(run.rglob("*")) if p.is_file()}
    before = snapshot()
    assert gate(run)
    assert snapshot() == before

# --- the test helper -------------------------------------------------------------------------

def test_finish_run_settles_facts_and_records_both_checkpoints(tmp_path):
    run = three_moves(tmp_path)
    add_fact(run, source_id="S1", primary_source=True, quote="Competitor D adds nine syringe lines in 2028")
    finish_run(run, ["F1"])
    facts = store.read_facts(run)
    assert [facts[i]["status"] for i in ("F1", "F2", "F3", "F4")] == ["confirmed", "confirmed", "confirmed", "rejected"]
    checkpoints = store.load_run(run)["checkpoints"]
    assert [(c["name"], c["answered_by"]) for c in checkpoints] == [("lenses", "test"), ("final_report", "test")]
    assert store.read_analysis(run) == minimal_analysis(["F1"])
