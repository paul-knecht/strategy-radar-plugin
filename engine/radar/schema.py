"""The data check: validate run.json, every source, every fact and analysis.json.

`check_data` never raises on a broken run folder. Every empty or unreadable file of the run becomes one
Problem with the message "not valid JSON", except a file this user may not open, which is named so. Problems come in a stable order: run.json, sources by
id number, facts by id number, analysis.json (then any lens files it names, judged by `lenses.check_lens` with messages
of its own), then the lens recommendation, by its form only (`recommend.shape_problems`; a run without one is fine, and the gate leaves out every problem of that file), and last the grouping into projects, by its form only (`projects.shape_problems`; the same holds).
The checks of analysis.json live in `schema_analysis.py`; `check_data` stays the single entry point.
"""
import os
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from . import calc, store
from .fetch import check_url
from .textnorm import quote_units
from .verify import is_early_signal

SAVED_BY = ("program", "hand")
SOURCE_ACCESS = ("ok", "not_accessible")
FACT_KINDS = ("capacity_move", "general")
# Every key a fact may hold: what a proposal brings, and what the program adds (id, checks, status, its reason, the codes for why a fact is uncertain, withdrawal).
FACT_KEYS = ("id", "kind", "statement", "quote", "quote_language", "quote_translation", "source_id", "supporting",
             "primary_source", "certainty", "tentative_reason", "early_signal", "fields", "about_company",
             "connections", "checks", "status", "status_reason", "uncertain_reasons", "withdrawn")
COMPANY_KEYS = ("name", "other_names", "home")   # a company the run lists, from its pack
SUPPORTING_KEYS = ("source_id", "quote", "quote_translation")
CONNECTION_KEYS = ("party", "tie", "description")   # a customer, buyer, seller or partner a fact names
PROGRAM_KEYS = ("id", "checks", "status", "status_reason", "uncertain_reasons", "withdrawn")   # set by the program, never by a proposal
CAPACITY_MOVE_FIELDS = ("company", "move_type", "site", "country", "what_added", "size_value", "size_unit",
                        "announced", "planned_start", "stage", "access", "delivery", "in_question")

EMPTY = "must not be empty"
NOT_ALLOWED = "not an allowed value"
NOT_JSON = "not valid JSON"
NOT_OPENED = "run.json may not be opened"   # the record is there; only this user may not read it
LOCKED = "may not be opened by this user"   # the same for a source, a fact, the analysis or a saved copy

AT_LEAST_ONE = "must have at least one entry"
SCENARIO_COUNT = "use no scenarios or between two and four"
NOT_A_DATE = "must be a date like 2027-12-31"
NOT_A_PROBABILITY = "must be a whole number from 1 to 99"
GROUPED_NUMBER = "write the number without thousands separators"
DEMO_MARK_PROBLEM = "the practice-run mark is only allowed on the invented private practice run"
SIZE_AS_TEXT = 'write the size as text, such as "2.5"'
MUST_BE_TEXT = "must be text"
TWO_OWN_COMPANIES = "at most one company of a run is its own company"
NOTE_ON_A_WEB_PAGE_ONLY = "only a saved web page can have the note little_running_text"
ABOUT_ON_A_MOVE = "a capacity move names its company in fields.company"
UNNAMED_PARTY = "a connection that names no party must describe it"   # stored facts only; a proposal gets the next one
IN_QUESTION_MISSING = "in_question is missing; it must be yes or no, set by the extractor"
UNNAMED_PROPOSED_PARTY = "a connection names its other party; leave out a tie whose party the source does not name"


@dataclass(frozen=True)
class Problem:
    file: str            # relative to the run folder
    field: str | None
    message: str


def _filled(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _load(path: Path):
    """The parsed JSON object in `path`, or None if it is empty, unreadable or not an object."""
    try:
        data = store._read_json(path)
    except (ValueError, OSError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def _may_not_be_opened(path: Path) -> bool:
    """True when `path` is there but this user may not open it for reading: not damaged, only locked."""
    try:
        with open(path, "rb"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


class _Problems:
    """Collects problems for one file at a time."""

    def __init__(self) -> None:
        self.items: list[Problem] = []

    def add(self, file: str, field: str | None, message: str) -> None:
        self.items.append(Problem(file, field, message))

    def nonempty(self, file: str, record: dict, field: str, prefix: str = "") -> None:
        if not _filled(record.get(field)):
            self.add(file, prefix + field, EMPTY)

    def allowed(self, file: str, record: dict, field: str, values: tuple, prefix: str = "") -> None:
        value = record.get(field)
        if not (isinstance(value, str) and value in values):
            self.add(file, prefix + field, NOT_ALLOWED)


def _check_companies(out: _Problems, run: dict) -> None:
    """The companies of a run, as `init-run` records them from the pack. A run made before the key existed has none."""
    if "companies" not in run:
        return
    companies = run["companies"]
    if not isinstance(companies, list):
        out.add("run.json", "companies", NOT_ALLOWED)
        return
    homes = 0
    for index, company in enumerate(companies):
        prefix = f"companies[{index}]"
        if not isinstance(company, dict):
            out.add("run.json", prefix, NOT_ALLOWED)
            continue
        for key in company:
            if key not in COMPANY_KEYS:
                out.add("run.json", f"{prefix}.{key}", NOT_ALLOWED)
        out.nonempty("run.json", company, "name", f"{prefix}.")
        names = company.get("other_names")
        if not isinstance(names, list):
            out.add("run.json", f"{prefix}.other_names", NOT_ALLOWED)
        else:
            for place, name in enumerate(names):
                if not _filled(name):
                    out.add("run.json", f"{prefix}.other_names[{place}]", EMPTY)
        if not isinstance(company.get("home"), bool):
            out.add("run.json", f"{prefix}.home", NOT_ALLOWED)
        elif company["home"]:
            homes += 1
    if homes > 1:
        out.add("run.json", "companies", TWO_OWN_COMPANIES)


# --- run.json --------------------------------------------------------------

def _check_run(out: _Problems, run_dir: Path) -> dict | None:
    path = run_dir / "run.json"
    if not path.exists():
        out.add("run.json", None, "run.json is missing")
        return None
    run = _load(path)
    if run is None:
        out.add("run.json", None, NOT_OPENED if _may_not_be_opened(path) else NOT_JSON)
        return None
    for field in ("question", "pack", "run_id"):
        out.nonempty("run.json", run, field)
    if run.get("language") != "en":
        out.add("run.json", "language", NOT_ALLOWED)
    out.allowed("run.json", run, "mode", store.RUN_MODES)
    if run.get("mode") == "private":
        out.nonempty("run.json", run, "private_acknowledged_at")
        out.nonempty("run.json", run, "private_acknowledged_words")
        if not store.keeps_out_of_git(run_dir):
            out.add(".gitignore", None, store.PRIVATE_NOT_IGNORED)
    if store.DEMO_MARK in run and not (run[store.DEMO_MARK] == store.DEMO_MARK_VALUE
                                       and run.get("mode") == "private" and run.get("illustrative") is True):
        out.add("run.json", store.DEMO_MARK, DEMO_MARK_PROBLEM)
    for key in store.RUN_RECORD_LISTS:   # every run record has them, each a list
        if not isinstance(run.get(key), list):
            out.add("run.json", key, NOT_ALLOWED)
    _check_companies(out, run)
    checkpoints = run.get("checkpoints")
    for index, checkpoint in enumerate(checkpoints if isinstance(checkpoints, list) else []):
        prefix = f"checkpoints[{index}]."
        if not isinstance(checkpoint, dict):
            out.add("run.json", f"checkpoints[{index}]", NOT_ALLOWED)
            continue
        out.allowed("run.json", checkpoint, "name", store.CHECKPOINTS, prefix)
        out.allowed("run.json", checkpoint, "answered_by", store.ANSWERED_BY, prefix)
    return run


# --- sources ---------------------------------------------------------------

def _forms_loop(start: str, links: dict[str, list[str]]) -> bool:
    """True if following based_on links from `start` leads back to `start`."""
    seen: set[str] = set()
    todo = list(links.get(start, []))
    while todo:
        current = todo.pop()
        if current == start:
            return True
        if current not in seen:
            seen.add(current)
            todo.extend(links.get(current, []))
    return False


def _check_copy(out: _Problems, file: str, run_dir: Path, source: dict) -> None:
    expected = source.get("copy_sha256")
    if not _filled(expected):
        out.add(file, "copy_sha256", EMPTY)
    copy_file = source.get("copy_file")
    if not _filled(copy_file):
        out.add(file, "copy_file", EMPTY)
        return
    try:
        root = run_dir.resolve()
        target = (run_dir / copy_file).resolve()
        inside = target.is_relative_to(root)
        is_file = inside and target.is_file()
    except (OSError, ValueError):
        out.add(file, "copy_file", NOT_ALLOWED)
        return
    if not inside:  # never read outside the run folder
        out.add(file, "copy_file", NOT_ALLOWED)
    elif not is_file:
        out.add(file, "copy_file", "saved copy is missing")
    elif _filled(expected):
        try:
            actual = store.sha256_file(target)
        except PermissionError:   # the copy is there; only this user may not read it
            out.add(file, "copy_file", LOCKED)
            return
        except OSError:
            out.add(file, "copy_file", "saved copy is missing")
            return
        if actual != expected:
            out.add(file, "copy_sha256", "saved copy has changed")


def _is_web_address(value) -> bool:
    """Judged by the form check the download uses, so what a download records as `final_url` always passes."""
    if not isinstance(value, str):
        return False
    try:
        check_url(value)
    except ValueError:   # also what urlsplit raises for a damaged address: the data check never raises
        return False
    return True


def _is_saved_web_page(source: dict) -> bool:
    """Whether a source is a saved copy of a web page: its original is an .html or .htm file (save-source and
    add-copy name it so)."""
    orig_file = source.get("orig_file")
    return (source.get("access") == "ok" and isinstance(orig_file, str)
            and orig_file.lower().endswith((".html", ".htm")))


def _check_text_note(out: _Problems, file: str, source: dict) -> None:
    """A record without the key is fine (every record written before it existed has none). When it is there, it holds
    its one value, and only on a saved web page: the program never sets it on a PDF, a text or a table."""
    if "text_note" not in source:
        return
    note = source["text_note"]
    if not (isinstance(note, str) and note in store.TEXT_NOTES):
        out.add(file, "text_note", NOT_ALLOWED)
    elif not _is_saved_web_page(source):
        out.add(file, "text_note", NOTE_ON_A_WEB_PAGE_ONLY)


def _check_source(out: _Problems, run_dir: Path, path: Path, source: dict, run_mode,
                  source_ids: set[str], links: dict[str, list[str]]) -> None:
    file = f"sources/{path.name}"
    if source.get("id") != path.stem:
        out.add(file, "id", "file name does not match id")
    for field in ("url", "publisher", "title", "date", "speaker", "interest", "language", "saved_at"):
        out.nonempty(file, source, field)
    out.allowed(file, source, "type", store.SOURCE_TYPES)
    out.allowed(file, source, "saved_by", SAVED_BY)
    out.allowed(file, source, "access", SOURCE_ACCESS)
    out.allowed(file, source, "data_class", store.DATA_CLASSES)
    data_class = source.get("data_class")
    if data_class in store.DATA_CLASSES and data_class != "public":
        if run_mode == "public":
            out.add(file, "data_class", "non-public source in a public run")
        provenance = source.get("provenance")
        if not (isinstance(provenance, dict) and _filled(provenance.get("supplied_by"))
                and _filled(provenance.get("basis"))):
            out.add(file, "provenance", "provenance is required for non-public sources")
    final_url = source.get("final_url")   # a record written before the key existed has none
    if final_url is not None and not _is_web_address(final_url):
        out.add(file, "final_url", NOT_ALLOWED)
    _check_text_note(out, file, source)
    based_on = source.get("based_on")
    if based_on is not None and not isinstance(based_on, list):
        out.add(file, "based_on", NOT_ALLOWED)
    else:
        for target in based_on or []:
            if not (isinstance(target, str) and target in source_ids):
                out.add(file, "based_on", f"source {target} does not exist")
        if _forms_loop(path.stem, links):
            out.add(file, "based_on", "based_on must not form a loop")
    if source.get("access") == "ok":
        _check_copy(out, file, run_dir, source)
    elif source.get("access") == "not_accessible":
        out.nonempty(file, source, "access_reason")


# --- the record counters in run.json ----------------------------------------

_MAX_COUNT = 1_000_000   # far above any real run; a larger number is a hand edit, not a count


def _check_counters(out: _Problems, run: dict, ids: dict[str, set[str]]) -> None:
    """Every record the run counted as created must still have its file. Runs without counters are not checked."""
    for kind, key in store.COUNTERS.items():
        if key not in run:
            continue
        count = run[key]
        if not (type(count) is int and 0 <= count <= _MAX_COUNT):
            out.add("run.json", key, NOT_ALLOWED)
            continue
        for number in range(1, count + 1):
            if f"{kind}{number}" in ids[kind]:
                continue
            if kind == "S":
                out.add("run.json", key, f"source S{number} is missing")
            else:
                out.add("run.json", key, f"fact F{number} is missing")


# --- facts -----------------------------------------------------------------

def _check_fact(out: _Problems, path: Path, fact: dict, source_ids: set[str], early_sources: set[str]) -> None:
    file = f"facts/{path.name}"
    if fact.get("id") != path.stem:
        out.add(file, "id", "file name does not match id")
    _fact_rules(out, file, fact, source_ids, early_sources)


def _unknown_keys(out: _Problems, file: str, record: dict, known: tuple, prefix: str = "") -> None:
    """Name every key of `record` that is not in `known`: a misspelt key would otherwise be ignored without a word."""
    for key in record:
        if key not in known:
            out.add(file, prefix + str(key), f"the key {key} is not known")


def _quote_text(out: _Problems, file: str, record: dict, prefix: str = "") -> None:
    """A quote is filled text: a number or a list is `must be text`, a missing or blank one `must not be empty`."""
    quote = record.get("quote")
    if quote is not None and not isinstance(quote, str):
        out.add(file, prefix + "quote", MUST_BE_TEXT)
    else:
        out.nonempty(file, record, "quote", prefix)


def _optional_text(out: _Problems, file: str, record: dict, key: str, prefix: str = "") -> None:
    """A key that may be left out or null holds text when it is given: a number or a list is `must be text`."""
    value = record.get(key)
    if value is not None and not isinstance(value, str):
        out.add(file, prefix + key, MUST_BE_TEXT)


def _quote_words(out: _Problems, file: str, fact: dict, record: dict, prefix: str = "") -> None:
    """A filled quote has 5 to 50 words; the count is not judged on a fact that is already rejected."""
    quote = record.get("quote")
    if fact.get("status") != "rejected" and _filled(quote) and not 5 <= quote_units(quote) <= 50:
        out.add(file, prefix + "quote", "quote must have 5 to 50 words")


def _fact_rules(out: _Problems, file: str, fact: dict, source_ids: set[str], early_sources: set[str]) -> None:
    """The rules for a fact's content, shared by the data check and `radar add-fact`.

    `early_sources` holds the ids of the sources of a type that only early signals come from."""
    _unknown_keys(out, file, fact, FACT_KEYS)
    out.nonempty(file, fact, "statement")
    _quote_text(out, file, fact)
    for field in ("quote_language", "source_id"):
        out.nonempty(file, fact, field)
    if _filled(fact.get("source_id")) and fact["source_id"] not in source_ids:
        out.add(file, "source_id", f"source {fact['source_id']} does not exist")
    supporting = fact.get("supporting")
    if supporting is not None and not isinstance(supporting, list):
        out.add(file, "supporting", NOT_ALLOWED)
    for index, item in enumerate(supporting if isinstance(supporting, list) else []):
        if not isinstance(item, dict):
            out.add(file, f"supporting[{index}]", NOT_ALLOWED)
            continue
        prefix = f"supporting[{index}]."
        _unknown_keys(out, file, item, SUPPORTING_KEYS, prefix)
        source_id = item.get("source_id")
        if not (isinstance(source_id, str) and source_id in source_ids):
            out.add(file, prefix + "source_id", f"source {source_id} does not exist")
        _quote_text(out, file, item, prefix)   # the same rule as the main quote
        _quote_words(out, file, fact, item, prefix)
        translation = item.get("quote_translation")
        if translation is not None and not isinstance(translation, str):
            out.add(file, prefix + "quote_translation", NOT_ALLOWED)
    out.allowed(file, fact, "kind", FACT_KINDS)
    out.allowed(file, fact, "certainty", store.CERTAINTY)
    out.allowed(file, fact, "status", store.STATUSES)
    if not isinstance(fact.get("primary_source"), bool):
        out.add(file, "primary_source", NOT_ALLOWED)
    if "early_signal" in fact and not isinstance(fact["early_signal"], bool):   # a fact stored without it is fine
        out.add(file, "early_signal", NOT_ALLOWED)
    elif fact.get("early_signal") is True:
        if fact.get("certainty") != "tentative":
            out.add(file, "certainty", "an early signal must be marked tentative")
        if fact.get("kind") != "general":
            out.add(file, "kind", "an early signal must be a general fact")
    elif isinstance(fact.get("source_id"), str) and fact["source_id"] in early_sources:   # a hint by where it comes from, marked or not
        out.add(file, "early_signal",
                "a fact from a permit, a job posting or a regulator record must be marked as an early signal")
    if fact.get("certainty") == "tentative":
        out.nonempty(file, fact, "tentative_reason")
    else:
        _optional_text(out, file, fact, "tentative_reason")
    if fact.get("status") in ("uncertain", "rejected"):
        out.nonempty(file, fact, "status_reason")
    if "uncertain_reasons" in fact:   # a fact settled before the codes existed has none, which is fine
        codes = fact["uncertain_reasons"]
        if not (isinstance(codes, list) and all(isinstance(code, str) and code in store.UNCERTAIN_REASONS
                                                for code in codes)):
            out.add(file, "uncertain_reasons", NOT_ALLOWED)
    withdrawn = fact.get("withdrawn")
    if withdrawn is not None:
        if isinstance(withdrawn, dict):
            out.nonempty(file, withdrawn, "reason", "withdrawn.")
        else:
            out.add(file, "withdrawn", NOT_ALLOWED)
    _quote_words(out, file, fact, fact)
    language = fact.get("quote_language")
    if _filled(language) and language != "en":
        out.nonempty(file, fact, "quote_translation")
    else:
        _optional_text(out, file, fact, "quote_translation")
    _company_and_connections(out, file, fact)
    fields = fact.get("fields")
    if fact.get("kind") == "capacity_move":
        if not isinstance(fields, dict):
            out.add(file, "fields", EMPTY)
            return
        _unknown_keys(out, file, fields, CAPACITY_MOVE_FIELDS, "fields.")
        for field in ("company", "what_added", "announced"):
            out.nonempty(file, fields, field, "fields.")
        for field in ("site", "country", "size_unit", "planned_start"):
            _optional_text(out, file, fields, field, "fields.")
        size = fields.get("size_value")
        if size is not None and not isinstance(size, str):   # calc reads the size as written, so only text keeps it
            out.add(file, "fields.size_value", SIZE_AS_TEXT)
        elif calc.is_grouped(size):
            out.add(file, "fields.size_value", GROUPED_NUMBER)
        out.allowed(file, fields, "move_type", store.MOVE_TYPES, "fields.")
        out.allowed(file, fields, "stage", store.STAGES, "fields.")
        out.allowed(file, fields, "access", store.ACCESS, "fields.")
        if fields.get("delivery") is not None:
            out.allowed(file, fields, "delivery", store.DELIVERY, "fields.")
        if "in_question" in fields:   # a move stored before the field existed has none; a proposal must have it
            out.allowed(file, fields, "in_question", store.IN_QUESTION, "fields.")
    elif fact.get("kind") == "general" and fields is not None:
        out.add(file, "fields", NOT_ALLOWED)


def _company_and_connections(out: _Problems, file: str, fact: dict) -> None:
    """The company a fact is about and the parties it names. Whether a name stands in a quote is judged when the
    report is built, not here. A fact stored before the keys existed has neither, which is fine."""
    if fact.get("kind") == "capacity_move" and fact.get("about_company") is not None:
        out.add(file, "about_company", ABOUT_ON_A_MOVE)
    else:
        _optional_name(out, file, fact, "about_company")
    connections = fact.get("connections")
    if connections is not None and not isinstance(connections, list):
        out.add(file, "connections", NOT_ALLOWED)
        return
    for index, connection in enumerate(connections or []):
        prefix = f"connections[{index}]."
        if not isinstance(connection, dict):
            out.add(file, f"connections[{index}]", NOT_ALLOWED)
            continue
        _unknown_keys(out, file, connection, CONNECTION_KEYS, prefix)
        out.allowed(file, connection, "tie", store.CONNECTION_TIES, prefix)
        _optional_name(out, file, connection, "party", prefix)
        description = connection.get("description")
        if description is not None and not isinstance(description, str):
            out.add(file, prefix + "description", MUST_BE_TEXT)
        elif connection.get("party") is None and not _filled(description):
            out.add(file, prefix + "description", UNNAMED_PARTY)


def _optional_name(out: _Problems, file: str, record: dict, key: str, prefix: str = "") -> None:
    """A name that may be null: when given, it is filled text."""
    value = record.get(key)
    if value is not None and not isinstance(value, str):
        out.add(file, prefix + key, MUST_BE_TEXT)
    elif value is not None and not value.strip():
        out.add(file, prefix + key, EMPTY)


# --- analysis.json ---------------------------------------------------------

def _walk(node, path: str = ""):
    """Yield (path, key, value) for every key of every object inside `node`, without recursion."""
    todo = deque([(node, path)])
    while todo:
        current, where = todo.popleft()
        if isinstance(current, dict):
            for key, value in current.items():
                sub = f"{where}.{key}" if where else str(key)
                yield sub, key, value
                todo.append((value, sub))
        elif isinstance(current, list):
            for index, value in enumerate(current):
                todo.append((value, f"{where}[{index}]"))


# --- the entry points ------------------------------------------------------

def check_proposal(run_dir: Path, proposal: dict) -> list[Problem]:
    """What is wrong with a proposed fact before it is written, by the same rules the data check applies. A key the
    program sets itself (id, checks, status, its reason, the withdrawal) is refused by name, so the one who proposed
    it learns that the value would not have been taken."""
    source_ids = {path.stem for _, path in store._numbered_files(Path(run_dir), "S")}
    early_sources = {source_id for source_id, source in store.read_sources(Path(run_dir)).items()
                     if source.get("type") in store.EARLY_SIGNAL_SOURCE_TYPES}
    out = _Problems()
    for key in proposal:
        if key in PROGRAM_KEYS:
            out.add("proposal", key, f"the key {key} is set by the program, not by a proposal")
    fact = store.proposed_fact(proposal)
    _fact_rules(out, "proposal", fact, source_ids, early_sources)
    fields = fact.get("fields")
    if fact.get("kind") == "capacity_move" and isinstance(fields, dict) and "in_question" not in fields:
        out.add("proposal", "fields.in_question", IN_QUESTION_MISSING)
    connections = fact.get("connections")   # a stored fact may leave its party out; a proposal may not
    if isinstance(connections, list):
        out.items = [p for p in out.items if p.message != UNNAMED_PARTY]
        for index, connection in enumerate(connections):
            if isinstance(connection, dict) and connection.get("party") is None:
                out.add("proposal", f"connections[{index}].party", UNNAMED_PROPOSED_PARTY)
    return out.items


def check_data(run_dir: Path, lenses_dir: Path | None = None) -> list[Problem]:
    run_dir = Path(run_dir)
    out = _Problems()
    run = _check_run(out, run_dir)
    run_mode = run.get("mode") if run else None

    source_files = store._numbered_files(run_dir, "S")
    fact_files = store._numbered_files(run_dir, "F")
    source_ids = {path.stem for _, path in source_files}
    fact_ids = {path.stem for _, path in fact_files}
    if run:
        _check_counters(out, run, {"S": source_ids, "F": fact_ids})

    excluded = run.get("excluded") if run else None
    for index, entry in enumerate(excluded if isinstance(excluded, list) else []):
        if not (isinstance(entry, dict) and "source_id" in entry):   # an entry without the key is not checked
            continue
        if not isinstance(entry["source_id"], str):
            out.add("run.json", f"excluded[{index}].source_id", MUST_BE_TEXT)
        elif entry["source_id"] not in source_ids:
            out.add("run.json", f"excluded[{index}].source_id", f"source {entry['source_id']} does not exist")

    sources = {path: _load(path) for _, path in source_files}
    links = {}
    for path, source in sources.items():
        based_on = source.get("based_on") if source else None
        links[path.stem] = [t for t in based_on if isinstance(t, str) and t in source_ids] \
            if isinstance(based_on, list) else []
    for _, path in source_files:
        if sources[path] is None:
            out.add(f"sources/{path.name}", None, LOCKED if _may_not_be_opened(path) else NOT_JSON)
        else:
            _check_source(out, run_dir, path, sources[path], run_mode, source_ids, links)

    early_sources = {path.stem for path, source in sources.items()
                     if source and source.get("type") in store.EARLY_SIGNAL_SOURCE_TYPES}
    by_id = {path.stem: source for path, source in sources.items() if source}
    early_facts = set()   # by the mark or by the source's type, as everywhere else
    for _, path in fact_files:
        fact = _load(path)
        if fact is None:
            out.add(f"facts/{path.name}", None, LOCKED if _may_not_be_opened(path) else NOT_JSON)
        else:
            _check_fact(out, path, fact, source_ids, early_sources)
            if is_early_signal(fact, by_id):
                early_facts.add(path.stem)

    analysis_path = run_dir / "analysis.json"
    if analysis_path.exists():
        analysis = _load(analysis_path)
        if analysis is None:
            out.add("analysis.json", None, LOCKED if _may_not_be_opened(analysis_path) else NOT_JSON)
        else:
            from .schema_analysis import check_analysis   # imported here: schema_analysis builds on this module
            check_analysis(out, analysis, fact_ids, Path(lenses_dir) if lenses_dir else None, frozenset(early_facts))

    from . import recommend   # imported here: recommend builds on this module
    recommendation_path = run_dir / recommend.RECORD
    if os.path.lexists(recommendation_path):   # advice: its form only, and a run without one is fine
        recommendation = _load(recommendation_path)
        if recommendation is None:
            out.add(recommend.RECORD, None, LOCKED if _may_not_be_opened(recommendation_path) else NOT_JSON)
        else:
            out.items.extend(recommend.shape_problems(recommendation))

    from . import projects   # imported here: projects builds on this module
    grouping_path = run_dir / projects.RECORD
    if os.path.lexists(grouping_path):   # a help for reading: its form only, and a run without one is fine
        grouping = _load(grouping_path)
        if grouping is None:
            out.add(projects.RECORD, None, LOCKED if _may_not_be_opened(grouping_path) else NOT_JSON)
        else:
            out.items.extend(projects.shape_problems(grouping))
    return out.items
