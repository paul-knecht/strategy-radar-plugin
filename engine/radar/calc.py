"""Checked arithmetic: the totals and shares in a report are computed here, never written by a model.

Only sourced figures in one unit go in: capacity moves that are confirmed or uncertain, each with a
plain `size_value` and a `size_unit` equal to the calculation's unit. Nothing is converted. All
arithmetic uses `decimal.Decimal`, never float. `compute` never raises on a hand-edited calculation;
whatever is wrong becomes a problem string and the value is None.
"""
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal, DivisionByZero, Inexact, InvalidOperation, Overflow

from . import store
from .verify import is_early_signal, needs_settling

_PLAIN_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?")
# Looks like a number with thousands separators (1.200, 1,200, 1.200.000): never read as a decimal.
_GROUPED = re.compile(r"\d{1,3}(?:[.,]\d{3})+")

# Wide enough for any sensible figure. A sum that would need rounding raises instead of being wrong.
_EXACT = Context(prec=400, traps=[InvalidOperation, Inexact, Overflow, DivisionByZero])
_DIVIDING = Context(prec=400, traps=[InvalidOperation, Overflow, DivisionByZero])


@dataclass(frozen=True)
class CalcResult:
    value: str | None
    includes_uncertain: bool
    problems: list[str]


def is_grouped(value) -> bool:
    """Whether `value` looks like a number with thousands separators, such as `1.200` or `1,200`."""
    return isinstance(value, str) and _GROUPED.fullmatch(value) is not None


def parse_number(value: str | None) -> Decimal | None:
    """A plain number such as `2` or `2.5`; anything else (separators, words, units, blanks) is None.

    A value that looks grouped (`1.200`) is never read as a decimal (1.2): it is None like any other non-number.
    """
    if isinstance(value, str) and _PLAIN_NUMBER.fullmatch(value) and not is_grouped(value):
        return Decimal(value)
    return None


def _write(number: Decimal) -> str:
    """A number without exponent or trailing zeros: 6, 2.5, 300."""
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _unit_key(unit) -> str | None:
    from .tidy import unit as tidy_unit   # tidy imports this module for parse_number
    named = tidy_unit(unit)   # "filling lines" and "lines" are one unit; None for a blank or non-text unit
    return named["name"].casefold() if named else None


def _is_settled_move(fact, sources) -> bool:
    """A confirmed or uncertain capacity move whose main source is a saved record of the run and is not a hint.

    A fact whose source record is missing from `sources` cannot be told from an early signal, so it is refused."""
    if not (isinstance(fact, dict) and fact.get("kind") == "capacity_move" and fact.get("status") in store.COUNTING):
        return False
    source_id = fact.get("source_id")
    if not (isinstance(source_id, str) and isinstance(sources.get(source_id), dict)):
        return False
    return not is_early_signal(fact, sources)   # a hint is never a figure to add up


def _input_value(fact_id, fact: dict, unit: str, problems: list[str]) -> Decimal | None:
    """The size of one input in the calculation's unit, or None after adding the reason to `problems`."""
    fields = fact.get("fields")
    fields = fields if isinstance(fields, dict) else {}
    stated = fields.get("size_unit")
    value = None
    if _unit_key(stated) != _unit_key(unit):
        problems.append(f'input {fact_id} is stated in "{stated if isinstance(stated, str) else ""}", not "{unit}"')
    else:
        value = parse_number(fields.get("size_value"))
        if value is None:
            problems.append(f"input {fact_id} has no plain number")
    return value


def compute(calculation: dict, facts: dict[str, dict], sources: dict[str, dict]) -> CalcResult:
    """Carry out one calculation of analysis.json on the facts as they stand now.

    `sources` is every source record of the run: an input counts only when its main source is among them."""
    calculation = calculation if isinstance(calculation, dict) else {}
    operation = calculation.get("operation")
    if not (isinstance(operation, str) and operation in store.CALC_OPERATIONS):
        return CalcResult(None, False, ["operation is not an allowed value"])

    problems: list[str] = []
    part_ids = calculation.get("fact_ids")
    if not isinstance(part_ids, list):
        problems.append("fact_ids must be a list")
    whole_ids = calculation.get("of_fact_ids")
    if whole_ids is None:   # only `share` needs a whole; a missing one is an empty one
        whole_ids = []
    elif not isinstance(whole_ids, list):
        problems.append("of_fact_ids must be a list")
    unit = calculation.get("unit")
    needs_unit = operation in ("sum", "share")
    if needs_unit and not (isinstance(unit, str) and unit.strip()):
        problems.append("unit is required")
    if problems:
        return CalcResult(None, False, problems)

    for fact_id in part_ids + whole_ids:   # a repeated input would silently count twice
        message = f"input {fact_id} is listed more than once"
        if (part_ids.count(fact_id) > 1 or whole_ids.count(fact_id) > 1) and message not in problems:
            problems.append(message)

    values: dict[str, Decimal | None] = {}   # one entry per distinct input; None when it cannot be used
    includes_uncertain = False
    for fact_id in part_ids + whole_ids:
        if isinstance(fact_id, str) and fact_id in values:
            continue
        fact = facts.get(fact_id) if isinstance(fact_id, str) else None
        if not _is_settled_move(fact, sources):
            message = f"input {fact_id} is not a settled capacity move"
            if message not in problems:
                problems.append(message)
            continue
        includes_uncertain = includes_uncertain or fact.get("status") == "uncertain"
        values[fact_id] = _input_value(fact_id, fact, unit, problems) if needs_unit else Decimal(0)

    if operation == "share" and not all(fact_id in whole_ids for fact_id in part_ids):
        problems.append("share inputs must be part of the whole")
    if problems:
        return CalcResult(None, includes_uncertain, problems)

    try:
        if operation == "count":
            return CalcResult(str(len(part_ids)), includes_uncertain, [])
        part = _total(part_ids, values)
        if operation == "sum":
            return CalcResult(_write(part), includes_uncertain, [])
        whole = _total(whole_ids, values)
        if whole == 0:
            return CalcResult(None, includes_uncertain, ["whole is zero"])
        share = _DIVIDING.divide(_EXACT.multiply(part, Decimal(100)), whole)
        share = share.quantize(Decimal(1), rounding=ROUND_HALF_UP, context=_DIVIDING)
        return CalcResult(_write(share), includes_uncertain, [])
    except ArithmeticError:
        return CalcResult(None, includes_uncertain, ["numbers are too large to calculate exactly"])


def settle_first(fact_ids: list, facts: dict[str, dict], sources: dict[str, dict],
                 texts: dict[str, str] | None = None) -> list[str]:
    """A problem for each listed fact whose stored status no longer follows from its stored checks, for the `calc`
    command, which refuses then: a total must not rest on a status that `settle` would change. `texts` is
    `verify.copy_texts` of the run, as `settle` uses it."""
    problems: list[str] = []
    for fact_id in fact_ids:
        fact = facts.get(fact_id) if isinstance(fact_id, str) else None
        if isinstance(fact, dict) and needs_settling(fact, sources, texts):
            message = f"input {fact_id} has changed since the facts were settled, so settle the facts first"
            if message not in problems:
                problems.append(message)
    return problems


def _total(fact_ids: list, values: dict) -> Decimal:
    total = Decimal(0)
    for fact_id in fact_ids:
        total = _EXACT.add(total, values[fact_id])
    return total
