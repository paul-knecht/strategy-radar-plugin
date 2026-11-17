"""The lens check: one rule for a lens file, used by `radar check-lenses` and by the gate for every lens an analysis
names (`schema_analysis._lens_problems`).

A lens is a thinking frame in our own words: a JSON object saved as its id plus `.json`, holding exactly the parts in
`KEYS` (and the optional `checked_on`). Every text is filled in and at most 400 characters long, which keeps each text
short; the check measures length only. `real` adds the rules for a lens that ships with the plugin: the day it was
checked, and no illustrative reference; the gate does not apply them, so the invented demo lenses pass there.

`check_lens` and `check_lenses` never raise on a hand-edited file or a folder that cannot be read. Every problem has a
fixed message with its own explanation in `explanations_en.json`, worded for a lens. One message is kept from the
gate's earlier lens check, word for word: `lens must have exactly 3 questions`.

The themes index, `themes.json` in the lens folder, sorts the lenses into themes: `{"themes": [{"name": ..., "lenses":
[lens ids]}]}`. It is not a lens: `lens_files` leaves it out. `check_lenses` checks an index that is there; with `real`
it also requires the index and that every lens is in exactly one theme.
"""
import re
from datetime import date
from pathlib import Path

from . import store
from .fetch import check_url
from .schema import Problem, _filled, _load, _Problems

KEYS = ("id", "name", "idea", "suggests", "limits", "competing_idea", "questions", "originals")
OPTIONAL_KEYS = ("checked_on",)
TEXT_KEYS = ("name", "idea", "suggests", "limits", "competing_idea")
ORIGINAL_KEYS = ("reference", "level", "link", "about")   # `about` is optional: only a secondary-source entry has it
LEVEL_ORDER = ("reference_confirmed", "course_slides", "secondary_source_read", "original_read")   # weakest first
SECONDARY = "secondary_source_read"
MAX_TEXT = 400
QUESTIONS = 3
LENS_ID = re.compile(r"[\w-]+")
LENS_FOLDER = "lenses"   # how a problem names the lens folder, and the start of each lens's name, as the gate names them
_ENDING = ".json"
THEMES_FILE = "themes.json"   # the index of themes in a lens folder: not a lens
THEMES_KEYS = ("themes",)
THEME_KEYS = ("name", "lenses")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_ILLUSTRATIVE = "illustrative"   # compared with a reference's start, after its spaces and in lower case


def is_illustrative(reference) -> bool:
    """True when `reference` is a text that begins with the word Illustrative (after its spaces, in any case): an
    invented work. The one test that the real-use rule, `rests_on_text` and the first stop's lens view all use."""
    return isinstance(reference, str) and reference.strip().lower().startswith(_ILLUSTRATIVE)


# The messages. QUESTION_COUNT is kept from the gate's earlier lens check; every other one is new and has its own entry.
QUESTION_COUNT = "lens must have exactly 3 questions"
NO_LENS_FILES = "no lens files"
ID_FORM = "a lens id may use only letters, digits, hyphens and underscores"
ID_NAME = "a lens id must match the name the lens is saved under"
UNKNOWN_PART = "a lens holds a part that the program does not know"
TEXT_NEEDED = "a lens part must be filled in with text"
TOO_LONG = "a lens text may be at most 400 characters long"
NO_ORIGINALS = "a lens needs at least one original"
ORIGINAL_PARTS = "an original of a lens needs its reference, level and link"
LINK = "a lens link must be none or a web address starting with http or https"
NOT_CHECKED = "a lens for real use must say when it was checked"
CHECKED_ON_FORM = "the day a lens was checked must be written as year, month and day"
CHECKED_ON_FUTURE = "the day a lens was checked lies in the future"
ILLUSTRATIVE_REFERENCE = "a lens for real use may not rest on an illustrative reference"
UNREADABLE = "a lens cannot be read"
LEVEL = "a lens level must be original_read, course_slides, secondary_source_read or reference_confirmed"
ABOUT_NEEDED = "a lens entry read as a source about a work must name that work"
ABOUT_ONLY = "only a lens entry read as a source about a work may name that work"
SECONDARY_LINK = "a lens entry read as a source about a work needs a web address as its link"
REFERENCE_LINK = ("a shipped lens entry at the level reference confirmed needs a web address as its link, to the page "
                  "that confirms the work")
FOLDER_UNREADABLE = "the lens folder cannot be read"
THEMES_MISSING = "the lens folder for real use needs a themes index"
THEMES_UNREADABLE = "the themes index of the lenses cannot be read"
THEMES_UNKNOWN_PART = "the themes index of the lenses holds a part that the program does not know"
THEMES_NOT_A_LIST = "the themes index of the lenses must hold a list of themes"
THEME_PARTS = "a theme of the lenses needs a name and a list of lens ids"
THEME_NAME = "a theme of the lenses needs a name of at most 400 characters"
THEME_LENS_HAS_NO_FILE = "a theme of the lenses names a lens that has no file"
LENS_LISTED_TWICE = "a lens may be listed only once in the themes index"
LENS_NOT_IN_A_THEME = "a lens for real use must be in one theme of the themes index"


def _text(out: _Problems, file: str, value, where: str) -> None:
    """A filled-in text of at most 400 characters."""
    if not _filled(value):
        out.add(file, where, TEXT_NEEDED)
    elif len(value) > MAX_TEXT:
        out.add(file, where, TOO_LONG)


def _is_web_address(value) -> bool:
    """Judged by the form check of the download, as a pack's addresses are."""
    if not isinstance(value, str):
        return False
    try:
        check_url(value)
    except ValueError:   # also what urlsplit raises for a damaged address: the lens check never raises
        return False
    return True


def _day(value) -> date | None:
    """The date in `value` when it is written as YYYY-MM-DD and is a real day, else None."""
    if not _ISO_DATE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _check_id(out: _Problems, file: str, lens: dict, name: str) -> None:
    lens_id = lens.get("id")
    if not (isinstance(lens_id, str) and LENS_ID.fullmatch(lens_id)):
        out.add(file, "id", ID_FORM)
    elif lens_id != name:
        out.add(file, "id", ID_NAME)


def _check_questions(out: _Problems, file: str, lens: dict) -> None:
    questions = lens.get("questions")
    if not (isinstance(questions, list) and len(questions) == QUESTIONS):
        out.add(file, "questions", QUESTION_COUNT)
    for index, question in enumerate(questions if isinstance(questions, list) else []):
        _text(out, file, question, f"questions[{index}]")


def _check_original(out: _Problems, file: str, original, where: str, real: bool) -> None:
    if not isinstance(original, dict):
        out.add(file, where, ORIGINAL_PARTS)
        return
    reference = original.get("reference")
    _text(out, file, reference, where + ".reference")
    if real and is_illustrative(reference):
        out.add(file, where + ".reference", ILLUSTRATIVE_REFERENCE)
    if original.get("level") not in store.LENS_LEVELS:
        out.add(file, where + ".level", LEVEL)
    link = original.get("link", "")
    if link is not None and not _is_web_address(link):
        out.add(file, where + ".link", LINK)
    elif isinstance(link, str) and len(link) > MAX_TEXT:
        out.add(file, where + ".link", TOO_LONG)
    if original.get("level") == SECONDARY:
        if "about" not in original:
            out.add(file, where + ".about", ABOUT_NEEDED)
        if link is None:   # a link that is not a web address was named above; a missing one is named as LINK
            out.add(file, where + ".link", SECONDARY_LINK)
    # A shipped lens written from the model's knowledge (its text was not read) must point the reader to the work.
    # An illustrative reference is refused on its own above, so it is not named twice.
    if real and original.get("level") == "reference_confirmed" and link is None and not is_illustrative(reference):
        out.add(file, where + ".link", REFERENCE_LINK)
    if "about" in original:
        if original.get("level") == SECONDARY:
            _text(out, file, original["about"], where + ".about")
        else:
            out.add(file, where + ".about", ABOUT_ONLY)
    for key in original:
        if key not in ORIGINAL_KEYS:
            out.add(file, f"{where}.{key}", UNKNOWN_PART)


def lens_level(lens: dict) -> str:
    """The level of a lens: the lowest level among its originals, by `LEVEL_ORDER`. A lens never states a higher level
    than the lowest of its originals. Valid only for a lens that passed the lens check (`check_lens`): it reads each
    original's `level` and raises KeyError, TypeError or ValueError for a lens that lacks them or names another."""
    return min((original["level"] for original in lens["originals"]), key=LEVEL_ORDER.index)


_RESTS_ON = {
    "course_slides": "{reference}; lecture slides on the idea were read",
    "reference_confirmed": "{reference}; its text was not read: the lens is written from the model's general knowledge of the work and was not checked against it",
    SECONDARY: "{reference}, a source about {about}, read; the original itself was not read",
}


def _without_full_stop(text) -> str:
    """`text` without the full stop that ends it, so that a reference such as "Smith, A. (2000). A survey." can stand
    in the middle of a sentence."""
    # It may also strip the dot of an abbreviation that ends the text ("... et al."): harmless in the middle of a sentence.
    return str(text).strip().rstrip(".").rstrip()


def rests_on(lens: dict) -> str:
    """What a lens rests on, in plain words. A lens whose originals were all read says so; otherwise the text starts
    with "Rests on: " and says it once, and then says, for each further original that was not read itself, "It also
    rests on ..."; a work that was read adds nothing. A full stop that ends a reference or the name of the work is
    dropped, so the text never holds two.

    Valid only for a lens that passed the lens check (`check_lens`): it reads `originals`, each with its `level` and
    `reference` (and `about` at the fourth level), and raises KeyError or TypeError for a lens that lacks them."""
    sentences = [_RESTS_ON[original["level"]].format(reference=_without_full_stop(original.get("reference")),
                                                     about=_without_full_stop(original.get("about")))
                 for original in lens["originals"] if original["level"] != "original_read"]
    if not sentences:
        return "Rests on: the original, read"
    return "Rests on: " + ". It also rests on ".join(sentences)


def rests_on_text(lens: dict, labels: dict) -> str:
    """What a lens rests on as the first stop and the report word it: `labels["rests_on_invented"]` for a lens with an
    original whose `reference` begins with the word Illustrative (an invented work), otherwise `rests_on`. Valid only
    for a lens that passed the lens check."""
    invented = any(is_illustrative(original.get("reference")) for original in lens["originals"])
    return labels["rests_on_invented"] if invented else rests_on(lens)


def _check_originals(out: _Problems, file: str, lens: dict, real: bool) -> None:
    originals = lens.get("originals")
    if not (isinstance(originals, list) and originals):
        out.add(file, "originals", NO_ORIGINALS)
        return
    for index, original in enumerate(originals):
        _check_original(out, file, original, f"originals[{index}]", real)


def _check_checked_on(out: _Problems, file: str, lens: dict, real: bool, today: date) -> None:
    """Optional. When it is there, a blank or a value that is not text is a day written in the wrong way, with or
    without `real`. With `real` it must be there, a real day and not after `today`; without it, a text is only held to
    the length of every text, so the gate never depends on today's date."""
    if "checked_on" not in lens:
        if real:
            out.add(file, "checked_on", NOT_CHECKED)
        return
    checked_on = lens["checked_on"]
    if not _filled(checked_on):
        out.add(file, "checked_on", CHECKED_ON_FORM)
        return
    if not real:
        _text(out, file, checked_on, "checked_on")
        return
    day = _day(checked_on)
    if day is None:
        out.add(file, "checked_on", CHECKED_ON_FORM)
    elif day > today:
        out.add(file, "checked_on", CHECKED_ON_FUTURE)


def check_lens(path: Path, real: bool, today: date) -> list[Problem]:
    """What is wrong with the lens file at `path`, each problem named `lenses/<file name>` as the gate names it.

    `real` adds the rules for a lens that ships; `today` is the last day `checked_on` may name. Never raises."""
    path = Path(path)
    file = f"{LENS_FOLDER}/{path.name}"
    out = _Problems()
    lens = _load(path)
    if lens is None:   # empty, damaged, not UTF-8, too deep, not one object, locked or a folder
        out.add(file, None, UNREADABLE)
        return out.items
    _check_id(out, file, lens, path.stem)
    for key in TEXT_KEYS:
        _text(out, file, lens.get(key), key)
    _check_questions(out, file, lens)
    _check_originals(out, file, lens, real)
    _check_checked_on(out, file, lens, real, today)
    for key in lens:
        if key not in KEYS and key not in OPTIONAL_KEYS:
            out.add(file, key, UNKNOWN_PART)
    return out.items


def lens_files(lenses_dir: Path) -> list[Path] | None:
    """The lens files of a folder, by their names as the folder lists them: every `.json` name that is a file, except
    the themes index `themes.json`, in the order of the names (other files are left alone). A folder that does not exist holds none. None when the folder
    cannot be listed or a name in it cannot be looked at (this user may list it but not enter it). Never raises."""
    try:
        return sorted((path for path in Path(lenses_dir).iterdir() if path.name.endswith(_ENDING) and path.name != THEMES_FILE
                              and path.is_file()),
                      key=lambda path: path.name)
    except (FileNotFoundError, NotADirectoryError):
        return []
    except OSError:
        return None


def lens_file(files: list[Path], lens_id: str) -> Path | None:
    """The file of the lens `lens_id` among `files`, by its exact name: on a disk that ignores case, a name in another
    case opens a file too, but it is not that lens's name."""
    return next((path for path in files if path.name == lens_id + _ENDING), None)


def folder_unreadable() -> Problem:
    """The one problem of a lens folder that cannot be read, as `check-lenses` and the gate name it."""
    return Problem(LENS_FOLDER, None, FOLDER_UNREADABLE)


def _index_present(path: Path) -> bool:
    """True when something stands at `path` (a name that cannot be looked at counts: reading it then fails)."""
    try:
        return path.exists()
    except OSError:
        return True


def _read_index(lenses_dir: Path) -> tuple[list[tuple[int, dict | None, list[str]]] | None, list[Problem]]:
    """What the themes index holds, and the problems of its form. Each theme that is an object gives (its position in
    the file, the theme as `{"name", "lenses"}` or None when it is badly formed, the lens ids it names that are text).
    None, with no problem, when there is no index; None with a problem when the file cannot be read as one object or
    its `themes` is not a list. Never raises."""
    path = Path(lenses_dir) / THEMES_FILE
    file = f"{LENS_FOLDER}/{THEMES_FILE}"
    if not _index_present(path):
        return None, []
    out = _Problems()
    index = _load(path)
    if index is None:
        out.add(file, None, THEMES_UNREADABLE)
        return None, out.items
    for key in index:
        if key not in THEMES_KEYS:
            out.add(file, key, THEMES_UNKNOWN_PART)
    raw = index.get("themes")
    if not isinstance(raw, list):
        out.add(file, "themes", THEMES_NOT_A_LIST)
        return None, out.items
    rows = []
    for number, theme in enumerate(raw):
        where = f"themes[{number}]"
        if not isinstance(theme, dict):
            out.add(file, where, THEME_PARTS)
            continue
        well_formed = True
        name, ids = theme.get("name"), theme.get("lenses")
        if not (_filled(name) and len(name) <= MAX_TEXT):
            out.add(file, where + ".name", THEME_NAME)
            well_formed = False
        if not isinstance(ids, list):
            out.add(file, where + ".lenses", THEME_PARTS)
            well_formed = False
            ids = []
        for position, lens_id in enumerate(ids):
            if not isinstance(lens_id, str):
                out.add(file, f"{where}.lenses[{position}]", THEME_PARTS)
                well_formed = False
        for key in theme:
            if key not in THEME_KEYS:
                out.add(file, f"{where}.{key}", THEMES_UNKNOWN_PART)
        texts = [lens_id for lens_id in ids if isinstance(lens_id, str)]
        rows.append((number, {"name": name, "lenses": texts} if well_formed else None, texts))
    return rows, out.items


def read_themes(lenses_dir: Path) -> tuple[list[dict] | None, list[Problem]]:
    """The themes index of a lens folder: (the themes as `[{"name": str, "lenses": [str]}]`, the problems of the file).

    The themes are None when there is no index (no problem), and None with a problem when the file cannot be read or
    does not hold a list of themes. A theme that is not written as a name and a list of lens ids is left out and named
    as a problem, so a reader of the themes never meets a badly formed one. Never raises."""
    rows, problems = _read_index(lenses_dir)
    return (None if rows is None else [theme for _, theme, _ in rows if theme is not None]), problems


def check_themes(lenses_dir: Path, real: bool) -> list[Problem]:
    """What is wrong with the themes index of a lens folder. An index that is there is checked: its form, that each
    lens it names has a file and that no lens is listed twice. `real` also requires the index, and that every lens
    file is listed. A folder that cannot be listed is named once, by `check_lenses`, not here. Never raises."""
    files = lens_files(lenses_dir)
    if files is None:
        return []
    rows, problems = _read_index(lenses_dir)
    file = f"{LENS_FOLDER}/{THEMES_FILE}"
    if rows is None:
        return [Problem(file, None, THEMES_MISSING)] if real and not problems else problems
    ids = {path.stem for path in files}
    listed = set()
    for number, _, names in rows:
        for position, lens_id in enumerate(names):
            where = f"themes[{number}].lenses[{position}]"
            if lens_id in listed:
                problems.append(Problem(file, where, LENS_LISTED_TWICE))
            elif lens_id not in ids:
                problems.append(Problem(file, where, THEME_LENS_HAS_NO_FILE))
            listed.add(lens_id)
    if real:
        problems.extend(Problem(f"{LENS_FOLDER}/{path.name}", None, LENS_NOT_IN_A_THEME)
                        for path in files if path.stem not in listed)
    return problems


def check_lenses(lenses_dir: Path, real: bool = False, today: date | None = None) -> list[Problem]:
    """What is wrong with the lenses in a folder (see `lens_files`), then with its themes index (see `check_themes`).
    A folder with no lens file is a problem, and so is a folder that cannot be read. `today` defaults to today. Never
    raises."""
    today = date.today() if today is None else today
    files = lens_files(lenses_dir)
    if files is None:
        return [folder_unreadable()]
    if not files:
        return [Problem(LENS_FOLDER, None, NO_LENS_FILES)]
    problems = []
    for path in files:
        problems.extend(check_lens(path, real, today))
    problems.extend(check_themes(lenses_dir, real))
    return problems
