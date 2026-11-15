"""The driver's own tests. They start no model, so they run in the default suite."""
import json
import os
from pathlib import Path

import pytest

from model.driver import (ALLOWED, ANSWER, ROOT, denied, lead_commands, only_run, parse_turn, plain, say,
                          session_command, session_environment, step_line)
from helpers import make_run

FIXTURE = Path(__file__).parent / "fixtures" / "turn.jsonl"   # one real turn in the stream form, recorded


def test_parse_turn_reads_the_recorded_output():
    turn = parse_turn(FIXTURE.read_text(encoding="utf-8"))
    assert turn.session == "SESSION" and "0.1" in turn.text and turn.failed is False


def test_parse_turn_keeps_every_text_of_the_lead_in_order_and_the_denials():
    turn = parse_turn(FIXTURE.read_text(encoding="utf-8"))
    assert len(turn.texts) == 2 and turn.texts[-1] == turn.text                 # the final text is the last one
    assert turn.texts[0].startswith("I'll run `radar --version`")              # said before the first call
    assert [(d["tool_name"], Path(d["tool_input"]["file_path"]).name) for d in turn.denials] == \
        [("Write", "outside.txt")]                                              # the write it was refused
    assert denied(turn) == list(turn.denials) and denied() == []


def test_parse_turn_sees_a_denial_that_only_the_stream_reports():
    """A helper's denial may come as the stream's own event and not reach the result's list."""
    event = {"type": "system", "subtype": "permission_denied", "tool_name": "Bash", "tool_use_id": "toolu_9",
             "message": "Claude requested permissions to use Bash, but you haven't granted it yet.",
             "parent_tool_use_id": "toolu_1", "session_id": "S"}
    result = {"type": "result", "is_error": False, "session_id": "S", "result": "Done.", "permission_denials": []}
    turn = parse_turn(json.dumps(event) + "\n" + json.dumps(result) + "\n")
    assert [(d["tool_name"], d["tool_use_id"]) for d in turn.denials] == [("Bash", "toolu_9")]
    assert turn.failed is False and denied(turn) != []


def test_parse_turn_leaves_out_the_text_of_a_helper():
    lead = {"type": "assistant", "parent_tool_use_id": None,
            "message": {"content": [{"type": "text", "text": "I am starting a helper."},
                                    {"type": "tool_use", "name": "Agent", "input": {}}]}}
    helper = {"type": "assistant", "parent_tool_use_id": "toolu_1",
              "message": {"content": [{"type": "text", "text": "Helper text."}]}}
    result = {"type": "result", "is_error": False, "session_id": "S", "result": "Done.", "permission_denials": []}
    turn = parse_turn("\n".join(json.dumps(event) for event in (lead, helper, result)))
    assert turn.texts == ("I am starting a helper.",) and turn.text == "Done." and turn.denials == ()


def test_parse_turn_keeps_the_lead_s_own_shell_commands_and_no_helper_s():
    """Fix wave I6: the planted-errors and full-run tests look at who ran which command; a helper's call names the
    call that started it, the lead's names none."""
    recorded = parse_turn(FIXTURE.read_text(encoding="utf-8"))
    assert recorded.commands == ("radar --version",)
    lead = {"type": "assistant", "parent_tool_use_id": None,
            "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "radar settle --run x"}},
                                    {"type": "tool_use", "name": "Read", "input": {"file_path": "/x"}}]}}
    helper = {"type": "assistant", "parent_tool_use_id": "toolu_1",
              "message": {"content": [{"type": "tool_use", "name": "Bash",
                                       "input": {"command": "radar record-support --run x --fact F1"}}]}}
    result = {"type": "result", "is_error": False, "session_id": "S", "result": "Done.", "permission_denials": []}
    turn = parse_turn("\n".join(json.dumps(event) for event in (lead, helper, result)))
    assert turn.commands == ("radar settle --run x",)
    assert lead_commands(turn) == ["radar settle --run x"] and lead_commands() == []


def test_parse_turn_marks_output_that_is_not_json_as_failed():
    assert parse_turn("command not found").failed is True


def test_parse_turn_marks_an_error_result_as_failed():
    printed = json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                          "session_id": "S", "result": ""})
    assert parse_turn(printed).failed is True
    assert parse_turn(json.dumps({"type": "result", "session_id": "S", "result": "hello"})).failed is True  # no flag


def test_parse_turn_takes_the_last_result_when_a_turn_prints_several():
    # A lead that ends a turn while its helpers still work may produce one result for each part of the turn.
    first = {"type": "result", "is_error": False, "session_id": "S", "result": "The helpers are working."}
    last = {"type": "result", "is_error": False, "session_id": "S", "result": "Which lenses should I use?"}
    first["permission_denials"] = [{"tool_name": "Bash", "tool_use_id": "t1", "tool_input": {"command": "ls"}}]
    turn = parse_turn(json.dumps(first) + "\n" + json.dumps(last) + "\n")
    assert (turn.session, turn.text, turn.failed) == ("S", "Which lenses should I use?", False)
    assert [d["tool_use_id"] for d in turn.denials] == ["t1"]                  # a denial of any part counts


def test_the_session_command_names_no_web_tool_and_bypasses_nothing(monkeypatch):
    monkeypatch.delenv("RADAR_TEST_INSTALLED", raising=False)
    command = session_command("hello", "S1")
    assert command[:3] == ["claude", "-p", "hello"]
    assert command[command.index("--plugin-dir") + 1] == str(ROOT)
    assert command[command.index("--resume") + 1] == "S1"
    assert command[command.index("--output-format") + 1:command.index("--output-format") + 3] == \
        ["stream-json", "--verbose"]                                            # every text of the lead, in order
    assert command[command.index("--allowedTools") + 1:] == ALLOWED          # the rules come last: the option takes a list
    assert "--resume" not in session_command("hello")
    for word in ("--permission-mode", "--dangerously-skip-permissions", "--allow-dangerously-skip-permissions",
                 "bypassPermissions"):
        assert word not in command
    assert not any(rule.startswith("Web") for rule in ALLOWED)              # these tests never touch the internet
    assert [rule for rule in ALLOWED if rule.startswith("Bash")] == ["Bash(radar *)"]
    assert "Write(./radar/**)" in ALLOWED and "Edit(./radar/**)" in ALLOWED and "Write" not in ALLOWED
    # the deferred point of the final review: reading (and with it searching) is limited to the project and the plugin
    assert [rule for rule in ALLOWED if rule.split("(")[0] in ("Read", "Glob", "Grep")] == \
        ["Read(./**)", f"Read(/{ROOT}/**)"]
    assert f"Read(/{ROOT}/**)".startswith("Read(//")                         # two slashes: a path from the root
    monkeypatch.setenv("RADAR_TEST_INSTALLED", "1")                         # Task 26: the installed plugin
    monkeypatch.setenv("RADAR_INSTALLED_DIR", "/somewhere/installed/strategy-radar/0.2.0")
    command = session_command("hello")
    assert "--plugin-dir" not in command
    # the installed copy is read from its own place, so that rule is added, and only then
    assert command[command.index("--allowedTools") + 1:] == [*ALLOWED, "Read(//somewhere/installed/strategy-radar/0.2.0/**)"]


def test_an_installed_run_without_a_found_installed_copy_stops_with_a_plain_message(monkeypatch, tmp_path):
    monkeypatch.setenv("RADAR_TEST_INSTALLED", "1")
    monkeypatch.delenv("RADAR_INSTALLED_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))                               # no plugin cache there
    with pytest.raises(RuntimeError, match="RADAR_INSTALLED_DIR"):
        session_command("hello")


def test_the_session_environment_is_small_and_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SOMETHING", "1")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")        # whatever this computer's PATH holds, here or in a Claude Code session
    project = tmp_path / "project"
    env = session_environment(project)
    assert set(env) <= {"HOME", "USER", "LOGNAME", "PATH", "SHELL", "TMPDIR", "LANG", "RADAR_PYTHON", "RADAR_HOME"}
    assert env["RADAR_PYTHON"] == str(ROOT / ".venv" / "bin" / "python")
    assert Path(env["RADAR_HOME"]).parent == tmp_path                       # in the test's own folder, not the project
    assert not Path(env["RADAR_HOME"]).is_relative_to(project)


def test_the_session_environment_refuses_a_path_with_a_radar_of_its_own(tmp_path, monkeypatch):
    """A radar found on the PATH would stand in for the plugin's own program."""
    other = tmp_path / "bin"
    other.mkdir()
    (other / "radar").write_text("#!/bin/sh\necho stand-in\n", encoding="utf-8")
    (other / "radar").chmod(0o755)
    monkeypatch.setenv("PATH", str(other) + os.pathsep + os.environ.get("PATH", ""))
    with pytest.raises(AssertionError, match="radar"):
        session_environment(tmp_path / "project")


def test_a_turn_that_does_not_end_in_time_keeps_what_it_printed(tmp_path, monkeypatch):
    """The turn is stopped, its output so far is saved, and the test fails naming the file."""
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "claude").write_text('#!/bin/sh\necho \'{"type": "system", "subtype": "init"}\'\nexec sleep 30\n',
                                 encoding="utf-8")
    (fake / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", str(fake) + os.pathsep + "/usr/bin" + os.pathsep + "/bin")
    project = tmp_path / "project"
    with pytest.raises(pytest.fail.Exception) as failed:
        say(project, "hello", timeout=1)
    saved = tmp_path / "turns" / "turn-1.json"
    assert str(saved) in str(failed.value) and "did not end within 1 s" in str(failed.value)
    assert '"subtype": "init"' in saved.read_text(encoding="utf-8")


def test_a_late_turn_is_still_saved_when_its_group_is_gone_and_a_child_holds_the_output(tmp_path, monkeypatch):
    """Stopping the group may find it gone, and a process outside it may keep the output open: neither blocks."""
    import model.driver as driver
    fake = tmp_path / "bin"
    fake.mkdir()
    pid_file = tmp_path / "pid"
    (fake / "claude").write_text(f'#!/bin/sh\necho \'{{"type": "system", "subtype": "init"}}\'\necho $$ > "{pid_file}"\n'
                                 'exec sleep 30\n', encoding="utf-8")
    (fake / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", str(fake) + os.pathsep + "/usr/bin" + os.pathsep + "/bin")

    def gone(pid, sig):
        raise ProcessLookupError(pid)
    monkeypatch.setattr(driver.os, "killpg", gone)                         # the group has gone; the process has not
    monkeypatch.setattr(driver, "AFTER_KILL", 1)
    try:
        with pytest.raises(pytest.fail.Exception) as failed:
            say(tmp_path / "project", "hello", timeout=1)
        saved = tmp_path / "turns" / "turn-1.json"
        assert str(saved) in str(failed.value)
        assert '"subtype": "init"' in saved.read_text(encoding="utf-8")
    finally:
        if pid_file.is_file():
            try:
                os.kill(int(pid_file.read_text(encoding="utf-8")), 9)
            except ProcessLookupError:
                pass


def test_only_run_finds_the_one_run_and_fails_otherwise(tmp_path):
    runs = tmp_path / "radar" / "runs"
    with pytest.raises(AssertionError):
        only_run(tmp_path)                                                  # no run at all
    first = make_run(runs, run_id="one")
    assert only_run(tmp_path) == first
    make_run(runs, run_id="two")
    with pytest.raises(AssertionError):
        only_run(tmp_path)                                                  # more than one


def test_step_line_is_the_line_a_step_file_tells_the_lead_to_send_first():
    six = step_line(6)
    assert six.startswith("Step 6 of 10: Your decision: lenses. ") and six.endswith(".") and '"' not in six
    first = (ROOT / "skills" / "run" / "steps" / "06-checkpoint-lenses.md").read_text(encoding="utf-8").splitlines()[0]
    assert first.endswith(f'"{six}"')
    assert step_line(5).startswith("Step 5 of 10: Check every quote. ")


def test_plain_leaves_markdown_stars_typographic_quotes_and_spacing_aside():
    assert plain("**Step 6 of 10:**  \u201cyes\u201d\n now") == 'Step 6 of 10: "yes" now'


def test_a_test_answer_starts_with_the_words_the_steps_look_for():
    steps = ROOT / "skills" / "run" / "steps"
    for step in ("06-checkpoint-lenses.md", "09-checkpoint-final.md"):
        assert f"the exact words `{ANSWER.strip()}`" in (steps / step).read_text(encoding="utf-8"), step
