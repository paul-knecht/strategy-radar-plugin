"""The company pack: a small settings file that says who a company is, which strategic question it cares about,
which other companies to watch, where to look, and the words and units of its industry.

A pack holds pointers, not facts. A competitor named in a pack is only a candidate until a source confirms what it
does, and a question taken from the company's own statements carries the quote and the address where it will be
checked. `check_pack` never raises on a hand-edited file: every problem becomes a `Problem` with a fixed message that
has its own explanation in `explanations_en.json`, worded for a pack. `window` works out the period to search.
"""
import calendar
import json
import re
from datetime import date
from pathlib import Path

from . import store
from .fetch import check_url
from .schema import Problem, _filled, _Problems
from .textnorm import quote_units

PLACE_KINDS = ("investor_relations", "press_room", "filings", "annual_reports", "regulator", "trade_press",
               "permits", "job_postings")
SUGGESTED_BY = ("user", "search")
DEFAULT_MONTHS = 36
MAX_MONTHS = 120

# The settings a pack may hold, and the settings of each entry in a list.
KEYS = ("id", "company", "industry", "illustrative", "strategic_questions", "competitors", "watch", "places",
        "vocabulary", "units", "demand_drivers", "languages", "time_window_months")
QUESTION_KEYS = ("text", "framing", "evidence", "framed_by")
EVIDENCE_KEYS = ("url", "quote")
CANDIDATE_KEYS = ("name", "status", "suggested_by", "found_at")
PLACE_KEYS = ("kind", "name", "url")
VOCABULARY_KEYS = ("term", "meaning")

_ID = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?")   # no hyphen at either end


def is_pack_id(name) -> bool:
    """Whether `name` has the form of a pack id: lower-case letters, digits and inner hyphens."""
    return isinstance(name, str) and _ID.fullmatch(name) is not None

# The messages. Each has its own entry in explanations_en.json.
NOT_READABLE = "the pack cannot be read"
TOO_DEEP = "the pack is nested too deeply to read"
NOT_SETTINGS = "the pack must be a set of named settings"
ENTRY_NOT_SETTINGS = "a pack entry must be a set of named settings"
UNKNOWN_KEY = "the pack has a setting that is not known"
ID_FORMAT = "the pack's id may use only lower-case letters, digits and hyphens, and must not start or end with a hyphen"
ID_FILE = "the pack's file name does not match its id"
EMPTY = "a pack setting must not be left empty"
FRAMING_NOT_ALLOWED = "a question's framing must be company or user"
SUGGESTED_BY_NOT_ALLOWED = "who suggested a name must be user or search"
ILLUSTRATIVE_NOT_ALLOWED = "the illustrative mark must be true or false"
KIND_NOT_ALLOWED = "the kind of a place to look is not one the pack allows"
EVIDENCE_ADDRESS = "an evidence address needs a web address starting with http or https and holding no password"
PLACE_ADDRESS = "a place to look needs a web address starting with http or https and holding no password"
AT_LEAST_ONE = "a pack list needs at least one entry"
NOT_LIST = "a pack setting must be a list"
NOT_TEXT = "a pack list entry must be text"
WINDOW = "must be a whole number from 1 to 120"
CANDIDATES_ONLY = "a pack lists candidates only"
SEARCH_NEEDS_ADDRESS = "a name found by search needs the address where it was found"
COMPANY_NEEDS_QUOTE = "a question taken from the company needs a quote and its address"
USER_NEEDS_FRAMER = "a question framed by the user must say who framed it"


def _is_web_address(value) -> bool:
    """Judged by the form check of the download (`fetch.check_url`), so a pack never names an address that
    `save-source` would refuse, and the other way round. The pack keeps its own messages."""
    if not isinstance(value, str):
        return False
    try:
        check_url(value)
    except ValueError:   # also what urlsplit raises for a damaged address: the pack check never raises
        return False
    return True


def _cannot_be_saved(data) -> bool:
    """True if some text of the pack holds a character that UTF-8 cannot write (a lone surrogate)."""
    todo = [data]
    while todo:
        item = todo.pop()
        if isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeEncodeError:
                return True
        elif isinstance(item, dict):
            todo.extend(item.keys())
            todo.extend(item.values())
        elif isinstance(item, list):
            todo.extend(item)
    return False


def load(path: Path) -> tuple[dict | None, Problem | None]:
    """The pack in `path` and no problem, or no pack and the one problem that stopped it from being read."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except RecursionError:
        return None, Problem(path.name, None, TOO_DEEP)
    except (OSError, ValueError):   # missing, empty, a folder, not UTF-8, not JSON
        return None, Problem(path.name, None, NOT_READABLE)
    if not isinstance(data, dict):
        return None, Problem(path.name, None, NOT_SETTINGS)
    if _cannot_be_saved(data):
        return None, Problem(path.name, None, NOT_READABLE)
    return data, None


# --- the checks -------------------------------------------------------------

def _text(out: _Problems, file: str, record: dict, key: str, prefix: str = "") -> None:
    if not _filled(record.get(key)):
        out.add(file, prefix + key, EMPTY)


def _unknown(out: _Problems, file: str, record: dict, allowed: tuple, prefix: str = "") -> None:
    for key in record:
        if key not in allowed:
            out.add(file, prefix + key, UNKNOWN_KEY)


def _list(out: _Problems, file: str, record: dict, key: str, at_least_one: bool = False) -> list | None:
    value = record.get(key)
    if not isinstance(value, list):
        out.add(file, key, NOT_LIST)
        return None
    if at_least_one and not value:
        out.add(file, key, AT_LEAST_ONE)
        return None
    return value


def _entries(out: _Problems, file: str, record: dict, key: str, at_least_one: bool = False):
    """Yield (position, entry) for every entry of the list `key` that is a set of named settings."""
    for index, entry in enumerate(_list(out, file, record, key, at_least_one) or []):
        if isinstance(entry, dict):
            yield f"{key}[{index}].", entry
        else:
            out.add(file, f"{key}[{index}]", ENTRY_NOT_SETTINGS)


def _check_id(out: _Problems, file: str, data: dict) -> None:
    pack_id = data.get("id")
    if not (isinstance(pack_id, str) and _ID.fullmatch(pack_id)):
        out.add(file, "id", ID_FORMAT)
    elif file.removesuffix(".json") != pack_id:
        out.add(file, "id", ID_FILE)


def _has_pointer(evidence) -> bool:
    """A list of at least one quote of 5 to 50 words, each with the web address it comes from."""
    if not isinstance(evidence, list) or not evidence:
        return False
    for item in evidence:
        if not (isinstance(item, dict) and _is_web_address(item.get("url")) and isinstance(item.get("quote"), str)
                and 5 <= quote_units(item["quote"]) <= 50):
            return False
    return True


def _check_evidence_addresses(out: _Problems, file: str, question: dict, where: str) -> None:
    """Evidence is optional on a question that is not taken from the company, but every address in it is checked."""
    if "evidence" not in question:
        return
    evidence = question["evidence"]
    if not isinstance(evidence, list):
        out.add(file, where + "evidence", NOT_LIST)
        return
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            out.add(file, f"{where}evidence[{index}]", ENTRY_NOT_SETTINGS)
        elif not _is_web_address(item.get("url")):
            out.add(file, f"{where}evidence[{index}].url", EVIDENCE_ADDRESS)


def _check_questions(out: _Problems, file: str, data: dict) -> None:
    for where, question in _entries(out, file, data, "strategic_questions", at_least_one=True):
        _text(out, file, question, "text", where)
        framing = question.get("framing")
        if not (isinstance(framing, str) and framing in store.FRAMING):
            out.add(file, where + "framing", FRAMING_NOT_ALLOWED)
        elif framing == "company":
            if not _has_pointer(question.get("evidence")):
                out.add(file, where + "evidence", COMPANY_NEEDS_QUOTE)
        elif not _filled(question.get("framed_by")):
            out.add(file, where + "framed_by", USER_NEEDS_FRAMER)
        if framing != "company":
            _check_evidence_addresses(out, file, question, where)
        for index, item in enumerate(question["evidence"] if isinstance(question.get("evidence"), list) else []):
            if isinstance(item, dict):
                _unknown(out, file, item, EVIDENCE_KEYS, f"{where}evidence[{index}].")
        _unknown(out, file, question, QUESTION_KEYS, where)


def _check_candidates(out: _Problems, file: str, data: dict, key: str) -> None:
    for where, entry in _entries(out, file, data, key):
        _text(out, file, entry, "name", where)
        if entry.get("status") != "candidate":
            out.add(file, where + "status", CANDIDATES_ONLY)
        suggested_by = entry.get("suggested_by")
        if not (isinstance(suggested_by, str) and suggested_by in SUGGESTED_BY):
            out.add(file, where + "suggested_by", SUGGESTED_BY_NOT_ALLOWED)
        elif suggested_by == "search" and not _is_web_address(entry.get("found_at")):
            out.add(file, where + "found_at", SEARCH_NEEDS_ADDRESS)
        _unknown(out, file, entry, CANDIDATE_KEYS, where)


def _check_places(out: _Problems, file: str, data: dict) -> None:
    for where, place in _entries(out, file, data, "places", at_least_one=True):
        kind = place.get("kind")
        if not (isinstance(kind, str) and kind in PLACE_KINDS):
            out.add(file, where + "kind", KIND_NOT_ALLOWED)
        _text(out, file, place, "name", where)
        if not _is_web_address(place.get("url")):
            out.add(file, where + "url", PLACE_ADDRESS)
        _unknown(out, file, place, PLACE_KEYS, where)


def _check_vocabulary(out: _Problems, file: str, data: dict) -> None:
    if "vocabulary" not in data:
        return
    for where, entry in _entries(out, file, data, "vocabulary"):
        _text(out, file, entry, "term", where)
        _text(out, file, entry, "meaning", where)
        _unknown(out, file, entry, VOCABULARY_KEYS, where)


def _check_words(out: _Problems, file: str, data: dict, key: str, at_least_one: bool = False) -> None:
    for index, word in enumerate(_list(out, file, data, key, at_least_one) or []):
        if not isinstance(word, str):
            out.add(file, f"{key}[{index}]", NOT_TEXT)
        elif not word.strip():
            out.add(file, f"{key}[{index}]", EMPTY)


def months_of(data: dict) -> int | None:
    """The time window of a pack in months: 36 if it has none, None if its value is refused."""
    if "time_window_months" not in data:
        return DEFAULT_MONTHS
    months = data["time_window_months"]
    return months if type(months) is int and 1 <= months <= MAX_MONTHS else None


def check(data: dict, file_name: str) -> list[Problem]:
    """What is wrong with a pack that was read, in the order of the format."""
    out = _Problems()
    _check_id(out, file_name, data)
    _text(out, file_name, data, "company")
    _text(out, file_name, data, "industry")
    if not isinstance(data.get("illustrative"), bool):
        out.add(file_name, "illustrative", ILLUSTRATIVE_NOT_ALLOWED)
    _check_questions(out, file_name, data)
    _check_candidates(out, file_name, data, "competitors")
    _check_candidates(out, file_name, data, "watch")
    _check_places(out, file_name, data)
    _check_vocabulary(out, file_name, data)
    _check_words(out, file_name, data, "units")
    _check_words(out, file_name, data, "demand_drivers")
    _check_words(out, file_name, data, "languages", at_least_one=True)
    if months_of(data) is None:
        out.add(file_name, "time_window_months", WINDOW)
    _unknown(out, file_name, data, KEYS)
    return out.items


def check_pack(path: Path) -> list[Problem]:
    """What is wrong with the pack in `path`. Never raises."""
    path = Path(path)
    data, unreadable = load(path)
    return [unreadable] if unreadable else check(data, path.name)


def summary(data: dict) -> dict:
    """The three things the command says about a pack it read; a value of the wrong kind is left out."""
    company, pack_id, illustrative = data.get("company"), data.get("id"), data.get("illustrative")
    return {"id": pack_id if isinstance(pack_id, str) else None,
            "company": company if isinstance(company, str) else None,
            "illustrative": illustrative if isinstance(illustrative, bool) else None}


# --- the time window --------------------------------------------------------

def window(months: int, today: date) -> dict:
    """The period to search: from the same day `months` months before `today` (or that month's last day) until today."""
    if type(months) is not int or months < 1:
        raise ValueError("months must be a whole number of 1 or more")
    year, month = divmod(today.year * 12 + today.month - 1 - months, 12)
    month += 1
    first = date(year, month, min(today.day, calendar.monthrange(year, month)[1]))
    return {"months": months, "from": first.isoformat(), "until": today.isoformat()}
