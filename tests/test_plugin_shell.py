import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

import radar
from plugin_helpers import (PLUGIN_FOLDERS, ROOT, TEXT_SUFFIXES, body, cli_options, fenced_json, fenced_text, front_matter, has_claude, plugin_text_files,
                            radar_calls, unknown_calls)


def test_the_manifest_names_the_plugin_and_matches_the_engine_version():
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "strategy-radar" and manifest["license"] == "MIT"
    assert manifest["version"] == radar.__version__
    assert manifest["author"] == {"name": "Paul Knecht"}


def test_the_marketplace_lists_the_plugin_at_the_repository_root():
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert market["owner"]["name"] and [(p["name"], p["source"]) for p in market["plugins"]] == [("strategy-radar", "./")]


def test_the_licence_is_mit_with_the_authors_name():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License") and "Copyright (c) 2026 Paul Knecht" in text


def test_the_lens_readme_says_the_library_is_not_part_of_this_version():
    text = (ROOT / "lenses" / "README.md").read_text(encoding="utf-8").lower()
    assert "not part of this version" in text and "two invented lenses" in text


def test_no_plugin_file_leans_on_another_plugin():
    for path in plugin_text_files():
        text = path.read_text(encoding="utf-8").lower()
        assert "superpowers" not in text and "academic-research-skills" not in text, path


def test_no_plugin_file_names_the_two_target_companies_before_their_packs_exist():
    # Real company content arrives with plan 2b, verified. Until then the plugin's own files stay invented.
    # The names are built from pieces so that this file does not trip itself if it is ever scanned.
    names = ["vet" + "ter", "rolls" + "-" + "royce"]
    for path in plugin_text_files():
        text = path.read_text(encoding="utf-8").lower()
        for name in names:
            assert name not in text, path


def test_the_plugin_file_finder_finds_the_demo_pack_and_every_existing_folder_contributes():
    found = plugin_text_files()
    assert ROOT / "packs" / "demo.json" in found
    for folder in PLUGIN_FOLDERS:
        if (ROOT / folder).is_dir():
            assert any(folder == p.relative_to(ROOT).parts[0] for p in found), folder
    assert {".sh", ".yaml", ".yml", ".toml", ".html"} <= TEXT_SUFFIXES


@pytest.mark.parametrize("text, expected", [
    ('RUN=$(radar init-run --pack-file p --bogus)', ["init-run: unknown option --bogus"]),
    ("cd x && radar gate --nope", ["gate: unknown option --nope"]),
    ("$ radar status --nope", ["status: unknown option --nope"]),
    ("radar status --run R | radar zzz", ["zzz: unknown command"]),
    ("radar status --run R && radar nonsense", ["nonsense: unknown command"]),
    ("radar status --run R ; radar nonsense", ["nonsense: unknown command"]),
    ("radar status --run R || radar nonsense", ["nonsense: unknown command"]),
])
def test_calls_are_found_at_every_command_boundary(text, expected):
    for wrapped in (f"`{text}`", f"```sh\n{text}\n```", f"```sh\necho `{text}`\n```"):
        assert unknown_calls(wrapped) == expected, wrapped


def test_two_calls_in_one_span_are_both_found():
    assert radar_calls("`radar status --run R && radar gate --run R`") == [("status", {"--run"}), ("gate", {"--run"})]


def test_options_on_continuation_lines_are_collected():
    text = "```sh\nradar init-run --root x \\\n  --question q \\\n  --bogus\n```\n"
    assert radar_calls(text) == [("init-run", {"--root", "--question", "--bogus"})]
    assert unknown_calls(text) == ["init-run: unknown option --bogus"]


@pytest.mark.parametrize("program", ['"${CLAUDE_PLUGIN_ROOT}/bin/radar"', "'/x/bin/radar'", "/x/bin/radar",
                                     '"/x y/bin/radar"'])
def test_the_full_path_form_is_found_quoted_or_not(program):
    assert radar_calls(f"`{program} gate --run R --nope`") == [("gate", {"--run", "--nope"})]


def test_a_word_that_looks_like_an_option_inside_a_quoted_argument_is_not_one():
    assert radar_calls('`radar withdraw-fact --reason "use --foo here" --fact F1`') == [
        ("withdraw-fact", {"--reason", "--fact"})]
    assert radar_calls("`radar withdraw-fact --reason 'use --foo here'`") == [("withdraw-fact", {"--reason"})]


def test_key_equals_value_counts_as_the_key():
    assert radar_calls("`radar status --run=R/x --lenses=a`") == [("status", {"--run", "--lenses"})]


def test_tilde_fences_and_long_fences_are_tracked():
    text = "~~~sh\nradar nonsense\n~~~\n````sh\n```\nradar zzz\n```\nradar yyy\n````\nradar not_code\n"
    assert [c for c, _ in radar_calls(text)] == ["nonsense", "zzz", "yyy"]


def test_a_call_with_no_subcommand_is_pinned():
    assert radar_calls("`radar --help`") == [("", {"--help"})]
    assert unknown_calls("`radar --help`") == [] and unknown_calls("`radar --version`") == []
    assert unknown_calls("`radar --bogus`") == ["radar: unknown option --bogus"]


def test_prose_and_midline_mentions_are_not_calls():
    assert radar_calls("Use radar status here.\n```sh\n# run radar status later\necho radar gate\n```\n") == []


def test_front_matter_joins_folded_text_and_lists_and_makes_no_bogus_keys(tmp_path):
    path = tmp_path / "s.md"
    path.write_text('---\nname: s\ndescription: >\n  First part\n  second part: with colon\n'
                    'allowed-tools:\n  - Read\n  - "Bash(radar *)"\nmodel: sonnet\n---\nbody\n', encoding="utf-8")
    assert front_matter(path) == {"name": "s", "description": "First part second part: with colon",
                                  "allowed-tools": "Read, Bash(radar *)", "model": "sonnet"}


def test_the_helpers_read_front_matter_and_find_radar_calls(tmp_path):
    sample = '---\nname: x\ndescription: "Does y."\n---\nRun `radar status --run "$RUN"` then `radar nonsense --flag`.\n'
    path = tmp_path / "sample.md"
    path.write_text(sample, encoding="utf-8")
    assert front_matter(path) == {"name": "x", "description": "Does y."}
    assert body(path) == 'Run `radar status --run "$RUN"` then `radar nonsense --flag`.\n'
    assert radar_calls(body(path)) == [("status", {"--run"}), ("nonsense", {"--flag"})]
    assert unknown_calls(body(path)) == ["nonsense: unknown command"]


def test_radar_calls_read_fenced_lines_and_full_paths_and_ignore_prose():
    text = ('Use radar status in prose.\n```sh\nradar settle --run "$RUN"\n'
            '"${CLAUDE_PLUGIN_ROOT}/bin/radar" gate --run "$RUN" --bogus\n```\n')
    assert radar_calls(text) == [("settle", {"--run"}), ("gate", {"--run", "--bogus"})]
    assert unknown_calls(text) == ["gate: unknown option --bogus"]


def test_cli_options_cover_every_subcommand_and_from_json():
    options = cli_options()
    assert "--run" in options["status"] and "--pack-file" in options["init-run"]
    assert all("--from-json" in found for found in options.values())


def test_engine_files_are_not_ignored_but_the_runs_folder_is():
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("no git checkout here")

    def ignored(name):
        return subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT).returncode == 0

    assert not ignored("engine/radar/cli.py") and not ignored("engine/radar/new_file.py")
    assert ignored("radar/runs/x/facts.json") and ignored("evals/results/one.json")


@pytest.mark.claude
@pytest.mark.skipif(not has_claude(), reason="the claude command is not installed")
def test_claude_plugin_validate_passes_in_strict_mode():
    result = subprocess.run(["claude", "plugin", "validate", str(ROOT), "--strict"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_fenced_text_reads_the_one_block_with_the_tag(tmp_path):
    path = tmp_path / "x.md"
    path.write_text("intro\n```json one\n{\"a\": 1}\n```\n```\nplain\n```\n```text two\nline 1\nline 2\n```\nend\n", encoding="utf-8")
    assert fenced_text(path, "two") == "line 1\nline 2"
    assert fenced_json(path, "one") == {"a": 1}


def test_fenced_text_needs_exactly_one_closed_block(tmp_path):
    path = tmp_path / "x.md"
    path.write_text("```json one\n{}\n```\n```text one\nb\n```\n```json open\n{}\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="exactly one"):
        fenced_text(path, "one")
    with pytest.raises(AssertionError, match="exactly one"):
        fenced_text(path, "missing")
    with pytest.raises(AssertionError, match="not closed"):
        fenced_text(path, "open")


def test_fenced_text_can_insist_that_the_block_comes_last(tmp_path):
    path = tmp_path / "x.md"
    path.write_text("```json one\n{}\n```\n\nmore\n", encoding="utf-8")
    assert fenced_json(path, "one") == {}
    with pytest.raises(AssertionError, match="must come last"):
        fenced_json(path, "one", last=True)
    path.write_text("```json one\n{}\n```\n\n\n", encoding="utf-8")
    assert fenced_json(path, "one", last=True) == {}


# Every space other than the plain one (Unicode Zs: the no-break spaces, the wide spaces of typesetting, the
# ideographic space) is refused; so is every format character (Cf, among them the soft hyphen, the zero-width
# characters, the direction marks and the byte-order mark), a line or paragraph separator (Zl, Zp), a control
# character (Cc) other than a tab or a line end, and the characters that are letters or signs by category but show
# as nothing (the Hangul fillers and the braille blank).
NO_BREAK_SPACES = {chr(0xA0), chr(0x2007), chr(0x202F)}
BLANK_LOOKING = {chr(code) for code in (0x115F, 0x1160, 0x3164, 0xFFA0, 0x2800)}
# Files that are not text: none is tracked today. A tracked file of one of these types is left out, because its bytes
# are not characters; any other tracked file must be UTF-8 text.
NOT_TEXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".woff", ".woff2", ".zip"}


def invisible_characters(text: str) -> list[str]:
    """Every invisible character in a text, as U+XXXX, in order of first appearance."""
    import unicodedata
    found = []
    for char in text:
        category = unicodedata.category(char)
        if (category in ("Cf", "Zl", "Zp") or (category == "Cc" and char not in "\t\n\r")
                or (category == "Zs" and char != " ") or char in BLANK_LOOKING) and f"U+{ord(char):04X}" not in found:
            found.append(f"U+{ord(char):04X}")
    return found


def tracked_files() -> list[Path]:
    """Every file git tracks in this repository that exists in the working tree."""
    if shutil.which("git") is None:
        pytest.skip("needs git to list the tracked files")
    done = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True)
    if done.returncode != 0:
        pytest.skip("not a git work tree")
    names = [name for name in done.stdout.decode("utf-8").split("\0") if name]
    return [ROOT / name for name in names if (ROOT / name).is_file()]


# Fix wave A23.10: the blank-looking letters and signs (Hangul fillers, the braille blank) and every wide space.
BLANK_LOOKING_CODES = (0x115F, 0x1160, 0x3164, 0xFFA0, 0x2800)
WIDE_SPACE_CODES = (0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2008, 0x2009, 0x200A, 0x205F,
                    0x3000)


def test_the_scan_also_finds_blank_looking_characters_and_every_wide_space():
    for code in BLANK_LOOKING_CODES + WIDE_SPACE_CODES:
        assert invisible_characters("a" + chr(code) + "b") == [f"U+{code:04X}"], hex(code)
    assert invisible_characters("a plain space and a tab\t") == []


def test_the_scan_finds_each_kind_of_invisible_character_and_nothing_visible():
    for code in (0x2028, 0x2029, 0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD, 0x202E, 0x2066, 0x00A0, 0x202F,
                 0x2007, 0x0000, 0x001B, 0x007F, 0x0085):
        assert invisible_characters("a" + chr(code) + "b") == [f"U+{code:04X}"], hex(code)
    visible = "Tab\tand line ends\r\n stay; " + "".join(chr(code) for code in (0xFC, 0x201E, 0x201C, 0x2014, 0x20AC))
    assert invisible_characters(visible) == []


def test_no_file_the_repository_tracks_holds_an_invisible_character():
    files = tracked_files()
    assert any(path.parent.name == "radar" and path.name == "cli.py" for path in files)
    assert any(path.parts[-2:] == ("docs", "engine.md") for path in files)
    found, not_text = {}, []
    for path in files:
        if path.suffix.lower() in NOT_TEXT:
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            not_text.append(str(path.relative_to(ROOT)))
            continue
        characters = invisible_characters(text)
        if characters:
            found[str(path.relative_to(ROOT))] = characters
    assert not_text == [], "a tracked file that is not UTF-8 text and not of a type left out"
    assert found == {}


EVAL_CASES = {
    "starts-a-run": ("strategy-radar:run", None),
    "starts-the-guided-start": ("strategy-radar:start", None),
    "stays-out-of-other-work": ("strategy-radar", "0"),
}


def test_the_eval_suite_has_three_cases_each_with_a_prompt_and_a_grader():
    cases = sorted(path.name for path in (ROOT / "evals").iterdir() if path.is_dir() and path.name != "results")
    assert cases == ["starts-a-run", "starts-the-guided-start", "stays-out-of-other-work"]
    for case in cases:
        assert (ROOT / "evals" / case / "prompt.md").is_file()
        assert list((ROOT / "evals" / case / "graders").glob("*.md"))


def _command_the_script_runs():
    """The words of the one command line the script hands over to (`exec ...`), without `exec` and the passed-on arguments."""
    lines = [line.strip() for line in (ROOT / "evals" / "run.sh").read_text(encoding="utf-8").splitlines()]
    commands = [line for line in lines if line.startswith("exec claude plugin ")]
    assert len(commands) == 1
    words = shlex.split(commands[0])
    assert words[0] == "exec" and words[-1] == "$@"
    return words[1:-1]


def _command_the_readme_shows():
    lines = (ROOT / "evals" / "README.md").read_text(encoding="utf-8").splitlines()
    commands = [line.strip() for line in lines if line.startswith("claude plugin ")]
    assert len(commands) == 1
    return shlex.split(commands[0])


def test_the_eval_command_never_publishes():
    run = _command_the_script_runs()
    assert "--no-publish" in run and "--publish-report" not in run
    assert "--no-publish" in _command_the_readme_shows()


def test_the_eval_script_runs_the_command_the_readme_shows():
    run = _command_the_script_runs()
    assert run == _command_the_readme_shows()
    assert run[3:] == [".", "--ablation", "none", "--no-publish", "--trust-plugin", "--threshold", "1.0"]


def test_the_eval_script_is_a_plain_executable_shell_script_that_runs_from_the_repository_root():
    script = ROOT / "evals" / "run.sh"
    text = script.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n")
    assert script.stat().st_mode & 0o111
    assert 'cd "$(dirname "$0")/.."' in text, "the script moves to the repository root before it starts"
    assert text.index('cd "$(dirname "$0")/.."') < text.index("exec claude plugin ")
    assert "evals/run.sh" in (ROOT / "evals" / "README.md").read_text(encoding="utf-8")


def test_the_eval_script_refuses_the_option_that_uploads_the_result_page_before_anything_runs(tmp_path):
    """T24 (fix wave): any argument that starts with --pub is refused, also a shortened spelling; a stand-in claude
    stands first on the PATH, so that a script that let one through would start no real session."""
    text = (ROOT / "evals" / "run.sh").read_text(encoding="utf-8")
    assert "--pub*" in text and text.index("--pub*") < text.index("exec claude plugin ")
    stand_in = tmp_path / "bin"
    stand_in.mkdir()
    started = tmp_path / "started"
    (stand_in / "claude").write_text(f'#!/bin/sh\necho "$@" > "{started}"\n', encoding="utf-8")
    (stand_in / "claude").chmod(0o755)
    env = dict(os.environ, PATH=str(stand_in) + os.pathsep + os.environ.get("PATH", ""))
    for argument in (["--publish-report"], ["--runs", "1", "--publish-report"], ["--publish-report=yes"], ["--pub"],
                     ["--publish"], ["--pub=1"], ["--case", "x", "--publ"]):
        done = subprocess.run(["sh", str(ROOT / "evals" / "run.sh"), *argument], capture_output=True, text=True,
                              timeout=30, env=env)
        assert done.returncode == 2 and done.stdout == "", argument
        assert len(done.stderr.strip().splitlines()) == 1 and "not allowed" in done.stderr, argument
        assert argument[-1] in done.stderr and not started.exists(), argument
    allowed = subprocess.run(["sh", str(ROOT / "evals" / "run.sh"), "--runs", "1"], capture_output=True, text=True,
                             timeout=30, env=env)
    assert allowed.returncode == 0 and started.read_text(encoding="utf-8").split()[-2:] == ["--runs", "1"]


def test_the_readme_says_the_third_case_checks_the_request_s_intent_only():
    text = " ".join((ROOT / "evals" / "README.md").read_text(encoding="utf-8").split())
    assert "The third case checks the intent of one request only" in text


@pytest.mark.parametrize("case", sorted(EVAL_CASES))
def test_each_eval_case_asks_one_thing_and_checks_which_skill_started(case):
    folder = ROOT / "evals" / case
    settings = front_matter(folder / "prompt.md")
    assert settings["max_turns"] == "3" and settings["runs"] == "3"
    assert settings["allowed_tools"] == "[Read, Glob, Grep, Skill]"
    assert body(folder / "prompt.md").strip(), "a case without a prompt checks nothing"
    graders = sorted((folder / "graders").glob("*.md"))
    assert [g.name for g in graders] == ["skill.md"]
    grader = front_matter(graders[0])
    match, most = EVAL_CASES[case]
    assert grader["type"] == "tool_used" and grader["tool"] == "Skill" and grader["input_match"] == match
    if most is None:
        assert grader["min"] == "1" and "max" not in grader
    else:
        # A case that must never start the plugin needs min 0 as well: the default minimum is one call.
        assert grader["min"] == "0" and grader["max"] == most


def test_the_eval_prompts_are_the_ones_the_plan_names():
    asked = {case: body(ROOT / "evals" / case / "prompt.md").strip() for case in EVAL_CASES}
    assert asked["starts-a-run"] == ("Which competitors of Example Pharma are adding filling capacity, and is it for their own use "
                                     "or for outside customers? Use the Strategy Radar demo pack.")
    assert asked["starts-the-guided-start"] == "I have just installed Strategy Radar and have never used it. Help me get started."
    assert asked["stays-out-of-other-work"] == "In store.py, rename the function load_run to read_run and update its callers."
