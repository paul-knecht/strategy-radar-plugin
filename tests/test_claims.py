"""claim-matcher-input and record-claim-groups: the claim matcher reads this round's proposals and sends groups of
proposals from different sources that state the same claim; the program checks them and writes proposals/merges.json
in the form join-proposals reads. Everything here is invented."""
import io
import json

import pytest

from radar import claims, join, parts, store, verify
from radar.cli import main
from radar.explain import explain
from radar.schema import Problem
from helpers import PERMIT_TEXT, add_source, early_signal_proposal, make_run, proposal

TEXT_A = "The expansion adds two high-speed syringe lines for customers, starting in 2028."
TEXT_B = "Competitor A confirmed two new syringe lines will open in 2028, the paper reported."
GENERAL = proposal(kind="general", fields=None, primary_source=True,
                   statement="Competitor A says the new lines are for outside customers.",
                   quote="the new lines are for customers outside the company")


def save_answer(run, source_id, proposals):
    (run / "proposals").mkdir(exist_ok=True)
    answer = {"proposals": proposals, "notes": {"nothing_found": False, "repeats": None, "doubts": [],
                                                "instructions_in_source": []}}
    (run / "proposals" / f"{source_id}.json").write_text(json.dumps(answer, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def run(tmp_path):
    """S1 the company's release, S2 a trade paper, S3 a permit; each with a saved answer."""
    folder = make_run(tmp_path)
    add_source(folder, TEXT_A, publisher="Competitor A")
    add_source(folder, TEXT_B, publisher="Trade Paper")
    add_source(folder, PERMIT_TEXT, publisher="Planning Office", type="permit")
    save_answer(folder, "S1", [proposal(source_id="S1"), {**GENERAL, "source_id": "S1"}])
    save_answer(folder, "S2", [proposal(source_id="S2",
                                        quote="Competitor A confirmed two new syringe lines – „2028“.")])
    save_answer(folder, "S3", [early_signal_proposal(source_id="S3"),
                               {**early_signal_proposal(source_id="S3"), "early_signal": False}])
    return folder


def merges(run):
    return run / "proposals" / "merges.json"


def run_cli(capsys, *argv, stdin=None, monkeypatch=None):
    if stdin is not None:
        monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(stdin.encode("utf-8")), encoding="utf-8"))
    code = main([str(part) for part in argv])
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    return code, json.loads(out)


# --- the input --------------------------------------------------------------------------------------------------------

def test_the_input_lists_each_proposal_with_its_place_and_quote(run, capsys):
    given = claims.matcher_input(run, ["S1", "S2"])
    assert given["question"] == "Who adds capacity?"
    assert [p["place"] for p in given["proposals"]] == ["S1#1", "S1#2", "S2#1"]
    first, general, second = given["proposals"]
    assert first == {"place": "S1#1", "source_id": "S1", "publisher": "Competitor A", "date": "2026-05-14",
                     "kind": "capacity_move", "statement": proposal()["statement"], "quote": proposal()["quote"],
                     "early_signal": False,
                     "fields": {"company": "Competitor A", "site": "Plant North", "size_value": "2",
                                "size_unit": "lines", "announced": "2026-05-14",
                                "planned_start": "2028"}}
    assert general["fields"] is None and second["publisher"] == "Trade Paper"
    assert second["quote"] == "Competitor A confirmed two new syringe lines – „2028“."   # character for character
    code, printed = run_cli(capsys, "claim-matcher-input", "--run", run, "--sources", "S1,S2")
    assert code == 0 and printed == {"question": given["question"], "part": 1, "parts": 1,
                                     "proposals": given["proposals"]}


def test_the_input_marks_a_permit_as_an_early_signal_even_unmarked(run):
    assert [p["early_signal"] for p in claims.matcher_input(run, ["S3"])["proposals"]] == [True, True]


def test_the_input_comes_in_parts_under_the_limit(run, capsys):
    many = [proposal(source_id="S1", statement=f"Competitor A will add line {n} at Plant North. " + "x" * 400)
            for n in range(100)]
    save_answer(run, "S1", many)
    found = claims.matcher_parts(run, ["S1"])
    assert len(found) > 1 and all(len(json.dumps(part)) < parts.PART_LIMIT for part in found)
    assert [p["place"] for part in found for p in part["proposals"]] == [f"S1#{n}" for n in range(1, 101)]
    assert "question" in found[0] and "question" not in found[1]
    code, printed = run_cli(capsys, "claim-matcher-input", "--run", run, "--sources", "S1", "--part", "2")
    assert code == 0 and printed == found[1]
    code, printed = run_cli(capsys, "claim-matcher-input", "--run", run, "--sources", "S1", "--part", "99")
    assert code == 1 and printed["problems"][0]["message"].startswith(parts.NO_SUCH_PART)


def test_a_source_joined_earlier_is_not_in_the_input(run):
    places = [p["place"] for p in claims.matcher_input(run, ["S2"])["proposals"]]
    assert places == ["S2#1"]   # S1 was joined in an earlier round: its saved answer is still there, and left out
    assert claims.record_groups(run, ["S2"], [{"keep": "S2#1", "fold": ["S1#1"]}], claims.MATCHER) == [
        Problem(None, "merges[0].fold", f"{join.NO_PROPOSAL}: S1#1")]
    assert not merges(run).exists()


def test_a_source_without_a_saved_answer_is_a_problem(run, capsys):
    code, printed = run_cli(capsys, "claim-matcher-input", "--run", run, "--sources", "S1,S4")
    assert code == 1 and printed["problems"][0]["message"].startswith(join.NO_ANSWER)


# --- recording the groups ---------------------------------------------------------------------------------------------

def test_groups_become_merges_join_reads(run, capsys, monkeypatch):
    code, printed = run_cli(capsys, "record-claim-groups", "--run", run, "--sources", "S1,S2",
                            "--by", "claim-matcher", "--list-stdin", stdin="keep: S1#1\nfold: S2#1\n",
                            monkeypatch=monkeypatch)
    assert (code, printed) == (0, {"recorded": True, "problems": [], "explained": []})
    written = json.loads(merges(run).read_text(encoding="utf-8"))
    assert written == [{"keep": "S1#1", "fold": ["S2#1"]}]
    joined = join.join(run, ["S1", "S2"], written)
    assert len(joined) == 2
    assert joined[0]["supporting"] == [{"source_id": "S2",
                                        "quote": "Competitor A confirmed two new syringe lines – „2028“."}]


def test_the_line_form_reads_blocks_and_refuses_what_it_cannot_read():
    assert claims.parse_group_lines([]) == []
    assert claims.parse_group_lines(["", "keep: S6#1", "fold: S2#3, S9#1", "", "", "fold: S1#1", "keep: S4#2"]) == [
        {"keep": "S6#1", "fold": ["S2#3", "S9#1"]}, {"keep": "S4#2", "fold": ["S1#1"]}]
    for lines in (["keep S6#1", "fold: S2#3"], ["keep: S6#1", "fold: S2#3", "why: same"],
                  ["keep: S6#1", "keep: S6#2", "fold: S2#3"], ["keep: S6#1"], ["keep: S6#1", "fold:"],
                  ["keep: S6#1", "fold: S2#3,,S2#4"], ["keep: S6", "fold: S2#3"], ["keep: S6#1", "fold: S2#0"],
                  ["keep: S6#1, S6#2", "fold: S2#3"]):
        with pytest.raises(ValueError):
            claims.parse_group_lines(lines)


@pytest.mark.parametrize("lines", ["keep S1#1\nfold: S2#1\n", "keep: S1#1\n"])
def test_lines_that_break_the_form_are_wrong_use(run, capsys, monkeypatch, lines):
    code, printed = run_cli(capsys, "record-claim-groups", "--run", run, "--sources", "S1,S2", "--by",
                            "claim-matcher", "--list-stdin", stdin=lines, monkeypatch=monkeypatch)
    assert code == 2 and list(printed) == ["error"] and not merges(run).exists()


def test_only_the_claim_matcher_may_record(run, capsys, monkeypatch):
    code, printed = run_cli(capsys, "record-claim-groups", "--run", run, "--sources", "S1,S2", "--by", "lead",
                            "--list-stdin", stdin="keep: S1#1\nfold: S2#1\n", monkeypatch=monkeypatch)
    assert code == 2 and list(printed) == ["error"] and not merges(run).exists()


def refused(run, sources, groups):
    """record_groups's problems; asserts that nothing was written."""
    problems = claims.record_groups(run, sources, groups, claims.MATCHER)
    assert problems and not merges(run).exists()
    assert all(explain(problem)["known"] for problem in problems), problems
    return [problem.message for problem in problems]


def test_a_place_that_does_not_exist_is_refused(run):
    assert refused(run, ["S1", "S2"], [{"keep": "S1#1", "fold": ["S2#2"]}]) == [f"{join.NO_PROPOSAL}: S2#2"]


def test_a_place_named_twice_is_refused(run):
    assert refused(run, ["S1", "S2", "S3"], [{"keep": "S1#1", "fold": ["S2#1"]},
                                             {"keep": "S1#2", "fold": ["S2#1"]}]) == [f"{join.NAMED_TWICE}: S2#1"]


def test_a_proposal_folded_into_itself_is_refused(run):
    assert refused(run, ["S1"], [{"keep": "S1#1", "fold": ["S1#1"]}]) == [f"{join.INTO_ITSELF}: S1#1"]


def test_two_places_of_the_same_source_are_refused(run):
    assert refused(run, ["S1", "S2"], [{"keep": "S1#1", "fold": ["S2#1", "S1#2"]}]) == [
        f"{claims.ONE_SOURCE}: S1#1 and S1#2"]


@pytest.mark.parametrize("place", ["S3#1", "S3#2"])   # marked, and unmarked but from a permit
def test_a_folded_early_signal_is_refused(run, place):
    assert refused(run, ["S1", "S3"], [{"keep": "S1#2", "fold": [place]}]) == [f"{claims.EARLY_SIGNAL}: {place}"]


@pytest.mark.parametrize("place", ["S3#1", "S3#2"])
def test_an_early_signal_that_stays_is_refused_too(run, place):
    assert refused(run, ["S1", "S3"], [{"keep": place, "fold": ["S1#2"]}]) == [f"{claims.EARLY_SIGNAL}: {place}"]


def test_a_unit_of_only_invisible_characters_states_nothing(run):
    save_answer(run, "S2", [proposal(source_id="S2", fields={"size_unit": "\u200b"})])
    assert claims.record_groups(run, ["S1", "S2"], [{"keep": "S1#1", "fold": ["S2#1"]}], claims.MATCHER) == []


def test_capacity_moves_of_different_companies_are_refused(run):
    save_answer(run, "S2", [proposal(source_id="S2", fields={"company": "Competitor B"})])
    assert refused(run, ["S1", "S2"], [{"keep": "S1#1", "fold": ["S2#1"]}]) == [
        f"{claims.OTHER_COMPANY}: S1#1 and S2#1"]


def test_another_spelling_of_one_company_is_one_company(run):
    save_answer(run, "S2", [proposal(source_id="S2", fields={"company": "Competitor A Inc.", "size_value": None,
                                                              "announced": " "})])
    assert claims.record_groups(run, ["S1", "S2"], [{"keep": "S1#1", "fold": ["S2#1"]}], claims.MATCHER) == []


@pytest.mark.parametrize("field, value", [("size_value", "3"), ("size_unit", "MW"), ("announced", "2026-06-01"),
                                         ("planned_start", "2029")])
def test_capacity_moves_that_state_different_details_are_refused(run, field, value):
    save_answer(run, "S2", [proposal(source_id="S2", fields={field: value})])
    assert refused(run, ["S1", "S2"], [{"keep": "S1#1", "fold": ["S2#1"]}]) == [
        f"{claims.OTHER_DETAIL} {field}: S1#1 and S2#1"]


@pytest.mark.parametrize("fields", [{"size_unit": "line"}, {"size_unit": "filling lines"}, {"size_value": "2.0"},
                                    {"size_unit": "Lines", "size_value": " 2 "}])
def test_one_size_written_another_way_is_one_size(run, fields):
    save_answer(run, "S2", [proposal(source_id="S2", fields=fields)])
    assert claims.record_groups(run, ["S1", "S2"], [{"keep": "S1#1", "fold": ["S2#1"]}], claims.MATCHER) == []


@pytest.mark.parametrize("company", [None, " "])
def test_a_capacity_move_that_names_no_company_is_refused(run, company):
    save_answer(run, "S2", [proposal(source_id="S2", fields={"company": company})])
    assert refused(run, ["S1", "S2"], [{"keep": "S1#1", "fold": ["S2#1"]}]) == [f"{claims.NO_COMPANY}: S2#1"]


def test_a_list_that_breaks_a_join_rule_and_a_group_rule_names_both(run):
    problems = claims.record_groups(run, ["S1", "S2", "S3"], [{"keep": "S1#1", "fold": ["S2#2"]},
                                                              {"keep": "S1#2", "fold": ["S3#1"]}], claims.MATCHER)
    assert problems == [Problem(None, "merges[0].fold", f"{join.NO_PROPOSAL}: S2#2"),
                        Problem(None, "merges[1]", f"{claims.EARLY_SIGNAL}: S3#1")]
    assert not merges(run).exists()


def test_no_groups_writes_an_empty_list(run, capsys, monkeypatch):
    code, printed = run_cli(capsys, "record-claim-groups", "--run", run, "--sources", "S2", "--by",
                            "claim-matcher", "--list-stdin", stdin="", monkeypatch=monkeypatch)
    assert (code, printed["recorded"]) == (0, True)
    assert json.loads(merges(run).read_text(encoding="utf-8")) == []
    assert join.join(run, ["S2"], []) == json.loads((run / "proposals" / "S2.json").read_text())["proposals"]


def test_a_second_record_replaces_the_first(run, capsys, monkeypatch):
    first = [{"keep": "S1#1", "fold": ["S2#1"]}]
    assert claims.record_groups(run, ["S1", "S2"], first, claims.MATCHER) == []
    code, printed = run_cli(capsys, "record-claim-groups", "--run", run, "--sources", "S1,S2", "--by",
                            "claim-matcher", "--list-stdin", stdin="keep: S1#1\nfold: S1#2\n",
                            monkeypatch=monkeypatch)
    assert code == 1 and printed["recorded"] is False and printed["explained"][0]["known"]
    assert json.loads(merges(run).read_text(encoding="utf-8")) == first   # a refused list leaves the first
    assert claims.record_groups(run, ["S1", "S2"], [], claims.MATCHER) == []
    assert json.loads(merges(run).read_text(encoding="utf-8")) == []


# --- independence stays settle's decision ---------------------------------------------------------------------------

def folded_and_settled(tmp_path, second_text):
    """S1 the company's release on its site, S2 a trade paper on another site holding `second_text`; each proposes the
    same move, not from the party itself; S2's is folded into S1's, joined, added, checked and settled."""
    run = make_run(tmp_path)
    add_source(run, TEXT_A, publisher="Competitor A")
    add_source(run, second_text, publisher="Trade Paper")
    move = dict(primary_source=False, quote="adds two high-speed syringe lines for customers")
    save_answer(run, "S1", [proposal(source_id="S1", **move)])
    save_answer(run, "S2", [proposal(source_id="S2", **{**move, "quote": "two high-speed syringe lines for customers, "
                                                                          "starting in 2028"})])
    assert claims.record_groups(run, ["S1", "S2"], [{"keep": "S1#1", "fold": ["S2#1"]}], claims.MATCHER) == []
    joined = join.join(run, ["S1", "S2"], json.loads(merges(run).read_text(encoding="utf-8")))
    assert len(joined) == 1
    fact = store.new_fact(run, joined[0])
    verify.check_quotes(run)
    verify.record_support(run, fact["id"], True, "support-checker", "")
    return verify.settle(run)[fact["id"]]


def test_a_folded_copy_of_the_same_text_stays_single_source(tmp_path):
    assert folded_and_settled(tmp_path / "same", TEXT_A) == "uncertain"
    second = TEXT_A.replace("The expansion", "The paper says the expansion")   # another text that holds the quote
    assert folded_and_settled(tmp_path / "other", second) == "confirmed"


def test_every_problem_message_has_its_explanation():
    for stem in (claims.ONE_SOURCE, claims.EARLY_SIGNAL, claims.OTHER_COMPANY, f"{claims.OTHER_DETAIL} size_value",
                 claims.NO_COMPANY):
        assert explain(Problem(None, "merges[0]", f"{stem}: S1#1 and S2#1"))["known"], stem
