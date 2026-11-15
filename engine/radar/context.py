"""The passage around a quote, for the support checker.

A quote can be found word for word and still mislead, for example when it is cut just after "not". No matching
rule can catch that, so the checker reads each quote inside its own sentence. This module finds that sentence in
the saved copy and hands it over, with the sentences next to it, as data. It only reads: nothing is written into
the run folder, and the text of a source is never interpreted.

The text handed over is the saved copy as it is, line breaks included, not the normalised text the matching uses.
"""
import re
from pathlib import Path

from .quotes import find_quote
from .store import read_facts, read_sources
from .textnorm import is_cjk
from .verify import (_read_copy, content_digest, is_early_signal, is_withdrawn, quote_found, site_of,
                     supporting_entries, text_id)

CONTEXT_WORDS = 80
SOURCE_FIELDS = ("url", "final_url", "publisher", "title", "date", "type", "speaker", "interest", "language",
                 "data_class")

_CLOSERS = "\"'”’»)]"
_CJK_CLOSERS = "”’」』）)]"   # right quotation marks, corner brackets, full-width bracket
# A unit ends at a blank line; after `.`, `!` or `?` (and any closing marks) when white space or the end follows;
# and after the full-width full stop, exclamation mark or question mark, which no space follows in Chinese or
# Japanese text.
_UNIT_END = re.compile(
    r"(?P<blank>(?:\r\n|\r|\n)[^\S\r\n]*(?:\r\n|\r|\n)\s*)"
    r"|(?P<stop>[.!?]+[" + re.escape(_CLOSERS) + r"]*(?=\s|\Z)|[。！？]+[" + re.escape(_CJK_CLOSERS) + r"]*)"
)


def sentence_units(text: str) -> list[tuple[int, int]]:
    """Start and end offsets of each sentence in the raw text, without the white space between sentences."""
    units = []
    position = 0

    def add(start: int, end: int) -> None:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end:
            units.append((start, end))

    for match in _UNIT_END.finditer(text):
        add(position, match.start() if match.lastgroup == "blank" else match.end())
        position = match.end()
    add(position, len(text))
    return units


def locate(quote: str, text: str, max_units: int = 12) -> tuple[int, int] | None:
    """First and last unit index of the shortest run of neighbouring units in which the quote is found.

    Each run is cut from the raw text, so a word split at a line end stays as the copy has it. A run counts only if
    the quote is also found in the run widened by the word on each side that belongs to the neighbouring units: the
    whole-words rules look at the words next to a match (a word split at a line end, a number grouped with a space),
    and a bare slice would hide them. None when no run of up to `max_units` units holds the quote.
    """
    units = sentence_units(text)
    for length in range(1, max_units + 1):
        for first in range(len(units) - length + 1):
            last = first + length - 1
            if (find_quote(quote, text[units[first][0]:units[last][1]]).passed
                    and find_quote(quote, _widened(text, units, first, last)).passed):
                return first, last
    return None


def _widened(text: str, units: list[tuple[int, int]], first: int, last: int) -> str:
    """The run from `first` to `last`, plus the last word of the unit before it and the first word of the unit
    after it, with the white space between kept as the copy has it."""
    start, end = units[first][0], units[last][1]
    if first > 0:
        begin = start
        while begin > units[first - 1][0] and text[begin - 1].isspace():
            begin -= 1
        while begin > units[first - 1][0] and not text[begin - 1].isspace():
            begin -= 1
        start = begin
    if last + 1 < len(units):
        stop = end
        while stop < units[last + 1][1] and text[stop].isspace():
            stop += 1
        while stop < units[last + 1][1] and not text[stop].isspace():
            stop += 1
        end = stop
    return text[start:end]


def _word_spans(text: str) -> list[tuple[int, int]]:
    """Each word's offsets: a run without white space, but in Chinese and Japanese two characters count as one word."""
    spans = []
    position, size = 0, len(text)
    while position < size:
        if text[position].isspace():
            position += 1
            continue
        end = position + 1
        if is_cjk(text[position]):
            if end < size and is_cjk(text[end]):
                end += 1
        else:
            while end < size and not text[end].isspace() and not is_cjk(text[end]):
                end += 1
        spans.append((position, end))
        position = end
    return spans


def _nearest_words(text: str, keep_end: bool) -> str:
    """`text` cut to the 80 words at its end (before the passage) or at its start (after it).

    The mark `…` joins the cut edge's word without a space, so the cut text still has exactly 80 words.
    """
    spans = _word_spans(text)
    if len(spans) <= CONTEXT_WORDS:
        return text
    if keep_end:
        return "…" + text[spans[-CONTEXT_WORDS][0]:]
    return text[:spans[CONTEXT_WORDS - 1][1]] + "…"


def _quote_entry(role: str, source_id, quote, translation, text: str | None, sentences: int) -> dict:
    found = text is not None and quote_found(quote, text)
    entry = {"role": role, "source_id": source_id, "quote": quote, "translation": translation,
             "found": found, "located": False, "before": None, "passage": None, "after": None}
    span = locate(quote, text) if found else None
    if span is None:
        return entry
    units = sentence_units(text)
    first, last = span
    before_units = units[max(0, first - sentences):first]
    after_units = units[last + 1:last + 1 + sentences]
    entry.update(
        located=True,
        before=_nearest_words(text[before_units[0][0]:before_units[-1][1]], True) if before_units else "",
        passage=text[units[first][0]:units[last][1]],
        after=_nearest_words(text[after_units[0][0]:after_units[-1][1]], False) if after_units else "")
    return entry


def _source_entry(source: dict | None) -> dict:
    """What the checker is told about a source: its description, the address asked for (`url`), the address the copy
    came from when that was another one (`final_url`, else null), and whether that address is on another site than
    the one asked for (`passed_on_to_another_site`), so a copy taken from somewhere else is never judged unseen."""
    source = source or {}
    entry = {name: source.get(name) for name in SOURCE_FIELDS}
    final_url = entry["final_url"]
    entry["passed_on_to_another_site"] = (isinstance(final_url, str) and bool(final_url)
                                          and site_of(final_url) != site_of(entry["url"]))
    return entry


def packet(run_dir: Path, fact_id: str, sentences: int = 1) -> dict:
    """What the support checker needs to judge one fact: the fact, each quote in its passage, and each source."""
    run_dir = Path(run_dir)
    fact = read_facts(run_dir).get(fact_id)
    if fact is None:
        raise ValueError(f"unknown fact id: {fact_id}")
    sources = read_sources(run_dir)
    wanted = [("main", text_id(fact.get("source_id")), fact.get("quote"), fact.get("quote_translation"))]
    wanted += [("supporting", text_id(entry.get("source_id")), entry.get("quote"), entry.get("quote_translation"))
               for entry in supporting_entries(fact)]
    quotes = []
    for role, source_id, quote, translation in wanted:
        text, _ = _read_copy(run_dir, sources.get(source_id))
        quotes.append(_quote_entry(role, source_id, quote, translation, text, sentences))
    return {
        "fact_id": fact_id,
        "kind": fact.get("kind"),
        "statement": fact.get("statement"),
        "fields": fact.get("fields"),
        "certainty": fact.get("certainty"),
        "tentative_reason": fact.get("tentative_reason"),
        "primary_source": fact.get("primary_source"),
        "early_signal": is_early_signal(fact, sources),
        "quotes": quotes,
        "sources": {entry["source_id"]: _source_entry(sources.get(entry["source_id"])) for entry in quotes},
    }


def _all_quotes_found(run_dir: Path, fact: dict, sources: dict[str, dict]) -> bool:
    wanted = [(text_id(fact.get("source_id")), fact.get("quote"))]
    wanted += [(text_id(entry.get("source_id")), entry.get("quote")) for entry in supporting_entries(fact)]
    for source_id, quote in wanted:
        text, _ = _read_copy(run_dir, sources.get(source_id))
        if text is None or not quote_found(quote, text):
            return False
    return True


def open_checks(run_dir: Path) -> list[str]:
    """Ids of the facts that are not withdrawn, whose quotes are all found now, and that lack a current verdict."""
    run_dir = Path(run_dir)
    sources = read_sources(run_dir)
    open_ids = []
    for fact_id, fact in read_facts(run_dir).items():
        if is_withdrawn(fact) or not _all_quotes_found(run_dir, fact, sources):
            continue
        support = (fact.get("checks") or {}).get("support")
        if not isinstance(support, dict) or support.get("content_sha256") != content_digest(fact):
            open_ids.append(fact_id)
    return open_ids
