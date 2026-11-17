"""The visuals of the HTML report, and the data behind the tables of the Markdown report.

Plain HTML and CSS only: tables, lists and `div` bars. The one inline style value the engine writes is the
width of a bar, a whole percentage computed here from sourced numbers. Every string that comes from the
model reaches the page through `esc` and nothing else; fixed text comes from `labels_en.json`.
Each function returns an HTML fragment, or an empty string when there is nothing to show. The functions
work on the model's fact dicts and on bare ones that carry no `source` or `data_class`.
"""
import html
import json
import re
from decimal import Decimal, ROUND_HALF_UP

from .. import projects, store
from ..textnorm import normalise
from . import companies as company_view
from .numbers import shown
from .model import fact_notes, field_label, group_by_company, load_labels, unit_for

_TOKEN = re.compile(r"[a-z][a-z0-9_]*")
_SAFE_URL = re.compile(r"https?://[^\s\x00-\x1f\x7f]+", re.IGNORECASE)
_YEAR = re.compile(r"(?<!\d)(?:19|20|21)\d{2}(?!\d)")
DELIVERY_OUTCOMES = ("on_time", "delayed", "cancelled")
ARROW = "→"


# --- escaping and small parts (html.py uses these too, so there is one escaping path) ---

def esc(value) -> str:
    """The only way model text enters the page: HTML-escaped, quotes included, so it is safe in any quoted attribute."""
    return "" if value is None else html.escape(str(value), quote=True)


def token(value) -> str:
    """An engine constant such as `under_construction`, for use in a class name; anything else becomes `other`."""
    return value if isinstance(value, str) and _TOKEN.fullmatch(value) else "other"


def join(parts, separator=" ") -> str:
    return separator.join(part for part in parts if part)


def pill(css: str, text) -> str:
    return f'<span class="pill {esc(css)}">{esc(text)}</span>'


def class_pill(data_class, labels: dict) -> str:
    """Anything that is not public carries its class label."""
    if data_class in (None, "public"):
        return ""
    return pill(f"class-{token(data_class)}", labels.get(f"class_{data_class}", data_class))


def marks(fact: dict, labels: dict) -> str:
    """The labels that make an uncertain, rejected or non-public fact recognisable wherever it appears."""
    return "".join(pill(_note_class(kind, value), text) for kind, value, text in fact_notes(fact, labels))


def _note_class(kind: str, value) -> str:
    """The class of a note's pill. "One source only" is a kind of uncertain, so it keeps the uncertain look."""
    if (kind, value) == ("status", "single_source"):
        return "status-uncertain status-single_source"
    return f"{kind}-{token(value)}"


def fact_ref(fact: dict, labels: dict) -> str:
    """A link to a fact. An uncertain fact carries the uncertain label and a non-public one its class label."""
    fact_id = fact.get("id")
    if fact.get("status") in store.COUNTING:
        link = f'<a href="#{esc(fact_id)}" data-view="facts">{esc(fact_id)}</a>'
    else:
        link = esc(fact_id)
    return f'<span class="factref">{link}{marks(fact, labels)}</span>'


def address(url) -> str:
    """A link only for http and https addresses; anything else is shown as text."""
    if url in (None, ""):
        return ""
    if isinstance(url, str) and _SAFE_URL.fullmatch(url):
        return f'<a href="{esc(url)}" rel="noopener noreferrer" target="_blank">{esc(url)}</a>'
    return f'<span class="url">{esc(url)}</span>'


def _fmt(labels: dict, key: str, **values) -> str:
    """A label with `{placeholders}` filled from escaped values."""
    return esc(labels[key]).format(**{name: esc(value) for name, value in values.items()})


def _listing(items, css: str = "", item_css: str = "") -> str:
    items = [item for item in items if item]
    attribute = f' class="{esc(css)}"' if css else ""
    item_attribute = f' class="{esc(item_css)}"' if item_css else ""
    return f"<ul{attribute}>" + "".join(f"<li{item_attribute}>{item}</li>" for item in items) + "</ul>" if items else ""


def _table(css: str, head: list[str], rows: list[str], corner: str = "") -> str:
    """A table whose corner cell is empty, so the column headers are the only `th scope="col"` cells; or, given a
    `corner`, headed by it (the heading of the column of row headings)."""
    corner_cell = f'<th scope="col" class="corner">{corner}</th>' if corner else "<td></td>"
    header = f"<tr>{corner_cell}" + "".join(f'<th scope="col">{cell}</th>' for cell in head) + "</tr>"
    return (f'<div class="table-wrap"><table class="{css}"><thead>{header}</thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


# --- facts of one kind ---

def _fields(fact: dict) -> dict | None:
    fields = fact.get("fields")
    return fields if fact.get("kind") == "capacity_move" and isinstance(fields, dict) else None


def _moves(facts: list[dict]) -> list[dict]:
    return [fact for fact in facts if _fields(fact) is not None]


def _inside_moves(facts: list[dict]) -> list[dict]:
    """The moves inside the question: only these are compared and counted."""
    return [fact for fact in _moves(facts) if projects.in_question(fact)]


def outside_pill(fact: dict, labels: dict) -> str:
    """The mark of a move outside the question, shown wherever such a move is listed but not counted."""
    return "" if projects.in_question(fact) else pill("outside", labels["pill_outside"])


def _text(value) -> str | None:
    """A stated value as text; blank or missing is None."""
    if value is None or isinstance(value, bool):
        return None
    text = normalise(str(value))
    return text or None


def _access(fact: dict) -> str:
    access = _fields(fact).get("access")
    return access if access in store.ACCESS else "not_stated"


def start_year(value: str | None) -> int | None:
    """The first four-digit year (1900 to 2199) in a planned start such as `Q3 2028` or `2027-06`."""
    found = _YEAR.search(value) if isinstance(value, str) else None
    return int(found.group()) if found else None


def _company_name(fact: dict) -> str:
    """The name the report shows for a fact's company: the model's tidy name, else (a bare fact) the one written."""
    shown = fact.get("company")
    name = shown.get("name") if isinstance(shown, dict) else None
    return _text(name) or _text(_fields(fact).get("company")) or ""


def _site_line(fact: dict) -> str:
    return join([_company_name(fact), _text(_fields(fact).get("site")) or ""], ", ")


# --- timeline ---

def _bar(fact: dict, css: str) -> str:
    link_text = esc(fact.get("id"))
    if fact.get("status") in store.COUNTING:
        return f'<a class="{css}" href="#{link_text}" data-view="facts">{link_text}</a>'
    return f'<span class="{css}">{link_text}</span>'


def _bar_classes(fact: dict, base: str) -> str:
    classes = [base, _access(fact)]
    if fact.get("status") == "uncertain":
        classes.append("uncertain")
    if fact.get("data_class") not in (None, "public"):
        classes.append("non-public")
    return " ".join(classes)


def _timeline_entry(fact: dict, labels: dict) -> str:
    note = _text(_fields(fact).get("site"))
    return ('<span class="entry">' + _bar(fact, _bar_classes(fact, "bar"))
            + (f' <span class="bar-note">{esc(note)}</span>' if note else "") + marks(fact, labels)
            + outside_pill(fact, labels) + "</span>")


def timeline(facts: list[dict], home_company: str | None = None) -> str:
    """One row per company, one column per year from the earliest to the latest planned start; no year is listed below."""
    labels = load_labels()
    dated: dict[str, dict[int, list[dict]]] = {}
    undated, years = [], set()
    groups = group_by_company(_moves(facts), home_company)
    for group in groups:
        for fact in group["moves"]:
            year = start_year(_fields(fact).get("planned_start"))
            if year is None:
                undated.append(fact)
            else:
                dated.setdefault(group["company"], {}).setdefault(year, []).append(fact)
                years.add(year)
    parts = []
    if years:
        columns = range(min(years), max(years) + 1)
        rows = []
        for group in (group for group in groups if group["company"] in dated):
            name = join([esc(group["company"]), pill("home", labels["home_company"]) if group["home"] else ""])
            cells = "".join("<td>" + " ".join(_timeline_entry(fact, labels) for fact in dated[group["company"]].get(year, []))
                            + "</td>" for year in columns)
            attribute = ' class="home"' if group["home"] else ""
            rows.append(f'<tr{attribute}><th scope="row">{name}</th>{cells}</tr>')
        parts.append(_table("timeline", [str(year) for year in columns], rows))
        legend = " ".join(f'<span class="bar {access}">{esc(labels["access_" + access])}</span>' for access in store.ACCESS)
        parts.append(f'<p class="bar-legend">{legend}</p>')
    if undated:
        items = [join([esc(_site_line(fact)), esc(_text(_fields(fact).get("what_added"))), fact_ref(fact, labels),
                       outside_pill(fact, labels)]) for fact in undated]
        parts.append(f'<h4>{esc(labels["start_not_stated"])}</h4>' + _listing(items, "undated"))
    return "\n".join(parts)


# --- move grid and delivery table ---

def _tally(facts: list[dict]) -> dict:
    return {"n": len(facts),
            "uncertain": sum(1 for fact in facts if fact.get("status") == "uncertain"),
            "non_public": sum(1 for fact in facts if fact.get("data_class") not in (None, "public")),
            "outside": sum(1 for fact in facts if not projects.in_question(fact))}


def tally_notes(tally: dict, labels: dict) -> list[str]:
    """What a count includes that a reader must not miss, as plain text."""
    notes = []
    if tally["uncertain"]:
        notes.append(labels["grid_uncertain"].format(n=tally["uncertain"]))
    if tally["non_public"]:
        notes.append(labels["grid_non_public"].format(n=tally["non_public"]))
    if tally.get("outside"):
        notes.append(labels["grid_outside"].format(n=tally["outside"]))
    return notes


def move_counts(facts: list[dict]) -> list[tuple[str, list[dict]]]:
    """Per company, one tally for each move type in the order of `MOVE_TYPES`; moves outside the question are left out."""
    return [(group["company"], [_tally([fact for fact in group["moves"] if _fields(fact).get("move_type") == move])
                                for move in store.MOVE_TYPES])
            for group in group_by_company(_inside_moves(facts), None)]


def delivery_counts(facts: list[dict]) -> list[tuple[str, list[dict]]]:
    """Per company that has a delivery record, one tally each for on time, delayed and cancelled."""
    rows = []
    for group in group_by_company(_moves(facts), None):
        tallies = [_tally([fact for fact in group["moves"] if _fields(fact).get("delivery") == outcome])
                   for outcome in DELIVERY_OUTCOMES]
        if any(tally["n"] for tally in tallies):
            rows.append((group["company"], tallies))
    return rows


def _count_cell(tally: dict, labels: dict) -> str:
    if not tally["n"]:
        return "<td></td>"
    notes = [pill("status-uncertain", labels["grid_uncertain"].format(n=tally["uncertain"]))] if tally["uncertain"] else []
    if tally["non_public"]:
        notes.append(pill("class-internal", labels["grid_non_public"].format(n=tally["non_public"])))
    if tally.get("outside"):
        notes.append(pill("outside", labels["grid_outside"].format(n=tally["outside"])))
    return "<td>" + join([esc(tally["n"])] + notes) + "</td>"


def _count_table(css: str, columns: list[str], rows: list[tuple[str, list[dict]]], labels: dict, corner: str = "") -> str:
    body = ['<tr><th scope="row">' + esc(company) + "</th>" + "".join(_count_cell(tally, labels) for tally in tallies) + "</tr>"
            for company, tallies in rows]
    return _table(css, [esc(label) for label in columns], body, esc(corner))


def move_grid(facts: list[dict]) -> str:
    """Rows are companies, columns the move types; each cell the number of facts, empty when there are none. The
    corner says what the rows are, so a company name is not mistaken for a column heading."""
    labels = load_labels()
    rows = move_counts(facts)
    return (_count_table("grid", [labels[f"move_{move}"] for move in store.MOVE_TYPES], rows, labels, labels["col_company"])
            if rows else "")


def delivery_table(facts: list[dict]) -> str:
    """How often each company delivered on time, late or not at all; nothing at all without such a record."""
    labels = load_labels()
    rows = delivery_counts(facts)
    return _count_table("delivery", [labels[f"delivery_{outcome}"] for outcome in DELIVERY_OUTCOMES], rows, labels) if rows else ""


# --- capacity bars ---

def _size_of(fact: dict) -> dict:
    """The tidy size of a capacity move: the model's, or (a bare fact) the same worked out from its fields."""
    size = fact.get("size")
    return size if isinstance(size, dict) else company_view.size_of(_fields(fact))


def stated_size(fact: dict, sep: str = "") -> str:
    """The size as stated: its value as written (with `sep` between its thousands, where one is given) and its unit
    tidied."""
    fields = _fields(fact)
    value = _text(fields.get("size_value"))
    return join([shown(value, sep) or "", unit_for(value, _size_of(fact).get("unit")) or ""])


def _width(value: Decimal, largest: Decimal) -> int:
    """A whole percentage of the largest value, rounded half up."""
    if largest <= 0:
        return 0
    return int((value * 100 / largest).to_integral_value(rounding=ROUND_HALF_UP))


def _shown_size(fact: dict, labels: dict) -> str:
    """The size for a bar: in the unit the bars compare in, with what was stated next to it when that differs."""
    converted = _size_of(fact).get("converted")
    sep = labels["thousands_separator"]
    if not isinstance(converted, dict):
        return esc(stated_size(fact, sep))
    value = f"{shown(converted['number'], sep)} {converted['unit']}"
    if converted.get("about"):
        value = labels["converted_about"].format(value=value)
    return _fmt(labels, "converted_from", converted=value, stated=stated_size(fact, sep))


def _bar_row(fact: dict, value: Decimal, largest: Decimal, labels: dict) -> str:
    access = _access(fact)
    fill = _bar_classes(fact, "bar-fill")
    return (f'<li class="bar-row"><span class="bar-label">{esc(_site_line(fact))}</span>'
            f'<div class="bar-track"><div class="{fill}" style="width:{_width(value, largest)}%"></div></div>'
            f'<span class="bar-value">{_shown_size(fact, labels)}</span> '
            f'<span class="bar-note">{esc(labels["access_" + access])}</span> {fact_ref(fact, labels)}</li>')


def _comparable_number(size: dict) -> Decimal | None:
    """The size's number in the unit the bars compare in (its conversion where it has one), or None."""
    converted = size.get("converted")
    number = converted["number"] if isinstance(converted, dict) else size.get("number")
    return Decimal(number) if isinstance(number, str) and number else None


def capacity_bars(facts: list[dict]) -> str:
    """Bars for sizes in the same unit, where two units that differ only by a fixed factor (square feet and square
    metres, or one currency in millions and in billions) count as one: the bar is drawn in the unit the family is
    compared in, with what was stated shown next to it. Every other stated size is listed, never compared. A move
    outside the question is left out: it adds another kind of capacity."""
    labels = load_labels()
    groups: dict[str, dict] = {}
    listed = []
    for fact in _inside_moves(facts):
        if not stated_size(fact):
            continue
        size = _size_of(fact)
        unit = size.get("compare_unit")   # as the program tidied it: "m²" must not go through `normalise`
        if not isinstance(unit, str) or not unit.strip():
            listed.append(fact)
            continue
        group = groups.setdefault(unit.casefold(), {"unit": unit, "items": []})
        group["items"].append((fact, _comparable_number(size)))
    parts = []
    for group in groups.values():
        numbers = [(fact, value) for fact, value in group["items"] if value is not None]
        if len(numbers) < 2:
            listed += [fact for fact, _ in group["items"]]
            continue
        listed += [fact for fact, value in group["items"] if value is None]
        largest = max(value for _, value in numbers)
        parts.append(f'<div class="capacity-group"><h4>{esc(group["unit"])}</h4><ul class="bars">'
                     + "".join(_bar_row(fact, value, largest, labels) for fact, value in numbers) + "</ul></div>")
    if listed:
        items = [join([esc(_site_line(fact)) + ":", esc(stated_size(fact, labels["thousands_separator"])), fact_ref(fact, labels)]) for fact in listed]
        parts.append(f'<div class="not-comparable"><p>{esc(labels["not_comparable"])}</p>{_listing(items)}</div>')
    return "\n".join(parts)


# --- totals ---

def totals(calculations: list[dict]) -> str:
    """The engine's own checked totals, as the model resolved them. No arithmetic happens here."""
    labels = load_labels()
    items = []
    for calculation in calculations:
        result, unit = esc(shown(calculation.get("result"), labels["thousands_separator"])), calculation.get("unit")
        value = (f"{result}%" if calculation.get("operation") == "share"
                 else join([result, esc(unit_for(calculation.get("result"), unit))]))
        refs = " ".join(fact_ref(fact, labels) for fact in calculation.get("inputs") or [])
        if calculation.get("whole"):
            refs += " / " + " ".join(fact_ref(fact, labels) for fact in calculation["whole"])
        note = (f' <span class="pill includes-uncertain">{esc(labels["includes_uncertain"])}</span>'
                if calculation.get("includes_uncertain") else "")
        items.append(f'<li class="total" id="{esc(calculation.get("id"))}">{esc(calculation.get("label"))}: '
                     f'{join([value, refs])}{note}</li>')
    return '<ul class="totals">' + "".join(items) + "</ul>" if items else ""


# --- sites by country ---

def _countries_of(fact: dict) -> list[str | None]:
    """The countries a move names, each by its one name: the model's, or (a bare fact) the one written. A move that
    names none is listed under no country (None)."""
    named = fact.get("countries")
    if not isinstance(named, list):
        written = _text(_fields(fact).get("country"))
        named = [written] if written else []
    return [country for country in named if _text(country)] or [None]


def sites_by_country(facts: list[dict]) -> str:
    """Countries alphabetically with the unknown one last, each with its sites and links to the facts. A move that
    names several countries is listed under each."""
    labels = load_labels()
    countries: dict[str, dict] = {}
    for fact in _moves(facts):
        site = _text(_fields(fact).get("site"))
        for country in _countries_of(fact):
            if country is None and site is None:
                continue
            entry = countries.setdefault((country or "").casefold(), {"name": country, "sites": {}})
            entry["sites"].setdefault((site or "").casefold(), {"name": site, "facts": []})["facts"].append(fact)
    ordered = sorted(countries.values(), key=lambda entry: (entry["name"] is None, (entry["name"] or "").casefold()))
    items = []
    for entry in ordered:
        sites = sorted(entry["sites"].values(), key=lambda site: (site["name"] is None, (site["name"] or "").casefold()))
        rows = [join([esc(site["name"] if site["name"] is not None else labels["site_not_stated"]),
                      " ".join(fact_ref(fact, labels) + outside_pill(fact, labels) for fact in site["facts"])])
                for site in sites]
        name = entry["name"] if entry["name"] is not None else labels["country_not_stated"]
        items.append(f'<strong class="country-name">{esc(name)}</strong>' + _listing(rows, "sites"))
    return _listing(items, "countries", "country")


# --- what changed ---

def _entries(value, *keys) -> list[dict]:
    """The dict entries of a list, each reduced to the named keys that hold text."""
    if not isinstance(value, list):
        return []
    return [{key: item.get(key) for key in keys} for item in value if isinstance(item, dict)]


def _field_changes(fields) -> list[tuple[str, object, object]]:
    if not isinstance(fields, dict):
        return []
    changes = []
    for name, pair in fields.items():
        before, after = (pair[0], pair[1]) if isinstance(pair, (list, tuple)) and len(pair) == 2 else (None, pair)
        changes.append((str(name), before, after))
    return changes


def read_changes(changes) -> dict:
    """What `radar compare` stored, in one shape. Missing or malformed parts are left out, not guessed."""
    changes = changes if isinstance(changes, dict) else {}
    unchanged = changes.get("unchanged")
    compared = (changes.get("previous_run"), changes.get("current_run"))
    return {
        "compared": compared if all(isinstance(run, str) and run for run in compared) else None,
        "new": [entry["fact_id"] for entry in _entries(changes.get("new"), "fact_id") if entry["fact_id"]],
        "changed": [{"fact_id": entry["fact_id"], "previous_fact_id": entry["previous_fact_id"],
                     "fields": _field_changes(entry["fields"])}
                    for entry in _entries(changes.get("changed"), "fact_id", "previous_fact_id", "fields")
                    if entry["fact_id"]],
        "source_changed": _entries(changes.get("source_changed"), "fact_id", "previous_fact_id", "url"),
        "source_unavailable": _entries(changes.get("source_unavailable"), "previous_fact_id", "url"),
        "not_found_again": [entry["previous_fact_id"] for entry in _entries(changes.get("not_found_again"), "previous_fact_id")
                            if entry["previous_fact_id"]],
        "possible_matches": _entries(changes.get("possible_matches"), "fact_id", "previous_fact_id", "differing_field"),
        "predictions_due": _entries(changes.get("predictions_due"), "prediction_id", "statement", "by"),
        "unchanged": unchanged if isinstance(unchanged, int) and not isinstance(unchanged, bool) else None,
    }


def field_name(name: str, labels: dict) -> str:
    return labels.get(f"field_{name}", name)


def field_value(name: str, value, labels: dict) -> str:
    """A changed field's value as plain text: its label where that field has one, `not stated` where it is empty."""
    if value is None or value == "":
        return labels["value_not_stated"]
    if isinstance(value, str):
        return field_label(name, value, labels)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def describe(fact: dict | None) -> str:
    """Company and statement of a fact as plain text, or nothing when the fact is not known."""
    if not fact:
        return ""
    fields = fact.get("fields") if isinstance(fact.get("fields"), dict) else {}
    what = _text(fact.get("statement")) or _text(fields.get("what_added")) or ""
    company = _text(fields.get("company"))
    return f"{company}: {what}" if company and what else (company or what)


def changes_view(changes: dict, facts_by_id: dict[str, dict]) -> str:
    """The comparison with the last run. A fact that is no longer found is never called withdrawn."""
    labels = load_labels()
    data = read_changes(changes)

    def current(fact_id) -> str:
        fact = facts_by_id.get(fact_id)
        return join([fact_ref(fact, labels) if fact else esc(fact_id), esc(describe(fact))])

    def earlier(fact_id) -> str:
        return f'<span class="earlier">{_fmt(labels, "changes_earlier", id=fact_id)}</span>'

    def section(key: str, items: list[str], note: str = "", item_css: str = "") -> str:
        return (f'<h3>{esc(labels["changes_" + key])}</h3>{note}' + _listing(items, item_css=item_css)) if items else ""

    changed = []
    for entry in data["changed"]:
        lines = [f'<span class="field">{esc(field_name(name, labels))}</span>: '
                 f'<span class="old">{esc(field_value(name, before, labels))}</span> {ARROW} '
                 f'<span class="new">{esc(field_value(name, after, labels))}</span>'
                 for name, before, after in entry["fields"]]
        changed.append(join([current(entry["fact_id"]), earlier(entry["previous_fact_id"]) if entry["previous_fact_id"] else ""])
                       + _listing(lines, "field-changes", "field-change"))
    matches = []
    for entry in data["possible_matches"]:
        matches.append(join([current(entry["fact_id"]), esc(labels["changes_may_match"]), earlier(entry["previous_fact_id"]) + ".",
                             esc(labels["changes_differs_in"]) + ": " + esc(field_name(entry["differing_field"] or "", labels)) + "."]))
    due = [f'{esc(entry["prediction_id"])}: {_fmt(labels, "changes_due_form", statement=entry["statement"], by=entry["by"])}'
           for entry in data["predictions_due"]]
    parts = [
        f'<p class="compared">{_fmt(labels, "changes_compared", previous=data["compared"][0], current=data["compared"][1])}</p>'
        if data["compared"] else "",
        section("new", [current(fact_id) for fact_id in data["new"]]),
        section("changed", changed),
        section("source_changed", [join([current(entry["fact_id"]), address(entry["url"])]) for entry in data["source_changed"]]),
        section("source_unavailable", [join([earlier(entry["previous_fact_id"]), address(entry["url"])])
                                       for entry in data["source_unavailable"]]),
        section("not_found_again", [earlier(fact_id) for fact_id in data["not_found_again"]],
                f'<p class="note">{esc(labels["changes_not_found_note"])}</p>'),
        section("possible_matches", matches),
        section("predictions_due", due, item_css="prediction-due"),
        f'<p class="unchanged">{_fmt(labels, "changes_unchanged", n=data["unchanged"])}</p>' if data["unchanged"] is not None else "",
    ]
    return "\n".join(part for part in parts if part)
