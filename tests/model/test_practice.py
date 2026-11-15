"""The practice tour, driven by a real model session. Costs real usage: run only with -m model."""
import pytest

from model.driver import denied, needs_claude, plain, say
from radar import demo, store
from radar.explain import explain
from radar.gate import gate


@pytest.mark.model
@needs_claude
def test_the_practice_tour_ends_with_a_report_and_a_refused_build(tmp_path):
    project = tmp_path / "project"
    turn = say(project, "/strategy-radar:practice")
    assert not turn.failed
    assert denied(turn) == []
    practice = project / "radar" / "practice"
    assert (practice / "demo" / "report" / "report.html").is_file()
    assert (practice / "demo-tampered").is_dir()
    assert not (practice / "demo-tampered" / "report" / "report.html").exists()
    assert sorted(path.name for path in (project / "radar").iterdir()) == ["practice"]   # it writes nowhere else
    # M17: the first thing said is that everything is invented (a live lead once said "made up")
    assert turn.texts and ("invented" in turn.texts[0].lower() or "made up" in turn.texts[0].lower()), turn.texts[:1]
    said = plain(" ".join(turn.texts))                                       # a bold mark or a line break is no difference
    # M17: the number the saved copy gives for F8 (the quote says 54), and the checker's notes of F9 and F10
    assert "45" in said
    facts = store.read_facts(practice / "demo")
    for planted in ("F9", "F10"):
        assert plain(facts[planted]["checks"]["support"]["note"]) in said, planted
    # the person is told that the build was refused, in the program's plain words (explanations_en.json)
    refusals = [explain(problem)["what"] for problem in gate(practice / "demo-tampered", demo.LENSES)]
    assert refusals and all(plain(what) in said for what in refusals), refusals
