"""One name per company, country and unit, from fixed lists. For display only.

Nothing here changes a stored fact, its status or what the program counts: the report uses these names to show
"Competitor C Inc." and "competitor c" as one company, "USA" and "U.S." as one country, "sqm" and "m2" as one unit.
A name that is not on a list is kept as written, with its spacing evened.
"""
import functools
import json
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Context, Decimal
from pathlib import Path

from .calc import parse_number
from .textnorm import normalise

_FOLDER = Path(__file__).parent

# --- company names ---------------------------------------------------------------------------------------------------

# Legal endings, each with or without a final dot (the final dot is trimmed before the ending is looked for).
_LEGAL_ENDINGS = (
    "inc", "incorporated", "ltd", "limited", "llc", "gmbh", "ag", "se", "sa", "s.a", "nv", "n.v", "bv", "b.v", "plc",
    "corp", "corporation", "co", "kg", "gmbh & co. kg", "gmbh & co kg", "s.p.a", "spa", "s.r.l", "srl", "oy", "ab",
    "a/s", "pte ltd", "pte. ltd", "pty ltd", "pty. ltd",
)
_ENDING = re.compile(
    r"(?P<head>.+?)[\s,]+(?:" + "|".join(re.escape(e) for e in sorted(_LEGAL_ENDINGS, key=len, reverse=True)) + r")",
    re.IGNORECASE,
)


def _trim_outer_punctuation(text: str) -> str:
    start, end = 0, len(text)
    while start < end and not text[start].isalnum():
        start += 1
    while end > start and not text[end - 1].isalnum():
        end -= 1
    return text[start:end]


def clean_company(name: str) -> str:
    """The name for display: its own letter case, spaces evened, outer punctuation trimmed, legal endings removed.

    A name that is only a legal ending, such as "Inc", is left as it is."""
    text = _trim_outer_punctuation(normalise(name))
    while True:
        found = _ENDING.fullmatch(text)
        head = _trim_outer_punctuation(found.group("head")) if found else ""
        if not head:
            return text
        text = head


def company_key(name: str) -> str:
    """What two spellings of one company share: `clean_company`, case-folded."""
    return clean_company(name).casefold()


def _folded(text: str) -> str:
    """The text in a form to find whole words in: normalised and case-folded."""
    return normalise(text).casefold()


def name_in(names: list[str], texts: list[str]) -> bool:
    """Whether any name appears in any text as whole words: case and spacing ignored, and no letter or digit right
    before or after the name."""
    haystacks = [_folded(text) for text in texts if isinstance(text, str)]
    for name in names:
        wanted = _folded(name) if isinstance(name, str) else ""
        if not wanted:
            continue
        pattern = re.compile(r"(?<![^\W_])" + re.escape(wanted) + r"(?![^\W_])")
        if any(pattern.search(text) for text in haystacks):
            return True
    return False


@dataclass
class Companies:
    """The companies a run's pack lists, and the way any written name is matched to them."""

    listed: list[dict] = field(default_factory=list)
    _by_key: dict[str, dict] = field(default_factory=dict, repr=False)

    @classmethod
    def from_run(cls, run: dict) -> "Companies":
        """From `run["companies"]`; a run made before that key existed has only its `home_company`, the one company."""
        stored = run.get("companies") if isinstance(run, dict) else None
        if isinstance(stored, list):
            entries = [entry for entry in stored if isinstance(entry, dict) and isinstance(entry.get("name"), str)
                       and entry["name"].strip()]
        else:
            home = run.get("home_company") if isinstance(run, dict) else None
            entries = [{"name": home, "other_names": [], "home": True}] if isinstance(home, str) and home.strip() else []
        listed = []
        for entry in entries:
            others = entry.get("other_names")
            others = [n for n in others if isinstance(n, str) and n.strip()] if isinstance(others, list) else []
            listed.append({"name": entry["name"], "other_names": others, "home": entry.get("home") is True})
        by_key: dict[str, dict] = {}
        for company in listed:
            for written in [company["name"], *company["other_names"]]:
                by_key.setdefault(company_key(written), company)
        return cls(listed, by_key)

    def resolve(self, name) -> dict | None:
        """`{"key", "name", "pack", "home"}` for a written name, or None for a blank one."""
        if not isinstance(name, str) or not company_key(name):
            return None
        key = company_key(name)
        company = self._by_key.get(key)
        if company is not None:
            return {"key": company_key(company["name"]), "name": company["name"], "pack": True,
                    "home": company["home"]}
        return {"key": key, "name": clean_company(name), "pack": False, "home": False}

    def names_to_find(self, name) -> list[str]:
        """The names to look for in a quote: a pack company's name and other names; else the name as written and
        its clean form."""
        found = self.resolve(name)
        if found is None:
            return []
        if found["pack"]:
            company = self._by_key[found["key"]]
            return [company["name"], *company["other_names"]]
        written = normalise(name)
        return list(dict.fromkeys([written, found["name"]]))


# --- countries -------------------------------------------------------------------------------------------------------

_COUNTRY_SPLIT = re.compile(r"\s*[,;/&]\s*|\s+and\s+", re.IGNORECASE)


def _country_key(text: str) -> str:
    return re.sub(r"[.\s]", "", normalise(text).casefold())


@functools.lru_cache(maxsize=None)
def _country_names() -> dict[str, str]:
    data = json.loads((_FOLDER / "countries_en.json").read_text(encoding="utf-8"))
    return {_country_key(written): country for country, variants in data.items() for written in [country, *variants]}


def countries(value) -> list[str]:
    """The countries a value names, each by its one name. A place not on the list is kept as written."""
    if not isinstance(value, str) or not normalise(value):
        return []
    names = _country_names()
    whole = names.get(_country_key(value))
    if whole is not None:
        return [whole]
    found = []
    for part in _COUNTRY_SPLIT.split(normalise(value)):
        part = normalise(part)
        if part:
            found.append(names.get(_country_key(part), part))
    return list(dict.fromkeys(found))


# --- units and sizes -------------------------------------------------------------------------------------------------

_DIVIDING = Context(prec=400)


def _unit_key(text: str) -> str:
    """Case, spacing, dashes and dots ignored."""
    return re.sub(r"\s+", " ", normalise(text).casefold().replace("-", " ").replace(".", "")).strip()


@functools.lru_cache(maxsize=None)
def _units() -> tuple[dict[str, str], dict[str, dict]]:
    """The unit names by their key, and the families by the name of each unit in them: {"unit": {"family", "base",
    "factor"}}."""
    data = json.loads((_FOLDER / "units_en.json").read_text(encoding="utf-8"))
    names = {_unit_key(written): name for name, variants in data["names"].items() for written in [name, *variants]}
    families = {}
    for family, record in data["families"].items():
        for name, factor in record["factors"].items():
            families[name] = {"family": family, "base": record["base"], "factor": Decimal(factor)}
    return names, families


def unit(value) -> dict | None:
    """`{"name", "family", "factor"}` for a written unit; a unit not on the list keeps its written name and has no
    family. A blank value gives None."""
    if not isinstance(value, str) or not normalise(value):
        return None
    names, families = _units()
    name = names.get(_unit_key(value))
    if name is None:
        return {"name": normalise(value), "family": None, "factor": None}
    member = families.get(name)
    return {"name": name, "family": member["family"] if member else None, "factor": member["factor"] if member else None}


def _plain(number: Decimal) -> str:
    """A number without exponent or trailing zeros: 6, 2.5, 300."""
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _converted(number: Decimal, tidy_unit: dict) -> dict | None:
    """The size in the family's base unit, or None when there is no family or the unit already is the base."""
    member = _units()[1].get(tidy_unit["name"])
    if member is None or member["base"] == tidy_unit["name"]:
        return None
    base_factor = _units()[1][member["base"]]["factor"]
    exact = _DIVIDING.divide(_DIVIDING.multiply(number, member["factor"]), base_factor)
    if exact == exact.to_integral_value():
        return {"number": _plain(exact), "unit": member["base"], "about": False}
    # three significant figures: a converted size is an estimate, not a measurement
    rounded = exact.quantize(Decimal(1).scaleb(exact.adjusted() - 2), rounding=ROUND_HALF_UP)
    return {"number": _plain(rounded), "unit": member["base"], "about": rounded != exact}


def size(value, unit_text) -> dict:
    """A size for display: what was stated, its unit tidied, its number, its value in the family's base unit when that
    differs, and the unit to compare sizes in. The stated value keeps its written form."""
    tidy_unit = unit(unit_text)
    written = str(value).strip() if value is not None else ""
    number = parse_number(value)
    member = _units()[1].get(tidy_unit["name"]) if tidy_unit else None
    return {
        "stated": " ".join(part for part in (written, tidy_unit["name"] if tidy_unit else "") if part),
        "unit": tidy_unit["name"] if tidy_unit else None,
        "number": number,
        "converted": _converted(number, tidy_unit) if number is not None and tidy_unit else None,
        "compare_unit": member["base"] if member else (tidy_unit["name"] if tidy_unit else None),
    }
