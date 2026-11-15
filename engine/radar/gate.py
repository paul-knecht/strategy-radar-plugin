"""The gate: the one check that decides whether a report may be built.

It trusts no stored result. Quotes are searched again in the saved copies and the settling rules are
applied again to the checks as they stand now. The gate only reads: it never writes to the run folder,
so the report builder and the status command can both call it. Hand-edited or broken records never make
it raise; `check_data` names them and the gate works around them.
"""
import re
from pathlib import Path

from . import calc, diff, store, verify
from .schema import Problem, _walk, check_data
from .verify import check_quote

_SETTLED = store.COUNTING + ("rejected",)
COMPARISON_FOR_ANOTHER_RUN = "the comparison was made for another run"
COMPARISON_FROM_EARLIER_VERSION = "the comparison was made by an earlier version of the program"
PRIVATE_NOT_PUBLISHABLE = "a publishable report may not be built from a private run"


def _copy_text(run_dir: Path, source: dict | None) -> str | None:
    """The current text of a source's saved copy, or None when there is no usable copy."""
    if not source or not isinstance(source.get("copy_file"), str):
        return None
    try:
        return verify._read_copy(run_dir, source)[0]
    except (OSError, ValueError):  # a path that cannot be resolved
        return None


def _text_or_none(value) -> str | None:
    return value if isinstance(value, str) else None


def _recomputed(run_dir: Path, fact: dict, sources: dict[str, dict]) -> tuple[dict, list[int]]:
    """A copy of the fact carrying quote checks made now, and the position of each supporting entry checked.

    The stored `checks.support` stays as recorded: it is bound to the fact's content by a digest
    that `expected_status` compares. Supporting entries that are not objects are left out (check_data names them).
    """
    stored = fact.get("checks")
    support = stored.get("support") if isinstance(stored, dict) else None
    main_id = _text_or_none(fact.get("source_id"))
    quote = check_quote(fact.get("quote"), _copy_text(run_dir, sources.get(main_id)))
    listed = fact.get("supporting") if isinstance(fact.get("supporting"), list) else []
    positions = [index for index, entry in enumerate(listed) if isinstance(entry, dict)]
    entries = [listed[index] for index in positions]
    supporting = []
    for entry in entries:
        entry_id = _text_or_none(entry.get("source_id"))
        entry_text = _copy_text(run_dir, sources.get(entry_id))
        supporting.append({"source_id": entry_id, **check_quote(entry.get("quote"), entry_text)})
    fresh = dict(fact, source_id=main_id, supporting=entries,
                 checks={"quote": quote, "supporting": supporting,
                         "support": support if isinstance(support, dict) else None})
    return fresh, positions


def _missing_analysis(run_dir: Path) -> list[Problem]:
    if (run_dir / "analysis.json").exists():
        return []
    return [Problem("analysis.json", None, "analysis is missing")]


def _missing_checkpoints(run_dir: Path) -> list[Problem]:
    try:
        run = store.load_run(run_dir)
    except (ValueError, OSError, RecursionError):  # check_data names it
        return []
    checkpoints = run.get("checkpoints") if isinstance(run, dict) else None
    recorded = {item.get("name") for item in checkpoints
                if isinstance(item, dict) and isinstance(item.get("name"), str)} \
        if isinstance(checkpoints, list) else set()
    return [Problem("run.json", "checkpoints", f"checkpoint {name} is not recorded")
            for name in store.CHECKPOINTS if name not in recorded]


def _checks_that_do_not_hold(run_dir: Path, facts: dict[str, dict], sources: dict[str, dict]) -> list[Problem]:
    """Every settled fact whose status or reason does not follow from checks made now.

    A confirmed or uncertain fact must also pass each check on its own; a rejected one is re-derived too,
    so a status or reason set by hand never stands. Two copies count as one source by the texts as they are now.
    """
    texts = verify.copy_texts(run_dir, sources)
    problems = []
    for fact_id, fact in facts.items():
        status = fact.get("status")
        if status not in _SETTLED:
            continue
        file = f"facts/{fact_id}.json"
        fresh, positions = _recomputed(run_dir, fact, sources)
        checks = fresh["checks"]
        if status in store.COUNTING:
            if checks["quote"]["passed"] is not True:
                problems.append(Problem(file, "quote", "quote not found in saved copy"))
            for position, entry in zip(positions, checks["supporting"]):
                if entry["passed"] is not True:
                    problems.append(Problem(file, f"supporting[{position}].quote",
                                            "supporting quote not found in saved copy"))
            support = checks["support"]
            if support is None or support.get("passed") is not True:
                problems.append(Problem(file, "checks.support", "support check not passed"))
        expected, reason = verify.expected_status(fresh, sources, texts)
        if expected != status:
            problems.append(Problem(file, "status", "status does not follow from the checks"))
        elif reason != fact.get("status_reason"):
            problems.append(Problem(file, "status_reason", "reason does not follow from the checks"))
    return problems


def _facts_that_do_not_count(run_dir: Path, facts: dict[str, dict]) -> list[Problem]:
    """Every reference in analysis.json to a fact that is not confirmed or uncertain."""
    try:
        analysis = store.read_analysis(run_dir)
    except (ValueError, OSError, RecursionError):  # check_data names it
        return []
    if not isinstance(analysis, dict):
        return []
    problems = []
    for where, key, value in _walk(analysis):
        if not (isinstance(key, str) and key.endswith("fact_ids") and isinstance(value, list)):
            continue
        for fact_id in value:
            if not isinstance(fact_id, str):
                continue
            status = facts[fact_id].get("status") if fact_id in facts else "missing"
            if status not in store.COUNTING:
                problems.append(Problem("analysis.json", where, f"rests on fact {fact_id} with status {status}"))
    return problems


_FACT_ID_IN_TEXT = re.compile(r"(?<![A-Za-z0-9_])F[0-9]+(?![A-Za-z0-9_])")   # F9, standing on its own


def _texts(analysis: dict):
    """(path, text) for every text of the analysis, in lists too, in the order the file holds them, except the lists
    of fact ids, which the rule above judges. Without recursion, so a deeply nested hand edit never makes it raise."""
    todo = [(analysis, "")]
    while todo:
        node, where = todo.pop()
        if isinstance(node, str):
            yield where, node
        elif isinstance(node, dict):
            todo.extend(reversed([(value, f"{where}.{key}" if where else str(key)) for key, value in node.items()
                                  if not (isinstance(key, str) and key.endswith("fact_ids"))]))
        elif isinstance(node, list):
            todo.extend(reversed([(value, f"{where}[{index}]") for index, value in enumerate(node)]))


def _facts_named_in_texts(run_dir: Path, facts: dict[str, dict]) -> list[Problem]:
    """Every fact id written in a text of the analysis ("as F9 shows") that names a fact which does not exist or does
    not count: a reader takes the text as resting on that fact. A withdrawn fact never counts, settled or not.

    A flag of the bias audit is not the analysis's own text: it may point at a fact the analysis leans on whatever its
    status ("M1 leans on F9"), and the writer may not change it. Whether the facts a flag names exist is part of the
    data check, which reports it while the auditor can still be asked again (ruling FWA-4)."""
    try:
        analysis = store.read_analysis(run_dir)
    except (ValueError, OSError, RecursionError):  # check_data names it
        return []
    if not isinstance(analysis, dict):
        return []
    problems = []
    for where, text in _texts(analysis):
        if where.startswith("audit_flags["):     # the flags themselves, not a key that merely begins so
            continue
        named = []
        for fact_id in _FACT_ID_IN_TEXT.findall(text):
            if fact_id not in named:
                named.append(fact_id)
        for fact_id in named:
            fact = facts.get(fact_id)
            status = ("missing" if fact is None else "withdrawn" if verify.is_withdrawn(fact)
                      else fact.get("status"))
            if status not in store.COUNTING:
                problems.append(Problem("analysis.json", where, f"a text names fact {fact_id} with status {status}"))
    return problems


def _totals_that_do_not_match(facts: dict[str, dict], sources: dict[str, dict], run_dir: Path) -> list[Problem]:
    """Every calculation the engine cannot carry out, or whose stored result differs from its own."""
    try:
        analysis = store.read_analysis(run_dir)
    except (ValueError, OSError, RecursionError):  # check_data names it
        return []
    calculations = analysis.get("calculations") if isinstance(analysis, dict) else None
    if not isinstance(calculations, list):
        return []
    problems = []
    for index, calculation in enumerate(calculations):
        if not isinstance(calculation, dict):  # check_data names it
            continue
        where = f"calculations[{index}]"
        result = calc.compute(calculation, facts, sources)
        problems += [Problem("analysis.json", where, message) for message in result.problems]
        if result.value is not None and result.value != calculation.get("result"):
            problems.append(Problem("analysis.json", where,
                                    f"result does not match its inputs (computed {result.value})"))
    return problems


def _run_record(run_dir: Path) -> dict | None:
    """run.json, or None when it cannot be read (check_data names that)."""
    try:
        run = store.load_run(run_dir)
    except (ValueError, OSError, RecursionError):
        return None
    return run if isinstance(run, dict) else None


def _belongs_to_the_run(changes: dict, run: dict | None) -> list[Problem]:
    """A comparison must have been made for this run and with an earlier run of the same kind (illustrative or not),
    so one copied over from another pair of runs is refused. A file without the earlier run's kind is from an
    earlier version of the program."""
    if run is None:
        return []
    problems = []
    kind = changes.get("previous_illustrative")
    if not isinstance(kind, bool):
        problems.append(Problem("changes.json", "previous_illustrative", COMPARISON_FROM_EARLIER_VERSION))
    elif kind != (run.get("illustrative") is True):
        problems.append(Problem("changes.json", "previous_illustrative", diff.ILLUSTRATIVE_MIX))
    if changes.get("current_run") != run.get("run_id"):
        problems.append(Problem("changes.json", "current_run", COMPARISON_FOR_ANOTHER_RUN))
    return problems


def _comparison_problems(run_dir: Path, facts: dict[str, dict], publishable: bool) -> list[Problem]:
    """A stored comparison with an earlier run must be as the program wrote it, match the facts as they are now,
    belong to this run, and stay private when it must: a run that is not private may not hold a comparison with
    non-public material at all."""
    path = run_dir / "changes.json"
    if not path.exists():
        return []
    try:
        changes = store._read_json(path)
    except (ValueError, OSError, RecursionError):
        changes = None
    if not isinstance(changes, dict):
        return [Problem("changes.json", None, "not valid JSON")]
    problems = []
    if changes.get("facts_digest") != diff.facts_digest(facts):
        problems.append(Problem("changes.json", None, "the comparison is out of date"))
    try:
        as_written = changes.get("file_digest") == diff.file_digest(changes)
    except (ValueError, RecursionError):   # nested too deeply to be written out again
        as_written = False
    if not as_written:
        problems.append(Problem("changes.json", None, "the comparison was changed after it was made"))
    run = _run_record(run_dir)
    problems += _belongs_to_the_run(changes, run)
    mode = run.get("mode") if run is not None else None
    if changes.get("previous_confidential") is True and mode != "private":   # a hand-copied file too
        problems.append(Problem("changes.json", "previous_confidential", diff.PRIVATE_INTO_PUBLIC))
    elif publishable and changes.get("previous_confidential") is True:
        problems.append(Problem("changes.json", "previous_confidential",
                                "a publishable report may not compare against a run with non-public sources"))
    return problems


def gate(run_dir: Path, lenses_dir: Path | None = None, publishable: bool = False) -> list[Problem]:
    """Every reason the report may not be built yet. An empty list means it may."""
    run_dir = Path(run_dir)
    sources, facts = store.read_sources(run_dir), store.read_facts(run_dir)
    problems = list(check_data(run_dir, lenses_dir))
    problems += _missing_analysis(run_dir)
    problems += _missing_checkpoints(run_dir)
    problems += _checks_that_do_not_hold(run_dir, facts, sources)
    problems += _facts_that_do_not_count(run_dir, facts)
    problems += _facts_named_in_texts(run_dir, facts)
    problems += [Problem(f"facts/{fact_id}.json", "status", "fact was never settled")
                 for fact_id, fact in facts.items() if fact.get("status") == "proposed"]
    problems += _totals_that_do_not_match(facts, sources, run_dir)
    if publishable:
        run = _run_record(run_dir)
        if run is not None and run.get("mode") != "public":   # any private run, also one of public sources only
            problems.append(Problem("run.json", "mode", PRIVATE_NOT_PUBLISHABLE))
        problems += [Problem(f"sources/{source_id}.json", "data_class",
                             "a publishable report may use public sources only")
                     for source_id, source in sources.items() if source.get("data_class") != "public"]
    problems += _comparison_problems(run_dir, facts, publishable)
    return problems
