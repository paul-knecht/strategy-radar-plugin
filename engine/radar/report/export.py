"""The two table files of a report: every fact and every source as rows a spreadsheet program can open.

Both functions are pure and return the whole file as text: comma-separated, every cell in double quotes, lines
ending in CRLF (the builder writes it as UTF-8 with a byte-order mark). Every cell passes through `csv_safe`, so
source text that starts like a formula (`=`, `+`, `-`, `@`), also right after a semicolon or tab where a program
set to another separator would start a new cell, is never run as one when the table is opened.
"""
import csv
import io
import re
import unicodedata

from ..textnorm import normalise
from ..verify import is_early_signal

_FORMULA_SIGNS = ("=", "+", "-", "@")
_BLANK_CATEGORIES = ("Zs", "Zl", "Zp", "Cc", "Cf")   # spaces, separators, control and format characters
_LINE_BREAK = re.compile("\r\n|[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]")
_CELL_SEPARATORS = (";", "\t")   # where a program set to a semicolon or tab separator starts a new cell
ENTRY_SEPARATOR = " | "   # between the entries of one cell that lists several quotes (a quote may hold a semicolon)

FACT_COLUMNS = ("fact_id", "illustrative", "status", "status_reason", "data_class", "kind", "early_signal", "company",
                "home_company", "move_type", "stage", "site", "country", "what_added", "size_value", "size_unit",
                "announced", "planned_start", "access", "delivery", "statement", "quote", "quote_language",
                "quote_translation", "supporting_quotes", "supporting_sources", "supporting_translations",
                "source_id", "source_title", "source_publisher", "source_date", "source_url")
SOURCE_COLUMNS = ("source_id", "illustrative", "data_class", "type", "publisher", "title", "date", "url", "final_url", "speaker", "interest",
                  "language", "saved_at", "saved_by", "access", "access_reason", "based_on", "supplied_by", "basis")
_FIELD_COLUMNS = ("company", "move_type", "stage", "site", "country", "what_added", "size_value", "size_unit",
                  "announced", "planned_start", "access", "delivery")


def _starts_like_a_formula(text: str) -> bool:
    """Whether a spreadsheet program could read `text` as a formula.

    Decided on a probe: the text in compatibility form (so full-width signs count) without its leading
    spaces, line breaks, control and format characters (which a program may skip over).
    """
    probe = unicodedata.normalize("NFKC", text)
    start = 0
    while start < len(probe) and unicodedata.category(probe[start]) in _BLANK_CATEGORIES:
        start += 1
    return probe.startswith(_FORMULA_SIGNS, start)


def csv_safe(value) -> str:
    """A cell's text: None is empty, a list is joined with `; `, each line break becomes a space, and a formula
    start gets an apostrophe in front, at the start of the cell and right after every semicolon or tab in it.

    The apostrophe goes on the original text; text is otherwise written unchanged.
    """
    if value is None:
        return ""
    text = "; ".join(str(item) for item in value) if isinstance(value, list) else str(value)
    text = _LINE_BREAK.sub(" ", text)
    parts = []
    for index, ch in enumerate(text):
        parts.append(ch)
        if ch in _CELL_SEPARATORS and _starts_like_a_formula(text[index + 1:]):
            parts.append("'")
    text = "".join(parts)
    return "'" + text if _starts_like_a_formula(text) else text


def _entries(texts) -> str:
    """Several texts in one cell, in order, joined with ENTRY_SEPARATOR. An entry after the first that starts like a
    formula gets an apostrophe in front, as the start of a cell does (csv_safe defends the start and the rest)."""
    texts = ["" if text is None else str(text) for text in texts]
    return ENTRY_SEPARATOR.join("'" + text if index and _starts_like_a_formula(text) else text
                                for index, text in enumerate(texts))


def _id_number(record_id) -> int:
    digits = "".join(ch for ch in str(record_id) if ch.isdigit())
    return int(digits) if digits else 0


def _company_key(company) -> str:
    return normalise(company).casefold() if isinstance(company, str) else ""


def _table(columns, records) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n", quoting=csv.QUOTE_ALL)
    writer.writerow(columns)
    for record in records:
        writer.writerow([csv_safe(record.get(column)) for column in columns])
    return out.getvalue()


def _illustrative(model: dict) -> str:
    """The `illustrative` cell of every row: `yes` in an illustrative run, so a table passed on alone still says so."""
    return "yes" if model.get("illustrative") else ""


def facts_csv(model: dict) -> str:
    """One row per fact in id order, rejected facts included."""
    home = _company_key(model.get("home_company"))
    records = []
    for fact in sorted(model["facts"] + model["rejected"], key=lambda fact: _id_number(fact["id"])):
        fields = fact.get("fields") if isinstance(fact.get("fields"), dict) else {}
        source = fact.get("source") or {}
        supporting = [entry for entry in fact.get("supporting") or [] if isinstance(entry, dict)]
        record = {"fact_id": fact["id"], "illustrative": _illustrative(model), "status": fact.get("status"), "status_reason": fact.get("status_reason"),
                  "data_class": fact.get("data_class"), "kind": fact.get("kind"),
                  "early_signal": "yes" if is_early_signal(fact) else "",
                  "home_company": "yes" if home and _company_key(fields.get("company")) == home else "",
                  "statement": fact.get("statement"), "quote": fact.get("quote"),
                  "quote_language": fact.get("quote_language"), "quote_translation": fact.get("quote_translation"),
                  "supporting_quotes": _entries(entry.get("quote") for entry in supporting),
                  "supporting_sources": _entries(entry.get("source_id") for entry in supporting),
                  # empty unless an entry has a translation; then one entry for each quote, in order
                  "supporting_translations": (_entries(entry.get("quote_translation") for entry in supporting)
                                              if any(entry.get("quote_translation") for entry in supporting) else ""),
                  "source_id": fact.get("source_id"), "source_title": source.get("title"),
                  "source_publisher": source.get("publisher"), "source_date": source.get("date"),
                  "source_url": source.get("url")}
        record.update({name: fields.get(name) for name in _FIELD_COLUMNS})
        records.append(record)
    return _table(FACT_COLUMNS, records)


def sources_csv(model: dict) -> str:
    """One row per source in id order."""
    records = []
    for source in sorted(model["sources"], key=lambda source: _id_number(source["id"])):
        provenance = source.get("provenance") if isinstance(source.get("provenance"), dict) else {}
        records.append(dict(source, source_id=source["id"], illustrative=_illustrative(model),
                            supplied_by=provenance.get("supplied_by"), basis=provenance.get("basis")))
    return _table(SOURCE_COLUMNS, records)
