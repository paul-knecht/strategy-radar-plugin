"""`radar setup`: a private Python environment with the PDF library, in a folder of its own under the home folder.

Nothing is installed into the system Python. Running it again repairs or updates the environment.
"""
import os
import subprocess
import sys
from pathlib import Path


def default_home() -> Path:
    """`$RADAR_HOME`, or `~/.strategy-radar` when it is not set or empty. Nothing is created."""
    chosen = os.environ.get("RADAR_HOME")
    return Path(chosen) if chosen else Path.home() / ".strategy-radar"


def is_private(python_path: str, home: Path) -> bool:
    """Whether `python_path`, as written, lies under `<home>/venv`. A link is not followed."""
    venv = Path(os.path.abspath(home / "venv"))
    return Path(os.path.abspath(python_path)).is_relative_to(venv)


def commands(home: Path, python: str) -> list[list[str]]:
    venv = home / "venv"
    return [[python, "-m", "venv", str(venv)],
            [str(venv / "bin" / "python"), "-m", "pip", "install", "pypdf>=4"]]


_FAILED = ["The private environment could not be made.",
           "The PDF library (pypdf) could not be installed."]


def _last_line(done: subprocess.CompletedProcess) -> str:
    for text in (done.stderr, done.stdout):
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        if lines:
            return lines[-1]
    return ""


def setup(home: Path, python: str = sys.executable, run=subprocess.run) -> dict:
    """Make `<home>/venv` and put `pypdf` in it. The second command does not run when the first fails."""
    for step, command in enumerate(commands(home, python)):
        try:
            done = run(command, capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL)
        except OSError as exc:
            raise ValueError(f"{_FAILED[step]} The last line of output was: {exc.strerror or exc}")
        if done.returncode != 0:
            last = _last_line(done)
            raise ValueError(f"{_FAILED[step]} " + (f"The last line of output was: {last}" if last
                                                    else "The command printed nothing."))
    return {"environment": str(home / "venv"), "created": True, "installed": ["pypdf"]}
