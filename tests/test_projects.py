"""The grouping of capacity moves into projects: the record the program writes for the project grouper, the rules it
checks at record time and again on the facts as they are now, the shape check of `check-data`, and what the grouper
reads. Everything here is invented: Competitor A's Plant North, reported three ways."""
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from radar import cli, demo, projects, store, verify
from radar.explain import explain
from radar.gate import gate
from radar.schema import Problem, check_data
from radar.status import run_status
from helpers import add_fact, add_source, finish_run, make_run

LENSES = demo.LENSES
NOW = datetime(2026, 11, 16, 9, 30, tzinfo=timezone.utc)
THREE_WAYS = [
    {"site": "Plant North", "country": "US"},
    {"site": "Plant North, Northtown", "country": "U.S."},
    {"site": "a new site in Northtown", "country": None},
]


def grouping_run(tmp_path, moves=THREE_WAYS, general=False, rejected=False) -> Path:
    """A run whose moves F1, F2, ... (each a dict of field values over the helper's defaults) are confirmed; then, when
    asked, a confirmed general fact and a move rejected because its quote is not in the copy."""
    quotes = [f"Move number {number} adds a filling line." for number in range(1, len(moves) + 1)]
    text = " ".join(quotes + ["Competitor A says the new lines are for its own products."])
    run = make_run(tmp_path)
    add_source(run, text, publisher="Competitor A", date="2026-05-14")
    for quote, fields in zip(quotes, moves):
        add_fact(run, source_id="S1", primary_source=True, quote=quote, fields=fields,
                 statement=f"Competitor A adds a filling line ({quote[:13]}).")
    if general:
        add_fact(run, kind="general", fields=None, source_id="S1", primary_source=True,
                 statement="Competitor A says the new lines are for its own products.",
                 quote="Competitor A says the new lines are for its own products.")
    if rejected:
        add_fact(run, source_id="S1", primary_source=True, quote="Competitor A adds nine filling lines.")
    finish_run(run, ["F1"], lens_id="firm-boundaries")
    return run


def one_project(*fact_ids, name="Competitor A, Plant North") -> dict:
    return {"name": name, "fact_ids": list(fact_ids)}


def messages(problems) -> list[str]:
    return [problem.message for problem in problems]


def refused(run, given, by=projects.GROUPER) -> list[Problem]:
    with pytest.raises(projects.ProjectsRefused) as caught:
        projects.record_projects(run, given, by, NOW)
    assert not (run / projects.RECORD).exists()
    return caught.value.problems


# --- the constants -------------------------------------------------------------------------------------------------

def test_the_constants():
    assert projects.RECORD == "projects.json" and projects.GROUPER == "project-grouper"
    assert projects.MAX_NAME == 120
    assert projects.RECORD_KEYS == ("by", "at", "projects") and projects.PROJECT_KEYS == ("id", "name", "fact_ids")


# --- recording -------------------------------------------------------------------------------------------------------

def test_one_site_named_three_ways_can_be_recorded_as_one_project(tmp_path):
    run = grouping_run(tmp_path)
    record = projects.record_projects(run, [one_project("F1", "F2", "F3")], "project-grouper", NOW)
    assert record == {"by": "project-grouper", "at": "2026-11-16T09:30:00Z",
                      "projects": [{"id": "P1", "name": "Competitor A, Plant North", "fact_ids": ["F1", "F2", "F3"]}]}
    assert json.loads((run / projects.RECORD).read_text(encoding="utf-8")) == record
    assert projects.current(run) == (record["projects"], "grouped")


def test_projects_get_ids_in_the_recorded_order(tmp_path):
    run = grouping_run(tmp_path)
    record = projects.record_projects(run, [one_project("F3", name="Northtown"), one_project("F1", "F2")],
                                      projects.GROUPER, NOW)
    assert [(project["id"], project["fact_ids"]) for project in record["projects"]] == [
        ("P1", ["F3"]), ("P2", ["F1", "F2"])]


def test_a_move_left_out_is_refused_and_nothing_is_written(tmp_path):
    run = grouping_run(tmp_path)
    assert refused(run, [one_project("F1", "F2")]) == [Problem(projects.RECORD, "F3", projects.FACT_LEFT_OUT)]


def test_a_move_named_twice_is_refused(tmp_path):
    run = grouping_run(tmp_path)
    problems = refused(run, [one_project("F1", "F2", "F3"), one_project("F2", name="Plant North again")])
    assert problems == [Problem(projects.RECORD, "F2", projects.FACT_TWICE)]


def test_two_companies_in_one_project_are_refused_after_tidying(tmp_path):
    run = grouping_run(tmp_path, [{"company": "Competitor A"}, {"company": "Competitor A Inc."},
                                  {"company": "Competitor B"}])
    projects.record_projects(run, [one_project("F1", "F2"), one_project("F3", name="Competitor B")],
                             projects.GROUPER, NOW)
    (run / projects.RECORD).unlink()
    assert refused(run, [one_project("F1", "F2", "F3")]) == [
        Problem(projects.RECORD, "projects[0]", projects.TWO_COMPANIES)]


def test_a_pack_company_s_other_name_counts_as_the_same_company(tmp_path):
    run = grouping_run(tmp_path, [{"company": "Competitor A"}, {"company": "CompA Pharma"}])
    data = store.load_run(run)
    data["companies"] = [{"name": "Competitor A", "other_names": ["CompA Pharma"], "home": False}]
    store.save_run(run, data)
    assert projects.check_projects(run, [one_project("F1", "F2")]) == []


def test_two_countries_in_one_project_are_refused_after_tidying(tmp_path):
    run = grouping_run(tmp_path, [{"country": "US"}, {"country": "U.S."}, {"country": "Germany"}])
    assert projects.check_projects(run, [one_project("F1", "F2"), one_project("F3", name="Germany")]) == []
    assert refused(run, [one_project("F1", "F2", "F3")]) == [
        Problem(projects.RECORD, "projects[0]", projects.TWO_COUNTRIES)]


def test_the_same_set_of_countries_fits_and_a_different_set_does_not(tmp_path):
    run = grouping_run(tmp_path, [{"country": "US, Germany"}, {"country": "Germany and USA"}, {"country": "US"},
                                  {"country": " "}])
    assert projects.check_projects(run, [one_project("F1", "F2", "F4"), one_project("F3", name="US")]) == []
    assert messages(projects.check_projects(run, [one_project("F1", "F2", "F3", "F4")])) == [projects.TWO_COUNTRIES]


def test_a_general_or_rejected_fact_cannot_sit_in_a_project(tmp_path):
    run = grouping_run(tmp_path, general=True, rejected=True)
    assert {fact_id: fact["status"] for fact_id, fact in store.read_facts(run).items()} == {
        "F1": "confirmed", "F2": "confirmed", "F3": "confirmed", "F4": "confirmed", "F5": "rejected"}
    assert sorted(projects.moves(run)) == ["F1", "F2", "F3"]
    problems = refused(run, [one_project("F1", "F2", "F3", "F4", "F5", "F9")])
    assert problems == [Problem(projects.RECORD, fact_id, projects.FACT_NOT_A_MOVE) for fact_id in ("F4", "F5", "F9")]


def test_a_project_needs_a_short_name(tmp_path):
    run = grouping_run(tmp_path)
    for name in ("", "   ", "x" * 121):
        assert refused(run, [one_project("F1", "F2", "F3", name=name)]) == [
            Problem(projects.RECORD, "projects[0].name", projects.NAME_NEEDED)]
    assert projects.check_projects(run, [one_project("F1", "F2", "F3", name="x" * 120)]) == []


@pytest.mark.parametrize("given", [None, "F1", [["F1"]], [{"name": "n"}], [{"name": "n", "fact_ids": "F1"}],
                                   [{"name": "n", "fact_ids": [1]}], [{"name": "n", "fact_ids": []}],
                                   [{"name": "n", "fact_ids": ["F1"], "id": "P1"}]])
def test_projects_in_the_wrong_form_are_refused_and_never_raise_otherwise(tmp_path, given):
    run = grouping_run(tmp_path)
    assert projects.SHAPE in messages(projects.check_projects(run, given))
    assert projects.SHAPE in messages(refused(run, given))


def test_only_the_grouper_may_record(tmp_path):
    run = grouping_run(tmp_path)
    with pytest.raises(ValueError, match=projects.NOT_THE_GROUPER):
        projects.record_projects(run, [one_project("F1", "F2", "F3")], "lead", NOW)
    assert not (run / projects.RECORD).exists()


def test_recording_a_grouping_changes_no_fact(tmp_path):
    run = grouping_run(tmp_path, general=True, rejected=True)
    before = {path.name: path.read_bytes() for path in (run / "facts").iterdir()}
    projects.record_projects(run, [one_project("F1", "F2", "F3")], projects.GROUPER, NOW)
    assert {path.name: path.read_bytes() for path in (run / "facts").iterdir()} == before


def test_a_new_grouping_replaces_the_earlier_one(tmp_path):
    run = grouping_run(tmp_path)
    projects.record_projects(run, [one_project("F1", "F2", "F3")], projects.GROUPER, NOW)
    projects.record_projects(run, [one_project("F1"), one_project("F2", "F3", name="Northtown")], projects.GROUPER,
                             NOW)
    assert [project["id"] for project in projects.current(run)[0]] == ["P1", "P2"]


def test_a_run_with_no_move_takes_an_empty_grouping(tmp_path):
    run = grouping_run(tmp_path, moves=[], general=True)
    assert projects.record_projects(run, [], projects.GROUPER, NOW)["projects"] == []
    assert projects.current(run) == ([], "grouped")


# --- the facts as they are now ----------------------------------------------------------------------------------------

def test_a_withdrawn_move_makes_the_grouping_outdated_and_the_gate_stays_open(tmp_path):
    run = grouping_run(tmp_path)
    projects.record_projects(run, [one_project("F1", "F2", "F3")], projects.GROUPER, NOW)
    assert gate(run, LENSES) == []
    verify.withdraw_fact(run, "F3", "The same move as F2.")   # not settled yet: it no longer counts all the same
    assert projects.current(run) == (None, "outdated")
    verify.settle(run)
    assert projects.current(run) == (None, "outdated") and gate(run, LENSES) == []


def test_a_move_added_after_the_grouping_makes_it_outdated(tmp_path):
    run = grouping_run(tmp_path)
    projects.record_projects(run, [one_project("F1", "F2", "F3")], projects.GROUPER, NOW)
    add_source(run, "Competitor B opens a new filling hall at Plant South in 2027.")
    add_fact(run, source_id="S2", primary_source=True, quote="Competitor B opens a new filling hall at Plant South")
    assert projects.current(run) == ([one_project("F1", "F2", "F3") | {"id": "P1"}], "grouped")   # F4 is proposed
    verify.check_quotes(run)
    verify.record_support(run, "F4", True, "support-checker", "")
    verify.settle(run)
    assert projects.current(run) == (None, "outdated")


def test_no_record_is_none(tmp_path):
    assert projects.current(grouping_run(tmp_path)) == (None, "none")


@pytest.mark.parametrize("content", ["{", "[]", json.dumps({"by": "project-grouper", "at": "x"}),
                                     json.dumps({"by": "lead", "at": "x", "projects": []}),
                                     json.dumps({"by": "project-grouper", "at": "x", "projects": [
                                         {"id": "P2", "name": "n", "fact_ids": ["F1", "F2", "F3"]}]}),
                                     json.dumps({"by": "project-grouper", "at": "x", "projects": [
                                         {"id": "P1", "name": "n", "fact_ids": ["F1", "F2", "F3"], "size": 1}]})])
def test_a_damaged_record_is_named_by_check_data_but_never_by_the_gate(tmp_path, content):
    run = grouping_run(tmp_path)
    (run / projects.RECORD).write_text(content, encoding="utf-8")
    assert projects.current(run) == (None, "damaged")
    named = [problem for problem in check_data(run, LENSES) if problem.file == projects.RECORD]
    assert named and all(explain(problem)["known"] for problem in named)
    assert gate(run, LENSES) == []


@pytest.mark.parametrize("name", ["", "   ", "x" * 121])
def test_a_saved_name_that_breaks_the_name_rule_is_damage_not_out_of_date(tmp_path, name):
    run = grouping_run(tmp_path)
    projects.record_projects(run, [one_project("F1", "F2", "F3")], projects.GROUPER, NOW)
    record = json.loads((run / projects.RECORD).read_text(encoding="utf-8"))
    record["projects"][0]["name"] = name
    (run / projects.RECORD).write_text(json.dumps(record), encoding="utf-8")
    assert projects.current(run) == (None, "damaged")
    assert Problem(projects.RECORD, "projects[0].name", projects.SHAPE) in check_data(run, LENSES)


def test_a_good_record_gives_check_data_nothing_to_say(tmp_path):
    run = grouping_run(tmp_path)
    projects.record_projects(run, [one_project("F1", "F2", "F3")], projects.GROUPER, NOW)
    assert check_data(run, LENSES) == []


def test_shape_problems_names_each_part(tmp_path):
    record = {"by": "project-grouper", "at": "2026-11-16T09:30:00Z",
              "projects": [{"id": "P1", "name": "n", "fact_ids": ["F1"]}]}
    assert projects.shape_problems(record) == []
    assert projects.shape_problems(None) == [Problem(projects.RECORD, None, projects.SHAPE)]
    assert projects.shape_problems({**record, "extra": 1}) == [Problem(projects.RECORD, "extra", projects.SHAPE)]
    assert projects.shape_problems({**record, "projects": [{"id": "P1", "name": 3, "fact_ids": ["F1"]}]}) == [
        Problem(projects.RECORD, "projects[0].name", projects.SHAPE)]


# --- the explanations ------------------------------------------------------------------------------------------------

def test_every_message_is_explained():
    for message in (projects.NOT_THE_GROUPER, projects.FACT_NOT_A_MOVE, projects.FACT_LEFT_OUT, projects.FACT_TWICE,
                    projects.TWO_COMPANIES, projects.TWO_COUNTRIES, projects.NAME_NEEDED, projects.SHAPE):
        assert explain(Problem(projects.RECORD, None, message))["known"], message
    for message in (projects.FACT_NOT_A_MOVE, projects.FACT_LEFT_OUT, projects.FACT_TWICE):
        assert "fact f3" in explain(Problem(projects.RECORD, "F3", message))["what"].lower(), message


# --- the line form ---------------------------------------------------------------------------------------------------

TWO_PROJECTS = """project: Competitor A, Plant North
facts: F1, F2

facts: F3
project: Competitor A, a new site in Northtown
"""


def test_the_line_form_reads_projects_and_refuses_an_unknown_key():
    assert projects.parse_list_lines(TWO_PROJECTS) == [
        {"name": "Competitor A, Plant North", "fact_ids": ["F1", "F2"]},
        {"name": "Competitor A, a new site in Northtown", "fact_ids": ["F3"]}]
    assert projects.parse_list_lines("\n\n") == []
    for text in ("project: A\nfacts: F1\nsize: 2\n", "project A\nfacts: F1\n", "project: A\n",
                 "project: A\nproject: B\nfacts: F1\n", "project: A\nfacts: \n", "note: none fits\n",
                 "project: A\nfacts: F1,,F2\n", "project: A\nfacts: F1, F2,\n"):
        with pytest.raises(ValueError):
            projects.parse_list_lines(text)


# --- the commands ----------------------------------------------------------------------------------------------------

def run_cli(capsys, *argv):
    code = cli.main([str(part) for part in argv])
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    return code, json.loads(out)


def _send(monkeypatch, text: str) -> None:
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(text.encode("utf-8")), encoding="utf-8"))


def test_record_projects_reads_plain_lines_from_standard_input(tmp_path, monkeypatch, capsys):
    run = grouping_run(tmp_path)
    _send(monkeypatch, TWO_PROJECTS)
    assert run_cli(capsys, "record-projects", "--run", run, "--by", projects.GROUPER, "--list-stdin") == (
        0, {"recorded": True, "problems": [], "explained": []})
    assert [project["fact_ids"] for project in projects.current(run)[0]] == [["F1", "F2"], ["F3"]]


def test_record_projects_names_each_problem_with_its_explanation(tmp_path, monkeypatch, capsys):
    run = grouping_run(tmp_path)
    _send(monkeypatch, "project: Competitor A, Plant North\nfacts: F1, F2\n")
    code, out = run_cli(capsys, "record-projects", "--run", run, "--by", projects.GROUPER, "--list-stdin")
    assert code == 1 and out["recorded"] is False
    assert out["problems"] == [{"file": projects.RECORD, "field": "F3", "message": projects.FACT_LEFT_OUT}]
    assert out["explained"][0]["known"] is True
    assert not (run / projects.RECORD).exists()


def test_record_projects_takes_a_file(tmp_path, capsys):
    run = grouping_run(tmp_path)
    path = tmp_path / "projects-in.json"
    path.write_text(json.dumps({"projects": [one_project("F1", "F2", "F3")]}), encoding="utf-8")
    assert run_cli(capsys, "record-projects", "--run", run, "--by", projects.GROUPER, "--file", path)[0] == 0
    assert projects.current(run)[1] == "grouped"


@pytest.mark.parametrize("content", ["{", "[]", json.dumps({"projects": []}) + "x", json.dumps({"groups": []}),
                                     json.dumps({"projects": [], "note": "n"}),
                                     '{"projects": [], "projects": []}',
                                     json.dumps({"projects": [{"name": "n", "fact_ids": []}]}),
                                     json.dumps({"projects": [{"name": 5, "fact_ids": [1]}]}),
                                     json.dumps({"projects": [{"name": 5, "fact_ids": ["F1", "F2", "F3"]}]})])
def test_record_projects_refuses_a_file_it_cannot_read(tmp_path, capsys, content):
    run = grouping_run(tmp_path)
    path = tmp_path / "projects-in.json"
    path.write_text(content, encoding="utf-8")
    code, out = run_cli(capsys, "record-projects", "--run", run, "--by", projects.GROUPER, "--file", path)
    assert code == 2 and list(out) == ["error"]
    assert not (run / projects.RECORD).exists()


def test_record_projects_refuses_another_helper_and_broken_lines(tmp_path, monkeypatch, capsys):
    run = grouping_run(tmp_path)
    _send(monkeypatch, TWO_PROJECTS)
    assert run_cli(capsys, "record-projects", "--run", run, "--by", "lead", "--list-stdin") == (
        2, {"error": projects.NOT_THE_GROUPER})
    _send(monkeypatch, "project Plant North\n")
    code, out = run_cli(capsys, "record-projects", "--run", run, "--by", projects.GROUPER, "--list-stdin")
    assert code == 2 and list(out) == ["error"]
    assert not (run / projects.RECORD).exists()


def test_the_grouper_input_shows_tidied_companies_and_countries(tmp_path, capsys):
    run = grouping_run(tmp_path, [{"company": "Competitor A Inc.", "country": "U.S.", "size_value": "2",
                                   "size_unit": "Lines"},
                                  {"company": "competitor b", "country": "Germany and USA", "site": None}],
                       general=True)
    data = store.load_run(run)
    data["companies"] = [{"name": "Competitor B", "other_names": [], "home": False}]
    store.save_run(run, data)
    given = projects.grouper_input(run)
    assert list(given) == ["question", "facts"] and given["question"] == "Who adds capacity?"
    first, second = given["facts"]
    assert first == {"id": "F1", "statement": "Competitor A adds a filling line (Move number 1).",
                     "status": "confirmed", "company": "Competitor A", "site": "Plant North",
                     "countries": ["United States"], "what_added": "a second filling line", "size": "2 lines",
                     "stage": "announced", "announced": "2026-05-14", "planned_start": "2028", "access": "open",
                     "publisher": "Competitor A", "date": "2026-05-14"}
    assert second["company"] == "Competitor B" and second["site"] is None
    assert second["countries"] == ["Germany", "United States"]
    assert run_cli(capsys, "project-grouper-input", "--run", run) == (0, {"question": given["question"], "part": 1,
                                                                          "parts": 1, "facts": given["facts"]})


def test_the_grouper_input_part_2_follows_part_1(tmp_path, capsys):
    run = grouping_run(tmp_path, [{"site": f"Plant {number}", "country": "US"} for number in range(1, 121)])
    whole = projects.grouper_input(run)
    code, first = run_cli(capsys, "project-grouper-input", "--run", run)
    assert code == 0 and first == run_cli(capsys, "project-grouper-input", "--run", run, "--part", 1)[1]
    assert first["parts"] >= 2 and first["part"] == 1 and first["question"] == whole["question"]
    printed = [first] + [run_cli(capsys, "project-grouper-input", "--run", run, "--part", number)[1]
                         for number in range(2, first["parts"] + 1)]
    assert all(given["parts"] == first["parts"] and "question" not in given for given in printed[1:])
    assert [fact["id"] for given in printed for fact in given["facts"]] == [f"F{n}" for n in range(1, 121)]
    assert [fact for given in printed for fact in given["facts"]] == whole["facts"]
    assert [given["part"] for given in printed] == list(range(1, first["parts"] + 1))
    assert all(given == projects.grouper_parts(run)[given["part"] - 1] for given in printed)


def test_the_grouper_input_refuses_a_part_it_does_not_have(tmp_path, capsys):
    run = grouping_run(tmp_path)
    code, out = run_cli(capsys, "project-grouper-input", "--run", run, "--part", 99)
    assert code == 1 and list(out) == ["problems", "explained"]
    assert "99" in out["problems"][0]["message"] and "1 part" in out["problems"][0]["message"]
    assert out["explained"][0]["known"] is True
    for wrong in ("0", "-1", "x", "1.5", "+2", " 2"):
        assert run_cli(capsys, "project-grouper-input", "--run", run, "--part", wrong)[0] == 2, wrong


def test_the_grouper_input_of_a_run_with_no_move_still_names_the_facts(tmp_path, capsys):
    run = grouping_run(tmp_path, moves=[], general=True)
    code, out = run_cli(capsys, "project-grouper-input", "--run", run)
    assert code == 0 and out == {"question": "Who adds capacity?", "part": 1, "parts": 1, "facts": []}


def test_the_grouper_reads_only_the_moves_inside_the_question(tmp_path):
    run = grouping_run(tmp_path, [{"in_question": "yes"}, {"in_question": "no"}, {}])
    fact = store.read_facts(run)["F3"]
    del fact["fields"]["in_question"]   # a move stored before the field existed counts as inside
    store.write_fact(run, fact)
    assert [given["id"] for given in projects.grouper_input(run)["facts"]] == ["F1", "F3"]
    assert list(projects.moves(run)) == ["F1", "F3"]
    projects.record_projects(run, [one_project("F1", "F3")], projects.GROUPER)   # F2 sits in no project


def test_status_says_whether_the_grouping_fits_the_facts(tmp_path):
    run = grouping_run(tmp_path)
    assert run_status(run, LENSES)["grouping"] == "none"
    projects.record_projects(run, [one_project("F1", "F2", "F3")], projects.GROUPER, NOW)
    assert run_status(run, LENSES)["grouping"] == "grouped"
    verify.withdraw_fact(run, "F2", "The same move as F1.")
    verify.settle(run)
    assert run_status(run, LENSES)["grouping"] == "outdated"
