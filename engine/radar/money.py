"""Whether a text states an amount of money, and whether it speaks of money at all. English only, as every run so far.

The gate uses both: a "not found" entry about money may not pass over confirmed facts that state an amount.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

_WORD = r"[^\W\d_]+"   # letters of any script, so "Müller" stays one word
_TOKEN = re.compile(r"[€$£]|\d[\d,.]*|" + _WORD)
_SIGNS = {"€", "$", "£"}
_CODES = {"USD", "EUR", "CHF", "GBP", "DKK", "KRW", "JPY", "CNY"}   # written in capitals
_CURRENCY_WORDS = {"euro", "euros", "dollar", "dollars", "franc", "francs", "krone", "kroner", "won"}
# shortcut: "won" and "a" also match the verb and the article; the gate only asks the writer to name a fact, so a false
# match is never unsafe. Upgrade if it becomes noisy.
_NUMBER_WORDS = {"a", "half", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
                 "thousand", "million", "billion", "bn", "m"}
_NEAR = 4   # at most three words between a currency and a number


@lru_cache(maxsize=1)
def _money_words() -> frozenset:
    return frozenset(json.loads(Path(__file__).with_name("money_words_en.json").read_text(encoding="utf-8")))


def _is_currency(token: str) -> bool:
    return token in _SIGNS or token in _CODES or token.lower() in _CURRENCY_WORDS


def _is_number(token: str) -> bool:
    return token[0].isdigit() or token.lower() in _NUMBER_WORDS


def states_money(text: str) -> bool:
    """A currency sign, code or word with a number or a scale word at most three words before or after it."""
    tokens = _TOKEN.findall(text)
    return any(_is_currency(token) and any(_is_number(near) for near in tokens[max(0, at - _NEAR):at + _NEAR + 1])
               for at, token in enumerate(tokens))


def speaks_of_money(text: str, leave_out: frozenset = frozenset()) -> bool:
    """Any word of money_words_en.json but those in `leave_out`, as a whole word, case ignored."""
    return any(word.lower() in _money_words() - leave_out for word in re.findall(_WORD, text))
