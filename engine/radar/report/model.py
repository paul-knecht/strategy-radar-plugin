"""The report model: everything the renderers need, built from the stored records only.

`build_model` is pure. It reads the run folder and writes nothing. It does not decide anything again:
a fact carries the `status` and `status_reason` that are stored, because the gate has already
confirmed they follow from the checks. Text is kept as it is; each renderer escapes it for its own format.

This module also holds what both renderers share about wording: the probability scale, how a reference to a
fact is marked, and the labels that stand in for engine words (statuses, reasons, step kinds, checkpoints,
access reasons, audit checks, field values). A reader never sees an engine word itself.
"""
import copy
import json
import re
from datetime import datetime
from pathlib import Path

from .. import calc, store, verify
from ..textnorm import normalise

_LABELS_FILE = Path(__file__).with_name("labels_en.json")
# The project's probability scale: (lowest probability, span shown in the legend, label key), highest first.
PROBABILITY_SCALE = ((95, "95-100", "prob_95"), (80, "80-94", "prob_80"), (60, "60-79", "prob_60"),
                     (40, "40-59", "prob_40"), (20, "20-39", "prob_20"), (5, "5-19", "prob_5"), (0, "0-4", "prob_0"))
REASONS = ("not_found", "not_supported", "quote_too_short", "quote_too_long", "no_saved_copy",
           "supporting_quote_not_found", "withdrawn", "checks_incomplete", "support_check_outdated")
ACCESS_REASONS = ("timeout", "network_error", "too_large", "unsupported_type", "no_text_layer", "unreadable_file",
                  "too_little_text", "login_required", "robots", "private_address", "too_many_redirects")
_HTTP_REASON = re.compile(r"http_([0-9]+)")
# Each field whose values have labels, with the label prefix and the values that have one. Nothing else resolves.
_FIELD_LABELS = {"move_type": ("move_", store.MOVE_TYPES), "stage": ("stage_", store.STAGES),
                 "access": ("access_", store.ACCESS), "delivery": ("delivery_", store.DELIVERY),
                 "status": ("status_", store.STATUSES)}
_DATE_FIELDS = ("announced", "planned_start")


def load_labels() -> dict[str, str]:
    """The fixed report text."""
    return json.loads(_LABELS_FILE.read_text(encoding="utf-8"))


def count_label(labels: dict[str, str], key: str, n) -> str:
    """The label `key` for a count of `n`, not yet filled: its `_one` form for exactly one, where it has one."""
    return labels[key + "_one"] if n == 1 and key + "_one" in labels else labels[key]


# The endings after which a word's plural ends in "es"; any other plural in "s" only drops its "s".
_ES_PLURALS = ("ches", "shes", "sses", "xes", "zes")


def unit_for(value, unit):
    """The unit as a reader reads it after `value`: a unit of one word in the singular after exactly one ("1 line",
    "1 batch", "1 facility"), else as written. A unit of several words ("million vials") and a word that does not end
    in a plural "s" ("kWh", "gas", "bus") are left as written."""
    if not isinstance(unit, str) or calc.parse_number(value if isinstance(value, str) else None) != 1:
        return unit
    if " " in unit.strip() or len(unit) < 3:
        return unit
    lower = unit.lower()
    if not lower.endswith("s") or lower.endswith(("ss", "us", "is", "as")):
        return unit
    if lower.endswith("ies") and len(unit) > 4:
        return unit[:-3] + ("Y" if unit[-3:].isupper() else "y")
    if lower.endswith(_ES_PLURALS):
        return unit[:-2]
    return unit[:-1]


def probability_word(probability: int, labels: dict[str, str]) -> str:
    """The project's own scale: 95 and above is `prob_95`, then 80, 60, 40, 20, 5; below 5 is `prob_0`."""
    for lowest, _, key in PROBABILITY_SCALE:
        if probability >= lowest:
            return labels[key]
    return labels["prob_0"]


# --- wording shared by both renderers -------------------------------------------------------------

def label(labels: dict[str, str], prefix: str, value, known: tuple) -> str:
    """The label of an engine word such as a step kind or audit check; anything else is shown as written."""
    if isinstance(value, str) and value in known and prefix + value in labels:
        return labels[prefix + value]
    return "" if value is None else str(value)


def fact_notes(fact: dict, labels: dict[str, str]) -> list[tuple[str, str, str]]:
    """How every reference to a fact is marked: (kind, value, label) for an uncertain or rejected status and for a
    source that is not public. A confirmed fact from a public source carries no note."""
    notes = []
    status = fact.get("status")
    if status in ("uncertain", "rejected"):
        notes.append(("status", status, labels[f"status_{status}"]))
    data_class = fact.get("data_class")
    if data_class not in (None, "public"):
        notes.append(("class", str(data_class), labels.get(f"class_{data_class}", str(data_class))))
    return notes


def reason_text(fact: dict, labels: dict[str, str]) -> str | None:
    """Why a fact has its status, for a reader: the label of an engine reason, or an uncertain fact's reason as written."""
    reason = fact.get("status_reason")
    if reason in REASONS:
        return labels[f"reason_{reason}"]
    return reason if isinstance(reason, str) and reason.strip() else None


def reason_note(fact: dict, labels: dict[str, str]) -> tuple[str, str] | None:
    """(label, text) of the words behind a rejection: the checker's note for `not_supported`, the analyst's reason
    for a withdrawal. None when there is none."""
    reason = fact.get("status_reason")
    if reason == "not_supported":
        support = (fact.get("checks") or {}).get("support") if isinstance(fact.get("checks"), dict) else None
        text = support.get("note") if isinstance(support, dict) else None
    elif reason == "withdrawn":
        withdrawn = fact.get("withdrawn")
        text = withdrawn.get("reason") if isinstance(withdrawn, dict) else None
    else:
        return None
    return (labels[f"reason_note_{reason}"], text) if isinstance(text, str) and text.strip() else None


def access_reason_text(reason, labels: dict[str, str]) -> str:
    """Why a source could not be saved, for a reader. A reason written by hand is shown as written."""
    if not isinstance(reason, str):
        return ""
    found = _HTTP_REASON.fullmatch(reason)
    if found:
        return labels["access_reason_http"].format(code=found.group(1))
    return label(labels, "access_reason_", reason, ACCESS_REASONS)


def field_label(name: str, value, labels: dict[str, str]) -> str:
    """A field value for a reader: its label where that field has labels for that value, else the value as written.
    A date that is not stated is said in words, never by its code."""
    if name in _DATE_FIELDS and value == "not_stated":
        return labels["value_not_stated"]
    prefix, known = _FIELD_LABELS.get(name, ("", ()))
    return label(labels, prefix, value, known) if known else ("" if value is None else str(value))


def checkpoint_parts(item: dict, labels: dict[str, str]) -> list[str]:
    """Who answered a decision and the answer, as the texts a report joins with ": ". An answer that begins with the
    words of its own label (every test answer begins "Recorded test answer:") is printed once, as recorded."""
    answered_by = item.get("answered_by")
    answered = labels.get(f"answered_by_{answered_by}", "" if answered_by is None else str(answered_by))
    answer = "" if item.get("answer") is None else str(item.get("answer"))
    return [answer] if answered and answer.startswith(answered + ":") else [answered, answer]


def _company_key(company) -> str:
    return normalise(company).casefold() if isinstance(company, str) else ""


def _id_number(record_id: str) -> int:
    digits = "".join(ch for ch in str(record_id) if ch.isdigit())
    return int(digits) if digits else 0


class _Resolver:
    """Turns fact ids into fact dicts that carry their source and data class."""

    def __init__(self, facts: dict[str, dict], sources: dict[str, dict]):
        self._facts, self._sources = facts, sources
        self._cache: dict[str, dict] = {}

    def fact(self, fact_id: str) -> dict | None:
        if fact_id not in self._facts:
            return None
        if fact_id not in self._cache:
            fact = copy.deepcopy(self._facts[fact_id])
            source = self._sources.get(fact.get("source_id"))
            fact["source"] = copy.deepcopy(source) if source is not None else None
            fact["data_class"] = source.get("data_class") if source is not None else None
            self._cache[fact_id] = fact
        return copy.deepcopy(self._cache[fact_id])

    def facts(self, fact_ids) -> list[dict]:
        found = (self.fact(fact_id) for fact_id in (fact_ids if isinstance(fact_ids, list) else []))
        return [fact for fact in found if fact is not None]

    def attach(self, item, ids_key: str = "fact_ids", into: str = "facts") -> dict:
        """A copy of `item` with the facts its `ids_key` names under `into`."""
        item = copy.deepcopy(item)
        item[into] = self.facts(item.get(ids_key))
        return item


def _load_lens(lenses_dir: Path, lens_id: str) -> dict:
    """The lens file, or just its id and name when the file cannot be read."""
    try:
        lens = json.loads((Path(lenses_dir) / f"{lens_id}.json").read_text(encoding="utf-8"))
        if isinstance(lens, dict):
            return lens
    except (OSError, ValueError):
        pass
    return {"id": lens_id, "name": lens_id}


def _lenses_in_order_of_use(analysis: dict) -> list[str]:
    """Lens ids in order of first use: chain steps of the messages first, then the lens notes."""
    order: list[str] = []
    for message in analysis.get("messages") or []:
        for step in message.get("chain") or []:
            lens_id = step.get("lens_id")
            if isinstance(lens_id, str) and lens_id not in order:
                order.append(lens_id)
    for note in analysis.get("lens_notes") or []:
        lens_id = note.get("lens_id")
        if isinstance(lens_id, str) and lens_id not in order:
            order.append(lens_id)
    return order


def split_early_signals(facts: list[dict]) -> tuple[list[dict], list[dict]]:
    """(the other facts, the early signals), each in the order given. Early signals stay in the one list of facts;
    only the listing under "What the sources say" tells them apart. `verify.is_early_signal` decides, by the mark or by
    the type of the source each fact carries."""
    early = [verify.is_early_signal(fact) for fact in facts]
    return ([fact for fact, is_early in zip(facts, early) if not is_early],
            [fact for fact, is_early in zip(facts, early) if is_early])


def group_by_company(facts: list[dict], home_company, baselines: list[dict] | None = None) -> list[dict]:
    """Capacity moves grouped by company, the home company first, then by name; each group lists its moves.

    Each group also carries `baseline`: the facts the company's baselines rest on, each once, in the order named.
    `baselines` are the analysis items with their facts attached under `facts`. A company that has a baseline but no
    move still gets a group, with no moves.
    """
    groups: dict[str, dict] = {}

    def group_of(company) -> dict:
        key = _company_key(company)
        return groups.setdefault(key, {"company": normalise(company) if isinstance(company, str) else "",
                                       "home": key == _company_key(home_company) and key != "",
                                       "moves": [], "baseline": []})

    for fact in facts:
        if fact.get("kind") != "capacity_move" or not isinstance(fact.get("fields"), dict):
            continue
        group_of(fact["fields"].get("company"))["moves"].append(fact)
    for item in baselines or []:
        shown = group_of(item.get("company"))["baseline"]
        for fact in item.get("facts") or []:
            if fact["id"] not in {seen["id"] for seen in shown}:
                shown.append(fact)
    for group in groups.values():
        group["moves"].sort(key=lambda fact: (fact["fields"].get("announced") or "", _id_number(fact["id"])))
    return sorted(groups.values(), key=lambda group: (not group["home"], _company_key(group["company"])))


def _latest_save_date(sources: dict[str, dict]) -> str | None:
    stamps = [source["saved_at"][:10] for source in sources.values()
              if isinstance(source.get("saved_at"), str) and source["saved_at"]]
    return max(stamps) if stamps else None


def _quotes_of(source_id: str, facts: list[dict]) -> list[dict]:
    quotes = []
    for fact in facts:
        if fact.get("source_id") == source_id:
            quotes.append({"fact_id": fact["id"], "quote": fact.get("quote"),
                           "translation": fact.get("quote_translation")})
        for entry in fact.get("supporting") or []:
            if isinstance(entry, dict) and entry.get("source_id") == source_id:
                quotes.append({"fact_id": fact["id"], "quote": entry.get("quote"),
                               "translation": entry.get("quote_translation")})
    return quotes


def _read_changes(run_dir: Path) -> dict | None:
    """The comparison with an earlier run, or None when there is none or the file is not a JSON object."""
    path = Path(run_dir) / "changes.json"
    try:
        changes = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return changes if isinstance(changes, dict) else None


def build_model(run_dir: Path, lenses_dir: Path, now: datetime | None = None) -> dict:
    """Everything the renderers need. `now` is when the report is built (default: the current time, in UTC)."""
    run_dir = Path(run_dir)
    labels = load_labels()
    run = store.load_run(run_dir)
    sources = store.read_sources(run_dir)
    all_facts = store.read_facts(run_dir)
    analysis = store.read_analysis(run_dir) or {}
    resolve = _Resolver(all_facts, sources)

    counted = [resolve.fact(fact_id) for fact_id, fact in all_facts.items() if fact.get("status") in store.COUNTING]
    rejected = [resolve.fact(fact_id) for fact_id, fact in all_facts.items() if fact.get("status") == "rejected"]
    changes = _read_changes(run_dir)
    confidential = (any(source.get("data_class") != "public" for source in sources.values())
                    or (changes is not None and changes.get("previous_confidential") is True))

    messages = []
    for message in analysis.get("messages") or []:
        message = copy.deepcopy(message)
        for step in message.get("chain") or []:
            step["facts"] = resolve.facts(step.get("fact_ids"))
            lens_id = step.get("lens_id")
            step["lens"] = ({"id": lens_id, "name": _load_lens(lenses_dir, lens_id).get("name", lens_id)}
                            if isinstance(lens_id, str) else None)
        if isinstance(message.get("outside_view"), dict):
            message["outside_view"] = resolve.attach(message["outside_view"])
        messages.append(message)

    options = copy.deepcopy(analysis.get("decision_options"))
    if isinstance(options, dict):
        options = resolve.attach(options, "framing_fact_ids", "framing_facts")
        for option in options.get("options") or []:
            for side in ("for", "against"):
                option[side] = [resolve.attach(point) for point in option.get(side) or []]

    notes = {note.get("lens_id"): note.get("here") or "" for note in reversed(analysis.get("lens_notes") or [])}
    lenses = []
    for lens_id in _lenses_in_order_of_use(analysis):
        lens = _load_lens(lenses_dir, lens_id)
        lens["here"] = notes.get(lens_id, "")
        lenses.append(lens)

    assumptions = []
    for assumption in analysis.get("assumptions") or []:
        assumption = resolve.attach(assumption)
        assumption["support_label"] = labels.get(f"support_{assumption.get('support')}", "")
        assumptions.append(assumption)
    by_id = {assumption["id"]: assumption for assumption in assumptions}

    scenarios = []
    for scenario in analysis.get("scenarios") or []:
        scenario = copy.deepcopy(scenario)
        scenario["assumptions"] = [copy.deepcopy(by_id[a]) for a in scenario.get("assumption_ids") or [] if a in by_id]
        scenario["signposts"] = [resolve.attach(signpost) for signpost in scenario.get("signposts") or []]
        scenarios.append(scenario)

    predictions = []
    for prediction in analysis.get("predictions") or []:
        prediction = copy.deepcopy(prediction)
        prediction["word"] = probability_word(prediction["probability"], labels)
        predictions.append(prediction)

    calculations = []
    for calculation in analysis.get("calculations") or []:
        calculation = resolve.attach(calculation, "fact_ids", "inputs")
        calculation["whole"] = resolve.facts(calculation.get("of_fact_ids"))
        calculation["includes_uncertain"] = calc.compute(calculation, all_facts, sources).includes_uncertain
        calculations.append(calculation)

    listed = analysis.get("baselines")
    baselines = [resolve.attach(item) for item in listed if isinstance(item, dict)] if isinstance(listed, list) else []
    return {
        "question": run.get("question"),
        "run_id": run.get("run_id"),
        "pack": run.get("pack"),
        "illustrative": bool(run.get("illustrative")),
        "sources_read_until": (run.get("sources_read_until") or _latest_save_date(sources)
                               or (run.get("started_at") or "")[:10] or None),
        "built_on": store._stamp(now)[:10],
        "home_company": run.get("home_company"),
        "mode": run.get("mode"),
        "confidential": confidential,
        "status_line": {
            "confirmed": sum(1 for fact in all_facts.values() if fact.get("status") == "confirmed"),
            "uncertain": sum(1 for fact in all_facts.values() if fact.get("status") == "uncertain"),
            "rejected": len(rejected),
            "sources": len(sources),
            "not_accessible": sum(1 for source in sources.values() if source.get("access") == "not_accessible"),
        },
        "messages": messages,
        "facts": counted,
        "rejected": rejected,
        "competitors": group_by_company(counted, run.get("home_company"), baselines),
        "demand_signals": [resolve.attach(signal) for signal in analysis.get("demand_signals") or []],
        "decision_options": options,
        "watch_items": copy.deepcopy(analysis.get("watch_items") or []),
        "audit_flags": copy.deepcopy(analysis.get("audit_flags") or []),
        "not_found": copy.deepcopy(analysis.get("not_found") or []),
        "contradictions": [resolve.attach(item) for item in analysis.get("contradictions") or []],
        "lenses": lenses,
        "sources": [dict(copy.deepcopy(source), quotes=_quotes_of(source_id, counted))
                    for source_id, source in sources.items()],
        "how_made": {"search_log": copy.deepcopy(run.get("search_log") or []),
                     "excluded": copy.deepcopy(run.get("excluded") or []),
                     "checkpoints": copy.deepcopy(run.get("checkpoints") or []),
                     # the person's own reply to the private-mode notice, word for word; shown next to the decisions
                     "private_acknowledged": (run.get("private_acknowledged_words")
                                              if run.get("mode") == "private"
                                              and isinstance(run.get("private_acknowledged_words"), str) else None)},
        "changes": changes,
        "assumptions": assumptions,
        "scenarios": scenarios,
        "predictions": predictions,
        "calculations": calculations,
        "compliance": labels["compliance_private"] if confidential else labels["compliance_public"],
    }
