"""The launcher `bin/radar`, `radar setup` and the changed `radar doctor`.

No test here runs the real `radar setup`: it would make a folder in the home directory and download a package.
Setup is tested with an injected `run` function or with `--dry-run`. Every test that could resolve the default home
sets `HOME` and `RADAR_HOME` to folders under `tmp_path`, so `~/.strategy-radar` is never created or read.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from radar import setup_env
from radar.cli import main
from helpers import BIN_RADAR, make_run

ROOT = Path(__file__).parent.parent
RADAR = str(BIN_RADAR)
PLAIN_PATH = "/usr/bin:/bin"


def run_launcher(*args, env, cwd=None, script=RADAR, shell=("/bin/sh",), input=None):
    """Start the launcher through a shell (/bin/sh unless told otherwise) with exactly `env` and nothing else."""
    return subprocess.run([*shell, script, *args], capture_output=True, text=True, env=env, cwd=cwd, input=input)


def make_private_python(home):
    """Make `<home>/venv/bin/python` a link to the Python that runs the tests."""
    bin_dir = home / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to(sys.executable)
    return bin_dir / "python"


def make_stand_in(path, new_enough=True):
    """A stand-in for a Python that answers the version check, then echoes what it was started with."""
    check = "exit 0" if new_enough else "exit 1"
    path.write_text("#!/bin/sh\n"
                    f'if [ "$1" = "-I" ] && [ "$2" = "-c" ]; then {check}; fi\n'   # the version question
                    'echo "PYTHONPATH=$PYTHONPATH"\n'
                    'for arg in "$@"; do echo "arg:$arg"; done\n', encoding="utf-8")
    path.chmod(0o755)
    return path


# --- the file itself ---------------------------------------------------------------------------------

EXPECTED_LAUNCHER = r"""#!/bin/sh
# Starts the Strategy Radar engine with a Python 3.10 or newer.
# Order: $RADAR_PYTHON, the private environment made by `radar setup`, then python3.
# Only shell built-ins are used up to this point, so the script works with any PATH.
case "$0" in */*) dir=${0%/*} ;; *) dir=. ;; esac
here=$(CDPATH= cd -- "$dir/.." && pwd)
# The question is asked with -I and nothing on standard input, so no PYTHON... setting of the person's (such as
# PYTHONINSPECT or a broken PYTHONPATH) can make a working Python look missing. The engine itself keeps them.
new_enough() { "$1" -I -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' </dev/null >/dev/null 2>&1; }
# On a Mac, /usr/bin/python3 is only a stand-in until Apple's developer tools are installed, and starting it offers
# to install them. So there it is passed over unless the tools are there. Any other Python may be tried.
may_try() {
  [ "$1" = /usr/bin/python3 ] || return 0
  [ -e /System/Library/CoreServices/SystemVersion.plist ] || return 0
  [ -e /Library/Developer/CommandLineTools/usr/bin/python3 ] || [ -e /Applications/Xcode.app ]
}
for candidate in "$RADAR_PYTHON" "${RADAR_HOME:-$HOME/.strategy-radar}/venv/bin/python" python3; do
  if [ -n "$candidate" ] && may_try "$(command -v "$candidate")" && new_enough "$candidate"; then
    # A script file is started, not `-m radar`: with -m, Python looks first in the folder
    # the command is run from, and a file named radar there would run in the engine's place.
    exec "$candidate" "$here/engine/start_radar.py" "$@"
  fi
done
printf '%s\n' '{"error": "Strategy Radar needs Python 3.10 or newer and did not find one.", "hint": "Install Python 3.10 or newer from python.org, then run: radar setup"}'
exit 2
"""


def test_the_launcher_text_is_the_agreed_text():
    assert BIN_RADAR.read_bytes().decode("utf-8") == EXPECTED_LAUNCHER


def test_the_launcher_is_executable_in_the_git_index():
    done = subprocess.run(["git", "ls-files", "-s", "bin/radar"], capture_output=True, text=True, cwd=ROOT)
    assert done.stdout.split()[0] == "100755", done.stdout + done.stderr


# --- which Python it picks ---------------------------------------------------------------------------

def test_the_launcher_uses_radar_python(tmp_path):
    result = run_launcher("--version", env={"PATH": PLAIN_PATH, "HOME": str(tmp_path), "RADAR_PYTHON": sys.executable})
    assert result.returncode == 0 and json.loads(result.stdout)["version"]


def test_the_launcher_prefers_the_private_environment(tmp_path):
    make_private_python(tmp_path / "home")
    result = run_launcher("doctor", env={"PATH": PLAIN_PATH, "HOME": str(tmp_path),
                                         "RADAR_HOME": str(tmp_path / "home")})
    assert json.loads(result.stdout)["environment"] == "private"


def test_without_a_new_enough_python_the_launcher_says_what_to_do(tmp_path):
    old = tmp_path / "python3"
    old.write_text("#!/bin/sh\nexit 1\n")
    old.chmod(0o755)
    result = run_launcher("--version", env={"PATH": str(tmp_path), "HOME": str(tmp_path)})
    assert result.returncode == 2
    assert "Python 3.10" in json.loads(result.stdout)["error"]


def test_the_message_without_a_python_is_one_json_line_with_a_hint(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = run_launcher("--version", env={"PATH": str(empty), "HOME": str(tmp_path)})
    assert result.returncode == 2 and result.stderr == ""
    lines = result.stdout.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {
        "error": "Strategy Radar needs Python 3.10 or newer and did not find one.",
        "hint": "Install Python 3.10 or newer from python.org, then run: radar setup"}


def test_radar_python_comes_before_the_private_environment(tmp_path):
    make_private_python(tmp_path / "home")
    stand_in = make_stand_in(tmp_path / "mine")
    result = run_launcher("--version", env={"PATH": PLAIN_PATH, "HOME": str(tmp_path), "RADAR_PYTHON": str(stand_in),
                                            "RADAR_HOME": str(tmp_path / "home")})
    assert result.returncode == 0 and f"arg:{ROOT}/engine/start_radar.py\narg:--version\n" in result.stdout


def test_a_radar_python_that_does_not_exist_falls_through(tmp_path):
    make_private_python(tmp_path / "home")
    result = run_launcher("doctor", env={"PATH": PLAIN_PATH, "HOME": str(tmp_path),
                                         "RADAR_PYTHON": str(tmp_path / "no-such-python"),
                                         "RADAR_HOME": str(tmp_path / "home")})
    assert result.stderr == ""
    assert json.loads(result.stdout)["environment"] == "private"


def test_a_radar_python_that_is_too_old_falls_through(tmp_path):
    make_private_python(tmp_path / "home")
    old = make_stand_in(tmp_path / "old", new_enough=False)
    result = run_launcher("doctor", env={"PATH": PLAIN_PATH, "HOME": str(tmp_path), "RADAR_PYTHON": str(old),
                                         "RADAR_HOME": str(tmp_path / "home")})
    assert result.stderr == ""
    assert json.loads(result.stdout)["environment"] == "private"


def test_an_empty_radar_home_means_the_default_place_under_home(tmp_path):
    make_private_python(tmp_path / ".strategy-radar")
    result = run_launcher("doctor", env={"PATH": PLAIN_PATH, "HOME": str(tmp_path), "RADAR_HOME": ""})
    assert json.loads(result.stdout)["environment"] == "private"


def test_a_python_found_on_the_path_is_the_last_choice(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_stand_in(bin_dir / "python3")
    result = run_launcher("--version", env={"PATH": str(bin_dir), "HOME": str(tmp_path)})
    assert result.returncode == 0 and f"arg:{ROOT}/engine/start_radar.py\narg:--version\n" in result.stdout


# --- how it starts the engine ------------------------------------------------------------------------

def test_arguments_with_spaces_and_quotes_arrive_unchanged(tmp_path):
    stand_in = make_stand_in(tmp_path / "mine")
    hard = ['He said "no" and it\'s $(touch hit) `id` ; & *', "two  spaces", "", "--question=a b", "-"]
    result = run_launcher("init-run", "--question", *hard,
                          env={"PATH": PLAIN_PATH, "HOME": str(tmp_path), "RADAR_PYTHON": str(stand_in)}, cwd=tmp_path)
    got = [line[len("arg:"):] for line in result.stdout.splitlines() if line.startswith("arg:")]
    assert got == [f"{ROOT}/engine/start_radar.py", "init-run", "--question", *hard]
    assert not (tmp_path / "hit").exists()


def test_a_question_with_quotes_reaches_the_real_engine_unchanged(tmp_path):
    question = 'Who adds "filling" capacity, and isn\'t $(this) `odd`?'
    result = run_launcher("init-run", "--root", str(tmp_path / "runs"), "--question", question, "--pack", "demo",
                          "--run-id", "r1", env={"PATH": PLAIN_PATH, "HOME": str(tmp_path),
                                                 "RADAR_PYTHON": sys.executable})
    assert result.returncode == 0, result.stdout + result.stderr
    run = json.loads((Path(json.loads(result.stdout)["run_dir"]) / "run.json").read_text(encoding="utf-8"))
    assert run["question"] == question


def test_a_callers_pythonpath_is_left_as_it_is(tmp_path):
    stand_in = make_stand_in(tmp_path / "mine")
    env = {"PATH": PLAIN_PATH, "HOME": str(tmp_path), "RADAR_PYTHON": str(stand_in)}
    kept = run_launcher("--version", env={**env, "PYTHONPATH": "/somewhere/else:/and/here"})
    assert kept.stdout.splitlines()[0] == "PYTHONPATH=/somewhere/else:/and/here"
    alone = run_launcher("--version", env=env)
    assert alone.stdout.splitlines()[0] == "PYTHONPATH="


def test_the_engines_package_wins_over_a_radar_package_on_the_callers_pythonpath(tmp_path):
    extra = tmp_path / "extra"
    (extra / "radar").mkdir(parents=True)
    (extra / "radar" / "__init__.py").write_text("raise SystemExit('FAKE ENGINE')\n", encoding="utf-8")
    (extra / "other_module.py").write_text("VALUE = 7\n", encoding="utf-8")
    env = {"PATH": PLAIN_PATH, "HOME": str(tmp_path), "RADAR_PYTHON": sys.executable, "PYTHONPATH": str(extra)}
    result = run_launcher("--version", env=env, cwd=tmp_path)
    assert result.returncode == 0 and json.loads(result.stdout)["version"], result.stdout + result.stderr
    # the caller's other entries are still on the search path of the Python that runs the engine
    probe = tmp_path / "probe.py"
    probe.write_text("import other_module\nprint(other_module.VALUE)\n", encoding="utf-8")
    seen = subprocess.run([sys.executable, str(probe)], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert seen.stdout.strip() == "7", seen.stderr


# --- a file or folder named radar in the folder the command runs from never replaces the engine ----------------

def plain_env(tmp_path):
    return {"PATH": PLAIN_PATH, "HOME": str(tmp_path), "RADAR_PYTHON": sys.executable}


def assert_the_real_engine_answered(result):
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["version"] and "SHADOW" not in result.stdout + result.stderr


def test_a_radar_py_in_the_working_folder_does_not_replace_the_engine(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "radar.py").write_text("print('SHADOW')\n", encoding="utf-8")
    assert_the_real_engine_answered(run_launcher("--version", env=plain_env(tmp_path), cwd=work))


def test_a_radar_package_in_the_working_folder_does_not_replace_the_engine(tmp_path):
    work = tmp_path / "work"
    (work / "radar").mkdir(parents=True)
    (work / "radar" / "__init__.py").write_text("", encoding="utf-8")
    (work / "radar" / "__main__.py").write_text("print('SHADOW')\n", encoding="utf-8")
    assert_the_real_engine_answered(run_launcher("--version", env=plain_env(tmp_path), cwd=work))


def test_an_empty_radar_folder_in_the_working_folder_does_not_hide_the_engine(tmp_path):
    work = tmp_path / "work"
    (work / "radar").mkdir(parents=True)   # the folder a reader's project holds for its runs
    assert_the_real_engine_answered(run_launcher("--version", env=plain_env(tmp_path), cwd=work))


def test_a_radar_package_on_the_callers_pythonpath_does_not_replace_the_engine(tmp_path):
    fake = tmp_path / "fake"
    (fake / "radar").mkdir(parents=True)
    (fake / "radar" / "__init__.py").write_text("", encoding="utf-8")
    (fake / "radar" / "cli.py").write_text("def main():\n    print('SHADOW')\n    return 0\n", encoding="utf-8")
    assert_the_real_engine_answered(
        run_launcher("--version", env={**plain_env(tmp_path), "PYTHONPATH": str(fake)}, cwd=tmp_path))


def test_a_cdpath_does_not_change_where_the_launcher_finds_the_engine(tmp_path):
    (tmp_path / "cd" / "bin").mkdir(parents=True)   # `cd bin/..` would go here, and print it, if CDPATH counted
    result = run_launcher("--version", env={**plain_env(tmp_path), "CDPATH": str(tmp_path / "cd")},
                          cwd=ROOT, script="bin/radar")
    assert_the_real_engine_answered(result)


def test_text_from_a_python_that_is_too_old_never_reaches_the_output(tmp_path):
    chatty = tmp_path / "chatty"
    chatty.write_text("#!/bin/sh\necho 'Python 3.8 says hello'\necho 'and more' >&2\nexit 1\n", encoding="utf-8")
    chatty.chmod(0o755)
    make_private_python(tmp_path / "home")
    env = {"PATH": PLAIN_PATH, "HOME": str(tmp_path), "RADAR_PYTHON": str(chatty), "RADAR_HOME": str(tmp_path / "home")}
    result = run_launcher("--version", env=env)
    assert result.stdout.count("\n") == 1 and json.loads(result.stdout)["version"] and result.stderr == ""
    nowhere = run_launcher("--version", env={"PATH": str(tmp_path / "none"), "HOME": str(tmp_path),
                                             "RADAR_PYTHON": str(chatty)})
    assert nowhere.returncode == 2 and nowhere.stdout.count("\n") == 1 and "error" in json.loads(nowhere.stdout)


def test_a_newline_inside_an_argument_arrives_unchanged(tmp_path):
    question = "First line\nsecond line\n\nfourth"
    result = run_launcher("init-run", "--root", str(tmp_path / "runs"), "--question", question, "--pack", "demo",
                          "--run-id", "r1", env=plain_env(tmp_path), cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    run = json.loads((Path(json.loads(result.stdout)["run_dir"]) / "run.json").read_text(encoding="utf-8"))
    assert run["question"] == question


@pytest.mark.parametrize("shell", [("dash",), ("bash", "--posix")], ids=["dash", "bash-posix"])
def test_the_core_case_works_in_other_shells(tmp_path, shell):
    if shutil.which(shell[0]) is None:
        pytest.skip(f"{shell[0]} is not on this machine")
    work = tmp_path / "work"
    (work / "radar").mkdir(parents=True)
    (work / "radar.py").write_text("print('SHADOW')\n", encoding="utf-8")
    env = {**plain_env(tmp_path), "PATH": os.environ["PATH"]}
    assert_the_real_engine_answered(run_launcher("--version", env=env, cwd=work, shell=(shutil.which(shell[0]), *shell[1:])))
    question = 'a "quoted" $(thing)\nover two lines'
    result = run_launcher("init-run", "--root", str(tmp_path / "runs"), "--question", question, "--pack", "demo",
                          "--run-id", "r1", env=env, cwd=work, shell=(shutil.which(shell[0]), *shell[1:]))
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_exit_code_of_the_engine_is_passed_on(tmp_path):
    env = {"PATH": PLAIN_PATH, "HOME": str(tmp_path), "RADAR_PYTHON": sys.executable}
    assert run_launcher("--version", env=env).returncode == 0
    used_wrongly = run_launcher("log-search", env=env)
    assert used_wrongly.returncode == 2 and "error" in json.loads(used_wrongly.stdout)
    run = make_run(tmp_path)   # a run with nothing in it: the gate refuses, which is exit code 1
    refused = run_launcher("gate", "--run", str(run), env=env)
    assert refused.returncode == 1, refused.stdout + refused.stderr
    json.loads(refused.stdout)


def test_the_launcher_works_through_a_path_with_a_space_and_from_another_folder(tmp_path):
    tree = tmp_path / "a folder with spaces"
    (tree / "bin").mkdir(parents=True)
    shutil.copy(BIN_RADAR, tree / "bin" / "radar")
    (tree / "engine").symlink_to(ROOT / "engine")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    env = {"PATH": PLAIN_PATH, "HOME": str(tmp_path), "RADAR_PYTHON": sys.executable}
    result = run_launcher("--version", env=env, cwd=elsewhere, script=str(tree / "bin" / "radar"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["version"]


def test_the_launcher_works_when_started_by_a_short_name_from_its_own_folder(tmp_path):
    result = run_launcher("--version", env={"PATH": PLAIN_PATH, "HOME": str(tmp_path), "RADAR_PYTHON": sys.executable},
                          cwd=ROOT / "bin", script="radar")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["version"]


def test_a_link_to_the_launcher_in_another_folder_does_not_find_the_engine(tmp_path):
    """Known limit, pinned: the script takes its place from `$0` and does not follow a link."""
    link_dir = tmp_path / "links"
    link_dir.mkdir()
    link = link_dir / "radar"
    link.symlink_to(BIN_RADAR)
    result = run_launcher("--version", env={"PATH": PLAIN_PATH, "HOME": str(tmp_path), "RADAR_PYTHON": sys.executable},
                          cwd=tmp_path, script=str(link))
    assert result.returncode != 0
    assert "can't open file" in result.stderr and "start_radar.py" in result.stderr
    assert result.stdout == ""


# --- radar setup: nothing real runs -------------------------------------------------------------------

def ok(cmd, **kwargs):
    return subprocess.CompletedProcess(cmd, 0, "", "")


def test_setup_dry_run_changes_nothing(tmp_path, capsys):
    assert main(["setup", "--home", str(tmp_path / "h"), "--dry-run"]) == 0
    assert len(json.loads(capsys.readouterr().out)["would_run"]) == 2 and not (tmp_path / "h").exists()


def test_setup_dry_run_prints_the_two_commands_on_one_line(tmp_path, capsys):
    assert main(["setup", "--home", str(tmp_path / "h"), "--dry-run"]) == 0
    text = capsys.readouterr().out
    assert text.count("\n") == 1
    assert json.loads(text) == {"would_run": setup_env.commands(tmp_path / "h", sys.executable)}


def test_setup_names_the_default_home_when_none_is_given(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("RADAR_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["setup", "--dry-run"]) == 0
    first, second = json.loads(capsys.readouterr().out)["would_run"]
    assert first[-1] == str(tmp_path / ".strategy-radar" / "venv")
    assert second[0] == str(tmp_path / ".strategy-radar" / "venv" / "bin" / "python")
    assert list(tmp_path.iterdir()) == []


def test_setup_takes_the_home_from_radar_home(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("RADAR_HOME", str(tmp_path / "chosen"))
    monkeypatch.setenv("HOME", str(tmp_path / "other"))
    assert main(["setup", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["would_run"][0][-1] == str(tmp_path / "chosen" / "venv")


def test_setup_takes_its_options_from_a_json_file(tmp_path, capsys):
    options = tmp_path / "options.json"
    options.write_text(json.dumps({"home": str(tmp_path / "h"), "dry_run": True}), encoding="utf-8")
    assert main(["setup", "--from-json", str(options)]) == 0
    assert json.loads(capsys.readouterr().out)["would_run"] == setup_env.commands(tmp_path / "h", sys.executable)
    assert not (tmp_path / "h").exists()


def test_setup_makes_a_relative_home_absolute(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["setup", "--home", "rel/home", "--dry-run"]) == 0
    first, second = json.loads(capsys.readouterr().out)["would_run"]
    assert first[-1] == str(tmp_path / "rel" / "home" / "venv")
    assert second[0] == str(tmp_path / "rel" / "home" / "venv" / "bin" / "python")
    seen = []
    monkeypatch.setattr(setup_env, "setup", lambda home, python=sys.executable: seen.append(home) or {"home": str(home)})
    assert main(["setup", "--home", "rel/home"]) == 0
    assert seen == [tmp_path / "rel" / "home"]


def test_setup_makes_a_home_that_starts_with_a_dash_absolute(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["setup", "--home=-x", "--dry-run"]) == 0
    first, second = json.loads(capsys.readouterr().out)["would_run"]
    assert first[-1] == str(tmp_path / "-x" / "venv") and second[0].startswith(str(tmp_path / "-x"))


def test_setup_makes_a_relative_radar_home_absolute_too(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RADAR_HOME", "relative-home")
    assert main(["setup", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["would_run"][0][-1] == str(tmp_path / "relative-home" / "venv")


def test_setup_refuses_a_home_that_is_a_file_before_anything_runs(tmp_path, capsys, monkeypatch):
    afile = tmp_path / "afile"
    afile.write_text("not a folder", encoding="utf-8")

    def must_not_run(*args, **kwargs):
        raise AssertionError("setup ran")

    monkeypatch.setattr(setup_env, "setup", must_not_run)
    for extra in ([], ["--dry-run"]):
        assert main(["setup", "--home", str(afile), *extra]) == 2
        out = capsys.readouterr().out
        assert out.count("\n") == 1
        error = json.loads(out)["error"]
        assert list(json.loads(out)) == ["error"] and str(afile) in error and error.count(".") == 1
    assert afile.read_text(encoding="utf-8") == "not a folder" and sorted(p.name for p in tmp_path.iterdir()) == ["afile"]


def test_the_commands_are_the_agreed_two():
    home = Path("/h")
    assert setup_env.commands(home, "py") == [
        ["py", "-m", "venv", "/h/venv"],
        ["/h/venv/bin/python", "-m", "pip", "install", "pypdf>=4"]]


def test_setup_runs_both_commands_in_order(tmp_path):
    calls = []
    setup_env.setup(tmp_path, python="py", run=lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""))
    assert calls == setup_env.commands(tmp_path, "py")


def test_setup_reports_what_it_made(tmp_path):
    assert setup_env.setup(tmp_path, python="py", run=ok) == {
        "environment": str(tmp_path / "venv"), "created": True, "installed": ["pypdf"]}


def test_setup_on_an_existing_environment_runs_the_same_commands_and_reports_the_same(tmp_path):
    (tmp_path / "venv" / "bin").mkdir(parents=True)
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return ok(cmd)

    first = setup_env.setup(tmp_path, python="py", run=run)
    second = setup_env.setup(tmp_path, python="py", run=run)
    assert first == second
    assert calls == setup_env.commands(tmp_path, "py") * 2


def test_setup_reports_a_failed_command(tmp_path):
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", "first line\nERROR: no network\n")

    with pytest.raises(ValueError) as caught:
        setup_env.setup(tmp_path, python="py", run=run)
    assert "ERROR: no network" in str(caught.value) and "first line" not in str(caught.value)


def test_when_the_first_command_fails_the_second_is_not_run(tmp_path):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "boom")

    with pytest.raises(ValueError):
        setup_env.setup(tmp_path, python="py", run=run)
    assert calls == setup_env.commands(tmp_path, "py")[:1]


def test_a_failure_says_what_could_not_be_done_in_plain_words(tmp_path):
    def fails_at(step):
        def run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1 if cmd == setup_env.commands(tmp_path, "py")[step] else 0, "",
                                               "the last words")
        return run

    with pytest.raises(ValueError) as made:
        setup_env.setup(tmp_path, python="py", run=fails_at(0))
    assert str(made.value) == "The private environment could not be made. The last line of output was: the last words"
    with pytest.raises(ValueError) as installed:
        setup_env.setup(tmp_path, python="py", run=fails_at(1))
    assert str(installed.value) == ("The PDF library (pypdf) could not be installed. "
                                    "The last line of output was: the last words")


def test_a_python_without_the_venv_module_ends_in_a_plain_message(tmp_path):
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 1, "", "/usr/bin/python3: No module named venv\n\n")

    with pytest.raises(ValueError) as caught:
        setup_env.setup(tmp_path, python="py", run=run)
    assert str(caught.value).endswith("No module named venv") and "Traceback" not in str(caught.value)


def test_a_failure_with_no_output_says_so(tmp_path):
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", "")

    with pytest.raises(ValueError) as caught:
        setup_env.setup(tmp_path, python="py", run=run)
    assert str(caught.value) == "The private environment could not be made. The command printed nothing."


def test_the_last_line_comes_from_the_error_output_or_else_the_normal_output(tmp_path):
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, "only normal output\n", "")

    with pytest.raises(ValueError) as caught:
        setup_env.setup(tmp_path, python="py", run=run)
    assert str(caught.value).endswith("only normal output")


def test_a_python_that_cannot_be_started_ends_in_a_plain_message(tmp_path):
    def run(cmd, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", cmd[0])

    with pytest.raises(ValueError) as caught:
        setup_env.setup(tmp_path, python="py", run=run)
    assert str(caught.value) == ("The private environment could not be made. "
                                 "The last line of output was: No such file or directory")


def test_setup_collects_the_output_and_gives_the_commands_no_input(tmp_path):
    seen = []

    def run(cmd, **kwargs):
        seen.append(kwargs)
        return ok(cmd)

    setup_env.setup(tmp_path, python="py", run=run)
    assert all(kw["capture_output"] is True and kw["text"] is True and kw["stdin"] is subprocess.DEVNULL for kw in seen)


def test_the_setup_command_shows_a_failure_as_one_json_line(tmp_path, capsys, monkeypatch):
    def refuse(home, python=sys.executable):
        raise ValueError("The private environment could not be made. The command printed nothing.")

    monkeypatch.setattr(setup_env, "setup", refuse)
    assert main(["setup", "--home", str(tmp_path / "h")]) == 2
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    assert json.loads(out) == {"error": "The private environment could not be made. The command printed nothing."}


def test_the_setup_command_prints_what_setup_returned(tmp_path, capsys, monkeypatch):
    seen = []

    def fake(home, python=sys.executable):
        seen.append((home, python))
        return {"environment": str(home / "venv"), "created": True, "installed": ["pypdf"]}

    monkeypatch.setattr(setup_env, "setup", fake)
    assert main(["setup", "--home", str(tmp_path / "h")]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "environment": str(tmp_path / "h" / "venv"), "created": True, "installed": ["pypdf"]}
    assert seen == [(tmp_path / "h", sys.executable)]


# --- radar doctor ------------------------------------------------------------------------------------

def set_homes(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("RADAR_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def test_doctor_names_its_python_and_points_to_setup(capsys, monkeypatch, tmp_path):
    set_homes(monkeypatch, tmp_path)
    monkeypatch.setitem(sys.modules, "pypdf", None)
    assert main(["doctor"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["python_path"] == sys.executable
    assert out["environment"] == "other"
    assert out["hint"] == "Run: radar setup"


def test_doctor_has_no_hint_when_everything_is_fine(capsys, monkeypatch, tmp_path):
    set_homes(monkeypatch, tmp_path)
    assert main(["doctor"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hint"] is None and out["python_path"] == sys.executable and out["environment"] == "other"


def test_doctor_says_private_for_a_python_under_the_homes_venv(capsys, monkeypatch, tmp_path):
    home = set_homes(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "executable", str(home / "venv" / "bin" / "python"))
    main(["doctor"])
    out = json.loads(capsys.readouterr().out)
    assert out["environment"] == "private" and out["python_path"] == str(home / "venv" / "bin" / "python")


def test_doctor_judges_the_path_as_written_not_where_a_link_leads(capsys, monkeypatch, tmp_path):
    home = set_homes(monkeypatch, tmp_path)
    real = home / "venv" / "bin"
    real.mkdir(parents=True)
    (real / "python").write_text("", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "python").symlink_to(real / "python")
    monkeypatch.setattr(sys, "executable", str(elsewhere / "python"))
    main(["doctor"])
    assert json.loads(capsys.readouterr().out)["environment"] == "other"


@pytest.mark.parametrize("written", ["{home}/venv-old/bin/python", "{home}/venv/../other/bin/python",
                                     "{home}/python", "{home}x/venv/bin/python", "/usr/bin/python3"])
def test_doctor_says_other_for_a_python_outside_the_homes_venv(capsys, monkeypatch, tmp_path, written):
    home = set_homes(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "executable", written.format(home=home))
    main(["doctor"])
    assert json.loads(capsys.readouterr().out)["environment"] == "other"


def test_doctor_takes_the_default_home_from_the_home_folder(capsys, monkeypatch, tmp_path):
    monkeypatch.delenv("RADAR_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(sys, "executable", str(tmp_path / ".strategy-radar" / "venv" / "bin" / "python"))
    main(["doctor"])
    assert json.loads(capsys.readouterr().out)["environment"] == "private"


def test_doctor_creates_nothing(capsys, monkeypatch, tmp_path):
    set_homes(monkeypatch, tmp_path)
    main(["doctor"])
    assert list(tmp_path.iterdir()) == []


def test_no_old_install_hint_is_left_anywhere():
    old = "pip install --user"
    for folder in ("engine", "docs/engine.md", "tests"):
        path = ROOT / folder
        files = [path] if path.is_file() else [p for p in path.rglob("*") if p.suffix in (".py", ".json", ".md")]
        for file in files:
            if file == Path(__file__):
                continue
            assert old not in file.read_text(encoding="utf-8"), file


# --- fix wave A5: Apple's stand-in python3 is passed over on a Mac without the developer tools -----------------------
# Not tried on a Mac without the tools (this computer has them). The decision is one shell function in both scripts;
# the tests run it with made-up files standing in for the three it looks at, under every shell on the computer.

import itertools   # noqa: E402
import re   # noqa: E402

GUARD_LAUNCHER = ROOT / "hooks" / "guard.sh"
STAND_IN = "/usr/bin/python3"
A_MAC = "/System/Library/CoreServices/SystemVersion.plist"
COMMAND_LINE_TOOLS = "/Library/Developer/CommandLineTools/usr/bin/python3"
XCODE = "/Applications/Xcode.app"
SHELLS = [shell for shell in ("/bin/sh", "/bin/bash", "/bin/zsh", "/bin/dash") if os.access(shell, os.X_OK)]


def the_function(script: Path) -> str:
    found = re.findall(r"^may_try\(\) \{\n.*?^\}\n", script.read_text(encoding="utf-8"), flags=re.M | re.S)
    assert len(found) == 1, script
    return found[0]


def test_the_rule_is_one_function_written_the_same_in_both_scripts():
    function = the_function(BIN_RADAR)
    assert function == the_function(GUARD_LAUNCHER)
    for path in (STAND_IN, A_MAC, COMMAND_LINE_TOOLS, XCODE):   # the files it looks at, as written
        assert path in function, path


def may_try(shell, path, mac, tools, xcode, folder) -> bool:
    """Run the scripts' own function with made-up files for the three it looks at: the answer for `path`."""
    stand_ins = {A_MAC: folder / "mac", COMMAND_LINE_TOOLS: folder / "tools", XCODE: folder / "xcode"}
    for real, made_up in stand_ins.items():
        made_up.unlink(missing_ok=True)
    for real, there in ((A_MAC, mac), (COMMAND_LINE_TOOLS, tools), (XCODE, xcode)):
        if there:
            stand_ins[real].write_text("", encoding="utf-8")
    function = the_function(BIN_RADAR)
    for real in (COMMAND_LINE_TOOLS, A_MAC, XCODE):   # the longest first: it ends with the stand-in's own path
        function = function.replace(real, str(stand_ins[real]))
    done = subprocess.run([shell, "-c", function + 'may_try "$1"', "may_try", path], capture_output=True, text=True,
                          env={"PATH": "/nowhere"})
    assert done.stdout == "" and done.stderr == "" and done.returncode in (0, 1), done
    return done.returncode == 0


@pytest.mark.parametrize("shell", SHELLS)
def test_the_stand_in_is_passed_over_only_on_a_mac_without_the_developer_tools(tmp_path, shell):
    for path, mac, tools, xcode in itertools.product(
            (STAND_IN, "/usr/local/bin/python3", "/opt/homebrew/bin/python3", "/usr/bin/python3.9", "python3", ""),
            (True, False), (True, False), (True, False)):
        expected = not (path == STAND_IN and mac and not tools and not xcode)
        assert may_try(shell, path, mac, tools, xcode, tmp_path) is expected, (path, mac, tools, xcode)


def test_both_scripts_ask_the_function_about_every_candidate_before_starting_it():
    for script in (BIN_RADAR, GUARD_LAUNCHER):
        text = script.read_text(encoding="utf-8")
        tests = re.findall(r"^  if (.+); then$", text, flags=re.M)
        assert tests and all('may_try "$(command -v "$candidate")" && new_enough "$candidate"' in test
                             for test in tests), (script, tests)


def test_a_python3_elsewhere_on_the_path_is_still_found(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_stand_in(bin_dir / "python3")
    result = run_launcher("--version", env={"PATH": str(bin_dir), "HOME": str(tmp_path)})
    assert result.returncode == 0 and f"arg:{ROOT}/engine/start_radar.py\narg:--version\n" in result.stdout


# --- fix wave A9: radar doctor says whether the guard can run on this computer -----------------------------------

from radar import cli   # noqa: E402

GUARD_HINT = ("Strategy Radar's guard cannot run on this computer, so nothing stops a hand-made change to a run's "
              "records before the final check refuses the report. Install Python from python.org, or install the "
              "plugin again.")


def test_doctor_says_the_guard_runs_here(capsys, monkeypatch, tmp_path):
    set_homes(monkeypatch, tmp_path)
    assert main(["doctor"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert (out["guard"], out["guard_hint"]) == ("ok", None)
    assert list(out)[-2:] == ["guard", "guard_hint"]


def a_guard(folder, answer):
    """A copy of the guard's launcher next to a guard.py that answers every event with `answer` (an exit code)."""
    hooks = folder / "hooks"
    hooks.mkdir(parents=True)
    shutil.copy(ROOT / "hooks" / "guard.sh", hooks / "guard.sh")
    (hooks / "guard.py").write_text(f"import sys\nsys.stdin.read()\nsys.exit({answer})\n", encoding="utf-8")
    return hooks / "guard.sh"


@pytest.mark.parametrize("how", ["lets everything through", "no guard.py", "no launcher", "no Python"])
def test_doctor_says_the_guard_is_not_running_when_it_would_let_a_record_be_written(capsys, monkeypatch, tmp_path, how):
    set_homes(monkeypatch, tmp_path)
    monkeypatch.setenv("RADAR_PYTHON", sys.executable)
    launcher = a_guard(tmp_path / "plugin", 0)
    if how == "no guard.py":
        (launcher.parent / "guard.py").unlink()
    elif how == "no launcher":
        launcher = tmp_path / "plugin" / "nothing" / "guard.sh"
    elif how == "no Python":
        launcher = ROOT / "hooks" / "guard.sh"
        monkeypatch.delenv("RADAR_PYTHON")
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setattr(cli, "GUARD_LAUNCHER", launcher)
    code = main(["doctor"])
    out = json.loads(capsys.readouterr().out)
    assert (out["guard"], out["guard_hint"]) == ("not_running", GUARD_HINT)
    assert code == (0 if out["python_ok"] and out["pypdf_ok"] else 1)   # the guard does not change the exit code


def test_doctor_counts_only_a_refusal_as_a_guard_that_runs(capsys, monkeypatch, tmp_path):
    set_homes(monkeypatch, tmp_path)
    monkeypatch.setenv("RADAR_PYTHON", sys.executable)
    monkeypatch.setattr(cli, "GUARD_LAUNCHER", a_guard(tmp_path / "refuses", 2))
    main(["doctor"])
    assert json.loads(capsys.readouterr().out)["guard"] == "ok"
    monkeypatch.setattr(cli, "GUARD_LAUNCHER", a_guard(tmp_path / "breaks", 1))
    main(["doctor"])
    assert json.loads(capsys.readouterr().out)["guard"] == "not_running"


def test_the_guard_check_leaves_nothing_behind(capsys, monkeypatch, tmp_path):
    set_homes(monkeypatch, tmp_path / "home-folder")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(scratch))
    main(["doctor"])
    assert json.loads(capsys.readouterr().out)["guard"] == "ok"
    assert list(scratch.iterdir()) == []


def test_the_guard_doctor_starts_is_the_plugin_s_own():
    assert cli.GUARD_LAUNCHER == ROOT / "hooks" / "guard.sh"


# --- fix wave A23.6: the version check runs cut off from the person's Python settings --------------------------------

NOT_FOUND = "Strategy Radar needs Python 3.10 or newer and did not find one."


def test_a_python_that_starts_oddly_in_the_person_s_settings_is_still_found(tmp_path):
    env = {"PATH": PLAIN_PATH, "HOME": str(tmp_path), "RADAR_PYTHON": sys.executable, "PYTHONINSPECT": "1"}
    result = run_launcher("--version", env=env, input="")
    assert NOT_FOUND not in result.stdout
    assert json.loads(result.stdout.splitlines()[0])["version"]   # the engine ran (what the setting does to it after
    #                                                               that is the person's own setting, as before)


def test_a_broken_pythonpath_no_longer_reads_as_no_python_found(tmp_path):
    broken = tmp_path / "broken"
    (broken / "encodings").mkdir(parents=True)
    (broken / "encodings" / "__init__.py").write_text("raise ImportError('broken on purpose')\n", encoding="utf-8")
    env = {"PATH": PLAIN_PATH, "HOME": str(tmp_path), "RADAR_PYTHON": sys.executable, "PYTHONPATH": str(broken)}
    result = run_launcher("--version", env=env)
    assert NOT_FOUND not in result.stdout          # the Python was found; what fails is the person's own setting


def test_both_scripts_ask_the_version_question_in_isolated_mode_with_nothing_on_standard_input():
    for script in (BIN_RADAR, ROOT / "hooks" / "guard.sh"):
        line = next(line for line in script.read_text(encoding="utf-8").splitlines() if line.startswith("new_enough()"))
        assert '"$1" -I -c ' in line and "</dev/null" in line, script
