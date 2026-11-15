import json
import re
from pathlib import Path

import radar
from radar.cli import main

ROOT = Path(__file__).resolve().parent.parent


def test_version_prints_json(capsys):
    assert main(["--version"]) == 0
    assert json.loads(capsys.readouterr().out) == {"version": radar.__version__}


def test_the_version_is_the_same_in_every_place_that_names_it():
    project = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    lock = re.search(r'name = "strategy-radar-engine"\nversion = "([^"]+)"',
                     (ROOT / "uv.lock").read_text(encoding="utf-8")).group(1)
    assert project == manifest == lock == radar.__version__


def test_unknown_command_is_usage_error(capsys):
    assert main(["no-such-command"]) == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    assert "error" in json.loads(captured.out)
