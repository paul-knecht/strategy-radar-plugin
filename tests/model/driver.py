"""Drives real Claude Code sessions for the model-driven tests: one message of the person per turn, through `claude -p`.

Every session runs in its own project folder, with this repository loaded as the plugin (left out when
RADAR_TEST_INSTALLED is 1, for the installed plugin), in the default permission mode with the narrow rules in
ALLOWED. Its environment is built from nothing: HOME, USER, LOGNAME, PATH, SHELL and TMPDIR are passed on, LANG is set
to en_US.UTF-8, and the two radar settings are added, so none of the calling session's own environment variables (its
CLAUDE_CODE_* settings, its sockets) reach it. HOME is passed on because Claude Code needs its sign-in, and with it the person's own Claude Code
settings, their CLAUDE.md and their enabled plugins load as in any session of theirs. The project is a folder of its
own inside the test's folder; the test's folder also holds the radar home, which nothing creates, and the printed
output of every turn, for reading after a failure.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / ".venv" / "bin" / "python"

# The radar program, reading only in the project and in the plugin folder, and writing by hand only under the
# project's radar/ folder, where every file the lead writes lies (found by a live probe: the default mode with these two
# path rules, no permission mode). No Glob and no Grep: Claude Code 2.1.325 has these search tools only when the allow
# list names them, so a session of a person's own has none, and the skills list a folder with a plain `ls` instead;
# live probes with these rules ran such listings of the plugin's and the project's folders and the Read tool on a
# plugin file without a denial. No web tool: these tests never touch the internet. A path that starts with two slashes
# is one from the root of the disk.
ALLOWED = ["Bash(radar *)", "Read(./**)", f"Read(/{ROOT}/**)", "Write(./radar/**)", "Edit(./radar/**)", "Agent",
           "Skill"]

# Every message that answers a decision starts with it, so the run records `answered_by` `test` (design 6).
ANSWER = "Recorded test answer: "

PASSED_ON = ("HOME", "USER", "LOGNAME", "PATH", "SHELL", "TMPDIR")   # HOME: Claude Code needs its sign-in
AFTER_KILL = 10   # seconds to collect what a stopped turn printed

needs_claude = pytest.mark.skipif(shutil.which("claude") is None, reason="the claude command is not installed")


@dataclass(frozen=True)
class Turn:
    session: str
    text: str                  # the final text of the turn
    failed: bool
    texts: tuple = ()          # every text the lead sent during the turn, in order; the final one is the last
    denials: tuple = ()        # every permission denial of the turn, as Claude Code reports it
    commands: tuple = ()       # every shell command the lead itself ran in the turn, in order (no helper's)


def _events(stdout: str) -> list:
    """The JSON objects a turn printed: one per line in the stream form, or one object, or a list of them."""
    try:
        printed = [json.loads(stdout)]
    except ValueError:
        printed = []
        for line in stdout.splitlines():
            try:
                printed.append(json.loads(line))
            except ValueError:
                continue
    if len(printed) == 1 and isinstance(printed[0], list):
        printed = printed[0]
    return [item for item in printed if isinstance(item, dict)]


def _lead_texts(events: list) -> tuple:
    """The text blocks of the lead's own messages, in order. A helper's messages name the call that started it."""
    texts = []
    for event in events:
        message = event.get("message")
        if event.get("type") != "assistant" or event.get("parent_tool_use_id") or not isinstance(message, dict):
            continue
        blocks = message.get("content")
        for block in blocks if isinstance(blocks, list) else []:
            if isinstance(block, dict) and block.get("type") == "text" and str(block.get("text", "")).strip():
                texts.append(block["text"])
    return tuple(texts)


def _lead_commands(events: list) -> tuple:
    """The shell commands of the lead's own calls, in order. A helper's call names the call that started it."""
    commands = []
    for event in events:
        message = event.get("message")
        if event.get("type") != "assistant" or event.get("parent_tool_use_id") or not isinstance(message, dict):
            continue
        blocks = message.get("content")
        for block in blocks if isinstance(blocks, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Bash":
                command = (block.get("input") or {}).get("command")
                if isinstance(command, str):
                    commands.append(command)
    return tuple(commands)


def _denials(events: list) -> tuple:
    """The denials the results list, then those the stream reports as events of its own (a helper's may reach only
    the stream), each once: a denial is known by the id of the call it refused."""
    reported = [denial for event in events if event.get("type") == "result"
                for denial in event.get("permission_denials") or []]
    reported += [{key: event.get(key) for key in ("tool_name", "tool_use_id", "message")} for event in events
                 if event.get("type") == "system" and event.get("subtype") == "permission_denied"]
    found, seen = [], set()
    for denial in reported:
        if not isinstance(denial, dict):
            continue
        key = denial.get("tool_use_id") or json.dumps(denial, sort_keys=True)
        if key not in seen:
            seen.add(key)
            found.append(denial)
    return tuple(found)


def parse_turn(stdout: str) -> Turn:
    """The session id, the final text, whether the turn failed, the lead's texts and the permission denials.

    Output that holds no result is a failed turn. When a turn prints several results (a lead that ends its turn
    while its helpers still work), the last one is the turn's; the denials of all of them count, and so do the
    denials the stream reports on its own.
    """
    events = _events(stdout)
    results = [event for event in events if event.get("type") == "result"]
    if not results:
        return Turn(session="", text=stdout, failed=True)
    last = results[-1]
    session, text = last.get("session_id"), last.get("result")
    failed = last.get("is_error") is not False or not isinstance(session, str) or not isinstance(text, str)
    return Turn(session=session if isinstance(session, str) else "", text=text if isinstance(text, str) else "",
                failed=failed, texts=_lead_texts(events), denials=_denials(events), commands=_lead_commands(events))


def denied(*turns: Turn) -> list:
    """Every permission denial of these turns. A model test asserts that the list is empty."""
    return [denial for turn in turns for denial in turn.denials]


def lead_commands(*turns: Turn) -> list:
    """Every shell command the lead itself ran in these turns (fix wave I6: who recorded a verdict)."""
    return [command for turn in turns for command in turn.commands]


def step_line(number: int) -> str:
    """The line a step file tells the lead to send first ("Step 6 of 10: ..."), read from the file itself."""
    (path,) = (ROOT / "skills" / "run" / "steps").glob(f"{number:02d}-*.md")
    first = path.read_text(encoding="utf-8").splitlines()[0]
    found = re.search(r'"(Step [0-9]+ of 10: [^"]+)"$', first)
    assert found, first
    return found.group(1)


def plain(text: str) -> str:
    """The words of a text, without markdown stars, typographic quotes or doubled spaces."""
    return " ".join(text.replace("*", "").replace("\u201c", '"').replace("\u201d", '"').split())


def session_command(message: str, session: str | None = None) -> list[str]:
    """The command line of one turn. The allow rules come last, because that option takes every word after it."""
    command = ["claude", "-p", message]
    if os.environ.get("RADAR_TEST_INSTALLED") != "1":
        command += ["--plugin-dir", str(ROOT)]
    command += ["--output-format", "stream-json", "--verbose"]
    if session:
        command += ["--resume", session]
    return command + ["--allowedTools", *ALLOWED, *installed_read_rule()]


def installed_read_rule() -> list[str]:
    """In installed mode only: the read rule for the installed copy, which lies outside this repository.

    The folder is RADAR_INSTALLED_DIR, or the one version folder Claude Code keeps under its plugin cache. Without it the
    session could not read or list its own plugin, and every test would fail on a denial that says nothing about the plugin.
    """
    if os.environ.get("RADAR_TEST_INSTALLED") != "1":
        return []
    folder = os.environ.get("RADAR_INSTALLED_DIR")
    if not folder:
        found = sorted(Path(os.path.expanduser("~/.claude/plugins/cache")).glob("*/strategy-radar/*"))
        folders = [path for path in found if path.is_dir()]
        if len(folders) != 1:
            raise RuntimeError("RADAR_TEST_INSTALLED is 1, but the installed copy of the plugin was not found as one folder under "
                               "~/.claude/plugins/cache. Install the plugin, or set RADAR_INSTALLED_DIR to its folder.")
        folder = str(folders[0])
    return [f"Read(/{Path(folder)}/**)"]


def session_environment(project: Path) -> dict[str, str]:
    """The whole environment of a session: a few settings of this computer and the two radar settings."""
    env = {name: os.environ[name] for name in PASSED_ON if name in os.environ}
    env.update(LANG="en_US.UTF-8", RADAR_PYTHON=str(PYTHON), RADAR_HOME=str(Path(project).parent / "radar-home"))
    stand_in = shutil.which("radar", path=env.get("PATH", ""))
    assert stand_in is None, f"a radar on the PATH ({stand_in}) would stand in for the plugin's own program"
    return env


def _save(turns: Path, stdout: str, stderr: str) -> Path:
    turns.mkdir(parents=True, exist_ok=True)
    number = len(list(turns.glob("turn-*.json"))) + 1
    (turns / f"turn-{number}.err").write_text(stderr, encoding="utf-8")
    saved = turns / f"turn-{number}.json"
    saved.write_text(stdout, encoding="utf-8")
    return saved


def _decoded(part) -> str:
    return part.decode("utf-8", "replace") if isinstance(part, bytes) else (part or "")


def _stop(process: subprocess.Popen) -> tuple[str, str]:
    """Stop a turn and everything it started, and return what it printed so far."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:                       # the group has gone already
        pass
    try:
        return process.communicate(timeout=AFTER_KILL)
    except subprocess.TimeoutExpired as late:       # a process outside the group still holds the output open
        printed = (_decoded(late.stdout), _decoded(late.stderr))
        process.kill()
        try:
            process.wait(timeout=AFTER_KILL)
        except subprocess.TimeoutExpired:
            pass
        for pipe in (process.stdout, process.stderr):
            pipe.close()
        return printed


def say(project: Path, message: str, session: str | None = None, timeout: int = 2400) -> Turn:
    """Send one message of the person, in a new session or in `session`, and wait for the turn to end.

    A turn that does not end within `timeout` seconds is stopped with everything it started; what it printed so
    far is saved, and the test fails with the name of that file.
    """
    project = Path(project)
    project.mkdir(parents=True, exist_ok=True)
    env = session_environment(project)
    turns = project.parent / "turns"
    started = time.monotonic()
    process = subprocess.Popen(session_command(message, session), cwd=project, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        stdout, stderr = _stop(process)
        saved = _save(turns, stdout, stderr)
        pytest.fail(f"the turn did not end within {timeout} s; what it printed so far is in {saved}")
    minutes = (time.monotonic() - started) / 60
    saved = _save(turns, stdout, stderr)
    turn = parse_turn(stdout)
    if process.returncode != 0:
        turn = Turn(turn.session, turn.text, True, turn.texts, turn.denials, turn.commands)
    results = [event for event in _events(stdout) if event.get("type") == "result"]
    cost = results[-1].get("total_cost_usd") if results else None
    print(f"--- {saved.stem}: {minutes:.1f} min, exit {process.returncode}, failed {turn.failed}, "
          f"results {len(results)}, texts {len(turn.texts)}, cost {cost}, "
          f"denials {json.dumps(list(turn.denials))}\n{turn.text}\n", flush=True)
    return turn


def only_run(project: Path) -> Path:
    """The one run folder under `project/radar/runs`. Fails when there is none or more than one."""
    runs = Path(project) / "radar" / "runs"
    folders = sorted(path for path in runs.iterdir() if path.is_dir()) if runs.is_dir() else []
    assert len(folders) == 1, f"expected one run folder under {runs}, found {[path.name for path in folders]}"
    return folders[0]
