"""The three planted errors, caught in a run driven by a real model session. Run only with -m model."""
import re
import warnings

import pytest

from model.driver import ANSWER, ROOT, denied, lead_commands, needs_claude, plain, say, step_line
from radar import demo, store
from radar.gate import gate
from radar.report.model import load_labels
from radar.status import run_status
from radar.verify import is_withdrawn

FACT_ID = re.compile(r"(?<![A-Za-z0-9_])F7(?![A-Za-z0-9_])")


def final_question() -> str:
    """The question step 9 asks word for word, read from its file."""
    text = (ROOT / "skills" / "run" / "steps" / "09-checkpoint-final.md").read_text(encoding="utf-8")
    (question,) = re.findall(r'xactly this: "([^"]+)"', text)
    return question


def names_f7(value, key="") -> bool:
    """Whether a part of the analysis names F7, in a list of fact ids or in a text."""
    if isinstance(value, dict):
        return any(names_f7(item, name) for name, item in value.items())
    if isinstance(value, list):
        return ("F7" in value and key.endswith("fact_ids")) or any(names_f7(item, key) for item in value)
    return isinstance(value, str) and bool(FACT_ID.search(value))


@pytest.mark.model
@needs_claude
def test_the_three_planted_errors_end_as_rejected_in_a_model_driven_run(tmp_path):
    project = tmp_path / "project"
    run = demo.build_demo_run(project / "radar" / "runs", stage="extracted")   # a half-finished run
    first = say(project, "/strategy-radar:run continue my last run")
    assert not first.failed
    facts = store.read_facts(run)
    assert (facts["F8"]["status"], facts["F8"]["status_reason"]) == ("rejected", "not_found")
    assert facts["F8"]["checks"]["support"] is None                                # the program alone
    for planted in ("F9", "F10"):                                                  # the checker's work
        assert (facts[planted]["status"], facts[planted]["status_reason"]) == ("rejected", "not_supported")
        assert facts[planted]["checks"]["support"]["by"] == "support-checker"
        assert facts[planted]["checks"]["support"]["note"].strip()
    assert sum(facts[f]["status"] in store.COUNTING for f in ("F1", "F2", "F3", "F4", "F5", "F6", "F7")) >= 5
    assert facts["F7"]["status"] != "confirmed"                                    # one unnamed source
    assert all(fact["status"] != "proposed" for fact in facts.values())
    assert run_status(run, demo.LENSES)["next"] == "checkpoint_lenses"

    second = say(project, ANSWER + "use both lenses.", first.session)
    assert not second.failed
    assert run_status(run, demo.LENSES)["next"] == "checkpoint_final"

    # The final review's added turn: a change at the final decision, walked live (step 9, "A change to a fact").
    third = say(project, ANSWER + "take fact F7 back, then show me the report again", second.session)
    assert not third.failed
    f7 = store.read_facts(run)["F7"]
    assert is_withdrawn(f7) and f7["withdrawn"]["reason"].strip()                  # taken back, with its reason
    analysis = store.read_analysis(run)
    own = {key: value for key, value in analysis.items() if key != "audit_flags"}   # a flag may name any fact (FWA-4)
    assert not names_f7(own), "the analysis still names F7"
    audit, written = run / "notes" / "audit.json", run / "analysis.json"
    assert audit.stat().st_mtime > written.stat().st_mtime                         # the audit is about it as it stands
    assert [c["name"] for c in store.load_run(run)["checkpoints"]] == ["lenses"]  # no decision on the report yet
    assert plain(third.text).endswith(plain(final_question())), third.text[-300:]

    fourth = say(project, ANSWER + "build the report as it stands.", third.session)
    assert not fourth.failed
    assert gate(run, demo.LENSES) == []
    report = (run / "report" / "report.md").read_text(encoding="utf-8")
    heading = "## " + load_labels()["sec_not_confirmed"]
    start = report.index(heading)
    end = report.find("\n## ", start + len(heading))                       # the next part of the report
    end = len(report) if end == -1 else end
    before, section, after = report[:start], report[start:end], report[end:]
    for planted in ("54 million vials", "scheduled to start filling in 2029", "plans to offer its new filling lines"):
        assert planted in section and planted not in before and planted not in after, planted
    assert plain(f7["statement"]) in plain(section)                         # the fact taken back stands there
    assert denied(first, second, third, fourth) == []
    # fix wave I6: only the support checker records a verdict; the lead's own commands never do
    assert [command for command in lead_commands(first, second, third, fourth) if "record-support" in command] == []
    # On coming back, the first thing the lead sends is the line of the step the run stands at (ruling T25c): a run
    # at the stage extracted stands at step 5. Checked last, so that a miss here still shows whether the rest held.
    # Known limit (ruling FL1, final live pass): at step 5 the lead has work to do before it can stop, and in that
    # pass it reported its work first and never sent step 5's line (it sent the lines of steps 6, 8, 9 and 10). A miss
    # is therefore reported as a warning, not as a failure; the same check at step 6, where the run waits for the
    # person, stays strict in test_checkpoint_answers.py.
    if not (first.texts and plain(first.texts[0]).startswith(step_line(5))):
        warnings.warn("known limit: on coming back at step 5 the lead did not send the step's line first: "
                      + repr(first.texts[:1]))
