"""Compare two runs: which capacity moves are new, changed, gone or only possibly the same.

Read-only: nothing here writes to either run folder. The `radar compare` command stores the result.
Non-public material never goes into a public run, and an illustrative run is compared only with another one.
The result also says whether the earlier run held non-public material (it was a private run, or one of its sources
was not public) and whether it was illustrative, carries a digest of the facts it
compared, so the gate can tell when the comparison no longer matches the current run, and a digest of itself,
so the gate can tell when the file was changed after the program wrote it.
"""
import hashlib
import json
import re
from datetime import date
from pathlib import Path

from . import store, verify
from .store import COUNTING, load_run, read_analysis, read_facts, read_sources
from .textnorm import normalise

KEY_FIELDS = ("company", "site", "move_type", "what_added")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

PRIVATE_INTO_PUBLIC = "a public run may not be compared with a run that holds non-public material"
ILLUSTRATIVE_MIX = "an illustrative run cannot be compared with a run that is not illustrative"
PRACTICE_RUN_ONLY = "the practice run can only be compared with an earlier practice run"
EARLIER_RUN_NOT_SETTLED = ("the earlier run has facts whose status no longer follows from their checks, "
                           "so settle the earlier run first")


class CompareRefused(ValueError):
    """Two runs that may not be compared, or an earlier run not settled; the message is one of the fixed ones above."""


def holds_non_public(run: dict, sources: dict[str, dict]) -> bool:
    """Whether a run holds material that is not public: it is not a public run, or one of its sources is not public."""
    return run.get("mode") != "public" or any(source.get("data_class") != "public" for source in sources.values())


def _refusal(previous_run: dict, previous_sources: dict[str, dict], current_run: dict) -> str | None:
    """Why the earlier run may not be compared into the current one, or None. A current run counts as public unless
    it says it is private, so a broken mode never lets non-public material through."""
    if current_run.get("mode") != "private" and holds_non_public(previous_run, previous_sources):
        return PRIVATE_INTO_PUBLIC
    if (previous_run.get("illustrative") is True) != (current_run.get("illustrative") is True):
        return ILLUSTRATIVE_MIX
    if store.is_demo_private_run(current_run) and not store.is_demo_private_run(previous_run):
        return PRACTICE_RUN_ONLY
    return None


def fact_key(fact: dict) -> tuple[str, str, str, str]:
    """What identifies a capacity move across runs: company, site, move type and what was added."""
    fields = fact.get("fields") or {}
    return tuple(normalise(str(fields.get(name) or "")).casefold() for name in KEY_FIELDS)


def _taking_part(facts: dict[str, dict]) -> dict[str, dict]:
    return {fact_id: fact for fact_id, fact in facts.items()
            if fact.get("kind") == "capacity_move" and fact.get("status") in COUNTING}


def facts_digest(facts: dict[str, dict]) -> str:
    """SHA-256 of the compared facts: each confirmed or uncertain capacity move, in id order, with status and fields."""
    compared = [{"id": fact_id, "status": fact.get("status"), "fields": fact.get("fields")}
                for fact_id, fact in sorted(_taking_part(facts).items(), key=lambda item: _id_number(item[0]))]
    text = json.dumps(compared, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_digest(changes: dict) -> str:
    """SHA-256 of the canonical JSON of a comparison without its own `file_digest` key.

    `compare_runs` stores it, so the gate can tell a comparison that was edited by hand or damaged after the
    program wrote it. It guards against a slip, not against someone who can recompute a hash.
    """
    text = json.dumps({key: value for key, value in changes.items() if key != "file_digest"},
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _id_number(fact_id: str) -> int:
    digits = "".join(ch for ch in fact_id if ch.isdigit())
    return int(digits) if digits else 0


def _main_source(fact: dict, sources: dict[str, dict]) -> dict:
    return sources.get(fact.get("source_id")) or {}


def _differences(previous: dict, current: dict) -> dict:
    """Every non-key field whose value differs, and the status, as {name: [before, after]}."""
    before, after = previous.get("fields") or {}, current.get("fields") or {}
    names = sorted((set(before) | set(after)) - set(KEY_FIELDS))
    diff = {name: [before.get(name), after.get(name)] for name in names if before.get(name) != after.get(name)}
    if previous.get("status") != current.get("status"):
        diff["status"] = [previous.get("status"), current.get("status")]
    return diff


def _predictions_due(previous: Path, today: date) -> list[dict]:
    try:
        analysis = read_analysis(previous)
    except (OSError, ValueError):
        return []
    predictions = analysis.get("predictions") if isinstance(analysis, dict) else None
    if not isinstance(predictions, list):
        return []
    due = []
    for prediction in predictions:
        if not isinstance(prediction, dict):
            continue
        by = prediction.get("by")
        if not isinstance(by, str) or not _ISO_DATE.fullmatch(by):
            continue
        try:
            deadline = date.fromisoformat(by)
        except ValueError:
            continue
        if deadline <= today:
            due.append({"prediction_id": prediction.get("id"),
                        "statement": prediction.get("statement"), "by": by})
    return due


def compare_runs(previous: Path, current: Path, today: date | None = None) -> dict:
    """The comparison of the earlier run with the current one. Raises CompareRefused, before anything of the earlier
    run is read into the result, when the two may not be joined: non-public material into a public run, an
    illustrative run with one that is not, or a run that is not a practice run into the practice run; and when a
    fact of the earlier run holds a status its checks no longer give it (withdrawn, a new verdict or a new source
    link, and not settled since), as `calc` refuses such a fact."""
    previous, current = Path(previous), Path(current)
    today = today or date.today()
    previous_run, current_run = load_run(previous), load_run(current)
    before_sources, after_sources = read_sources(previous), read_sources(current)
    refusal = _refusal(previous_run, before_sources, current_run)
    if refusal:
        raise CompareRefused(refusal)
    previous_facts = read_facts(previous)   # its stored statuses are taken on trust only when they still follow
    texts = verify.copy_texts(previous, before_sources)
    if any(verify.needs_settling(fact, before_sources, texts) for fact in previous_facts.values()):
        raise CompareRefused(EARLIER_RUN_NOT_SETTLED)
    current_facts = read_facts(current)
    before, after = _taking_part(previous_facts), _taking_part(current_facts)

    previous_by_key: dict[tuple, list[str]] = {}
    for fact_id, fact in before.items():
        previous_by_key.setdefault(fact_key(fact), []).append(fact_id)

    # Exact matches: facts with the same key pair up in id order; any surplus has no partner.
    taken: dict[tuple, int] = {}
    pairs: list[tuple[str, str]] = []
    unmatched_current: list[str] = []
    for fact_id, fact in after.items():
        key = fact_key(fact)
        position = taken.get(key, 0)
        candidates = previous_by_key.get(key, [])
        if position < len(candidates):
            pairs.append((fact_id, candidates[position]))
            taken[key] = position + 1
        else:
            unmatched_current.append(fact_id)
    matched_previous = {previous_id for _, previous_id in pairs}
    unmatched_previous = [fact_id for fact_id in before if fact_id not in matched_previous]

    result = {"previous_run": previous_run.get("run_id"), "current_run": current_run.get("run_id"),
              "new": [], "changed": [], "source_changed": [], "source_unavailable": [],
              "not_found_again": [], "possible_matches": [], "predictions_due": [], "unchanged": 0,
              "previous_confidential": holds_non_public(previous_run, before_sources),
              "previous_illustrative": previous_run.get("illustrative") is True,
              "facts_digest": facts_digest(current_facts)}

    for fact_id, previous_id in pairs:
        old, new = before[previous_id], after[fact_id]
        differing = _differences(old, new)
        old_source, new_source = _main_source(old, before_sources), _main_source(new, after_sources)
        if differing:
            result["changed"].append({"fact_id": fact_id, "previous_fact_id": previous_id, "fields": differing})
        elif (old_source.get("url") and old_source.get("url") == new_source.get("url")
              and old_source.get("copy_sha256") != new_source.get("copy_sha256")):
            result["source_changed"].append(
                {"fact_id": fact_id, "previous_fact_id": previous_id, "url": new_source["url"]})
        else:
            result["unchanged"] += 1

    # Possible matches: exactly three key parts agree. Each previous fact is used at most once.
    available = list(unmatched_previous)
    for fact_id in unmatched_current:
        current_key = fact_key(after[fact_id])
        for previous_id in available:
            apart = [name for name, a, b in zip(KEY_FIELDS, current_key, fact_key(before[previous_id])) if a != b]
            if len(apart) == 1:
                result["possible_matches"].append(
                    {"fact_id": fact_id, "previous_fact_id": previous_id, "differing_field": apart[0]})
                available.remove(previous_id)
                break
        else:
            result["new"].append({"fact_id": fact_id})

    inaccessible = {source.get("url") for source in after_sources.values()
                    if source.get("access") == "not_accessible" and source.get("url")}
    for previous_id in available:
        url = _main_source(before[previous_id], before_sources).get("url")
        if url in inaccessible:
            result["source_unavailable"].append({"previous_fact_id": previous_id, "url": url})
        else:
            result["not_found_again"].append({"previous_fact_id": previous_id})

    result["predictions_due"] = _predictions_due(previous, today)
    result["file_digest"] = file_digest(result)
    return result
