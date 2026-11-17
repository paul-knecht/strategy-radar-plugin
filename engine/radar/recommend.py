"""The lens recommendation: what the lens advisor suggests at the first stop, checked for its form and recorded by the
program, never written by hand or by a helper.

The advisor reads `advisor_input`: the run's question, the frame of the question, every lens that passes the lens
check (without its limits, its competing idea or its originals) and the facts that count (without their quotes or the
texts of their sources), in parts that each fit its Bash tool (`advisor_parts`). It returns at most four entries, ranked by their place in the list, each
`{"lens", "question_part", "why", "facts", "missing"}`, or none with a note that says why none fits. `record_recommendation`
checks the list by every rule of `check_recommendation`, under the run lock, and writes `lens-recommendation.json` in the
run folder with the facts it saw, each with its status, and the models the helpers were set to use. A list that fails a
rule writes nothing.

The record is advice, not a check: `check-data` looks at its shape only (`shape_problems`) and names a damaged or
unreadable record, and the gate leaves out every problem of this file, so the record never stops a report. A damaged
record is not thrown out: `readable_record` keeps every part that can still be read and says exactly where the rest
sits, for the first stop and for the report. A fact
withdrawn after the recommendation was made never blocks one either; noticing that the record is out of date is the
first stop's job. Every problem has a fixed message with its own explanation in `explanations_en.json`.

The blind readers (`READERS`) each read every link of the recommendation, one lens and one fact at a time, from
`link_packets`: the lens's name, idea, suggestion and three questions, and the fact's statement and status, never the
advisor's reason, the part of the question or what is missing. Each records its own verdict, `bears` or `doubt` with a
note, through `record_link_check`, so a mark never passes through the writer. `marks` says, for every link, how many
readers doubted it and which reader has not read it; a reader that recorded nothing is never counted as agreement.
"""
import os
import re
from datetime import date, datetime
from pathlib import Path

from . import lens_view, lenses, parts, store, verify
from .schema import Problem, _filled, _load, _Problems

RECORD = "lens-recommendation.json"   # in the run folder
MAX_ENTRIES = 4
ADVISOR = "lens-advisor"
READERS = ("lens-link-reader", "lens-link-reader-quick")
MODEL_NAMES = (ADVISOR,) + READERS   # the helpers whose model setting the record keeps
MODELS_FILE = Path(__file__).resolve().parents[2] / "settings" / "models.json"
MAX_TEXT = 400
MAX_LINK_NOTE = 2000   # a link reader's note, as long as a support checker's may be
PART_WORDS_MIN, PART_WORDS_MAX = 2, 15

ENTRY_KEYS = ("lens", "question_part", "why", "facts", "missing")
ENTRY_TEXTS = ("question_part", "why", "missing")
RECORD_KEYS = ("by", "at", "question", "entries", "note", "facts_seen", "models_set_to", "link_checks")
LINK_CHECK_KEYS = ("lens", "fact", "by", "verdict", "note", "at")

TOO_MANY = "a lens recommendation may name at most 4 lenses"
NOTE_NEEDED = "a lens recommendation that names no lens must say in its note why none fits"
ENTRIES_NOT_A_LIST = "the lens recommendation must hold a list of entries"
ENTRY_PARTS = ("an entry of the lens recommendation must hold exactly the lens, the part of the question, why, "
               "the facts and what it lacks")
LENS_NOT_FOUND = "an entry of the lens recommendation names no lens of the lens folder"
LENS_FAILS_CHECK = "an entry of the lens recommendation names a lens that fails the lens check"
LENS_TWICE = "the lens recommendation names a lens twice"
PART_WORDS = "the part of the question in a lens recommendation must have 2 to 15 words"
PART_NOT_IN_QUESTION = "the part of the question in a lens recommendation is not copied word for word from the question"
FACTS_NOT_A_LIST = "the facts of an entry of the lens recommendation must come as a list of fact numbers"
FACT_UNKNOWN = "the lens recommendation names a fact number that the run does not hold"
FACT_TWICE = "an entry of the lens recommendation names the same fact twice"
FACT_DOES_NOT_COUNT = "the lens recommendation names a fact that does not count"
TEXT_NEEDED = "a text of the lens recommendation must be filled in"
TEXT_TOO_LONG = "a text of the lens recommendation may be at most 400 characters long"
NOT_THE_ADVISOR = "only the lens advisor may record the lens recommendation"
REFUSED = "the lens recommendation was refused because it does not pass the form check"
SHAPE_PARTS = "the saved lens recommendation does not hold exactly the parts the program writes"
SHAPE_FORM = "a part of the saved lens recommendation has the wrong form"
LINK_NOTE_TOO_LONG = "a reader's note on a link of the saved lens recommendation may be at most 2,000 characters long"
NOT_A_READER = "only a link reader may record a verdict on a link of the lens recommendation"
NOT_A_LINK = "a link reader named a link that the lens recommendation does not hold"
NO_RECOMMENDATION = "this run holds no lens recommendation that a link reader can record a verdict on"
VERDICT_UNKNOWN = "a link reader's verdict must be that the fact bears on the lens or that it is in doubt"
DOUBT_NEEDS_NOTE = "a link reader that doubts a link must say why in a note"
READER_NOTE_TOO_LONG = "a link reader's note may be at most 2,000 characters long"
VERDICTS = ("bears", "doubt")

_WORD = re.compile(r"\w")


# The plain line form of the list, which the lens advisor sends on standard input so that no curly bracket stands in
# its command: one `key: value` per line, a blank line between entries, and the note on a line of its own.
LINE_KEYS = {"lens": "lens", "part": "question_part", "why": "why", "facts": "facts", "missing": "missing"}
NO_FACTS = "none"


def parse_list_lines(text: str) -> tuple[list[dict], str | None]:
    """The entries and the note of a list in the plain line form, as `record_recommendation` takes them.

    Each line holds one `key: value`, split at the first `: `; a value may not span lines. Entries are separated by
    one or more blank lines; the keys of an entry are exactly `lens`, `part`, `why`, `facts` and `missing`, in any
    order. `facts` holds fact numbers separated by commas, or `none`. An optional `note: ...` stands alone between
    blank lines, anywhere outside an entry. Raises ValueError, with a plain sentence, for a line with no `: `, a key
    that is not known, a key given twice in one entry, an entry that lacks a key, a note inside an entry and a second
    note. Says nothing on what the values hold: the form check does that."""
    blocks, block = [], []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            block.append((number, line))
        elif block:
            blocks.append(block)
            block = []
    if block:
        blocks.append(block)
    entries, note, keys = [], None, ", ".join(LINE_KEYS)
    for block in blocks:
        entry = {}
        for number, line in block:
            key, sep, value = line.partition(": ")
            key, value = key.strip(), value.strip()
            if not sep:
                raise ValueError(f"line {number} of the list has no ': ' after its key. Write each part as key: value "
                                 "on a line of its own.")
            if key == "note":
                if len(block) > 1:
                    raise ValueError(f"line {number} of the list holds the note inside an entry. The note stands on a "
                                     "line of its own, with a blank line between it and each entry.")
                if note is not None:
                    raise ValueError("the note is given twice in the list. Give at most one note line.")
                note = value
                continue
            if key not in LINE_KEYS:
                raise ValueError(f"line {number} of the list names a key that is not known. The keys of an entry are "
                                 f"{keys}; a note stands on a line of its own.")
            if LINE_KEYS[key] in entry:
                raise ValueError(f"line {number} of the list gives {key} a second time in one entry. Leave a blank "
                                 "line between two entries.")
            if key == "facts":
                if not value:
                    raise ValueError(f"line {number} of the list gives no facts. Write the fact numbers separated by "
                                     f"commas, or {NO_FACTS}.")
                value = [] if value == NO_FACTS else [item.strip() for item in value.split(",")]
            entry[LINE_KEYS[key]] = value
        if not entry:
            continue
        for key, name in LINE_KEYS.items():
            if name not in entry:
                raise ValueError(f"entry {len(entries) + 1} of the list has no {key}. Each entry needs {keys}.")
        entries.append({name: entry[name] for name in ENTRY_KEYS})
    return entries, note


class RecommendationRefused(ValueError):
    """The list fails the form check; nothing was written. `problems` names every rule it fails."""

    def __init__(self, problems: list[Problem]):
        super().__init__(REFUSED)
        self.problems = problems


def counts(fact: dict) -> bool:
    """Whether a fact counts: confirmed or uncertain, and not withdrawn. A withdrawn fact never counts, also before the
    next settle rejects it, as the gate says."""
    return fact.get("status") in store.COUNTING and not verify.is_withdrawn(fact)


# --- the form check -------------------------------------------------------------------------------------------------

def _even(text: str) -> str:
    """The text in lower case with every run of white space one space, trimmed: what the question part is compared by."""
    return " ".join(text.split()).lower()


def _is_word(character: str) -> bool:
    return bool(_WORD.fullmatch(character))


def word_count(part: str) -> int:
    """The words of a part: the pieces between white space that hold a letter, a digit or an underscore. A sign that
    stands alone ("-", "?") is not a word."""
    return sum(1 for piece in part.split() if _WORD.search(piece))


def copied_from(part: str, question: str) -> bool:
    """Whether `part` stands in `question`, by `_even` on both sides, starting and ending at word boundaries: a part
    cut inside a word is not copied. Every place the part stands is tried."""
    part, question = _even(part), _even(question)
    if not part:
        return False
    start = question.find(part)
    while start != -1:
        end = start + len(part)
        starts_clean = start == 0 or not (_is_word(question[start - 1]) and _is_word(part[0]))
        ends_clean = end == len(question) or not (_is_word(question[end]) and _is_word(part[-1]))
        if starts_clean and ends_clean:
            return True
        start = question.find(part, start + 1)
    return False


def _text(out: _Problems, field: str, value) -> bool:
    """A filled-in text of at most 400 characters; True when it is one."""
    if not _filled(value):
        out.add(RECORD, field, TEXT_NEEDED)
        return False
    if len(value) > MAX_TEXT:
        out.add(RECORD, field, TEXT_TOO_LONG)
        return False
    return True


def _check_lens(out: _Problems, field: str, lens_id, files: list | None, today: date) -> None:
    if files is None:   # the folder cannot be listed: named once, by the caller
        return
    path = lenses.lens_file(files, lens_id) if isinstance(lens_id, str) else None
    if path is None:
        out.add(RECORD, field, LENS_NOT_FOUND)
    elif lenses.check_lens(path, False, today):
        out.add(RECORD, field, LENS_FAILS_CHECK)


def _check_facts(out: _Problems, field: str, fact_ids, facts: dict[str, dict]) -> None:
    if not isinstance(fact_ids, list):
        out.add(RECORD, field, FACTS_NOT_A_LIST)
        return
    named = set()
    for index, fact_id in enumerate(fact_ids):
        fact = facts.get(fact_id) if isinstance(fact_id, str) else None
        if fact is not None and fact_id in named:
            out.add(RECORD, f"{field}[{index}]", FACT_TWICE)
            continue
        if fact is not None:
            named.add(fact_id)
        if fact is None:
            out.add(RECORD, f"{field}[{index}]", FACT_UNKNOWN)
        elif not counts(fact):
            out.add(RECORD, f"{field}[{index}]", FACT_DOES_NOT_COUNT)


def _check_entry(out: _Problems, index: int, entry, question: str, facts: dict[str, dict], files: list | None,
                 seen: set, today: date) -> None:
    where = f"entries[{index}]"
    if not isinstance(entry, dict):
        out.add(RECORD, where, ENTRY_PARTS)
        return
    if set(entry) != set(ENTRY_KEYS):
        out.add(RECORD, where, ENTRY_PARTS)
    if "lens" in entry:
        lens_id = entry["lens"]
        if isinstance(lens_id, str) and lens_id in seen:
            out.add(RECORD, where + ".lens", LENS_TWICE)
        else:
            _check_lens(out, where + ".lens", lens_id, files, today)
            if isinstance(lens_id, str):
                seen.add(lens_id)
    if "question_part" in entry and _text(out, where + ".question_part", entry["question_part"]):
        part = entry["question_part"]
        if not PART_WORDS_MIN <= word_count(part) <= PART_WORDS_MAX:
            out.add(RECORD, where + ".question_part", PART_WORDS)
        elif not copied_from(part, question):
            out.add(RECORD, where + ".question_part", PART_NOT_IN_QUESTION)
    if "why" in entry:
        _text(out, where + ".why", entry["why"])
    if "facts" in entry:
        _check_facts(out, where + ".facts", entry["facts"], facts)
    if "missing" in entry:
        _text(out, where + ".missing", entry["missing"])


def _problems(run_dir: Path, lenses_dir: Path, entries, note, facts: dict[str, dict]) -> list[Problem]:
    out = _Problems()
    question = store.load_run(run_dir).get("question")
    question = question if isinstance(question, str) else ""
    listed = isinstance(entries, list)
    if not listed:
        out.add(RECORD, "entries", ENTRIES_NOT_A_LIST)
        entries = []
    elif len(entries) > MAX_ENTRIES:
        out.add(RECORD, "entries", TOO_MANY)
    if listed and not entries and not _filled(note):
        out.add(RECORD, "note", NOTE_NEEDED)
    elif note is not None:
        _text(out, "note", note)
    files = lenses.lens_files(lenses_dir)
    if files is None and entries:
        out.add(lenses.LENS_FOLDER, None, lenses.FOLDER_UNREADABLE)
    seen, today = set(), date.today()
    for index, entry in enumerate(entries):
        _check_entry(out, index, entry, question, facts, files, seen, today)
    return out.items


def check_recommendation(run_dir: Path, lenses_dir: Path, entries, note) -> list[Problem]:
    """Every rule the list fails, each problem named `lens-recommendation.json` with the entry and part it is about.
    Takes no lock: `record_recommendation` holds it around the same check. Never raises on odd input."""
    run_dir = Path(run_dir)
    return _problems(run_dir, Path(lenses_dir), entries, note, store.read_facts(run_dir))


# --- the record -----------------------------------------------------------------------------------------------------

def _models_set_to() -> dict:
    """The model each helper of the recommendation is set to use in `settings/models.json`, or None for a name that
    is not set to a text there, and for every name when the file cannot be read."""
    try:
        settings = store._read_json(MODELS_FILE)
    except (OSError, ValueError):
        settings = None
    settings = settings if isinstance(settings, dict) else {}
    return {name: settings[name] if isinstance(settings.get(name), str) else None for name in MODEL_NAMES}


def record_recommendation(run_dir: Path, lenses_dir: Path, entries, note, by: str,
                          now: datetime | None = None) -> None:
    """Check the list and write the run's recommendation record, replacing any earlier one (and its link checks).

    Refused, before anything is written: a `by` that is not the lens advisor (ValueError, NOT_THE_ADVISOR) and a list
    that fails the form check (RecommendationRefused, a ValueError, with every problem). Holds the run lock from reading
    the facts to writing the record, so a fact withdrawn in parallel is either seen or not, never half."""
    if by != ADVISOR:
        raise ValueError(NOT_THE_ADVISOR)
    run_dir = Path(run_dir)
    with verify._run_lock(run_dir):
        facts = store.read_facts(run_dir)
        problems = _problems(run_dir, Path(lenses_dir), entries, note, facts)
        if problems:
            raise RecommendationRefused(problems)
        record = {"by": by, "at": store._stamp(now), "question": store.load_run(run_dir).get("question"),
                  "entries": entries, "note": note,
                  "facts_seen": {fact_id: fact["status"] for fact_id, fact in facts.items() if counts(fact)},
                  "models_set_to": _models_set_to(), "link_checks": []}
        store._write_json(run_dir / RECORD, record)


def read_record(run_dir: Path) -> dict | None:
    """The run's recommendation record, or None when there is none or it cannot be read as one object."""
    return _load(Path(run_dir) / RECORD)


# --- the shape check of check-data -----------------------------------------------------------------------------------

def _exact_keys(out: _Problems, field: str, value: dict, keys: tuple) -> None:
    if set(value) != set(keys):
        out.add(RECORD, field, SHAPE_PARTS)


def _shape_text(out: _Problems, field: str, value) -> None:
    if not isinstance(value, str):
        out.add(RECORD, field, SHAPE_FORM)
    elif not value.strip():
        out.add(RECORD, field, TEXT_NEEDED)
    elif len(value) > MAX_TEXT:
        out.add(RECORD, field, TEXT_TOO_LONG)


def _shape_entry(out: _Problems, where: str, entry) -> None:
    if not isinstance(entry, dict):
        out.add(RECORD, where, SHAPE_FORM)
        return
    _exact_keys(out, where, entry, ENTRY_KEYS)
    if "lens" in entry and not isinstance(entry["lens"], str):
        out.add(RECORD, where + ".lens", SHAPE_FORM)
    for key in ENTRY_TEXTS:
        if key in entry:
            _shape_text(out, f"{where}.{key}", entry[key])
    if "facts" in entry and not (isinstance(entry["facts"], list)
                                 and all(isinstance(fact_id, str) for fact_id in entry["facts"])):
        out.add(RECORD, where + ".facts", SHAPE_FORM)


def _shape_link_check(out: _Problems, where: str, check) -> None:
    if not isinstance(check, dict):
        out.add(RECORD, where, SHAPE_FORM)
        return
    _exact_keys(out, where, check, LINK_CHECK_KEYS)
    for key in LINK_CHECK_KEYS:
        if key in check and not isinstance(check[key], str):
            out.add(RECORD, f"{where}.{key}", SHAPE_FORM)
        elif key == "note" and key in check and len(check[key]) > MAX_LINK_NOTE:   # may be empty: a reader that agrees
            out.add(RECORD, where + ".note", LINK_NOTE_TOO_LONG)
        elif (key == "verdict" and key in check and check[key] not in VERDICTS) \
                or (key == "by" and key in check and check[key] not in READERS):
            out.add(RECORD, f"{where}.{key}", SHAPE_FORM)


def shape_problems(record) -> list[Problem]:
    """What is wrong with the form of a saved recommendation record: its keys, the type of each part and the length of
    each text, and the same for each entry and each link check. Never the facts, the lenses or the question it names:
    the record is advice, and what changed since it was made never blocks a report. Never raises."""
    out = _Problems()
    if not isinstance(record, dict):
        out.add(RECORD, None, SHAPE_FORM)
        return out.items
    for key in record:
        if key not in RECORD_KEYS:
            out.add(RECORD, str(key), SHAPE_PARTS)
    for key in RECORD_KEYS:
        if key not in record:
            out.add(RECORD, key, SHAPE_PARTS)
    for key in ("by", "at", "question"):
        if key in record and not isinstance(record[key], str):
            out.add(RECORD, key, SHAPE_FORM)
    if "entries" in record:
        if isinstance(record["entries"], list):
            for index, entry in enumerate(record["entries"]):
                _shape_entry(out, f"entries[{index}]", entry)
        else:
            out.add(RECORD, "entries", SHAPE_FORM)
    if "note" in record and record["note"] is not None:
        _shape_text(out, "note", record["note"])
    elif record.get("entries") == []:   # the program never writes an empty list without a note that says why
        out.add(RECORD, "note", NOTE_NEEDED)
    seen = record.get("facts_seen")
    if "facts_seen" in record and not (isinstance(seen, dict) and all(isinstance(status, str)
                                                                      for status in seen.values())):
        out.add(RECORD, "facts_seen", SHAPE_FORM)
    models = record.get("models_set_to")
    if "models_set_to" in record:
        if not isinstance(models, dict):
            out.add(RECORD, "models_set_to", SHAPE_FORM)
        else:
            _exact_keys(out, "models_set_to", models, MODEL_NAMES)
            if not all(value is None or isinstance(value, str) for value in models.values()):
                out.add(RECORD, "models_set_to", SHAPE_FORM)
    if "link_checks" in record:
        if isinstance(record["link_checks"], list):
            for index, check in enumerate(record["link_checks"]):
                _shape_link_check(out, f"link_checks[{index}]", check)
        else:
            out.add(RECORD, "link_checks", SHAPE_FORM)
    return out.items


# --- what can still be shown of a damaged record (Paul's decision 18: keep it, and flag exactly where) ---------------

_PLACE = re.compile(r"(entries|link_checks)\[(\d+)\](?:\.(\w+))?")
RECORD_PARTS = ("by", "at", "question", "note", "facts_seen", "models_set_to", "entries", "link_checks")


def _places(problems: list[Problem], extra_keys: set) -> tuple[set, dict, dict]:
    """Where each shape problem sits: the record's own parts (a key of `RECORD_KEYS`, or "extra" for a key the program
    does not write), and for each entry and each link check by its index, the parts named (None for the whole). A
    key the program does not write is "extra" whatever its name, even one that looks like a place in a list."""
    top, entries, checks = set(), {}, {}
    for problem in problems:
        if problem.field in extra_keys:
            top.add("extra")
            continue
        place = _PLACE.fullmatch(problem.field or "")
        if place:
            kind, index, part = place.groups()
            (entries if kind == "entries" else checks).setdefault(int(index), set()).add(part)
        else:
            top.add(problem.field if problem.field in RECORD_KEYS else "extra")
    return top, entries, checks


def _shown_text(value) -> str | None:
    """A text as it can be shown: None when it is not a text, or is empty, so that nothing blank is printed (its flag
    says why it is not shown)."""
    return value if isinstance(value, str) and value.strip() else None


def _clean_entry(entry, parts: set) -> dict | None:
    """One entry as it can still be shown, with `damage`: `[{"part", "readable"}]`, one item for each damaged part,
    `readable` false when the part is not a text (or not a list, for the facts) and so cannot be shown; an empty
    text is readable but not shown (None). None when the
    entry is not an object or names no lens that can be read: then nothing of it can be shown."""
    if not isinstance(entry, dict) or not isinstance(entry.get("lens"), str):
        return None
    damage = []
    if None in parts and any(key not in ENTRY_KEYS for key in entry):
        damage.append({"part": "extra", "readable": False})
    cleaned = {"lens": entry["lens"]}
    for part in ENTRY_KEYS[1:]:   # in the order the program writes them
        value = entry.get(part)
        if part == "facts":
            cleaned[part] = [fact_id for fact_id in value if isinstance(fact_id, str)] if isinstance(value, list) else []
            readable = isinstance(value, list)   # its fact numbers are shown; anything else in it is not
        else:
            cleaned[part] = _shown_text(value)
            readable = isinstance(value, str)
        if part in parts or part not in entry:
            damage.append({"part": part, "readable": readable})
    return {**cleaned, "damage": damage}


def readable_record(run_dir: Path) -> tuple[dict | None, list[dict], bool]:
    """`(record, damage, damaged)`: what the first stop's view and the report show of the run's recommendation. The
    one reading of the record that both use.

    `damaged` is true when a record file is there whose form is wrong (`shape_problems`) or that cannot be read at
    all. A damaged record is not thrown out: every part that can still be read is kept, and `damage` says exactly
    where the rest sits. `record` is None when there is no record file, or when nothing of it can be shown (it cannot
    be read as one object, or it holds no entry and no note that can be read); else it always has every key of
    `RECORD_KEYS`, with a part that cannot be read set to None (`facts_seen`), {} (`models_set_to`) or [] (`entries`,
    `link_checks`). Each entry is `{"lens", "question_part", "why", "facts", "missing", "damage"}` (see `_clean_entry`);
    only the link checks of the form the readers write are kept.

    `damage` holds the record's own damaged parts as `{"part", "readable"}` (part "extra" for a key the program does
    not write), each entry that cannot be read at all as `{"entry": <its place in the list, from 1>}`, and each link
    check that cannot be read as `{"verdict": "<lens>/<fact>"}` (with `"by"` when it names one of `READERS`, and
    `"held": False` when the list holds no such
    link, so that it is said on the record and not next to a link), or `{"verdict": None}` when not even its link can
    be read. Never raises."""
    run_dir = Path(run_dir)
    raw = read_record(run_dir)
    if raw is None:
        return None, [], os.path.lexists(run_dir / RECORD)
    problems = shape_problems(raw)
    if not isinstance(raw, dict):
        return None, [], True
    top, entry_places, check_places = _places(problems, {str(key) for key in raw if key not in RECORD_KEYS})
    damage = [{"part": "extra", "readable": False}] if "extra" in top else []
    cleaned = {}
    for part in ("by", "at", "question", "note"):
        value = raw.get(part)
        cleaned[part] = _shown_text(value)
        if part in top or part not in raw:
            damage.append({"part": part, "readable": isinstance(value, str)})
    seen = raw.get("facts_seen")
    cleaned["facts_seen"] = None if "facts_seen" in top else seen
    models = raw.get("models_set_to")
    cleaned["models_set_to"] = {name: value for name, value in models.items()
                                if name in MODEL_NAMES and (value is None or isinstance(value, str))} \
        if isinstance(models, dict) else {}
    for part in ("facts_seen", "models_set_to"):
        if part in top:
            damage.append({"part": part, "readable": False})
    entries = raw.get("entries")
    cleaned["entries"] = []
    if isinstance(entries, list):
        for index, entry in enumerate(entries):
            kept = _clean_entry(entry, entry_places.get(index, set()))
            if kept is None:
                damage.append({"entry": index + 1})
            else:
                cleaned["entries"].append(kept)
    if "entries" in top:
        damage.append({"part": "entries", "readable": False})
    checks = raw.get("link_checks")
    cleaned["link_checks"] = []
    for index, check in enumerate(checks if isinstance(checks, list) else []):
        if index not in check_places:
            cleaned["link_checks"].append(check)
        elif isinstance(check, dict) and isinstance(check.get("lens"), str) and isinstance(check.get("fact"), str):
            item = {"verdict": f"{check['lens']}/{check['fact']}"}
            if check.get("by") in READERS:
                item["by"] = check["by"]   # this reader recorded something: it is not said to have recorded nothing
            damage.append(item)
        else:
            damage.append({"verdict": None})
    if "link_checks" in top:
        damage.append({"part": "link_checks", "readable": False})
    held = {f"{lens_id}/{fact_id}" for lens_id, fact_id in _links(cleaned)}
    for item in damage:   # a verdict on a link the list does not hold is never said next to a link, so say it here
        if item.get("verdict") and item["verdict"] not in held:
            item["held"] = False
    if not cleaned["entries"] and cleaned["note"] is None:
        return None, damage, True
    return cleaned, damage, bool(problems)


def damage_sentences(damage: list[dict], labels: dict[str, str]) -> list[str]:
    """Each damaged place, in plain words from the report's labels: a part of the record or of an entry (by its
    plain name), an entry that cannot be read, a reader's verdict that cannot be read. The verdicts on a link that
    the list holds are said next to that link (`marks`), not here."""
    sentences = []
    for item in damage:
        if "entry" in item:
            sentences.append(labels["rec_flag_entry"].format(n=item["entry"]))
        elif "verdict" in item:
            if item["verdict"] is None:
                sentences.append(labels["rec_flag_verdict"])
            elif item.get("held") is False:
                sentences.append(labels["rec_flag_verdict_elsewhere"])
        elif item["part"] == "extra":
            sentences.append(labels["rec_flag_extra"])
        elif item["part"] == "facts_seen":
            sentences.append(labels["rec_flag_stale_unknown"])
        else:
            part = labels["rec_partname_" + item["part"]]
            sentences.append(labels["rec_flag_changed" if item["readable"] else "rec_flag_unreadable"].format(part=part))
    return sentences


def is_stale(run_dir: Path, record: dict) -> bool:
    """Whether the facts that count now, with their statuses, are not the facts a readable `record` saw: the
    recommendation was made for other facts. The one comparison that the first stop's view and the report use. False
    when what the record saw cannot be read (`facts_seen` is None): that is said as damage, never guessed."""
    if record.get("facts_seen") is None:
        return False
    counting = {fact_id: fact.get("status") for fact_id, fact in store.read_facts(Path(run_dir)).items() if counts(fact)}
    return counting != record["facts_seen"]


# --- what the advisor reads -------------------------------------------------------------------------------------------

def _frame(run_dir: Path) -> str | None:
    try:
        return (run_dir / "notes" / "frame.md").read_text(encoding="utf-8")
    except (OSError, ValueError):   # not there, a folder, locked or not UTF-8 text
        return None


def _advisor_lenses(lenses_dir: Path) -> list[dict]:
    """Every lens that passes the lens check, in the order `list_lenses` shows them, with its theme (None for a lens
    in no theme) and its level in plain words. Raises `lens_view.LensFolderUnreadable` for a folder that cannot be
    listed."""
    listing = lens_view.list_lenses(lenses_dir)
    shown = [(entry, theme["name"]) for theme in listing["themes"] for entry in theme["lenses"]]
    shown += [(entry, None) for entry in listing["not_yet_sorted"]]
    files = lenses.lens_files(lenses_dir) or []
    result = []
    for entry, theme in shown:
        path = lenses.lens_file(files, entry["id"])
        lens = _load(path) if path is not None and not lenses.check_lens(path, False, date.today()) else None
        if lens is None:   # changed or removed since it was listed
            continue
        result.append({"id": lens["id"], "name": lens["name"], "idea": lens["idea"], "suggests": lens["suggests"],
                       "questions": lens["questions"], "level": entry["level"], "theme": theme})
    return result


def advisor_input(run_dir: Path, lenses_dir: Path) -> dict:
    """What the lens advisor reads: `{"question", "frame", "lenses", "facts"}`. `frame` is the text of
    `notes/frame.md`, or None. A lens is `{"id", "name", "idea", "suggests", "questions", "level", "theme"}`, for every
    lens that passes the lens check; a fact is `{"id", "statement", "status", "publisher", "early_signal"}`, for every
    fact that counts. No quote, no source text, no limits, no competing idea and no originals. Changes nothing."""
    run_dir = Path(run_dir)
    sources = store.read_sources(run_dir)
    facts = []
    for fact_id, fact in store.read_facts(run_dir).items():
        if not counts(fact):
            continue
        source = sources.get(verify.text_id(fact.get("source_id"))) or {}
        facts.append({"id": fact_id, "statement": fact.get("statement"), "status": fact.get("status"),
                      "publisher": source.get("publisher"), "early_signal": verify.is_early_signal(fact, sources)})
    return {"question": store.load_run(run_dir).get("question"), "frame": _frame(run_dir),
            "lenses": _advisor_lenses(Path(lenses_dir)), "facts": facts}


def advisor_parts(run_dir: Path, lenses_dir: Path) -> list[dict]:
    """`advisor_input` in parts that each print shorter than `parts.PART_LIMIT`: the question and the frame on the first
    part only, then every lens before the first fact. Changes nothing."""
    return parts.split_input(advisor_input(run_dir, lenses_dir), ("lenses", "facts"))


# --- the blind readers ------------------------------------------------------------------------------------------------

def _entries(record) -> list[dict]:
    """The entries of a record that can be read as one: every entry that is an object with a lens name and a list of
    facts. Anything else in a hand-edited record is left out, never raised on."""
    entries = record.get("entries") if isinstance(record, dict) else None
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict) and isinstance(entry.get("lens"), str)
            and isinstance(entry.get("facts"), list)]


def _links(record) -> list[tuple[str, str]]:
    """Every link of the record, a lens with one of its facts, in the order of the entries and of their facts; each
    once. An entry with no facts has no link."""
    links = []
    for entry in _entries(record):
        for fact_id in entry["facts"]:
            if isinstance(fact_id, str) and (entry["lens"], fact_id) not in links:
                links.append((entry["lens"], fact_id))
    return links


def link_packets(run_dir: Path, lenses_dir: Path) -> list[dict]:
    """What the link readers read: one packet for every link of the recorded recommendation, in the order of the
    entries and of their facts: `{"lens", "lens_name", "idea", "suggests", "questions", "fact", "statement",
    "status"}`. Nothing of the advisor's reason, the part of the question or what is missing. A link whose lens no
    longer passes the lens check, or whose fact the run no longer holds, has no packet. No packet when there is no
    readable recommendation. Raises `lens_view.LensFolderUnreadable` for a folder that cannot be listed. Changes
    nothing and takes no lock."""
    run_dir = Path(run_dir)
    files = lenses.lens_files(Path(lenses_dir))
    if files is None:
        raise lens_view.LensFolderUnreadable(lenses.FOLDER_UNREADABLE)
    links = _links(read_record(run_dir))
    if not links:
        return []
    facts, loaded, today, packets = store.read_facts(run_dir), {}, date.today(), []
    for lens_id, fact_id in links:
        if lens_id not in loaded:
            path = lenses.lens_file(files, lens_id)
            loaded[lens_id] = _load(path) if path is not None and not lenses.check_lens(path, False, today) else None
        lens, fact = loaded[lens_id], facts.get(fact_id)
        if lens is None or fact is None:
            continue
        packets.append({"lens": lens_id, "lens_name": lens["name"], "idea": lens["idea"], "suggests": lens["suggests"],
                        "questions": lens["questions"], "fact": fact_id, "statement": fact.get("statement"),
                        "status": fact.get("status")})
    return packets


def record_link_check(run_dir: Path, lens: str, fact: str, verdict: str, by: str, note: str,
                      now: datetime | None = None) -> None:
    """Record one link reader's verdict on one link of the recorded recommendation. Holds the run lock.

    The same reader recording the same link again replaces its earlier verdict; the other reader's is kept. Refused
    (ValueError), before anything is written: a `by` that is not one of `READERS`, a verdict that is not `bears` or
    `doubt`, a `doubt` with no note, a note over 2,000 characters, a run with no readable recommendation, and a link
    (lens and fact) that the recommendation does not hold. A note on `bears` may be empty."""
    if by not in READERS:
        raise ValueError(NOT_A_READER)
    if verdict not in VERDICTS:
        raise ValueError(VERDICT_UNKNOWN)
    if verdict == "doubt" and not (isinstance(note, str) and note.strip()):
        raise ValueError(DOUBT_NEEDS_NOTE)
    note = note if isinstance(note, str) else ""
    if len(note) > MAX_LINK_NOTE:
        raise ValueError(READER_NOTE_TOO_LONG)
    run_dir = Path(run_dir)
    with verify._run_lock(run_dir):
        record = read_record(run_dir)
        if not isinstance(record, dict) or not isinstance(record.get("entries"), list) \
                or not isinstance(record.get("link_checks"), list):
            raise ValueError(NO_RECOMMENDATION)
        if not (isinstance(lens, str) and isinstance(fact, str) and (lens, fact) in _links(record)):
            raise ValueError(NOT_A_LINK)
        checks = [check for check in record["link_checks"]
                  if not (isinstance(check, dict) and (check.get("lens"), check.get("fact"), check.get("by"))
                          == (lens, fact, by))]
        checks.append({"lens": lens, "fact": fact, "by": by, "verdict": verdict, "note": note,
                       "at": store._stamp(now)})
        record["link_checks"] = checks
        store._write_json(run_dir / RECORD, record)


def marks(run_dir: Path) -> dict[str, dict]:
    """What the readers said about every link of the recorded recommendation, one key `"<lens>/<fact>"` for each,
    always in one shape: `{"doubts": int, "read_by": [readers], "unread_by": [readers], "verdicts": [{"reader",
    "verdict", "note"}], "unreadable": int}`, the readers in the order of `READERS`. A link has a mark when `doubts` is
    above 0. A reader that recorded nothing is in `unread_by`, never counted as agreement. A verdict for a link the
    record does not hold is left out; one in a form the readers do not write (a stranger's, too) is left out and
    counted in `unreadable` of its link, so that it is said where it stands, and a reader whose verdict it was is then
    not in `unread_by`: it recorded something, which cannot be read. When a hand-edited record holds two
    verdicts of one reader on one link, the later counts. {} when nothing of the recommendation can be read
    (`readable_record`)."""
    record, damage, _ = readable_record(run_dir)
    if record is None:
        return {}
    given = {}
    for check in record["link_checks"]:
        given[(check["lens"], check["fact"], check["by"])] = check
    unreadable, unreadable_by = {}, set()
    for item in damage:
        if item.get("verdict"):
            unreadable[item["verdict"]] = unreadable.get(item["verdict"], 0) + 1
            if item.get("by"):
                unreadable_by.add((item["verdict"], item["by"]))
    result = {}
    for lens_id, fact_id in _links(record):
        verdicts = [{"reader": reader, "verdict": given[(lens_id, fact_id, reader)]["verdict"],
                     "note": given[(lens_id, fact_id, reader)]["note"]}
                    for reader in READERS if (lens_id, fact_id, reader) in given]
        read_by = [verdict["reader"] for verdict in verdicts]
        result[f"{lens_id}/{fact_id}"] = {
            "doubts": sum(1 for verdict in verdicts if verdict["verdict"] == "doubt"), "read_by": read_by,
            "unread_by": [reader for reader in READERS if reader not in read_by
                          and (f"{lens_id}/{fact_id}", reader) not in unreadable_by], "verdicts": verdicts,
            "unreadable": unreadable.get(f"{lens_id}/{fact_id}", 0)}
    return result
