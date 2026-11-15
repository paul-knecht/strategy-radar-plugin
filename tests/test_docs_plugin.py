"""What a program can check about the plugin guide, docs/plugin.md.

Whether a sentence is true of the plugin is for a reader; these tests check what has a fixed answer: the guide
exists, names the four commands and the ten steps as the skills do, shows only real `radar` calls, mentions only
files that exist, quotes the program's own notice, carries the models of the helpers as the settings file says,
and has the two sections that a person ticks off or reads as limits.
"""
import importlib.util
import json
import re
from pathlib import Path

import pytest

import radar
from plugin_helpers import ROOT, front_matter, radar_calls, unknown_calls
from plugin_helpers import fenced_json
from radar import demo, store
from radar.report.build import build_report
from radar.report.model import load_labels
from test_plugin_shell import invisible_characters

GUIDE = ROOT / "docs" / "plugin.md"
SKILLS = ("start", "practice", "run", "new-pack")
HELPERS = ("source-scout", "fact-extractor", "support-checker", "bias-auditor")
SPANS = re.compile(r"`([^`\n]+)`")
FILE_ENDINGS = (".md", ".json", ".py", ".sh", ".txt", ".toml")
# Paths in the guide that are not in this repository: they are in the person's own project or home folder, or inside a
# run folder, which only a run makes. The fixed names inside a run's report folder are checked against a built report
# in test_the_report_files_the_guide_names_are_the_ones_a_build_writes.
OUTSIDE = ("radar/", ".claude/", "~/", "report/", "copies/", "facts/", "sources/", "notes/", "proposals/", "inbox/")


@pytest.fixture(scope="module")
def guide() -> str:
    assert GUIDE.is_file(), "docs/plugin.md is the plugin guide"
    return GUIDE.read_text(encoding="utf-8")


def squeezed(text: str) -> str:
    """Text with every run of white space made one space, and quotation marks and bold marks left out."""
    return re.sub(r"\s+", " ", text.replace("*", "").replace("> ", "")).strip()


def section(guide: str, heading: str) -> str:
    """The text of the `## heading` part, up to the next `## ` heading."""
    match = re.search(r"^## " + re.escape(heading) + r"\s*$", guide, re.M)
    assert match, f"the guide has no section called {heading}"
    rest = guide[match.end():]
    end = re.search(r"^## ", rest, re.M)
    return rest[:end.start()] if end else rest


def test_the_guide_names_the_four_commands_as_the_skills_are_named(guide):
    names = [f"/strategy-radar:{front_matter(ROOT / 'skills' / skill / 'SKILL.md')['name']}" for skill in SKILLS]
    assert names == ["/strategy-radar:start", "/strategy-radar:practice", "/strategy-radar:run", "/strategy-radar:new-pack"]
    for name in names:
        assert f"`{name}`" in guide, name
    mentioned = set(re.findall(r"/strategy-radar:[a-z-]+", guide))
    assert mentioned == set(names), "the guide names no command that no skill has"


def test_the_guide_names_the_ten_steps_of_a_run_as_the_step_files_do(guide):
    found = {}
    for path in sorted((ROOT / "skills" / "run" / "steps").glob("[0-9][0-9]-*.md")):
        number, name = re.match(r"Send this as text now.*?\"Step (\d+) of 10: ([^.]+)\.", path.read_text(encoding="utf-8")).groups()
        found[int(number)] = name
    assert sorted(found) == list(range(1, 11))
    for number, name in found.items():
        assert re.search(rf"^{number}\. \*\*{re.escape(name)}\.\*\*", guide, re.M), (number, name)


def test_every_radar_call_the_guide_shows_is_a_real_command_with_real_options(guide):
    assert radar_calls(guide), "the guide shows at least one radar call"
    assert unknown_calls(guide) == []


def test_the_guide_names_no_real_company():
    # Built from pieces, as in test_plugin_shell.py, so that this file does not hold the names either.
    names = ["vet" + "ter", "rolls" + "-" + "royce"]
    text = GUIDE.read_text(encoding="utf-8").lower()
    for name in names:
        assert name not in text


def test_the_guide_holds_no_invisible_character():
    assert invisible_characters(GUIDE.read_text(encoding="utf-8")) == []


def test_every_file_or_folder_the_guide_mentions_exists(guide):
    top = {path.name for path in ROOT.iterdir() if path.name not in ("radar",)}
    checked = []
    for span in SPANS.findall(guide):
        if re.search(r"[\s<>*$\"{}]", span) or span.startswith(("http", "--", "/")):
            continue                                                    # a command, a placeholder or an address
        if span.startswith(OUTSIDE):
            continue                                                    # in the person's own project or home folder
        if span.split("/")[0] in top and ("/" in span or span.endswith(FILE_ENDINGS)):
            checked.append(span)
            assert (ROOT / span.rstrip("/")).exists(), f"the guide names {span}, which is not here"
        elif "/" in span and span.endswith(FILE_ENDINGS):
            raise AssertionError(f"the guide names {span}: neither in this repository nor a path of the person's project")
    for expected in ("hooks/guard.py", "settings/models.json", "docs/engine.md", "evals/README.md", "tests/model/", "packs/demo.json"):
        assert expected in checked, f"the guide should name {expected}"


def test_a_version_the_guide_mentions_is_the_one_the_program_has(guide):
    # ruling FWB-4: the guide also names the Claude Code version the plugin was built and tried with
    versions = set(re.findall(r"(?<!Claude Code )\b\d+\.\d+\.\d+\b", guide))
    assert versions == {radar.__version__}, "the guide names the version, and only this one"
    assert set(re.findall(r"Claude Code (\d+\.\d+\.\d+)", guide)) == {"2.1.325"}


def test_the_guide_has_the_two_sections_a_person_ticks_off_and_reads(guide):
    headings = re.findall(r"^## (.+?)\s*$", guide, re.M)
    assert "What to check by hand" in headings and "Known limits" in headings
    by_hand = section(guide, "What to check by hand")
    assert len(re.findall(r"^- \[ \] ", by_hand, re.M)) == 6, "six things to tick off"
    for word in ("printed page", "German", "developer tools", "not scripted", "browser", "listing"):
        assert word in by_hand, word
    limits = section(guide, "Known limits")
    groups = re.findall(r"^### (.+?)\s*$", limits, re.M)
    assert groups == ["What the program cannot detect", "What was not tested",
                      "What rests on instructions and tests, not on the program"]
    for word in ("Windows", "Linux", "second name", "shared platform", "stylesheet", "never fetched", "Claude Code only",
                 "No README and no icon"):
        assert word in limits, word


def test_the_guide_puts_what_only_instructions_hold_on_the_instruction_side(guide):
    held = section(guide, "What a program enforces, and what rests on instructions").split("**What rests on instructions")[1]
    for phrase in ("a figure written in the text", "writes no file of a run with a shell command",
                   "private-mode notice, and that the yes", "What the extractor and the auditor read"):
        assert phrase in held, phrase


def helper_rows(guide: str) -> dict:
    """The cells of each helper's row of the table, by the helper's plain name."""
    found = {}
    for helper in HELPERS:
        (row,) = [line for line in guide.splitlines() if line.startswith("|") and f"`strategy-radar:{helper}`" in line]
        found[helper] = [cell.strip() for cell in row.strip().strip("|").split("|")]
    return found


def test_the_guide_gives_each_helper_the_model_and_the_tools_its_files_name(guide):
    models = json.loads((ROOT / "settings" / "models.json").read_text(encoding="utf-8"))
    assert sorted(models) == sorted(HELPERS)
    header = [cell.strip() for cell in next(line for line in guide.splitlines() if line.startswith("| Helper")).strip("|").split("|")]
    assert header[:3] == ["Helper", "Model", "Tools"] and header[-2:] == ["Held by its tools or the guard", "Held by instructions only"]
    for helper, cells in helper_rows(guide).items():
        assert len(cells) == len(header), helper
        assert cells[1] == models[helper], (helper, cells[1])
        assert cells[2] == front_matter(ROOT / "agents" / f"{helper}.md")["tools"], (helper, cells[2])


def test_the_guide_names_the_four_places_the_guard_leaves_to_the_lead_and_no_more(guide):
    spec = importlib.util.spec_from_file_location("guard", ROOT / "hooks" / "guard.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    places = [guard.LEAD_FILE.decode()] + [folder.decode() + "/" for folder in guard.LEAD_FOLDERS]
    assert len(places) == 4
    paragraph = next(line for line in guide.splitlines() if line.startswith("**The guard**"))
    for place in places:
        assert f"`{place}`" in paragraph, place
    assert "four places" in paragraph and "Write, Edit and NotebookEdit" in paragraph
    assert set(guard.WRITING_TOOLS) == {"Write", "Edit", "NotebookEdit"}


def test_the_guide_names_the_ten_checks_as_the_report_prints_them(guide):
    checks = fenced_json(ROOT / "references" / "bias-audit.md", "radar-constants", last=True)["checks"]
    labels = load_labels()
    assert len(checks) == 10
    for check in checks:
        assert labels["audit_" + check] in guide, check


def test_the_report_files_the_guide_names_are_the_ones_a_build_writes(guide, tmp_path):
    """Fix wave A1: every run today is on the invented pack, so its tables carry the illustrative mark."""
    run = demo.build_demo_run(tmp_path, stage="complete")
    written = {path.name for path in build_report(run, demo.LENSES)}
    named = {span.split("/", 1)[1] for span in SPANS.findall(guide) if span.startswith("report/")}
    assert named == {"report.html", "report.md", "facts-illustrative.csv", "sources-illustrative.csv"}
    assert named <= written, named - written
    text = squeezed(guide)
    assert "an `illustrative` column" in text and "`facts.csv` and `sources.csv`" in text


def test_the_guide_says_what_a_second_source_must_do_to_confirm_a_fact(guide):
    """Fix wave I1: a second source confirms with a quote of its own that states the fact's claim."""
    text = squeezed(guide)
    assert "also has the quote" not in text
    assert ("an independent second source states the fact's claim in a quote of its own, found word for word in "
            "its own copy") in text


def test_the_guide_names_the_two_limits_of_the_guard_s_verdict_rule(guide):
    """Ruling FWA-6: the rule against recording a verdict holds in every project where the plugin is on, and it
    knows the checker by its name only."""
    limits = squeezed(section(guide, "Known limits"))
    for needed in ("a shell command that holds the word record-support is refused unless the support checker runs "
                   "it, also in a project that has nothing to do with a run",
                   "An agent of your own that is named support-checker is treated as the plugin's support checker"):
        assert needed in limits, needed


def test_the_guide_says_what_confirmed_means_and_what_the_refusal_to_build_covers(guide):
    """Fix wave, the guide: the three likely misunderstandings the reviewer names, said early and plainly."""
    opening = squeezed(guide[:guide.index("## Try it and install it")])
    for needed in ('"Confirmed" has a narrow meaning here', "the party itself states it",
                   "two independent sources state it", "a model", "It does not mean that the fact is true",
                   "when a fact or a listed total is not checked", "The free text of the analysis",
                   "the program checks its form and the facts it names, not what it says",
                   "documents of your own", "the run is practice, not a finding about a real company"):
        assert needed in opening, needed
    assert "refuses to build it if anything is unchecked" not in opening


def test_the_guide_names_what_the_program_now_enforces(guide):
    """Fix wave, the guide: what parts A and B made the program hold, on its side of the guide."""
    enforced = squeezed(section(guide, "What a program enforces, and what rests on instructions")
                        .split("**What rests on instructions")[0])
    for needed in ('a "Fact" step of the reasoning names a fact', "each chain ends with its conclusion",
                   'A fact number written in a text ("as F2 shows") must name a fact that counts',
                   "A flag of the bias audit may name any fact of the run, whatever its status, but only one that exists",
                   "Every saved copy has its data class", "A version to publish is never built from a private run",
                   "your reply in your own words", "How this report was made",
                   "carry the illustrative mark", "`radar doctor` says whether the guard can run",
                   "an earlier run whose facts must be settled again first",
                   "Only the support checker records whether a quote supports its fact.",
                   "Strategy Radar's guard: ", "a catch for slips, not a wall"):
        assert needed in enforced, needed
    held = squeezed(section(guide, "What a program enforces, and what rests on instructions")
                    .split("**What rests on instructions")[1])
    assert "Claude Code usually asks you" in held and "kept word for word" in held
    assert "holds no non-public source yet" not in squeezed(guide)


def test_the_guide_carries_the_known_limits_the_fix_wave_left(guide):
    """The rows marked "leave as known limit" and part A's limits by ruling, in plain words."""
    limits = squeezed(section(guide, "Known limits"))
    for needed in ("What the free text of the analysis says", "A size whose unit is in the source's language",
                   "Smaller limits of the program", "a record written again keeps no file mode set by hand",
                   "robots.txt is asked for before the two-second wait", "A sub-site", "hidden from screen readers",
                   "A Mac without Apple's developer tools", "only a link to the stand-in is not recognised",
                   "Paths no live session walked", 'A "no" to the private-mode notice',
                   "no example of a quote in another language", "Your words, word for word",
                   "A break at the wrong moment", "in the same second", "find `radar` calls by their form",
                   "The settings line and the setup"):
        assert needed in limits, needed


def test_the_guide_says_how_the_lead_finds_files_and_how_the_guard_fails(guide):
    """Rulings FWB-4 (no separate search tool in today's Claude Code) and FWB-3.3 (what the guard lets through)."""
    text = squeezed(guide)
    for needed in ("built and tried with Claude Code 2.1.325", "has no separate search tool",
                   "the lead lists a folder with `ls`", "Claude Code may ask you before a listing in the plugin's folder",
                   "no unscripted session was run"):
        assert needed in text, needed
    for needed in ("A call it cannot read at all is let through, a helper's too",
                   "An error of its own while it judges a call it could read lets the lead's call through and "
                   "refuses a helper's", "When it cannot start at all", "its launcher refuses every call of the plugin's "
                   "helpers and lets everything else through"):
        assert needed in text, needed
    assert "except a call of one of the plugin's helpers" not in text and "never left unlimited" not in text


def test_the_guide_quotes_the_private_mode_notice_word_for_word(guide):
    assert squeezed(store.PRIVATE_NOTICE_TEXT) in squeezed(guide)


def test_the_guide_says_what_the_tests_cost_and_how_many_cost_it(guide):
    model_tests = sum(path.read_text(encoding="utf-8").count("@pytest.mark.model")
                      for path in (ROOT / "tests" / "model").glob("test_*.py"))
    assert model_tests == 5
    text = squeezed(guide)
    assert "five model-driven tests" in text and "about 18 US dollars" in text and "Four of the five passed" in text
    assert "about 1 US dollar" in text and text.count("not a promise") >= 2
    assert "uv run pytest -m model tests/model -q" in guide and "sh evals/run.sh" in guide


def test_the_guide_does_not_promise_a_later_content(guide):
    # It describes the plugin as it is. It may say what is missing, never what a section "will" hold.
    assert not re.search(r"\bwill (hold|contain|describe|list|be added)\b", guide)
