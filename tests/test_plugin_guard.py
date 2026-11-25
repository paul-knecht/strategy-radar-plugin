"""The guard hook: run records are written only by the program, and a helper runs only what it may.

Every name, path and text here is invented and illustrative.
"""
import ast
import errno
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

import pytest

from helpers import make_run
from plugin_helpers import ROOT, body
from radar import demo

GUARD = ROOT / "hooks" / "guard.py"
FIXTURES = ROOT / "tests" / "fixtures"

SENDER = "Strategy Radar's guard: "     # fix wave A7: a person in an unrelated project knows who refused
RECORDS = SENDER + "Run records are written only by the radar program. Use the radar command for this step."
HELPER = SENDER + "This helper may only run: radar quote-context and radar record-support."
NO_COMMANDS = SENDER + "This helper may not run commands."
UNCHECKED = SENDER + "The guard cannot check where this path leads. Use a shorter, plain path."
SECOND_NAME = SENDER + ("This file also has a second name somewhere else on this computer, and the guard cannot see "
                        "where, so it is not written by hand. Save a fresh copy of the file under a new name and work "
                        "on that.")
OWN_RADAR = str(ROOT / "bin" / "radar")
CHECKER = "strategy-radar:support-checker"


def load_guard():
    spec = importlib.util.spec_from_file_location("radar_guard", GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load_guard()


def event(tool, agent=None, **tool_input):
    base = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}
    return {**base, "agent_type": agent} if agent else base


def recorded(name):
    return json.loads((FIXTURES / f"hook_event_{name}.json").read_text(encoding="utf-8"))


def minor_version(python):
    """The minor version number of the Python 3 at `python`, asked by starting it once; None when it does not start."""
    try:
        started = subprocess.run([python, "-c", "import sys; print(sys.version_info[1])"],
                                 capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return int(started.stdout.strip()) if started.returncode == 0 and started.stdout.strip().isdigit() else None


def stock_python():
    """/usr/bin/python3, the Python that comes with the computer (3.9 on a current Mac), when it really runs; else None.

    On a Mac it is only a stand-in until the developer tools are installed, and starting the stand-in asks the person
    to install them. There it is started only when `xcode-select -p` names a folder of tools that is there.
    """
    path = "/usr/bin/python3"
    if not os.access(path, os.X_OK):
        return None
    if sys.platform == "darwin":
        try:
            tools = subprocess.run(["/usr/bin/xcode-select", "-p"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        if tools.returncode != 0 or not os.path.isdir(tools.stdout.strip()):
            return None
    minor = minor_version(path)
    return path if minor is not None and minor >= 8 else None


def other_pythons():
    """Every python3.N on this computer's path that really starts, and the computer's own Python (stock_python) when its
    version is not among them, oldest first; each is started once to ask."""
    found = {}
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        if os.path.isdir(folder):
            for name in os.listdir(folder):
                path = os.path.join(folder, name)
                match = re.fullmatch(r"python3\.(\d+)", name)
                if not match or int(match.group(1)) in found or not os.access(path, os.X_OK):
                    continue
                if minor_version(path) == int(match.group(1)):
                    found[int(match.group(1))] = path
    stock = stock_python()
    if stock is not None:
        found.setdefault(minor_version(stock), stock)
    return [found[minor] for minor in sorted(found)]


def write(path, **more):
    return event("Write", file_path=str(path), content="{}", **more)


# ---------------------------------------------------------------- rule 1: run records

ENGINE_OWNED = ["run.json", "changes.json", ".gitignore", "sources/S1.json", "facts/F1.json", "copies/S1.txt",
                "copies/.gitignore", "report/report.html", "report/assets/chart.svg", "facts", "sources/new/S9.json",
                # everything else that is not one of the lead's four places, named or not
                ".lock", ".fetch.lock", ".last_fetch.json", ".F1.json.tmp", ".run.json.tmp", "new-file.txt", "README.md",
                "new-folder/a.md", "analysis.json.bak", "analysis.json/part", "analysis", "notes.md", "inbox.json",
                "Notes/a.md", "Analysis.json", "PROPOSALS/S1.json", "notes /a.md", ".notes/a.md",
                # only folders with the three names are the lead's: a file of that name at the run root is not
                "notes", "proposals", "inbox"]
THE_LEAD_S = ["analysis.json", "notes/frame.md", "proposals/S1.json", "inbox/a.json", "notes/deep/er/plan.md"]


def test_the_two_reasons_are_the_plain_sentences_of_the_plan():
    assert guard.RECORDS_REASON == RECORDS
    assert guard.HELPER_REASON == HELPER
    assert guard.NO_COMMANDS_REASON == NO_COMMANDS
    assert guard.UNCHECKED_REASON == UNCHECKED
    assert guard.SECOND_NAME_REASON == SECOND_NAME


def test_writing_a_fact_record_by_hand_is_refused(tmp_path):
    run = make_run(tmp_path)
    assert "radar program" in guard.decide(event("Write", file_path=str(run / "facts" / "F1.json"), content="{}"))


@pytest.mark.parametrize("target", ENGINE_OWNED)
def test_every_engine_owned_file_is_protected(tmp_path, target):
    run = make_run(tmp_path)
    assert guard.decide(write(run / target)) == RECORDS
    assert guard.decide(event("Edit", file_path=str(run / target), old_string="a", new_string="b")) == RECORDS
    assert guard.decide(event("NotebookEdit", notebook_path=str(run / target), new_source="x")) == RECORDS


@pytest.mark.parametrize("target", THE_LEAD_S)
def test_the_lead_s_own_files_are_let_through(tmp_path, target):
    run = make_run(tmp_path)
    assert guard.decide(write(run / target)) is None
    assert guard.decide(event("Edit", file_path=str(run / target), old_string="a", new_string="b")) is None
    assert guard.decide(event("NotebookEdit", notebook_path=str(run / target), new_source="x")) is None


def test_a_file_outside_any_run_folder_is_let_through(tmp_path):
    make_run(tmp_path)
    (tmp_path / "facts").mkdir()
    for target in ("facts/F1.json", "run.json", "sources/S1.json", "report/report.html", "elsewhere/notes.md"):
        assert guard.decide(write(tmp_path / target)) is None


def test_a_folder_is_a_run_only_with_its_record_and_a_records_folder(tmp_path):
    only_record = tmp_path / "a"
    only_record.mkdir()
    (only_record / "run.json").write_text("{}", encoding="utf-8")
    assert guard.decide(write(only_record / "report" / "x.html")) is None      # some other project's run.json
    no_record = tmp_path / "b"
    (no_record / "facts").mkdir(parents=True)
    (no_record / "sources").mkdir()
    assert guard.decide(write(no_record / "facts" / "F1.json")) is None        # the program refuses it as a run too
    for only in ("sources", "facts"):                                          # the record and one of the two folders
        half = tmp_path / ("half-" + only)
        (half / only).mkdir(parents=True)
        (half / "run.json").write_text("{}", encoding="utf-8")
        for target in ("run.json", only + "/x.json", "README.md", "report/a.html"):
            assert guard.decide(write(half / target)) is None, target


def test_a_run_just_made_and_a_finished_run_are_both_protected(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("RADAR_HOME", str(tmp_path / "radar-home"))
    fresh = make_run(tmp_path / "fresh")
    finished = demo.build_demo_run(tmp_path / "practice")
    assert (finished / "facts" / "F8.json").is_file()
    for run in (fresh, finished):
        assert guard.decide(write(run / "facts" / "F8.json")) == RECORDS
        assert guard.decide(write(run / "run.json")) == RECORDS
        assert guard.decide(write(run / "analysis.json")) is None


def test_a_run_whose_record_is_damaged_stays_protected_and_one_that_lost_a_folder_does_not(tmp_path):
    run = make_run(tmp_path)
    (run / "run.json").write_text("not json", encoding="utf-8")
    assert guard.decide(write(run / "sources" / "S1.json")) == RECORDS
    assert guard.decide(write(run / "run.json")) == RECORDS
    shutil.rmtree(run / "facts")                  # the price of the narrow definition: this is no run folder any more
    assert guard.decide(write(run / "run.json")) is None
    assert guard.decide(write(run / "sources" / "S1.json")) is None


def test_a_relative_path_is_read_from_the_folder_the_event_names(tmp_path):
    run = make_run(tmp_path)
    assert guard.decide(event("Write", file_path="facts/F1.json", content="{}", ) | {"cwd": str(run)}) == RECORDS
    assert guard.decide({**write("run1/facts/F1.json"), "cwd": str(tmp_path)}) == RECORDS
    assert guard.decide({**write("../run.json"), "cwd": str(run / "notes")}) == RECORDS
    assert guard.decide({**write("notes/frame.md"), "cwd": str(run)}) is None
    assert guard.decide({**write("facts/F1.json"), "cwd": str(tmp_path)}) is None


def test_a_relative_path_without_a_named_folder_is_read_from_the_working_folder(tmp_path, monkeypatch):
    run = make_run(tmp_path)
    monkeypatch.chdir(run)
    assert guard.decide(write("facts/F1.json")) == RECORDS
    assert guard.decide({**write("facts/F1.json"), "cwd": None}) == RECORDS


def test_a_path_that_starts_at_the_home_folder_is_followed_there(tmp_path, monkeypatch):
    run = make_run(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert guard.decide({**write("~/run1/facts/F1.json"), "cwd": str(tmp_path / "elsewhere")}) == RECORDS
    assert guard.decide({**write("~/run1/notes/a.md"), "cwd": str(tmp_path / "elsewhere")}) is None
    assert run.name == "run1"


def test_a_detour_through_another_folder_does_not_hide_a_record(tmp_path):
    run = make_run(tmp_path)
    assert guard.decide(write(str(run) + "/notes/../facts/F1.json")) == RECORDS
    assert guard.decide(write(str(run) + "/notes/../../run1/run.json")) == RECORDS
    assert guard.decide(write(str(run) + "//facts///F1.json")) == RECORDS
    assert guard.decide(write(str(run) + "/facts/./F1.json")) == RECORDS
    assert guard.decide(write(str(run) + "/facts/")) == RECORDS
    assert guard.decide(write(str(run) + "/facts/../notes/a.md")) is None


NUL, LONE = chr(0), chr(0xD800)


def refused_by_the_program(asked, reason=RECORDS, python=sys.executable):
    result = run_guard(json.dumps(asked), python=python)
    assert result.stdout == b"" and result.returncode in (0, 2)
    return result.returncode == 2 and result.stderr.decode("utf-8") == reason + "\n"


@pytest.mark.parametrize("odd", [LONE, chr(0xDFFF), chr(0xFFFE), "a" + LONE + "b"])
def test_a_detour_through_a_name_no_computer_can_hold_does_not_hide_a_record(tmp_path, odd):
    run = make_run(tmp_path)
    for path in (f"{run}/notes/{odd}/../../facts/F1.json", f"{run}/{odd}/../run.json", f"{run}/facts/{odd}",
                 f"{run}/notes/../{odd}", f"{run}/{odd}/a.md"):
        asked = write(path)
        assert guard.decide(asked) == RECORDS and refused_by_the_program(asked), ascii(path)
    assert guard.decide(write(f"{run}/notes/{odd}")) is None
    assert guard.decide(write(f"{run}/notes/{odd}/a.md")) is None
    assert guard.decide(write(f"{run}/notes/{odd}/../a.md")) == UNCHECKED     # back out of a folder that is not there
    assert guard.decide(write(f"{tmp_path}/{odd}/facts/F1.json")) is None
    assert guard.decide({**write("facts/F1.json"), "cwd": f"{run}/notes/{odd}/../.."}) == RECORDS
    assert guard.decide({**write("../../.lock"), "cwd": f"{run}/notes/{odd}"}) == RECORDS
    assert guard.decide({**write("a.md"), "cwd": f"{run}/notes/{odd}"}) is None


@pytest.mark.parametrize("python", other_pythons() or [sys.executable])
def test_a_path_or_folder_with_the_character_that_ends_a_name_cannot_be_checked_and_is_refused(tmp_path, python):
    run = make_run(tmp_path)
    (run / "notes").mkdir()
    (run / "notes" / "lk").symlink_to("../facts", target_is_directory=True)
    paths = [f"{run}/notes/lk/F1.json{NUL}junk", f"{run}/notes/lk/{NUL}", f"{run}/notes/{NUL}/../../facts/F1.json",
             f"{run}/facts/F1.json{NUL}", f"{run}/notes/a.md{NUL}", f"{tmp_path}/{NUL}", f"{NUL}", f"a{NUL}b"]
    for path in paths:
        asked = write(path)
        assert guard.decide(asked) == UNCHECKED and refused_by_the_program(asked, UNCHECKED, python), ascii(path)
        asked = event("NotebookEdit", notebook_path=path, new_source="x")
        assert guard.decide(asked) == UNCHECKED, ascii(path)
    for cwd, name in ((f"{run}/notes/{NUL}/../..", "facts/F1.json"), (f"{run}/notes{NUL}", "a.md"), (NUL, "a.md")):
        asked = {**write(name), "cwd": cwd}
        assert guard.decide(asked) == UNCHECKED and refused_by_the_program(asked, UNCHECKED, python), ascii(cwd)
    assert guard.decide({**write(f"{run}/notes/a.md"), "cwd": NUL}) == UNCHECKED     # the folder is part of the event


def test_a_path_longer_than_a_computer_opens_is_refused_fast_whatever_it_names(tmp_path):
    import time
    run = make_run(tmp_path)
    started = time.monotonic()
    for path in (f"{run}/notes/" + "a/" * 400000 + "x.md", f"{run}/facts/" + "a/" * 400000 + "x.md",
                 f"{run}/notes/" + "a/../" * 300000 + "../facts/F1.json", f"{tmp_path}/" + "b" * 2000000,
                 "/" + "../" * 500000 + str(run)[1:] + "/run.json", f"{tmp_path}/" + "c" * 4096,
                 f"{tmp_path}/" + "/".join(["deep"] * 1200) + "/a.txt"):
        assert guard.decide(write(path)) == UNCHECKED
    assert time.monotonic() - started < 5
    asked = write(f"{tmp_path}/" + "b" * 2000000)
    assert refused_by_the_program(asked, UNCHECKED)


def longest_path(folder):
    """The longest path, in bytes, that this computer opens at `folder`, as the computer itself says.

    Its limit counts the mark that ends a name, so the longest path is one byte shorter: 4095 bytes on Linux,
    1023 on macOS. The tests take it from here and never from a fixed number; the guard does not need it at all.
    """
    return os.pathconf(str(folder), "PC_PATH_MAX") - 1


LONGEST_HERE = longest_path(tempfile.gettempdir())       # where pytest makes its folders; for the lists of cases only


def test_a_long_path_that_a_computer_still_opens_is_judged_as_any_other(tmp_path):
    # Every folder on the way is made and the file is written, so the guard asks the computer about a path
    # exactly as long as the longest one it opens, and about every part of it.
    run = make_run(tmp_path)
    longest = longest_path(tmp_path)
    for start, expected in (("notes", None), ("facts", RECORDS), ("new", RECORDS)):
        (run / start).mkdir(exist_ok=True)
        folder = deep_folder(run / start, longest - 5)
        path = folder + "/a.md"
        assert len(path.encode("utf-8")) == longest
        Path(path).write_text("x", encoding="utf-8")                        # the computer opens it
        assert os.path.isfile(path)
        for asked in (write(path), event("Edit", file_path=path, old_string="x", new_string="y"),
                      write(folder + "/b.md")):                             # and a new name beside it
            assert guard.decide(asked) == expected, start


def deep_folder(base, length, link=None):
    """Make folders below `base` so that the deepest one's full path is exactly `length` bytes long; give that path.

    The folders are made step by step from an open folder, because a path that long cannot be named in one piece.
    With `link=(name, target)` a link of that name is put into the deepest folder.
    """
    base = str(base)
    left = length - len(base.encode("utf-8"))
    names = []
    while left > 256:
        names.append("n" * 200)
        left -= 201
    assert 2 <= left <= 256
    names.append("m" * (left - 1))
    folder = os.open(base, os.O_RDONLY)
    try:
        for name in names:
            os.mkdir(name, dir_fd=folder)
            deeper = os.open(name, os.O_RDONLY, dir_fd=folder)
            os.close(folder)
            folder = deeper
        if link:
            os.symlink(link[1], link[0], dir_fd=folder)
    finally:
        os.close(folder)
    path = "/".join([base] + names)
    assert len(path) == length
    return path


@pytest.mark.parametrize("beyond, expected", [(-195, None), (0, None), (1, UNCHECKED), (2, UNCHECKED)])
def test_a_file_that_is_there_is_let_through_up_to_the_longest_path_the_computer_opens(tmp_path, beyond, expected):
    # The path is `beyond` bytes longer than the longest path this computer opens (Linux 4095, macOS 1023).
    # The guard does not know that number: it asks the computer about every part.
    run = make_run(tmp_path)
    (run / "notes").mkdir()
    length = longest_path(tmp_path) + beyond
    folder = deep_folder(run / "notes", length - 5)
    path = folder + "/a.md"
    assert len(path) == length
    if beyond <= 0:
        Path(path).write_text("x", encoding="utf-8")
    else:
        with pytest.raises(OSError) as refused:                             # tried: the computer opens no longer path
            open(path, "w", encoding="utf-8").close()
        assert refused.value.errno == errno.ENAMETOOLONG
    assert guard.decide(write(path)) == expected
    assert guard.decide(event("Edit", file_path=path, old_string="a", new_string="b")) == expected
    outside = deep_folder(tmp_path, length - 5) + "/a.md"
    assert guard.decide(write(outside)) == expected


@pytest.mark.parametrize("beyond, expected", [(0, RECORDS), (1, UNCHECKED), (2, UNCHECKED)])
def test_a_link_at_the_very_edge_of_what_the_computer_opens_is_never_let_through(tmp_path, beyond, expected):
    run = make_run(tmp_path)
    (run / "notes").mkdir()
    (run / "facts" / "F1.json").write_text("old", encoding="utf-8")
    longest = longest_path(tmp_path)
    big = tmp_path / "big"
    big.mkdir()
    start = deep_folder(big, longest * 6 // 10)
    length = longest + beyond
    deep_folder(start, length - 2, link=("k", str(run / "facts" / "F1.json")))    # the link's own path: `length` bytes
    # A relative link: macOS puts a link's target in front of the rest of the path and opens nothing longer in all.
    (run / "notes" / "L1").symlink_to(os.path.relpath(start, run / "notes"), target_is_directory=True)
    below = [name for name in os.listdir(start)]
    path = f"{run}/notes/L1"
    while True:                                                             # walk down to the link, by short steps
        names = os.listdir(path)
        if names == ["k"]:
            break
        path += "/" + names[0]
    path += "/k"
    assert len(path) < longest * 6 // 10 and below
    with open(path, "w", encoding="utf-8") as handle:                       # the computer follows it to the record
        handle.write("new")
    assert (run / "facts" / "F1.json").read_text(encoding="utf-8") == "new"
    assert guard.decide(write(path)) == expected and refused_by_the_program(write(path), expected)


def test_a_link_the_computer_follows_but_cannot_be_asked_about_is_not_struck_out_by_a_step_back(tmp_path):
    # notes/M leads half the longest path down a tree; the tree goes on to 5 bytes beyond the longest path the
    # computer opens and holds a link k back to notes/x. The computer follows k; asked about k by its full path it
    # says "too long". Two steps back from k is the run.
    run = make_run(tmp_path)
    (run / "notes" / "x").mkdir(parents=True)
    (run / "facts" / "F1.json").write_text("old", encoding="utf-8")
    longest = longest_path(tmp_path)
    big = tmp_path / "big"
    big.mkdir()
    start = deep_folder(big, longest // 2)
    deep = deep_folder(start, longest + 5, link=("k", str(run / "notes" / "x")))
    assert len(deep + "/k") == longest + 7
    # A relative link: macOS puts a link's target in front of the rest of the path and opens nothing longer in all.
    (run / "notes" / "M").symlink_to(os.path.relpath(start, run / "notes"), target_is_directory=True)
    text = f"{run}/notes/M/{deep[len(start) + 1:]}/k/../../facts/F1.json"
    assert len(text) < longest
    assert os.path.samefile(text, run / "facts" / "F1.json")
    with open(text, "w", encoding="utf-8") as handle:                       # the computer lands on the record
        handle.write("new")
    assert (run / "facts" / "F1.json").read_text(encoding="utf-8") == "new"
    relative = text[len(f"{run}/"):]
    for asked in (write(text), event("Edit", file_path=text, old_string="a", new_string="b"),
                  event("NotebookEdit", notebook_path=text, new_source="x"), {**write(relative), "cwd": str(run)},
                  {**write(relative[len("notes/"):]), "cwd": str(run / "notes")}):
        assert guard.decide(asked) == UNCHECKED and refused_by_the_program(asked, UNCHECKED), asked["tool_name"]
    launched = launch(json.dumps(write(text)).encode("utf-8"), {"PATH": "/nowhere", "HOME": str(tmp_path), "RADAR_PYTHON": sys.executable})
    assert (launched.returncode, launched.stderr.decode("utf-8")) == (2, UNCHECKED + "\n")


def test_a_step_back_out_of_something_that_is_not_there_is_not_guessed(tmp_path):
    run = make_run(tmp_path)
    (run / "notes").mkdir()
    assert guard.decide(write(f"{run}/notes/not-there/../a.md")) == UNCHECKED
    assert guard.decide(write(f"{tmp_path}/not-there/../a.md")) == UNCHECKED
    assert guard.decide(write(f"{run}/notes/not-there/../../facts/F1.json")) == RECORDS      # tidied, it is a record
    assert guard.decide(write(f"{run}/notes/not-there/a.md")) is None
    assert guard.decide({**write("../notes/a.md"), "cwd": str(run / "notes")}) is None       # every part is there


def test_a_path_through_a_file_is_judged_as_a_place_below_it(tmp_path):
    # The computer opens no such path. The guard takes the safe side: what lies "below" a record is a record.
    run = make_run(tmp_path)
    (run / "notes").mkdir()
    (run / "facts" / "F1.json").write_text("{}", encoding="utf-8")
    (run / "notes" / "a.md").write_text("x", encoding="utf-8")
    assert guard.decide(write(f"{run}/facts/F1.json/x")) == RECORDS
    assert guard.decide(write(f"{run}/run.json/x/y")) == RECORDS
    assert guard.decide(write(f"{run}/notes/a.md/x")) is None
    assert guard.decide(write(f"{run}/notes/a.md/")) is None
    assert guard.decide(write(f"{run}/notes/a.md/../../facts/F1.json")) == RECORDS
    assert guard.decide(write(f"{run}/notes/a.md/../b.md")) == UNCHECKED
    assert guard.decide(write(f"{tmp_path}/run1/notes/a.md/..")) == RECORDS      # tidied: a file named notes at the run root
    assert guard.decide(write(f"{tmp_path}/run1/notes/a.md/../x/b.md")) == UNCHECKED


def test_a_project_reached_through_a_link_is_judged_like_any_other(tmp_path):
    real = tmp_path / "real project"
    run = make_run(real)
    (tmp_path / "link").symlink_to(real, target_is_directory=True)
    through = tmp_path / "link" / "run1"
    for target in ("analysis.json", "notes/a.md", "proposals/S1.json", "inbox/new/a.json"):
        assert guard.decide(write(through / target)) is None, target
        assert guard.decide({**write(target), "cwd": str(through)}) is None, target
    for target in ("run.json", "facts/F1.json", ".lock", "new.txt"):
        assert guard.decide(write(through / target)) == RECORDS, target
        assert guard.decide({**write(target), "cwd": str(through)}) == RECORDS, target
    assert guard.decide(write(tmp_path / "link" / "elsewhere.md")) is None
    assert run.is_dir()


def test_more_links_in_a_row_than_a_computer_follows_cannot_be_checked(tmp_path):
    run = make_run(tmp_path)
    (run / "notes").mkdir()
    (run / "notes" / "l0").symlink_to("../facts", target_is_directory=True)
    for number in range(1, 60):
        (run / "notes" / f"l{number}").symlink_to(f"l{number - 1}")

    def chain(links):                                   # notes/l<n> is a chain of n + 1 links ending at facts/
        return run / "notes" / f"l{links - 1}" / "F1.json"

    def opens(path):
        try:
            open(path, "w").close()
            return True
        except OSError as error:
            assert error.errno == errno.ELOOP
            return False

    follows = max(links for links in range(1, 61) if opens(chain(links)))    # tried: Linux 40, macOS 32
    assert not any(opens(chain(links)) for links in range(follows + 1, 61))
    assert follows <= guard.MOST_LINKS                  # the guard never gives up before the computer does
    for links in range(1, guard.MOST_LINKS + 1):        # judged by where it lands, also past where the computer gives up
        assert guard.decide(write(chain(links))) == RECORDS, links
    for links in (guard.MOST_LINKS + 1, 60):
        assert guard.decide(write(chain(links))) == UNCHECKED, links
        assert not opens(chain(links))                  # the computer gives up as well


def test_a_path_of_very_many_parts_that_are_all_there_is_decided_fast(tmp_path):
    import time
    run = make_run(tmp_path)
    (run / "notes").mkdir()
    longest = longest_path(tmp_path)
    for base, expected in ((run / "notes", None), (run / "facts", RECORDS), (tmp_path, None)):
        count = (longest - 95 - len(str(base))) // 2
        folder = os.open(str(base), os.O_RDONLY)
        try:
            for _ in range(count):
                os.mkdir("a", dir_fd=folder)
                deeper = os.open("a", os.O_RDONLY, dir_fd=folder)
                os.close(folder)
                folder = deeper
        finally:
            os.close(folder)
        path = str(base) + "/a" * count + "/x.md"
        assert longest - 100 < len(path) <= longest
        open(path, "w").close()                                             # the computer opens it
        started = time.monotonic()
        assert guard.decide(write(path)) == expected
        assert time.monotonic() - started < 2


LIMITED = """
import errno, importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("radar_guard", sys.argv[1])
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
asked = json.loads(sys.argv[2])
answers = [guard.decide(asked)]
real = {name: getattr(os, name) for name in ("lstat", "stat", "readlink")}
def limited(function, limit):
    def ask(path, *args, **kwargs):
        if len(os.fsencode(path)) >= limit:
            raise OSError(errno.ENAMETOOLONG, "File name too long")
        return function(path, *args, **kwargs)
    return ask
for names in (("lstat",), ("readlink",), ("lstat", "stat"), ("lstat", "stat", "readlink")):
    for name in real:
        setattr(os, name, limited(real[name], int(sys.argv[3])) if name in names else real[name])
    answers.append(guard.decide(asked))
print(json.dumps(answers))
"""


# Smaller computers imitated on this one: only a limit well below this computer's own can be imitated, because the
# tree that goes past it must still be built and opened here. On Linux all four; on macOS (1023 bytes) 255 and 512,
# and there the real limit is met in the tests above.
IMITATED_LIMITS = [limit for limit in (255, 512, 1024, 2048) if limit <= LONGEST_HERE * 3 // 4]


@pytest.mark.parametrize("limit", IMITATED_LIMITS)
@pytest.mark.parametrize("python", other_pythons() or [sys.executable])
def test_whatever_the_longest_path_a_computer_answers_about_a_link_behind_it_is_not_struck_out(tmp_path, python, limit):
    # The computer's limit is imitated: lstat alone, readlink alone, lstat and stat, all three fail from `limit` bytes on.
    assert limit + 200 < longest_path(tmp_path)
    run = make_run(tmp_path)
    (run / "notes" / "x" / "y").mkdir(parents=True)
    big = tmp_path / "big"
    big.mkdir()
    assert len(str(big)) + 80 < limit
    start = deep_folder(big, len(str(big)) + 60)
    deep = deep_folder(start, limit + 40, link=("k", str(run / "notes" / "x")))
    os.symlink(str(run / "notes" / "x" / "y"), deep + "/k3")
    (run / "notes" / "M").symlink_to(start, target_is_directory=True)
    below = deep[len(start) + 1:]
    for text in (f"{run}/notes/M/{below}/k/../../facts/F1.json", f"{run}/notes/M/{below}/k3/../../../facts/F1.json"):
        assert os.path.samefile(os.path.dirname(text), run / "facts")
        done = subprocess.run([python, "-c", LIMITED, str(GUARD), json.dumps(write(text)), str(limit)],
                              capture_output=True, text=True)
        assert done.stderr == ""
        assert json.loads(done.stdout) == [RECORDS, UNCHECKED, UNCHECKED, UNCHECKED, UNCHECKED], text[-30:]
    plain = subprocess.run([python, "-c", LIMITED, str(GUARD), json.dumps(write(f"{run}/notes/a.md")), str(limit)],
                           capture_output=True, text=True)
    assert json.loads(plain.stdout) == [None] * 5 or len(f"{run}/notes/a.md") >= limit


def lands_on_something_protected(text, protected_files, protected_folders, run_root):
    """Ask the computer itself where `text` lands: on a protected file, or as a new name in a protected folder."""
    try:
        found = os.stat(text)
        return (found.st_dev, found.st_ino) in protected_files
    except FileNotFoundError:
        pass
    except OSError:
        return False
    name = os.path.basename(text)
    if name in ("", ".", ".."):
        return False
    try:
        parent = os.stat(os.path.dirname(text) or "/")
    except OSError:
        return False
    where = (parent.st_dev, parent.st_ino)
    return where in protected_folders or (where == run_root and name != "analysis.json")


def test_wherever_the_computer_lands_on_a_record_the_guard_refuses(tmp_path):
    """Four thousand made-up paths over a small tree full of links, always the same ones (seeded).

    Whenever the computer says the text as written reaches a protected file or a new name in a protected folder,
    or says so of the tidied text, the guard must refuse.
    """
    import random
    run = make_run(tmp_path / "proj")
    outside = tmp_path / "outside" / "dir"
    outside.mkdir(parents=True)
    for folder in ("notes/sub", "inbox", "facts/more"):
        (run / folder).mkdir(parents=True)
    for name in ("facts/F1.json", "sources/S1.json", "notes/a.md", ".lock", "facts/more/F2.json"):
        (run / name).write_text("{}", encoding="utf-8")
    links = {"notes/tofacts": "../facts", "notes/away": str(outside), "notes/up": "..", "notes/abs": str(run),
             "notes/loop": "loop", "notes/chain": "tofacts", "notes/file": "../run.json", "inbox/x": "../notes/sub",
             "notes/sub/deepup": "../..", "notes/sub/rec": "../../facts/F1.json", "notes/dangling": "nothing/here",
             "notes/sub/sideways": "../../sources/S1.json", "inbox/out": str(tmp_path / "outside")}
    for name, target in links.items():
        os.symlink(target, run / name)
    os.symlink(str(run / "facts"), outside / "back")
    os.symlink(str(run), tmp_path / "outside" / "in")
    os.symlink("../../proj/run1/notes", outside / "tonotes")

    def identity(path):
        found = os.stat(path)
        return (found.st_dev, found.st_ino)

    protected_files = {identity(run / name) for name in ("run.json", "facts/F1.json", "sources/S1.json", ".lock",
                                                         ".gitignore", "facts/more/F2.json", "copies/.gitignore")}
    protected_folders = {identity(run / name) for name in ("facts", "sources", "copies", "report", "facts/more")}
    parts = ["..", "..", ".", "", "notes", "inbox", "facts", "sources", "sub", "more", "F1.json", "run.json", "a.md", "new.md",
             "analysis.json", ".lock", "tofacts", "away", "up", "abs", "loop", "chain", "file", "x", "deepup", "rec",
             "dangling", "sideways", "out", "back", "in", "tonotes", "dir", "run1", "proj", "outside", "nothing"]
    starts = [str(run), str(run / "notes"), str(run / "notes" / "sub"), str(run / "inbox"), str(outside), str(tmp_path)]
    chooser = random.Random(17)
    landed = refused = passed = 0
    for _ in range(4000):
        text = chooser.choice(starts) + "/" + "/".join(chooser.choice(parts) for _ in range(chooser.randint(1, 7)))
        answer = guard.decide(write(text))
        inside = text.startswith(str(run) + "/") and chooser.random() < 0.5
        answers = {answer, guard.decide({**write(text[len(str(run)) + 1:].lstrip("/") or "." if inside else text), "cwd": str(run)})}
        if chooser.random() < 0.3:
            answers.add(guard.decide(event("NotebookEdit", notebook_path=text, new_source="x")))
        reached = (lands_on_something_protected(text, protected_files, protected_folders, identity(run))
                   or lands_on_something_protected(os.path.normpath(text), protected_files, protected_folders, identity(run)))
        if reached:
            landed += 1
            assert None not in answers, text
        refused += answer is not None
        passed += answer is None
    assert landed > 100 and passed > 400 and refused > landed


IMITATION = """
import errno, importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("radar_guard", sys.argv[1])
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
asked = json.loads(sys.argv[2])
print(json.dumps(guard.decide(asked)))
def limited(real):
    def ask(path, *args, **kwargs):
        if len(os.fsencode(path)) >= int(sys.argv[3]):
            raise OSError(errno.ENAMETOOLONG, "File name too long")
        return real(path, *args, **kwargs)
    return ask
os.lstat, os.stat, os.readlink = limited(os.lstat), limited(os.stat), limited(os.readlink)
print(json.dumps(guard.decide(asked)))
"""


@pytest.mark.parametrize("python", other_pythons() or [sys.executable])
def test_a_computer_that_opens_only_shorter_paths_does_not_open_a_way_round(tmp_path, python):
    # Some computers stop sooner than this one (on Linux: macOS's 1024 bytes; on macOS: half its own limit).
    # That is imitated: every question about a longer path fails.
    run = make_run(tmp_path)
    (run / "notes").mkdir()
    longest = longest_path(tmp_path)
    smaller = min(1024, longest // 2 + 1)
    big = tmp_path / "big"
    big.mkdir()
    far = deep_folder(big, (smaller + longest) // 2, link=("back2", str(run / "facts")))
    (run / "notes" / "L1").symlink_to(far, target_is_directory=True)
    path = f"{run}/notes/L1/back2/F1.json"
    assert len(path) < 300 and len(far + "/back2") < longest
    assert os.path.samefile(os.path.dirname(path), run / "facts")         # this computer follows it to the records
    done = subprocess.run([python, "-c", IMITATION, str(GUARD), json.dumps(write(path)), str(smaller)],
                          capture_output=True, text=True)
    assert done.stderr == ""
    assert [json.loads(line) for line in done.stdout.splitlines()] == [RECORDS, UNCHECKED]
    plain = subprocess.run([python, "-c", IMITATION, str(GUARD), json.dumps(write(f"{run}/notes/a.md")), str(smaller)],
                           capture_output=True, text=True)
    assert [json.loads(line) for line in plain.stdout.splitlines()] == [None, None]      # ordinary work is not touched


def test_links_that_lead_nowhere_or_in_a_circle_cannot_be_checked(tmp_path):
    run = make_run(tmp_path)
    (run / "notes").mkdir()
    (run / "notes" / "self").symlink_to("self")
    (run / "notes" / "a").symlink_to("b")
    (run / "notes" / "b").symlink_to("a")
    for name in ("self", "self/x.md", "a", "a/x.md", "b/deeper/x.md"):
        assert guard.decide(write(run / "notes" / name)) == UNCHECKED, name
        assert guard.decide({**write("notes/" + name), "cwd": str(run)}) == UNCHECKED, name
    outside = tmp_path / "loop"
    outside.symlink_to("loop")
    assert guard.decide(write(outside / "x.md")) == UNCHECKED and refused_by_the_program(write(outside / "x.md"), UNCHECKED)
    assert guard.decide(write(run / "notes" / ("x" * 300))) == UNCHECKED             # a name no computer holds
    assert guard.decide(write(tmp_path / ("x" * 300) / "a.md")) == UNCHECKED


def test_a_chain_of_links_the_computer_follows_is_judged_by_where_it_ends(tmp_path):
    run = make_run(tmp_path)
    for folder in ("notes", "inbox"):
        (run / folder).mkdir()
    (run / "notes" / "c1").symlink_to("c2")
    (run / "notes" / "c2").symlink_to("c3")
    (run / "notes" / "c3").symlink_to("../facts", target_is_directory=True)
    assert guard.decide(write(run / "notes" / "c1" / "F1.json")) == RECORDS
    (run / "notes" / "d1").symlink_to("d2")
    (run / "notes" / "d2").symlink_to("../inbox", target_is_directory=True)
    assert guard.decide(write(run / "notes" / "d1" / "a.json")) is None
    (run / "notes" / "new").symlink_to("not-there-yet.md")                  # a link to a file that is not there yet
    assert guard.decide(write(run / "notes" / "new")) is None
    (tmp_path / "out").symlink_to(tmp_path / "nothing" / "here.md")
    assert guard.decide(write(tmp_path / "out")) is None


def test_ordinary_work_is_let_through(tmp_path, monkeypatch):
    run = make_run(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    odd = "My files (1) [draft] B" + chr(0xFC) + "ro " + chr(0x1F600) + " & more"
    (tmp_path / odd).mkdir()
    (tmp_path / "there.md").write_text("x", encoding="utf-8")
    for path in (tmp_path / "there.md", tmp_path / "new.md", tmp_path / odd / "a b.md", tmp_path / odd / "new" / "deeper" / "a.md",
                 tmp_path / "a" / "b" / "c" / "d" / "e" / "new.md", run / "notes" / "a" / "b" / "c" / "d" / "new.md",
                 run / "notes" / odd / "a.md", run / "analysis.json", run / "proposals" / "S1.json", run / "inbox" / "a.json"):
        for asked in (write(path), event("Edit", file_path=str(path), old_string="a", new_string="b"),
                      event("NotebookEdit", notebook_path=str(path), new_source="x")):
            assert guard.decide(asked) is None, path
    for asked in ({**write("new.md"), "cwd": str(tmp_path)}, {**write(odd + "/new/a.md"), "cwd": str(tmp_path)},
                  {**write("notes/a.md"), "cwd": str(run)}, {**write("~/x.md"), "cwd": str(tmp_path)}, write("~/new/x.md")):
        assert guard.decide(asked) is None, asked
    monkeypatch.chdir(tmp_path)
    assert guard.decide(write("new.md")) is None and guard.decide(write(odd + "/a.md")) is None       # no folder named


def test_the_guard_does_not_need_a_folder_of_its_own(tmp_path):
    # The folder the hook was started in is gone; the event still says where the session is.
    run = make_run(tmp_path)
    gone = tmp_path / "gone"
    gone.mkdir()
    script = 'rmdir "$1" && exec "$2" "$3"'
    for asked, code, reason in ((write(run / "facts" / "F1.json"), 2, RECORDS + "\n"),
                                ({**write("facts/F1.json"), "cwd": str(run)}, 2, RECORDS + "\n"),
                                ({**write(run / "notes" / "a.md"), "cwd": str(run)}, 0, ""),
                                (write("x/a.md"), 0, "")):                  # no folder named: read from the top folder
        gone.mkdir(exist_ok=True)
        result = subprocess.run(["/bin/sh", "-c", script, "sh", str(gone), sys.executable, str(GUARD)],
                                input=json.dumps({**asked, "cwd": asked.get("cwd", str(tmp_path))} if code else asked).encode("utf-8"),
                                capture_output=True, cwd=gone)
        assert not gone.exists()
        assert (result.returncode, result.stdout, result.stderr.decode("utf-8")) == (code, b"", reason), asked


def test_a_link_into_a_tree_too_deep_to_follow_is_refused(tmp_path):
    # notes/L1 leads far down a tree; seven more folders on, the real place is longer than a computer opens,
    # and there a link leads back to facts/. The computer follows it; the guard cannot, so it refuses.
    run = make_run(tmp_path)
    (run / "notes").mkdir()
    longest = longest_path(tmp_path)
    big = tmp_path / "big"
    big.mkdir()
    step = min(201, (longest - len(str(run)) - 30) // 8)                   # so that the text below stays short enough
    name = "n" * (step - 1)
    target = Path(deep_folder(big, longest + 1 - 7 * step))                # seven more folders pass the limit by a byte
    assert len(str(target)) < longest < len(str(target)) + 7 * step
    # A relative link: macOS puts a link's target in front of the rest of the path and opens nothing longer in all.
    (run / "notes" / "L1").symlink_to(os.path.relpath(target, run / "notes"), target_is_directory=True)
    folder = os.open(str(target), os.O_RDONLY)
    try:
        for _ in range(7):
            os.mkdir(name, dir_fd=folder)
            deeper = os.open(name, os.O_RDONLY, dir_fd=folder)
            os.close(folder)
            folder = deeper
        os.symlink(str(run / "facts"), "back", dir_fd=folder)
    finally:
        os.close(folder)
    path = f"{run}/notes/L1/" + "/".join([name] * 7) + "/back/F1.json"
    assert len(path) < longest
    with open(path, "w", encoding="utf-8") as handle:                       # the computer really lands on the record
        handle.write("{}")
    assert (run / "facts" / "F1.json").read_text(encoding="utf-8") == "{}"
    assert guard.decide(write(path)) == UNCHECKED and refused_by_the_program(write(path), UNCHECKED)
    assert guard.decide(write(f"{run}/notes/L1/a.md")) is None             # a link out of the run, short enough to follow


def test_a_relative_path_that_is_too_long_only_together_with_its_folder_is_refused(tmp_path):
    run = make_run(tmp_path)
    (run / "notes" / "a").mkdir(parents=True)
    (run / "notes" / "out").symlink_to("../sources", target_is_directory=True)
    name = "a/../" * 800 + "out/../facts/F1.json"
    assert len(name) == 4020 < guard.LONGEST_PATH
    name = "a/../" * 14 + name                    # so that it is too long with the folder wherever the tests run
    assert len(name) <= guard.LONGEST_PATH < len(f"{run}/notes/{name}")
    asked = {**write(name), "cwd": str(run / "notes")}
    assert guard.decide(asked) == UNCHECKED and refused_by_the_program(asked, UNCHECKED)
    short = {**write("a/../" * 8 + "out/../facts/F1.json"), "cwd": str(run / "notes")}
    assert guard.decide(short) == RECORDS and refused_by_the_program(short)


def test_a_link_that_points_at_a_record_is_refused(tmp_path):
    run = make_run(tmp_path)
    (run / "facts" / "F1.json").write_text("{}", encoding="utf-8")
    (run / "notes").mkdir()
    (run / "notes" / "innocent.md").symlink_to(run / "facts" / "F1.json")
    assert guard.decide(write(run / "notes" / "innocent.md")) == RECORDS
    (run / "notes" / "folder").symlink_to(run / "facts", target_is_directory=True)
    assert guard.decide(write(run / "notes" / "folder" / "F2.json")) == RECORDS
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "shortcut").symlink_to(run, target_is_directory=True)
    assert guard.decide(write(outside / "shortcut" / "run.json")) == RECORDS
    (outside / "one.json").symlink_to(run / "sources" / "S1.json")           # the link's target does not exist yet
    assert guard.decide(write(outside / "one.json")) == RECORDS
    (run / "analysis.json").unlink(missing_ok=True)
    (run / "analysis.json").symlink_to(run / "facts" / "F1.json")             # even the lead's own file name
    assert guard.decide(write(run / "analysis.json")) == RECORDS


def test_a_link_in_one_of_the_lead_s_places_may_only_lead_to_the_lead_s_places(tmp_path):
    run = make_run(tmp_path)
    for folder in ("notes", "proposals", "inbox"):
        (run / folder).mkdir()
    (run / "notes" / "lock").symlink_to(run / ".lock")
    (run / "proposals" / "fetch").symlink_to(run / ".last_fetch.json")
    (run / "inbox" / "root").symlink_to(run, target_is_directory=True)
    (run / "notes" / "new").symlink_to(run / "something-new.txt")
    for link in ("notes/lock", "proposals/fetch", "inbox/root/new.txt", "inbox/root/run.json", "notes/new"):
        assert guard.decide(write(run / link)) == RECORDS, link
    (run / "notes" / "draft").symlink_to(run / "analysis.json")
    (run / "notes" / "other").symlink_to(run / "inbox", target_is_directory=True)
    (run / "notes" / "out").symlink_to(tmp_path / "elsewhere.md")
    for link in ("notes/draft", "notes/other/a.json", "notes/out", "inbox/root/notes/a.md", "inbox/root/analysis.json"):
        assert guard.decide(write(run / link)) is None, link


PADDING = ["./" * 2100, "a/../" * 1400, "/" * 5000, "./" * 40000, "/./" * 3000 + "//"]


@pytest.mark.parametrize("padding", PADDING)
def test_padding_a_path_beyond_what_a_computer_opens_does_not_hide_a_link(tmp_path, padding):
    run = make_run(tmp_path / "one")
    (run / "notes").mkdir()
    (run / "notes" / "lk").symlink_to("../facts", target_is_directory=True)
    for path in (f"{run}/notes/lk/{padding}F1.json", f"{run}/notes/{padding}lk/F1.json",
                 f"{tmp_path}/{padding}one/run1/notes/lk/F1.json", f"/{padding}{str(run)[1:]}/notes/lk/F1.json"):
        assert len(path) > guard.LONGEST_PATH
        assert guard.decide(write(path)) == UNCHECKED and refused_by_the_program(write(path), UNCHECKED), path[:80]
    assert guard.decide(write(f"{run}/notes/{padding}a.md")) == UNCHECKED     # the harmless twin too: it cannot be checked

    other = make_run(tmp_path / "two")
    (other / "analysis.json").symlink_to("run.json")
    shutil.rmtree(other / "copies")
    (other / "notes").symlink_to("facts", target_is_directory=True)
    for name in ("analysis.json", "notes/F1.json"):
        path = f"{other}/{padding}{name}"
        assert guard.decide(write(path)) == UNCHECKED and refused_by_the_program(write(path), UNCHECKED), name
        assert guard.decide(write(f"{other}/./{name}")) == RECORDS, name

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "in").symlink_to(run / "facts", target_is_directory=True)
    path = f"{outside}/{padding}in/F1.json"
    assert guard.decide(write(path)) == UNCHECKED and refused_by_the_program(write(path), UNCHECKED)
    assert guard.decide(write(f"{outside}/././/in/F1.json")) == RECORDS

    for cwd, name in ((f"{run}/notes/{padding}", "lk/F1.json"), (f"{run}/{padding}notes", "lk/F1.json"),
                      (f"{outside}/{padding}", "in/F1.json")):
        asked = {**write(name), "cwd": cwd}
        assert guard.decide(asked) == UNCHECKED and refused_by_the_program(asked, UNCHECKED), name


def test_a_detour_through_a_link_that_leads_away_does_not_hide_a_link_that_leads_back(tmp_path):
    # Followed step by step the path leaves the run; with the detour struck out first it lands on a record.
    run = make_run(tmp_path)
    away = tmp_path / "far" / "away"
    away.mkdir(parents=True)
    (run / "notes").mkdir()
    (run / "notes" / "away").symlink_to(away, target_is_directory=True)
    (run / "notes" / "lk").symlink_to("../facts", target_is_directory=True)
    asked = write(f"{run}/notes/away/../lk/F1.json")
    assert guard.decide(asked) == RECORDS and refused_by_the_program(asked)
    assert guard.decide(write(f"{run}/notes/away/../a.md")) is None


def test_a_detour_that_only_lands_on_a_record_when_followed_step_by_step_is_refused_too(tmp_path):
    # The other way round: struck out first the path stays under notes/, followed step by step it is a record.
    run = make_run(tmp_path)
    (run / "notes").mkdir()
    (run / "notes" / "out").symlink_to("../sources", target_is_directory=True)
    for padding, reason in (("", RECORDS), ("./" * 20, RECORDS), ("/" * 50, RECORDS), ("./" * 2100, UNCHECKED),
                            ("/" * 5000, UNCHECKED), ("./" * 40000, UNCHECKED)):
        asked = write(f"{run}/notes/{padding}out/../facts/F1.json")
        assert guard.decide(asked) == reason and refused_by_the_program(asked, reason), len(padding)


def test_a_records_folder_that_is_itself_a_link_is_still_protected(tmp_path):
    run = make_run(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    shutil.rmtree(run / "facts")
    (run / "facts").symlink_to(elsewhere, target_is_directory=True)
    assert guard.decide(write(run / "facts" / "F1.json")) == RECORDS


def test_a_file_that_does_not_exist_yet_is_judged_by_where_it_would_be(tmp_path):
    run = make_run(tmp_path)
    assert guard.decide(write(run / "facts" / "new" / "deeper" / "F99.json")) == RECORDS
    assert guard.decide(write(run / "changes.json")) == RECORDS
    assert guard.decide(write(run / "notes" / "new" / "deeper" / "a.md")) is None


def test_only_the_exact_names_of_the_lead_s_places_are_let_through(tmp_path):
    # Some computers treat Facts/ and facts/ as one folder. Only the four names as written pass, so that cannot matter.
    run = make_run(tmp_path)
    for target in ("Facts/F1.json", "FACTS/f1.json", "Run.JSON", "CHANGES.json", "Report/x.html", ".GitIgnore",
                   "NOTES/a.md", "Inbox/a.json", "ANALYSIS.JSON"):
        assert guard.decide(write(run / target)) == RECORDS, target


def test_a_made_up_run_inside_a_run_hides_nothing(tmp_path):
    run = make_run(tmp_path)
    (run / "facts" / "run.json").write_text("{}", encoding="utf-8")
    (run / "facts" / "facts").mkdir()
    assert guard.decide(write(run / "facts" / "F1.json")) == RECORDS
    assert guard.decide(write(run / "facts" / "analysis.json")) == RECORDS
    assert guard.decide(write(run / "facts" / "notes" / "a.md")) == RECORDS
    inner = run / "notes" / "copy"
    (inner / "facts").mkdir(parents=True)
    (inner / "sources").mkdir()
    (inner / "run.json").write_text("{}", encoding="utf-8")
    assert guard.decide(write(inner / "facts" / "F1.json")) == RECORDS
    assert guard.decide(write(inner / "notes" / "a.md")) is None


def test_a_helper_may_not_write_a_record_either(tmp_path):
    run = make_run(tmp_path)
    for helper in ("strategy-radar:fact-extractor", CHECKER, "general-purpose"):
        assert guard.decide(write(run / "facts" / "F1.json") | {"agent_type": helper}) == RECORDS


def test_reading_a_record_is_nobody_s_business_here(tmp_path):
    run = make_run(tmp_path)
    assert guard.decide(event("Read", file_path=str(run / "facts" / "F1.json"))) is None
    assert guard.decide(event("Glob", path=str(run / "facts"), pattern="*.json")) is None


@pytest.mark.parametrize("name, key", [("lead_write", "file_path"), ("lead_edit", "file_path"),
                                       ("lead_notebook_edit", "notebook_path")])
def test_the_recorded_real_writing_events_carry_the_names_the_guard_reads(tmp_path, name, key):
    real = recorded(name)
    assert real["tool_name"] in guard.WRITING_TOOLS and "agent_type" not in real
    assert isinstance(real["tool_input"][key], str) and os.path.isabs(real["cwd"])
    assert guard.decide(real) is None                                    # as recorded: a file in no run
    run = make_run(tmp_path)
    into_a_run = {**real, "cwd": str(run), "tool_input": {**real["tool_input"], key: str(run / "facts" / "F8.json")}}
    assert guard.decide(into_a_run) == RECORDS
    relative = {**real, "cwd": str(run), "tool_input": {**real["tool_input"], key: "sources/S1.json"}}
    assert guard.decide(relative) == RECORDS
    own = {**real, "cwd": str(run), "tool_input": {**real["tool_input"], key: str(run / "notes" / "a.md")}}
    assert guard.decide(own) is None


# ---------------------------------------------------------------- rule 1: places the computer names in its own ways

@pytest.mark.skipif(not os.path.isdir("/dev/fd"), reason="this computer has no /dev/fd (macOS and Linux both have it)")
def test_a_place_that_each_program_sees_for_itself_cannot_be_checked(tmp_path):
    # /dev/fd/N is whatever the asking program has open as number N. The guard is a program of its own and cannot
    # see what the writing tool has open (ruling T17k). Tried: with a record open as a number, a write by that name
    # changes the record, and even in the same program the name tells nothing about where it leads.
    run = make_run(tmp_path)
    record = run / "facts" / "F1.json"
    record.write_text("old", encoding="utf-8")
    number = os.open(record, os.O_RDWR)
    try:
        by_number = f"/dev/fd/{number}"
        with open(by_number, "w", encoding="utf-8") as handle:
            handle.write("new")
        assert record.read_text(encoding="utf-8") == "new"
        assert guard.decide(write(by_number)) == UNCHECKED
    finally:
        os.close(number)
    (tmp_path / "fd").symlink_to("/dev/fd", target_is_directory=True)
    for path in ("/dev/fd/0", "/dev/fd/1", "/dev/fd/2", "/dev/fd/1/x.md", "/dev/stdin", "/dev/stdout", "/dev/stderr",
                 "/dev//fd/1", "/dev/./fd/1", "/dev/fd/../fd/1", f"{tmp_path}/fd/1", "/dev/fd"):
        asked = write(path)
        assert guard.decide(asked) == UNCHECKED and refused_by_the_program(asked, UNCHECKED), path
        assert guard.decide(event("NotebookEdit", notebook_path=path, new_source="x")) == UNCHECKED, path
    assert guard.decide({**write("fd/1"), "cwd": "/dev"}) == UNCHECKED
    assert guard.decide(write("/dev/null")) is None                         # the rest of /dev is no such place


@pytest.mark.skipif(not os.path.isdir("/proc/self"), reason="this computer has no /proc (macOS has none)")
def test_a_place_under_proc_cannot_be_checked_in_either_rule(tmp_path, monkeypatch):
    # /proc/self is the asking program itself: its folder, its open files, its view of the top folder (ruling T17k).
    make_run(tmp_path)
    monkeypatch.chdir(tmp_path)
    for path in ("/proc/self/cwd/new.md", "/proc/self/cwd/run1/notes/a.md", f"/proc/self/root{tmp_path}/new.md",
                 f"/proc/{os.getpid()}/cwd/new.md", "/proc/self/fd/1", "/proc"):
        assert guard.decide(write(path)) == UNCHECKED, path
    monkeypatch.chdir(ROOT)
    assert not guard._is_own_radar("/proc/self/cwd/bin/radar")
    assert guard.decide(event("Bash", CHECKER, command="/proc/self/cwd/bin/radar quote-context --run x --fact F1")) == HELPER


def test_a_place_marked_as_seen_differently_cannot_be_checked_in_either_rule(tmp_path, monkeypatch):
    # The rule itself, on any computer: a folder the guard knows as such a place (by what the computer says it is,
    # not by its name) makes every path into it, however spelled or linked, one that cannot be checked.
    run = make_run(tmp_path)
    (run / "notes").mkdir()
    marked = tmp_path / "marked"
    (marked / "inner").mkdir(parents=True)
    (marked / "plugin").symlink_to(ROOT, target_is_directory=True)
    (marked / "back").symlink_to(run, target_is_directory=True)
    (tmp_path / "to-marked").symlink_to(marked, target_is_directory=True)
    found = os.lstat(marked)
    monkeypatch.setattr(guard, "SHORTCUTS", guard.SHORTCUTS | {(found.st_dev, found.st_ino)})
    for path in (f"{marked}/new.md", f"{marked}/inner/new.md", f"{tmp_path}/to-marked/new.md", f"{marked}/back/notes/a.md",
                 f"{tmp_path}/./marked//inner/../new.md", str(marked)):
        assert guard.decide(write(path)) == UNCHECKED, path
    assert guard.decide({**write("marked/new.md"), "cwd": str(tmp_path)}) == UNCHECKED
    assert guard.decide(write(f"{marked}/back/facts/F1.json")) == RECORDS   # the tidied text is a record
    assert guard.decide(write(f"{tmp_path}/new.md")) is None
    assert guard.decide(write(f"{run}/notes/a.md")) is None
    assert not guard._is_own_radar(f"{marked}/plugin/bin/radar")              # rule 2: not this plugin's program
    linked = tmp_path / "plugin-link"
    linked.symlink_to(ROOT, target_is_directory=True)
    assert guard._is_own_radar(f"{linked}/bin/radar")                       # the same, outside the marked folder


@pytest.mark.skipif(not (sys.platform == "darwin" and os.path.isdir("/.vol")),
                    reason="only macOS opens a file by its numbers, under /.vol")
def test_a_place_named_by_its_numbers_cannot_be_checked(tmp_path):
    run = make_run(tmp_path)
    (run / "notes").mkdir()
    record = run / "facts" / "F1.json"
    record.write_text("old", encoding="utf-8")

    def numbers(path):
        found = os.stat(path)
        return f"/.vol/{found.st_dev}/{found.st_ino}"

    facts, notes, the_run, the_record = numbers(run / "facts"), numbers(run / "notes"), numbers(run), numbers(record)
    with open(f"{facts}/F1.json", "w", encoding="utf-8") as handle:         # the computer opens the record so
        handle.write("new")
    assert record.read_text(encoding="utf-8") == "new"
    (tmp_path / "vol").symlink_to("/.vol", target_is_directory=True)
    for path in (f"{facts}/F1.json", the_record, f"{facts}/F9.json", f"{notes}/a.md", f"{the_run}/notes/a.md",
                 f"/{facts}/F1.json", f"/.{facts}/F1.json", f"/tmp/..{facts}/F1.json", f"{tmp_path}/vol{facts[5:]}/F1.json"):
        asked = write(path)
        assert guard.decide(asked) == UNCHECKED and refused_by_the_program(asked, UNCHECKED), path
    assert guard.decide({**write(f"{facts[1:]}/F1.json"), "cwd": "/"}) == UNCHECKED
    assert guard.decide(write(f"{the_run}/facts/F1.json")) == RECORDS       # seen as a run folder: refused as a record


def test_a_file_that_has_another_name_as_well_is_not_written_by_hand(tmp_path):
    # A hard link is a second name of the same file. Where the other names are, the guard cannot see; no other
    # spelling of the path helps, so the refusal says what does: a fresh copy under a new name.
    run = make_run(tmp_path)
    (run / "notes").mkdir()
    record = run / "facts" / "F1.json"
    record.write_text("old", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.link(record, elsewhere / "twin.json")
    with open(elsewhere / "twin.json", "w", encoding="utf-8") as handle:     # the computer writes the record
        handle.write("new")
    assert record.read_text(encoding="utf-8") == "new"
    os.link(run / "run.json", run / "notes" / "run-copy.json")
    (elsewhere / "pointer.json").symlink_to(elsewhere / "twin.json")
    for path in (elsewhere / "twin.json", run / "notes" / "run-copy.json", elsewhere / "pointer.json"):
        for asked in (write(path), event("Edit", file_path=str(path), old_string="a", new_string="b"),
                      event("NotebookEdit", notebook_path=str(path), new_source="x")):
            assert guard.decide(asked) == SECOND_NAME, path
        assert refused_by_the_program(write(path), SECOND_NAME)
    assert guard.decide({**write("twin.json"), "cwd": str(elsewhere)}) == SECOND_NAME
    assert guard.decide(write(f"{elsewhere}/twin.json/below")) == SECOND_NAME   # a place below it lands in it too
    (elsewhere / "a.md").write_text("x", encoding="utf-8")                  # the price: an ordinary file with two names
    os.link(elsewhere / "a.md", elsewhere / "b.md")
    assert guard.decide(write(elsewhere / "a.md")) == SECOND_NAME
    os.unlink(elsewhere / "b.md")
    assert guard.decide(write(elsewhere / "a.md")) is None                  # one name again
    assert guard.decide(write(elsewhere / "a.md/below")) is None
    assert guard.decide(write(elsewhere / "new.md")) is None
    assert guard.decide(write(f"{elsewhere}/{'x' * 300}/twin.json")) == UNCHECKED    # other cases keep their sentence


@pytest.mark.skipif(sys.platform != "darwin", reason="only macOS opens a file's second stream as file/..namedfork/rsrc")
def test_a_write_to_the_second_stream_of_a_file_with_a_second_name_is_not_let_through(tmp_path):
    # On macOS file/..namedfork/rsrc is a second stream of the same file: writing it changes the file's attributes
    # and its time, whichever of its names the path goes through.
    run = make_run(tmp_path)
    (run / "notes").mkdir()
    for name in ("F1.json", "F2.json"):
        (run / "facts" / name).write_text("{}", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.link(run / "facts" / "F2.json", elsewhere / "twin.json")
    stream = f"{elsewhere}/twin.json/..namedfork/rsrc"
    for asked in (write(stream), event("Edit", file_path=stream, old_string="a", new_string="b"),
                  event("NotebookEdit", notebook_path=stream, new_source="x")):
        assert guard.decide(asked) == SECOND_NAME, asked["tool_name"]
    assert refused_by_the_program(write(stream), SECOND_NAME)
    before = os.stat(run / "facts" / "F2.json").st_mtime_ns
    with open(stream, "wb") as handle:                                      # tried: the record is changed
        handle.write(b"x")
    assert os.stat(run / "facts" / "F2.json").st_mtime_ns != before
    assert guard.decide(write(stream)) == SECOND_NAME                       # and once the stream is there as well
    inside = f"{run}/facts/F1.json/..namedfork/rsrc"
    assert guard.decide(write(inside)) == RECORDS and refused_by_the_program(write(inside))
    (run / "notes" / "a.md").write_text("x", encoding="utf-8")
    assert guard.decide(write(f"{run}/notes/a.md/..namedfork/rsrc")) is None    # a file of one name in the lead's place


def a_run_in_a_folder_with_an_umlaut(tmp_path):
    """A run below Proj/Bär (the ä written as one character), with notes/, a source and a fact record."""
    run = make_run(tmp_path / "Proj" / unicodedata.normalize("NFC", "B" + chr(0xE4) + "r"))
    (run / "notes").mkdir()
    for name in ("sources/S1.json", "facts/F1.json"):
        (run / name).write_text("{}", encoding="utf-8")
    return run


def other_spellings(run):
    """The run folder spelled in other ways: other case, the ä in two characters, both. Each with where it leads."""
    decomposed = unicodedata.normalize("NFD", run.parent.name)
    assert decomposed != run.parent.name
    return [run.parent / "RUN1", run.parent.parent.parent / "PROJ" / run.parent.name / run.name,
            run.parent.parent / decomposed / run.name, run.parent.parent / decomposed.upper() / "Run1"]


def test_another_spelling_of_a_name_in_a_run_folder_is_refused_on_any_computer(tmp_path):
    # Inside a run folder only the four names as written pass. On a computer that ignores case these spellings
    # are the records themselves (asked below); on one that does not, they are new names in the run folder.
    run = a_run_in_a_folder_with_an_umlaut(tmp_path)
    for name in ("RUN.JSON", "Run.Json", "Facts/F1.json", "SOURCES/s1.json", "facts/f1.JSON", "NOTES/a.md",
                 "Analysis.JSON", "Inbox/a.json"):
        assert guard.decide(write(f"{run}/{name}")) == RECORDS, name
        assert guard.decide({**write(name), "cwd": str(run)}) == RECORDS, name
    if os.path.exists(run / "RUN.JSON"):                                    # this computer ignores case
        assert os.path.samefile(run / "Facts" / "F1.json", run / "facts" / "F1.json")
    for leading in ("/", "//"):                                             # a leading // may mean something else
        assert guard.decide(write(f"{leading}{run}/facts/F1.json")) == RECORDS, leading
        assert guard.decide(write(f"{leading}{run}/notes/a.md")) is None, leading


def test_a_run_reached_by_another_spelling_of_a_folder_is_judged_by_what_the_computer_says(tmp_path):
    run = a_run_in_a_folder_with_an_umlaut(tmp_path)
    for folder in other_spellings(run):
        same = os.path.isdir(folder) and os.path.samefile(folder, run)      # macOS: yes; most Linux disks: no
        expected = RECORDS if same else None
        assert guard.decide(write(f"{folder}/facts/F1.json")) == expected, folder
        assert guard.decide(write(f"{folder}/run.json")) == expected, folder
        assert guard.decide({**write("facts/F1.json"), "cwd": str(folder)}) == expected, folder
        assert guard.decide(write(f"{folder}/notes/a.md")) is None, folder


EXACT_NAMES = """
import errno, importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("radar_guard", sys.argv[1])
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
def as_written(path):
    # Every part must be in its folder exactly as written, byte for byte, as on a computer that tells names
    # apart by every byte (most Linux disks).
    text = os.fsencode(path)
    folder = b"/" if text.startswith(b"/") else b"."
    for part in text.split(b"/"):
        if part in (b"", b"."):
            continue
        if part == b"..":
            return True                     # not imitated; the guard asks about no such text
        try:
            names = os.listdir(folder)
        except OSError:
            return True                     # a folder that may not be listed: the computer answers
        if part not in names:
            return False
        folder = os.path.join(folder, part)
    return True
def exact(real):
    def ask(path, *args, **kwargs):
        if not as_written(path):
            raise FileNotFoundError(errno.ENOENT, "No such file or directory")
        return real(path, *args, **kwargs)
    return ask
os.lstat, os.stat = exact(os.lstat), exact(os.stat)
print(json.dumps([guard.decide(asked) for asked in json.loads(sys.argv[2])]))
"""


def test_on_a_computer_that_tells_every_spelling_apart_another_spelling_is_another_place(tmp_path):
    # Imitated here: every question about a name that is not written exactly as on the disk finds nothing.
    run = a_run_in_a_folder_with_an_umlaut(tmp_path)
    asked = [write(f"{folder}/facts/F1.json") for folder in other_spellings(run)]
    asked += [{**write("facts/F1.json"), "cwd": str(folder)} for folder in other_spellings(run)]
    asked += [write(f"{run}/{name}") for name in ("RUN.JSON", "Facts/F1.json", "NOTES/a.md", "facts/F1.json", "notes/a.md")]
    done = subprocess.run([sys.executable, "-c", EXACT_NAMES, str(GUARD), json.dumps(asked)], capture_output=True, text=True)
    assert done.stderr == ""
    assert json.loads(done.stdout) == [None] * 8 + [RECORDS, RECORDS, RECORDS, RECORDS, None]


@pytest.mark.skipif(not (os.path.islink("/var") and os.path.realpath("/var") == "/private/var"
                         and os.path.realpath(tempfile.gettempdir()).startswith("/private/var/")),
                    reason="only macOS reaches /private/var also as /var, and the test folders must lie there")
def test_a_run_reached_as_var_or_as_private_var_is_the_same_run(tmp_path):
    run = os.path.realpath(make_run(tmp_path))
    (Path(run) / "notes").mkdir()
    short = run[len("/private"):]
    for spelled in (run, short, "/VAR" + short[len("/var"):], "/private/../var" + short[len("/var"):]):
        same = os.path.isdir(spelled) and os.path.samefile(spelled, run)
        expected = RECORDS if same else None
        assert guard.decide(write(f"{spelled}/facts/F1.json")) == expected, spelled
        assert guard.decide({**write("facts/F1.json"), "cwd": spelled}) == expected, spelled
        assert guard.decide(write(f"{spelled}/notes/a.md")) is None, spelled
    assert os.path.samefile(short, run)


@pytest.mark.skipif(not os.path.isdir("/.resolve/1/"), reason="only macOS reads /.resolve/<n>/ and /.nofollow/ in a path itself")
def test_the_path_forms_macos_reads_itself_do_not_hide_a_record(tmp_path):
    run = make_run(tmp_path)
    (run / "notes").mkdir()
    record = run / "facts" / "F1.json"
    record.write_text("old", encoding="utf-8")
    (run / "notes" / "innocent.md").symlink_to(record)
    (run / "notes" / "tofacts").symlink_to("../facts", target_is_directory=True)
    real = os.path.realpath(run)
    with open(f"/.resolve/0{real}/notes/innocent.md", "w", encoding="utf-8") as handle:     # /.resolve/0/ follows links
        handle.write("new")
    assert record.read_text(encoding="utf-8") == "new"
    with pytest.raises(OSError) as refused:                                 # /.nofollow/ follows none
        open(f"/.nofollow{real}/notes/innocent.md", "w", encoding="utf-8").close()
    assert refused.value.errno == errno.ELOOP
    for flags in ("0", "1", "2", "32", "x"):
        for path, expected in ((f"/.resolve/{flags}{real}/notes/innocent.md", UNCHECKED),
                               (f"/.resolve/{flags}{real}/notes/tofacts/F1.json", UNCHECKED),
                               (f"/.resolve/{flags}{real}/notes/a.md", UNCHECKED),            # the price: harmless, refused
                               (f"/.resolve/{flags}{real}/facts/F1.json", UNCHECKED if flags == "x" else RECORDS)):
            assert guard.decide(write(path)) == expected, path
    for path, expected in ((f"/.nofollow{real}/facts/F1.json", RECORDS), (f"/.nofollow{real}/notes/tofacts/F1.json", RECORDS),
                           (f"/.nofollow{real}/notes/innocent.md", RECORDS), (f"/.nofollow{real}/notes/a.md", None)):
        assert guard.decide(write(path)) == expected, path


# ---------------------------------------------------------------- rule 2: what a helper may run

RUN = '"/home/a b/Documents (1)/radar/runs/r1"'
GOOD_VERDICT = ("radar record-support --run \"/p/radar/runs/r1\" --fact F3 --passed false --by support-checker "
                "--note-stdin <<'RADAR_NOTE'\nIt says \"not\" $(rm -rf ~), and {\"by\": `id`} is only text here.\n"
                "RADAR_NOTE")
OPEN = "<<'RADAR_NOTE'"
VERDICT_LINE = "radar record-support --run x --fact F1 --passed true --by support-checker --note-stdin " + OPEN
BODY = "The quote states the size."
OLD_VERDICT = ("radar record-support --run x --fact F1 --passed true --from-json - <<'RADAR_JSON'\n"
               '{"by": "support checker", "note": "It states the size."}\nRADAR_JSON')       # the form before PM1


def verdict(first_line=VERDICT_LINE, *lines, end="RADAR_NOTE"):
    return "\n".join([first_line, *(lines or (BODY,)), end])


ACCEPTED = [
    'radar quote-context --run "/p/radar/runs/r1" --fact F3',
    "radar quote-context --run " + RUN + " --fact F3",
    "radar quote-context --run S1,S2 --fact F3",                                    # a run named S1,S2 is only a folder name
    "radar quote-context --fact F12 --run " + RUN,                                  # the two options in any order
    "radar quote-context --run /p/radar/runs/r1 --fact F3",                         # a plain folder needs no quotes
    "radar quote-context --run runs/r-1_a.b:c=d --fact F3",
    "radar quote-context --run \"=x and = more\" --fact F3",                         # inside the quotes = is a letter like any
    "radar quote-context --run \"/p/it's (a) run; really & truly/r1\" --fact F3",    # all of it inside the quotes
    "radar quote-context --run \"/p/" + chr(0xFC) + "ber " + chr(0x201C) + "x" + chr(0x201D) + "/r1\" --fact F3",
    OWN_RADAR + " quote-context --run x --fact F1",                                 # this plugin's program by its full path
    '"' + OWN_RADAR + '" quote-context --run x --fact F1',
    "radar   quote-context  --run   x   --fact  F1",                                # more spaces between the words
    "  radar quote-context --run x --fact F1  ",                                    # spaces before and after
    "radar quote-context --run x --fact F1\n",                                      # one line break at the very end
    GOOD_VERDICT,
    GOOD_VERDICT + "\n",
    verdict(),
    verdict("radar record-support --note-stdin --by support-checker --passed false --fact F10 --run " + RUN + "   "
            + OPEN + "  "),                                                          # the five options in any order
    verdict("radar record-support --by support-checker --run x --note-stdin --fact F1 --passed false " + OPEN),
    verdict('"' + OWN_RADAR + '" record-support --run ' + RUN + " --fact F3 --passed true --by support-checker "
            "--note-stdin " + OPEN),
    verdict(VERDICT_LINE, "rm -rf ~; `id` $(id) | sh && x > /etc/passwd", '{"by": "someone", "note": "$HOME"}'),
    verdict(VERDICT_LINE, " RADAR_NOTE", "RADAR_NOTE ", "RADAR_NOTEX", "xRADAR_NOTE", "radar_note"),  # none ends the text
    verdict(VERDICT_LINE, "RADAR_JSON", "--from-json -"),                            # only text inside the quoted mark
    verdict(VERDICT_LINE, "", "", BODY, ""),
    VERDICT_LINE + "\nRADAR_NOTE",                                                   # an empty text: an empty note
    verdict(VERDICT_LINE, "a" + chr(0x2028) + "RADAR_NOTE"),                         # no line break to the shell
    verdict(VERDICT_LINE, BODY + "\r"),
]

Q = chr(34)
HOSTILE = [
    # the brief's own
    "ls", "radar settle --run x", "radar quote-context --run x --fact F1; rm -rf ~",
    "radar quote-context --run x --fact F1 | sh", "radar record-support --run x --fact F1 --passed true $(id)",
    "radar quote-context --run x --fact F1\nrm -rf ~",
    "radar record-support --run x --fact F1 --passed true --by support-checker --note-stdin <<'RADAR_NOTE'\nok\n"
    "RADAR_NOTE\nrm -rf ~",
    # not a command at all, or another program
    "", " ", "\n", "radar", "radar ", "radar quote-context", "quote-context --run x --fact F1",
    "echo hi", "Radar quote-context --run x --fact F1", "radarx quote-context --run x --fact F1",
    "bin/radar quote-context --run x --fact F1", "./bin/radar quote-context --run x --fact F1",
    "/opt/bin/radar2 quote-context --run x --fact F1", "/opt/bin/radar/x quote-context --run x --fact F1",
    "/opt/sbin/radar quote-context --run x --fact F1", "/opt/xbin/radar quote-context --run x --fact F1",
    "/tmp/evil/bin/radar quote-context --run x --fact F1", '"/tmp/evil/bin/radar" quote-context --run x --fact F1',
    "/a/../x/bin/radar quote-context --run x --fact F1", "/opt/plugins/strategy-radar/bin/radar quote-context --run x --fact F1",
    str(ROOT) + "/../" + ROOT.name + "/bin/radar quote-context --run x --fact F1",          # the right file, by a detour
    str(ROOT) + "/./bin/radar quote-context --run x --fact F1", str(ROOT) + "//bin/radar quote-context --run x --fact F1",
    str(ROOT) + "/bin/../bin/radar quote-context --run x --fact F1", str(ROOT) + "/bin/radar/ quote-context --run x --fact F1",
    str(ROOT) + "/engine/start_radar.py quote-context --run x --fact F1", str(ROOT) + "/hooks/guard.py quote-context --run x --fact F1",
    "/bin/radar quote-context --run x --fact F1", "//bin/radar quote-context --run x --fact F1",
    "~/bin/radar quote-context --run x --fact F1", "$HOME/bin/radar quote-context --run x --fact F1",
    '"$HOME/bin/radar" quote-context --run x --fact F1', "'/opt/bin/radar' quote-context --run x --fact F1",
    "X=1 radar quote-context --run x --fact F1", "PATH=/tmp radar quote-context --run x --fact F1",
    "command radar quote-context --run x --fact F1", "exec radar quote-context --run x --fact F1",
    "env radar quote-context --run x --fact F1", "sh -c radar quote-context --run x --fact F1",
    "sudo radar quote-context --run x --fact F1", "\\radar quote-context --run x --fact F1",
    "radar\tquote-context --run x --fact F1", "radar quote-context\t--run x --fact F1",
    "\tradar quote-context --run x --fact F1", "radar quote-context --run x --fact F1\t",
    '"radar quote-context" --run x --fact F1', 'radar "quote-context --run x" --fact F1',
    'ra"dar" quote-context --run x --fact F1', 'radar quote"-context" --run x --fact F1',
    # other subcommands and options
    "radar status --root x", "radar gate --run x", "radar withdraw-fact --run x --fact F1", "radar checkpoint --run x --name lenses",
    "radar quote-context --run x --open", "radar quote-context --run x --fact F1 --open",
    "radar quote-context --run x", "radar quote-context --fact F1", "radar quote-context --run x --fact",
    "radar quote-context --run x --run y --fact F1", "radar quote-context --run x --fact F1 --fact F2",
    "radar quote-context --run x --fact F1 F2", "radar quote-context x --fact F1", "radar quote-context --run x --fact F1 extra",
    "radar quote-context --run x --fact F1 --from-json /etc/passwd", "radar quote-context --run x --fact F1 --from-json -",
    "radar quote-context --run=x --fact=F1", "radar quote-context --run=x --fact F1", "radar quote-context --run x --fact=F1",
    "radar quote-context --ru x --fact F1", "radar quote-context --run x --fac F1", "radar quote-context -r x --fact F1",
    "radar quote-context --run --from-json=/etc/passwd --fact F1", "radar quote-context --run -x --fact F1",
    'radar quote-context --run "--from-json=/etc/passwd" --fact F1', 'radar quote-context --run "-" --fact F1',
    'radar quote-context "--run" x --fact F1', 'radar quote-context --run x "--fact" F1',
    "radar quote-context --help", "radar --version", "radar --help quote-context --run x --fact F1",
    "radar quote-context --run x --fact F1 -- extra", "radar quote-context -- --run x --fact F1",
    "radar record-support --run x --fact F1 --passed true", "radar record-support --run x --fact F1 --passed true --from-json -",
    "radar record-support --run x --fact F1 --passed true --note fine --by me",
    "radar record-support --run x --fact F1 --passed true --by support-checker --note fine",
    "radar record-support --run x --fact F1 --passed true --by support-checker --note-stdin",       # no here-document
    "radar quote-context --run x --fact F1 --note-stdin", "radar quote-context --run x --fact F1 --by support-checker",
    # a fact number is the letter F and digits
    "radar quote-context --run x --fact f1", "radar quote-context --run x --fact F", "radar quote-context --run x --fact 1",
    "radar quote-context --run x --fact F1a", "radar quote-context --run x --fact S1", "radar quote-context --run x --fact F1,F2",
    "radar quote-context --run x --fact F-1", "radar quote-context --run x --fact ../F1", 'radar quote-context --run x --fact "F1"',
    "radar quote-context --run x --fact F" + chr(0x663), "radar quote-context --run x --fact " + chr(0xFF26) + "1",
    # values that the shell would read
    'radar quote-context --run "$HOME" --fact F1', "radar quote-context --run $HOME --fact F1",
    'radar quote-context --run "`id`" --fact F1', 'radar quote-context --run "$(id)" --fact F1',
    'radar quote-context --run "a\\"b" --fact F1', 'radar quote-context --run "a\\\\" --fact F1',
    "radar quote-context --run a\\ b --fact F1", "radar quote-context --run x\\\n--fact F1",
    'radar quote-context --run "a\nb" --fact F1', 'radar quote-context --run "a\rb" --fact F1',
    'radar quote-context --run "a\tb" --fact F1', 'radar quote-context --run "" --fact F1',
    'radar quote-context --run "x --fact F1', 'radar quote-context --run x" --fact F1', 'radar quote-context --run "x"y --fact F1',
    'radar quote-context --run "x""y" --fact F1', 'radar quote-context --run x"y" --fact F1',
    "radar quote-context --run 'x' --fact F1", "radar quote-context --run '/p/a b' --fact F1", "radar quote-context --run $'x' --fact F1",
    "radar quote-context --run ~ --fact F1", "radar quote-context --run ~root/x --fact F1", "radar quote-context --run * --fact F1",
    "radar quote-context --run x? --fact F1", "radar quote-context --run [x] --fact F1", "radar quote-context --run {a,b} --fact F1",
    "radar quote-context --run x! --fact F1", "radar quote-context --run x#y --fact F1", "radar quote-context --run x --fact F1 #",
    "radar quote-context --run x --fact F1 # fine", "radar quote-context --run x%y --fact F1", "radar quote-context --run x,y --fact F1",
    "radar quote-context --run =x --fact F1", "radar quote-context --run =ls --fact F1", "radar quote-context --run = --fact F1",
    "=radar quote-context --run x --fact F1", "radar =quote-context --run x --fact F1",
    "radar quote-context --run x@y --fact F1", "radar quote-context --run x+y --fact F1", "radar quote-context --run (x) --fact F1",
    # more than one command
    "radar quote-context --run x --fact F1 && ls", "radar quote-context --run x --fact F1 || ls", "radar quote-context --run x --fact F1 & ls",
    "radar quote-context --run x --fact F1 &", "radar quote-context --run x --fact F1;", "radar quote-context --run x --fact F1 ;",
    "radar quote-context --run x --fact F1 > /tmp/out", "radar quote-context --run x --fact F1 >> ~/.bashrc",
    "radar quote-context --run x --fact F1 2>&1", "radar quote-context --run x --fact F1 < /etc/passwd",
    "radar quote-context --run x --fact F1 <<< hi", "radar quote-context --run x --fact F1 | cat", "radar quote-context --run x --fact F1 `id`",
    "(radar quote-context --run x --fact F1)", "{ radar quote-context --run x --fact F1; }", "! radar quote-context --run x --fact F1",
    "time radar quote-context --run x --fact F1", "radar quote-context --run x --fact F1\n\n", "radar quote-context --run x --fact F1\n ",
    "radar quote-context --run x --fact F1\nradar quote-context --run x --fact F2", "\nradar quote-context --run x --fact F1",
    "ls\nradar quote-context --run x --fact F1", "radar quote-context --run x --fact F1\r\n", "radar quote-context --run x --fact F1\r",
    "radar quote-context --run x\r --fact F1", "radar quote-context --run x --fact F1" + chr(0), "radar quote-context --run x" + chr(0) + " --fact F1",
    chr(0) + "radar quote-context --run x --fact F1", "radar quote-context --run x --fact F1" + chr(0x0B), "radar quote-context --run x --fact F1" + chr(0x0C),
    "radar quote-context --run x --fact F1" + chr(0x2028) + "ls", "radar quote-context --run x --fact F1" + chr(0x85) + "ls",
    "radar quote-context --run x" + chr(0xA0) + "--fact F1", "radar quote-context --run x" + chr(0x3000) + "--fact F1",
    'radar quote-context --run "x' + chr(0x2028) + 'y" --fact F1', 'radar quote-context --run "x' + chr(0x85) + 'y" --fact F1',
    'radar quote-context --run "x' + chr(0x7F) + 'y" --fact F1', 'radar quote-context --run "x' + chr(0x1B) + '[2Jy" --fact F1',
    'radar quote-context --run "x' + chr(0xD800) + 'y" --fact F1',
    'radar quote-context --run "x' + chr(0xA0) + 'y" --fact F1', 'radar quote-context --run "x' + chr(0x3000) + 'y" --fact F1',
    'radar quote-context --run "x' + chr(0x2009) + 'y" --fact F1', 'radar quote-context --run "x' + chr(0x200B) + 'y" --fact F1',
    'radar quote-context --run "x' + chr(0x202E) + 'y" --fact F1', 'radar quote-context --run "x' + chr(0xAD) + 'y" --fact F1',
    'radar quote-context --run "x' + chr(0xFEFF) + 'y" --fact F1', 'radar quote-context --run "x' + chr(0x2060) + 'y" --fact F1',
    'radar quote-context --run "x' + chr(0x9F) + 'y" --fact F1', 'radar quote-context --run "x' + chr(0xE0001) + 'y" --fact F1',
    # look-alikes of the quotation mark do not quote
    "radar quote-context --run " + chr(0x201C) + "/p/a b" + chr(0x201D) + " --fact F1",
    "radar quote-context --run " + chr(0x201C) + "/p/r1" + chr(0x201D) + " --fact F1",
    "radar quote-context --run " + chr(0xFF02) + "/p/r1" + chr(0xFF02) + " --fact F1",
    "radar quote-context --run " + chr(0x2018) + "/p/r1" + chr(0x2019) + " --fact F1",
    "radar quote-context --run /p/" + chr(0xFC) + "ber/r1 --fact F1",                # letters beyond a to z need the quotes
    "radar quote-context " + chr(0x2014) + "run x --fact F1", "radar quote-context --run x " + chr(0x2013) + "-fact F1",
    "r" + chr(0x430) + "dar quote-context --run x --fact F1",
    # the verdict
    verdict(VERDICT_LINE.replace("--passed true", "--passed true;")), verdict(VERDICT_LINE.replace("--passed true", "--passed yes")),
    verdict(VERDICT_LINE.replace("--passed true", "--passed True")), verdict(VERDICT_LINE.replace("--passed true", "--passed 1")),
    verdict(VERDICT_LINE.replace("--passed true", '--passed "true"')), verdict(VERDICT_LINE.replace("--passed true", "--passed")),
    verdict(VERDICT_LINE.replace("--passed true", "--passed true --passed false")), verdict(VERDICT_LINE.replace(" --passed true", "")),
    verdict(VERDICT_LINE.replace(" --fact F1", "")), verdict(VERDICT_LINE.replace(" --run x", "")),
    # the form before PM1, and --from-json in any shape: through it a helper could set any option
    OLD_VERDICT, OLD_VERDICT.replace("RADAR_JSON", "RADAR_NOTE"),
    verdict(VERDICT_LINE.replace(" --by support-checker --note-stdin", " --from-json -")),
    verdict(VERDICT_LINE.replace("--note-stdin", "--from-json -")), verdict(VERDICT_LINE.replace("--note-stdin", "--note-stdin --from-json -")),
    verdict(VERDICT_LINE.replace("--note-stdin", "--note-stdin --from-json /etc/passwd")),
    verdict(VERDICT_LINE.replace("--note-stdin", "--note-stdin --from-json verdict.json")),
    verdict(VERDICT_LINE.replace("--note-stdin", '--note-stdin --from-json "-"')),
    verdict(VERDICT_LINE.replace("--note-stdin", "--note-stdin --from-json=-")),
    # --note-stdin is a switch, given once, written plain
    verdict(VERDICT_LINE.replace(" --note-stdin", "")), verdict(VERDICT_LINE.replace("--note-stdin", "--note-stdin --note-stdin")),
    verdict(VERDICT_LINE.replace("--note-stdin", "--note-stdin true")), verdict(VERDICT_LINE.replace("--note-stdin", "--note-stdin=1")),
    verdict(VERDICT_LINE.replace("--note-stdin", "--note-stdin -")), verdict(VERDICT_LINE.replace("--note-stdin", '"--note-stdin"')),
    verdict(VERDICT_LINE.replace("--note-stdin", "--note-std")), verdict(VERDICT_LINE.replace("--note-stdin", "--note")),
    verdict(VERDICT_LINE.replace("--note-stdin", "--note_stdin")), verdict(VERDICT_LINE.replace("--note-stdin", "--Note-stdin")),
    # the note never stands on the command line
    verdict(VERDICT_LINE.replace("--note-stdin", "--note fine")), verdict(VERDICT_LINE.replace("--note-stdin", '--note "fine"')),
    verdict(VERDICT_LINE.replace("--note-stdin", "--note-stdin --note fine")), verdict(VERDICT_LINE.replace("--note-stdin", "--note=fine")),
    verdict(VERDICT_LINE.replace("--note-stdin", '--note-stdin --note ""')),
    # --by carries the checker's one name, written plain
    verdict(VERDICT_LINE.replace(" --by support-checker", "")), verdict(VERDICT_LINE.replace("--by support-checker", "--by me")),
    verdict(VERDICT_LINE.replace("--by support-checker", '--by "support-checker"')),
    verdict(VERDICT_LINE.replace("--by support-checker", '--by "support checker"')),
    verdict(VERDICT_LINE.replace("--by support-checker", "--by support")),
    verdict(VERDICT_LINE.replace("--by support-checker", "--by support-checker2")),
    verdict(VERDICT_LINE.replace("--by support-checker", "--by Support-Checker")),
    verdict(VERDICT_LINE.replace("--by support-checker", "--by strategy-radar:support-checker")),
    verdict(VERDICT_LINE.replace("--by support-checker", "--by=support-checker")),
    verdict(VERDICT_LINE.replace("--by support-checker", "--by support-checker --by support-checker")),
    verdict(VERDICT_LINE.replace("--by support-checker", "--by support-checker support-checker")),
    verdict(VERDICT_LINE.replace("--by support-checker", "--by")), verdict(VERDICT_LINE.replace("--by support-checker", "--by -")),
    verdict(VERDICT_LINE.replace("--by support-checker", "--by support" + chr(0x2011) + "checker")),
    verdict(VERDICT_LINE.replace("--by support-checker", "--by $USER")), verdict(VERDICT_LINE.replace("--by support-checker", "--by '$(id)'")),
    verdict(VERDICT_LINE.replace("--fact F1", "--fact F1 --open")), verdict(VERDICT_LINE.replace("--fact F1", "--fact F1 --note fine")),
    verdict(VERDICT_LINE.replace("record-support", "settle")), verdict(VERDICT_LINE.replace("record-support", "quote-context")),
    verdict(VERDICT_LINE.replace("record-support", "withdraw-fact")),
    verdict("radar quote-context --run x --fact F1 " + OPEN),
    # one here-document, its end mark in single quotes, last on the first line
    verdict(VERDICT_LINE.replace(OPEN, "<<'RADAR_JSON'"), end="RADAR_JSON"), verdict(VERDICT_LINE.replace(OPEN, "<<'RADAR_JSON'")),
    verdict(VERDICT_LINE.replace(OPEN, "<<RADAR_NOTE")), verdict(VERDICT_LINE.replace(OPEN, "<<" + Q + "RADAR_NOTE" + Q)),
    verdict(VERDICT_LINE.replace(OPEN, "<<-'RADAR_NOTE'")), verdict(VERDICT_LINE.replace(OPEN, "<< 'RADAR_NOTE'")),
    verdict(VERDICT_LINE.replace(OPEN, "<<'EOF'"), end="EOF"), verdict(VERDICT_LINE.replace(OPEN, "<<<'RADAR_NOTE'")),
    verdict(VERDICT_LINE.replace(OPEN, "<<'RADAR_NOTE';ls")), verdict(VERDICT_LINE.replace(OPEN, "<<'RADAR_NOTE' ; ls")),
    verdict(VERDICT_LINE.replace(OPEN, "<<'RADAR_NOTE' | sh")), verdict(VERDICT_LINE.replace(OPEN, "<<'RADAR_NOTE' > /tmp/x")),
    verdict(VERDICT_LINE.replace(OPEN, "<<'RADAR_NOTE' && ls")), verdict(VERDICT_LINE.replace(OPEN, "<<'RADAR_NOTE' <<'RADAR_NOTE'")),
    verdict(VERDICT_LINE.replace(OPEN, "<<'RADAR_NOTE' --open")), verdict(VERDICT_LINE.replace(OPEN, "<<'RADAR_NOTE'\\")),
    verdict(VERDICT_LINE.replace(OPEN, "<<'RADAR_NOTE'\t")), verdict(VERDICT_LINE.replace(OPEN, "<<'RADAR_NOTE'\r")),
    verdict(VERDICT_LINE.replace(OPEN, "<<'RADAR_NOTE' 2>&1")), verdict(VERDICT_LINE.replace(OPEN, "<<'RADAR_NOTE' < /etc/passwd")),
    verdict(VERDICT_LINE.replace(" " + OPEN, OPEN)), verdict(VERDICT_LINE.replace("radar record-support", OPEN + " radar record-support")),
    verdict(VERDICT_LINE.replace("--fact F1", OPEN + " --fact F1")), verdict(VERDICT_LINE.replace("--by", OPEN + " --by")),
    verdict(VERDICT_LINE.replace(OPEN, "<<" + chr(0x2018) + "RADAR_NOTE" + chr(0x2019))),
    VERDICT_LINE, VERDICT_LINE + "\n", VERDICT_LINE + "\n" + BODY, VERDICT_LINE + "\n" + BODY + "\n",
    verdict(end="RADAR_NOTE ") , verdict(end=" RADAR_NOTE"), verdict(end="RADAR_NOTE\r"), verdict(end="RADAR_NOTE\n\n"),
    verdict(end="RADAR_NOTE\nls"), verdict(end="RADAR_NOTE\n\nls\n"), verdict(end="RADAR_NOTE;ls"), verdict(end="RADAR_NOTE\n "),
    verdict(end="radar_note"), verdict(end="EOF"), verdict(end="RADAR_JSON"), verdict(end="RADAR_NOTE" + chr(0)),
    verdict(VERDICT_LINE, "a" + chr(0) + "b"),
    verdict(VERDICT_LINE, "RADAR_NOTE", "rm -rf ~"),                                # a line of the text equal to the end mark
    verdict(VERDICT_LINE, BODY, "RADAR_NOTE", "rm -rf ~"), verdict(VERDICT_LINE, "RADAR_NOTE"),
    verdict(VERDICT_LINE, "RADAR_NOTE", "radar settle --run x", "cat <<'RADAR_NOTE'"),
    verdict() + "\nradar settle --run x", verdict() + "\n" + verdict(),
    "radar quote-context --run x --fact F1\n" + verdict(), verdict() + "\r\n", verdict().replace("\n", "\r\n"),
]


@pytest.fixture(scope="module")
def checker_blocks():
    text = body(ROOT / "agents" / "support-checker.md")
    return [block.strip("\n") for block in re.findall(r"```bash\n(.*?)```", text, flags=re.S)]


def test_the_checker_may_run_its_two_commands():
    assert guard.decide(event("Bash", "strategy-radar:support-checker",
                              command='radar quote-context --run "/p/radar/runs/r1" --fact F3')) is None
    assert guard.decide(event("Bash", "support-checker", command=GOOD_VERDICT)) is None


def test_the_commands_exactly_as_the_checker_s_file_writes_them_are_allowed(checker_blocks):
    assert len(checker_blocks) == 2 and all("<run folder>" in block for block in checker_blocks)
    assert "=" not in "".join(block.splitlines()[0] for block in checker_blocks)   # the file never writes --key=value
    for folder in ("/p/radar/runs/r1", "/home/a b/Documents (1)/radar/runs/r1", "/Users/x/it's & more; 100%/runs/r1"):
        for block in checker_blocks:
            command = block.replace("<run folder>", folder)
            assert guard.decide(event("Bash", CHECKER, command=command)) is None, command


@pytest.mark.parametrize("command", ACCEPTED)
def test_what_the_checker_is_allowed(command):
    assert guard.decide(event("Bash", CHECKER, command=command)) is None
    assert guard.decide(event("Bash", "support-checker", command=command, description="Fetch the packet")) is None


@pytest.mark.parametrize("command", [
    "ls", "radar settle --run x", "radar quote-context --run x --fact F1; rm -rf ~",
    "radar quote-context --run x --fact F1 | sh", "radar record-support --run x --fact F1 --passed true $(id)",
    "radar quote-context --run x --fact F1\nrm -rf ~",
    "radar record-support --run x --fact F1 --passed true --by support-checker --note-stdin <<'RADAR_NOTE'\nok\n"
    "RADAR_NOTE\nrm -rf ~"])
def test_the_checker_may_run_nothing_else(command):
    assert guard.decide(event("Bash", "strategy-radar:support-checker", command=command)) is not None


def test_the_checker_may_no_longer_hand_over_its_options_through_from_json():
    # PM1: through --from-json a helper could set any option of record-support; the note now comes as plain text.
    assert "--from-json" not in guard.OPTIONS["record-support"] and "--note" not in guard.OPTIONS["record-support"]
    for command in (OLD_VERDICT, OLD_VERDICT.replace("--from-json -", "--by support-checker --from-json -"),
                    VERDICT_LINE.replace("--note-stdin", "--from-json -") + "\n" + BODY + "\nRADAR_NOTE"):
        assert guard.decide(event("Bash", CHECKER, command=command)) == HELPER, command


def test_the_one_name_the_checker_records_under_is_the_one_its_file_gives(checker_blocks):
    assert guard.CHECKER_BY == "support-checker" == guard.CHECKER
    assert "--by " + guard.CHECKER_BY + " --note-stdin " + OPEN in checker_blocks[1].splitlines()[0]
    assert checker_blocks[1].splitlines()[-1] == "RADAR_NOTE"


@pytest.mark.parametrize("command", HOSTILE)
def test_anything_outside_the_two_shapes_is_refused(command):
    assert guard.decide(event("Bash", CHECKER, command=command)) == HELPER
    assert guard.decide(event("Bash", "support-checker", command=command)) == HELPER


def test_the_hostile_list_is_not_refused_for_a_silly_reason():
    # Each of these differs from an allowed command in one small way only.
    assert guard.decide(event("Bash", CHECKER, command="radar quote-context --run x --fact F1")) is None
    assert guard.decide(event("Bash", CHECKER, command=verdict())) is None
    assert len(set(HOSTILE)) == len(HOSTILE) and not set(HOSTILE) & set(ACCEPTED)


@pytest.mark.parametrize("command", [None, 7, ["radar", "quote-context"], {"a": 1}, True])
def test_a_helper_s_command_that_is_no_text_is_refused(command):
    assert guard.decide(event("Bash", CHECKER, command=command)) == HELPER
    assert guard.decide({"tool_name": "Bash", "agent_type": CHECKER, "tool_input": {}}) == HELPER
    assert guard.decide({"tool_name": "Bash", "agent_type": CHECKER}) == HELPER
    assert guard.decide({"tool_name": "Bash", "agent_type": CHECKER, "tool_input": "radar quote-context"}) == HELPER


@pytest.mark.parametrize("helper", ["source-scout", "fact-extractor", "bias-auditor"])
def test_the_other_helpers_may_run_no_command(helper):
    assert guard.decide(event("Bash", f"strategy-radar:{helper}", command="radar status --root x")) is not None
    for name in (helper, f"strategy-radar:{helper}"):
        for command in ("ls", GOOD_VERDICT, "radar quote-context --run x --fact F1", None, 7):
            assert guard.decide(event("Bash", name, command=command)) == NO_COMMANDS
        assert guard.decide({"tool_name": "Bash", "agent_type": name}) == NO_COMMANDS


def test_the_lead_s_commands_are_not_limited():
    assert guard.decide(event("Bash", command="radar settle --run x && ls")) is None
    for agent in (None, ""):
        assert guard.decide({"tool_name": "Bash", "agent_type": agent, "tool_input": {"command": "rm -rf x; ls | sh"}}) is None


def test_the_recorded_real_event_of_the_lead_is_not_limited():
    real = recorded("lead_bash")
    assert "agent_type" not in real and "agent_id" not in real and real["tool_name"] == "Bash"
    assert guard.decide(real) is None
    assert guard.decide({**real, "tool_input": {"command": "radar settle --run x && ls | sh"}}) is None


def test_the_recorded_real_event_is_recognised_as_a_helper():
    recorded_event = recorded("helper_bash")
    assert recorded_event["agent_type"] == "strategy-radar:support-checker"       # the form a real session gives
    assert guard.decide(recorded_event) is not None     # the recorded helper ran its command and then `echo hi`
    assert guard.decide({**recorded_event, "tool_input": {"command": "echo hi"}}) == HELPER
    allowed = {**recorded_event, "tool_input": {"command": 'radar quote-context --run "/p/r1" --fact F3'}}
    assert guard.decide(allowed) is None                  # the same helper with one of its two commands


@pytest.mark.parametrize("agent", [
    "my-support-checker", "xsupport-checker", "other-plugin:support-checker", "strategy-radar:my-support-checker",
    "strategy-radar:support-checker-2", "strategy-radar:tools:support-checker", "strategy-radar-2:support-checker",
    "my-strategy-radar:support-checker", "general-purpose", "Explore", "strategy-radar:", ":support-checker",
    "Support-Checker", "strategy-radar:Support-Checker", "support-checker ", " support-checker", "strategy-radar:run",
    "my-bias-auditor", "other:source-scout", "fact-extractor2"])
def test_another_agent_whose_name_only_looks_alike_is_not_taken_for_a_helper(agent):
    assert guard.decide(event("Bash", agent, command="ls")) is None


@pytest.mark.parametrize("agent", [
    "support-checker", "strategy-radar:support-checker", "source-scout", "strategy-radar:source-scout",
    "fact-extractor", "strategy-radar:fact-extractor", "bias-auditor", "strategy-radar:bias-auditor"])
def test_each_helper_is_known_by_its_plain_name_and_by_its_name_in_the_plugin(agent):
    assert guard.decide(event("Bash", agent, command="ls")) == (HELPER if agent.endswith("support-checker") else NO_COMMANDS)
    result = run_guard(json.dumps(event("Bash", agent, command="ls")))
    assert result.returncode == 2
    assert result.stderr.decode("utf-8") == (HELPER if agent.endswith("support-checker") else NO_COMMANDS) + "\n"


def linked_plugin(tmp_path, name="a b"):
    """A folder under tmp_path that is a link to the plugin's own folder, as an install may be reached."""
    link = tmp_path / name
    link.symlink_to(ROOT, target_is_directory=True)
    return link


def by_path(program):
    return guard.decide(event("Bash", CHECKER, command=program + " quote-context --run x --fact F1"))


def test_the_program_by_its_path_must_be_this_plugin_s_own(tmp_path):
    assert guard.OWN_RADAR == os.path.realpath(OWN_RADAR).encode("utf-8")
    assert by_path(OWN_RADAR) is None and by_path('"' + OWN_RADAR + '"') is None
    evil = tmp_path / "evil" / "bin"
    evil.mkdir(parents=True)
    shutil.copy(OWN_RADAR, evil / "radar")                                  # the same bytes somewhere else
    assert by_path(str(evil / "radar")) == HELPER
    assert by_path(str(tmp_path / "nothing" / "bin" / "radar")) == HELPER
    # The plugin's folder reached through a link: the program finds its engine next to itself, so it is the same program.
    link = linked_plugin(tmp_path)
    assert by_path('"' + str(link) + '/bin/radar"') is None
    assert by_path(str(linked_plugin(tmp_path, "plain")) + "/bin/radar") is None


def test_a_link_to_the_program_is_not_the_program(tmp_path):
    # Started through a link, the launcher looks for its engine beside the link, so something else could run.
    for where in (tmp_path / "one" / "bin", tmp_path / "two" / "bin"):
        where.parent.mkdir()
    (tmp_path / "one" / "bin").mkdir()
    (tmp_path / "one" / "bin" / "radar").symlink_to(OWN_RADAR)             # a link to the file
    (tmp_path / "two" / "bin").symlink_to(ROOT / "bin", target_is_directory=True)   # a link to its folder
    assert by_path(str(tmp_path / "one" / "bin" / "radar")) == HELPER
    assert by_path(str(tmp_path / "two" / "bin" / "radar")) == HELPER


def test_the_helper_names_are_the_helpers_that_exist():
    assert sorted(guard.HELPERS) == sorted(path.stem for path in (ROOT / "agents").glob("*.md"))
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert guard.PLUGIN == manifest["name"]


def test_a_helper_s_other_tools_are_not_the_guard_s_business(tmp_path):
    assert guard.decide(event("Read", "strategy-radar:fact-extractor", file_path=str(tmp_path / "copies" / "S1.txt"))) is None
    assert guard.decide(event("WebSearch", "strategy-radar:source-scout", query="capacity")) is None


# ------------------------------------------------- what the shell really does with an allowed command

STUB = """#!/bin/sh
{ printf 'CALL\\n'; for word in "$@"; do printf 'WORD:%s\\n' "$word"; done; printf 'TEXT:'; cat; printf '\\nEND\\n'; } >> "$STUB_LOG"
"""


# Fix wave A23.11: every shell found on this computer, not bash only.
REAL_SHELLS = [found for found in (shutil.which(name) for name in ("sh", "bash", "zsh", "dash")) if found]


def run_in_a_real_shell(command, tmp_path, shell):
    """Run `command` with `shell` in an empty folder; `radar` (and any /bin/radar path) is a stub that writes down its
    call."""
    box = tmp_path / "box"
    box.mkdir(exist_ok=True)
    stub_dir = tmp_path / "stub" / "bin"
    stub_dir.mkdir(parents=True, exist_ok=True)
    stub = stub_dir / "radar"
    stub.write_text(STUB, encoding="utf-8")
    stub.chmod(0o755)
    log = tmp_path / "calls.log"
    if log.exists():
        log.unlink()
    command = command.replace('"' + OWN_RADAR + '"', '"' + str(stub) + '"', 1) if command.startswith('"') else command
    command = re.sub("^" + re.escape(OWN_RADAR) + "(?= )", '"' + str(stub) + '"', command)
    env = {"PATH": str(stub_dir) + os.pathsep + "/usr/bin" + os.pathsep + "/bin", "STUB_LOG": str(log), "HOME": str(box)}
    done = subprocess.run([shell, "-c", command], cwd=box, env=env, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=20)
    calls = log.read_bytes().decode("utf-8") if log.exists() else ""            # as written, line ends untouched
    return done, calls, sorted(p.name for p in box.iterdir())


@pytest.mark.parametrize("shell", REAL_SHELLS)
@pytest.mark.parametrize("command", [c for c in ACCEPTED if chr(0x2028) not in c])
def test_an_allowed_command_starts_the_program_once_and_nothing_else(command, tmp_path, shell):
    done, calls, left_behind = run_in_a_real_shell(command, tmp_path, shell)
    assert done.returncode == 0 and done.stdout == "" and done.stderr == ""
    assert calls.count("CALL\n") == 1 and left_behind == []
    words = re.findall(r"^WORD:(.*)$", calls, flags=re.M)
    assert words[0] in ("quote-context", "record-support")
    if words[0] == "quote-context":
        options = dict(zip(words[1::2], words[2::2]))
        assert set(options) == {"--run", "--fact"} and len(words) == 5
        assert calls.split("TEXT:")[1] == "\nEND\n"                       # nothing on standard input
    else:
        assert words.count("--note-stdin") == 1 and len(words) == 10
        valued = [word for word in words[1:] if word != "--note-stdin"]
        options = dict(zip(valued[0::2], valued[1::2]))
        assert set(options) == {"--run", "--fact", "--passed", "--by"}
        assert options["--by"] == "support-checker" and options["--passed"] in ("true", "false")
        text = calls.split("TEXT:", 1)[1][:-len("\nEND\n")]
        assert text == "".join(line + "\n" for line in command.rstrip("\n").split("\n")[1:-1])   # the text, untouched
    assert re.fullmatch(r"F[0-9]+", options["--fact"])
    assert not any(mark in options["--run"] for mark in "\"$`\\\n")


@pytest.mark.parametrize("shell", REAL_SHELLS)
def test_the_run_folder_with_spaces_and_brackets_arrives_whole(tmp_path, shell):
    done, calls, _ = run_in_a_real_shell("radar quote-context --run " + RUN + " --fact F3", tmp_path, shell)
    assert "WORD:/home/a b/Documents (1)/radar/runs/r1\n" in calls


FRAGMENTS = [";", "&", "&&", "|", "||", "`id`", "$(id)", "$HOME", ">", ">x", "<", "<x", "(", ")", "\n", "\nls", "\r", "\t", "\\",
             "'", Q, "#", "*", "~", "!", "{", "}", "--open", "-", "--", "=", "ls", "x", "F1", "true", OPEN, "RADAR_NOTE",
             chr(0), chr(0x2028), chr(0x201C), "--from-json /etc/passwd", "--from-json -", "--run y", "X=1", "--note-stdin",
             "--note x", "--by me", "support-checker", "<<'RADAR_JSON'"]


@pytest.mark.parametrize("shell", REAL_SHELLS)
def test_a_hostile_piece_put_anywhere_into_a_good_command_never_gets_more_than_the_program_started(tmp_path, shell):
    """Every piece is put between any two words, and glued to either side of each word, of both good commands.

    The command must be refused; where the guard lets one through, a real shell must start the program once,
    with one of the two subcommands, and do nothing else.
    """
    good = ["radar quote-context --run " + RUN + " --fact F3", GOOD_VERDICT]
    tried = let_through = 0
    for command in good:
        first, _, rest = command.partition("\n")
        places = [0] + [m.start() for m in re.finditer(" ", first)] + [len(first)]
        for place in places:
            for piece in FRAGMENTS:
                for glue in (piece, " " + piece, piece + " ", " " + piece + " "):
                    changed = first[:place] + glue + first[place:] + ("\n" + rest if rest else "")
                    tried += 1
                    if guard.decide(event("Bash", CHECKER, command=changed)) is not None:
                        continue
                    let_through += 1
                    done, calls, left_behind = run_in_a_real_shell(changed, tmp_path, shell)
                    assert calls.count("CALL\n") == 1 and left_behind == [] and done.stdout == "", changed
                    assert re.findall(r"^WORD:(.*)$", calls, flags=re.M)[0] in ("quote-context", "record-support"), changed
    assert tried > 3000 and 0 < let_through < tried / 10


# ---------------------------------------------------------------- the hook as a program

def run_guard(text, cwd=None, env=None, python=sys.executable):
    data = text if isinstance(text, bytes) else text.encode("utf-8")
    return subprocess.run([python, str(GUARD)], input=data, capture_output=True, cwd=cwd, env=env)


def test_the_guard_never_breaks_a_session(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "hooks" / "guard.py")], input="not json", capture_output=True, text=True)
    assert result.returncode == 0


@pytest.mark.parametrize("text", [
    "", "not json", "[]", "null", "7", '"text"', "{}", '{"tool_name": "Write"}', '{"tool_name": "Write", "tool_input": null}',
    '{"tool_name": "Write", "tool_input": "facts/F1.json"}', '{"tool_name": "Write", "tool_input": {"file_path": 7}}',
    '{"tool_name": "Write", "tool_input": {"file_path": ""}}', '{"tool_name": "Write", "tool_input": {"file_path": ["a"]}}',
    '{"tool_name": ["Write"], "tool_input": {}}',
    '{"tool_name": "Bash", "agent_type": ["strategy-radar:support-checker"], "tool_input": {"command": "ls"}}',
    '{"tool_name": "Bash", "agent_type": 7, "tool_input": {"command": "ls"}}',
    '{"tool_name": "Bash", "tool_input": {"command": "ls"}', b"\xff\xfe\x00", "[" * 100000,
    '{"tool_name": "Write", "cwd": 7, "tool_input": {"file_path": "x/y.txt"}}'])
def test_an_event_the_guard_cannot_read_is_let_through_in_silence(text, tmp_path):
    result = run_guard(text, cwd=tmp_path)
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")


def test_decide_itself_never_raises():
    for odd in (None, [], "text", 7, {"tool_name": "Write", "tool_input": {"file_path": chr(0xD800)}, "cwd": chr(0xDC00)},
                {"tool_name": "Write", "tool_input": {"file_path": {"a": 1}}}, {"tool_name": "Write", "cwd": [], "tool_input": {}},
                {"tool_name": {}}, {"tool_name": "Bash", "agent_type": {}}):
        assert guard.decide(odd) is None


def test_a_refusal_exits_with_code_2_and_says_why(tmp_path):
    run = make_run(tmp_path)
    result = run_guard(json.dumps(write(run / "facts" / "F1.json")))
    assert (result.returncode, result.stdout) == (2, b"")
    assert result.stderr.decode("utf-8") == RECORDS + "\n"
    result = run_guard(json.dumps(event("Bash", CHECKER, command="ls")))
    assert (result.returncode, result.stdout) == (2, b"")
    assert result.stderr.decode("utf-8") == HELPER + "\n"
    result = run_guard(json.dumps(write(str(tmp_path) + "/" + "x" * 5000)))
    assert (result.returncode, result.stdout) == (2, b"")
    assert result.stderr.decode("utf-8") == UNCHECKED + "\n"


def test_a_call_that_is_let_through_prints_nothing(tmp_path):
    run = make_run(tmp_path)
    for allowed in (write(run / "notes" / "frame.md"), event("Bash", command="ls && ls"),
                    event("Bash", CHECKER, command=GOOD_VERDICT), recorded("lead_write")):
        result = run_guard(json.dumps(allowed))
        assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")


def test_the_recorded_real_helper_event_is_refused_when_fed_to_the_program():
    result = run_guard((FIXTURES / "hook_event_helper_bash.json").read_bytes())
    assert result.returncode == 2 and result.stderr.decode("utf-8") == HELPER + "\n"


def test_a_folder_name_beyond_plain_letters_is_read_whatever_the_computer_s_language_setting(tmp_path):
    root = tmp_path / ("B" + chr(0xFC) + "ro " + chr(0x4E2D))
    run = make_run(root)
    env = {"PATH": os.environ.get("PATH", ""), "LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0", "PYTHONIOENCODING": "ascii"}
    result = run_guard(json.dumps(write(run / "facts" / "F1.json"), ensure_ascii=False), env=env)
    assert result.returncode == 2 and result.stderr.decode("ascii") == RECORDS + "\n"
    result = run_guard(json.dumps(write(run / "notes" / "a.md"), ensure_ascii=False), env=env)
    assert (result.returncode, result.stderr) == (0, b"")


def test_the_hook_file_starts_the_guard_for_the_writing_tools_and_for_commands():
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    assert list(hooks) == ["hooks"] and list(hooks["hooks"]) == ["PreToolUse"]
    (entry,) = hooks["hooks"]["PreToolUse"]
    assert set(entry["matcher"].split("|")) == set(guard.WRITING_TOOLS) | {"Bash"} == {"Write", "Edit", "NotebookEdit", "Bash"}
    assert entry["hooks"] == [{"type": "command", "command": "sh", "args": ["${CLAUDE_PLUGIN_ROOT}/hooks/guard.sh"]}]


# ---------------------------------------------------------------- the launcher that finds a Python for the guard

LAUNCHER = ROOT / "hooks" / "guard.sh"
FOR_LINE = re.compile(r"^for candidate in (.+); do$", flags=re.M)
REFUSED_EVENT = json.dumps(event("Bash", CHECKER, command="ls")).encode("utf-8")
ALLOWED_EVENT = json.dumps(event("Bash", CHECKER, command="radar quote-context --run x --fact F1")).encode("utf-8")


def launch(data, env, cwd=None):
    return subprocess.run(["/bin/sh", str(LAUNCHER)], input=data, capture_output=True, env=env, cwd=cwd)


def failing_python(folder, name="python3"):
    """A stand-in like the one on a Mac without the developer tools: it is there, it says something, it does not work."""
    folder.mkdir(parents=True, exist_ok=True)
    stub = folder / name
    stub.write_text("#!/bin/sh\necho 'no developer tools were found' >&2\nexit 1\n", encoding="utf-8")
    stub.chmod(0o755)
    return stub


def test_the_launcher_looks_for_a_python_where_the_program_does():
    radar = (ROOT / "bin" / "radar").read_text(encoding="utf-8")
    launcher = LAUNCHER.read_text(encoding="utf-8")
    assert len(FOR_LINE.findall(radar)) == 1
    assert FOR_LINE.findall(launcher)[0] == FOR_LINE.findall(radar)[0]            # the same places, in the same order
    test_line = re.compile(r"^new_enough\(\) \{ (.+) \}$", flags=re.M)
    # the same question, for 3.8; the launcher keeps the event on standard input away from the candidate
    # and asks with -I, so a setting of the computer cannot change the answer
    # (fix wave A23.6: bin/radar asks it in the same way now)
    assert test_line.findall(launcher)[0] == test_line.findall(radar)[0].replace("(3, 10)", "(3, 8)")
    assert launcher.startswith("#!/bin/sh\n") and os.access(LAUNCHER, os.X_OK)


def test_the_launcher_hands_back_the_guard_s_answer_unchanged(tmp_path):
    env = {"PATH": "/nowhere", "HOME": str(tmp_path), "RADAR_PYTHON": sys.executable}
    refused = launch(REFUSED_EVENT, env)
    assert (refused.returncode, refused.stdout, refused.stderr.decode("utf-8")) == (2, b"", HELPER + "\n")
    allowed = launch(ALLOWED_EVENT, env)
    assert (allowed.returncode, allowed.stdout, allowed.stderr) == (0, b"", b"")
    run = make_run(tmp_path)
    record = launch(json.dumps(write(run / "facts" / "F1.json")).encode("utf-8"), env, cwd=tmp_path)
    assert (record.returncode, record.stdout, record.stderr.decode("utf-8")) == (2, b"", RECORDS + "\n")
    unreadable = launch(b"not json", env)
    assert (unreadable.returncode, unreadable.stdout, unreadable.stderr) == (0, b"", b"")


def test_the_launcher_works_from_any_folder_and_by_a_path_with_a_space(tmp_path):
    link = linked_plugin(tmp_path)
    env = {"PATH": "/nowhere", "HOME": str(tmp_path), "RADAR_PYTHON": sys.executable}
    refused = subprocess.run(["/bin/sh", str(link / "hooks" / "guard.sh")], input=REFUSED_EVENT, capture_output=True,
                             env=env, cwd="/")
    assert (refused.returncode, refused.stderr.decode("utf-8")) == (2, HELPER + "\n")
    relative = subprocess.run(["/bin/sh", "guard.sh"], input=REFUSED_EVENT, capture_output=True, env=env, cwd=ROOT / "hooks")
    assert (relative.returncode, relative.stderr.decode("utf-8")) == (2, HELPER + "\n")


def test_the_launcher_uses_the_private_environment_when_there_is_one(tmp_path):
    home = tmp_path / "radar-home"
    (home / "venv" / "bin").mkdir(parents=True)
    (home / "venv" / "bin" / "python").symlink_to(os.path.realpath(sys.executable))
    refused = launch(REFUSED_EVENT, {"PATH": "/nowhere", "HOME": str(tmp_path / "none"), "RADAR_HOME": str(home)})
    assert (refused.returncode, refused.stderr.decode("utf-8")) == (2, HELPER + "\n")
    (tmp_path / "home" / ".strategy-radar" / "venv" / "bin").mkdir(parents=True)
    (tmp_path / "home" / ".strategy-radar" / "venv" / "bin" / "python").symlink_to(os.path.realpath(sys.executable))
    refused = launch(REFUSED_EVENT, {"PATH": "/nowhere", "HOME": str(tmp_path / "home")})
    assert (refused.returncode, refused.stderr.decode("utf-8")) == (2, HELPER + "\n")


def test_a_python3_that_does_not_work_does_not_switch_the_guard_off(tmp_path):
    folder = tmp_path / "path"
    failing_python(folder)
    name = "python3.%d" % sys.version_info[1]
    (folder / name).symlink_to(os.path.realpath(sys.executable))
    env = {"PATH": str(folder), "HOME": str(tmp_path)}
    refused = launch(REFUSED_EVENT, env)
    assert (refused.returncode, refused.stdout, refused.stderr.decode("utf-8")) == (2, b"", HELPER + "\n")
    allowed = launch(ALLOWED_EVENT, env)
    assert (allowed.returncode, allowed.stdout, allowed.stderr) == (0, b"", b"")
    newer = "python3.%d" % (sys.version_info[1] + 1 if sys.version_info[1] < 14 else 13)
    failing_python(folder, newer)                                          # another name that does not work either
    assert launch(REFUSED_EVENT, env).returncode == 2
    assert launch(REFUSED_EVENT, {**env, "RADAR_PYTHON": str(folder / "python3")}).returncode == 2


def test_without_any_python_the_launcher_lets_the_call_through_in_silence(tmp_path):
    # A helper's call is the one exception (fix wave A8): it is refused, see the tests at the end of this file.
    empty = tmp_path / "empty"
    empty.mkdir()
    for env in ({"PATH": str(empty), "HOME": str(tmp_path)}, {"PATH": "", "HOME": str(tmp_path)},
                {"PATH": str(failing_python(tmp_path / "bad").parent), "HOME": str(tmp_path), "RADAR_PYTHON": "/nowhere/python"}):
        result = launch(LEAD_EVENT, env)
        assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")
        result = launch(REFUSED_EVENT, env)
        assert (result.returncode, result.stdout, result.stderr.decode("utf-8")) == (2, b"", NOT_STARTED + "\n")


def test_the_computer_s_python_settings_cannot_switch_a_refusal_off(tmp_path):
    planted = tmp_path / "planted"
    planted.mkdir()
    (planted / "json.py").write_text("def loads(text):\n    raise ValueError('planted')\n", encoding="utf-8")
    (planted / "unicodedata.py").write_text("raise ImportError('planted')\n", encoding="utf-8")
    base = {"PATH": "/nowhere", "HOME": str(tmp_path), "RADAR_PYTHON": sys.executable}
    for more in ({"PYTHONINSPECT": "1"}, {"PYTHONPATH": str(planted)}, {"PYTHONSTARTUP": str(planted / "json.py")},
                 {"PYTHONHOME": str(planted)}, {"PYTHONOPTIMIZE": "2", "PYTHONDONTWRITEBYTECODE": "", "PYTHONVERBOSE": ""}):
        refused = launch(REFUSED_EVENT, {**base, **more})
        assert (refused.returncode, refused.stdout, refused.stderr.decode("utf-8")) == (2, b"", HELPER + "\n"), more
        allowed = launch(ALLOWED_EVENT, {**base, **more})
        assert (allowed.returncode, allowed.stdout, allowed.stderr) == (0, b"", b""), more
    refused = launch(REFUSED_EVENT, base, cwd=planted)                  # a json.py in the folder the session is in
    assert (refused.returncode, refused.stderr.decode("utf-8")) == (2, HELPER + "\n")


def test_a_file_planted_next_to_the_guard_is_not_loaded(tmp_path):
    hooks = tmp_path / "plugin" / "hooks"
    hooks.mkdir(parents=True)
    for name in ("guard.sh", "guard.py"):
        shutil.copy(ROOT / "hooks" / name, hooks / name)
    (hooks / "json.py").write_text("def loads(text):\n    raise ValueError('planted')\n", encoding="utf-8")
    env = {"PATH": "/nowhere", "HOME": str(tmp_path), "RADAR_PYTHON": sys.executable}
    refused = subprocess.run(["/bin/sh", str(hooks / "guard.sh")], input=REFUSED_EVENT, capture_output=True, env=env)
    assert (refused.returncode, refused.stderr.decode("utf-8")) == (2, HELPER + "\n")


def test_a_launcher_without_its_guard_lets_the_call_through_in_silence(tmp_path):
    hooks = tmp_path / "plugin" / "hooks"
    hooks.mkdir(parents=True)
    shutil.copy(LAUNCHER, hooks / "guard.sh")
    env = {"PATH": "/nowhere", "HOME": str(tmp_path), "RADAR_PYTHON": sys.executable}
    for guard_file in (None, "folder"):
        if guard_file:
            (hooks / "guard.py").mkdir()                                   # there, but nothing a Python can run
        result = subprocess.run(["/bin/sh", str(hooks / "guard.sh")], input=LEAD_EVENT, capture_output=True, env=env)
        assert (result.returncode, result.stdout, result.stderr) == (0, b"", b""), guard_file
        result = subprocess.run(["/bin/sh", str(hooks / "guard.sh")], input=REFUSED_EVENT, capture_output=True, env=env)
        assert (result.returncode, result.stderr.decode("utf-8")) == (2, NOT_STARTED + "\n"), guard_file


def test_a_launcher_that_cannot_enter_its_own_folder_lets_the_call_through_in_silence(tmp_path):
    # The script's text is run under a name in a folder that is not there, so its `cd` fails.
    env = {"PATH": "/nowhere", "HOME": str(tmp_path), "RADAR_PYTHON": sys.executable}
    for data, code, said in ((LEAD_EVENT, 0, ""), (REFUSED_EVENT, 2, NOT_STARTED + "\n")):
        result = subprocess.run(["/bin/sh", "-c", LAUNCHER.read_text(encoding="utf-8"),
                                 str(tmp_path / "gone" / "guard.sh")], input=data, capture_output=True, env=env)
        assert (result.returncode, result.stdout, result.stderr.decode("utf-8")) == (code, b"", said)


def test_the_launcher_starts_python_cut_off_from_the_computer_s_settings():
    launcher = LAUNCHER.read_text(encoding="utf-8")
    starts = re.findall(r"^\s*exec (.+)$", launcher, flags=re.M)
    assert len(starts) == 2 and set(starts) == {'"$candidate" -I "$here/guard.py"'}


def test_a_python_too_old_for_the_guard_is_passed_over(tmp_path):
    folder = tmp_path / "path"
    folder.mkdir()
    old = folder / "python3"
    old.write_text("#!/bin/sh\n# says it is 3.7: every version question fails, everything else would run\n"
                   "case \"$2\" in *version_info*) exit 1 ;; esac\necho ran >&2\nexit 2\n", encoding="utf-8")
    old.chmod(0o755)
    result = launch(LEAD_EVENT, {"PATH": str(folder), "HOME": str(tmp_path)})
    assert (result.returncode, result.stderr) == (0, b"")
    result = launch(REFUSED_EVENT, {"PATH": str(folder), "HOME": str(tmp_path)})   # no guard: a helper is refused
    assert (result.returncode, result.stderr.decode("utf-8")) == (2, NOT_STARTED + "\n")


@pytest.mark.parametrize("shell", ["/bin/sh", "/bin/zsh", "/bin/bash", "/bin/dash"])
def test_the_launcher_starts_the_python_that_comes_with_the_computer_under_every_shell(tmp_path, shell):
    # The hook starts the launcher with sh; the person's own shell on a Mac is zsh. Neither may change the answer.
    if stock_python() is None:
        pytest.skip("this computer has no working /usr/bin/python3 (a Mac without the developer tools has only a stand-in)")
    if not os.access(shell, os.X_OK):
        pytest.skip(f"{shell} is not on this computer")
    run = make_run(tmp_path)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home")}
    chosen = subprocess.run([shell, "-c", "command -v python3"], env=env, capture_output=True, text=True)
    assert chosen.stdout.strip() == "/usr/bin/python3"                       # the one the launcher finds first
    for asked, code, reason in ((json.dumps(write(run / "facts" / "F1.json")).encode("utf-8"), 2, RECORDS + "\n"),
                                (json.dumps(write(run / "notes" / "a.md")).encode("utf-8"), 0, ""),
                                (json.dumps(event("Bash", CHECKER, command=GOOD_VERDICT)).encode("utf-8"), 0, ""),
                                (ALLOWED_EVENT, 0, ""), (REFUSED_EVENT, 2, HELPER + "\n"), (b"not json", 0, "")):
        result = subprocess.run([shell, str(LAUNCHER)], input=asked, capture_output=True, env=env)
        assert (result.returncode, result.stdout, result.stderr.decode("utf-8")) == (code, b"", reason), asked[:60]


# ---------------------------------------------------------------- an older Python must be able to run it

BUILTIN_CONTAINERS = {"list", "dict", "set", "tuple", "frozenset", "type"}
NEWER_NAMES = {"removeprefix", "removesuffix"}


def newer_syntax(source):
    """What in `source` an older Python (3.8, 3.9) would not accept or could not run."""
    found = []
    tree = ast.parse(source)
    annotations = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            arguments = node.args
            every = arguments.posonlyargs + arguments.args + arguments.kwonlyargs + [arguments.vararg, arguments.kwarg]
            annotations += [a.annotation for a in every if a is not None and a.annotation is not None]
            if node.returns is not None:
                annotations.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
        elif type(node).__name__ in ("Match", "TryStar", "TypeAlias"):
            found.append(f"line {node.lineno}: {type(node).__name__}")
        elif isinstance(node, ast.Attribute) and node.attr in NEWER_NAMES:
            found.append(f"line {node.lineno}: .{node.attr}()")
        elif isinstance(node, ast.With) and len(node.items) > 1 and getattr(node.items[0].context_expr, "lineno", 0) > node.lineno:
            found.append(f"line {node.lineno}: bracketed with")
    for annotation in annotations:
        for node in ast.walk(annotation):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
                found.append(f"line {node.lineno}: X | Y in an annotation")
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in BUILTIN_CONTAINERS:
                found.append(f"line {node.lineno}: {node.value.id}[...] in an annotation")
    return found


def test_the_check_for_newer_syntax_finds_what_it_must():
    assert newer_syntax("def decide(event: dict) -> str | None:\n    return None\n") == ["line 1: X | Y in an annotation"]
    assert newer_syntax("def f(a, *, b: int | None = None):\n    pass\n") == ["line 1: X | Y in an annotation"]
    assert newer_syntax("def f(*a: int | str, **k: 'x'):\n    pass\n") == ["line 1: X | Y in an annotation"]
    assert newer_syntax("x: int | None = None\n") == ["line 1: X | Y in an annotation"]
    assert newer_syntax("def f(a: list[str]) -> dict[str, int]:\n    pass\n") == [
        "line 1: list[...] in an annotation", "line 1: dict[...] in an annotation"]
    assert newer_syntax("match x:\n    case 1:\n        pass\n") == ["line 1: Match"]
    assert newer_syntax("y = 'abc'.removeprefix('a')\n") == ["line 1: .removeprefix()"]
    assert newer_syntax("from typing import Optional\ndef f(a: Optional[str] = None) -> Optional[str]:\n    return a or None\n"
                        "x = 1 | 2\n") == []


def test_the_guard_runs_on_python_3_8_syntax():
    source = (ROOT / "hooks" / "guard.py").read_text(encoding="utf-8")
    ast.parse(source, feature_version=(3, 8))
    assert newer_syntax(source) == []


def test_the_guard_uses_the_standard_library_only_and_only_a_little_of_it():
    tree = ast.parse(GUARD.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module)
    assert names <= {"errno", "json", "os", "re", "stat", "sys", "unicodedata"}


@pytest.mark.parametrize("python", other_pythons() or [sys.executable])
def test_the_guard_decides_the_same_under_every_python_on_this_computer(python, tmp_path):
    run = make_run(tmp_path)
    refused = run_guard(json.dumps(write(run / "facts" / "F1.json")), python=python)
    assert (refused.returncode, refused.stdout, refused.stderr.decode("utf-8")) == (2, b"", RECORDS + "\n")
    refused = run_guard(json.dumps(event("Bash", CHECKER, command="radar quote-context --run x --fact F1; ls")), python=python)
    assert (refused.returncode, refused.stderr.decode("utf-8")) == (2, HELPER + "\n")
    for allowed in (write(run / "notes" / "a.md"), event("Bash", CHECKER, command=GOOD_VERDICT)):
        passed = run_guard(json.dumps(allowed), python=python)
        assert (passed.returncode, passed.stdout, passed.stderr) == (0, b"", b"")


# --- fix wave A3: only the support checker records a verdict --------------------------------------------------------

VERDICT_ONLY = SENDER + ("Only the support checker records whether a quote supports its fact. "
                         "Ask the support checker to check this fact.")
NOT_THE_CHECKER = [None, "", "general-purpose", "Explore", "other-plugin:support-checker", "my-support-checker",
                   "strategy-radar:run", "strategy-radar:support-checker-2", "Support-Checker"]
VERDICT_COMMANDS = [
    GOOD_VERDICT,
    verdict(),
    "radar record-support --run x --fact F1 --passed true --by support-checker --note ok",
    "radar record-support --run x --fact F1 --passed true --from-json verdict.json",
    OWN_RADAR + " record-support --run x --fact F1 --passed true --by lead --note ok",
    "python3 /p/engine/start_radar.py record-support --run x --fact F1 --passed true --by lead --note ok",
    "sh -c 'radar record-support --run x --fact F1 --passed true --by lead --note ok'",
    "cd /p && radar settle --run x && radar record-support --run x --fact F1 --passed false --by me --note no",
    'RADAR_PYTHON=python3 "radar" "record-support" --run x',
]


def lead_event(agent, command):
    """A Bash event of a caller that is not the support checker; None and "" stand for the lead itself."""
    return {"tool_name": "Bash", "agent_type": agent, "tool_input": {"command": command}} if agent is not None \
        else {"tool_name": "Bash", "tool_input": {"command": command}}


def test_the_sentence_for_a_verdict_from_anyone_else_is_its_own():
    assert guard.VERDICT_REASON == VERDICT_ONLY
    assert len({guard.VERDICT_REASON, guard.HELPER_REASON, guard.NO_COMMANDS_REASON, guard.RECORDS_REASON}) == 4


@pytest.mark.parametrize("agent", NOT_THE_CHECKER)
@pytest.mark.parametrize("command", VERDICT_COMMANDS)
def test_a_verdict_command_from_anyone_but_the_support_checker_is_refused(agent, command):
    assert guard.decide(lead_event(agent, command)) == VERDICT_ONLY


def test_the_recorded_real_event_of_the_lead_is_refused_when_it_records_a_verdict():
    real = recorded("lead_bash")
    assert guard.decide({**real, "tool_input": {"command": verdict()}}) == VERDICT_ONLY
    result = run_guard(json.dumps({**real, "tool_input": {"command": verdict()}}))
    assert result.returncode == 2 and result.stderr.decode("utf-8") == VERDICT_ONLY + "\n"


def test_the_lead_s_other_commands_stay_unlimited_and_the_checker_keeps_its_verdict():
    for command in ("radar settle --run x && ls", "radar quote-context --run x --fact F1", "radar record --run x",
                    "radar support --run x", "rm -rf x; ls | sh"):
        assert guard.decide(lead_event(None, command)) is None, command
    assert guard.decide(event("Bash", CHECKER, command=verdict())) is None
    assert guard.decide(event("Bash", "support-checker", command=GOOD_VERDICT)) is None
    for helper in ("source-scout", "fact-extractor", "bias-auditor"):   # they run nothing at all, as before
        assert guard.decide(event("Bash", helper, command=verdict())) == NO_COMMANDS


@pytest.mark.parametrize("command", [None, 7, ["radar", "record-support"], {"command": "record-support"}])
def test_a_lead_s_command_that_is_no_text_is_let_through_as_before(command):
    assert guard.decide(lead_event(None, command)) is None


# --- fix wave A7: every sentence the guard prints begins with who refused -------------------------------------------

def test_every_sentence_of_the_guard_begins_with_its_name():
    reasons = {name: value for name, value in vars(guard).items() if name.endswith("_REASON")}
    assert len(reasons) >= 6
    for name, value in reasons.items():
        assert value.startswith("Strategy Radar's guard: ") and value.count("Strategy Radar's guard") == 1, name
    assert guard.SENDER == SENDER


def test_the_launcher_s_own_sentence_begins_with_the_guard_s_name_too():
    sentences = re.findall(r'^ *refusal="([^"]*)"$', LAUNCHER.read_text(encoding="utf-8"), flags=re.M)
    assert sentences and all(sentence.startswith(SENDER) for sentence in sentences), sentences


# --- fix wave A8: a helper is never unlimited, also when the guard fails or cannot start -----------------------------

FAILED = SENDER + "The guard could not check this call, so a helper may not make it."


def test_an_error_of_the_guard_s_own_while_judging_a_helper_s_command_refuses_it(monkeypatch):
    def broken(*args):
        raise RuntimeError("an error of the guard's own")
    monkeypatch.setattr(guard, "_is_a_checker_command", broken)
    for agent in ("support-checker", CHECKER):
        assert guard.decide(event("Bash", agent, command="radar quote-context --run x --fact F1")) == FAILED
    monkeypatch.setattr(guard, "_helper_name", lambda agent_type: broken() if agent_type else None)
    for agent in ("support-checker", CHECKER, "strategy-radar:source-scout", "fact-extractor"):
        assert guard.decide(event("Bash", agent, command="ls")) == FAILED, agent
    assert guard.FAILED_REASON == FAILED


def test_an_error_while_judging_anyone_else_s_call_still_lets_it_through(monkeypatch, tmp_path):
    def broken(*args):
        raise RuntimeError("an error of the guard's own")
    monkeypatch.setattr(guard, "_judge_write", broken)
    assert guard.decide(write(tmp_path / "a.md")) is None
    assert guard.decide(event("Bash", command="ls")) is None
    assert guard.decide(event("Write", "general-purpose", file_path=str(tmp_path / "a.md"))) is None


LEAD_EVENT = json.dumps(event("Bash", command="ls")).encode("utf-8")
HELPER_EVENTS = [json.dumps(event("Bash", agent, command="radar quote-context --run x --fact F1")).encode("utf-8")
                 for agent in ("support-checker", CHECKER, "source-scout", "strategy-radar:fact-extractor",
                               "strategy-radar:bias-auditor", "lens-advisor", "strategy-radar:lens-advisor",
                               "lens-link-reader", "strategy-radar:lens-link-reader", "lens-link-reader-quick",
                               "strategy-radar:lens-link-reader-quick", "project-grouper", "strategy-radar:project-grouper")]
NOT_STARTED = SENDER + ("The guard cannot start on this computer, so the helpers of Strategy Radar may not use "
                        "this tool now. Install Python from python.org, or install the plugin again.")


def test_the_sentence_for_a_guard_that_cannot_start_is_the_launcher_s_own():
    assert NOT_STARTED in LAUNCHER.read_text(encoding="utf-8")


def cannot_start(tmp_path, how):
    """Run the launcher in a way it cannot start the guard: no Python, no guard.py, or no folder to enter."""
    env = {"PATH": str(tmp_path / "empty"), "HOME": str(tmp_path)}
    (tmp_path / "empty").mkdir(exist_ok=True)
    if how == "no Python":
        return lambda data: launch(data, env)
    hooks = tmp_path / "plugin" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    shutil.copy(LAUNCHER, hooks / "guard.sh")
    env = {**env, "RADAR_PYTHON": sys.executable}
    if how == "no guard.py":
        return lambda data: subprocess.run(["/bin/sh", str(hooks / "guard.sh")], input=data, capture_output=True,
                                           env=env)
    return lambda data: subprocess.run(["/bin/sh", "-c", LAUNCHER.read_text(encoding="utf-8"),
                                        str(tmp_path / "gone" / "guard.sh")], input=data, capture_output=True, env=env)


@pytest.mark.parametrize("how", ["no Python", "no guard.py", "no folder to enter"])
def test_when_the_guard_cannot_start_a_helper_s_call_is_refused_and_every_other_call_let_through(tmp_path, how):
    started = cannot_start(tmp_path, how)
    for data in HELPER_EVENTS:
        result = started(data)
        assert (result.returncode, result.stdout, result.stderr.decode("utf-8")) == (2, b"", NOT_STARTED + "\n"), data
    for data in (LEAD_EVENT, json.dumps(write(tmp_path / "a.md")).encode("utf-8"), b"not json", b"",
                 json.dumps(event("Bash", "other-plugin:support-checker", command="ls")).encode("utf-8"),
                 json.dumps(event("Bash", "other-plugin:lens-advisor", command="ls")).encode("utf-8"),
                 json.dumps(event("Bash", "general-purpose", command="ls")).encode("utf-8")):
        result = started(data)
        assert (result.returncode, result.stdout, result.stderr) == (0, b"", b""), data


def test_a_recorded_real_helper_event_over_several_lines_is_refused_when_no_python_is_found(tmp_path):
    started = cannot_start(tmp_path, "no Python")
    real = (FIXTURES / "hook_event_helper_bash.json").read_bytes()
    assert b"\n" in real                                  # pretty-printed: the launcher reads every line
    result = started(real)
    assert (result.returncode, result.stderr.decode("utf-8")) == (2, NOT_STARTED + "\n")
    result = started((FIXTURES / "hook_event_lead_bash.json").read_bytes())
    assert (result.returncode, result.stderr) == (0, b"")


def test_the_real_shell_tests_run_under_more_than_one_shell_here():
    assert len(REAL_SHELLS) >= 2 and any(path.endswith("/sh") for path in REAL_SHELLS)


# --- the lens recommender: the advisor and the two blind link readers -----------------------------------------------
# Each runs its two commands, in the form its file shows, and nothing else; each records only under its own name, so
# one reader can never record under the other's; and nobody else records a link verdict or the recommendation.

ADVISOR = "strategy-radar:lens-advisor"
READER = "strategy-radar:lens-link-reader"
QUICK = "strategy-radar:lens-link-reader-quick"
LENS_HELPERS = ("lens-advisor", "lens-link-reader", "lens-link-reader-quick")
ADVISOR_ONLY = SENDER + "This helper may only run: radar lens-advisor-input and radar record-lens-recommendation."
READER_ONLY = SENDER + "This helper may only run: radar lens-link-context and radar record-link-check."
LINK_VERDICT_ONLY = SENDER + ("Only the two link readers record whether a fact bears on a lens. "
                              "Ask the link readers to read the suggested links.")
LIST_ONLY = SENDER + ("Only the lens advisor records the lens recommendation. "
                      "Ask the lens advisor to make the list.")
LENSES_AT = '"/home/a b/plugin (1)/lenses"'
LIST_OPEN = "<<'RADAR_LIST'"
ADVISOR_INPUT = 'radar lens-advisor-input --run "/p/radar/runs/r1" --lenses "/p/plugin/lenses"'
LIST_LINE = ('radar record-lens-recommendation --run "/p/radar/runs/r1" --lenses "/p/plugin/lenses" --by lens-advisor '
             "--list-stdin " + LIST_OPEN)
LIST_BODY = 'note: It says "no" $(rm -rf ~), `id` and $HOME, which is only text here.'
LINK_CONTEXT = 'radar lens-link-context --run "/p/radar/runs/r1" --lenses "/p/plugin/lenses"'


def recommendation(first_line=LIST_LINE, *lines, end="RADAR_LIST"):
    return "\n".join([first_line, *(lines or (LIST_BODY,)), end])


def check_line(by="lens-link-reader", verdict_word="doubt"):
    return ('radar record-link-check --run "/p/radar/runs/r1" --lens firm-boundaries --fact F3 --verdict ' + verdict_word
            + " --by " + by + " --note-stdin " + OPEN)


def link_check(by="lens-link-reader", *lines, first_line=None, end="RADAR_NOTE"):
    return "\n".join([first_line or check_line(by), *(lines or (BODY,)), end])


ADVISOR_ACCEPTED = [
    ADVISOR_INPUT,
    "radar lens-advisor-input --run " + RUN + " --lenses " + LENSES_AT,                 # quoted absolute folders
    "radar lens-advisor-input --lenses " + LENSES_AT + " --run " + RUN,                 # in any order
    "radar lens-advisor-input --run /p/radar/runs/r1 --lenses /p/plugin/lenses",        # plain folders need no quotes
    'radar lens-advisor-input --run "/p/it\'s (a) run; & 100%/r1" --lenses "/p/it\'s & more; 100%/lenses"',
    OWN_RADAR + " lens-advisor-input --run x --lenses y",
    '"' + OWN_RADAR + '" lens-advisor-input --run x --lenses y',
    ADVISOR_INPUT + "\n",
    ADVISOR_INPUT + " --part 2",                                                          # a later part of the input
    "radar lens-advisor-input --part 10 --lenses " + LENSES_AT + " --run " + RUN,
    recommendation(),
    recommendation() + "\n",
    recommendation("radar record-lens-recommendation --list-stdin --by lens-advisor --lenses " + LENSES_AT + " --run " + RUN
                   + "  " + LIST_OPEN + " "),                                            # the four options in any order
    recommendation('"' + OWN_RADAR + '" record-lens-recommendation --run x --lenses y --by lens-advisor --list-stdin '
                   + LIST_OPEN),
    recommendation(LIST_LINE, "lens: firm-boundaries", "part: adding capacity",
                   "why: rm -rf ~; `id` $(id) | sh && x > /etc/passwd", "facts: F1, F2", "missing: x", "",
                   "lens: capacity-commitment", "part: for whom", "why: y", "facts: none", "missing: z"),
    recommendation(LIST_LINE, '{"entries": [], "note": "only text inside the quoted mark"}'),
    recommendation(LIST_LINE, " RADAR_LIST", "RADAR_LIST ", "RADAR_LISTX", "xRADAR_LIST", "radar_list"),  # none ends it
    recommendation(LIST_LINE, "RADAR_NOTE", "RADAR_JSON", "--from-json -"),               # only text inside the quoted mark
    LIST_LINE + "\nRADAR_LIST",                                                           # an empty text: the program refuses it
    recommendation(LIST_LINE, "note: a" + chr(0x2028) + "RADAR_LIST"),
]


def reader_accepted(by):
    line = check_line(by)
    return [
        LINK_CONTEXT,
        "radar lens-link-context --run " + RUN + " --lenses " + LENSES_AT,
        "radar lens-link-context --lenses " + LENSES_AT + " --run " + RUN,
        "radar lens-link-context --run /p/radar/runs/r1 --lenses /p/plugin/lenses",
        OWN_RADAR + " lens-link-context --run x --lenses y",
        LINK_CONTEXT + "\n",
        LINK_CONTEXT + " --part 2",                                                       # a later part of the links
        "radar lens-link-context --part 10 --lenses " + LENSES_AT + " --run " + RUN,
        link_check(by),
        link_check(by) + "\n",
        link_check(by, first_line=check_line(by, "bears")),
        link_check(by, first_line="radar record-link-check --note-stdin --by " + by + " --verdict bears --fact F12 --lens "
                   "what-a-firm-is-good-at --run " + RUN + "  " + OPEN + " "),            # the six options in any order
        link_check(by, first_line='"' + OWN_RADAR + '" record-link-check --run x --lens a_b-2 --fact F1 --verdict doubt '
                   "--by " + by + " --note-stdin " + OPEN),
        link_check(by, "rm -rf ~; `id` $(id) | sh && x > /etc/passwd", '{"by": "someone", "note": "$HOME"}'),
        link_check(by, " RADAR_NOTE", "RADAR_NOTE ", "RADAR_NOTEX", "RADAR_LIST", "radar_note"),
        line + "\nRADAR_NOTE",
    ]


def hostile_for_both_kinds(good_read, good_record):
    """What none of the three may run, built from one good command of each of the helper's two kinds."""
    first, _, rest = good_record.partition("\n")
    return [
        "ls", "", " ", "\n", "radar", "radar settle --run x", "radar status --root x", "echo hi",
        "radar quote-context --run x --fact F1", GOOD_VERDICT, verdict(),
        # joined commands, pipes and redirects
        good_read + "; rm -rf ~", good_read + " && ls", good_read + " || ls", good_read + " & ls", good_read + " &",
        good_read + " | sh", good_read + " | cat", good_read + " > /tmp/out", good_read + " >> ~/.bashrc",
        good_read + " 2>&1", good_read + " < /etc/passwd", good_read + " <<< hi", good_read + " `id`",
        good_read + " $(id)", good_read + "\nrm -rf ~", "ls\n" + good_read, "(" + good_read + ")", good_read + "\n\n",
        good_read + "\r", "X=1 " + good_read, "sh -c " + good_read, "env " + good_read,
        good_record + "\nrm -rf ~", good_record + "\n" + good_read, good_read + "\n" + good_record,
        good_record.replace("\n", "\r\n"), good_record + "\r\n",
        first.replace(" <<", " | sh <<") + "\n" + rest, first.replace(" <<", " > /tmp/x <<") + "\n" + rest,
        first.replace(" <<", " && ls <<") + "\n" + rest, first.replace(" <<", " ; ls <<") + "\n" + rest,
        first + " | sh\n" + rest, first + " > /tmp/x\n" + rest, first + " ; ls\n" + rest, first + "\n" + rest + "\nls",
        first + "\n" + rest + " | sh", first + "\n" + rest + ";ls",
        # the program by another name
        good_read.replace("radar ", "bin/radar ", 1), good_read.replace("radar ", "/tmp/evil/bin/radar ", 1),
        good_read.replace("radar ", "Radar ", 1), good_read.replace("radar ", "radarx ", 1),
        # the read command: its two options, once each, no more
        good_read + " --from-json -", good_read + " --from-json /etc/passwd", good_read + " --open",
        good_read + " extra", good_read + " --run y", good_read + " --lenses y", good_read + " --note-stdin",
        good_read + " " + OPEN, good_read + " " + LIST_OPEN, good_read + " --by lens-advisor",
        good_read.replace(' --lenses "/p/plugin/lenses"', ""), good_read.replace(' --run "/p/radar/runs/r1"', ""),
        good_read.replace('--lenses "/p/plugin/lenses"', "--lenses -x"),
        good_read.replace('--lenses "/p/plugin/lenses"', '--lenses "-x"'),
        good_read.replace('--lenses "/p/plugin/lenses"', '--lenses "--from-json=/etc/passwd"'),
        good_read.replace('--lenses "/p/plugin/lenses"', '--lenses "$HOME"'),
        good_read.replace('--lenses "/p/plugin/lenses"', "--lenses $HOME"),
        good_read.replace('--lenses "/p/plugin/lenses"', '--lenses "`id`"'),
        good_read.replace('--lenses "/p/plugin/lenses"', "--lenses '/p/a b'"),
        good_read.replace('--lenses "/p/plugin/lenses"', '--lenses ""'),
        good_read.replace('--lenses "/p/plugin/lenses"', '--lenses "a\nb"'),
        good_read.replace('--lenses "/p/plugin/lenses"', "--lenses=/p/plugin/lenses"),
        good_read.replace('--lenses "/p/plugin/lenses"', "--lenses ~"),
        good_read.replace('--lenses "/p/plugin/lenses"', "--lenses /p/" + chr(0xFC) + "ber"),
        good_read.replace('--lenses "/p/plugin/lenses"', '"--lenses" /p/plugin/lenses'),
        good_read.replace('--run "/p/radar/runs/r1"', "--run -x"),
        # a part, where the read command takes one, is a positive whole number given once
        good_read + " --part x", good_read + " --part 0", good_read + " --part -2", good_read + " --part",
        good_read + ' --part "2"', good_read + " --part=2", good_read + " --part 2 --part 3", good_read + " --parts 2",
        good_read + " --part 2 --all",
        # the record command: its options, once each, its own here-document last
        first, first + "\n", first + "\n" + rest.split("\n")[0],
        first.replace(" " + first.split()[-1], "") + "\n" + rest,                       # no here-document opener
        first + " --from-json -\n" + rest, first.replace("--by", "--from-json - --by") + "\n" + rest,
        first.replace("--by", "--open --by") + "\n" + rest, first.replace("--by", "--run y --by") + "\n" + rest,
        first.replace("--by", "--lenses y --by") + "\n" + rest, first.replace("--by", "--note fine --by") + "\n" + rest,
        first.replace(first.split()[1], "settle", 1) + "\n" + rest,
    ]


ADVISOR_HOSTILE = hostile_for_both_kinds(ADVISOR_INPUT, recommendation()) + [
    # the advisor records only under its own name
    recommendation(LIST_LINE.replace("--by lens-advisor", "--by lens-link-reader")),
    recommendation(LIST_LINE.replace("--by lens-advisor", "--by lens-link-reader-quick")),
    recommendation(LIST_LINE.replace("--by lens-advisor", "--by support-checker")),
    recommendation(LIST_LINE.replace("--by lens-advisor", "--by lead")),
    recommendation(LIST_LINE.replace("--by lens-advisor", '--by "lens-advisor"')),
    recommendation(LIST_LINE.replace("--by lens-advisor", "--by strategy-radar:lens-advisor")),
    recommendation(LIST_LINE.replace("--by lens-advisor", "--by Lens-Advisor")),
    recommendation(LIST_LINE.replace("--by lens-advisor", "--by lens-advisor2")),
    recommendation(LIST_LINE.replace("--by lens-advisor", "--by=lens-advisor")),
    recommendation(LIST_LINE.replace("--by lens-advisor", "--by lens-advisor --by lens-advisor")),
    recommendation(LIST_LINE.replace(" --by lens-advisor", "")),
    # the list comes as plain lines on standard input, from the here-document, and from nowhere else: never as JSON
    # with --file, whose curly brackets would stop every recommendation for an approval
    recommendation(LIST_LINE.replace("--list-stdin", "--file -")),
    recommendation(LIST_LINE.replace("--list-stdin", "--file list.json")),
    recommendation(LIST_LINE.replace("--list-stdin", "--file /etc/passwd")),
    recommendation(LIST_LINE.replace("--list-stdin", "--list-stdin --file -")),
    recommendation(LIST_LINE.replace("--list-stdin", '"--list-stdin"')),
    recommendation(LIST_LINE.replace("--list-stdin", "--list-stdin=1")),
    recommendation(LIST_LINE.replace("--list-stdin", "--list-stdin -")),
    recommendation(LIST_LINE.replace("--list-stdin", "--list-stdin true")),
    recommendation(LIST_LINE.replace("--list-stdin", "--list-stdin --list-stdin")),
    recommendation(LIST_LINE.replace("--list-stdin", "--list-std")),
    recommendation(LIST_LINE.replace("--list-stdin", "--note-stdin")),
    recommendation(LIST_LINE.replace(" --list-stdin", "")),
    recommendation(LIST_LINE.replace("--list-stdin", "--list-stdin --from-json -")),
    recommendation(LIST_LINE.replace("--list-stdin", "--from-json -")),
    recommendation(LIST_LINE.replace("--list-stdin", "--part 2 --list-stdin")),          # only its input comes in parts
    # its own here-document, its end mark in single quotes, last on the first line
    recommendation(LIST_LINE.replace(LIST_OPEN, OPEN), end="RADAR_NOTE"),
    recommendation(LIST_LINE.replace(LIST_OPEN, OPEN)),
    recommendation(LIST_LINE.replace(LIST_OPEN, "<<'RADAR_JSON'"), end="RADAR_JSON"),
    recommendation(LIST_LINE.replace(LIST_OPEN, "<<RADAR_LIST")),
    recommendation(LIST_LINE.replace(LIST_OPEN, "<<" + Q + "RADAR_LIST" + Q)),
    recommendation(LIST_LINE.replace(LIST_OPEN, "<<-'RADAR_LIST'")),
    recommendation(LIST_LINE.replace(LIST_OPEN, "<< 'RADAR_LIST'")),
    recommendation(LIST_LINE.replace(LIST_OPEN, "<<'EOF'"), end="EOF"),
    recommendation(LIST_LINE.replace(LIST_OPEN, LIST_OPEN + " " + LIST_OPEN)),
    recommendation(LIST_LINE.replace(LIST_OPEN, LIST_OPEN + "\t")),
    recommendation(LIST_LINE.replace("--by", LIST_OPEN + " --by")),
    recommendation(end="RADAR_LIST "), recommendation(end=" RADAR_LIST"), recommendation(end="RADAR_LIST\r"),
    recommendation(end="RADAR_LIST\n\n"), recommendation(end="radar_list"),
    recommendation(end="RADAR_NOTE"), recommendation(end="RADAR_LIST" + chr(0)),
    # a line of the text equal to the end mark would end it early, and what follows would run
    recommendation(LIST_LINE, "RADAR_LIST", "rm -rf ~"), recommendation(LIST_LINE, LIST_BODY, "RADAR_LIST", "ls"),
    recommendation(LIST_LINE, "RADAR_LIST"), recommendation() + "\n" + recommendation(),
    # the readers' commands are not the advisor's
    LINK_CONTEXT, link_check(), link_check("lens-link-reader-quick"), link_check("lens-advisor"),
    link_check("lens-advisor", first_line=check_line("lens-advisor").replace(OPEN, LIST_OPEN), end="RADAR_LIST"),
    recommendation(ADVISOR_INPUT + " " + LIST_OPEN),
]


def reader_hostile(by, other):
    line = check_line(by)
    first = line
    return hostile_for_both_kinds(LINK_CONTEXT, link_check(by)) + [
        # only the links come in parts, never a verdict
        link_check(by, first_line=line.replace("--note-stdin", "--part 2 --note-stdin")),
        # a reader records only under its own name: the readers stay independent
        link_check(by, first_line=line.replace("--by " + by, "--by " + other)),
        link_check(by, first_line=line.replace("--by " + by, "--by lens-advisor")),
        link_check(by, first_line=line.replace("--by " + by, "--by support-checker")),
        link_check(by, first_line=line.replace("--by " + by, '--by "' + by + '"')),
        link_check(by, first_line=line.replace("--by " + by, "--by strategy-radar:" + by)),
        link_check(by, first_line=line.replace("--by " + by, "--by " + by.upper())),
        link_check(by, first_line=line.replace("--by " + by, "--by=" + by)),
        link_check(by, first_line=line.replace("--by " + by, "--by " + by + " --by " + by)),
        link_check(by, first_line=line.replace("--by " + by, "--by " + by + " " + other)),
        link_check(by, first_line=line.replace(" --by " + by, "")),
        link_check(by, first_line=line.replace("--by " + by, "--by")),
        # the note comes on standard input, never on the command line
        link_check(by, first_line=line.replace("--note-stdin", "--note fine")),
        link_check(by, first_line=line.replace("--note-stdin", '--note "fine"')),
        link_check(by, first_line=line.replace("--note-stdin", "--note-stdin --note fine")),
        link_check(by, first_line=line.replace("--note-stdin", "--note=fine")),
        link_check(by, first_line=line.replace(" --note-stdin", "")),
        link_check(by, first_line=line.replace("--note-stdin", "--note-stdin --note-stdin")),
        link_check(by, first_line=line.replace("--note-stdin", "--note-stdin -")),
        link_check(by, first_line=line.replace("--note-stdin", '"--note-stdin"')),
        link_check(by, first_line=line.replace("--note-stdin", "--note-stdin --from-json -")),
        line.replace(" --note-stdin " + OPEN, " --note fine"),
        line.replace(" " + OPEN, ""),                                                    # no here-document
        # the verdict is one of two plain words
        link_check(by, first_line=line.replace("--verdict doubt", "--verdict yes")),
        link_check(by, first_line=line.replace("--verdict doubt", "--verdict Bears")),
        link_check(by, first_line=line.replace("--verdict doubt", '--verdict "bears"')),
        link_check(by, first_line=line.replace("--verdict doubt", "--verdict")),
        link_check(by, first_line=line.replace("--verdict doubt", "--verdict bears --verdict doubt")),
        link_check(by, first_line=line.replace(" --verdict doubt", "")),
        link_check(by, first_line=line.replace("--verdict doubt", "--verdict=doubt")),
        # the lens is a plain lens name, the fact the letter F and digits
        link_check(by, first_line=line.replace("--lens firm-boundaries", '--lens "firm-boundaries"')),
        link_check(by, first_line=line.replace("--lens firm-boundaries", "--lens -x")),
        link_check(by, first_line=line.replace("--lens firm-boundaries", "--lens --from-json")),
        link_check(by, first_line=line.replace("--lens firm-boundaries", "--lens ../x")),
        link_check(by, first_line=line.replace("--lens firm-boundaries", "--lens a/b")),
        link_check(by, first_line=line.replace("--lens firm-boundaries", "--lens a.b")),
        link_check(by, first_line=line.replace("--lens firm-boundaries", "--lens a:b")),
        link_check(by, first_line=line.replace("--lens firm-boundaries", "--lens a=b")),
        link_check(by, first_line=line.replace("--lens firm-boundaries", "--lens")),
        link_check(by, first_line=line.replace("--lens firm-boundaries", "--lens $HOME")),
        link_check(by, first_line=line.replace("--lens firm-boundaries", "--lens f" + chr(0xFC) + "r")),
        link_check(by, first_line=line.replace(" --lens firm-boundaries", "")),
        link_check(by, first_line=line.replace("--lens firm-boundaries", "--lens a --lens b")),
        link_check(by, first_line=line.replace("--fact F3", "--fact f3")),
        link_check(by, first_line=line.replace("--fact F3", '--fact "F3"')),
        link_check(by, first_line=line.replace("--fact F3", "--fact F3,F4")),
        link_check(by, first_line=line.replace(" --fact F3", "")),
        # its own here-document, its end mark in single quotes, last on the first line
        link_check(by, first_line=line.replace(OPEN, LIST_OPEN), end="RADAR_LIST"),
        link_check(by, first_line=line.replace(OPEN, LIST_OPEN)),
        link_check(by, first_line=line.replace(OPEN, "<<RADAR_NOTE")),
        link_check(by, first_line=line.replace(OPEN, "<<" + Q + "RADAR_NOTE" + Q)),
        link_check(by, first_line=line.replace(OPEN, "<<-'RADAR_NOTE'")),
        link_check(by, first_line=line.replace(OPEN, "<<'EOF'"), end="EOF"),
        link_check(by, first_line=line.replace("--by", OPEN + " --by")),
        link_check(by, end="RADAR_NOTE "), link_check(by, end="RADAR_NOTE\n\n"), link_check(by, end="RADAR_LIST"),
        link_check(by, "RADAR_NOTE", "rm -rf ~"), link_check(by, BODY, "RADAR_NOTE", "ls"),
        link_check(by) + "\n" + link_check(by),
        # the advisor's commands are not a reader's
        ADVISOR_INPUT, recommendation(),
        recommendation(LIST_LINE.replace("--by lens-advisor", "--by " + by)),
        first.replace("record-link-check", "record-support"),
    ]


READER_HOSTILE = reader_hostile("lens-link-reader", "lens-link-reader-quick")
QUICK_HOSTILE = reader_hostile("lens-link-reader-quick", "lens-link-reader")


def test_the_sentences_of_the_lens_helpers_are_their_own():
    assert guard.ADVISOR_REASON == ADVISOR_ONLY and guard.READER_REASON == READER_ONLY
    assert guard.LINK_VERDICT_REASON == LINK_VERDICT_ONLY and guard.LIST_REASON == LIST_ONLY
    reasons = {guard.VERDICT_REASON, guard.HELPER_REASON, guard.NO_COMMANDS_REASON, guard.RECORDS_REASON,
               guard.ADVISOR_REASON, guard.READER_REASON, guard.LINK_VERDICT_REASON, guard.LIST_REASON,
               guard.FAILED_REASON}
    assert len(reasons) == 9


def test_the_three_lens_helpers_are_helpers_and_each_records_under_its_own_name():
    assert set(LENS_HELPERS) <= set(guard.HELPERS)       # the count of all helpers is in the grouper's section below
    assert set(guard.LENS_COMMANDS) == set(LENS_HELPERS)
    assert set(guard.LENS_COMMANDS["lens-advisor"]) == {"lens-advisor-input", "record-lens-recommendation"}
    for reader in LENS_HELPERS[1:]:
        assert set(guard.LENS_COMMANDS[reader]) == {"lens-link-context", "record-link-check"}
    for helper in (CHECKER, "source-scout", "fact-extractor", "bias-auditor"):   # the four keep their rules
        assert guard._helper_name(helper) not in guard.LENS_COMMANDS
    assert set(guard.OPTIONS) == {"quote-context", "record-support"}             # the checker's table is unchanged


@pytest.mark.parametrize("command", ADVISOR_ACCEPTED)
def test_what_the_advisor_is_allowed(command):
    assert guard.decide(event("Bash", ADVISOR, command=command)) is None
    assert guard.decide(event("Bash", "lens-advisor", command=command)) is None


@pytest.mark.parametrize("by", ["lens-link-reader", "lens-link-reader-quick"])
def test_what_each_reader_is_allowed(by):
    for command in reader_accepted(by):
        assert guard.decide(event("Bash", "strategy-radar:" + by, command=command)) is None, command
        assert guard.decide(event("Bash", by, command=command)) is None, command


@pytest.mark.parametrize("command", ADVISOR_HOSTILE)
def test_anything_outside_the_advisor_s_two_shapes_is_refused(command):
    assert guard.decide(event("Bash", ADVISOR, command=command)) == ADVISOR_ONLY
    assert guard.decide(event("Bash", "lens-advisor", command=command)) == ADVISOR_ONLY


@pytest.mark.parametrize("command", READER_HOSTILE)
def test_anything_outside_the_reader_s_two_shapes_is_refused(command):
    assert guard.decide(event("Bash", READER, command=command)) == READER_ONLY
    assert guard.decide(event("Bash", "lens-link-reader", command=command)) == READER_ONLY


@pytest.mark.parametrize("command", QUICK_HOSTILE)
def test_anything_outside_the_quick_reader_s_two_shapes_is_refused(command):
    assert guard.decide(event("Bash", QUICK, command=command)) == READER_ONLY
    assert guard.decide(event("Bash", "lens-link-reader-quick", command=command)) == READER_ONLY


def test_the_lens_hostile_lists_are_not_refused_for_a_silly_reason():
    assert len(set(ADVISOR_HOSTILE)) == len(ADVISOR_HOSTILE) and not set(ADVISOR_HOSTILE) & set(ADVISOR_ACCEPTED)
    for by, hostile in (("lens-link-reader", READER_HOSTILE), ("lens-link-reader-quick", QUICK_HOSTILE)):
        assert len(set(hostile)) == len(hostile) and not set(hostile) & set(reader_accepted(by))


def test_one_reader_can_never_record_under_the_other_s_name():
    assert guard.decide(event("Bash", READER, command=link_check("lens-link-reader"))) is None
    assert guard.decide(event("Bash", QUICK, command=link_check("lens-link-reader-quick"))) is None
    assert guard.decide(event("Bash", READER, command=link_check("lens-link-reader-quick"))) == READER_ONLY
    assert guard.decide(event("Bash", QUICK, command=link_check("lens-link-reader"))) == READER_ONLY
    for reader in (READER, QUICK):
        assert guard.decide(event("Bash", reader, command=link_check("lens-advisor"))) == READER_ONLY


@pytest.mark.parametrize("command", [None, 7, ["radar", "lens-link-context"], {"a": 1}, True])
def test_a_lens_helper_s_command_that_is_no_text_is_refused(command):
    for agent, reason in ((ADVISOR, ADVISOR_ONLY), (READER, READER_ONLY), (QUICK, READER_ONLY)):
        assert guard.decide(event("Bash", agent, command=command)) == reason
        assert guard.decide({"tool_name": "Bash", "agent_type": agent, "tool_input": {}}) == reason
        assert guard.decide({"tool_name": "Bash", "agent_type": agent}) == reason


def test_the_support_checker_and_the_helpers_with_no_commands_may_run_none_of_the_lens_commands():
    for command in (ADVISOR_INPUT, recommendation(), LINK_CONTEXT, link_check(), link_check("lens-link-reader-quick"),
                    link_check("support-checker")):
        for agent in (CHECKER, "support-checker"):
            assert guard.decide(event("Bash", agent, command=command)) == HELPER, command
        for helper in ("source-scout", "fact-extractor", "bias-auditor"):
            assert guard.decide(event("Bash", "strategy-radar:" + helper, command=command)) == NO_COMMANDS
    assert guard.decide(event("Bash", CHECKER, command=GOOD_VERDICT)) is None      # and the checker keeps its own


def test_the_advisor_may_not_record_a_link_verdict_and_a_reader_may_not_record_the_list():
    for command in (link_check(), link_check("lens-advisor"), GOOD_VERDICT):
        assert guard.decide(event("Bash", ADVISOR, command=command)) == ADVISOR_ONLY
    for reader in (READER, QUICK):
        for command in (recommendation(), GOOD_VERDICT, ADVISOR_INPUT):
            assert guard.decide(event("Bash", reader, command=command)) == READER_ONLY


NOT_A_LENS_HELPER = [None, "", "general-purpose", "Explore", "other-plugin:lens-advisor", "my-lens-advisor",
                     "strategy-radar:lens-advisor-2", "Lens-Advisor", "other:lens-link-reader", "lens-link-reader-slow",
                     "strategy-radar:lens-link-reader-quick-2", "lens-link-reader-quick ", "strategy-radar:run"]
LINK_VERDICT_COMMANDS = [
    link_check(), link_check("lens-link-reader-quick"),
    "radar record-link-check --run x --lens a --fact F1 --verdict bears --by lead --note ok",
    OWN_RADAR + " record-link-check --run x --lens a --fact F1 --verdict doubt --by lens-link-reader --note no",
    "python3 /p/engine/start_radar.py record-link-check --run x --lens a --fact F1 --verdict bears --by me --note ok",
    "sh -c 'radar record-link-check --run x --from-json check.json'",
    "cd /p && radar settle --run x && radar record-link-check --run x --lens a --fact F1 --verdict bears --by x --note y",
]
LIST_COMMANDS = [
    recommendation(),
    "radar record-lens-recommendation --run x --lenses y --by lens-advisor --file list.json",
    OWN_RADAR + " record-lens-recommendation --run x --lenses y --by lead --file -",
    "python3 /p/engine/start_radar.py record-lens-recommendation --run x --lenses y --by me --file l.json",
    "sh -c 'radar record-lens-recommendation --run x --from-json r.json'",
    "cd /p && radar settle --run x && radar record-lens-recommendation --run x --lenses y --by x --file z",
]


@pytest.mark.parametrize("agent", NOT_A_LENS_HELPER)
def test_a_link_verdict_or_a_recommendation_from_anyone_but_its_helper_is_refused(agent):
    for command in LINK_VERDICT_COMMANDS:
        assert guard.decide(lead_event(agent, command)) == LINK_VERDICT_ONLY, command
    for command in LIST_COMMANDS:
        assert guard.decide(lead_event(agent, command)) == LIST_ONLY, command
    assert guard.decide(lead_event(agent, "ls")) is None


def test_the_lead_may_still_read_what_the_lens_helpers_read_and_record_a_support_verdict_never():
    for command in (ADVISOR_INPUT, LINK_CONTEXT, "radar lens-view --run x --lenses y", "radar list-lenses --lenses y",
                    "radar settle --run x && ls"):
        assert guard.decide(lead_event(None, command)) is None, command
    # a command with more than one of the record words gets the sentence of the first, in a fixed order
    assert guard.decide(lead_event(None, verdict() + "\n" + link_check() + "\n" + recommendation())) == VERDICT_ONLY
    assert guard.decide(lead_event(None, recommendation() + "\n" + link_check())) == LINK_VERDICT_ONLY
    assert guard.decide(lead_event(None, recommendation() + "\n" + verdict())) == VERDICT_ONLY


def test_the_recorded_real_event_of_the_lead_is_refused_when_it_records_for_a_lens_helper():
    real = recorded("lead_bash")
    assert guard.decide({**real, "tool_input": {"command": link_check()}}) == LINK_VERDICT_ONLY
    assert guard.decide({**real, "tool_input": {"command": recommendation()}}) == LIST_ONLY
    result = run_guard(json.dumps({**real, "tool_input": {"command": recommendation()}}))
    assert result.returncode == 2 and result.stderr.decode("utf-8") == LIST_ONLY + "\n"
    result = run_guard(json.dumps({**real, "tool_input": {"command": link_check()}}))
    assert result.returncode == 2 and result.stderr.decode("utf-8") == LINK_VERDICT_ONLY + "\n"


@pytest.mark.parametrize("agent", ["lens-advisor", ADVISOR, "lens-link-reader", READER, "lens-link-reader-quick", QUICK])
def test_each_lens_helper_is_known_by_its_plain_name_and_by_its_name_in_the_plugin(agent):
    reason = ADVISOR_ONLY if agent.endswith("advisor") else READER_ONLY
    assert guard.decide(event("Bash", agent, command="ls")) == reason
    result = run_guard(json.dumps(event("Bash", agent, command="ls")))
    assert (result.returncode, result.stderr.decode("utf-8")) == (2, reason + "\n")
    allowed = run_guard(json.dumps(event("Bash", agent, command=ADVISOR_INPUT if agent.endswith("advisor") else LINK_CONTEXT)))
    assert (allowed.returncode, allowed.stdout, allowed.stderr) == (0, b"", b"")


def test_an_error_of_the_guard_s_own_while_judging_a_lens_helper_s_command_refuses_it(monkeypatch):
    def broken(*args):
        raise RuntimeError("an error of the guard's own")
    monkeypatch.setattr(guard, "_is_a_lens_helper_command", broken)
    for agent, command in ((ADVISOR, ADVISOR_INPUT), ("lens-advisor", recommendation()), (READER, LINK_CONTEXT),
                           ("lens-link-reader-quick", link_check("lens-link-reader-quick"))):
        assert guard.decide(event("Bash", agent, command=command)) == FAILED, agent
    monkeypatch.undo()
    monkeypatch.setattr(guard, "_fits", broken)                    # the part the checker shares with them
    for agent, command in ((ADVISOR, recommendation()), (QUICK, LINK_CONTEXT), (CHECKER, GOOD_VERDICT)):
        assert guard.decide(event("Bash", agent, command=command)) == FAILED, agent
    assert guard.decide(lead_event(None, "ls")) is None


def test_the_launcher_refuses_every_helper_when_the_guard_cannot_start():
    text = LAUNCHER.read_text(encoding="utf-8")
    case = text[text.index('case "$event" in'):text.index("refusal=")]
    named = set(re.findall(r"\*'\"([a-z:-]+)\"'\*", case))
    assert named == set(guard.HELPERS) | {guard.PLUGIN + ":" + helper for helper in guard.HELPERS}


def lens_blocks(name):
    text = body(ROOT / "agents" / (name + ".md"))
    return [block.strip("\n") for block in re.findall(r"```bash\n(.*?)```", text, flags=re.S)]


@pytest.mark.parametrize("name", LENS_HELPERS)
def test_the_commands_exactly_as_each_lens_helper_s_file_writes_them_are_allowed(name):
    blocks = lens_blocks(name)
    assert len(blocks) == 3                                              # each also reads a further part
    assert all("<run folder>" in block for block in blocks) and "<lens folder>" in blocks[0]
    assert "=" not in "".join(block.splitlines()[0] for block in blocks)   # the file never writes --key=value
    for run, lenses in (("/p/radar/runs/r1", "/p/plugin/lenses"),
                        ("/home/a b/Documents (1)/radar/runs/r1", "/home/a b/plugin (1)/lenses"),
                        ("/Users/x/it's & more; 100%/runs/r1", "/Users/x/it's & more; 100%/lenses")):
        for index, block in enumerate(blocks):
            command = block.replace("<run folder>", run).replace("<lens folder>", lenses)
            assert guard.decide(event("Bash", "strategy-radar:" + name, command=command)) is None, command
            assert guard.decide(event("Bash", name, command=command)) is None, command
            for other in LENS_HELPERS:
                if other == name:
                    continue
                both_read = index < 2 and name != "lens-advisor" and other != "lens-advisor"
                expected = None if both_read else (ADVISOR_ONLY if other == "lens-advisor" else READER_ONLY)
                assert guard.decide(event("Bash", other, command=command)) == expected, (other, command)
            assert guard.decide(event("Bash", CHECKER, command=command)) == HELPER


@pytest.mark.parametrize("name", LENS_HELPERS)
def test_the_one_name_each_lens_helper_records_under_is_its_own(name):
    record = lens_blocks(name)[-1]
    first = record.splitlines()[0]
    assert "--by " + name + " " in first and first.count("--by") == 1
    assert record.splitlines()[-1] == ("RADAR_LIST" if name == "lens-advisor" else "RADAR_NOTE")
    assert first.endswith(LIST_OPEN if name == "lens-advisor" else OPEN)


@pytest.mark.parametrize("shell", REAL_SHELLS)
def test_an_allowed_lens_command_starts_the_program_once_and_nothing_else(tmp_path, shell):
    cases = [(command, "lens-advisor") for command in ADVISOR_ACCEPTED if chr(0x2028) not in command]
    cases += [(command, by) for by in LENS_HELPERS[1:] for command in reader_accepted(by)]
    for command, by in cases:
        done, calls, left_behind = run_in_a_real_shell(command, tmp_path, shell)
        assert done.returncode == 0 and done.stdout == "" and done.stderr == "", command
        assert calls.count("CALL\n") == 1 and left_behind == [], command
        words = re.findall(r"^WORD:(.*)$", calls, flags=re.M)
        text = calls.split("TEXT:", 1)[1][:-len("\nEND\n")]
        if words[0] in ("lens-advisor-input", "lens-link-context") and "--part" in words:
            assert len(words) == 7 and set(words[1::2]) == {"--run", "--lenses", "--part"} and text == "", command
            assert re.fullmatch(r"[1-9][0-9]*", words[words.index("--part") + 1]), command
        elif words[0] in ("lens-advisor-input", "lens-link-context"):
            assert len(words) == 5 and set(words[1::2]) == {"--run", "--lenses"} and text == "", command
        elif words[0] == "record-lens-recommendation":
            assert words.count("--list-stdin") == 1 and len(words) == 8, command
            valued = [word for word in words[1:] if word != "--list-stdin"]
            options = dict(zip(valued[0::2], valued[1::2]))
            assert set(options) == {"--run", "--lenses", "--by"} and options["--by"] == "lens-advisor", command
            assert text == "".join(line + "\n" for line in command.rstrip("\n").split("\n")[1:-1])   # untouched
        else:
            assert words[0] == "record-link-check" and words.count("--note-stdin") == 1 and len(words) == 12, command
            valued = [word for word in words[1:] if word != "--note-stdin"]
            options = dict(zip(valued[0::2], valued[1::2]))
            assert set(options) == {"--run", "--lens", "--fact", "--verdict", "--by"}
            assert options["--by"] == by and options["--verdict"] in ("bears", "doubt")
            assert text == "".join(line + "\n" for line in command.rstrip("\n").split("\n")[1:-1])


LENS_FRAGMENTS = FRAGMENTS + [LIST_OPEN, "RADAR_LIST", "--file -", "--list-stdin", "--lens x", "--lenses y", "--verdict bears",
                              "--by lens-link-reader", "--by lens-link-reader-quick", "--by lens-advisor", "lens-advisor"]


@pytest.mark.parametrize("shell", REAL_SHELLS)
def test_a_hostile_piece_put_anywhere_into_a_good_lens_command_never_gets_more_than_the_program_started(tmp_path, shell):
    """As for the checker: every piece between any two words, and glued to either side of each word, of one good
    command of each kind of each lens helper. Where the guard lets one through, a real shell must start the program
    once, with one of that helper's two subcommands, and do nothing else."""
    good = [("lens-advisor", "radar lens-advisor-input --run " + RUN + " --lenses " + LENSES_AT),
            ("lens-advisor", recommendation()),
            ("lens-link-reader", "radar lens-link-context --run " + RUN + " --lenses " + LENSES_AT),
            ("lens-link-reader", link_check("lens-link-reader")),
            ("lens-link-reader-quick", link_check("lens-link-reader-quick"))]
    tried = let_through = 0
    for helper, command in good:
        own = set(guard.LENS_COMMANDS[helper])
        first, _, rest = command.partition("\n")
        places = [0] + [m.start() for m in re.finditer(" ", first)] + [len(first)]
        for place in places:
            for piece in LENS_FRAGMENTS:
                for glue in (piece, " " + piece, piece + " ", " " + piece + " "):
                    changed = first[:place] + glue + first[place:] + ("\n" + rest if rest else "")
                    tried += 1
                    if guard.decide(event("Bash", helper, command=changed)) is not None:
                        continue
                    let_through += 1
                    done, calls, left_behind = run_in_a_real_shell(changed, tmp_path, shell)
                    assert calls.count("CALL\n") == 1 and left_behind == [] and done.stdout == "", changed
                    words = re.findall(r"^WORD:(.*)$", calls, flags=re.M)
                    assert words[0] in own, changed
                    if "--by" in words:
                        assert words[words.index("--by") + 1] == helper, changed
    assert tried > 5000 and 0 < let_through < tried / 8      # mostly pieces inside the quoted folders, which are text


# --- the project grouper: two commands of its own, and nobody else records the projects --------------------------------
# It fetches its input and records its list, in the form its file shows, and nothing else, and it records only under its
# own name. The lens table is not touched: the grouper has a table of its own.

GROUPER = "strategy-radar:project-grouper"
GROUPER_ONLY = SENDER + "This helper may only run: radar project-grouper-input and radar record-projects."
PROJECTS_ONLY = SENDER + ("Only the project grouper records the projects. "
                          "Ask the project grouper to group the moves.")
GROUPER_INPUT = 'radar project-grouper-input --run "/p/radar/runs/r1"'
PROJECTS_LINE = 'radar record-projects --run "/p/radar/runs/r1" --by project-grouper --list-stdin ' + LIST_OPEN
PROJECTS_BODY = ("project: Competitor A, Plant North", "facts: F1, F2", "", "project: Competitor B, Plant South",
                 "facts: F3")


def projects_call(first_line=PROJECTS_LINE, *lines, end="RADAR_LIST"):
    return "\n".join([first_line, *(lines or PROJECTS_BODY), end])


GROUPER_ACCEPTED = [
    GROUPER_INPUT,
    GROUPER_INPUT + "\n",
    "radar project-grouper-input --run " + RUN,                                   # a quoted folder with spaces
    "radar project-grouper-input --run /p/radar/runs/r1",                          # a plain folder needs no quotes
    'radar project-grouper-input --run "/p/it\'s (a) run; & 100%/r1"',
    OWN_RADAR + " project-grouper-input --run x",
    '"' + OWN_RADAR + '" project-grouper-input --run x',
    GROUPER_INPUT + " --part 2",                                                   # a later part of the input
    "radar project-grouper-input --part 12 --run " + RUN,
    projects_call(),
    projects_call() + "\n",
    projects_call("radar record-projects --list-stdin --by project-grouper --run " + RUN + "  " + LIST_OPEN + " "),
    projects_call('"' + OWN_RADAR + '" record-projects --run x --by project-grouper --list-stdin ' + LIST_OPEN),
    projects_call(PROJECTS_LINE, "project: it's a \"name\" with $(id) and `id`", "facts: F1"),    # only text
    projects_call(PROJECTS_LINE, " RADAR_LIST", "RADAR_LIST ", "RADAR_LISTX", "radar_list", "RADAR_NOTE"),
    PROJECTS_LINE + "\nRADAR_LIST",                            # an empty list: the program refuses it
]
GROUPER_HOSTILE = [
    "ls", "", " ", "\n", "radar", "radar settle --run x", "radar status --root x", "echo hi",
    "radar lens-advisor-input --run x --lenses y", "radar quote-context --run x --fact F1",
    "radar project-grouper-input", "radar record-projects",
    # joined commands, pipes and redirects
    GROUPER_INPUT + "; rm -rf ~", GROUPER_INPUT + " && ls", GROUPER_INPUT + " || ls", GROUPER_INPUT + " & ls",
    GROUPER_INPUT + " | sh", GROUPER_INPUT + " > /tmp/out", GROUPER_INPUT + " < /etc/passwd",
    GROUPER_INPUT + " `id`", GROUPER_INPUT + " $(id)", GROUPER_INPUT + "\nrm -rf ~", "ls\n" + GROUPER_INPUT,
    "(" + GROUPER_INPUT + ")", GROUPER_INPUT + "\n\n", "X=1 " + GROUPER_INPUT, "sh -c " + GROUPER_INPUT,
    projects_call() + "\nrm -rf ~", projects_call() + "\n" + GROUPER_INPUT, GROUPER_INPUT + "\n" + projects_call(),
    projects_call().replace("\n", "\r\n"), projects_call() + "\r\n",
    PROJECTS_LINE.replace(" <<", " | sh <<") + "\n" + "\n".join(PROJECTS_BODY) + "\nRADAR_LIST",
    PROJECTS_LINE + " ; ls\n" + "\n".join(PROJECTS_BODY) + "\nRADAR_LIST",
    projects_call() + " | sh", projects_call() + "\nls",
    # the program by another name
    GROUPER_INPUT.replace("radar ", "bin/radar ", 1), GROUPER_INPUT.replace("radar ", "/tmp/evil/bin/radar ", 1),
    GROUPER_INPUT.replace("radar ", "Radar ", 1), GROUPER_INPUT.replace("radar ", "radarx ", 1),
    # the input command: its one option, once, with a plain value
    GROUPER_INPUT + " --from-json -", GROUPER_INPUT + " --file x", GROUPER_INPUT + " extra",
    GROUPER_INPUT + " --run y", GROUPER_INPUT + " --lenses y", GROUPER_INPUT + " --by project-grouper",
    GROUPER_INPUT + " --list-stdin", GROUPER_INPUT + " " + LIST_OPEN, GROUPER_INPUT.replace(' --run "/p/radar/runs/r1"', ""),
    "radar project-grouper-input --run -x", "radar project-grouper-input --run", "radar project-grouper-input --run=x",
    GROUPER_INPUT + " --run",
    # a part is a positive whole number, given once
    GROUPER_INPUT + " --part x", GROUPER_INPUT + " --part 0", GROUPER_INPUT + " --part -1", GROUPER_INPUT + " --part 02",
    GROUPER_INPUT + ' --part "2"', GROUPER_INPUT + " --part 1.5", GROUPER_INPUT + " --part", GROUPER_INPUT + " --part=2",
    GROUPER_INPUT + " --part 2 --part 3", GROUPER_INPUT + " --part 2;ls", GROUPER_INPUT + " --part $(id)",
    GROUPER_INPUT + " --parts 2", GROUPER_INPUT + " --page 2", GROUPER_INPUT + " --part 2 --all",
    projects_call(PROJECTS_LINE.replace("--list-stdin", "--part 2 --list-stdin")),
    # the list is on standard input, never on the command line and never in a file
    projects_call(PROJECTS_LINE.replace("--list-stdin " + LIST_OPEN, "--file projects.json")),
    projects_call(PROJECTS_LINE.replace("--list-stdin", "--file projects.json")),
    projects_call(PROJECTS_LINE.replace("--list-stdin", "--from-json -")),
    projects_call(PROJECTS_LINE.replace("--list-stdin", "--list-stdin --file p.json")),
    projects_call(PROJECTS_LINE.replace("--list-stdin", "--list-stdin --from-json p.json")),
    projects_call(PROJECTS_LINE.replace("--list-stdin", "--list-stdin --list-stdin")),
    projects_call(PROJECTS_LINE.replace(" --list-stdin", "")),
    projects_call(PROJECTS_LINE.replace("--list-stdin", '"--list-stdin"')),
    projects_call(PROJECTS_LINE.replace("--list-stdin", "--list-stdin -")),
    projects_call(PROJECTS_LINE.replace("--list-stdin", "--note-stdin")),
    projects_call(PROJECTS_LINE.replace("--run", "--lenses y --run")),
    projects_call(PROJECTS_LINE + ' {"projects": []}'),                          # a curly bracket on the command line
    projects_call(PROJECTS_LINE.replace('--run "/p/radar/runs/r1"', "--run {x}")),
    # a curly bracket anywhere in the list: the grouper writes none, so a call with one is sent back to be corrected
    projects_call(PROJECTS_LINE, '{"projects": []}'), projects_call(PROJECTS_LINE, "project: A {B}", "facts: F1"),
    projects_call(PROJECTS_LINE, "project: A }", "facts: F1"), projects_call(PROJECTS_LINE, "project: { A", "facts: F1"),
    projects_call(PROJECTS_LINE.replace('"/p/radar/runs/r1"', '"/p/{r1}"')),
    GROUPER_INPUT.replace("r1", "{r1}"), GROUPER_INPUT + " }",
    # it records only under its own name
    projects_call(PROJECTS_LINE.replace("--by project-grouper", "--by lens-advisor")),
    projects_call(PROJECTS_LINE.replace("--by project-grouper", "--by support-checker")),
    projects_call(PROJECTS_LINE.replace("--by project-grouper", "--by lead")),
    projects_call(PROJECTS_LINE.replace("--by project-grouper", '--by "project-grouper"')),
    projects_call(PROJECTS_LINE.replace("--by project-grouper", "--by strategy-radar:project-grouper")),
    projects_call(PROJECTS_LINE.replace("--by project-grouper", "--by Project-Grouper")),
    projects_call(PROJECTS_LINE.replace("--by project-grouper", "--by project-grouper2")),
    projects_call(PROJECTS_LINE.replace("--by project-grouper", "--by=project-grouper")),
    projects_call(PROJECTS_LINE.replace("--by project-grouper", "--by project-grouper --by project-grouper")),
    projects_call(PROJECTS_LINE.replace("--by project-grouper", "--by project-grouper --by lead")),
    projects_call(PROJECTS_LINE.replace("--by project-grouper", "--by")),
    projects_call(PROJECTS_LINE.replace(" --by project-grouper", "")),
    projects_call(PROJECTS_LINE.replace(' --run "/p/radar/runs/r1"', "")),
    # its own here-document, its end mark in single quotes, last on the first line
    projects_call(PROJECTS_LINE.replace(LIST_OPEN, OPEN), end="RADAR_NOTE"),
    projects_call(PROJECTS_LINE.replace(LIST_OPEN, OPEN)),
    projects_call(PROJECTS_LINE.replace(LIST_OPEN, "<<RADAR_LIST")),
    projects_call(PROJECTS_LINE.replace(LIST_OPEN, "<<-'RADAR_LIST'")),
    projects_call(PROJECTS_LINE.replace(LIST_OPEN, "<< 'RADAR_LIST'")),
    projects_call(PROJECTS_LINE.replace(LIST_OPEN, "<<'EOF'"), end="EOF"),
    projects_call(PROJECTS_LINE.replace(LIST_OPEN, LIST_OPEN + " " + LIST_OPEN)),
    projects_call(PROJECTS_LINE.replace("--by", LIST_OPEN + " --by")),
    projects_call(end="RADAR_LIST "), projects_call(end=" RADAR_LIST"), projects_call(end="RADAR_LIST\r"),
    projects_call(end="RADAR_LIST\n\n"), projects_call(end="radar_list"), projects_call(end="RADAR_NOTE"),
    # a line of the text equal to the end mark would end it early, and what follows would run
    projects_call(PROJECTS_LINE, "RADAR_LIST", "rm -rf ~"), projects_call(PROJECTS_LINE, *PROJECTS_BODY, "RADAR_LIST", "ls"),
    projects_call(PROJECTS_LINE, "RADAR_LIST"), projects_call() + "\n" + projects_call(),
    # the lens helpers' commands are not the grouper's
    ADVISOR_INPUT, recommendation(), LINK_CONTEXT, link_check(), verdict(), GOOD_VERDICT,
    projects_call(GROUPER_INPUT + " " + LIST_OPEN),
]


def test_the_grouper_has_its_own_two_sentences_and_a_table_of_its_own():
    assert guard.GROUPER_REASON == GROUPER_ONLY and guard.PROJECTS_REASON == PROJECTS_ONLY
    assert guard.GROUPER_COMMANDS == {"project-grouper": {
        "project-grouper-input": (("--run",), None),
        "record-projects": (("--run", "--by", "--list-stdin"), (guard.LIST_OPENER, guard.LIST_END))}}
    assert guard.OPTIONAL == {"lens-advisor-input": ("--part",), "project-grouper-input": ("--part",),
                              "claim-matcher-input": ("--part",), "lens-link-context": ("--part",)}
    assert "project-grouper" not in guard.LENS_COMMANDS and "project-grouper" not in guard.LENS_REASONS
    assert guard.PROJECTS_REASON in [reason for _, reason in guard.RECORD_WORDS]
    assert ("record-projects", guard.PROJECTS_REASON) in guard.RECORD_WORDS
    reasons = {guard.VERDICT_REASON, guard.HELPER_REASON, guard.NO_COMMANDS_REASON, guard.RECORDS_REASON,
               guard.ADVISOR_REASON, guard.READER_REASON, guard.LINK_VERDICT_REASON, guard.LIST_REASON,
               guard.FAILED_REASON, guard.GROUPER_REASON, guard.PROJECTS_REASON}
    assert len(reasons) == 11                                 # every sentence is its own


def test_eight_helpers_and_the_lens_table_is_unchanged():
    assert set(LENS_HELPERS) <= set(guard.HELPERS) and len(set(guard.HELPERS)) == len(guard.HELPERS) == 9
    assert "project-grouper" in guard.HELPERS and "claim-matcher" in guard.HELPERS
    assert set(guard.LENS_COMMANDS) == set(LENS_HELPERS)
    assert set(guard.LENS_COMMANDS["lens-advisor"]) == {"lens-advisor-input", "record-lens-recommendation"}
    for reader in LENS_HELPERS[1:]:
        assert set(guard.LENS_COMMANDS[reader]) == {"lens-link-context", "record-link-check"}
    assert [word for word, _ in guard.RECORD_WORDS][:3] == ["record-support", "record-link-check",
                                                           "record-lens-recommendation"]
    assert guard._helper_name("strategy-radar:project-grouper") == "project-grouper"
    assert guard._helper_name("project-grouper") == "project-grouper"
    assert guard._helper_name("other-plugin:project-grouper") is None
    assert guard._helper_name("project-grouper2") is None


@pytest.mark.parametrize("command", GROUPER_ACCEPTED)
def test_the_grouper_may_run_exactly_its_two_commands(command):
    assert guard.decide(event("Bash", GROUPER, command=command)) is None
    assert guard.decide(event("Bash", "project-grouper", command=command)) is None


@pytest.mark.parametrize("command", GROUPER_HOSTILE)
def test_anything_outside_the_grouper_s_two_shapes_is_refused(command):
    assert guard.decide(event("Bash", GROUPER, command=command)) == GROUPER_ONLY
    assert guard.decide(event("Bash", "project-grouper", command=command)) == GROUPER_ONLY


@pytest.mark.parametrize("command", [None, 7, ["radar", "record-projects"], {"command": "record-projects"}])
def test_a_grouper_command_that_is_no_text_is_refused(command):
    assert guard.decide(event("Bash", GROUPER, command=command)) == GROUPER_ONLY
    assert guard.decide({"tool_name": "Bash", "agent_type": GROUPER}) == GROUPER_ONLY


def test_the_lead_may_not_record_the_projects():
    for command in (projects_call(), PROJECTS_LINE, "radar record-projects --run x --by lead --file p.json",
                    OWN_RADAR + " record-projects --run x --by project-grouper --list-stdin",
                    "python3 /p/engine/start_radar.py record-projects --run x --by me --from-json p.json",
                    "sh -c 'radar record-projects --run x --file p.json'",
                    "cd /p && radar settle --run x && radar record-projects --run x --by x --file z"):
        for agent in (None, "", "general-purpose", "Explore", "other-plugin:project-grouper", "my-project-grouper",
                      "strategy-radar:project-grouper-2", "Project-Grouper", "strategy-radar:run"):
            assert guard.decide(lead_event(agent, command)) == PROJECTS_ONLY, (agent, command)


def test_the_lead_may_still_read_what_the_grouper_reads():
    for command in (GROUPER_INPUT, "radar project-grouper-input --run x", "radar status --run x", "ls"):
        assert guard.decide(lead_event(None, command)) is None, command
    # a command with more than one record word gets the sentence of the first, in a fixed order
    assert guard.decide(lead_event(None, recommendation() + "\n" + projects_call())) == LIST_ONLY
    assert guard.decide(lead_event(None, projects_call() + "\n" + verdict())) == VERDICT_ONLY
    assert guard.decide(lead_event(None, projects_call() + "\n" + link_check())) == LINK_VERDICT_ONLY


def test_the_other_helpers_may_not_run_the_grouper_s_commands():
    for command in (GROUPER_INPUT, projects_call()):
        for helper in ("lens-advisor", "lens-link-reader", "lens-link-reader-quick"):
            assert guard.decide(event("Bash", helper, command=command)) == guard.LENS_REASONS[helper]
        assert guard.decide(event("Bash", "support-checker", command=command)) == HELPER
        for helper in ("source-scout", "fact-extractor", "bias-auditor"):
            assert guard.decide(event("Bash", "strategy-radar:" + helper, command=command)) == NO_COMMANDS
    for command in (ADVISOR_INPUT, recommendation(), LINK_CONTEXT, link_check(), GOOD_VERDICT):
        assert guard.decide(event("Bash", GROUPER, command=command)) == GROUPER_ONLY


def test_the_recorded_real_event_of_the_lead_is_refused_when_it_records_the_projects():
    real = recorded("lead_bash")
    assert guard.decide({**real, "tool_input": {"command": projects_call()}}) == PROJECTS_ONLY
    result = run_guard(json.dumps({**real, "tool_input": {"command": projects_call()}}))
    assert result.returncode == 2 and result.stderr.decode("utf-8") == PROJECTS_ONLY + "\n"


@pytest.mark.parametrize("agent", ["project-grouper", GROUPER])
def test_the_grouper_is_known_by_its_plain_name_and_by_its_name_in_the_plugin(agent):
    assert guard.decide(event("Bash", agent, command="ls")) == GROUPER_ONLY
    result = run_guard(json.dumps(event("Bash", agent, command="ls")))
    assert (result.returncode, result.stderr.decode("utf-8")) == (2, GROUPER_ONLY + "\n")
    allowed = run_guard(json.dumps(event("Bash", agent, command=GROUPER_INPUT)))
    assert (allowed.returncode, allowed.stdout, allowed.stderr) == (0, b"", b"")


def test_an_error_of_the_guard_s_own_while_judging_the_grouper_refuses_it(monkeypatch):
    def broken(*args):
        raise RuntimeError("an error of the guard's own")
    monkeypatch.setattr(guard, "_fits", broken)
    for agent, command in ((GROUPER, GROUPER_INPUT), ("project-grouper", projects_call())):
        assert guard.decide(event("Bash", agent, command=command)) == FAILED, agent
    assert guard.decide(lead_event(None, "ls")) is None


def test_the_commands_exactly_as_the_grouper_s_file_writes_them_are_allowed():
    blocks = [block.strip("\n") for block in re.findall(r"```bash\n(.*?)```",
                                                         body(ROOT / "agents" / "project-grouper.md"), flags=re.S)]
    assert len(blocks) == 3 and all("<run folder>" in block for block in blocks)   # part 1, a further part, the record
    assert "=" not in "".join(block.splitlines()[0] for block in blocks)         # the file never writes --key=value
    first = blocks[-1].splitlines()[0]
    assert "--by project-grouper " in first and first.count("--by") == 1 and first.endswith(guard.LIST_OPENER)
    assert blocks[-1].splitlines()[-1] == "RADAR_LIST"
    for run in ("/p/radar/runs/r1", "/home/a b/Documents (1)/radar/runs/r1", "/Users/x/it's & more; 100%/runs/r1"):
        for block in blocks:
            command = block.replace("<run folder>", run)
            assert guard.decide(event("Bash", GROUPER, command=command)) is None, command
            assert guard.decide(event("Bash", "project-grouper", command=command)) is None, command
            for other in ("lens-advisor", "lens-link-reader", "lens-link-reader-quick"):
                assert guard.decide(event("Bash", other, command=command)) == guard.LENS_REASONS[other]
            assert guard.decide(event("Bash", CHECKER, command=command)) == HELPER


@pytest.mark.parametrize("shell", REAL_SHELLS)
def test_an_allowed_grouper_command_starts_the_program_once_and_nothing_else(tmp_path, shell):
    for command in GROUPER_ACCEPTED:
        done, calls, left_behind = run_in_a_real_shell(command, tmp_path, shell)
        assert done.returncode == 0 and done.stdout == "" and done.stderr == "", command
        assert calls.count("CALL\n") == 1 and left_behind == [], command
        words = re.findall(r"^WORD:(.*)$", calls, flags=re.M)
        text = calls.split("TEXT:", 1)[1][:-len("\nEND\n")]
        if words[0] == "project-grouper-input" and "--part" in words:
            assert len(words) == 5 and set(words[1::2]) == {"--run", "--part"} and text == "", command
            assert re.fullmatch(r"[1-9][0-9]*", words[words.index("--part") + 1]), command
        elif words[0] == "project-grouper-input":
            assert len(words) == 3 and words[1] == "--run" and text == "", command
        else:
            assert words[0] == "record-projects" and words.count("--list-stdin") == 1 and len(words) == 6, command
            valued = [word for word in words[1:] if word != "--list-stdin"]
            options = dict(zip(valued[0::2], valued[1::2]))
            assert set(options) == {"--run", "--by"} and options["--by"] == "project-grouper", command
            assert text == "".join(line + "\n" for line in command.rstrip("\n").split("\n")[1:-1])   # untouched


@pytest.mark.parametrize("shell", REAL_SHELLS)
def test_a_hostile_piece_put_anywhere_into_a_good_grouper_command_never_gets_more_than_the_program_started(tmp_path, shell):
    """As for the lens helpers: every piece between any two words, and glued to either side of each word, of one good
    command of each kind. Where the guard lets one through, a real shell must start the program once, with one of the
    grouper's two subcommands, and do nothing else."""
    pieces = LENS_FRAGMENTS + ["--file -", "--file p.json", "--by project-grouper", "project-grouper", "record-projects"]
    tried = let_through = 0
    for command in ("radar project-grouper-input --run " + RUN, projects_call()):
        first, _, rest = command.partition("\n")
        places = [0] + [m.start() for m in re.finditer(" ", first)] + [len(first)]
        for place in places:
            for piece in pieces:
                for glue in (piece, " " + piece, piece + " ", " " + piece + " "):
                    changed = first[:place] + glue + first[place:] + ("\n" + rest if rest else "")
                    tried += 1
                    if guard.decide(event("Bash", "project-grouper", command=changed)) is not None:
                        continue
                    let_through += 1
                    done, calls, left_behind = run_in_a_real_shell(changed, tmp_path, shell)
                    assert calls.count("CALL\n") == 1 and left_behind == [] and done.stdout == "", changed
                    words = re.findall(r"^WORD:(.*)$", calls, flags=re.M)
                    assert words[0] in guard.GROUPER_COMMANDS["project-grouper"], changed
                    if "--by" in words:
                        assert words[words.index("--by") + 1] == "project-grouper", changed
    assert tried > 1000 and 0 < let_through < tried / 8


# --- the claim matcher: two commands of its own, and nobody else records the claim groups ------------------------------
# It fetches its input and records its list, in the form its file shows, and nothing else, and it records only under its
# own name. It has a table of its own, as the grouper has.

MATCHER = "strategy-radar:claim-matcher"
MATCHER_ONLY = SENDER + "This helper may only run: radar claim-matcher-input and radar record-claim-groups."
CLAIMS_ONLY = SENDER + ("Only the claim matcher records the claim groups. "
                        "Ask the claim matcher to match the proposals.")
MATCHER_INPUT = 'radar claim-matcher-input --run "/p/radar/runs/r1" --sources S1,S2'
CLAIMS_LINE = ('radar record-claim-groups --run "/p/radar/runs/r1" --sources S1,S2 --by claim-matcher --list-stdin '
               + LIST_OPEN)
CLAIMS_BODY = ("keep: S1#1", "fold: S2#3, S9#1", "", "keep: S2#1", "fold: S3#2")


def claims_call(first_line=CLAIMS_LINE, *lines, end="RADAR_LIST"):
    return "\n".join([first_line, *(lines or CLAIMS_BODY), end])


MATCHER_ACCEPTED = [
    MATCHER_INPUT, MATCHER_INPUT + "\n", MATCHER_INPUT + " --part 2", MATCHER_INPUT.replace("S1,S2", "S7"),
    "radar claim-matcher-input --sources S1,S12 --part 12 --run " + RUN,
    OWN_RADAR + " claim-matcher-input --run x --sources S1",
    claims_call(), claims_call() + "\n", claims_call(CLAIMS_LINE, "keep: S1#1", "fold: S2#3"),
    claims_call("radar record-claim-groups --list-stdin --by claim-matcher --sources S1,S2 --run " + RUN + " " + LIST_OPEN),
    claims_call('"' + OWN_RADAR + '" record-claim-groups --run x --sources S1 --by claim-matcher --list-stdin ' + LIST_OPEN),
    CLAIMS_LINE + "\nRADAR_LIST",                              # an empty list: no groups
]
MATCHER_HOSTILE = [
    "ls", "", "\n", "radar", "radar settle --run x", "radar claim-matcher-input", "radar record-claim-groups",
    MATCHER_INPUT + "; ls", MATCHER_INPUT + " && ls", MATCHER_INPUT + " | sh", MATCHER_INPUT + " > /tmp/x",
    MATCHER_INPUT + " `id`", MATCHER_INPUT + " $(id)", MATCHER_INPUT + "\nrm -rf ~", "X=1 " + MATCHER_INPUT,
    MATCHER_INPUT.replace("radar ", "bin/radar ", 1), MATCHER_INPUT.replace("radar ", "/tmp/evil/bin/radar ", 1),
    # the options: each exactly once, only these
    MATCHER_INPUT + " --run y", MATCHER_INPUT + " --sources S3", MATCHER_INPUT + " --file x", MATCHER_INPUT + " extra",
    MATCHER_INPUT + " --by claim-matcher", MATCHER_INPUT + " --list-stdin",
    MATCHER_INPUT.replace(' --run "/p/radar/runs/r1"', ""), MATCHER_INPUT.replace(" --sources S1,S2", ""),
    MATCHER_INPUT + " --run",
    # --sources: source ids, plain, joined by commas
    MATCHER_INPUT.replace("S1,S2", '"S1,S2"'), MATCHER_INPUT.replace("S1,S2", "S1, S2"),
    MATCHER_INPUT.replace("S1,S2", "S1,"), MATCHER_INPUT.replace("S1,S2", ",S1"), MATCHER_INPUT.replace("S1,S2", "s1"),
    MATCHER_INPUT.replace("S1,S2", "1,2"), MATCHER_INPUT.replace("S1,S2", "S"),
    MATCHER_INPUT.replace("S1,S2", "S1;ls"), MATCHER_INPUT.replace("S1,S2", "S1,S2,$(id)"),
    MATCHER_INPUT.replace("S1,S2", "-S1"), MATCHER_INPUT.replace("S1,S2", "F1"),
    MATCHER_INPUT.replace("--sources S1,S2", "--sources"), MATCHER_INPUT.replace("--sources", "--source"),
    MATCHER_INPUT.replace("--sources S1,S2", "--sources=S1"),
    # --part: a positive whole number, plain, once
    MATCHER_INPUT + " --part x", MATCHER_INPUT + " --part 0", MATCHER_INPUT + " --part -1", MATCHER_INPUT + " --part 02",
    MATCHER_INPUT + ' --part "2"', MATCHER_INPUT + " --part", MATCHER_INPUT + " --part 2 --part 3",
    MATCHER_INPUT + " --part=2", MATCHER_INPUT + " --part 2;ls",
    # the record call: the list on standard input, never a file, and only under its own name
    claims_call(CLAIMS_LINE.replace(" --list-stdin", "")),
    claims_call(CLAIMS_LINE.replace("--list-stdin", "--file g.json")),
    claims_call(CLAIMS_LINE.replace("--list-stdin", "--from-json -")),
    claims_call(CLAIMS_LINE.replace("--list-stdin", "--note-stdin")),
    claims_call(CLAIMS_LINE.replace(" --sources S1,S2", "")),
    claims_call(CLAIMS_LINE.replace(' --run "/p/radar/runs/r1"', "")),
    claims_call(CLAIMS_LINE.replace(" --by claim-matcher", "")),
    claims_call(CLAIMS_LINE.replace("--by claim-matcher", "--by lead")),
    claims_call(CLAIMS_LINE.replace("--by claim-matcher", "--by project-grouper")),
    claims_call(CLAIMS_LINE.replace("--by claim-matcher", "--by strategy-radar:claim-matcher")),
    claims_call(CLAIMS_LINE.replace("--by claim-matcher", '--by "claim-matcher"')),
    claims_call(CLAIMS_LINE.replace("--by claim-matcher", "--by Claim-Matcher")),
    claims_call(CLAIMS_LINE.replace("--by claim-matcher", "--by claim-matcher2")),
    claims_call(CLAIMS_LINE.replace("--by claim-matcher", "--by claim-matcher --by claim-matcher")),
    # a curly bracket anywhere is sent back to be corrected
    claims_call(CLAIMS_LINE + ' {"merges": []}'), claims_call(CLAIMS_LINE.replace("S1,S2", "{S1}")),
    claims_call(CLAIMS_LINE, '[{"keep": "S1#1"}]'), claims_call(CLAIMS_LINE, "keep: S1#1 {x}", "fold: S2#3"),
    # its own here-document, its end mark in single quotes, last on the first line
    claims_call(CLAIMS_LINE.replace(LIST_OPEN, OPEN), end="RADAR_NOTE"), claims_call(CLAIMS_LINE.replace(LIST_OPEN, OPEN)),
    claims_call(CLAIMS_LINE.replace(LIST_OPEN, "<<RADAR_LIST")),
    claims_call(CLAIMS_LINE.replace(LIST_OPEN, "<<-'RADAR_LIST'")),
    claims_call(end="RADAR_LIST "), claims_call(end="radar_list"), claims_call() + "\n\n",
    # a line equal to the end mark would end the list early, and what follows would run
    claims_call(CLAIMS_LINE, "keep: S1#1", "RADAR_LIST", "rm -rf ~"), claims_call() + "\n" + claims_call(),
    # the other helpers' commands are not the matcher's
    GROUPER_INPUT, projects_call(), ADVISOR_INPUT, recommendation(), LINK_CONTEXT, link_check(), GOOD_VERDICT,
    claims_call(MATCHER_INPUT + " " + LIST_OPEN),
]


def test_the_matcher_has_its_own_two_sentences_and_a_table_of_its_own():
    assert guard.MATCHER_REASON == MATCHER_ONLY and guard.CLAIMS_REASON == CLAIMS_ONLY
    assert guard.MATCHER_COMMANDS == {"claim-matcher": {
        "claim-matcher-input": (("--run", "--sources"), None),
        "record-claim-groups": (("--run", "--sources", "--by", "--list-stdin"),
                                (guard.LIST_OPENER, guard.LIST_END))}}
    assert guard.OPTIONAL["claim-matcher-input"] == ("--part",)
    assert "claim-matcher" not in guard.LENS_COMMANDS and "claim-matcher" not in guard.GROUPER_COMMANDS
    assert ("record-claim-groups", guard.CLAIMS_REASON) in guard.RECORD_WORDS
    assert len({guard.MATCHER_REASON, guard.CLAIMS_REASON, guard.GROUPER_REASON, guard.PROJECTS_REASON}) == 4
    assert guard._helper_name("strategy-radar:claim-matcher") == guard._helper_name("claim-matcher") == "claim-matcher"
    assert guard._helper_name("other-plugin:claim-matcher") is None and guard._helper_name("claim-matcher2") is None


@pytest.mark.parametrize("command", MATCHER_ACCEPTED)
def test_the_matcher_may_run_exactly_its_two_commands(command):
    assert guard.decide(event("Bash", MATCHER, command=command)) is None
    assert guard.decide(event("Bash", "claim-matcher", command=command)) is None


@pytest.mark.parametrize("command", MATCHER_HOSTILE)
def test_anything_outside_the_matcher_s_two_shapes_is_refused(command):
    assert guard.decide(event("Bash", MATCHER, command=command)) == MATCHER_ONLY
    assert guard.decide(event("Bash", "claim-matcher", command=command)) == MATCHER_ONLY


@pytest.mark.parametrize("command", [None, 7, ["radar", "record-claim-groups"]])
def test_a_matcher_command_that_is_no_text_is_refused(command):
    assert guard.decide(event("Bash", MATCHER, command=command)) == MATCHER_ONLY
    assert guard.decide({"tool_name": "Bash", "agent_type": MATCHER}) == MATCHER_ONLY


def test_the_lead_and_the_other_helpers_may_not_record_the_claim_groups():
    for command in (claims_call(), CLAIMS_LINE, "radar record-claim-groups --run x --sources S1 --by lead",
                    "sh -c 'radar record-claim-groups --run x'"):
        for agent in (None, "", "general-purpose", "other-plugin:claim-matcher", "Claim-Matcher", "strategy-radar:run"):
            assert guard.decide(lead_event(agent, command)) == CLAIMS_ONLY, (agent, command)
        assert guard.decide(event("Bash", GROUPER, command=command)) == GROUPER_ONLY
        assert guard.decide(event("Bash", "lens-advisor", command=command)) == guard.LENS_REASONS["lens-advisor"]
        assert guard.decide(event("Bash", "support-checker", command=command)) == HELPER
    assert guard.decide(lead_event(None, MATCHER_INPUT)) is None            # reading is open to the lead
    for command in (MATCHER_INPUT, claims_call()):
        assert guard.decide(event("Bash", "source-scout", command=command)) == NO_COMMANDS


def test_an_error_of_the_guard_s_own_while_judging_the_matcher_refuses_it(monkeypatch):
    def broken(*args):
        raise RuntimeError("an error of the guard's own")
    monkeypatch.setattr(guard, "_fits", broken)
    assert guard.decide(event("Bash", MATCHER, command=MATCHER_INPUT)) == FAILED


def test_the_commands_exactly_as_the_matcher_s_file_writes_them_are_allowed():
    blocks = [block.strip("\n") for block in re.findall(r"```bash\n(.*?)```",
                                                         body(ROOT / "agents" / "claim-matcher.md"), flags=re.S)]
    assert len(blocks) == 3 and all("<run folder>" in block for block in blocks)   # part 1, a further part, the record
    first = blocks[-1].splitlines()[0]
    assert "--by claim-matcher " in first and first.count("--by") == 1 and first.endswith(guard.LIST_OPENER)
    assert blocks[-1].splitlines()[-1] == "RADAR_LIST"
    for run in ("/p/radar/runs/r1", "/home/a b/Documents (1)/radar/runs/r1", "/Users/x/it's & more; 100%/runs/r1"):
        for block in blocks:
            command = block.replace("<run folder>", run)
            assert guard.decide(event("Bash", MATCHER, command=command)) is None, command
            assert guard.decide(event("Bash", GROUPER, command=command)) == GROUPER_ONLY
            assert guard.decide(event("Bash", CHECKER, command=command)) == HELPER


def test_the_matcher_is_refused_through_the_real_guard_script():
    for agent in ("claim-matcher", MATCHER):
        result = run_guard(json.dumps(event("Bash", agent, command="ls")))
        assert (result.returncode, result.stderr.decode("utf-8")) == (2, MATCHER_ONLY + "\n")
        allowed = run_guard(json.dumps(event("Bash", agent, command=MATCHER_INPUT)))
        assert (allowed.returncode, allowed.stdout, allowed.stderr) == (0, b"", b"")
