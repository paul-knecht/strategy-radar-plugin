"""The report model's projects, the answer to the core question, connections, and each message's sources and checks
(invented fixtures only: Competitor A's Plant North, reported three times, and Competitor B's plant in Exampleland)."""
import json

from radar import projects, store, verify
from radar.gate import gate
from radar.report import projects_view
from radar.report.build import build_report
from radar.report.model import build_model
from helpers import add_fact, add_source, make_run, minimal_analysis
from test_report_build import LENSES

PACK = [{"name": "Example Pharma", "other_names": [], "home": True},
        {"name": "Competitor A", "other_names": ["CompA"], "home": False},
        {"name": "Competitor B", "other_names": [], "home": False}]
TEXT_A = ("Competitor A will add a filling line at Plant North. "
          "CompA adds a second filling line at Plant North. "
          "Competitor A will sell vials from Plant North to Drug maker B, its new customer.")
TEXT_A2 = "The filling line of Competitor A at Plant North is now operating."
TEXT_B = "Competitor B builds a plant in Exampleland for its own products."


def moves_run(tmp_path, analysis=None):
    """F1, F2 (S1, 2026-05-14) and F3 (S3, 2026-09-01): Competitor A's moves at Plant North, all three open, F3
    operating; F4 (S2, a trade journal): Competitor B's plant for its own use, from one source only; F5: a general fact
    about Competitor A that names Drug maker B as its customer."""
    run = make_run(tmp_path, companies=PACK, home_company="Example Pharma")
    add_source(run, TEXT_A, publisher="Competitor A", date="2026-05-14")
    add_source(run, TEXT_B, publisher="Trade Journal", type="trade_press", date="2026-03-02")
    add_source(run, TEXT_A2, publisher="Competitor A", date="2026-09-01")
    add_fact(run, source_id="S1", primary_source=True, quote="Competitor A will add a filling line at Plant North")
    add_fact(run, source_id="S1", primary_source=True, quote="CompA adds a second filling line at Plant North",
             fields={"company": "CompA", "site": "Plant North"})
    add_fact(run, source_id="S3", primary_source=True, quote="Competitor A at Plant North is now operating",
             fields={"stage": "operating", "site": None})
    add_fact(run, source_id="S2", primary_source=False, quote="Competitor B builds a plant in Exampleland",
             statement="Competitor B builds a plant.",
             fields={"company": "Competitor B", "move_type": "new_site", "site": None, "access": "captive",
                     "what_added": "a new plant"})
    add_fact(run, kind="general", fields=None, source_id="S1", primary_source=True,
             statement="Competitor A will sell vials to Drug maker B.", about_company="Competitor A",
             quote="Competitor A will sell vials from Plant North to Drug maker B, its new customer.",
             connections=[{"party": "Drug maker B", "tie": "customer", "description": None}])
    verify.check_quotes(run)
    for fact_id in store.read_facts(run):
        verify.record_support(run, fact_id, True, "support-checker", "")
    verify.settle(run)
    store.write_analysis(run, analysis or minimal_analysis(["F1"]))
    for name in store.CHECKPOINTS:
        store.record_checkpoint(run, name, "test", "ok")
    return run


def group(run):
    projects.record_projects(run, [{"name": "Competitor B, Exampleland", "fact_ids": ["F4"]},
                                   {"name": "Competitor A, Plant North", "fact_ids": ["F1", "F2", "F3"]}],
                             projects.GROUPER)


def items_by_id(model):
    return {item["id"]: item for item in model["projects"]["items"]}


def test_the_access_rule_has_four_outcomes():
    def facts(*said):
        return [{"fields": {"access": access}} for access in said]
    open_and_unstated, captive_only = facts("open", "not_stated", None), facts("captive")
    both, none_stated = facts("open", "captive", "not_stated"), facts("not_stated", None) + [{"fields": None}]
    assert [projects_view.project_access(fs) for fs in (open_and_unstated, captive_only, both, none_stated)] == \
        ["open", "captive", "disagree", "not_stated"]
    assert projects_view.ACCESS_SHOWN == ("open", "captive", "disagree", "not_stated")


def test_the_spread_leaves_out_blanks_and_puts_the_most_frequent_first():
    assert projects_view.spread(["2028", None, "2027", "", "2028", "  ", "2026"]) == \
        [("2028", 2), ("2027", 1), ("2026", 1)]
    assert projects_view.spread([None, ""]) == []


def test_the_core_answer_counts_projects_not_reports(tmp_path):
    run = moves_run(tmp_path)
    group(run)
    model = build_model(run, LENSES)
    assert model["projects"]["state"] == "grouped"
    assert [item["id"] for item in model["projects"]["items"]] == ["P2", "P1"]   # Competitor A comes first
    assert model["core_answer"] == {"open": 1, "captive": 1, "disagree": 0, "not_stated": 0, "total": 2,
                                    "outside": 0}


def test_a_project_shows_the_spread_of_its_reports(tmp_path):
    run = moves_run(tmp_path)
    group(run)
    item = items_by_id(build_model(run, LENSES))["P2"]
    assert item["name"] == "Competitor A, Plant North" and item["company"]["name"] == "Competitor A"
    assert [fact["id"] for fact in item["facts"]] == ["F3", "F1", "F2"]   # newest first
    assert item["spread"]["stage"] == [["announced", 2], ["operating", 1]]
    assert item["spread"]["site"] == [["Plant North", 2]]
    assert item["spread"]["planned_start"] == [["2028", 3]]
    assert item["spread"]["countries"] == [["Exampleland", 3]]
    assert item["spread"]["what"] == [["a second filling line", 3]]
    assert item["counts"] == {"confirmed": 3, "single_source": 0, "uncertain": 0}
    assert item["access"] == "open" and item["dates"] == ["2026-09-01", "2026-05-14"]
    single = items_by_id(build_model(run, LENSES))["P1"]
    assert single["counts"] == {"confirmed": 0, "single_source": 1, "uncertain": 0} and single["access"] == "captive"


def test_without_a_grouping_each_move_is_its_own_project(tmp_path):
    model = build_model(moves_run(tmp_path), LENSES)
    assert model["projects"]["state"] == "none"
    items = items_by_id(model)
    assert [item["id"] for item in model["projects"]["items"]] == ["project-F3", "project-F1", "project-F2",
                                                                   "project-F4"]
    assert items["project-F1"]["name"] == "Competitor A: a second filling line, Plant North"
    assert items["project-F3"]["name"] == "Competitor A: a second filling line"   # no site stated
    assert items["project-F4"]["name"] == "Competitor B: a new plant"
    assert all(len(item["facts"]) == 1 for item in items.values())
    assert model["core_answer"] == {"open": 3, "captive": 1, "disagree": 0, "not_stated": 0, "total": 4,
                                    "outside": 0}


def test_an_outdated_grouping_shows_moves_ungrouped_and_says_so(tmp_path):
    run = moves_run(tmp_path)
    group(run)
    verify.withdraw_fact(run, "F2", "a duplicate of F1")
    verify.settle(run)
    model = build_model(run, LENSES)
    assert model["projects"]["state"] == "outdated"
    assert [item["id"] for item in model["projects"]["items"]] == ["project-F3", "project-F1", "project-F4"]


def test_a_damaged_grouping_shows_moves_ungrouped(tmp_path):
    run = moves_run(tmp_path)
    (run / projects.RECORD).write_text("{not json", encoding="utf-8")
    model = build_model(run, LENSES)
    assert model["projects"]["state"] == "damaged" and len(model["projects"]["items"]) == 4


def test_rejected_facts_never_sit_in_a_project(tmp_path):
    run = moves_run(tmp_path)
    verify.withdraw_fact(run, "F4", "not about a plant")
    verify.settle(run)
    model = build_model(run, LENSES)
    assert "F4" in [fact["id"] for fact in model["rejected"]]
    assert all(fact["id"] != "F4" for item in model["projects"]["items"] for fact in item["facts"])
    assert model["core_answer"]["total"] == 3


def test_a_project_whose_reports_are_all_gone_is_skipped_and_never_stops_the_build(tmp_path, monkeypatch):
    run = moves_run(tmp_path)
    recorded = [{"id": "P1", "name": "Competitor B, Exampleland", "fact_ids": ["F4"]},
                {"id": "P2", "name": "Gone, nowhere", "fact_ids": ["F99"]},
                {"id": "P3", "name": "Competitor A, Plant North", "fact_ids": ["F1", "F2", "F3"]}]
    monkeypatch.setattr(projects_view.projects, "current", lambda run_dir: (recorded, "grouped"))
    model = build_model(run, LENSES)
    ids = [item["id"] for item in model["projects"]["items"]]
    assert len(ids) == 2 and set(ids) == {"P1", "P3"}
    assert model["projects"]["state"] == "grouped"


def test_grouping_changes_no_status(tmp_path):
    run = moves_run(tmp_path)
    before = store.read_facts(run)
    group(run)
    model = build_model(run, LENSES)
    after = store.read_facts(run)
    assert after == before
    for item in model["projects"]["items"]:
        for fact in item["facts"]:
            assert (fact["status"], fact["status_reason"]) == (after[fact["id"]]["status"],
                                                               after[fact["id"]]["status_reason"])
    assert all(fact["status"] == after[fact["id"]]["status"] for fact in model["facts"])


def test_each_company_has_its_own_core_answer(tmp_path):
    run = moves_run(tmp_path)
    group(run)
    companies = {entry["name"]: entry for entry in build_model(run, LENSES)["companies"]}
    assert companies["Example Pharma"]["core_answer"] is None
    assert companies["Competitor A"]["core_answer"] == {"open": 1, "captive": 0, "disagree": 0, "not_stated": 0,
                                                        "total": 1, "outside": 0}
    assert companies["Competitor B"]["core_answer"] == {"open": 0, "captive": 1, "disagree": 0, "not_stated": 0,
                                                        "total": 1, "outside": 0}


TEXT_FIVE = ("Move one adds a filling line. Move two adds a filling line. Move three adds a filling line. "
             "Move four adds a drug-substance plant. Move five adds a packaging hall.")


def five_moves_run(tmp_path, in_question=("yes", "yes", "yes", "no", "no")):
    """F1 to F5 of Competitor A, each its own project and confirmed: F3 says nothing on access, the others are open.
    `in_question` gives each move's value; None leaves the field out, as in a run made before it existed."""
    run = make_run(tmp_path, companies=PACK, home_company="Example Pharma")
    add_source(run, TEXT_FIVE, publisher="Competitor A", date="2026-05-14")
    quotes = [sentence + "." for sentence in TEXT_FIVE.rstrip(".").split(". ")]
    for number, (quote, inside) in enumerate(zip(quotes, in_question), start=1):
        fields = {"access": "not_stated" if number == 3 else "open", "site": f"Plant {number}",
                  "in_question": inside}
        fact = add_fact(run, source_id="S1", primary_source=True, quote=quote, fields=fields,
                        statement=f"Competitor A adds capacity (move {number}).")
        if inside is None:
            del fact["fields"]["in_question"]
            store.write_fact(run, fact)
    verify.check_quotes(run)
    for fact_id in store.read_facts(run):
        verify.record_support(run, fact_id, True, "support-checker", "")
    verify.settle(run)
    store.write_analysis(run, minimal_analysis(["F1"]))
    for name in store.CHECKPOINTS:
        store.record_checkpoint(run, name, "test", "ok")
    return run


def test_the_answer_counts_only_moves_in_the_question(tmp_path):
    model = build_model(five_moves_run(tmp_path), LENSES)
    assert model["core_answer"] == {"open": 2, "captive": 0, "disagree": 0, "not_stated": 1, "total": 3,
                                    "outside": 2}
    assert [item["id"] for item in model["projects"]["items"]] == ["project-F1", "project-F2", "project-F3"]
    assert {fact["id"] for fact in model["facts"]} >= {"F4", "F5"}   # nothing is hidden: they stay in the facts
    [company] = [entry for entry in model["companies"] if entry["name"] == "Competitor A"]
    assert company["core_answer"]["total"] == 3 and company["core_answer"]["outside"] == 2
    assert projects_view.in_question({"fields": {"in_question": "no"}}) is False
    assert projects_view.in_question({"fields": {"in_question": "yes"}}) is True
    assert projects_view.in_question({"fields": {}}) is True and projects_view.in_question({}) is True


def test_an_old_run_without_the_field_counts_every_move(tmp_path):
    model = build_model(five_moves_run(tmp_path, in_question=(None,) * 5), LENSES)
    assert model["core_answer"] == {"open": 4, "captive": 0, "disagree": 0, "not_stated": 1, "total": 5,
                                    "outside": 0}


def test_a_run_whose_moves_all_fall_outside_still_says_so(tmp_path):
    model = build_model(five_moves_run(tmp_path, in_question=("no",) * 5), LENSES)
    assert model["projects"]["items"] == []
    assert model["core_answer"] == {"open": 0, "captive": 0, "disagree": 0, "not_stated": 0, "total": 0,
                                    "outside": 5}


def test_a_run_without_a_counting_move_has_no_core_answer(tmp_path):
    run = make_run(tmp_path)
    add_source(run, TEXT_A, publisher="Competitor A")
    add_fact(run, kind="general", fields=None, source_id="S1", primary_source=True,
             quote="Competitor A will add a filling line at Plant North")
    verify.check_quotes(run)
    verify.record_support(run, "F1", True, "support-checker", "")
    verify.settle(run)
    store.write_analysis(run, minimal_analysis(["F1"]))
    model = build_model(run, LENSES)
    assert model["core_answer"] is None and model["projects"]["items"] == []


def test_the_connections_list_every_kept_connection_in_the_order_of_the_facts(tmp_path):
    model = build_model(moves_run(tmp_path), LENSES)
    [connection] = model["connections"]
    assert connection["fact"]["id"] == "F5" and connection["company"]["name"] == "Competitor A"
    assert connection["party_name"] == "Drug maker B" and connection["party"]["key"] == "other"
    assert (connection["tie"], connection["description"]) == ("customer", None)


def analysis_with_flags():
    analysis = minimal_analysis(["F1", "F4"])
    analysis["messages"][0]["outside_view"] = {"text": "Expansions often slip.", "fact_ids": ["F2", "F3"]}
    analysis["audit_flags"] = [
        {"check": "framing", "text": "The message leans on Competitor A's own words.", "message_ids": ["M1", "M9"]},
        {"check": "outside_view", "text": "No base rate was looked for."}]
    return analysis


def test_a_flag_sits_under_the_message_it_names_and_stays_in_the_list_of_checks(tmp_path):
    model = build_model(moves_run(tmp_path, analysis_with_flags()), LENSES)
    flags = model["audit_flags"]
    assert [flag["message_ids"] for flag in flags] == [["M1"], []]   # only ids of messages that exist
    assert [flag["check"] for flag in model["messages"][0]["flags"]] == ["framing"]


def test_a_message_names_its_sources_by_publisher_and_marks_the_company_s_own(tmp_path):
    message = build_model(moves_run(tmp_path, analysis_with_flags()), LENSES)["messages"][0]
    assert message["sources"] == [{"id": "S1", "publisher": "Competitor A", "own": True},
                                  {"id": "S2", "publisher": "Trade Journal", "own": False},
                                  {"id": "S3", "publisher": "Competitor A", "own": True}]
    assert message["companies"] == ["c2", "c3"]


def test_the_model_with_projects_is_plain_data(tmp_path):
    run = moves_run(tmp_path, analysis_with_flags())
    group(run)
    model = build_model(run, LENSES)
    assert json.loads(json.dumps(model)) == model


def test_an_old_run_builds_with_plain_fallbacks(tmp_path):
    """Review focus 1: a run made before this change has no reason codes, no company tags, no connections, no
    companies in run.json, flags without message ids and no grouping."""
    run = moves_run(tmp_path, analysis_with_flags())
    for fact in store.read_facts(run).values():
        for key in ("uncertain_reasons", "about_company", "connections"):
            fact.pop(key, None)
        store.write_fact(run, fact)
    record = json.loads((run / "run.json").read_text(encoding="utf-8"))
    del record["companies"]
    (run / "run.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    analysis = store.read_analysis(run)
    for flag in analysis["audit_flags"]:
        flag.pop("message_ids", None)
    store.write_analysis(run, analysis)
    assert not (run / projects.RECORD).exists()
    assert gate(run, LENSES) == []
    paths = build_report(run, LENSES)
    assert [path.name for path in paths] == ["report.md", "report.html", "facts.csv", "sources.csv"]
    model = build_model(run, LENSES)
    facts = {fact["id"]: fact for fact in model["facts"]}
    assert facts["F4"]["shown_status"] == "single_source"
    assert facts["F5"]["company"]["key"] == "none" and model["connections"] == []
    assert model["projects"]["state"] == "none" and len(model["projects"]["items"]) == 4
    assert [flag["message_ids"] for flag in model["audit_flags"]] == [[], []]
    assert model["messages"][0]["flags"] == []
