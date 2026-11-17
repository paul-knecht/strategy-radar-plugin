"""What a program can check about the two model-driven tests that are written and not run (no model is started).

They are seven with the five that ran; the guide says so and says which two have not been run. These checks keep the
two honest: the planted traps of the invented work are what they claim to be, the questions the new-lens test looks
for are the two the skill asks, and nothing in either holds a character outside ASCII.
"""
import re

import pytest
from pathlib import Path

from model import test_new_lens_session as new_lens
from model import test_recommender_session as recommender
from plugin_helpers import ROOT, company_names_in
from test_plugin_shell import invisible_characters

FILES = (Path(new_lens.__file__), Path(recommender.__file__))


def words(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def test_the_skill_asks_the_two_questions_the_new_lens_test_looks_for():
    if not new_lens.SKILL.is_file():
        pytest.skip("the new-lens skill is the maintainer's and is not in the public copy")
    asked = re.findall(r'^Ask: "([^"]+)"', new_lens.SKILL.read_text(encoding="utf-8"), re.M)
    assert len(asked) == 2 and asked[0].startswith("Shall I use these works and copies")   # a batch of one, too
    assert asked[1].startswith("Shall I add these lenses to the plugin's lenses")


def test_the_planted_traps_are_what_they_claim_to_be():
    work = words(new_lens.WORK)
    assert words(new_lens.TRAP_QUOTE) not in work                   # a quote that is not in the copy
    assert words("a bakery which posts its waiting time at the door loses fewer customers than one which does not") in work
    assert words(new_lens.TRAP_UNSUPPORTED) not in work             # the sentence the quote does not support
    assert words(new_lens.EIGHT_WORDS) in work and len(new_lens.EIGHT_WORDS.split()) >= 8
    assert "made-up" in new_lens.WORK and "no real work" in new_lens.WORK


def test_the_invented_work_and_the_two_tests_hold_no_company_name_and_only_ascii():
    for path in FILES:
        text = path.read_text(encoding="utf-8")
        assert re.search(r"[^\x00-\x7f]", text) is None and invisible_characters(text) == [], path.name
        assert company_names_in(text) == [], path.name


def test_the_recommender_test_looks_for_the_sentence_the_first_stop_says():
    step = (ROOT / "skills" / "run" / "steps" / "06-checkpoint-lenses.md").read_text(encoding="utf-8")
    assert recommender.NOT_CHECKED + "; a doubt mark is advice." in step


def test_the_new_lens_test_changes_nothing_in_this_repository():
    text = Path(new_lens.__file__).read_text(encoding="utf-8")
    assert "make_checkout(project)" in text and "tmp_path / \"project\"" in text
    assert "ROOT / \"lenses\", project" in text            # lenses/ is only ever copied from, never written


def test_what_the_new_lens_test_looks_for_is_what_the_overlap_script_prints_for_the_planted_run(tmp_path):
    """Final review: the new-lens test reads the overlap script's printed line, so that line must be what the script
    really prints for a lens holding the planted run of eight words, with the exit code that is no pass."""
    import json
    import subprocess
    import sys
    copies = tmp_path / "copies"
    copies.mkdir()
    (copies / "S1.txt").write_text(new_lens.WORK, encoding="utf-8")
    lens = {"name": "A test lens", "idea": "The idea says " + new_lens.EIGHT_WORDS + ".", "suggests": "Look.",
            "limits": [], "competing_idea": "Another idea.", "questions": ["One?", "Two?", "Three?"], "originals": []}
    (tmp_path / "lens.json").write_text(json.dumps(lens), encoding="utf-8")
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_lens_overlap.py"), "--lens",
                           str(tmp_path / "lens.json"), "--copies", str(copies)], capture_output=True, text=True)
    assert done.returncode == 1 and new_lens.OVERLAP_FOUND in done.stdout, done.stdout + done.stderr


def test_the_guide_says_which_of_the_five_traps_the_new_lens_test_checks():
    from radar import lenses
    text = " ".join((ROOT / "docs" / "plugin.md").read_text(encoding="utf-8").split())
    assert "that each of the five is turned down" in text and "by the overlap check" in text
    source = Path(new_lens.__file__).read_text(encoding="utf-8")
    for needed in ("lenses.TOO_LONG", "lenses.LENS_NOT_IN_A_THEME", "OVERLAP_FOUND in out", '"not_found"',
                   '"not_supported"'):
        assert needed in source, needed
    assert lenses.TOO_LONG and lenses.LENS_NOT_IN_A_THEME
