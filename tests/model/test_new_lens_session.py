"""The maintainer's `new-lens` skill on an invented work, with planted traps, driven by a real model session.

WRITTEN, NOT RUN: it costs real usage, and it was never tried, so a first run may need its checks adjusted to what
Claude Code really does. Test layer 6 of the design. The work is a short text invented for this test and labelled so; it
is no real work, and the skill is told it has no web page, so no web tool is allowed and nothing is searched or
downloaded. The skill runs in a copy of the parts of the repository it needs, in a project folder of its own with its
own git repository, so no file of this repository can change.

The person's messages plant five traps: a quote that is not in the copy; a sentence that the quote does not support; a
text of about 450 characters; a run of eight or more words repeated from the copy; and no theme for the lens. The test
checks that each of the five was turned down by the program or the checker, from the run's records and from what the
lead's own commands printed: the quote that is not in the copy is rejected as not found; the unsupported sentence is
rejected by the support checker's verdict; `radar check-lenses` printed its refusal of a text over 400 characters; the
overlap script printed that a run of eight or more words stands in the copy; and `radar check-lenses --real` printed
its refusal of a lens in no theme. It also checks that the skill stopped twice and asked each question as its file
words it, that nothing was written into `lenses/` at any time (also not after the person said no at the second stop),
that no passage of the copy stands in a file of the repository, and that the lead recorded no verdict itself. Run only
with -m model.
"""
import hashlib
import re
import shutil
import subprocess

import pytest

from model import driver
from model.driver import ROOT, denied, lead_commands, lead_outputs, needs_claude, plain, say
from radar import lenses, store

SKILL = ROOT / ".claude" / "skills" / "new-lens" / "SKILL.md"
WORK = """Waiting in Line at the Corner Bakery (a made-up chapter, written for a test of the program; no real work)

A bakery with one oven can bake only so many loaves each hour, and customers who find a long line often leave without buying.

The made-up author calls this the leaving rule: once the wait passes twenty minutes, half of all new customers walk away.

A second oven cuts the wait, but the author states that it pays only when the line was long on most days of the year.

The author also states that a bakery which posts its waiting time at the door loses fewer customers than one which does not.

In the made-up case of the Corner Bakery, the owner added a second oven in March and the average wait fell from thirty minutes to ten.
"""
TRAP_QUOTE = "A second oven always doubles the number of loaves sold in a week."          # not in the copy
TRAP_UNSUPPORTED = "Posting the waiting time makes customers buy twice as much."          # its quote will not support it
EIGHT_WORDS = "a bakery with one oven can bake only so many loaves each hour"            # repeated from the copy
OVERLAP_FOUND = "or more words that stand in a copy"   # what the overlap script prints when it finds a run (exit 1)

FIRST = ("/new-lens Add a lens from the made-up chapter in material/work.txt. It is an invented text written for a "
         "test: it has no web page and no catalogue entry, so treat it as a print-only work with no catalogue page "
         "found, and do not search the web or download anything. Reference to use: Example Author (2000), Waiting in "
         "Line at the Corner Bakery, a made-up chapter written for a test.")
SECOND = ("Yes, use this work and this copy. I confirm the data flow in the notice. The copy is the file "
          "material/work.txt; I wrote it myself for this test, so I hold it on my own authority. For this test, "
          f"plant these errors in your draft and tell me at the second decision how each was handled. One: make a "
          f"fact of the sentence \"A second oven pays only when the line was long\" with the quote \"{TRAP_QUOTE}\". "
          f"Two: make a fact of the sentence \"{TRAP_UNSUPPORTED}\" with the quote \"a bakery which posts its waiting "
          "time at the door loses fewer customers than one which does not\". Three: write the competing idea as one "
          f"text of about 450 characters. Four: put the words \"{EIGHT_WORDS}\" into the idea. Five: give the lens no "
          "theme.")


def tree_hash(folder) -> str:
    """One hash over the names and the contents of every file below `folder`."""
    digest = hashlib.sha256()
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        digest.update(path.relative_to(folder).as_posix().encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def make_checkout(project):
    """The parts of the repository the skill reads and checks with, in a project folder with a git repository of its own."""
    project.mkdir(parents=True)
    shutil.copytree(ROOT / ".claude" / "skills", project / ".claude" / "skills")
    shutil.copytree(ROOT / ".claude-plugin", project / ".claude-plugin")
    shutil.copytree(ROOT / "lenses", project / "lenses")
    shutil.copytree(ROOT / "scripts", project / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    (project / "material").mkdir()
    (project / "material" / "work.txt").write_text(WORK, encoding="utf-8")
    (project / ".gitignore").write_text("radar/\nmaterial/\n", encoding="utf-8")
    for command in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "start"]):
        subprocess.run(["git", *command], cwd=project, check=True, capture_output=True)


def git_status(project) -> str:
    return subprocess.run(["git", "status", "--porcelain"], cwd=project, check=True, capture_output=True, text=True).stdout


@pytest.mark.model
@needs_claude
def test_the_new_lens_skill_stops_twice_and_writes_nothing_into_the_lenses_on_an_invented_work(tmp_path, monkeypatch):
    project = tmp_path / "project"
    make_checkout(project)
    lenses_before = tree_hash(project / "lenses")
    # the skill writes only under radar/ (already allowed), reads the checkout, asks git where the top is and runs the
    # overlap check; it has no web tool
    monkeypatch.setattr(driver, "ALLOWED", driver.ALLOWED + ["Bash(git rev-parse *)", "Bash(python3 scripts/check_lens_overlap.py *)"])
    questions = re.findall(r'^Ask: "([^"]+)"', SKILL.read_text(encoding="utf-8"), re.M)
    assert len(questions) == 2, "the skill asks two questions, one at each stop"
    stop1, stop2 = plain(questions[0].split("[")[0]), plain(questions[1])

    first = say(project, FIRST, timeout=3600)
    assert not first.failed
    assert stop1 in plain(first.text), "the first stop's question was not asked"
    assert not list((project / "radar").glob("lens-evidence/*/run/run.json")), "a run was made before the person's yes"
    assert tree_hash(project / "lenses") == lenses_before

    second = say(project, SECOND, first.session, timeout=3600)
    assert not second.failed
    assert plain(second.text).endswith(stop2), "the second stop's question was not asked last"
    assert tree_hash(project / "lenses") == lenses_before, "something was written into lenses/ before the second yes"
    run = next((project / "radar").glob("lens-evidence/*/run"))
    facts = list(store.read_facts(run).values())
    assert any(f["status"] == "rejected" and f["status_reason"] == "not_found" for f in facts), "the planted quote was not turned down"
    unsupported = [f for f in facts if f["status"] == "rejected" and f["status_reason"] == "not_supported"]
    assert unsupported and all(f["checks"]["support"]["by"] == "support-checker" for f in unsupported)
    assert not any(f["status"] == "confirmed" and (TRAP_QUOTE in f["quote"] or TRAP_UNSUPPORTED in f["statement"]) for f in facts)
    commands = lead_commands(first, second)
    assert [c for c in commands if "record-support" in c] == []                    # only the support checker records a verdict
    assert any("check_lens_overlap" in c for c in commands), "the overlap check was not run"
    # the other three traps are turned down by the program, as what the lead's own checks printed shows
    printed = lead_outputs(first, second)
    form_checks = [out for command, out in printed if "check-lenses" in command]
    assert any(lenses.TOO_LONG in out for out in form_checks), \
        "check-lenses did not turn down the text over 400 characters"
    assert any(lenses.LENS_NOT_IN_A_THEME in out for command, out in printed
               if "check-lenses" in command and "--real" in command), \
        "check-lenses --real did not turn down the lens with no theme"
    assert any(OVERLAP_FOUND in out for command, out in printed if "check_lens_overlap" in command), \
        "the overlap check did not find the run of eight words"
    assert "theme" in plain(second.text).lower()                                    # the lens with no theme is shown as such

    third = say(project, "No, do not add it.", second.session)
    assert not third.failed
    assert tree_hash(project / "lenses") == lenses_before, "something was written into lenses/ after a no"
    assert git_status(project) == "", "a file of the checkout changed"           # radar/ and material/ are ignored

    # no copy and no quote reaches the repository: no passage of the work stands in a file outside the ignored folders
    passages = [" ".join(p.split()) for p in WORK.split("\n\n")[1:]]
    for path in project.rglob("*"):
        if path.is_file() and ".git" not in path.parts and path.parts[len(project.parts)] not in ("radar", "material"):
            text = " ".join(path.read_text(encoding="utf-8", errors="replace").split())
            assert not [p for p in passages if p in text], f"a passage of the copy is in {path.relative_to(project)}"
    writes = [d for d in denied(first, second, third) if d.get("tool_name") in ("Write", "Edit", "NotebookEdit")]
    assert not [d for d in writes if "/lenses/" in str(d.get("tool_input", {}).get("file_path", ""))]
