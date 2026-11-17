"""The maintainer's overlap check: no run of eight or more words of a lens's own words appears in a copy of a work.

The script lives in `scripts/`, outside the engine and outside the plugin's folders, and the `new-lens` skill of this
repository runs it on a draft lens and the copies of the private evidence run. These tests use invented texts only.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_lens_overlap.py"

# Invented copy text (illustrative): no work is quoted.
COPY = ("In this invented chapter the plain example says that a small shop which buys one special machine for one "
        "buyer depends on that buyer for years afterwards.")
EIGHT = "a small shop which buys one special machine"         # eight words that stand in COPY
SEVEN = "a small shop which buys one special"                  # seven words that stand in COPY


def load():
    spec = importlib.util.spec_from_file_location("check_lens_overlap", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_run_of_seven_words_is_no_problem():
    assert load().overlap(["We note: " + SEVEN + " tool, and more."], [COPY]) == []


def test_a_run_of_eight_words_is_a_problem():
    assert load().overlap(["We see " + EIGHT + " cutting, and more."], [COPY]) == [EIGHT]


def test_case_and_punctuation_are_ignored_on_both_sides():
    lens = "A Small-Shop, which BUYS one; special (machine) cutter..."
    assert load().overlap([lens], [COPY]) == ["a small shop which buys one special machine"]
    assert load().overlap([EIGHT], [COPY.upper().replace(" ", " -- ")]) == [EIGHT]


def test_a_longer_run_is_given_once_as_a_whole():
    longer = "a small shop which buys one special machine for one buyer"
    assert load().overlap(["Then " + longer + " and so on."], [COPY]) == [longer]


def test_it_looks_in_every_copy_and_at_every_lens_text():
    other = "a second invented copy speaks of slow growth in a firm that hires too fast for its managers"
    found = load().overlap(["Nothing to see here at all, in eight or more words.", "When slow growth in a firm that "
                            "hires too fast appears.", EIGHT], [COPY, other])
    assert found == ["slow growth in a firm that hires too fast", EIGHT]


def test_a_run_is_never_made_across_two_texts():
    # The last four words of one lens text and the first four of the next stand together in the copy; they are not
    # one run, because a lens text is checked on its own, and so is each copy.
    assert load().overlap(["Our view: a small shop which", "buys one special machine, we say."], [COPY]) == []
    assert load().overlap(["a small shop which buys one special machine"], ["a small shop which", "buys one special "
                                                                             "machine"]) == []


def test_a_run_length_other_than_eight_can_be_asked_for():
    assert load().overlap(["We note: " + SEVEN + " tool."], [COPY], words=7) == [SEVEN]
    with pytest.raises(ValueError):
        load().overlap([EIGHT], [COPY], words=0)


def lens_file(folder: Path, **texts) -> Path:
    lens = {"id": "invented-lens", "name": "An invented lens", "idea": "Our own words only.",
            "suggests": "Look at our own words.", "limits": "Our own limit.", "competing_idea": "Our own rival view.",
            "questions": ["One?", "Two?", "Three?"],
            "originals": [{"reference": "Illustrative: " + EIGHT + " and more", "level": "original_read", "link": None}]}
    lens.update(texts)
    path = folder / "invented-lens.json"
    path.write_text(json.dumps(lens), encoding="utf-8")
    return path


def copies(folder: Path) -> Path:
    base = folder / "copies"
    base.mkdir()
    (base / "S1.txt").write_text(COPY, encoding="utf-8")
    (base / "S1.orig.pdf").write_bytes(b"%PDF-1.4 " + EIGHT.encode("ascii"))   # an original file is not read
    return base


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_the_command_passes_a_lens_whose_own_words_stand_in_no_copy(tmp_path):
    # The reference repeats the copy's words, as a reference may repeat a title: it is not one of the lens's own texts.
    done = run("--lens", str(lens_file(tmp_path)), "--copies", str(copies(tmp_path)))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "No run of 8 or more words" in done.stdout


@pytest.mark.parametrize("part", ["name", "idea", "suggests", "limits", "competing_idea", "questions"])
def test_the_command_finds_a_run_in_each_text_of_a_lens_and_exits_1(tmp_path, part):
    value = ["One?", "Two " + EIGHT + "?", "Three?"] if part == "questions" else "Ours, then " + EIGHT + "."
    done = run("--lens", str(lens_file(tmp_path, **{part: value})), "--copies", str(copies(tmp_path)))
    assert done.returncode == 1, done.stdout + done.stderr
    assert EIGHT in done.stdout


def test_the_command_reads_copies_in_folders_below(tmp_path):
    base = tmp_path / "run" / "copies"
    base.mkdir(parents=True)
    (base / "S2.txt").write_text(COPY, encoding="utf-8")
    done = run("--lens", str(lens_file(tmp_path, idea=EIGHT)), "--copies", str(tmp_path / "run"))
    assert done.returncode == 1 and EIGHT in done.stdout


@pytest.mark.parametrize("case", ["no lens file", "lens not json", "lens not an object", "no copies folder",
                                  "no text copy"])
def test_wrong_use_is_exit_2_and_never_a_pass(tmp_path, case):
    lens, folder = lens_file(tmp_path), tmp_path / "copies"
    if case == "no lens file":
        lens = tmp_path / "missing.json"
    elif case == "lens not json":
        lens.write_text("{not json", encoding="utf-8")
    elif case == "lens not an object":
        lens.write_text("[]", encoding="utf-8")
    if case != "no copies folder":
        folder.mkdir()
        if case != "no text copy":
            (folder / "S1.txt").write_text(COPY, encoding="utf-8")
        else:
            (folder / "S1.orig.pdf").write_bytes(b"%PDF-1.4")
    done = run("--lens", str(lens), "--copies", str(folder))
    assert done.returncode == 2, (case, done.stdout, done.stderr)
    assert "No run of 8 or more words" not in done.stdout


def test_the_script_uses_the_standard_library_only_and_plain_ascii():
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.isascii()
    imports = {line.split()[1].split(".")[0] for line in text.splitlines() if line.startswith(("import ", "from "))}
    assert imports <= set(sys.stdlib_module_names), imports


def test_a_joined_stretch_is_described_as_made_of_runs_found_in_a_copy(tmp_path):
    # Two hits that overlap in the lens text are joined; the joined stretch as a whole need not stand in one copy.
    doc = " ".join(load().overlap.__doc__.split())
    assert "made of runs of" in doc and "need not stand in a copy as a whole" in doc
    done = run("--lens", str(lens_file(tmp_path, idea=EIGHT)), "--copies", str(copies(tmp_path)))
    assert "stretch(es) of the lens made of runs of 8 or more words that stand in a copy" in done.stdout
