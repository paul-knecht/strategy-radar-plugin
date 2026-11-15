"""Plain-language explanations of the problems the gate raises.

Every fixed problem message has an entry in `explanations_en.json` with three parts: what happened, why
and what to do. A key matches when the message contains it. A key may contain `{id}`, which then matches
the fact, source, assumption or scenario named in the message. Without one, the id comes from the file
the problem names (`facts/F3.json` gives F3). `{value}` is the figure in "(computed 6)". `{field}` is the setting
a pack problem names ("this setting" if it names none). A message with no entry gets a generic explanation and
`known: False`. `explain` never raises.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

_EXPLANATIONS_FILE = Path(__file__).with_name("explanations_en.json")
_FILE_ID = re.compile(r"(?:facts|sources)/([A-Za-z0-9_-]+)\.json")
_COMPUTED = re.compile(r"\(computed (.+)\)\s*$")
_UNKNOWN = "?"
_A_SETTING = "this setting"


@lru_cache(maxsize=1)
def _entries() -> tuple:
    """(pattern, entry) pairs, the most specific key first."""
    data = json.loads(_EXPLANATIONS_FILE.read_text(encoding="utf-8"))
    pairs = []
    for key in sorted(data, key=len, reverse=True):
        pattern = r"(?P<id>.+?)".join(re.escape(part) for part in key.split("{id}"))
        pairs.append((re.compile(pattern, re.DOTALL), data[key]))
    return tuple(pairs)


def _text(value) -> str | None:
    return value if isinstance(value, str) else None


def _fill(template: str, ids: dict) -> str:
    return re.sub(r"\{(id|value|field)\}", lambda found: ids[found.group(1)], template)


def _generic(file, message) -> dict:
    where = file if isinstance(file, str) and file else "the run folder"
    return {"known": False,
            "what": f"The report could not be built because of a problem in {where}.",
            "why": message if isinstance(message, str) else "",
            "do": "Fix the named file or run the step that writes it again."}


def explain(problem) -> dict:
    """What a problem means, why it arose and what to do about it, for a reader who is not a programmer."""
    file = message = None
    try:
        file, message = _text(getattr(problem, "file", None)), _text(getattr(problem, "message", None))
        if message is None:
            return _generic(file, message)
        for pattern, entry in _entries():
            found = pattern.search(message)
            if not found:
                continue
            from_file = _FILE_ID.fullmatch(file) if file else None
            named = found.groupdict().get("id") or (from_file.group(1) if from_file else _UNKNOWN)
            computed = _COMPUTED.search(message)
            field = _text(getattr(problem, "field", None))   # the setting a pack problem is about
            values = {"id": named, "value": computed.group(1) if computed else _UNKNOWN,
                      "field": field if field else _A_SETTING}
            return {"known": True, **{part: _fill(entry[part], values) for part in ("what", "why", "do")}}
    except Exception:  # an explanation must never be the thing that fails
        pass
    return _generic(file, message)
