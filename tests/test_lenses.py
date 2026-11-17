"""The lens check: one rule for a lens file, used by `radar check-lenses` and by the gate.

Every lens here is a changed copy of an invented demo lens; every reference and date is invented.
"""
import contextlib
import json
import os
import re
from datetime import date
from pathlib import Path

import pytest

from helpers import add_fact, add_source, make_run, minimal_analysis, unreadable_file
from radar import lenses, store
from radar.cli import main
from radar.demo import LENSES
from radar.explain import _entries, explain
from radar.schema import Problem, check_data
from test_status import ENGINE, _messages_in

TODAY = date(2026, 11, 15)
FILE = "lenses/firm-boundaries.json"
INVENTED_REFERENCE = "Invented Author (2020), An invented work for this test"


def demo_lens() -> dict:
    """A fresh copy of the invented demo lens firm-boundaries."""
    return json.loads((LENSES / "firm-boundaries.json").read_text(encoding="utf-8"))


def real_lens() -> dict:
    """The demo lens as a lens that ships would be: a reference that is not illustrative, and the day it was checked."""
    lens = demo_lens()
    lens["originals"][0]["reference"] = INVENTED_REFERENCE
    lens["originals"][0]["link"] = "https://www.example.com/the-work"   # a shipped reference-confirmed lens links to it
    lens["checked_on"] = "2026-11-01"
    return lens


def write(folder, lens, name="firm-boundaries") -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json"
    path.write_text(json.dumps(lens, indent=2), encoding="utf-8")
    return path


def problems(tmp_path, lens, real=False, today=TODAY, name="firm-boundaries") -> list[Problem]:
    return lenses.check_lens(write(tmp_path / "lenses", lens, name), real, today)


def put(lens: dict, field: str, value) -> dict:
    """Set the part `field` names: a key of the lens, questions[N] or originals[0].KEY."""
    if field.startswith("questions["):
        lens["questions"][int(field[len("questions["):-1])] = value
    elif field.startswith("originals[0]."):
        lens["originals"][0][field[len("originals[0]."):]] = value
    else:
        lens[field] = value
    return lens


def run_command(capsys, *argv):
    code = main([str(part) for part in argv])
    return code, json.loads(capsys.readouterr().out)


def run_naming(tmp_path, *lens_ids) -> Path:
    """A clean run whose analysis names the first lens id in its reasoning and the others in lens notes."""
    run = make_run(tmp_path / "runs")
    source = add_source(run, "The expansion adds two high-speed syringe lines for customers in 2028.")
    add_fact(run, source_id=source["id"], quote="adds two high-speed syringe lines for customers")
    analysis = minimal_analysis(["F1"], lens_id=lens_ids[0])
    analysis["lens_notes"] = [{"lens_id": lens_id, "here": "x"} for lens_id in lens_ids[1:]]
    store.write_analysis(run, analysis)
    return run


@contextlib.contextmanager
def folder_mode(folder: Path, mode: int):
    """`folder` with its mode set to `mode`, set back afterwards so it can be removed. Skips the test for a user (root,
    for example) whom the mode does not stop."""
    folder.chmod(mode)
    try:
        if os.access(folder, os.X_OK):
            pytest.skip("this user can enter a folder that nobody may enter")
        yield folder
    finally:
        folder.chmod(0o755)


# --- the demo lenses ------------------------------------------------------------------------

def test_the_two_demo_lenses_pass_without_real(capsys):
    assert sorted(path.name for path in LENSES.glob("*.json")) == ["capacity-commitment.json", "firm-boundaries.json"]
    assert lenses.check_lenses(LENSES) == []
    assert run_command(capsys, "check-lenses", "--lenses", LENSES) == (0, {"problems": [], "explained": []})


def test_the_demo_lenses_fail_with_real(capsys):
    expected = [Problem(f"lenses/{name}.json", field, message)
                for name in ("capacity-commitment", "firm-boundaries")
                for field, message in (("originals[0].reference", lenses.ILLUSTRATIVE_REFERENCE),
                                       ("checked_on", lenses.NOT_CHECKED))]
    expected.append(Problem("lenses/themes.json", None, lenses.THEMES_MISSING))   # the demo folder has no index
    assert lenses.check_lenses(LENSES, real=True, today=TODAY) == expected
    code, out = run_command(capsys, "check-lenses", "--lenses", LENSES, "--real")
    assert code == 1 and out["problems"] == [{"file": p.file, "field": p.field, "message": p.message} for p in expected]
    assert [entry["known"] for entry in out["explained"]] == [True] * 5


def test_a_lens_as_it_would_ship_passes_with_real(tmp_path):
    assert problems(tmp_path, real_lens(), real=True) == []
    assert problems(tmp_path, real_lens()) == []


# --- one rule at a time, each on a copy of a valid lens -----------------------------------------

def test_an_unknown_key_is_a_problem(tmp_path):
    assert problems(tmp_path, put(demo_lens(), "colour", "blue")) == [Problem(FILE, "colour", lenses.UNKNOWN_PART)]
    in_an_original = put(demo_lens(), "originals[0].pages", "1-9")
    assert problems(tmp_path, in_an_original) == [Problem(FILE, "originals[0].pages", lenses.UNKNOWN_PART)]
    assert problems(tmp_path, put(demo_lens(), "checked_on", "2026-11-01")) == []   # the one optional key


def test_an_id_that_differs_from_the_file_name_is_a_problem(tmp_path):
    assert problems(tmp_path, put(demo_lens(), "id", "firm-borders")) == [Problem(FILE, "id", lenses.ID_NAME)]
    assert problems(tmp_path, demo_lens(), name="boundaries") == [
        Problem("lenses/boundaries.json", "id", lenses.ID_NAME)]
    for odd in ("firm boundaries", "../firm-boundaries", "", None, 7):   # not in the form of a lens id
        assert problems(tmp_path, put(demo_lens(), "id", odd), name="firm boundaries") == [
            Problem("lenses/firm boundaries.json", "id", lenses.ID_FORM)], odd


@pytest.mark.parametrize("field", ["name", "idea", "suggests", "limits", "competing_idea", "questions[1]",
                                   "originals[0].reference", "checked_on"])
def test_a_string_of_401_characters_is_a_problem(tmp_path, field):
    assert problems(tmp_path, put(demo_lens(), field, "x" * 400)) == []
    assert problems(tmp_path, put(demo_lens(), field, "x" * 401)) == [Problem(FILE, field, lenses.TOO_LONG)]


def test_a_link_of_401_characters_is_a_problem(tmp_path):
    address = "https://www.example.com/"
    assert problems(tmp_path, put(demo_lens(), "originals[0].link", address + "a" * (400 - len(address)))) == []
    assert problems(tmp_path, put(demo_lens(), "originals[0].link", address + "a" * (401 - len(address)))) == [
        Problem(FILE, "originals[0].link", lenses.TOO_LONG)]


@pytest.mark.parametrize("field", ["name", "idea", "suggests", "limits", "competing_idea", "questions[0]",
                                   "originals[0].reference"])
def test_a_blank_or_missing_text_is_a_problem(tmp_path, field):
    for value in ("", "   ", 7, ["a text"], None):
        assert problems(tmp_path, put(demo_lens(), field, value)) == [Problem(FILE, field, lenses.TEXT_NEEDED)], value
    if "[" not in field:
        lens = demo_lens()
        del lens[field]
        assert problems(tmp_path, lens) == [Problem(FILE, field, lenses.TEXT_NEEDED)]


def test_two_questions_are_a_problem(tmp_path):
    lens = demo_lens()
    lens["questions"] = lens["questions"][:2]
    assert problems(tmp_path, lens) == [Problem(FILE, "questions", lenses.QUESTION_COUNT)]
    for odd in ("one question?", None, lens["questions"] * 2):
        assert problems(tmp_path, put(demo_lens(), "questions", odd)) == [
            Problem(FILE, "questions", lenses.QUESTION_COUNT)]


def test_empty_originals_are_a_problem(tmp_path):
    for odd in ([], None, "a work", {"reference": "a work"}):
        assert problems(tmp_path, put(demo_lens(), "originals", odd)) == [
            Problem(FILE, "originals", lenses.NO_ORIGINALS)], odd
    lens = demo_lens()
    del lens["originals"]
    assert problems(tmp_path, lens) == [Problem(FILE, "originals", lenses.NO_ORIGINALS)]
    lens = demo_lens()
    lens["originals"].append("a second work")
    assert problems(tmp_path, lens) == [Problem(FILE, "originals[1]", lenses.ORIGINAL_PARTS)]


def test_level_gold_is_a_problem(tmp_path):
    assert problems(tmp_path, put(demo_lens(), "originals[0].level", "gold")) == [
        Problem(FILE, "originals[0].level", lenses.LEVEL)]
    lens = demo_lens()
    del lens["originals"][0]["level"]
    assert problems(tmp_path, lens) == [Problem(FILE, "originals[0].level", lenses.LEVEL)]
    for level in store.LENS_LEVELS:
        lens = secondary_lens() if level == "secondary_source_read" else demo_lens()   # that level needs about and a link
        assert problems(tmp_path, put(lens, "originals[0].level", level)) == [], level


SECONDARY = "secondary_source_read"
SECONDARY_LINK = "https://www.example.com/an-invented-survey"


def secondary_lens() -> dict:
    """The demo lens with its one original read as a source about the work: level, about and a web address."""
    lens = demo_lens()
    lens["originals"][0].update({"level": SECONDARY, "about": "An invented work for this test", "link": SECONDARY_LINK})
    return lens


def test_a_secondary_source_entry_needs_about_and_a_link(tmp_path):
    assert problems(tmp_path, secondary_lens()) == []
    no_about = secondary_lens()
    del no_about["originals"][0]["about"]
    assert problems(tmp_path, no_about) == [Problem(FILE, "originals[0].about", lenses.ABOUT_NEEDED)]
    no_link = put(secondary_lens(), "originals[0].link", None)
    assert problems(tmp_path, no_link) == [Problem(FILE, "originals[0].link", lenses.SECONDARY_LINK)]
    neither = put(no_about, "originals[0].link", None)
    assert problems(tmp_path, neither) == [Problem(FILE, "originals[0].about", lenses.ABOUT_NEEDED),
                                           Problem(FILE, "originals[0].link", lenses.SECONDARY_LINK)]
    assert problems(tmp_path, put(secondary_lens(), "originals[0].link", "ftp://x")) == [
        Problem(FILE, "originals[0].link", lenses.LINK)]


def test_about_is_refused_on_any_other_level(tmp_path):
    for level in store.LENS_LEVELS:
        if level == SECONDARY:
            continue
        lens = put(demo_lens(), "originals[0].level", level)
        assert problems(tmp_path, lens) == [], level
        lens["originals"][0]["about"] = "An invented work for this test"
        assert problems(tmp_path, lens) == [Problem(FILE, "originals[0].about", lenses.ABOUT_ONLY)], level


def test_about_is_a_filled_text_of_at_most_400_characters(tmp_path):
    for bad in ("", "   ", None, 7, ["a"]):
        assert problems(tmp_path, put(secondary_lens(), "originals[0].about", bad)) == [
            Problem(FILE, "originals[0].about", lenses.TEXT_NEEDED)], bad
    assert problems(tmp_path, put(secondary_lens(), "originals[0].about", "a" * 401)) == [
        Problem(FILE, "originals[0].about", lenses.TOO_LONG)]
    assert problems(tmp_path, put(secondary_lens(), "originals[0].about", "a" * 400)) == []


def test_the_order_of_the_levels_is_weakest_first_and_holds_every_level():
    assert lenses.LEVEL_ORDER == ("reference_confirmed", "course_slides", SECONDARY, "original_read")
    assert set(lenses.LEVEL_ORDER) == set(store.LENS_LEVELS) and len(store.LENS_LEVELS) == 4
    assert lenses.ORIGINAL_KEYS == ("reference", "level", "link", "about")


def test_lens_level_is_the_lowest_by_the_order():
    def level(*levels):
        return lenses.lens_level({"originals": [{"level": item} for item in levels]})
    assert level("original_read", SECONDARY) == level(SECONDARY, "original_read") == SECONDARY
    assert level(SECONDARY, "course_slides") == level("course_slides", SECONDARY) == "course_slides"
    assert level("original_read", "course_slides") == level("course_slides", "original_read") == "course_slides"
    assert level(SECONDARY, "reference_confirmed") == level("reference_confirmed", SECONDARY) == "reference_confirmed"
    assert level("original_read", "reference_confirmed") == level("reference_confirmed", "original_read") == "reference_confirmed"
    assert level("course_slides", "reference_confirmed") == level("reference_confirmed", "course_slides") == "reference_confirmed"
    assert level("original_read", "original_read") == "original_read"


def test_rests_on_says_the_original_was_read_or_not():
    read = lenses.rests_on(put(demo_lens(), "originals[0].level", "original_read"))
    assert read.startswith("Rests on: the original, read") and "was not read" not in read
    text = lenses.rests_on(secondary_lens())
    entry = secondary_lens()["originals"][0]
    assert text.startswith("Rests on: ") and entry["reference"] in text and entry["about"] in text
    assert "the original itself was not read" in text
    slides = lenses.rests_on(put(demo_lens(), "originals[0].level", "course_slides"))
    assert "lecture slides on the idea were read" in slides and demo_lens()["originals"][0]["reference"] in slides
    confirmed = lenses.rests_on(put(demo_lens(), "originals[0].level", "reference_confirmed"))
    assert "the lens is written from the model's general knowledge of the work and was not checked against it" in confirmed
    mixed = secondary_lens()
    mixed["originals"].append({"reference": "A second work", "level": "original_read", "link": None})
    assert lenses.rests_on(mixed) == text   # a work that was read adds nothing to what the lens does not rest on


def test_rests_on_is_pinned_word_for_word_for_each_level():
    def lens(level, reference="Smith (2000)", about="Jones (1990)"):
        original = {"reference": reference, "level": level, "link": None}
        if level == SECONDARY:
            original["about"] = about
        return {"originals": [original]}
    assert lenses.rests_on(lens("original_read")) == "Rests on: the original, read"
    assert lenses.rests_on(lens("course_slides")) == "Rests on: Smith (2000); lecture slides on the idea were read"
    assert lenses.rests_on(lens("reference_confirmed")) == (
        "Rests on: Smith (2000); its text was not read: the lens is written from the model's general knowledge of the "
        "work and was not checked against it")
    assert lenses.rests_on(lens(SECONDARY)) == (
        "Rests on: Smith (2000), a source about Jones (1990), read; the original itself was not read")


def test_rests_on_for_two_unread_originals_reads_well_and_never_doubles_a_full_stop():
    one = {"reference": "Smith, A. (2000). A survey.", "level": SECONDARY, "about": "Jones, B. (1990). The work.",
           "link": "https://www.example.com/a"}
    two = {"reference": "Lee, C. (2010). Slides.", "level": "course_slides", "link": None}
    text = lenses.rests_on({"originals": [one, two]})
    assert text == ("Rests on: Smith, A. (2000). A survey, a source about Jones, B. (1990). The work, read; "
                    "the original itself was not read. It also rests on Lee, C. (2010). Slides; "
                    "lecture slides on the idea were read")
    assert ".." not in text and text.count("Rests on: ") == 1
    three = {"reference": "Kim, D. (2012). The book.", "level": "reference_confirmed", "link": None}
    text = lenses.rests_on({"originals": [two, three]})
    assert text == ("Rests on: Lee, C. (2010). Slides; lecture slides on the idea were read. "
                    "It also rests on Kim, D. (2012). The book; its text was not read: the lens is written from the "
                    "model's general knowledge of the work and was not checked against it")
    assert ".." not in text and ".;" not in text and ".," not in text


def test_rests_on_and_lens_level_are_documented_as_valid_only_after_the_lens_check():
    for function in (lenses.rests_on, lenses.lens_level):
        assert "lens check" in function.__doc__


_LEVEL_WORD = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")


def test_the_level_message_and_its_explanation_name_exactly_the_allowed_levels():
    entry = json.loads((ENGINE / "explanations_en.json").read_text(encoding="utf-8"))[lenses.LEVEL]
    for text in (lenses.LEVEL, entry["why"], entry["do"]):
        assert set(_LEVEL_WORD.findall(text)) == set(store.LENS_LEVELS), text


def test_a_link_to_ftp_is_a_problem(tmp_path):
    for bad in ("ftp://x", "x", "", "https://user:pw@www.example.com/a", "https://www.example.com/a b", 7,
                "https://www.ex" + chr(0xE4) + "mple.com/a", "https://www.example.com/a" + chr(0x200B),
                "https://www.example.com:99999/a"):
        assert problems(tmp_path, put(demo_lens(), "originals[0].link", bad)) == [
            Problem(FILE, "originals[0].link", lenses.LINK)], bad
    lens = demo_lens()
    del lens["originals"][0]["link"]
    assert problems(tmp_path, lens) == [Problem(FILE, "originals[0].link", lenses.LINK)]
    for good in (None, "https://www.example.com/an-invented-work", "http://www.example.com/a?b=1"):
        assert problems(tmp_path, put(demo_lens(), "originals[0].link", good)) == [], good


def test_a_lens_that_cannot_be_read_is_a_problem(tmp_path):
    folder = tmp_path / "lenses"
    folder.mkdir()
    path = folder / "firm-boundaries.json"
    unreadable = [Problem(FILE, None, lenses.UNREADABLE)]
    valid = json.dumps(demo_lens())
    for text in ("{", "", "[]", '"a lens"', chr(0xFEFF) + valid, "[" * 100000 + "]" * 100000):   # with a BOM; too deep
        path.write_text(text, encoding="utf-8")
        assert lenses.check_lens(path, False, TODAY) == unreadable, text[:20]
    path.write_bytes(valid.replace("Where", "Wh" + chr(0xE9) + "re").encode("latin-1"))   # not UTF-8
    assert lenses.check_lens(path, False, TODAY) == unreadable
    path.write_text(valid, encoding="utf-8")
    with unreadable_file(path):   # this user may not open it
        assert lenses.check_lens(path, False, TODAY) == unreadable
    path.unlink()
    path.mkdir()   # a folder under a lens's name
    assert lenses.check_lens(path, False, TODAY) == unreadable


def test_real_with_no_checked_on_is_a_problem(tmp_path):
    lens = real_lens()
    del lens["checked_on"]
    assert problems(tmp_path, lens, real=True) == [Problem(FILE, "checked_on", lenses.NOT_CHECKED)]
    assert problems(tmp_path, lens) == []   # without real the day is optional


def test_real_with_a_future_date_is_a_problem(tmp_path):
    assert problems(tmp_path, put(real_lens(), "checked_on", "2026-11-15"), real=True, today=TODAY) == []
    assert problems(tmp_path, put(real_lens(), "checked_on", "2026-11-16"), real=True, today=TODAY) == [
        Problem(FILE, "checked_on", lenses.CHECKED_ON_FUTURE)]


def test_real_with_a_bad_date_is_a_problem(tmp_path):
    for bad in ("15.11.2026", "2026-13-01", "2026-02-30", "20261101", "2026-11-1", "2026-W46-1", "last week",
                "", "  ", 20261101, None, "2026-11-01" + "x" * 400):   # with real, anything but a day is a date problem
        assert problems(tmp_path, put(real_lens(), "checked_on", bad), real=True) == [
            Problem(FILE, "checked_on", lenses.CHECKED_ON_FORM)], bad
    assert problems(tmp_path, put(real_lens(), "checked_on", "last week")) == []   # without real a text is not judged


@pytest.mark.parametrize("real", [False, True])
def test_a_day_that_is_blank_or_not_text_is_a_date_problem_with_and_without_real(tmp_path, real):
    for not_text in ("", "  ", 20261101, None, ["2026-11-01"]):
        assert problems(tmp_path, put(real_lens(), "checked_on", not_text), real=real) == [
            Problem(FILE, "checked_on", lenses.CHECKED_ON_FORM)], not_text


def test_real_with_an_illustrative_reference_is_a_problem(tmp_path):
    for reference in ("Illustrative reference, not a real work", "  Illustrative reference", "illustrative work",
                      "ILLUSTRATIVE: an invented work"):
        lens = real_lens()
        lens["originals"].append({"reference": reference, "level": "original_read", "link": None})
        assert problems(tmp_path, lens, real=True) == [
            Problem(FILE, "originals[1].reference", lenses.ILLUSTRATIVE_REFERENCE)], reference
        assert problems(tmp_path, lens) == []
    named_inside = put(real_lens(), "originals[0].reference", "Invented Author (2020), An illustrative case")
    assert problems(tmp_path, named_inside, real=True) == []   # only a reference that begins with the word


# --- a folder of lenses -----------------------------------------------------------------------

def test_an_empty_folder_is_a_problem(tmp_path, capsys):
    folder = tmp_path / "lenses"
    folder.mkdir()
    (folder / "README.md").write_text("Notes on the lenses, not a lens.", encoding="utf-8")
    assert lenses.check_lenses(folder) == [Problem("lenses", None, lenses.NO_LENS_FILES)]
    code, out = run_command(capsys, "check-lenses", "--lenses", folder)
    assert code == 1 and out["problems"] == [{"file": "lenses", "field": None, "message": "no lens files"}]
    assert out["explained"][0]["known"] is True


def test_every_lens_of_a_folder_is_checked_in_the_order_of_its_names(tmp_path):
    folder = tmp_path / "lenses"
    write(folder, put(put(demo_lens(), "id", "b-lens"), "colour", "blue"), name="b-lens")
    write(folder, put(demo_lens(), "id", "a-lens"), name="a-lens")
    write(folder, put(put(demo_lens(), "id", "c-lens"), "idea", ""), name="c-lens")
    assert lenses.check_lenses(folder) == [Problem("lenses/b-lens.json", "colour", lenses.UNKNOWN_PART),
                                           Problem("lenses/c-lens.json", "idea", lenses.TEXT_NEEDED)]


@pytest.mark.parametrize("mode", [0o444, 0o000], ids=["listed but not entered", "not listed"])
def test_a_lens_folder_that_cannot_be_read_is_a_problem_for_the_command_and_the_gate(tmp_path, capsys, mode):
    folder = tmp_path / "lenses"
    write(folder, demo_lens())
    write(folder, json.loads((LENSES / "capacity-commitment.json").read_text(encoding="utf-8")),
          name="capacity-commitment")
    run = run_naming(tmp_path, "firm-boundaries", "capacity-commitment")
    expected = [Problem("lenses", None, lenses.FOLDER_UNREADABLE)]
    with folder_mode(folder, mode):
        assert lenses.check_lenses(folder) == expected
        code, out = run_command(capsys, "check-lenses", "--lenses", folder)
        assert code == 1 and out["problems"] == [{"file": "lenses", "field": None, "message": lenses.FOLDER_UNREADABLE}]
        assert out["explained"][0]["known"] is True
        assert check_data(run, folder) == expected   # named once, and no lens is said not to exist


def test_a_missing_folder_is_wrong_use_exit_2(tmp_path, capsys):
    missing = tmp_path / "lenses"
    assert run_command(capsys, "check-lenses", "--lenses", missing) == (
        2, {"error": f"{missing} does not exist. Give the folder of the lens files."})
    a_file = tmp_path / "a-file"
    a_file.write_text("not a folder", encoding="utf-8")
    assert run_command(capsys, "check-lenses", "--lenses", a_file) == (
        2, {"error": f"{a_file} is a file, not a folder. Give the folder of the lens files."})


# --- the themes index ------------------------------------------------------------------------

INDEX = "lenses/themes.json"
THEME_IDS = ("a-lens", "b-lens", "c-lens")


def themed_folder(tmp_path, themes="all", ids=THEME_IDS) -> Path:
    """A folder of lenses that would ship, with a themes index. `themes` is the object to write, a text to write as it
    is, None for no index, or "all" for one theme holding every lens."""
    folder = tmp_path / "lenses"
    for lens_id in ids:
        write(folder, put(real_lens(), "id", lens_id), name=lens_id)
    if themes == "all":
        themes = {"themes": [{"name": "All of them", "lenses": list(ids)}]}
    if themes is not None:
        text = themes if isinstance(themes, str) else json.dumps(themes, indent=2)
        (folder / "themes.json").write_text(text, encoding="utf-8")
    return folder


def themes_of(*groups, **extra) -> dict:
    return {"themes": [{"name": f"Theme {number}", "lenses": list(group)} for number, group in enumerate(groups)],
            **extra}


def test_themes_json_is_not_read_as_a_lens(tmp_path):
    folder = themed_folder(tmp_path)
    assert [path.name for path in lenses.lens_files(folder)] == ["a-lens.json", "b-lens.json", "c-lens.json"]
    assert lenses.THEMES_FILE == "themes.json"
    assert lenses.check_lenses(folder, real=True, today=TODAY) == []
    only_the_index = tmp_path / "only"
    only_the_index.mkdir()
    (only_the_index / "themes.json").write_text(json.dumps(themes_of(["a-lens"])), encoding="utf-8")
    assert lenses.lens_files(only_the_index) == []
    assert lenses.check_lenses(only_the_index) == [Problem("lenses", None, lenses.NO_LENS_FILES)]
    # a damaged index is a problem of the index, never of a lens, and the gate does not look at it at all
    damaged = themed_folder(tmp_path / "damaged", "{")
    assert lenses.check_lenses(damaged, today=TODAY) == [Problem(INDEX, None, lenses.THEMES_UNREADABLE)]
    run = run_naming(tmp_path, "a-lens")
    assert check_data(run, damaged) == []


def test_each_lens_must_be_in_exactly_one_theme_with_real(tmp_path):
    folder = themed_folder(tmp_path, themes_of(["a-lens", "b-lens"]))
    assert lenses.check_lenses(folder, real=True, today=TODAY) == [
        Problem("lenses/c-lens.json", None, lenses.LENS_NOT_IN_A_THEME)]
    assert lenses.check_lenses(folder, today=TODAY) == []   # without real, only what the index says is checked
    two_themes = themed_folder(tmp_path / "two", themes_of(["a-lens"], ["b-lens", "c-lens"]))
    assert lenses.check_lenses(two_themes, real=True, today=TODAY) == []


def test_a_theme_naming_a_lens_that_has_no_file_is_refused(tmp_path):
    folder = themed_folder(tmp_path, themes_of(["a-lens", "b-lens"], ["c-lens", "d-lens"]))
    expected = [Problem(INDEX, "themes[1].lenses[1]", lenses.THEME_LENS_HAS_NO_FILE)]
    assert lenses.check_lenses(folder, today=TODAY) == expected == lenses.check_lenses(folder, real=True, today=TODAY)
    wrong_case = themed_folder(tmp_path / "case", themes_of(["A-Lens", "b-lens", "c-lens"]))
    assert Problem(INDEX, "themes[0].lenses[0]", lenses.THEME_LENS_HAS_NO_FILE) in lenses.check_lenses(wrong_case)
    assert Problem("lenses/a-lens.json", None, lenses.LENS_NOT_IN_A_THEME) in lenses.check_lenses(wrong_case, real=True)


def test_a_lens_listed_twice_is_refused(tmp_path):
    in_two_themes = themed_folder(tmp_path, themes_of(["a-lens", "b-lens"], ["b-lens", "c-lens"]))
    assert lenses.check_lenses(in_two_themes, today=TODAY) == [
        Problem(INDEX, "themes[1].lenses[0]", lenses.LENS_LISTED_TWICE)]
    in_one_theme = themed_folder(tmp_path / "one", themes_of(["a-lens", "b-lens", "a-lens", "c-lens"]))
    assert lenses.check_lenses(in_one_theme, real=True, today=TODAY) == [
        Problem(INDEX, "themes[0].lenses[2]", lenses.LENS_LISTED_TWICE)]


def test_without_real_a_missing_index_is_fine_and_a_present_one_is_checked(tmp_path, capsys):
    folder = themed_folder(tmp_path, None)
    assert lenses.read_themes(folder) == (None, [])
    assert lenses.check_themes(folder, real=False) == []
    assert lenses.check_lenses(folder, today=TODAY) == []
    assert lenses.check_lenses(folder, real=True, today=TODAY) == [Problem(INDEX, None, lenses.THEMES_MISSING)]
    assert lenses.check_themes(folder, real=True) == [Problem(INDEX, None, lenses.THEMES_MISSING)]
    code, out = run_command(capsys, "check-lenses", "--lenses", folder, "--real")
    assert code == 1 and out["problems"] == [{"file": INDEX, "field": None, "message": lenses.THEMES_MISSING}]
    assert out["explained"][0]["known"] is True
    present = themed_folder(tmp_path / "present", themes_of(["a-lens", "nowhere"], ["b-lens", "c-lens"]))
    assert lenses.check_themes(present, real=False) == [
        Problem(INDEX, "themes[0].lenses[1]", lenses.THEME_LENS_HAS_NO_FILE)]
    code, out = run_command(capsys, "check-lenses", "--lenses", present)
    assert code == 1 and [entry["known"] for entry in out["explained"]] == [True]


def test_an_unknown_key_in_the_index_is_refused(tmp_path):
    folder = themed_folder(tmp_path, themes_of(["a-lens", "b-lens", "c-lens"], colour="blue"))
    assert lenses.check_themes(folder, real=True) == [Problem(INDEX, "colour", lenses.THEMES_UNKNOWN_PART)]
    themes = themes_of(["a-lens", "b-lens", "c-lens"])
    themes["themes"][0]["colour"] = "blue"
    folder = themed_folder(tmp_path / "inner", themes)
    assert lenses.check_themes(folder, real=True) == [Problem(INDEX, "themes[0].colour", lenses.THEMES_UNKNOWN_PART)]


def test_a_theme_name_is_a_filled_text_of_at_most_400_characters(tmp_path):
    def with_name(name, path):
        themes = themes_of(["a-lens", "b-lens", "c-lens"])
        themes["themes"][0]["name"] = name
        return themed_folder(path, themes)

    assert lenses.check_themes(with_name("x" * 400, tmp_path / "ok"), real=True) == []
    for number, bad in enumerate(("x" * 401, "", "   ", 7, None, ["a name"])):
        folder = with_name(bad, tmp_path / f"bad{number}")
        assert lenses.check_themes(folder, real=True) == [Problem(INDEX, "themes[0].name", lenses.THEME_NAME)], bad
    themes = themes_of(["a-lens", "b-lens", "c-lens"])
    del themes["themes"][0]["name"]
    assert lenses.check_themes(themed_folder(tmp_path / "gone", themes), real=True) == [
        Problem(INDEX, "themes[0].name", lenses.THEME_NAME)]


def test_a_badly_shaped_index_is_refused_and_never_raises(tmp_path):
    for number, (themes, expected) in enumerate((
            ({}, [Problem(INDEX, "themes", lenses.THEMES_NOT_A_LIST)]),
            ({"themes": "a-lens"}, [Problem(INDEX, "themes", lenses.THEMES_NOT_A_LIST)]),
            ("[]", [Problem(INDEX, None, lenses.THEMES_UNREADABLE)]),
            ("", [Problem(INDEX, None, lenses.THEMES_UNREADABLE)]),
            ({"themes": ["a-lens"]}, [Problem(INDEX, "themes[0]", lenses.THEME_PARTS)]),
            ({"themes": [{"name": "A"}]}, [Problem(INDEX, "themes[0].lenses", lenses.THEME_PARTS)]),
            ({"themes": [{"name": "A", "lenses": "a-lens"}]}, [Problem(INDEX, "themes[0].lenses", lenses.THEME_PARTS)]),
            ({"themes": [{"name": "A", "lenses": ["a-lens", 7]}]},
             [Problem(INDEX, "themes[0].lenses[1]", lenses.THEME_PARTS)]))):
        folder = themed_folder(tmp_path / f"case{number}", themes)
        assert lenses.check_themes(folder, real=False) == expected, themes
        everything = lenses.check_themes(folder, real=True)
        assert all(problem in everything for problem in expected), themes
    unreadable = tmp_path / "a-folder-as-index"
    folder = themed_folder(unreadable, None)
    (folder / "themes.json").mkdir()
    assert [path.name for path in lenses.lens_files(folder)] == ["a-lens.json", "b-lens.json", "c-lens.json"]
    assert lenses.check_themes(folder, real=True) == [Problem(INDEX, None, lenses.THEMES_UNREADABLE)]


def test_read_themes_gives_the_themes_as_they_are_written(tmp_path):
    folder = themed_folder(tmp_path, themes_of(["a-lens"], ["b-lens", "c-lens"]))
    assert lenses.read_themes(folder) == (
        [{"name": "Theme 0", "lenses": ["a-lens"]}, {"name": "Theme 1", "lenses": ["b-lens", "c-lens"]}], [])
    broken = themed_folder(tmp_path / "broken", {"themes": [{"name": "Fine", "lenses": ["a-lens"]}, "b-lens"]})
    themes, found = lenses.read_themes(broken)
    assert themes == [{"name": "Fine", "lenses": ["a-lens"]}] and found == [Problem(INDEX, "themes[1]", lenses.THEME_PARTS)]
    assert lenses.read_themes(themed_folder(tmp_path / "damaged", "{")) == (
        None, [Problem(INDEX, None, lenses.THEMES_UNREADABLE)])
    assert lenses.read_themes(tmp_path / "no-such-folder") == (None, [])


def test_the_theme_check_never_raises_on_a_folder_that_cannot_be_read(tmp_path):
    folder = themed_folder(tmp_path)
    with folder_mode(folder, 0o000):
        assert lenses.check_themes(folder, real=True) == []   # the folder problem is named once, by check_lenses
        assert lenses.check_lenses(folder, real=True, today=TODAY) == [Problem("lenses", None, lenses.FOLDER_UNREADABLE)]
        assert lenses.read_themes(folder)[0] is None


# --- the gate and the command ----------------------------------------------------------------

BROKEN = {
    "an unknown key": lambda lens: put(lens, "colour", "blue"),
    "an id that differs from the file name": lambda lens: put(lens, "id", "firm-borders"),
    "a string of 401 characters": lambda lens: put(lens, "idea", "x" * 401),
    "a blank text": lambda lens: put(lens, "limits", " "),
    "two questions": lambda lens: put(lens, "questions", lens["questions"][:2]),
    "empty originals": lambda lens: put(lens, "originals", []),
    "level gold": lambda lens: put(lens, "originals[0].level", "gold"),
    "a link to ftp": lambda lens: put(lens, "originals[0].link", "ftp://x"),
}


@pytest.mark.parametrize("how", sorted(BROKEN))
def test_the_gate_and_the_command_use_the_same_rule(tmp_path, capsys, how):
    run = make_run(tmp_path / "runs")
    source = add_source(run, "The expansion adds two high-speed syringe lines for customers in 2028.")
    add_fact(run, source_id=source["id"], quote="adds two high-speed syringe lines for customers")
    store.write_analysis(run, minimal_analysis(["F1"], lens_id="firm-boundaries"))
    folder = tmp_path / "lenses"
    write(folder, BROKEN[how](demo_lens()))
    found = check_data(run, folder)
    from_the_gate = [p for p in found if p.file.startswith("lenses/")]
    assert len(from_the_gate) == 1 and from_the_gate == lenses.check_lenses(folder)
    assert [p for p in found if p not in from_the_gate] == []
    code, out = run_command(capsys, "check-lenses", "--lenses", folder)
    assert code == 1
    assert out["problems"] == [{"file": p.file, "field": p.field, "message": p.message} for p in from_the_gate]


def test_the_gate_and_the_command_agree_on_a_lens_that_cannot_be_read(tmp_path, capsys):
    run = run_naming(tmp_path, "firm-boundaries")
    folder = tmp_path / "lenses"
    folder.mkdir()
    (folder / "firm-boundaries.json").write_text("{", encoding="utf-8")
    expected = [Problem(FILE, None, lenses.UNREADABLE)]
    assert check_data(run, folder) == expected == lenses.check_lenses(folder)
    code, out = run_command(capsys, "check-lenses", "--lenses", folder)
    assert code == 1 and out["problems"] == [{"file": FILE, "field": None, "message": lenses.UNREADABLE}]


def test_the_gate_finds_a_lens_only_under_its_exact_name(tmp_path):
    run = run_naming(tmp_path, "Firm-Boundaries")
    folder = tmp_path / "lenses"
    write(folder, demo_lens())   # firm-boundaries.json: on a disk that ignores case it also opens as Firm-Boundaries
    assert check_data(run, folder) == [
        Problem("analysis.json", "messages[0].chain[1].lens_id", "lens Firm-Boundaries does not exist")]


# --- the messages and their explanations ------------------------------------------------------

def new_lens_messages() -> set[str]:
    """Every message lenses.py hands to a problem, as the code reads, except the one it keeps from the gate's old lens
    check, word for word."""
    return _messages_in(ENGINE / "lenses.py") - {lenses.QUESTION_COUNT}


def test_every_new_lens_message_has_its_own_explanation():
    assert lenses.QUESTION_COUNT == "lens must have exactly 3 questions"   # the old message, unchanged
    messages = new_lens_messages()
    assert len(messages) == 29, sorted(messages)   # 29 with the link rule for a lens from the model's knowledge
    entries = json.loads((ENGINE / "explanations_en.json").read_text(encoding="utf-8"))
    for message in sorted(messages):
        assert message in entries, message
        matching = [entry for pattern, entry in _entries() if pattern.search(message)]
        assert matching == [entries[message]], message   # no other entry, older or new, is found inside it
        own = {part: text.replace("{field}", "idea") for part, text in entries[message].items()}
        assert explain(Problem(FILE, "idea", message)) == {"known": True, **own}, message
        text = " ".join(entries[message].values()).lower()
        assert "lens" in text, message
        assert not re.search(r"this run|saved item|\banalysis\b|\breports?\b|\{id\}|\{value\}", text), message
        # Only a lens's name and idea are shown when lenses are chosen, and the day it was checked is never shown.
        assert not re.search(r"\bshow(?:s|n)?\b|the person who chooses", text), message
        assert "step that writes it again" not in text, message   # nothing writes a lens: a person does


def test_the_link_explanation_names_what_the_check_refuses():
    entry = json.loads((ENGINE / "explanations_en.json").read_text(encoding="utf-8"))[lenses.LINK]
    text = " ".join(entry.values())
    for named in ("http or https", "user name", "password", "space", "hidden character", "port", "plain letters"):
        assert named in text, named


@pytest.mark.parametrize("reference, expected", [
    ("Illustrative work, not a real one", True),
    ("  ILLUSTRATIVE reference", True),
    ("illustrative", True),
    ("A real work (illustrative in name only)", False),
    ("", False),
    (None, False),
    (7, False),
])
def test_one_shared_test_says_whether_a_reference_is_illustrative(reference, expected):
    assert lenses.is_illustrative(reference) is expected


@pytest.mark.parametrize("reference", ["  ILLUSTRATIVE reference", "A real work, illustrative later on", "Smith (2000). A real work."])
def test_the_real_use_rule_the_first_stop_and_the_lens_view_agree_with_the_shared_test(reference):
    from radar import lens_view
    lens = {"originals": [{"reference": reference, "level": "original_read"}]}
    expected = lenses.is_illustrative(reference)
    out = lenses._Problems()
    lenses._check_original(out, "x.json", lens["originals"][0], "originals[0]", True)
    assert any(problem.message == lenses.ILLUSTRATIVE_REFERENCE for problem in out.items) is expected
    assert lens_view._invented(lens) is expected
    labels = {"rests_on_invented": "INVENTED"}
    assert (lenses.rests_on_text(lens, labels) == "INVENTED") is expected


def test_a_shipped_lens_written_from_the_model_s_knowledge_must_link_to_the_work(tmp_path):
    """Paul (2026-11-16): a lens from the model's knowledge still names the original, "so a user has the option to read
    further into it". The strict check for shipped lenses refuses it without a link; the invented demo lenses, which
    are never shipped as real, are not held to it."""
    lens = put(demo_lens(), "originals[0].level", "reference_confirmed")
    lens = put(lens, "originals[0].reference", "Smith, A. (2000). A work.")
    lens = put(lens, "originals[0].link", None)
    path = tmp_path / f"{lens['id']}.json"
    path.write_text(json.dumps(lens), encoding="utf-8")
    real = [p.message for p in lenses.check_lens(path, True, date.today())]
    assert lenses.REFERENCE_LINK in real
    assert lenses.REFERENCE_LINK not in [p.message for p in lenses.check_lens(path, False, date.today())]
    lens = put(lens, "originals[0].link", "https://catalogue.example/work")
    path.write_text(json.dumps(lens), encoding="utf-8")
    assert lenses.REFERENCE_LINK not in [p.message for p in lenses.check_lens(path, True, date.today())]
