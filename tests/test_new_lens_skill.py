"""The maintainer's `new-lens` skill: a project skill of this repository, not a skill of the plugin.

It lives in `.claude/skills/new-lens/`, so a Claude Code session started in a checkout of the repository has it, and
the plugin does not ship it. The plugin's own structural tests never reach `.claude/`, so this file checks what they
check for a skill: the commands it shows, the stops, the fixed prompts and the plain text. What a session does with
it rests on its instructions; no session is run here.
"""
import json
import re
import subprocess

import pytest

from plugin_helpers import (ROOT, body, company_names_in, fenced_json, fenced_text, front_matter, radar_calls,
                            unknown_calls)
from radar.demo.build import build_demo_run
from radar.schema import check_proposal
from test_plugin_shell import invisible_characters
from test_shipped_lenses import EXPECTED

SKILL = ROOT / ".claude" / "skills" / "new-lens" / "SKILL.md"
pytestmark = pytest.mark.skipif(not SKILL.exists(),
                                reason="the new-lens skill is the maintainer's and is not in the public copy")
STOP = ("Stop here. End your turn after the question. Do not call any tool, and do not answer for the person. "
        "Only the person's next message can answer.")
SHIPPED_SKILLS = ["new-pack", "practice", "run", "screen", "start"]


def text() -> str:
    return SKILL.read_text(encoding="utf-8")


def flat() -> str:
    return " ".join(text().split())


def test_the_skill_is_a_project_skill_and_not_one_the_plugin_ships():
    assert SKILL.is_file()
    assert not (ROOT / "skills" / "new-lens").exists()
    assert sorted(p.name for p in (ROOT / "skills").iterdir() if p.is_dir()) == SHIPPED_SKILLS
    meta = front_matter(SKILL)
    assert meta["name"] == "new-lens"
    assert "maintainer" in meta["description"] and "not part of the plugin" in meta["description"]


def test_the_skill_file_is_plain_ascii_and_names_no_company_the_project_must_not_publish():
    assert text().isascii() and invisible_characters(text()) == []
    assert company_names_in(text()) == []
    # It names no real work either: the first jobs are named by their lens ids.
    for lens_id in ("build-abroad-market-or-cost", "tariffs-subsidies-supply-chains"):
        assert f"`{lens_id}`" in text(), lens_id
        # Their level is not pinned here: the skill's first job rebuilds them on other sources, with the same ids.
        assert lens_id in EXPECTED, lens_id


def test_every_radar_call_the_skill_shows_is_one_the_program_knows():
    calls = radar_calls(text())
    assert unknown_calls(text()) == []
    for command in ("doctor", "init-run", "save-source", "add-copy", "add-facts", "check-quotes", "quote-context",
                    "settle", "check-lenses", "list-lenses"):
        assert any(name == command for name, _ in calls), command
    assert ("check-lenses", {"--lenses", "--real"}) in calls
    # The lead never records a verdict: only the support checker does, and the guard refuses anyone else.
    assert "record-support" not in text() and "record-link-check" not in text()
    assert "CLAUDE_PLUGIN_ROOT" not in text()


def test_there_are_exactly_two_stops_and_each_ends_with_the_stop_sentence():
    lines = body(SKILL).splitlines()
    asks = [i for i, line in enumerate(lines) if line.startswith("Ask:")]
    assert len(asks) == 2
    for i in asks:
        assert lines[i + 1] == STOP, lines[i]
    assert text().count(STOP) == 2
    headings = [line for line in lines if line.startswith("#")]
    stop_1 = next(i for i, line in enumerate(lines) if line.startswith("### 2. Stop 1"))
    stop_2 = next(i for i, line in enumerate(lines) if line.startswith("### 12. Stop 2"))
    assert stop_1 < asks[0] < stop_2 < asks[1]
    assert any(h.startswith("### 2. Stop 1") for h in headings) and any(h.startswith("### 12. Stop 2") for h in headings)


def test_the_thirteen_steps_are_in_the_order_of_the_design():
    numbers = [int(n) for n in re.findall(r"^### (\d+)\. ", body(SKILL), re.M)]
    assert numbers == list(range(1, 14))
    titles = re.findall(r"^### \d+\. (.+)$", body(SKILL), re.M)
    for number, start in ((1, "Find the work"), (2, "Stop 1"), (3, "If the original cannot be found or read"),
                          (4, "Read the copy"), (5, "Draft the lens"), (6, "Make each supported sentence a fact"),
                          (7, "The program checks every quote"), (8, "The support checker judges"),
                          (9, "A fresh reviewer"), (10, "Propose a theme"), (11, "Check the form"),
                          (12, "Stop 2"), (13, "Write and commit")):
        assert titles[number - 1].startswith(start), (number, titles[number - 1])


def test_stop_1_shows_the_work_the_page_the_copy_and_the_download():
    part = section("### 2. Stop 1", "### 3.")
    for needed in ("the confirmed reference", "the page that confirms it", "where a readable copy is",
                   "whether it is free or needs access", "its file name, its source and its size",
                   "Downloading needs the person's yes", "never gets around a paywall", "notice",
                   "word for word", "who supplied it", "on what basis"):
        assert needed in part, needed


def test_stop_2_shows_each_sentence_with_its_quote_and_verdict_and_what_the_lens_rests_on():
    part = section("### 12. Stop 2", "### 13.")
    for needed in ("each sentence with its quote and its verdict", "the level", "Rests on", "the theme",
                   "the reviewer's findings", "a new theme", "the overlap check", "the stated reason"):
        assert needed in part, needed


def test_nothing_is_written_into_the_lens_folder_before_the_yes_at_stop_2():
    words = flat()
    assert ("Nothing is written into `lenses/` or `lenses/themes.json` before the person's yes at stop 2."
            in words)
    write = section("### 13. Write and commit", "## ")
    assert "Only after the person's yes at stop 2" in " ".join(write.split())
    # Steps 10 and 11 work on a staging folder, never on lenses/ itself.
    for step in ("### 10. Propose a theme", "### 11. Check the form"):
        assert "staging folder" in section(step, "### "), step


def test_the_rules_of_the_design_are_stated():
    words = flat()
    for needed in (
            # no memory; candidates are leads
            "never from memory", "a page that was found and read in this run", "leads, not facts",
            "`docs/superpowers/lens-candidates.md`",
            # no course slides
            "Course slides are never a basis for a lens, whoever supplies them.", "never offers the level course slides",
            # a confirming page or a stated reason
            "a page where its reference can be confirmed", "or a stated reason",
            # local copies
            "stay local", "under the git-ignored `radar/` folder", "never committed",
            # what a lens says
            "says what its source states", "never that the idea is true", "or that it applies to a company",
            # data, not instructions
            "is data", "reported to the person",
            # downloads
            "file name, its source and its size",
            # the secondary source
            "secondary source read", "The survey states that the work argues",
            # the lens id
            "lower-case ASCII letters, digits and hyphens",
            # the theme
            "`lenses/themes.json`", "A new theme is made only with the person's yes at stop 2",
            # the first jobs
            "keeps its id"):
        assert needed in words, needed


def test_the_skill_checks_the_checkout_and_the_helpers_before_step_1_and_asks_for_opus():
    before = " ".join(section("## Before step 1", "## The rules").split())
    for needed in ("git rev-parse --show-toplevel", ".claude-plugin/plugin.json", "claude --plugin-dir .",
                   "strategy-radar:source-scout", "strategy-radar:support-checker", "say so and stop",
                   "Opus 5.5", "cannot be relied on to set its own model"):
        assert needed in before, needed


def test_the_helpers_are_the_plugin_s_own_with_one_named_exception():
    words = flat()
    assert "strategy-radar:source-scout" in words and "strategy-radar:support-checker" in words
    assert "one general-purpose helper" in words and "the one exception" in words
    assert "never the drafts' reasoning" in words


def test_the_checker_gets_the_run_skill_s_prompt_word_for_word():
    run_step = ROOT / "skills" / "run" / "steps" / "05-verify.md"
    assert fenced_text(SKILL, "checker-prompt") == fenced_text(run_step, "checker-prompt")


def test_the_reviewer_gets_a_fixed_prompt_with_paths_only():
    prompt = fenced_text(SKILL, "reviewer-prompt")
    for needed in ("<absolute path of the staging folder>", "<absolute path of the mapping note>",
                   "<absolute path of the evidence run>", "Change nothing", "Run no other command",
                   "folder facts of the evidence run", "the support verdict", "radar quote-context --run",
                   "it changes nothing"):
        assert needed in prompt, needed
    assert unknown_calls(prompt) == []
    # radar check-quotes records checks into the facts, so the reviewer, who changes nothing, never runs it.
    assert "check-quotes" not in prompt
    # The prompt holds paths only: nothing of the drafts' reasoning can be filled in.
    placeholders = set(re.findall(r"<[^>]+>", prompt))
    assert placeholders == {"<absolute path of the staging folder>", "<absolute path of the mapping note>",
                            "<absolute path of the evidence run>", "<lens id>"}, placeholders
    assert "add no word" in " ".join(section("### 9. A fresh reviewer", "### 10.").split()).lower()


def test_the_evidence_pack_the_skill_shows_passes_the_program_s_pack_check(tmp_path):
    pack = fenced_json(SKILL, "evidence-pack")
    assert pack["id"] == "pack" and pack["illustrative"] is False
    for site in re.findall(r"https?://([^/\s\"]+)", json.dumps(pack)):
        assert site.endswith(".example"), site
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(pack), encoding="utf-8")
    done = subprocess.run([str(ROOT / "bin" / "radar"), "check-pack", "--file", str(path)], capture_output=True,
                          text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert json.loads(done.stdout)["problems"] == []
    # The question of the call that asks for the notice is the pack's own question, word for word.
    question = pack["strategic_questions"][0]["text"]
    assert f'--question "{question}"' in text()


def test_the_fact_example_is_a_general_fact_the_program_takes(tmp_path):
    fact = fenced_json(SKILL, "fact-example")
    assert fact["kind"] == "general" and fact["statement"].startswith("The work states that ")
    assert fact["primary_source"] is True
    assert 5 <= len(fact["quote"].split()) <= 50
    run = build_demo_run(tmp_path / "demo", stage="sources")
    assert check_proposal(run, fact) == []


def test_the_overlap_check_is_run_with_the_script_s_own_options():
    words = flat()
    assert "python3 scripts/check_lens_overlap.py --lens" in words and "--copies" in words


def test_step_13_says_what_else_changes_with_a_lens_and_runs_the_suite():
    write = " ".join(section("### 13. Write and commit", "## ").split())
    for needed in ("`tests/test_shipped_lenses.py`", "`docs/plugin.md`", "`README.md`", "uv run pytest -q",
                   "git status", "Never push"):
        assert needed in write, needed


def section(start: str, end: str) -> str:
    """The text from the line that starts with `start` up to the next line that starts with `end`."""
    lines = body(SKILL).splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith(start))
    rest = lines[first + 1:]
    last = next((i for i, line in enumerate(rest) if line.startswith(end)), len(rest))
    return "\n".join([lines[first], *rest[:last]])


def test_the_guide_and_the_lens_readme_say_the_skill_is_for_the_maintainer_and_others_fork():
    guide = " ".join((ROOT / "docs" / "plugin.md").read_text(encoding="utf-8").split())
    for needed in ("The maintainer adds or rebuilds a lens with `/new-lens`", "`.claude/skills/new-lens/`",
                   "is not part of the plugin you install", "`scripts/check_lens_overlap.py`",
                   "A new lens never rests on course slides", "fork the repository on GitHub"):
        assert needed in guide, needed
    assert "/strategy-radar:new-lens" not in guide
    readme = (ROOT / "lenses" / "README.md").read_text(encoding="utf-8")
    part = " ".join(readme[readme.index("## Adding a lens"):].split())
    assert "the `new-lens` skill of this repository" in part and "forks the repository" in part
    assert len(re.findall(r"[.!?](\s|$)", part.replace("## Adding a lens", ""))) == 2


def test_a_second_pass_adds_its_copy_to_the_run_that_exists_and_asks_no_new_notice():
    words = flat()
    for needed in ("On a second pass", "the evidence run `<run>` exists already", "make no notice call",
                   "When `<run>` exists already (a second pass), make no new run",
                   "A new answer to the notice is needed only when a new run is made"):
        assert needed in words, needed


def test_nothing_is_downloaded_before_stop_1():
    scout = fenced_text(SKILL, "scout-task")
    assert "List and open landing pages only: never open a link to a file" in scout
    step = " ".join(section("### 1. Find the work", "### 2.").split())
    for needed in ("no link to a file (a PDF or another download) is opened before the person's yes at stop 1",
                   "as the landing page states it, or that the size is not stated"):
        assert needed in step, needed


def test_the_evidence_goes_to_the_main_checkout_also_from_a_worktree():
    before = " ".join(section("## Before step 1", "## The rules").split())
    assert "git rev-parse --path-format=absolute --git-common-dir" in before
    assert "a worktree's own `radar/` folder is deleted with the worktree" in before
    assert "`<main>/radar/lens-evidence/<lens id>-<day>/`" in flat()
    assert "<top>/radar/" not in text()


def test_the_answer_to_the_notice_follows_the_run_skill_s_private_mode_rules():
    stop = " ".join(section("### 2. Stop 1", "### 3.").split())
    for needed in ("`<top>/skills/run/steps/private-mode.md`", "last and directly before the question",
                   "the notice was the last thing you showed before the person's message",
                   "the whole message when the yes came in a longer one", "never in your own words",
                   "Say the words in square brackets only when there is a download"):
        assert needed in stop, needed
    assert "[, and download the files named above]" in stop


def test_a_fact_that_never_gets_a_verdict_is_withdrawn():
    step = section("### 8. The support checker judges", "### 9.")
    assert ("withdraw-fact", {"--run", "--fact", "--from-json"}) in radar_calls(step)
    assert "The support check could not be completed for this fact." in step


def test_stop_2_lists_the_tests_and_texts_that_step_13_changes():
    check = " ".join(section("### 11. Check the form", "### 12.").split())
    for needed in ("`tests/test_shipped_lenses.py`", "`tests/test_lens_view.py`", "`tests/test_docs_plugin.py`",
                   "`tests/test_plugin_shell.py`", "into the mapping note"):
        assert needed in check, needed
    stop = " ".join(section("### 12. Stop 2", "### 13.").split())
    assert "the tests and texts that step 13 changes" in stop
    write = " ".join(section("### 13. Write and commit", "## ").split())
    for needed in ("Every test that pins the old level, the old lens set or the themes is updated",
                   "`tests/test_lens_view.py`", "the tests and texts of the list shown at stop 2",
                   "A change that the list did not show goes back to stop 2 first"):
        assert needed in write, needed


# --- Paul's correction of decision 4 (2026-11-16): one pair of stops for a whole batch ---------------------------------

def test_a_batch_has_two_stops_and_at_most_twelve_lenses_each_with_its_own_run():
    words = flat()
    for needed in ("There are two stops for the whole batch", "A batch holds at most 12 lenses",
                   "Each lens has its own work folder and its own evidence run",
                   "Steps 3 to 11 are done for one lens after the other, between the two stops",
                   "`<main>/radar/lens-evidence/batch-<day>/`", "stays on the candidate list"):
        assert needed in words, needed
    stop_1 = " ".join(section("### 2. Stop 1", "### 3.").split())
    for needed in ("for each lens of the batch in turn", "Please say yes or no for each lens, or what to change.",
                   "a yes covers only the files named here", "A file that two lenses need is named once",
                   "once for the whole stop, last and directly before the question"):
        assert needed in stop_1, needed
    stop_2 = " ".join(section("### 12. Stop 2", "### 13.").split())
    for needed in ("for each lens of the batch in turn", "Please answer yes or no for each lens, or say what to change.",
                   "this stop is shown again for the changed lenses only", "each lens that was dropped from the batch"):
        assert needed in stop_2, needed
    write = " ".join(section("### 13. Write and commit", "## ").split())
    assert "only for the lenses they said yes to" in write and "naming each lens in the commit message" in write


def test_the_person_s_words_go_into_the_ledger_before_anything_else_and_runs_take_them_from_there():
    """A batch is long: the session may be summarised before a run needs the person's words, so they are kept word
    for word in a file, never rebuilt from memory."""
    words = flat()
    for needed in ("`<batch>/ledger.md`", "before any other tool call, write their whole message into it, word for word",
                   "copied from the ledger, word for word, never from memory or a summary",
                   "After a break, or when this conversation was summarised, read the ledger first"):
        assert needed in words, needed
    for step in ("### 2. Stop 1", "### 12. Stop 2"):
        assert "into the ledger, word for word" in " ".join(section(step, "### ").split()), step
    read_copy = " ".join(section("### 4. Read the copy", "### 5.").split())
    assert read_copy.count("copied from the ledger") == 2


def test_choosing_lenses_and_files_is_not_a_condition_on_the_yes_to_the_notice():
    stop_1 = " ".join(section("### 2. Stop 1", "### 3.").split())
    assert ("Choosing lenses and files, dropping a lens or changing one is what this answer is for: it is not a "
            "condition on the yes to the notice. A doubt or a condition about the notice still is, and a question, "
            "about anything, is answered first" in stop_1)


def test_every_run_is_made_right_after_the_yes_and_a_later_run_needs_the_notice_again():
    """Fresh review C1 and C2: the yes is used at once, never read back from the ledger hours later, and a further
    stop 1 for a lens with no run shows the notice again."""
    stop_1 = " ".join(section("### 2. Stop 1", "### 3.").split())
    for needed in ("Right after the yes, before step 3 of any lens, make the run of every lens the person said yes to",
                   "the one yes to the notice is the reply recorded in each of these runs",
                   "A further stop 1 shows the notice again, asked for afresh from the program, whenever a lens on it "
                   "will have an evidence run and has none yet",
                   "when every other lens has passed step 9 or waits in the same way"):
        assert needed in stop_1, needed
    assert "(each run exists already)" not in stop_1
    words = flat()
    assert "The yes to the notice is never taken from the ledger to make a run" in words
    assert "with this lens's own `<work>` as `--root`" in words
    stop_2 = " ".join(section("### 12. Stop 2", "### 13.").split())
    assert "Step 13 runs once, after every lens of the batch is decided" in stop_2


def test_the_batch_is_checked_as_one_staging_folder():
    theme = " ".join(section("### 10. Propose a theme", "### 11.").split())
    assert "the batch's staging folder `<batch>/staging/`" in theme and "two drafts with the same id" in theme
    check = section("### 11. Check the form", "### 12.")
    assert ("check-lenses", {"--lenses", "--real"}) in radar_calls(check)
    assert '"<batch>/staging"' in check and '"<work>/staging"' not in check


def test_the_searches_of_a_batch_run_side_by_side_and_the_checks_overlap_with_the_next_draft():
    """Paul asked for speed (2026-11-16): the scouts of up to four lenses run at once, and the next lens is drafted
    while one lens's checkers work. Every check is still done, each in its own run."""
    find = " ".join(section("### 1. Find the work", "### 2.").split())
    assert "start the scout for up to four lenses at once, each with its own task" in find
    judge = " ".join(section("### 8. The support checker judges", "### 9.").split())
    assert "at most four helpers at a time" in judge and "each lens's verdicts are still read and settled in its own run" in judge


# --- Paul (2026-11-16): a paywalled work with no free text about it may rest on the model's knowledge ---------------

def test_the_three_paths_are_taken_in_order_and_the_third_only_for_a_paywalled_work():
    find = " ".join(section("### 1. Find the work", "### 2.").split())
    first, second, third = (find.index("First, a free readable copy of the original"),
                            find.index("Second, if there is none, look in the same way for a free external source"),
                            find.index("Third, only if there is neither and the original is behind a paywall"))
    assert first < second < third
    assert "its reference is still confirmed from a public page" in find
    stop_1 = " ".join(section("### 2. Stop 1", "### 3.").split())
    for needed in ("which of the three paths it takes", "not checked against its text, at the level reference confirmed",
                   "with a link to the page that confirms the work so that a reader can find it",
                   "will have an evidence run (it has a copy)"):
        assert needed in stop_1, needed


def test_a_lens_from_the_model_s_knowledge_says_so_has_no_run_and_claims_nothing_precise():
    three = " ".join(section("### 3. If the original cannot be found or read", "### 4.").split())
    for needed in ("**The third path: the model's knowledge.**", "no copy and no evidence run, so no notice is needed",
                   "steps 4, 6, 7 and 8 and the overlap check of step 9 do not apply",
                   "no exact figure, no quote, no page number", "the level `reference_confirmed`",
                   "the confirming page's address as `link`",
                   "its text was not read: the lens is written from the model's general knowledge of the work and was "
                   "not checked against it", "\"model knowledge\"", "Course slides are never a basis for a lens"):
        assert needed in three, needed
    assert "with one exception: a lens on the third path of step 3" in flat()
    stop_2 = " ".join(section("### 12. Stop 2", "### 13.").split())
    assert "each sentence marked as written from the model's knowledge and not checked against the text" in stop_2


def test_a_lens_from_the_model_s_knowledge_gets_its_own_fixed_reviewer_prompt():
    prompt = fenced_text(SKILL, "reviewer-prompt-knowledge")
    for needed in ("Change nothing", "run no command", "general knowledge of a work whose text was not read",
                   "no exact figure, no quote, no page number", "the level reference confirmed",
                   "a web address as its link", "whether it matches what is widely known of the work"):
        assert needed in prompt, needed
    assert set(re.findall(r"<[^>]+>", prompt)) == {"<absolute path of the staging folder>",
                                                    "<absolute path of the mapping note>", "<lens id>"}
    assert unknown_calls(prompt) == []


# --- Paul (2026-11-16): six batches at once, unattended, each waiting at stop 2 --------------------------------------

def test_unattended_mode_makes_public_runs_downloads_no_file_and_waits_at_stop_2():
    part = " ".join(section("## Unattended mode", "## Adding the batches together").split())
    for needed in ('holds the word "unattended" and names one batch of `docs/superpowers/lens-batches.md`',
                   "Write the person's starting message into the ledger first, word for word",
                   "`<main>/radar/lens-evidence/<batch name>-<day>/`",
                   "No private run is made and no notice is asked for", "without `--mode private`",
                   "the person supplies no copy", "never the address of a PDF or another file",
                   "Stop 1 is not shown", "write each decision with its reason into the ledger",
                   "when the original is behind a paywall or is free only as a file",
                   "the person may upgrade it with one yes to that download",
                   "Stop 2 is shown and waited for", "Never write into `lenses/` or `lenses/themes.json` in this mode, "
                   "and never commit"):
        assert needed in part, needed
    merge = " ".join(section("## Adding the batches together", "## The steps").split())
    for needed in ('"/new-lens add batches"', "one after the other", "after their yes, do step 13 for that batch",
                   "mark the batch as added in its ledger", "added once"):
        assert needed in merge, needed


def test_a_sonnet_session_needs_an_opus_advisor_and_the_reviewer_stays_on_opus():
    """Paul (2026-11-16): the batches may run on Sonnet 5.5 with the advisor on Opus 5.5, to save usage."""
    before = " ".join(section("## Before step 1", "## The rules").split())
    for needed in ("or on Sonnet 5.5 with the advisor tool on and set to Opus 5.5",
                   "or on Sonnet 5.5 with no advisor on Opus 5.5, the person switches the model",
                   "ask the advisor before you write each draft (step 5) and before stop 2",
                   "The fresh reviewer of step 9 always runs on Opus."):
        assert needed in before, needed
    review = " ".join(section("### 9. A fresh reviewer", "### 10.").split())
    assert review.count("on the model `opus`") == 2
