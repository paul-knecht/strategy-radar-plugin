"""The report's projects: the capacity moves grouped into projects, each with its reports, the spread of what they say,
the access the program sets by a fixed rule and the counts by status; and the answer to the core question, counted by
project. For display only: nothing here changes a fact or its status, and every count is computed here.

The projects are the grouping the project grouper recorded when it still fits the facts (`projects.current`). Without
one (none recorded, a damaged record, or one that no longer fits), every capacity move that counts is a project of its
own, with the id `project-<fact id>`.
"""
from pathlib import Path

from .. import projects, store, verify
from . import companies as company_view

ACCESS_SHOWN = ("open", "captive", "disagree", "not_stated")
COUNTED_AS = ("confirmed", "single_source", "uncertain")   # a project's counts, by each fact's shown status
SPREAD_FIELDS = (("site", "site"), ("stage", "stage"), ("planned_start", "planned_start"), ("what", "what_added"))


def _fields(fact: dict) -> dict:
    fields = fact.get("fields")
    return fields if isinstance(fields, dict) else {}


def project_access(facts: list[dict]) -> str:
    """The access of a project by the fixed rule: "open" when at least one report says open and none says captive,
    "captive" the other way round, "disagree" when both appear, else "not_stated" (a report that says neither, in
    any form, does not count)."""
    said = {_fields(fact).get("access") for fact in facts}
    if "open" in said and "captive" in said:
        return "disagree"
    if "open" in said:
        return "open"
    if "captive" in said:
        return "captive"
    return "not_stated"


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def spread(values: list) -> list[tuple[str, int]]:
    """What the reports say, as (value, how many reports say it): blanks left out, the most frequent first, ties in
    the order of first appearance."""
    counts: dict = {}
    for value in values:
        if not _blank(value):
            counts[value] = counts.get(value, 0) + 1
    return sorted(counts.items(), key=lambda item: -item[1])   # stable: ties keep the order of first appearance


def newest_first(facts: list[dict]) -> list[dict]:
    """Facts newest date first, undated last, then by id number."""
    by_id = sorted(facts, key=lambda fact: company_view.id_number(fact.get("id")))
    return sorted(by_id, key=lambda fact: fact.get("date") or "", reverse=True)


def _item(project_id: str, name: str, facts: list[dict]) -> dict:
    facts = newest_first(facts)
    counts = {shown: 0 for shown in COUNTED_AS}
    for fact in facts:
        if fact.get("shown_status") in counts:
            counts[fact["shown_status"]] += 1
    values = {key: [_fields(fact).get(field) for fact in facts] for key, field in SPREAD_FIELDS}
    values["countries"] = [country for fact in facts for country in fact.get("countries") or []]
    # each pair as a list, so the model stays plain data that reads back the same from JSON
    shown_spread = {key: [list(pair) for pair in spread(given)] for key, given in values.items()}
    dates = list(dict.fromkeys(fact["date"] for fact in facts if fact.get("date")))
    return {"id": project_id, "name": name, "company": dict(facts[0]["company"]), "facts": facts, "counts": counts,
            "access": project_access(facts), "spread": shown_spread, "dates": dates}


def _ungrouped_name(fact: dict, labels: dict[str, str]) -> str:
    """"<company>: <what was added>", with ", <site>" when a site is stated."""
    fields = _fields(fact)
    company = fact["company"].get("name") or fields.get("company") or ""
    name = labels["project_name_move"].format(company=company, what=fields.get("what_added") or "")
    site = fields.get("site")
    return labels["project_name_site"].format(name=name, site=site) if not _blank(site) else name


def _counting_move(fact: dict) -> bool:
    return (fact.get("kind") == "capacity_move" and fact.get("status") in store.COUNTING
            and not verify.is_withdrawn(fact))


in_question = projects.in_question   # missing field: inside, so an old run counts every move


def outside(fact: dict) -> bool:
    """A capacity move that counts but does not add the kind of capacity the question asks about: it sits in no
    project and is counted apart from the answer."""
    return _counting_move(fact) and not in_question(fact)


def build(run_dir: Path, model_facts: list[dict], companies: list[dict]) -> dict:
    """`{"state", "items"}`: the projects of the run, in the order of `companies` (the company buttons), then newest
    first, then by id. `state` is that of `projects.current`: "grouped" when the recorded grouping is shown, else
    "none", "damaged" or "outdated", and each capacity move that counts is then a project of its own.

    `model_facts` are the arranged model facts (each with its `company`, `countries`, `date` and `shown_status`). Only
    capacity moves that count and lie inside the question ever sit in a project; a rejected fact never does."""
    from .model import load_labels   # here and not at the top: the model imports this module
    by_id = {fact["id"]: fact for fact in model_facts if _counting_move(fact) and in_question(fact)}
    recorded, state = projects.current(Path(run_dir))
    if recorded is not None:
        items = []
        for project in recorded:
            known = [by_id[fact_id] for fact_id in project["fact_ids"] if fact_id in by_id]
            if known:   # a project whose reports are all gone is skipped, never built
                items.append(_item(project["id"], project["name"], known))
    else:
        labels = load_labels()
        items = [_item(f"project-{fact_id}", _ungrouped_name(fact, labels), [fact]) for fact_id, fact in by_id.items()]
    place = {entry["key"]: position for position, entry in enumerate(companies)}
    items.sort(key=lambda item: company_view.id_number(item["facts"][0]["id"]) if recorded is None
               else int(item["id"][1:]))
    items.sort(key=lambda item: item["dates"][0] if item["dates"] else "", reverse=True)
    items.sort(key=lambda item: place.get(item["company"]["key"], len(place)))
    return {"state": state, "items": items}


def core_answer(items: list[dict], outside_moves: int = 0) -> dict:
    """How many projects are open to customers, for own use, disagree and not stated, and how many in all; and
    `outside`, how many moves that count fall outside the question (they are in no project)."""
    answer = {access: 0 for access in ACCESS_SHOWN}
    for item in items:
        answer[item["access"]] += 1
    return dict(answer, total=len(items), outside=outside_moves)
