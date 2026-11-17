"""Print the command that starts each lens batch of `docs/superpowers/lens-batches.md` in its own terminal.

For the maintainer only. Each command starts a Claude Code session in this checkout, with the checkout loaded as the
plugin, on Sonnet 5.5 at medium effort with the advisor on Opus 5.5 (Paul: to save usage), and runs `/new-lens unattended <batch>`: the batch is built without the person and stops at
stop 2, where it waits for them. Nothing is committed by these sessions. This script starts nothing itself.

Usage: python3 scripts/start_lens_batches.py [--continue] [batch name ...]

With --continue, each command goes on with a batch that stopped (at a usage limit, a crash or a closed terminal): the
session reads the batch's ledger first and goes on in the same batch folder, as the skill says after a break.
"""
import re
import shlex
import subprocess
import sys
from pathlib import Path

TOP = Path(__file__).resolve().parents[1]
BATCHES = TOP / "docs" / "superpowers" / "lens-batches.md"
MODEL = "claude-sonnet-5-5"   # with the advisor on Opus 5.5 (Paul, 2026-11-16, to save usage)


def batch_names(text: str) -> list[str]:
    """The batch names, in the order of the list: every heading `## batch-<n>`."""
    return re.findall(r"^## (batch-\d+)$", text, re.M)


def prompt(batch: str) -> str:
    return (f"/new-lens unattended {batch}: build every lens of {batch} in docs/superpowers/lens-batches.md. "
            "Each entry there is a lead from memory, not a fact. Work without me until stop 2, then wait.")


def main_checkout() -> Path:
    """The main checkout, where the evidence is: the folder above git's common folder (also from a worktree)."""
    common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=TOP,
                            capture_output=True, text=True, check=True).stdout.strip()
    return Path(common).parent


def ledger_of(batch: str) -> Path | None:
    """The newest ledger of a batch, in `<main>/radar/lens-evidence/<batch>-<day>[-n]/`, or None."""
    found = sorted((main_checkout() / "radar" / "lens-evidence").glob(f"{batch}-*/ledger.md"),
                   key=lambda path: path.stat().st_mtime)
    return found[-1] if found else None


def continue_prompt(batch: str, ledger: Path) -> str:
    return (f"/new-lens unattended {batch}: continue this batch, which stopped before stop 2. Its ledger is {ledger}: "
            "read it first and go on from it, in the same batch folder and the same work folders; start no new batch "
            "folder and redo no step the ledger shows as done. Each entry is a lead from memory, not a fact. Work "
            "without me until stop 2, then wait.")


def command(batch: str, ledger: Path | None = None) -> str:
    text = continue_prompt(batch, ledger) if ledger else prompt(batch)
    return (f"cd {shlex.quote(str(TOP))} && claude --plugin-dir . --model {MODEL} --effort medium --permission-mode auto "
            f"{shlex.quote(text)}")


def main(argv: list[str]) -> int:
    resume = "--continue" in argv
    argv = [arg for arg in argv if arg != "--continue"]
    names = batch_names(BATCHES.read_text(encoding="utf-8"))
    wanted = argv or names
    unknown = [name for name in wanted if name not in names]
    if unknown:
        print(f"No such batch in {BATCHES.name}: {', '.join(unknown)}", file=sys.stderr)
        return 2
    for name in wanted:
        ledger = ledger_of(name) if resume else None
        if resume and ledger is None:
            print(f"{name} has no ledger to continue from; start it without --continue", file=sys.stderr)
            return 2
        print(command(name, ledger))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
