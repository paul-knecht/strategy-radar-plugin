"""Display of numbers: thousands separators for large ones. Stored values and CSV cells keep plain digits."""
import re

_PLAIN = re.compile(r"(-?)([0-9]+)(\.[0-9]+)?")   # ASCII digits only
_THOUSANDS = re.compile(r"\B(?=(?:\d{3})+$)")


def shown(value, sep: str):
    """`value` with `sep` between the thousands of its whole-number part; anything that is not a plain decimal
    number (a word, a unit) comes back unchanged. Never pass a year or a fact id: only quantities."""
    match = _PLAIN.fullmatch(value) if isinstance(value, str) and sep else None
    if not match:
        return value
    sign, whole, fraction = match.groups()
    return sign + _THOUSANDS.sub(sep, whole) + (fraction or "")
