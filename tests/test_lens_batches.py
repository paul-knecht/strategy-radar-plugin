"""The six lens batches Paul asked to run at the same time, unattended (2026-11-16), and the script that prints the
command for each. No session is started here."""
import re
import subprocess
import sys

import pytest

from plugin_helpers import ROOT

BATCHES = ROOT / "docs" / "superpowers" / "lens-batches.md"
SCRIPT = ROOT / "scripts" / "start_lens_batches.py"
pytestmark = pytest.mark.skipif(not BATCHES.exists(),
                                reason="the lens batches are the maintainer's notes and are not in the public copy")


def batches() -> dict[str, list[str]]:
    text = BATCHES.read_text(encoding="utf-8")
    parts = re.split(r"^## ", text, flags=re.M)[1:]
    return {part.splitlines()[0]: [line[2:] for line in part.splitlines() if line.startswith("- ")]
            for part in parts if part.startswith("batch-")}


def test_there_are_six_batches_of_at_most_twelve_and_no_lead_twice():
    found = batches()
    assert list(found) == [f"batch-{n}" for n in range(1, 7)]
    assert all(1 <= len(entries) <= 12 for entries in found.values()), {k: len(v) for k, v in found.items()}
    entries = [entry for group in found.values() for entry in group]
    assert len(entries) == len(set(entries))
    assert "`build-abroad-market-or-cost`" in " ".join(found["batch-1"])
    text = BATCHES.read_text(encoding="utf-8")
    assert "written from memory" in text and "## Left out on purpose" in text
    assert text.isascii()


def test_the_script_prints_one_unattended_plugin_session_per_batch():
    done = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, check=True)
    lines = done.stdout.splitlines()
    assert len(lines) == 6
    for number, line in enumerate(lines, start=1):
        for needed in ("claude --plugin-dir .", "--model claude-sonnet-5-5", "--effort medium", "--permission-mode auto",
                       f"/new-lens unattended batch-{number}:", "until stop 2, then wait"):
            assert needed in line, (number, needed)
        assert "dangerously" not in line and "bypassPermissions" not in line
    one = subprocess.run([sys.executable, str(SCRIPT), "batch-3"], capture_output=True, text=True, check=True)
    assert one.stdout.count("\n") == 1 and "batch-3" in one.stdout
    wrong = subprocess.run([sys.executable, str(SCRIPT), "batch-9"], capture_output=True, text=True)
    assert wrong.returncode == 2 and wrong.stdout == ""


def test_continue_points_a_fresh_session_at_the_batch_s_own_ledger(tmp_path, monkeypatch):
    """After a usage limit or a closed terminal, a batch goes on from its ledger in the same folder."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("start_lens_batches", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    folder = tmp_path / "radar" / "lens-evidence" / "batch-4-20261116"
    folder.mkdir(parents=True)
    (folder / "ledger.md").write_text("# Ledger\n", encoding="utf-8")
    monkeypatch.setattr(module, "main_checkout", lambda: tmp_path)
    assert module.ledger_of("batch-4") == folder / "ledger.md"
    assert module.ledger_of("batch-5") is None
    line = module.command("batch-4", module.ledger_of("batch-4"))
    for needed in ("--effort medium", "/new-lens unattended batch-4: continue this batch", str(folder / "ledger.md"),
                   "read it first and go on from it", "start no new batch folder", "until stop 2, then wait"):
        assert needed in line, needed


def venture_batches() -> dict[str, list[str]]:
    text = BATCHES.read_text(encoding="utf-8")
    parts = re.split(r"^## ", text, flags=re.M)[1:]
    return {part.splitlines()[0]: [line[2:] for line in part.splitlines() if line.startswith("- ")]
            for part in parts if part.startswith("venture-")}


def test_the_venture_batches_hold_the_eight_leads_in_two_halves():
    """Paul, 2026-11-17: plan all VC checks, build the best-suited now, in two unattended sessions of four."""
    found = venture_batches()
    assert list(found) == ["venture-1a", "venture-1b"]
    assert [len(v) for v in found.values()] == [4, 4]
    assert "Venture screening" in BATCHES.read_text(encoding="utf-8")


def test_the_candidate_list_allows_practitioner_works_for_venture_screening_only_in_paul_s_words():
    text = (ROOT / "docs" / "superpowers" / "lens-candidates.md").read_text(encoding="utf-8")
    assert "## Venture screening" in text
    assert '"those are fine for the VC option within the startegy radar"' in text
