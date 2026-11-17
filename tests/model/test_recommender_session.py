"""The lens recommender at the first stop, driven by a real model session. WRITTEN, NOT RUN: it costs real usage.

Test layer 2 of the design: one real session on the invented demo pack, up to the first decision (step 6). It checks
that the run still stops and records nothing until the person answers, that the advisor's list passes the form
check, that each of the two readers recorded verdicts only under its own name, that the lead recorded nothing, and
that the first stop shows the recommendation as unchecked advice. The session prints its cost (`cost` in the line
the driver prints), which is what section 11 of the design needs in place of its guessed figures.

Not checked here, because a session cannot be made to show it: that the fallback holds when a helper's model is not
available to the account, and whether the recommendation is any good (an answer key of the person's, not a test).
A model can answer differently another time; a first run may need the checks below adjusted to what Claude Code
really does. Run only with -m model.
"""
import json
import warnings

import pytest

from model.driver import ROOT, denied, lead_commands, needs_claude, plain, say, step_line
from radar import demo, recommend, store
from radar.demo.build import QUESTION
from radar.lens_view import run_view
from radar.schema import check_data
from radar.status import run_status

NOT_CHECKED = "The recommendation is the advisor's suggestion and is not checked"


@pytest.mark.model
@needs_claude
def test_the_first_stop_shows_a_recommendation_as_unchecked_advice_and_records_no_decision(tmp_path):
    project = tmp_path / "project"
    run = demo.build_demo_run(project / "radar" / "runs", stage="checked")
    assert recommend.read_record(run) is None                                      # nothing is recommended yet
    first = say(project, "/strategy-radar:run continue my last run")
    assert not first.failed
    assert denied(first) == []

    # the run stopped at the decision and answered nothing for the person
    status = run_status(run, demo.LENSES)
    assert status["next"] == "checkpoint_lenses" and status["waiting_for_person"] is True
    assert store.load_run(run)["checkpoints"] == []
    assert "Which lenses should I use?" in first.text

    # the advisor recorded a list that passes the form check, under its own name, for this run's question
    record = recommend.read_record(run)
    assert record is not None, "the lens advisor recorded no list"
    assert record["by"] == recommend.ADVISOR and record["question"] == QUESTION
    assert len(record["entries"]) <= recommend.MAX_ENTRIES
    lens_ids = {path.stem for path in demo.LENSES.glob("*.json")}
    for entry in record["entries"]:
        assert entry["lens"] in lens_ids
        assert recommend.copied_from(entry["question_part"], QUESTION), entry["question_part"]
    assert check_data(run, demo.LENSES) == []
    view = run_view(run, demo.LENSES)
    assert view["stale"] is False and view["damaged"] is False

    # each reader recorded only under its own name, and only for links of the list
    links = {(entry["lens"], fact) for entry in record["entries"] for fact in entry["facts"]}
    assert {check["by"] for check in record["link_checks"]} <= set(recommend.READERS)
    assert {(check["lens"], check["fact"]) for check in record["link_checks"]} <= links
    for check in record["link_checks"]:
        assert check["verdict"] in recommend.VERDICTS and (check["verdict"] == "bears" or check["note"].strip())
    for reader in recommend.READERS:
        read = {(check["lens"], check["fact"]) for check in record["link_checks"] if check["by"] == reader}
        if read != links:                  # a reader that failed leaves its links unread: a warning, not a failure
            warnings.warn(f"{reader} read {len(read)} of {len(links)} links")

    # the models in the record are the ones the settings file sets, said as "set to", not "ran on"
    models = json.loads((ROOT / "settings" / "models.json").read_text(encoding="utf-8"))
    assert record["models_set_to"] == {name: models[name] for name in recommend.MODEL_NAMES}

    # the lead recorded neither the list nor a verdict: only the helpers do
    commands = lead_commands(first)
    assert [c for c in commands if "record-lens-recommendation" in c or "record-link-check" in c] == []

    # the first stop says the list is unchecked advice, and shows every lens on offer
    said = plain(first.text)
    assert NOT_CHECKED in said, "the stop does not say the recommendation is not checked"
    for lens_file in demo.LENSES.glob("*.json"):
        assert json.loads(lens_file.read_text(encoding="utf-8"))["name"] in said, lens_file.name
    assert "invented for practice" in said.lower()                                # the two demo lenses show no level
    assert plain(first.texts[0]).startswith(step_line(6)), first.texts[:2]
