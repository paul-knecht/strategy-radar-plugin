"""Review Focus 2, driven by a real model session: a question back is not a decision. Run only with -m model."""
import pytest

from model.driver import ANSWER, denied, needs_claude, plain, say, step_line
from radar import demo, store


@pytest.mark.model
@needs_claude
def test_a_question_back_is_not_recorded_as_a_decision(tmp_path):
    project = tmp_path / "project"
    run = demo.build_demo_run(project / "radar" / "runs", stage="checked")
    first = say(project, "/strategy-radar:run continue my last run")
    assert not first.failed
    assert store.load_run(run)["checkpoints"] == []
    assert "Which lenses should I use?" in first.text
    second = say(project, ANSWER + "what would the second lens add for my question?", first.session)
    assert not second.failed
    assert store.load_run(run)["checkpoints"] == []
    assert "Which lenses should I use?" in second.text
    third = say(project, ANSWER + "use both lenses.", second.session)
    assert not third.failed
    assert [(c["name"], c["answered_by"], c["answer"]) for c in store.load_run(run)["checkpoints"]] == \
        [("lenses", "test", ANSWER + "use both lenses.")]                    # the whole message, word for word
    assert denied(first, second, third) == []
    # On coming back, the first thing the lead sends is the line of the step the run stands at (ruling T25c): a run
    # at the stage checked stands at step 6. Checked last, so that a miss here still shows whether the rest held.
    assert first.texts and plain(first.texts[0]).startswith(step_line(6)), first.texts[:2]
