"""Quote matching: does a quote appear word for word in a saved copy?

The quote is looked for in three versions of the normalised copy: as it is, with line-end hyphens removed and with
line-end hyphens kept. A place where it occurs counts only when the quote covers whole words as they stand between
spaces in the copy. Before the match, back to the previous space, only opening brackets and quotation marks may stand;
after it, up to the next space, only sentence punctuation, closing brackets and quotation marks. So "likely" is not
found in "unlikely" or "(un)likely", "add 20" not in "add 20.5", "add 20%" or "add 20'000", and "20 percent" not in
"-20 percent" or "<20 percent".

Two rules look across a space: no match starts right after a word split at a line end ("un- likely", "20%- 30%"), and
none starts or ends inside a number grouped with spaces ("20 000").

Chinese and Japanese text has no spaces between words. An edge with a Chinese or Japanese character on either side
is not tested, and neither is one where only ASCII sentence punctuation, brackets or quotation marks (full-width
punctuation after NFKC) stand between the edge and such a character. There the match is refused only when both sides
of the edge belong to a number, so that a quote cannot cut a number such as 3 oku 5000 man.
"""
import unicodedata
from dataclasses import dataclass

from .textnorm import dehyphenate, is_cjk, normalise, quote_units

MIN_UNITS = 5
MAX_UNITS = 50
_OPENING = frozenset("([{\"'" + chr(0xBF) + chr(0xA1))   # with the inverted question and exclamation marks
_CLOSING = frozenset(".,;:!?)]}\"'")
# Chinese and Japanese comma, full stop, brackets and quotation marks: U+3001, U+3002, U+3008 to U+3011, U+3014 to
# U+301B and U+301D to U+301F. Not the wave dash U+301C, which joins a range.
_CJK_PUNCTUATION = frozenset(chr(cp) for low, high in ((0x3001, 0x3002), (0x3008, 0x3011), (0x3014, 0x301B),
                                                       (0x301D, 0x301F)) for cp in range(low, high + 1))
# ASCII sentence punctuation, brackets and quotation marks, as NFKC leaves full-width Chinese punctuation.
_ASCII_PUNCTUATION = frozenset(",.;:!?()[]{}\"'")
# ASCII digits and the Han numerals and multipliers (zero to nine, ten, hundred, thousand, 10 000 twice, 100 million
# twice, trillion).
_NUMERALS = frozenset("0123456789" + "".join(map(chr, (
    0x3007, 0x4E00, 0x4E8C, 0x4E09, 0x56DB, 0x4E94, 0x516D, 0x4E03, 0x516B, 0x4E5D,
    0x5341, 0x767E, 0x5343, 0x4E07, 0x842C, 0x5104, 0x4EBF, 0x5146))))
# Characters that belong to a number in Chinese or Japanese text: the numerals, `-`, `~`, `%` and the wave dash.
# `.` and `,` belong to it only between two ASCII digits.
_NUMBER_CHARACTERS = _NUMERALS | frozenset("-~%" + chr(0x301C))
_DECIMAL_MARKS = frozenset(".,")
_ASCII_DIGITS = frozenset("0123456789")
# Before a hyphen at the end of the word before a match, these join it to the next word (rule 4): percent, per mille
# and degree signs, besides letters, digits and currency signs.
_UNIT_SIGNS = frozenset("%" + chr(0x2030) + chr(0xB0))


@dataclass(frozen=True)
class QuoteResult:
    passed: bool
    mode: str | None
    reason: str | None


def _digit(ch: str) -> bool:
    """A digit, including a circled digit, a fraction or another number character (No), which normalise keeps."""
    return ch != "" and (ch.isdigit() or unicodedata.category(ch) == "No")


def _chinese_or_japanese(ch: str) -> bool:
    """A Chinese or Japanese character, or their comma, full stop, bracket or quotation mark."""
    return ch != "" and (is_cjk(ch) or ch in _CJK_PUNCTUATION)


def _exempt(inner: str, outer: str, beyond_punctuation: str) -> bool:
    """Whether an edge is not tested: `inner` is the quote's character at the edge, `outer` the copy's character
    next to it, and `beyond_punctuation` the copy's first character past a run of ASCII sentence punctuation,
    brackets, quotation marks and braces next to the edge ("" when there is no such run)."""
    return _chinese_or_japanese(inner) or _chinese_or_japanese(outer) or _chinese_or_japanese(beyond_punctuation)


def _number_character(ch: str, before: str, after: str) -> bool:
    """Whether `ch` belongs to a number, given the characters directly before and after it. A `.` or `,` belongs to
    a number only with an ASCII digit on both sides (3,500 or 1.5); otherwise it is punctuation."""
    if ch in _DECIMAL_MARKS:
        return before in _ASCII_DIGITS and after in _ASCII_DIGITS
    return ch in _NUMBER_CHARACTERS


def _cuts_a_number(before_left: str, left: str, right: str, after_right: str) -> bool:
    """Ruling c: at an exempt edge between `left` and `right`, a match may not cut one number (3 oku | 5000)."""
    return _number_character(left, before_left, right) and _number_character(right, left, after_right)


def _joined_to_the_next_line(word: str) -> bool:
    """Rule 4: the word before a match ends with a hyphen that joins it to the match: after a letter, a digit, a
    percent, per mille or degree sign or a currency sign ("un- likely", "10- 20", "20%- 30%", "pre- and post-").
    After anything else ("--", "500,-", "follows:-") the hyphen is a dash and an ordinary boundary."""
    if len(word) < 2 or not word.endswith("-"):
        return False
    joined = word[-2]
    return joined.isalnum() or joined in _UNIT_SIGNS or unicodedata.category(joined) == "Sc"


def _three_digits(text: str) -> bool:
    """Whether `text` starts with exactly three digits, not followed by a fourth."""
    return len(text) >= 3 and all(_digit(ch) for ch in text[:3]) and not _digit(text[3:4])


def _start_counts(needle: str, haystack: str, start: int) -> bool:
    """The match starts a word: only opening marks stand between the previous space and the match (the principle),
    the word before is not split at a line end (rule 4), and no number grouped with a space is cut (rule 5). At an
    exempt Chinese or Japanese edge only the number check applies."""
    outer = haystack[start - 1] if start > 0 else ""
    run = start
    while run > 0 and haystack[run - 1] in _ASCII_PUNCTUATION:
        run -= 1
    beyond = haystack[run - 1] if run < start and run > 0 else ""
    if _exempt(needle[0], outer, beyond):
        return not _cuts_a_number(haystack[start - 2] if start >= 2 else "", outer, needle[0], needle[1:2])
    space = haystack.rfind(" ", 0, start)
    if not all(ch in _OPENING for ch in haystack[space + 1:start]):
        return False
    word_before = haystack[haystack.rfind(" ", 0, space) + 1:space] if space > 0 else ""
    if _joined_to_the_next_line(word_before):
        return False
    return not (start >= 2 and outer == " " and _digit(haystack[start - 2]) and _three_digits(needle))


def _end_counts(needle: str, haystack: str, end: int) -> bool:
    """The match ends a word: only closing marks stand between the match and the next space (the principle), and no
    number grouped with a space is cut (rule 5). At an exempt Chinese or Japanese edge only the number check
    applies."""
    outer = haystack[end] if end < len(haystack) else ""
    run = end
    while run < len(haystack) and haystack[run] in _ASCII_PUNCTUATION:
        run += 1
    beyond = haystack[run] if end < run < len(haystack) else ""
    if _exempt(needle[-1], outer, beyond):
        return not _cuts_a_number(needle[-2:-1], needle[-1], outer, haystack[end + 1:end + 2])
    space = haystack.find(" ", end)
    if not all(ch in _CLOSING for ch in haystack[end:space if space != -1 else len(haystack)]):
        return False
    return not (space == end and _digit(needle[-1]) and _three_digits(haystack[end + 1:end + 5]))


def _found(needle: str, haystack: str) -> bool:
    """Whether `needle` occurs as whole words in `haystack`. Every occurrence is tried, not only the first."""
    start = haystack.find(needle)
    while start != -1:
        if _start_counts(needle, haystack, start) and _end_counts(needle, haystack, start + len(needle)):
            return True
        start = haystack.find(needle, start + 1)
    return False


def find_quote(quote: str, copy_text: str) -> QuoteResult:
    units = quote_units(quote)
    if units < MIN_UNITS:
        return QuoteResult(False, None, "quote_too_short")
    if units > MAX_UNITS:
        return QuoteResult(False, None, "quote_too_long")
    needle = normalise(quote)
    candidates = (
        ("exact", normalise(copy_text)),
        ("dehyphenated", normalise(dehyphenate(copy_text))),
        ("line_hyphen_kept", normalise(dehyphenate(copy_text, keep_hyphen=True))),
    )
    for mode, haystack in candidates:
        if _found(needle, haystack):
            return QuoteResult(True, mode, None)
    return QuoteResult(False, None, "not_found")
