"""The data check of analysis.json: every section the report reads, in the shape the renderers rely on.

`schema.check_data` calls `check_analysis` and stays the single entry point. Nothing here raises on a
hand-edited analysis: a section or item of the wrong type becomes a named problem (`must be a list`,
`must be an object`, `must be text`), so the report builder never meets it after the gate has opened.
A section or text that is missing or null is not a type problem; the report then shows nothing there.
"""
import re
from datetime import date
from pathlib import Path

from . import store
from .schema import (AT_LEAST_ONE, MUST_BE_TEXT, NOT_A_DATE, NOT_A_PROBABILITY, NOT_ALLOWED, NOT_JSON,
                     SCENARIO_COUNT, Problem, _Problems, _filled, _load, _walk)

AUDIT_FLAG_KEYS = ("check", "text")   # a flag is exactly a check and a text; the report prints nothing else of it

MUST_BE_LIST = "must be a list"
MUST_BE_OBJECT = "must be an object"
# A step the report prints as "Fact" must rest on a fact, and a key message's reasoning ends in its conclusion.
FACT_STEP_WITHOUT_FACT = "a fact step must name at least one fact"
CONCLUSION_NOT_LAST = "the last step of a chain must be its conclusion"
FLAG_KEY_NOT_KNOWN = "the key {} is not known in a flag"   # ruling FWA-5a: explained for a flag, not for a fact
# A flag of the bias audit may name any fact of the run, whatever its status, but only one that exists (ruling FWA-4).
FLAG_NAMES_NO_FACT = "a flag names fact {}, which does not exist"
_FACT_ID_IN_TEXT = re.compile(r"(?<![A-Za-z0-9_])F[0-9]+(?![A-Za-z0-9_])")   # F9, standing on its own, as the gate reads it

_LENS_ID = re.compile(r"[\w-]+")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


# --- types ------------------------------------------------------------------

def _list(out: _Problems, container: dict, key: str, where: str) -> list:
    """The list at `container[key]`; missing or null is empty, and any other type is named and treated as empty."""
    value = container.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        out.add("analysis.json", where, MUST_BE_LIST)
        return []
    return value


def _objects(out: _Problems, items: list, where: str) -> list[tuple[int, dict]]:
    """(position, item) for every item that is an object; every other item is named."""
    found = []
    for index, item in enumerate(items):
        if isinstance(item, dict):
            found.append((index, item))
        else:
            out.add("analysis.json", f"{where}[{index}]", MUST_BE_OBJECT)
    return found


def _text(out: _Problems, record: dict, field: str, prefix: str) -> None:
    value = record.get(field)
    if value is not None and not isinstance(value, str):
        out.add("analysis.json", prefix + field, MUST_BE_TEXT)


def _texts(out: _Problems, items: list, where: str) -> None:
    for index, item in enumerate(items):
        if not isinstance(item, str):
            out.add("analysis.json", f"{where}[{index}]", MUST_BE_TEXT)


# --- messages, options and the shown lists ------------------------------------

def _check_message(out: _Problems, index: int, message: dict) -> None:
    prefix = f"messages[{index}]."
    for field in ("text", "counter_view", "would_change"):
        out.nonempty("analysis.json", message, field, prefix)
    out.allowed("analysis.json", message, "confidence", store.CONFIDENCE, prefix)
    chain = message.get("chain")
    if chain is not None and not isinstance(chain, list):
        out.add("analysis.json", prefix + "chain", MUST_BE_LIST)
    else:
        steps = _objects(out, chain or [], prefix + "chain")
        for position, step in steps:
            out.allowed("analysis.json", step, "kind", store.STEP_KINDS, f"{prefix}chain[{position}].")
            _text(out, step, "text", f"{prefix}chain[{position}].")
            if step.get("kind") == "fact" and step.get("fact_ids") in (None, []):   # another type is named below
                out.add("analysis.json", f"{prefix}chain[{position}].fact_ids", FACT_STEP_WITHOUT_FACT)
        kinds = [step.get("kind") for _, step in steps]
        if "fact" not in kinds:
            out.add("analysis.json", prefix + "chain", "chain must have at least one fact step")
        if kinds.count("conclusion") != 1:
            out.add("analysis.json", prefix + "chain", "chain must have exactly one conclusion step")
        elif not (isinstance(chain[-1], dict) and chain[-1].get("kind") == "conclusion"):   # nothing after it
            out.add("analysis.json", prefix + "chain", CONCLUSION_NOT_LAST)
    outside = message.get("outside_view")
    if outside is not None:
        if isinstance(outside, dict):
            _text(out, outside, "text", prefix + "outside_view.")
        else:
            out.add("analysis.json", prefix + "outside_view", MUST_BE_OBJECT)


def _check_messages(out: _Problems, analysis: dict) -> None:
    messages = analysis.get("messages")
    if not isinstance(messages, list):
        out.add("analysis.json", "messages", NOT_ALLOWED)
        return
    records = []
    for index, message in enumerate(messages):
        if isinstance(message, dict):
            records.append((index, message))
        else:
            out.add("analysis.json", f"messages[{index}]", NOT_ALLOWED)
    _unique_ids(out, "messages", records)
    for index, message in records:
        _check_message(out, index, message)


def _check_options(out: _Problems, analysis: dict) -> None:
    """The decision options: their question, framing, options with points for and against, and open questions."""
    options = analysis.get("decision_options")
    if options is not None and not isinstance(options, dict):
        out.add("analysis.json", "decision_options", MUST_BE_OBJECT)
    if not (isinstance(options, dict) and options.get("framing") in store.FRAMING):
        out.add("analysis.json", "decision_options.framing", NOT_ALLOWED)
    if not isinstance(options, dict):
        return
    _text(out, options, "question", "decision_options.")
    where = "decision_options.options"
    for index, option in _objects(out, _list(out, options, "options", where), where):
        _text(out, option, "name", f"{where}[{index}].")
        for side in ("for", "against"):
            side_where = f"{where}[{index}].{side}"
            for position, point in _objects(out, _list(out, option, side, side_where), side_where):
                _text(out, point, "text", f"{side_where}[{position}].")
    where = "decision_options.internal_questions"
    _texts(out, _list(out, options, "internal_questions", where), where)


def _check_sections(out: _Problems, analysis: dict) -> None:
    """The lists the report shows as they are: signals, watch items, checks, contradictions, gaps and lens notes."""
    for section, text_fields in (("demand_signals", ("text",)), ("watch_items", ("text", "trigger")),
                                 ("audit_flags", ("text",)), ("contradictions", ("text",)),
                                 ("lens_notes", ("here",))):
        for index, item in _objects(out, _list(out, analysis, section, section), section):
            prefix = f"{section}[{index}]."
            for field in text_fields:
                _text(out, item, field, prefix)
            if section == "audit_flags":
                out.allowed("analysis.json", item, "check", store.AUDIT_CHECKS, prefix)
                for key in item:                       # a flag's own message, so that its explanation fits a flag
                    if key not in AUDIT_FLAG_KEYS:
                        out.add("analysis.json", prefix + str(key), FLAG_KEY_NOT_KNOWN.format(key))
                if item.get("text") is None or isinstance(item.get("text"), str):   # another type is named above
                    out.nonempty("analysis.json", item, "text", prefix)
            if section == "lens_notes":
                out.nonempty("analysis.json", item, "lens_id", prefix)
    _texts(out, _list(out, analysis, "not_found", "not_found"), "not_found")


def _lens_problems(lenses_dir: Path, lens_id: str) -> list[Problem] | None:
    """Problems in one lens file, or None if there is no such lens."""
    path = lenses_dir / f"{lens_id}.json"
    if not _LENS_ID.fullmatch(lens_id) or not path.is_file():
        return None
    file = f"lenses/{lens_id}.json"
    out = _Problems()
    lens = _load(path)
    if lens is None:
        out.add(file, None, NOT_JSON)
        return out.items
    questions = lens.get("questions")
    if not (isinstance(questions, list) and len(questions) == 3):
        out.add(file, "questions", "lens must have exactly 3 questions")
    originals = lens.get("originals")
    if not isinstance(originals, list):
        out.add(file, "originals", NOT_ALLOWED)
        return out.items
    for index, original in enumerate(originals):
        if not (isinstance(original, dict) and original.get("level") in store.LENS_LEVELS):
            out.add(file, f"originals[{index}].level", NOT_ALLOWED)
    return out.items


# --- assumptions, scenarios, predictions, calculations ---------------------

def _records(out: _Problems, analysis: dict, section: str) -> list[tuple[int, dict]]:
    """The (index, record) pairs of one list section. A missing section is empty; a wrong type is named."""
    if section not in analysis:
        return []
    items = analysis[section]
    if not isinstance(items, list):
        out.add("analysis.json", section, NOT_ALLOWED)
        return []
    records = []
    for index, item in enumerate(items):
        if isinstance(item, dict):
            records.append((index, item))
        else:
            out.add("analysis.json", f"{section}[{index}]", NOT_ALLOWED)
    return records


def _unique_ids(out: _Problems, section: str, records: list[tuple[int, dict]]) -> set[str]:
    """Check that every record has a distinct, non-empty id; return the ids."""
    seen: set[str] = set()
    for index, record in records:
        prefix = f"{section}[{index}]."
        out.nonempty("analysis.json", record, "id", prefix)
        record_id = record.get("id")
        if _filled(record_id):
            if record_id in seen:
                out.add("analysis.json", prefix + "id", f"id {record_id} is used more than once")
            seen.add(record_id)
    return seen


def _check_scenario(out: _Problems, index: int, scenario: dict, assumption_ids: set[str]) -> None:
    prefix = f"scenarios[{index}]."
    for field in ("name", "description"):
        out.nonempty("analysis.json", scenario, field, prefix)
    linked = scenario.get("assumption_ids")
    if not isinstance(linked, list):
        out.add("analysis.json", prefix + "assumption_ids", NOT_ALLOWED)
    elif not linked:
        out.add("analysis.json", prefix + "assumption_ids", AT_LEAST_ONE)
    else:
        for assumption_id in linked:
            if not (isinstance(assumption_id, str) and assumption_id in assumption_ids):
                out.add("analysis.json", prefix + "assumption_ids", f"assumption {assumption_id} does not exist")
    signposts = scenario.get("signposts")
    if not isinstance(signposts, list):
        out.add("analysis.json", prefix + "signposts", NOT_ALLOWED)
    elif not signposts:
        out.add("analysis.json", prefix + "signposts", AT_LEAST_ONE)
    for position, signpost in enumerate(signposts if isinstance(signposts, list) else []):
        if isinstance(signpost, dict):
            out.nonempty("analysis.json", signpost, "text", f"{prefix}signposts[{position}].")
        else:
            out.add("analysis.json", f"{prefix}signposts[{position}]", NOT_ALLOWED)


def _is_date(value) -> bool:
    if not (isinstance(value, str) and _ISO_DATE.fullmatch(value)):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _check_prediction(out: _Problems, index: int, prediction: dict, message_ids: set[str]) -> None:
    prefix = f"predictions[{index}]."
    message_id = prediction.get("message_id")
    if not (isinstance(message_id, str) and message_id in message_ids):
        out.add("analysis.json", prefix + "message_id", f"message {message_id} does not exist")
    for field in ("statement", "resolves_when"):
        out.nonempty("analysis.json", prediction, field, prefix)
    if not _is_date(prediction.get("by")):
        out.add("analysis.json", prefix + "by", NOT_A_DATE)
    probability = prediction.get("probability")
    if not (type(probability) is int and 1 <= probability <= 99):
        out.add("analysis.json", prefix + "probability", NOT_A_PROBABILITY)


def _check_judgements(out: _Problems, analysis: dict) -> None:
    file = "analysis.json"
    assumptions = _records(out, analysis, "assumptions")
    assumption_ids = _unique_ids(out, "assumptions", assumptions)
    for index, assumption in assumptions:
        prefix = f"assumptions[{index}]."
        for field in ("text", "if_wrong"):
            out.nonempty(file, assumption, field, prefix)
        out.allowed(file, assumption, "support", store.SUPPORT_LEVELS, prefix)

    scenarios = _records(out, analysis, "scenarios")
    scenario_ids = _unique_ids(out, "scenarios", scenarios)
    if isinstance(analysis.get("scenarios"), list) and len(analysis["scenarios"]) not in (0, 2, 3, 4):
        out.add(file, "scenarios", SCENARIO_COUNT)
    for index, scenario in scenarios:
        _check_scenario(out, index, scenario, assumption_ids)

    watch_items = analysis.get("watch_items")
    for index, item in enumerate(watch_items if isinstance(watch_items, list) else []):
        scenario_id = item.get("scenario_id") if isinstance(item, dict) else None
        if scenario_id is not None and not (isinstance(scenario_id, str) and scenario_id in scenario_ids):
            out.add(file, f"watch_items[{index}].scenario_id", f"scenario {scenario_id} does not exist")

    messages = analysis.get("messages")
    message_ids = {message["id"] for message in messages
                   if isinstance(message, dict) and isinstance(message.get("id"), str)} \
        if isinstance(messages, list) else set()
    predictions = _records(out, analysis, "predictions")
    _unique_ids(out, "predictions", predictions)
    for index, prediction in predictions:
        _check_prediction(out, index, prediction, message_ids)

    calculations = _records(out, analysis, "calculations")
    _unique_ids(out, "calculations", calculations)
    for index, calculation in calculations:
        prefix = f"calculations[{index}]."
        for field in ("label", "result"):
            out.nonempty(file, calculation, field, prefix)
        out.allowed(file, calculation, "operation", store.CALC_OPERATIONS, prefix)
        fact_ids = calculation.get("fact_ids")
        if isinstance(fact_ids, list) and not fact_ids:   # a wrong type is named with the other fact_ids
            out.add(file, prefix + "fact_ids", AT_LEAST_ONE)


def _check_baselines(out: _Problems, analysis: dict, early_ids: frozenset) -> None:
    """The baselines of the competitors: a company and at least one fact each, and no wording of their own.

    The report shows each fact's own checked statement, so a baseline cannot carry a figure its facts do not hold.
    A baseline is what a company already has, so it never rests on an early signal (a fact in `early_ids`).
    A wrong type of `fact_ids` is named with the other fact_ids."""
    for index, baseline in _records(out, analysis, "baselines"):
        prefix = f"baselines[{index}]."
        out.nonempty("analysis.json", baseline, "company", prefix)
        if "text" in baseline:
            out.add("analysis.json", prefix + "text", "a baseline takes its wording from its facts")
        fact_ids = baseline.get("fact_ids")
        if fact_ids is None or (isinstance(fact_ids, list) and not fact_ids):
            out.add("analysis.json", prefix + "fact_ids", AT_LEAST_ONE)
        for fact_id in fact_ids if isinstance(fact_ids, list) else []:
            if isinstance(fact_id, str) and fact_id in early_ids:
                out.add("analysis.json", prefix + "fact_ids", f"a baseline may not rest on {fact_id}, an early signal")


def _check_flag_facts(out: _Problems, analysis: dict, fact_ids: set[str]) -> None:
    """Every fact id written in a flag's text names a fact of this run."""
    flags = analysis.get("audit_flags")
    for index, flag in enumerate(flags if isinstance(flags, list) else []):
        text = flag.get("text") if isinstance(flag, dict) else None
        named = []
        for fact_id in _FACT_ID_IN_TEXT.findall(text) if isinstance(text, str) else []:
            if fact_id not in named:
                named.append(fact_id)
        for fact_id in named:
            if fact_id not in fact_ids:
                out.add("analysis.json", f"audit_flags[{index}].text", FLAG_NAMES_NO_FACT.format(fact_id))


def check_analysis(out: _Problems, analysis: dict, fact_ids: set[str], lenses_dir: Path | None,
                   early_ids: frozenset = frozenset()) -> None:
    """Add every problem in analysis.json to `out`. `early_ids` are the facts that are early signals."""
    file = "analysis.json"
    _check_messages(out, analysis)
    _check_options(out, analysis)
    _check_sections(out, analysis)
    _check_flag_facts(out, analysis, fact_ids)
    _check_judgements(out, analysis)
    _check_baselines(out, analysis, early_ids)
    checked: dict[str, list[Problem] | None] = {}
    for path, key, value in _walk(analysis):
        if isinstance(key, str) and key.endswith("fact_ids"):
            if not isinstance(value, list):
                out.add(file, path, NOT_ALLOWED)
                continue
            for fact_id in value:
                if not (isinstance(fact_id, str) and fact_id in fact_ids):
                    out.add(file, path, f"fact {fact_id} does not exist")
        elif key == "lens_id" and lenses_dir is not None and value is not None:
            found = None
            if isinstance(value, str):
                if value not in checked:
                    checked[value] = _lens_problems(lenses_dir, value)
                    out.items.extend(checked[value] or [])
                found = checked[value]
            if found is None:
                out.add(file, path, f"lens {value} does not exist")
