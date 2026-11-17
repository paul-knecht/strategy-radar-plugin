"""The grouping of capacity moves into projects: which reports are about one plan at one site. The project grouper
judges that; the program records it and checks its rules, never the judgement itself.

The grouper reads `grouper_input`: the run's question and every capacity move that counts, with its company and
countries tidied (`tidy`), and no quote, in parts that each fit its Bash tool (`grouper_parts`). It sends a list of projects, each `{"name", "fact_ids"}`, and
`record_projects` checks it by every rule of `check_projects`, under the run lock, and writes `projects.json` in the
run folder with each project's id (`P1`, `P2`, ... in the order sent). A list that breaks a rule writes nothing.

The rules: every capacity move that counts sits in exactly one project and nothing else does; a project's moves are of
one company (the tidied name, so a pack company's other names are that company); and every move of a project that
states a country states the same countries (a move that states none does not count against this).

The record is a help for reading the report, not a check: `check-data` looks at its shape only (`shape_problems`),
and the gate leaves out every problem of this file, so it never stops a report. `current` runs the rules again on the
facts as they are now, and a grouping that no longer fits them (a move added or withdrawn since) counts as none.
"""
from datetime import datetime
from pathlib import Path

from . import parts, store, tidy, verify
from .schema import Problem, _load, _Problems

RECORD = "projects.json"   # in the run folder
GROUPER = "project-grouper"
MAX_NAME = 120
RECORD_KEYS = ("by", "at", "projects")
PROJECT_KEYS = ("id", "name", "fact_ids")
GIVEN_KEYS = ("name", "fact_ids")   # what the grouper sends for one project

NOT_THE_GROUPER = "only the project grouper may record the projects"
FACT_NOT_A_MOVE = "a project names a fact that is not a capacity move that counts"
FACT_LEFT_OUT = "the projects leave out a capacity move that counts"
FACT_TWICE = "the projects name the same fact twice"
TWO_COMPANIES = "a project holds moves of more than one company"
TWO_COUNTRIES = "a project holds moves in different countries"
NAME_NEEDED = "a project needs a name of at most 120 characters"
SHAPE = "the saved projects do not hold exactly the parts the program writes"

# The plain line form, which the grouper sends on standard input so that no curly bracket stands in its command.
LINE_KEYS = {"project": "name", "facts": "fact_ids"}


class ProjectsRefused(ValueError):
    """The list breaks a rule; nothing was written. `problems` names every rule it breaks."""

    def __init__(self, problems: list[Problem]):
        super().__init__("the projects were refused because they break a rule")
        self.problems = problems


def _fields(fact: dict) -> dict:
    fields = fact.get("fields")
    return fields if isinstance(fields, dict) else {}


def in_question(fact: dict) -> bool:
    """Whether a move adds the kind of capacity the run's question asks about. A move stored before the field
    existed has none and counts as inside."""
    return _fields(fact).get("in_question") != "no"


def moves(run_dir: Path) -> dict[str, dict]:
    """The capacity moves that count, by id: confirmed or uncertain, not withdrawn (also before the next settle
    rejects a withdrawn one), and inside the question."""
    return {fact_id: fact for fact_id, fact in store.read_facts(Path(run_dir)).items()
            if fact.get("kind") == "capacity_move" and fact.get("status") in store.COUNTING
            and not verify.is_withdrawn(fact) and in_question(fact)}


# --- the rules -------------------------------------------------------------------------------------------------------

def _well_formed(projects) -> bool:
    """A list of objects with exactly a name and a non-empty list of fact ids."""
    return isinstance(projects, list) and all(
        isinstance(project, dict) and set(project) == set(GIVEN_KEYS)
        and isinstance(project["fact_ids"], list) and project["fact_ids"]
        and all(isinstance(fact_id, str) for fact_id in project["fact_ids"]) for project in projects)


def _name_fits(name) -> bool:
    return isinstance(name, str) and bool(name.strip()) and len(name) <= MAX_NAME


def _problems(projects, counting: dict[str, dict], companies: tidy.Companies) -> list[Problem]:
    out = _Problems()
    if not _well_formed(projects):
        out.add(RECORD, "projects", SHAPE)
        return out.items
    placed = set()
    for index, project in enumerate(projects):
        where = f"projects[{index}]"
        if not _name_fits(project["name"]):
            out.add(RECORD, where + ".name", NAME_NEEDED)
        held = []
        for fact_id in project["fact_ids"]:
            if fact_id not in counting:
                out.add(RECORD, fact_id, FACT_NOT_A_MOVE)
            elif fact_id in placed:
                out.add(RECORD, fact_id, FACT_TWICE)
            else:
                placed.add(fact_id)
                held.append(_fields(counting[fact_id]))
        owners = {found["key"] for found in (companies.resolve(fields.get("company")) for fields in held) if found}
        if len(owners) > 1:
            out.add(RECORD, where, TWO_COMPANIES)
        places = {frozenset(tidy.countries(fields.get("country"))) for fields in held} - {frozenset()}
        if len(places) > 1:
            out.add(RECORD, where, TWO_COUNTRIES)
    for fact_id in counting:
        if fact_id not in placed:
            out.add(RECORD, fact_id, FACT_LEFT_OUT)
    return out.items


def _companies(run_dir: Path) -> tidy.Companies:
    return tidy.Companies.from_run(store.load_run(run_dir))


def check_projects(run_dir: Path, projects: list[dict]) -> list[Problem]:
    """Every rule the projects break, each a problem of `projects.json`: the field names the project, or the fact a
    problem is about (so its explanation can name it). Takes no lock: `record_projects` holds it around the same check.
    Never raises on odd input."""
    run_dir = Path(run_dir)
    return _problems(projects, moves(run_dir), _companies(run_dir))


# --- the record ------------------------------------------------------------------------------------------------------

def record_projects(run_dir: Path, projects: list[dict], by: str, now: datetime | None = None) -> dict:
    """Check the projects and write the run's grouping, replacing any earlier one; return what was written.

    Refused, before anything is written: a `by` that is not the project grouper (ValueError, NOT_THE_GROUPER) and
    projects that break a rule (ProjectsRefused, a ValueError, with every problem). Holds the run lock from reading
    the facts to writing the record, so a fact withdrawn in parallel is either seen or not, never half."""
    if by != GROUPER:
        raise ValueError(NOT_THE_GROUPER)
    run_dir = Path(run_dir)
    with verify._run_lock(run_dir):
        problems = check_projects(run_dir, projects)
        if problems:
            raise ProjectsRefused(problems)
        record = {"by": by, "at": store._stamp(now),
                  "projects": [{"id": f"P{number}", "name": project["name"], "fact_ids": project["fact_ids"]}
                               for number, project in enumerate(projects, start=1)]}
        store._write_json(run_dir / RECORD, record)
    return record


def shape_problems(record) -> list[Problem]:
    """What is wrong with the form of a saved grouping: exactly its parts, each of the right type, the grouper as its
    maker, each name filled in and at most 120 characters, and the projects numbered P1, P2, ... in order. Never the facts it names. Never raises."""
    out = _Problems()
    if not isinstance(record, dict):
        out.add(RECORD, None, SHAPE)
        return out.items
    for key in record:
        if key not in RECORD_KEYS:
            out.add(RECORD, str(key), SHAPE)
    for key in RECORD_KEYS:
        if key not in record:
            out.add(RECORD, key, SHAPE)
    if "by" in record and record["by"] != GROUPER:
        out.add(RECORD, "by", SHAPE)
    if "at" in record and not isinstance(record["at"], str):
        out.add(RECORD, "at", SHAPE)
    if "projects" in record:
        if not isinstance(record["projects"], list):
            out.add(RECORD, "projects", SHAPE)
            return out.items
        for index, project in enumerate(record["projects"]):
            where = f"projects[{index}]"
            if not isinstance(project, dict) or set(project) != set(PROJECT_KEYS):
                out.add(RECORD, where, SHAPE)
                continue
            if project["id"] != f"P{index + 1}":
                out.add(RECORD, where + ".id", SHAPE)
            if not _name_fits(project["name"]):   # the program never writes a blank or overlong name
                out.add(RECORD, where + ".name", SHAPE)
            fact_ids = project["fact_ids"]
            if not (isinstance(fact_ids, list) and fact_ids and all(isinstance(fact_id, str) for fact_id in fact_ids)):
                out.add(RECORD, where + ".fact_ids", SHAPE)
    return out.items


def current(run_dir: Path) -> tuple[list[dict] | None, str]:
    """The recorded projects when they still fit the facts as they are now: `(projects, "grouped")`. Otherwise
    `(None, state)`: `"none"` when there is no record, `"damaged"` when it cannot be read or its form is wrong, and
    `"outdated"` when a rule fails on the facts now. Takes no lock (the report calls it under the run lock) and never
    raises."""
    run_dir = Path(run_dir)
    path = run_dir / RECORD
    try:
        if not path.exists() and not path.is_symlink():
            return None, "none"
        record = _load(path)
        if record is None or shape_problems(record):
            return None, "damaged"
        given = [{key: project[key] for key in GIVEN_KEYS} for project in record["projects"]]
        if check_projects(run_dir, given):
            return None, "outdated"
    except (OSError, ValueError, RecursionError):
        return None, "damaged"
    return record["projects"], "grouped"


# --- what the grouper reads ------------------------------------------------------------------------------------------

def grouper_input(run_dir: Path) -> dict:
    """What the project grouper reads: `{"question", "facts"}`, a fact for every capacity move that counts and lies
    inside the question (`moves`), in the order of the fact numbers: `{"id", "statement", "status", "company", "site", "countries", "what_added", "size",
    "stage", "announced", "planned_start", "access", "publisher", "date"}`. `company` is the tidied name (None for a
    blank one), `countries` the tidied countries, `size` the size as stated with its unit tidied; `publisher` and
    `date` are those of the fact's main source. No quote and no source text. Changes nothing."""
    run_dir = Path(run_dir)
    companies, sources = _companies(run_dir), store.read_sources(run_dir)
    facts = []
    for fact_id, fact in moves(run_dir).items():
        fields = _fields(fact)
        company = companies.resolve(fields.get("company"))
        size = tidy.size(fields.get("size_value"), fields.get("size_unit"))["stated"]
        source = sources.get(verify.text_id(fact.get("source_id"))) or {}
        facts.append({"id": fact_id, "statement": fact.get("statement"), "status": fact.get("status"),
                      "company": company["name"] if company else None, "site": fields.get("site"),
                      "countries": tidy.countries(fields.get("country")), "what_added": fields.get("what_added"),
                      "size": size, "stage": fields.get("stage"), "announced": fields.get("announced"),
                      "planned_start": fields.get("planned_start"), "access": fields.get("access"),
                      "publisher": source.get("publisher"), "date": source.get("date")})
    return {"question": store.load_run(run_dir).get("question"), "facts": facts}


def grouper_parts(run_dir: Path) -> list[dict]:
    """`grouper_input` in parts that each print shorter than `parts.PART_LIMIT`: the question on the first part only,
    and each part `{"part", "parts", "facts"}`. Changes nothing."""
    return parts.split_input(grouper_input(run_dir), ("facts",))


# --- the plain line form -----------------------------------------------------------------------------------------------

def parse_list_lines(text: str) -> list[dict]:
    """The projects of a list in the plain line form, as `record_projects` takes them.

    Each line holds one `key: value`, split at the first `: `. Projects are separated by one or more blank lines; the
    keys of a project are exactly `project` (its name) and `facts` (fact numbers separated by commas), in any order.
    Raises ValueError, with a plain sentence, for a line with no `: `, a key that is not known, a key given twice in
    one project, a project that lacks a key and a `facts` with no value. Says nothing on what the values hold: the
    rules do that."""
    blocks, block = [], []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            block.append((number, line))
        elif block:
            blocks.append(block)
            block = []
    if block:
        blocks.append(block)
    projects, keys = [], " and ".join(LINE_KEYS)
    for block in blocks:
        project = {}
        for number, line in block:
            key, sep, value = line.partition(": ")
            key, value = key.strip(), value.strip()
            if not sep:
                raise ValueError(f"line {number} of the list has no ': ' after its key. Write each part as key: value "
                                 "on a line of its own.")
            if key not in LINE_KEYS:
                raise ValueError(f"line {number} of the list names a key that is not known. The keys of a project are "
                                 f"{keys}.")
            if LINE_KEYS[key] in project:
                raise ValueError(f"line {number} of the list gives {key} a second time in one project. Leave a blank "
                                 "line between two projects.")
            if key == "facts":
                if not value:
                    raise ValueError(f"line {number} of the list gives no facts. Write the fact numbers separated by "
                                     "commas.")
                value = [item.strip() for item in value.split(",")]
                if not all(value):
                    raise ValueError(f"line {number} of the list holds an empty fact number. Write the fact numbers "
                                     "separated by commas.")
            project[LINE_KEYS[key]] = value
        for key, name in LINE_KEYS.items():
            if name not in project:
                raise ValueError(f"project {len(projects) + 1} of the list has no {key}. Each project needs {keys}.")
        projects.append({name: project[name] for name in GIVEN_KEYS})
    return projects
