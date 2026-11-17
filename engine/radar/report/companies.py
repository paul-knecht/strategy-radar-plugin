"""Which company each fact is about, the status the report shows for it, and its tidy values. For display only.

Nothing here changes a stored fact, its `status` or its `status_reason`. A company or a party a model named is kept only
when the name is found in the fact's own words (see `arrange`); a name that is not found is dropped from the report and
counted, and the fact keeps its status.
"""
import re
from decimal import Decimal

from .. import store, tidy, verify

# The number of different sources (a source that repeats another counts once with it) an outside company needs for
# an entry of its own.
OWN_PAGE_SOURCES = 3
_DATE = re.compile(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?(?![\d-])")
_NONE = {"key": "none", "name": None, "group": "none", "home": False}


def shown_status(fact: dict, sources: dict[str, dict]) -> str:
    """The status the report shows: "single_source" for an uncertain fact whose one reason is that it rests on one
    source that is not the party itself, else the fact's own status ("confirmed", "uncertain" or "rejected").

    By the codes `settle` writes (`uncertain_reasons`) when the fact has them; for a fact settled before the codes
    existed, by its reason, its certainty and whether it is an early signal, which by the order of
    `verify.expected_status` says the same. `sources` may be empty when the fact carries its `source`."""
    status = fact.get("status")
    if status != "uncertain":
        return status
    codes = fact.get("uncertain_reasons")
    if isinstance(codes, list):
        alone = codes == ["single_source"]
    else:
        alone = (fact.get("status_reason") == verify.NOT_PRIMARY_REASON and fact.get("certainty") != "tentative"
                 and not verify.is_early_signal(fact, sources))
    return "single_source" if alone else "uncertain"


def fact_date(source: dict | None) -> str | None:
    """A fact's date for sorting and filtering: its source's publication date, read from its start as `YYYY-MM-DD`,
    `YYYY-MM` or `YYYY`. Any other form gives None (undated)."""
    written = source.get("date") if isinstance(source, dict) else None
    found = _DATE.match(written) if isinstance(written, str) else None
    if found is None:
        return None
    year, month, day = found.groups()
    if (month is not None and not 1 <= int(month) <= 12) or (day is not None and not 1 <= int(day) <= 31):
        return None
    return found.group(0)


def count_clusters(source_ids, sources: dict[str, dict]) -> int:
    """How many different sources `source_ids` are: two sources whose lineages (`verify._lineage`) overlap are one,
    and so is every source joined to them that way."""
    clusters: list[set[str]] = []
    for source_id in dict.fromkeys(source_ids):
        lineage = verify._lineage(source_id, sources)
        touching = [cluster for cluster in clusters if cluster & lineage]
        for cluster in touching:
            lineage |= cluster
            clusters.remove(cluster)
        clusters.append(lineage)
    return len(clusters)


def _company_texts(fact: dict) -> list[str]:
    """The words a fact's company is looked for in: its quotes, their translations and its statement."""
    return _quote_texts(fact) + [fact.get("statement")]


def _quote_texts(fact: dict) -> list[str]:
    """The words a connection's party is looked for in: the main quote, every supporting quote, their translations."""
    texts = [fact.get("quote"), fact.get("quote_translation")]
    for entry in fact.get("supporting") or []:
        if isinstance(entry, dict):
            texts += [entry.get("quote"), entry.get("quote_translation")]
    return texts


def size_of(fields: dict) -> dict:
    """The tidy size, its number as plain text (2, 2.5) so the model stays plain data."""
    found = tidy.size(fields.get("size_value"), fields.get("size_unit"))
    number = found["number"]
    return dict(found, number=tidy._plain(number) if isinstance(number, Decimal) else None)


def id_number(record_id) -> int:
    """The number in a record id (F12 gives 12), for sorting ids by number; 0 when it holds no digit."""
    digits = "".join(ch for ch in str(record_id) if ch.isdigit())
    return int(digits) if digits else 0


def arrange(run: dict, facts: list[dict], sources: dict[str, dict]) -> dict:
    """Give each model fact in `facts` (in place) its `shown_status`, `date`, `company`, `countries`, `size` and
    `connections`; return `{"companies", "names_dropped", "by_id"}`.

    A capacity move's company is its `fields.company`. A general fact's is its `about_company`, kept only when the name
    is found in the fact's quotes, their translations or its statement. A connection is kept when its party is found
    in the quotes or their translations, or when it names no party. Each name dropped is counted.

    `companies` is the order of the company buttons: the pack's companies (the home company first, then in pack
    order), then each outside company with at least `OWN_PAGE_SOURCES` different sources, by name; then "other" and
    "none" when any fact falls under them. An outside company's sources are the main sources of the confirmed and
    uncertain facts that are about it or name it as a kept party (`count_clusters`). An entry has `only_connections`
    when it is an outside company with no fact of its own: it is listed only because connections name it."""
    pack = tidy.Companies.from_run(run)
    dropped = {"companies": 0, "parties": 0}
    found = {}   # fact id: (its company or None, [(a kept party or None, its connection entry)])
    for fact in facts:
        fields = fact.get("fields") if isinstance(fact.get("fields"), dict) else {}
        if fact.get("kind") == "capacity_move":
            company = pack.resolve(fields.get("company"))
        else:
            company = pack.resolve(fact.get("about_company"))
            if company is not None and not tidy.name_in(pack.names_to_find(fact.get("about_company")),
                                                        _company_texts(fact)):
                company = None
                dropped["companies"] += 1
        parties = []
        for entry in fact.get("connections") or []:
            if not isinstance(entry, dict):
                continue
            party = pack.resolve(entry.get("party"))
            if party is not None and not tidy.name_in(pack.names_to_find(entry.get("party")), _quote_texts(fact)):
                dropped["parties"] += 1
                continue
            parties.append((party, entry))
        found[fact["id"]] = (company, parties)

    outside: dict[str, dict] = {}
    for fact in facts:
        if fact.get("status") not in store.COUNTING:
            continue
        company, parties = found[fact["id"]]
        for named in [company] + [party for party, _ in parties]:
            if named is not None and not named["pack"]:
                outside.setdefault(named["key"], {"name": named["name"], "sources": []})["sources"].append(
                    fact.get("source_id"))
    own = sorted(((record["name"], key) for key, record in outside.items()
                  if count_clusters(record["sources"], sources) >= OWN_PAGE_SOURCES),
                 key=lambda named: (named[0].casefold(), named[0]))

    listed = sorted(pack.listed, key=lambda company: not company["home"])
    entries = [{"key": f"c{number}", "name": name, "home": home, "group": group, "facts": 0}
               for number, (name, home, group) in enumerate(
                   [(company["name"], company["home"], "pack") for company in listed]
                   + [(name, False, "own") for name, _ in own], start=1)]
    by_company_key = dict(zip([tidy.company_key(company["name"]) for company in listed] + [key for _, key in own],
                              entries))

    def record(named: dict | None) -> dict:
        if named is None:
            return dict(_NONE)
        entry = by_company_key.get(named["key"])
        if entry is None:
            return {"key": "other", "name": named["name"], "group": "other", "home": False}
        return {"key": entry["key"], "name": entry["name"], "group": entry["group"], "home": entry["home"]}

    counts: dict[str, int] = {}
    for fact in facts:
        company, parties = found[fact["id"]]
        fields = fact.get("fields") if isinstance(fact.get("fields"), dict) else {}
        fact["shown_status"] = shown_status(fact, sources)
        fact["date"] = fact_date(sources.get(fact.get("source_id")) or fact.get("source"))
        fact["company"] = record(company)
        fact["countries"] = tidy.countries(fields.get("country"))
        fact["size"] = size_of(fields) if fact.get("kind") == "capacity_move" else None
        fact["connections"] = []
        for party, entry in parties:
            shown = record(party) if party is not None else None
            fact["connections"].append({"party": shown, "party_name": shown["name"] if shown else None,
                                        "tie": entry.get("tie"), "description": entry.get("description")})
        counts[fact["company"]["key"]] = counts.get(fact["company"]["key"], 0) + 1

    for entry in entries:
        entry["facts"] = counts.get(entry["key"], 0)
        entry["only_connections"] = entry["group"] == "own" and entry["facts"] == 0   # kept only as a party
    for key in ("other", "none"):
        if counts.get(key):
            entries.append({"key": key, "name": None, "home": False, "group": key, "facts": counts[key]})
    return {"companies": entries, "names_dropped": dropped, "by_id": {fact["id"]: fact for fact in facts}}


def shown_name(run: dict, name):
    """The name the report shows for a company written as `name`: a pack company's pack name, else the tidy name;
    `name` itself when it is blank or not text."""
    found = tidy.Companies.from_run(run).resolve(name)
    return found["name"] if found is not None else name


def order(facts: list[dict], company_list: list[dict]) -> list[dict]:
    """Arranged facts in the order of the companies, then newest date first (undated last), then by id."""
    place = {entry["key"]: position for position, entry in enumerate(company_list)}
    by_id = sorted(facts, key=lambda fact: id_number(fact.get("id")))
    by_date = sorted(by_id, key=lambda fact: fact.get("date") or "", reverse=True)   # stable: ties keep id order
    return sorted(by_date, key=lambda fact: place.get(fact["company"]["key"], len(place)))
