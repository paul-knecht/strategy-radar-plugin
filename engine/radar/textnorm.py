"""Text normalisation for quote matching.

Ignores only spacing, line breaks, typographic variants of quotes and dashes,
ligatures, soft hyphens and line-end hyphenation. Never case, words or punctuation.
"""
import math
import re
import unicodedata

_QUOTE_MAP = {
    **dict.fromkeys("\u201c\u201d\u201e\u201f\u00ab\u00bb", '"'),
    **dict.fromkeys("\u2018\u2019\u201a\u201b\u2039\u203a", "'"),
    **dict.fromkeys("\u2010\u2011\u2012\u2013\u2212", "-"),
    # The em dash and the horizontal bar are dashes between clauses, never joining hyphens: a spaced hyphen.
    # Between two digits they are a range (see _DIGIT_RANGE_DASH). The en dash stays a plain hyphen.
    **dict.fromkeys("\u2014\u2015", " - "),
    **dict.fromkeys("\u00ad\u200b\u200c\u200d\u2060\ufeff", None),
}
_TRANSLATION = str.maketrans(_QUOTE_MAP)

# Mapped before NFKC runs.
# Superscript and subscript digits stay distinct from plain digits (NFKC would fold them): a footnote mark
# after 500 must not read as 5001. Each becomes `^` or `_` plus the digit.
# Accents typed as an apostrophe become one: NFKC would turn the acute accent into a space and a combining mark, so
# that "can" plus acute plus "t" read as "can t". The prime U+2032 is not one of them: it marks feet or minutes.
_SUPERSCRIPT_DIGITS = (0x2070, 0xB9, 0xB2, 0xB3, 0x2074, 0x2075, 0x2076, 0x2077, 0x2078, 0x2079)
# acute accent, grave accent, modifier letter apostrophe, Greek koronis
_APOSTROPHE_LOOKALIKES = "".join(map(chr, (0xB4, 0x60, 0x2BC, 0x1FBD)))
_BEFORE_NFKC = str.maketrans({
    **{chr(code): "^" + str(digit) for digit, code in enumerate(_SUPERSCRIPT_DIGITS)},
    **{chr(0x2080 + digit): "_" + str(digit) for digit in range(10)},
    **dict.fromkeys(_APOSTROPHE_LOOKALIKES, "'"),
})

# An em dash or horizontal bar directly after a digit and before a digit, perhaps with whitespace or a line break in
# between, joins a range such as 1990-2000: a plain hyphen, and the whitespace stays.
_DIGIT_RANGE_DASH = re.compile(r"(?<=\d)[\u2014\u2015](?=\s*\d)")

# Chinese and Japanese code point ranges: these scripts have no spaces between words.
_CJK_RANGES = (
    (0x3040, 0x30FF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
)

_SOFT_HYPHEN = chr(0xAD)
# Hyphens that can end a line: ASCII hyphen, U+2010, U+2011 and the soft hyphen.
_LINE_END_HYPHENS = "-" + chr(0x2010) + chr(0x2011) + _SOFT_HYPHEN

# A hyphen after a letter, then optional spaces, a line break, optional whitespace, a letter.
_LINE_END_HYPHEN = re.compile(
    r"(?<=[^\W\d_])([" + re.escape(_LINE_END_HYPHENS) + r"])[^\S\r\n]*(?:\r\n|\r|\n)\s*(?=[^\W\d_])"
)
# A soft hyphen between a letter or digit and a line break before a letter or digit. A soft hyphen is never a real
# hyphen, so normalise always joins there, in every variant: "un", soft hyphen, line break, "likely" reads
# "unlikely", "COVID" plus "19" reads "COVID19", and "10" plus "20" reads "1020".
_SOFT_LINE_END_HYPHEN = re.compile(
    r"(?<=[^\W_])" + _SOFT_HYPHEN + r"[^\S\r\n]*(?:\r\n|\r|\n)\s*(?=[^\W_])"
)

_CJK_CLASS = "[" + "".join(chr(lo) + "-" + chr(hi) for lo, hi in _CJK_RANGES) + "]"
# Whitespace between two Chinese or Japanese characters is a line wrap, not a word gap.
_CJK_GAP = re.compile("(?<=" + _CJK_CLASS + ") (?=" + _CJK_CLASS + ")")


def _fold_compatible(text: str) -> str:
    """NFKC (ligatures, full-width forms, no-break spaces), except for the other number characters.

    These are the characters of Unicode category No, such as circled digits and vulgar fractions: NFKC would read 500
    plus a circled one as 5001, and 1 plus a half as 11/2. They stay as they are. The category is looked up for each
    distinct character of the text; superscript and subscript digits are already written out by then.
    """
    kept = sorted(ch for ch in set(text) if unicodedata.category(ch) == "No")
    if not kept:
        return unicodedata.normalize("NFKC", text)
    parts = re.split("([" + "".join(map(re.escape, kept)) + "])", text)   # every odd part is one kept character
    return "".join(part if index % 2 else unicodedata.normalize("NFKC", part) for index, part in enumerate(parts))


def normalise(text: str) -> str:
    text = _SOFT_LINE_END_HYPHEN.sub("", text)
    text = _fold_compatible(text.translate(_BEFORE_NFKC))
    text = _DIGIT_RANGE_DASH.sub("-", text).translate(_TRANSLATION)
    text = re.sub(r"\s+", " ", text).strip()
    return _CJK_GAP.sub("", text)


def is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def quote_units(text: str) -> int:
    """Length of a quote in words; two Chinese or Japanese characters count as one word.

    A part with no letter and no digit, such as a lone dash, is not a word.
    """
    units = 0
    for part in normalise(text).split(" "):
        if not any(ch.isalnum() for ch in part):
            continue
        cjk = sum(1 for ch in part if is_cjk(ch))
        if cjk == 0:
            units += 1
            continue
        units += math.ceil(cjk / 2)
        if any(ch.isalnum() and not is_cjk(ch) for ch in part):
            units += 1
    return units


def dehyphenate(text: str, keep_hyphen: bool = False) -> str:
    """Join words split by a hyphen at a line end.

    The hyphen is kept if keep_hyphen is true, except a soft hyphen, which is never a real hyphen.
    """

    def join(match: re.Match) -> str:
        hyphen = match.group(1)
        return hyphen if keep_hyphen and hyphen != _SOFT_HYPHEN else ""

    return _LINE_END_HYPHEN.sub(join, text)
