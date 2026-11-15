"""Review Focus 3, driven by a real model session: the notice comes before any private run. Run only with -m model."""
import json
import re
import shutil

import pytest

from model.driver import ROOT, denied, needs_claude, only_run, plain, say
from radar import demo, store
from radar.demo.build import QUESTION
from radar.status import list_runs

ASK = "Do you confirm this? Please answer yes to start a private run."


def decision_question(step_file: str) -> str:
    """The question a decision step asks word for word, read from its file ("... exactly this: \"...\"")."""
    text = (ROOT / "skills" / "run" / "steps" / step_file).read_text(encoding="utf-8")
    (question,) = re.findall(r'xactly this: "([^"]+)"', text)
    return question


@pytest.mark.model
@needs_claude
def test_the_notice_is_shown_before_any_private_run_exists(tmp_path):
    project = tmp_path / "project"
    (project / "material").mkdir(parents=True)
    shutil.copy(demo.SOURCES / "private" / "s7_example_pharma_internal_memo.txt", project / "material" / "memo.txt")
    first = say(project, f"/strategy-radar:run Start a private run with the demo pack and my own memo in "
                         f"material/memo.txt. Question: {QUESTION} I confirm the data flow.")
    assert not first.failed
    runs = project / "radar" / "runs"
    assert list_runs(runs) == []                                             # nothing was started
    assert not runs.is_dir() or not any(path.is_dir() for path in runs.iterdir())
    assert store.PRIVATE_NOTICE_TEXT in plain(first.text)                   # the program's text, word for word
    assert plain(first.text).endswith(ASK)                                    # the notice's question comes last
    said = plain(" ".join(first.texts))
    for step_file in ("06-checkpoint-lenses.md", "09-checkpoint-final.md"):  # no decision of the run is asked
        assert plain(decision_question(step_file)) not in said, step_file
    written = sorted(path.relative_to(project).as_posix() for path in (project / "radar").rglob("*") if path.is_file())
    assert written == ["radar/inbox/new-run.json"]                           # no source, no copy before the yes
    assert denied(first) == []
    second = say(project, "Yes, I confirm.", first.session)
    assert not second.failed
    assert denied(second) == []
    run = only_run(project)
    record = store.load_run(run)
    assert record["mode"] == "private" and record["private_acknowledged_at"]
    assert record["private_acknowledged_words"] == "Yes, I confirm."          # fix wave A21: the person's own words
    assert not store.is_demo_private_run(record)                             # not the invented practice run
    assert json.loads((project / "radar" / "inbox" / "new-run.json").read_text(encoding="utf-8")) == {}   # M14
    sources = store.read_sources(run)
    assert sources == {} or all(s["provenance"] for s in sources.values() if s["data_class"] != "public")
    # fix wave I7: the memo is not saved before the person has answered the questions about it (the warning of an
    # invented pack and the three questions of private mode come first), and never as public
    memo = (project / "material" / "memo.txt").read_text(encoding="utf-8")
    passages = [" ".join(paragraph.split()) for paragraph in memo.split("\n\n") if len(paragraph) > 60]
    copies = [" ".join(path.read_text(encoding="utf-8").split()) for path in (run / "copies").glob("*.txt")] \
        if (run / "copies").is_dir() else []
    assert not [passage for passage in passages for copy in copies if passage in copy], "the memo was saved"
    for source in sources.values():
        if source["data_class"] == "public":
            copy = " ".join((run / source["copy_file"]).read_text(encoding="utf-8").split())
            assert not [passage for passage in passages if passage in copy], "the memo was saved as public"
