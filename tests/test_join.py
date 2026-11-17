"""join-proposals: the extractors' saved answers joined into the bare list add-facts takes, unchanged; the lead only
names the merges. Everything here is invented."""
import json

import pytest

from radar import join
from radar.cli import main
from radar.demo import build_demo_run
from radar.explain import explain


def run_cli(capsys, *argv):
    code = main([str(part) for part in argv])
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    return code, json.loads(out)


def proposal(source_id, quote, translation=None, supporting=None, language="en"):
    return {"kind": "general", "statement": f"An invented statement from {source_id}.", "quote": quote,
            "quote_language": language, "quote_translation": translation, "source_id": source_id,
            "supporting": supporting or [], "primary_source": True, "certainty": "firm", "tentative_reason": None,
            "early_signal": False, "fields": None, "about_company": "Competitor A", "connections": []}


S1 = [proposal("S1", "Wettbewerber A baut zwei neue Abfülllinien im Werk Nord – „bis 2027“.",
               translation="Competitor A builds two new filling lines at Plant North, by 2027.", language="de"),
      proposal("S1", "Competitor A has signed a five-year contract to fill prefilled syringes.")]
S5 = [proposal("S5", "The application describes a new production hall for Competitor C on the north side.")]
S6 = [proposal("S6", "Competitor A will add two filling lines at Plant North in Country X.",
               supporting=[{"source_id": "S6", "quote": "Plant North is the largest site of the company."}])]


@pytest.fixture
def run(tmp_path):
    folder = build_demo_run(tmp_path / "runs", stage="sources")
    (folder / "proposals").mkdir()
    for source_id, proposals in (("S1", S1), ("S5", S5), ("S6", S6)):
        answer = {"proposals": proposals, "notes": {"nothing_found": False, "repeats": None, "doubts": ["A doubt."],
                                                    "instructions_in_source": []}}
        (folder / "proposals" / f"{source_id}.json").write_text(json.dumps(answer, ensure_ascii=False),
                                                                encoding="utf-8")
    return folder


def merges_file(run, merges):
    path = run / "proposals" / "merges.json"
    path.write_text(json.dumps(merges), encoding="utf-8")
    return path


def test_joined_proposals_are_unchanged(run, capsys):
    out = run / "proposals" / "all.json"
    code, printed = run_cli(capsys, "join-proposals", "--run", run, "--sources", "S1,S6", "--out", out)
    assert (code, printed) == (0, {"written": 3, "folded": 0, "out": str(out)})
    joined = json.loads(out.read_text(encoding="utf-8"))
    assert joined == S1 + S6
    assert [p["quote"] for p in joined] == [p["quote"] for p in S1 + S6]
    assert joined[0]["quote"].encode("utf-8") == S1[0]["quote"].encode("utf-8")
    assert "notes" not in out.read_text(encoding="utf-8")


def test_a_fold_moves_the_quote_into_supporting(run, capsys):
    out = run / "proposals" / "all.json"
    merges = merges_file(run, [{"keep": "S6#1", "fold": ["S1#1", "S5#1"]}])
    code, printed = run_cli(capsys, "join-proposals", "--run", run, "--sources", "S1,S5,S6", "--merges", merges,
                            "--out", out)
    assert (code, printed) == (0, {"written": 2, "folded": 2, "out": str(out)})
    joined = json.loads(out.read_text(encoding="utf-8"))
    keeper = dict(S6[0], supporting=S6[0]["supporting"] + [
        {"source_id": "S1", "quote": S1[0]["quote"], "quote_translation": S1[0]["quote_translation"]},
        {"source_id": "S5", "quote": S5[0]["quote"]}])   # a null translation gives no key
    assert joined == [S1[1], keeper]


def test_only_the_named_sources_are_joined(run, capsys):
    out = run / "proposals" / "all-2.json"
    code, printed = run_cli(capsys, "join-proposals", "--run", run, "--sources", "S5", "--out", out)
    assert (code, printed["written"]) == (0, 1)
    assert json.loads(out.read_text(encoding="utf-8")) == S5
    assert join.join(run, ["S6", "S1"], []) == S6 + S1   # the order of --sources, then each answer's own


def test_a_source_without_a_saved_answer_writes_nothing(run, capsys):
    out = run / "proposals" / "all.json"
    code, printed = run_cli(capsys, "join-proposals", "--run", run, "--sources", "S1,S2", "--out", out)
    assert code == 1 and not out.exists()
    assert [p["message"] for p in printed["problems"]] == [
        f"{join.NO_ANSWER} S2: proposals/S2.json is not there"]
    assert all(entry["known"] for entry in printed["explained"])


@pytest.mark.parametrize("merges, stem, ref", [
    ([{"keep": "S6#1", "fold": ["S1#1", "S1#3"]}], join.NO_PROPOSAL, "S1#3"),
    ([{"keep": "S6#1", "fold": ["S99#1"]}], join.NO_PROPOSAL, "S99#1"),
    ([{"keep": "S6#1", "fold": ["S1#2"]}, {"keep": "S5#1", "fold": ["S1#2"]}], join.NAMED_TWICE, "S1#2"),
    ([{"keep": "S6#1", "fold": ["S6#1"]}], join.INTO_ITSELF, "S6#1")])
def test_a_bad_merge_writes_nothing(run, capsys, merges, stem, ref):
    out = run / "proposals" / "all.json"
    code, printed = run_cli(capsys, "join-proposals", "--run", run, "--sources", "S1,S5,S6",
                            "--merges", merges_file(run, merges), "--out", out)
    assert code == 1 and not out.exists()
    assert [p["message"] for p in printed["problems"]] == [f"{stem}: {ref}"]
    assert all(entry["known"] for entry in printed["explained"])


@pytest.mark.parametrize("sources", ["S1,,S6", "S1,S1", "../S1", "s1"])
def test_sources_that_are_not_plain_distinct_ids_are_wrong_use(run, capsys, sources):
    out = run / "proposals" / "all.json"
    code, printed = run_cli(capsys, "join-proposals", "--run", run, "--sources", sources, "--out", out)
    assert code == 2 and list(printed) == ["error"] and not out.exists()


@pytest.mark.parametrize("merges", [{"keep": "S6#1"}, [{"keep": "S6#1", "fold": []}],
                                    [{"keep": "S6#1", "fold": ["S1#0"]}], [{"keep": "S6", "fold": ["S1#1"]}],
                                    [{"keep": "S6#1", "fold": ["S1#1"], "why": "same"}]])
def test_a_merges_file_of_the_wrong_form_is_wrong_use(run, capsys, merges):
    out = run / "proposals" / "all.json"
    code, printed = run_cli(capsys, "join-proposals", "--run", run, "--sources", "S1,S6",
                            "--merges", merges_file(run, merges), "--out", out)
    assert code == 2 and list(printed) == ["error"] and not out.exists()


def test_the_output_is_accepted_by_add_facts(run, capsys):
    out = run / "proposals" / "all.json"
    merges = merges_file(run, [{"keep": "S6#1", "fold": ["S1#1"]}])
    assert run_cli(capsys, "join-proposals", "--run", run, "--sources", "S1,S5,S6", "--merges", merges,
                   "--out", out)[0] == 0
    code, printed = run_cli(capsys, "add-facts", "--run", run, "--file", out)
    assert printed["refused"] == [] and code == 0 and len(printed["added"]) == 3


def test_every_problem_message_has_its_explanation():
    for stem in (join.NO_ANSWER, join.NOT_AN_ANSWER, join.NO_PROPOSAL, join.NAMED_TWICE, join.INTO_ITSELF):
        assert explain(join.Problem(None, None, f"{stem}: S1#1"))["known"], stem
