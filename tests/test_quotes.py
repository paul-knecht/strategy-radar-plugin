import pytest

from radar.textnorm import normalise, dehyphenate, quote_units
from radar.quotes import find_quote

COPY = ("The company said the expan-\nsion adds two high-speed\n"
        "syringe lines for fill-\nfinish customers, starting in 2028.")

def test_normalise_spacing_and_typography():
    assert normalise("  two\n lines\u00a0here ") == "two lines here"
    assert normalise("„Ausbau“ – ‘neu’") == "\"Ausbau\" - 'neu'"
    assert normalise("e\ufb03cient soft\u00adhyphen") == "efficient softhyphen"
    assert normalise("Capacity") != normalise("capacity")

def test_dehyphenate_only_at_line_ends():
    assert dehyphenate("expan-\n  sion of") == "expansion of"
    assert dehyphenate("fill-\nfinish", keep_hyphen=True) == "fill-finish"
    assert dehyphenate("fill-finish line") == "fill-finish line"

def test_find_quote_exact():
    r = find_quote("adds two high-speed syringe lines", COPY)
    assert (r.passed, r.mode, r.reason) == (True, "exact", None)

def test_find_quote_across_removed_hyphen():
    r = find_quote("the expansion adds two high-speed syringe lines", COPY)
    assert (r.passed, r.mode) == (True, "dehyphenated")

def test_find_quote_across_kept_hyphen():
    r = find_quote("syringe lines for fill-finish customers, starting in 2028", COPY)
    assert (r.passed, r.mode) == (True, "line_hyphen_kept")

def test_find_quote_fails_when_one_word_differs():
    r = find_quote("adds three high-speed syringe lines", COPY)
    assert (r.passed, r.mode, r.reason) == (False, None, "not_found")

def test_find_quote_is_case_sensitive():
    assert find_quote("ADDS TWO HIGH-SPEED SYRINGE LINES", COPY).reason == "not_found"

def test_find_quote_length_limits():
    assert find_quote("two syringe lines", COPY).reason == "quote_too_short"
    long_quote = " ".join(["word"] * 51)
    assert find_quote(long_quote, " ".join(["word"] * 60)).reason == "quote_too_long"

def test_quote_units_counts_words_and_halves_cjk_characters():
    assert quote_units("adds two high-speed syringe lines") == 5
    assert quote_units(chr(0x4EA7) * 12) == 6            # twelve Chinese characters, no spaces
    assert quote_units("Site X " + chr(0x30AB) * 5) == 5  # two words plus five Japanese characters
    assert quote_units("The company - founded in 1990 " + chr(0x2014) + " said") == 6   # a lone dash is no word

def test_find_quote_accepts_a_quote_without_spaces():
    han = "".join(chr(0x4E00 + i) for i in range(40))
    assert find_quote(han[5:25], "prefix " + han + " suffix").passed
    assert find_quote(han[5:11], han).reason == "quote_too_short"

def test_find_quote_keeps_umlauts_and_eszett():
    copy = "Die Erweiterung umfasst zwei\nneue Abfüllanlagen und schließt 2028 ab."
    assert find_quote("zwei neue Abfüllanlagen und schließt 2028 ab", copy).passed

def _han(n):
    return "".join(chr(0x4E00 + i) for i in range(n))

def test_find_quote_across_a_line_break_inside_cjk_text():
    plain = _han(40)
    wrapped = plain[:15] + "\n" + plain[15:]
    r = find_quote(plain[5:25], wrapped)
    assert (r.passed, r.mode) == (True, "exact")

def test_normalise_drops_space_between_cjk_but_keeps_it_next_to_other_text():
    assert normalise(_han(3) + " \n " + _han(3)) == _han(3) + _han(3)
    assert normalise("Site X " + _han(3)) == "Site X " + _han(3)
    assert normalise(_han(3) + " Site") == _han(3) + " Site"

def test_find_quote_across_a_soft_hyphen_at_line_end():
    # A soft hyphen at a line end joins the word in every variant (ruling b), so the exact copy already has it whole.
    copy = "The company said the expan" + chr(0xAD) + "\nsion adds two high-speed syringe lines."
    r = find_quote("the expansion adds two high-speed syringe lines", copy)
    assert (r.passed, r.mode) == (True, "exact")

def test_find_quote_across_a_unicode_hyphen_at_line_end():
    copy = "The company said the expan" + chr(0x2010) + "\nsion adds two high-speed syringe lines."
    r = find_quote("the expansion adds two high-speed syringe lines", copy)
    assert (r.passed, r.mode) == (True, "dehyphenated")

def test_dehyphenate_soft_hyphen_is_never_kept_but_unicode_hyphens_follow_keep_hyphen():
    assert dehyphenate("fill" + chr(0xAD) + "\nfinish", keep_hyphen=True) == "fillfinish"
    assert dehyphenate("fill" + chr(0xAD) + "\nfinish") == "fillfinish"
    assert dehyphenate("fill" + chr(0x2011) + "\nfinish") == "fillfinish"
    assert normalise(dehyphenate("fill" + chr(0x2010) + "\nfinish", keep_hyphen=True)) == "fill-finish"


# --- a match never starts or ends inside a word or number (final fix C2) ---------------

SUP_SIX, SUP_ONE, SUB_TWO = chr(0x2076), chr(0xB9), chr(0x2082)


def test_a_match_may_not_start_inside_a_word():
    copy = "The company is unlikely to expand capacity at Plant North before 2030."
    assert find_quote("likely to expand capacity at Plant North before 2030.", copy).reason == "not_found"
    assert find_quote("expand capacity at Plant North", copy).passed


def test_a_match_may_not_end_inside_a_number():
    assert find_quote("The company will add 20", "The company will add 200 filling lines.").reason == "not_found"


def test_a_number_matches_only_the_whole_number():
    quote = "The company will add 20"
    assert find_quote(quote, "The company will add 20 lines.").passed
    for copy in ("The company will add 200 lines.", "The company will add 20.5 lines.",
                 "The company will add 20,000 lines."):
        assert find_quote(quote, copy).reason == "not_found", copy


def test_a_quote_ending_at_a_sentence_final_number_still_matches():
    quote = "syringe lines for customers, starting in 2028"
    for copy in ("Two syringe lines for customers, starting in 2028. Then more.",
                 "Two syringe lines for customers, starting in 2028.",
                 "Two syringe lines for customers, starting in 2028"):
        assert find_quote(quote, copy).passed, copy


def test_a_match_may_not_start_inside_a_number():
    quote = "500 lines were planned for the site"
    for copy in ("In all, 1.500 lines were planned for the site.", "In all, 1,500 lines were planned for the site.",
                 "In all, 2500 lines were planned for the site."):
        assert find_quote(quote, copy).reason == "not_found", copy
    assert find_quote(quote, "In all, 500 lines were planned for the site.").passed


def test_a_match_at_the_very_start_and_the_very_end_of_the_copy():
    quote = "adds two high-speed syringe lines"
    assert find_quote(quote, quote).passed
    assert find_quote(quote, quote + " later").passed and find_quote(quote, "It " + quote).passed


def test_a_rejected_position_does_not_hide_a_later_valid_one():
    copy = "The company will add 200 lines. Later it said: The company will add 20 lines."
    assert find_quote("The company will add 20", copy).passed


def test_chinese_and_japanese_characters_are_exempt_from_the_word_edges():
    han = _han(40)
    assert find_quote(han[5:25], han).passed
    latin = "Plant North adds two new lines"
    assert find_quote(latin, han[:10] + latin + han[10:20]).passed


def test_superscript_and_subscript_digits_stay_distinct_from_plain_digits():
    assert normalise("10" + SUP_SIX) == "10^6" and normalise("CO" + SUB_TWO) == "CO_2"
    copy = "Capacity rises to 10" + SUP_SIX + " doses a year at the site."
    assert find_quote("Capacity rises to 106 doses a year", copy).reason == "not_found"
    assert find_quote("Capacity rises to 10" + SUP_SIX + " doses a year", copy).passed
    footnote = "The plant will make 500" + SUP_ONE + " million doses."
    assert find_quote("The plant will make 5001 million doses", footnote).reason == "not_found"
    assert find_quote("The plant cuts its CO2 output", "The plant cuts its CO" + SUB_TWO + " output by half.").reason \
        == "not_found"


# --- a match may not cut a number or a hyphen-joined word (quote hardening, rules 1 to 4) ----------

MINUS, NBSP, NARROW_NBSP, RIGHT_QUOTE = chr(0x2212), chr(0xA0), chr(0x202F), chr(0x2019)
CIRCLED_ONE, HALF = chr(0x2460), chr(0xBD)
EN_DASH, EM_DASH, HORIZONTAL_BAR, SOFT_HYPHEN = chr(0x2013), chr(0x2014), chr(0x2015), chr(0xAD)
SUP_TWO, PER_MILLE, DEGREE, EURO, POUND = chr(0xB2), chr(0x2030), chr(0xB0), chr(0x20AC), chr(0xA3)


def _text(*code_points):
    return "".join(chr(cp) for cp in code_points)


# Fix round 2: Chinese and Japanese text. None of these characters is a number character, except OKU, MAN and the
# numerals in NIJU and SANJU.
WAVE_DASH, FULL_COMMA, FULL_COLON, FULL_SEMICOLON = chr(0x301C), chr(0xFF0C), chr(0xFF1A), chr(0xFF1B)
OKU, MAN, NIJU, SANJU = chr(0x5104), chr(0x4E07), _text(0x4E8C, 0x5341), _text(0x4E09, 0x5341)
JA_CAPACITY = _text(0x306E, 0x751F, 0x7523, 0x80FD, 0x529B, 0x3092, 0x62E1, 0x5927, 0x3059, 0x308B)  # of capacity...
JA_FACTORY = _text(0x5DE5, 0x5834, 0x306F)                                                         # the factory
JA_INVEST = _text(0x4E07, 0x5186, 0x3092, 0x6295, 0x8CC7, 0x3059, 0x308B)                          # 10,000 yen, invest
JA_TOTAL = _text(0x8A2D, 0x5099, 0x6295, 0x8CC7, 0x306F, 0x7DCF, 0x984D)                           # capex in total
JA_PLAN = _text(0x3092, 0x4E88, 0x5B9A, 0x3059, 0x308B)                                            # is planned
JA_ANNUAL, JA_TONS = _text(0x5E74, 0x9593), _text(0x30C8, 0x30F3, 0x3092, 0x751F, 0x7523, 0x3059, 0x308B)
ZH_SAID = _text(0x516C, 0x53F8, 0x8868, 0x793A)                                                    # the company said
ZH_QUOTE = "2028" + _text(0x5E74, 0x5C06, 0x6269, 0x5927, 0x4EA7, 0x80FD, 0x548C, 0x751F, 0x4EA7, 0x7EBF)
LATIN_LINES = "Plant North adds two new lines"
ACCENTS_AS_APOSTROPHES = (chr(0xB4), chr(0x60), chr(0x2BC), chr(0x1FBD))
PRIME, LEFT_DOUBLE, RIGHT_DOUBLE, FULL_STOP_WIDE = chr(0x2032), chr(0x201C), chr(0x201D), chr(0xFF0E)
# Fix round 3
ZH_INVEST_500_YI = ZH_SAID + _text(0x6295, 0x8D44) + "500" + chr(0x4EBF)   # the company said: invest 50 bn
JA_TOTAL_5_MAN = JA_TOTAL + "5" + MAN
ZH_ONE_OF = ZH_SAID + _text(0x662F, 0x751F, 0x4EA7, 0x5546, 0x4E4B, 0x4E00)               # ... is one of the makers
YEAR_2025, YEAR_2028 = "2025" + chr(0x5E74), "2028" + chr(0x5E74)
MITSUBISHI = _text(0x4E09, 0x83F1) + JA_CAPACITY                                          # starts with the numeral 3

# The rows of the re-review: each quote matched a copy that says something else.
REVIEWED_ROWS = [
    ("The plant has a capacity of 10", "The plant has a capacity of 10" + SUP_SIX + " tonnes."),
    ("6 tonnes of glass in 2025", "The plant made 10" + SUP_SIX + " tonnes of glass in 2025."),
    ("likely to expand capacity at Plant North before 2030.",
     "The company is un-\nlikely to expand capacity at Plant North before 2030."),
    ("binding agreement to buy the Plant North site",
     "They signed a non-binding agreement to buy the Plant North site."),
    ("20 percent in 2025 at Plant North", "Output changed by " + MINUS + "20 percent in 2025 at Plant North."),
    ("20 percent in 2025 at Plant North", "Output changed by -20 percent in 2025 at Plant North."),
    ("The company will add 20.", "The company will add 20.5 filling lines."),
    ("The company will add 20,", "The company will add 20,000 lines."),
    *[("The company will add 20", "The company will add 20" + mark + "000 filling lines.")
      for mark in (" ", NBSP, NARROW_NBSP, "'", RIGHT_QUOTE)],
    ("supplies 5001 million doses a year", "supplies 500" + CIRCLED_ONE + " million doses a year"),
    ("The company will add 11 lines", "The company will add 1" + HALF + " lines"),
    ("The company will add 11", "The company will add 1" + HALF + " lines"),
    ("2 lines at Plant North in 2026", "The company will add 1" + HALF + " lines at Plant North in 2026"),
]


@pytest.mark.parametrize("quote, copy", REVIEWED_ROWS)
def test_a_quote_that_cuts_a_number_or_a_joined_word_is_not_found(quote, copy):
    r = find_quote(quote, copy)
    assert (r.passed, r.mode, r.reason) == (False, None, "not_found")


# Each case: the quote, a copy in which it cuts a number or a joined word (refused) and a copy in which the same quote
# sits at an ordinary boundary (found). In END_CASES both copies start with the quote, in START_CASES both end with it.
END_CASES = {
    "rule 1, superscript digit after a number": (
        "The plant has a capacity of 10",
        "The plant has a capacity of 10" + SUP_SIX + " tonnes.", "The plant has a capacity of 10 tonnes."),
    "rule 1, subscript digit after a number": (
        "The plant has a capacity of 10",
        "The plant has a capacity of 10" + SUB_TWO + " tonnes.", "The plant has a capacity of 10 tonnes."),
    "rule 2, hyphen and letter after a word": (
        "The company runs two lines at Plant North",
        "The company runs two lines at Plant North-East.",
        "The company runs two lines at Plant North - the largest site."),
    "rule 2, hyphen and digit after a word": (
        "The site fills vials for COVID", "The site fills vials for COVID-19 vaccines.",
        "The site fills vials for COVID vaccines."),
    "rule 2, hyphen and digit after a number": (
        "Output will grow by 10", "Output will grow by 10-20 percent.", "Output will grow by 10 percent."),
    "rule 2, word split at a line end": (
        "The company builds lines for small", "The company builds lines for small-\nscale batches.",
        "The company builds lines for small batches."),
    "rule 2, suspended hyphen": (
        "The company builds lines for small", "The company builds lines for small- and large-scale batches.",
        "The company builds lines for small and large batches."),
    "rule 3, decimal point at the end of the quote": (
        "The company will add 20.", "The company will add 20.5 filling lines.",
        "The company will add 20. Five more follow."),
    "rule 3, thousands comma at the end of the quote": (
        "The company will add 20,", "The company will add 20,000 lines.", "The company will add 20, then 30 lines."),
    **{f"rule 4, grouped with {name}": (
        "The company will add 20", "The company will add 20" + mark + "000 filling lines.",
        "The company will add 20 filling lines.")
       for name, mark in (("a space", " "), ("a no-break space", NBSP), ("a narrow no-break space", NARROW_NBSP),
                          ("an apostrophe", "'"), ("a typographic apostrophe", RIGHT_QUOTE))},
    "rule 5, circled digit after a number": (
        "The plant supplies 500", "The plant supplies 500" + CIRCLED_ONE + " million doses.",
        "The plant supplies 500 million doses."),
    "rule 5, fraction after a number": (
        "The company will add 1", "The company will add 1" + HALF + " lines.", "The company will add 1 line."),
    "rule 5, decimal mark and a fraction after a number": (
        "The company will add 20", "The company will add 20." + HALF + " lines.", "The company will add 20. Lines."),
    **{f"ruling a, en dash joins, {name} separates": (
        "The company has run Plant North since 1990",
        "The company has run Plant North since 1990" + EN_DASH + "2000.",
        "The company has run Plant North since 1990" + dash + "longer than any rival.")
       for name, dash in (("em dash", EM_DASH), ("horizontal bar", HORIZONTAL_BAR))},
    "ruling b, soft hyphen at a line end": (
        "The company builds lines for small", "The company builds lines for small" + SOFT_HYPHEN + "\nscale batches.",
        "The company builds lines for small batches."),
    "ruling c, digit after a line-end hyphen": (
        "The site fills vials for COVID", "The site fills vials for COVID-\n19 vaccines.",
        "The site fills vials for COVID vaccines."),
    "ruling c, number split at a line end": (
        "Output at the plant rose by 10", "Output at the plant rose by 10-\n20 percent.",
        "Output at the plant rose by 10 percent."),
    "ruling e, subscript digit after a letter": (
        "The plant cuts its emissions of CO", "The plant cuts its emissions of CO" + SUB_TWO + " by half.",
        "The plant cuts its emissions of CO by half."),
    "ruling e, superscript digit after a unit": (
        "The site covers an area of 10,000 m", "The site covers an area of 10,000 m" + SUP_TWO + " in total.",
        "The site covers an area of 10,000 m in total."),
    **{f"ruling f, {name} after a number": (
        "The company will add 20", "The company will add 20" + symbol + " more capacity.",
        "The company will add 20" + " " + symbol + " more capacity.")
       for name, symbol in (("percent sign", "%"), ("per mille sign", PER_MILLE), ("plus sign", "+"),
                            ("degree sign", DEGREE), ("euro sign", EURO), ("dollar sign", "$"))},
    "principle, slash after a year": (
        "The plant will start production in 2025", "The plant will start production in 2025/26.",
        "The plant will start production in 2025."),
    "principle, apostrophe inside a word": (
        "Management said the company can", "Management said the company can't.", "Management said the company can."),
    "principle, possessive": (
        "It signed a supply contract with Drug Maker B", "It signed a supply contract with Drug Maker B's parent.",
        "It signed a supply contract with Drug Maker B, the parent."),
    **{f"principle, range of percentages with {name}": (
        "Output at Plant North grew by 20%", "Output at Plant North grew by 20%" + dash + "30% in 2025.",
        "Output at Plant North grew by 20% in 2025.")
       for name, dash in (("a hyphen", "-"), ("an en dash", EN_DASH))},
    "principle, range of amounts": (
        "The company plans to invest " + EURO + "20m", "The company plans to invest " + EURO + "20m" + EN_DASH + EURO
        + "30m.", "The company plans to invest " + EURO + "20m."),
    "principle, asterisk": ("The company will add 20", "The company will add 20* lines.", "The company will add 20."),
    "principle, superscript minus": (
        "The plant reaches a purity of 10", "The plant reaches a purity of 10" + chr(0x207B) + SUP_SIX + " units.",
        "The plant reaches a purity of 10 units."),
    "principle, ratio": ("The plant dilutes the batch 1", "The plant dilutes the batch 1:20 first.",
                         "The plant dilutes the batch 1: first."),
    "fix 2 ruling a, wave dash after a percentage": (
        "Output at Plant North grew by 20%", "Output at Plant North grew by 20%" + WAVE_DASH + "30%.",
        "Output at Plant North grew by 20%."),
    "fix 2 ruling b, Latin quote before a full-width comma": (
        LATIN_LINES, LATIN_LINES + "*" + JA_CAPACITY, LATIN_LINES + FULL_COMMA + JA_CAPACITY),
    "fix 2 ruling c, number after a Han multiplier": (
        JA_TOTAL + "3" + OKU, JA_TOTAL + "3" + OKU + "5000" + JA_INVEST, JA_TOTAL + "3" + OKU + JA_PLAN),
    **{f"fix 2 ruling d, {hex(ord(accent))} typed as an apostrophe": (
        "Management said the company can", "Management said the company can" + accent + "t.",
        "Management said the company can.")
       for accent in ACCENTS_AS_APOSTROPHES},
    "fix 2 addendum, prime after a number": (
        "The ceiling height at Plant North is 5",
        "The ceiling height at Plant North is 5" + PRIME + " in the old hall.",
        "The ceiling height at Plant North is 5 in the old hall."),
    "fix 2 addendum, Latin quote before a closing quotation mark": (
        LATIN_LINES, LATIN_LINES + "*" + JA_CAPACITY, LATIN_LINES + RIGHT_DOUBLE + JA_CAPACITY),
    "fix 2 addendum, number before a full-width comma": (
        JA_TOTAL + "30", JA_TOTAL + "30,5" + JA_PLAN, JA_TOTAL + "30" + FULL_COMMA + JA_PLAN),
    "fix 3, Han multiplier before a comma and a year": (
        ZH_INVEST_500_YI, ZH_INVEST_500_YI + "5" + JA_PLAN, ZH_INVEST_500_YI + FULL_COMMA + YEAR_2025 + JA_PLAN),
}

START_CASES = {
    "rule 1, superscript digit before a number": (
        "6 tonnes of glass in 2025",
        "The plant made 10" + SUP_SIX + " tonnes of glass in 2025", "The plant made 6 tonnes of glass in 2025"),
    "rule 1, subscript digit before a number": (
        "2 emissions fell by half in 2025",
        "The plant's CO" + SUB_TWO + " emissions fell by half in 2025",
        "At the plant, line 2 emissions fell by half in 2025"),
    "rule 2, compound word": (
        "binding agreement to buy the Plant North site",
        "They signed a non-binding agreement to buy the Plant North site",
        "They signed a binding agreement to buy the Plant North site"),
    "rule 2, number and hyphen before a word": (
        "year contract with Drug Maker B", "The company signed a 10-year contract with Drug Maker B",
        "The company signed a one year contract with Drug Maker B"),
    "rule 2, word split at a line end": (
        "likely to expand capacity at Plant North", "The company is un-\nlikely to expand capacity at Plant North",
        "The company is likely to expand capacity at Plant North"),
    "rule 2, suspended hyphen": (
        "and post-approval checks on each batch", "The lab runs pre- and post-approval checks on each batch",
        "The lab runs pre-approval and post-approval checks on each batch"),
    **{f"rule 2, {name} before a number": (
        "20 percent in 2025 at Plant North", "Output changed by " + sign + "20 percent in 2025 at Plant North",
        "Output changed by 20 percent in 2025 at Plant North")
       for name, sign in (("minus sign", MINUS), ("hyphen", "-"), ("plus sign", "+"))},
    "rule 3, decimal point at the start of the quote": (
        ".5 filling lines at Plant North", "The company will add 20.5 filling lines at Plant North",
        "The company will add .5 filling lines at Plant North"),
    "rule 3, thousands comma at the start of the quote": (
        ",000 lines at Plant North", "The company will add 20,000 lines at Plant North",
        "The company will add ,000 lines at Plant North"),
    **{f"rule 4, grouped with {name}": (
        "000 lines at Plant North", "The company will add 20" + mark + "000 lines at Plant North",
        "The company will add" + mark + "000 lines at Plant North")
       for name, mark in (("a space", " "), ("a no-break space", NBSP), ("a narrow no-break space", NARROW_NBSP))},
    # Fix round 1: "add'000" is one word between spaces, so the honest twin puts the apostrophe after a space.
    **{f"rule 4, grouped with {name}": (
        "000 lines at Plant North", "The company will add 20" + mark + "000 lines at Plant North",
        "The company will add " + mark + "000 lines at Plant North")
       for name, mark in (("an apostrophe", "'"), ("a typographic apostrophe", RIGHT_QUOTE))},
    "rule 5, circled digit before a number": (
        "500 million doses a year", "The plant supplies " + CIRCLED_ONE + "500 million doses a year",
        "The plant supplies 500 million doses a year"),
    "rule 5, fraction cut after its first digit": (
        "2 lines at Plant North in 2026", "The company will add 1" + HALF + " lines at Plant North in 2026",
        "The company will add 2 lines at Plant North in 2026"),
    "rule 5, sign before a fraction": (
        HALF + " percent at Plant North in 2026", "Output changed by -" + HALF + " percent at Plant North in 2026",
        "Output changed by " + HALF + " percent at Plant North in 2026"),
    **{f"ruling a, en dash joins, {name} separates": (
        "will add two lines at Plant North", "The plan for 2025" + EN_DASH + "will add two lines at Plant North",
        "The company" + dash + "founded in 1990" + dash + "will add two lines at Plant North")
       for name, dash in (("em dash", EM_DASH), ("horizontal bar", HORIZONTAL_BAR))},
    "ruling b, soft hyphen at a line end": (
        "likely to expand capacity at Plant North",
        "The company is un" + SOFT_HYPHEN + "\nlikely to expand capacity at Plant North",
        "The company is likely to expand capacity at Plant North"),
    "ruling c, number split at a line end": (
        "20 percent of capacity at Plant North", "Output rose by 10-\n20 percent of capacity at Plant North",
        "Output rose by 20 percent of capacity at Plant North"),
    **{f"ruling d, quote starting with {name} after a number": (
        sign + "20 percent of capacity at Plant North",
        "Output rose by 10" + sign + "20 percent of capacity at Plant North",
        "Output rose by " + sign + "20 percent of capacity at Plant North")
       for name, sign in (("a hyphen", "-"), ("a minus sign", MINUS), ("a plus sign", "+"))},
    "ruling d, quote starting with a hyphen after a letter": (
        "-19 vaccines were filled at Plant North", "COVID-19 vaccines were filled at Plant North",
        "Of the batches, -19 vaccines were filled at Plant North"),
    "ruling e, superscript digit directly before": (
        "(one million) doses at the site", "Annual capacity is 10" + SUP_SIX + "(one million) doses at the site",
        "Annual capacity is 10" + SUP_SIX + " (one million) doses at the site"),
    **{f"ruling f, {name} before a number": (
        "20 million for the new site", "The company will spend " + sign + "20 million for the new site",
        "The company will spend " + sign + " 20 million for the new site")
       for name, sign in (("euro sign", EURO), ("dollar sign", "$"), ("pound sign", POUND))},
    **{f"principle, {prefix} before a dollar sign": (
        "$20 million for the new site", f"It will spend {prefix}$20 million for the new site",
        "It will spend $20 million for the new site")
       for prefix in ("A", "HK", "C", "R")},
    "principle, sign before a currency sign": (
        EURO + "20 million net income in 2025", "The company reported -" + EURO + "20 million net income in 2025",
        "The company reported " + EURO + "20 million net income in 2025"),
    **{f"principle, comparison sign {hex(ord(sign))}": (
        "20 percent of revenue came from Plant North",
        "Last year " + sign + "20 percent of revenue came from Plant North",
        "Last year 20 percent of revenue came from Plant North")
       for sign in ("<", ">", chr(0x2264), chr(0x2265), "~", chr(0xB1))},
    "principle, range of percentages": (
        "-30% of capacity at Plant North", "Lines ran at 20%-30% of capacity at Plant North",
        "Lines ran at -30% of capacity at Plant North"),
    "principle, fraction with a slash": (
        "4 of the shares in the company", "The fund holds 3/4 of the shares in the company",
        "The fund holds 4 of the shares in the company"),
    "principle, ratio": ("20 before filling at Plant North", "The plant dilutes the batch 1:20 before filling at "
                         "Plant North", "The plant dilutes the batch 20 before filling at Plant North"),
    "principle, bracketed prefix": (
        "likely to expand capacity at Plant North", "The company is (un)likely to expand capacity at Plant North",
        "The company is (likely to expand capacity at Plant North"),
    **{f"principle, minus look-alike {hex(ord(sign))}": (
        "20 percent of capacity at Plant North", "Output changed by " + sign + "20 percent of capacity at Plant North",
        "Output changed by 20 percent of capacity at Plant North")
       for sign in (chr(0x2D7), chr(0x2796), chr(0x2043))},
    "fix 2 ruling a, wave dash before a number": (
        "30% of capacity at Plant North", "Lines ran at 20" + WAVE_DASH + "30% of capacity at Plant North",
        "Lines ran at 30% of capacity at Plant North"),
    "fix 2 ruling a, wave dash in Japanese text": (
        "30%" + JA_CAPACITY, "20" + WAVE_DASH + "30%" + JA_CAPACITY, JA_FACTORY + "30%" + JA_CAPACITY),
    **{f"fix 2 ruling b, Chinese quote after {hex(ord(mark))}": (
        ZH_QUOTE, ZH_SAID + "*" + ZH_QUOTE, ZH_SAID + mark + ZH_QUOTE)
       for mark in (FULL_COLON, FULL_SEMICOLON)},
    "fix 2 ruling b, Latin quote after a full-width comma": (
        LATIN_LINES, JA_CAPACITY + "*" + LATIN_LINES, JA_CAPACITY + FULL_COMMA + LATIN_LINES),
    "fix 2 ruling c, number after a Han multiplier": (
        "5000" + JA_INVEST, JA_TOTAL + "3" + OKU + "5000" + JA_INVEST, JA_TOTAL + "5000" + JA_INVEST),
    "fix 2 ruling c, number after man": (
        "2000" + JA_TONS, JA_ANNUAL + "1" + MAN + "2000" + JA_TONS, JA_ANNUAL + "2000" + JA_TONS),
    "fix 2 ruling c, Han numeral after a wave dash": (
        SANJU + "%" + JA_CAPACITY, NIJU + WAVE_DASH + SANJU + "%" + JA_CAPACITY,
        JA_FACTORY + SANJU + "%" + JA_CAPACITY),
    **{f"fix 2 ruling e, symbol range split at a line end with {name}": (
        "30% of capacity at Plant North", "Lines ran at 20%" + dash + "\n30% of capacity at Plant North",
        "Lines ran at 30% of capacity at Plant North")
       for name, dash in (("a hyphen", "-"), ("an en dash", EN_DASH))},
    **{f"fix 2 ruling f, {name} range at a line end": (
        "30 percent of capacity at Plant North", "Output rose by 20" + dash + "\n30 percent of capacity at Plant North",
        "Output rose by 30 percent of capacity at Plant North")
       for name, dash in (("em dash", EM_DASH), ("horizontal bar", HORIZONTAL_BAR))},
    "fix 2 ruling g, soft hyphen between digits": (
        "20 percent of capacity at Plant North",
        "Output rose by 10" + SOFT_HYPHEN + "\n20 percent of capacity at Plant North",
        "Output rose by 20 percent of capacity at Plant North"),
    "fix 2 addendum, Chinese quote after an opening quotation mark": (
        ZH_QUOTE, ZH_SAID + "*" + ZH_QUOTE, ZH_SAID + LEFT_DOUBLE + ZH_QUOTE),
    "fix 2 addendum, Chinese quote after a full-width comma": (
        ZH_QUOTE, ZH_SAID + "*" + ZH_QUOTE, ZH_SAID + FULL_COMMA + ZH_QUOTE),
    "fix 2 addendum, spaced double hyphen": (   # refused twin "2025-" since fix round 3 ("2025--" is a dash)
        "will add two lines at Plant North", "The plan for 2025- will add two lines at Plant North",
        "The company -- founded in 1990 -- will add two lines at Plant North"),
    "fix 3, Han numeral after a list number": (
        MITSUBISHI, "1" + MITSUBISHI, "1." + MITSUBISHI),
    "fix 3, German price before a word": (
        "Euro per unit at Plant North", "The price is 500- Euro per unit at Plant North",
        "The price is 500,- Euro per unit at Plant North"),
    "fix 3, colon and hyphen before a word": (
        "Euro per unit at Plant North", "The steps are as follows- Euro per unit at Plant North",
        "The steps are as follows:- Euro per unit at Plant North"),
}

# A word as the copy has it and as the quote gives it. Added next to a quote, it decides the one haystack variant
# (exact, dehyphenated, line_hyphen_kept) in which the quote can be found.
SEAMS = {
    "exact": ("final review", "final review"),
    "dehyphenated": ("expan-\nsion", "expansion"),
    "line_hyphen_kept": ("fill-\nfinish", "fill-finish"),
}


@pytest.mark.parametrize("mode", SEAMS)
@pytest.mark.parametrize("quote, refused, honest", END_CASES.values(), ids=list(END_CASES))
def test_a_match_may_not_end_inside_a_number_or_joined_word_in_any_variant(quote, refused, honest, mode):
    in_copy, in_quote = SEAMS[mode]
    quote = f"the {in_quote} team: {quote}"
    assert find_quote(quote, f"Reported by the {in_copy} team: {refused}").reason == "not_found"
    assert find_quote(quote, f"Reported by the {in_copy} team: {honest}").mode == mode


@pytest.mark.parametrize("mode", SEAMS)
@pytest.mark.parametrize("quote, refused, honest", START_CASES.values(), ids=list(START_CASES))
def test_a_match_may_not_start_inside_a_number_or_joined_word_in_any_variant(quote, refused, honest, mode):
    in_copy, in_quote = SEAMS[mode]
    quote = f"{quote} for the {in_quote} team"
    assert find_quote(quote, f"{refused} for the {in_copy} team.").reason == "not_found"
    assert find_quote(quote, f"{honest} for the {in_copy} team.").mode == mode


def test_a_spaced_dash_is_an_ordinary_boundary():
    quote = "The company - founded in 1990 - will add two lines"
    assert find_quote(quote, quote + " at Plant North.").passed
    copy = "The company - founded in 1990 - will add two lines at Plant North."
    assert find_quote("will add two lines at Plant North", copy).passed
    assert find_quote("The company - founded in 1990", copy).passed
    for copy in ("The company will add 20 lines.", "The company will add 20 - the largest step so far."):
        assert find_quote("The company will add 20", copy).passed, copy


def test_a_hyphen_inside_the_quote_or_before_its_first_word_does_not_matter():
    copy = "The company adds two high-speed syringe lines for customers in Europe."
    assert find_quote("adds two high-speed syringe lines", copy).passed
    assert find_quote("syringe lines for customers in Europe", copy).passed


def test_a_quote_beside_or_across_a_line_end_hyphen_still_matches():
    copy = "The company is un-\nlikely to expand capacity at Plant North before 2030."
    assert find_quote("expand capacity at Plant North before 2030", copy).passed
    r = find_quote("unlikely to expand capacity at Plant North before 2030", copy)
    assert (r.passed, r.mode) == (True, "dehyphenated")
    r = find_quote("fill-finish customers, starting in 2028", COPY)
    assert (r.passed, r.mode) == (True, "line_hyphen_kept")


def test_a_year_at_the_end_of_a_quote_still_matches_before_a_comma():
    copy = "Two syringe lines for customers, starting in 2028, the company said."
    assert find_quote("syringe lines for customers, starting in 2028", copy).passed


def test_a_quote_ending_on_a_superscript_digit_matches_the_same_mark():
    copy = "The plant has a capacity of 10" + SUP_SIX + " tonnes."
    assert find_quote("The plant has a capacity of 10" + SUP_SIX, copy).passed


def test_normalise_makes_every_no_break_space_a_space_and_the_typographic_apostrophe_ascii():
    assert normalise("20" + NBSP + "000") == normalise("20" + NARROW_NBSP + "000") == "20 000"
    assert normalise("20" + RIGHT_QUOTE + "000") == "20'000"


def test_grouping_needs_exactly_three_digits_after_the_separator():
    assert find_quote("The company will add 20", "The company will add 20 1000-litre tanks.").passed
    for quote in ("The company will add 20", "The company will add 20 000"):
        assert find_quote(quote, "The company will add 20 000 000 lines.").reason == "not_found", quote


def test_a_year_directly_followed_by_a_three_digit_figure_is_refused_by_design():
    # The accepted cost of rule 4: the copy cannot tell "2025 300" from a number grouped with a space.
    assert find_quote("The plan was approved in 2025", "The plan was approved in 2025 300 days late.").reason \
        == "not_found"


def test_a_refused_occurrence_does_not_hide_a_later_honest_one():
    copy = ("They signed a non-binding agreement to buy the Plant North site. "
            "A year later they signed a binding agreement to buy the Plant North site.")
    assert find_quote("binding agreement to buy the Plant North site", copy).passed
    copy = "The company will add 20 000 lines. Then it said: The company will add 20 lines."
    assert find_quote("The company will add 20", copy).passed


def test_chinese_and_japanese_characters_next_to_a_hyphen_keep_their_behaviour():
    # Han characters that are not numerals (fix round 2, ruling c: a numeral next to "-" reads as a number).
    han, latin = _text(*range(0x4E0A, 0x4E1E)), "Plant North adds two new lines"
    # Fix round 1, rule 3: only an edge with a Chinese or Japanese character on either side is exempt. Here the
    # hyphen and "P" meet, so the quote must cover the whole word, hyphens included.
    copy = han[:10] + "-" + latin + "-" + han[10:]
    assert find_quote(latin, copy).reason == "not_found"
    assert find_quote("-" + latin + "-", copy).passed
    assert find_quote(han, "Plant North-" + han + "-Site").passed


# --- other number characters are never folded into plain digits (quote hardening, rule 5) ---------------------------

def test_normalise_keeps_circled_digits_and_fractions_but_still_folds_the_rest():
    assert normalise("500" + CIRCLED_ONE) == "500" + CIRCLED_ONE
    assert normalise("1" + HALF + " lines") == "1" + HALF + " lines"
    ligature, full_width_two = chr(0xFB01), chr(0xFF12)
    assert normalise(ligature + "lling " + CIRCLED_ONE + full_width_two + HALF) == "filling " + CIRCLED_ONE + "2" + HALF


def test_a_quote_with_the_same_circled_digit_or_fraction_still_matches():
    copy = "Each year the plant supplies 500" + CIRCLED_ONE + " million doses. It will add 1" + HALF + " lines."
    assert find_quote("Each year the plant supplies 500" + CIRCLED_ONE + " million doses", copy).passed
    assert find_quote("Each year the plant supplies 500" + CIRCLED_ONE, copy).passed
    assert find_quote("It will add 1" + HALF + " lines.", copy).passed


# --- round 2: rulings (a) to (f) ------------------------------------------------------------------------------------

# The controller's examples, lengthened to five words where they were shorter.
ROUND_2_ROWS = [
    ("likely to expand capacity at Plant North",
     "The company is un" + SOFT_HYPHEN + "\nlikely to expand capacity at Plant North."),
    ("20 percent of capacity at Plant North", "Output rose by 10-\n20 percent of capacity at Plant North."),
    ("-20 percent of capacity at Plant North", "Output varied between 10-20 percent of capacity at Plant North."),
    ("The plant cuts its emissions of CO", "The plant cuts its emissions of CO" + SUB_TWO + " by half."),
    ("a site of 10,000 m", "The plant stands on a site of 10,000 m" + SUP_TWO + "."),
    ("The company will add 20", "The company will add 20% more capacity."),
    ("20 million for the new site", "The company will spend " + EURO + "20 million for the new site."),
]


@pytest.mark.parametrize("quote, copy", ROUND_2_ROWS)
def test_round_2_cases_are_not_found(quote, copy):
    r = find_quote(quote, copy)
    assert (r.passed, r.mode, r.reason) == (False, None, "not_found")


def test_normalise_spaces_em_dashes_but_keeps_the_en_dash_a_plain_hyphen():
    assert normalise("1990" + EM_DASH + "will") == normalise("1990" + HORIZONTAL_BAR + "will") == "1990 - will"
    assert normalise("1990 " + EM_DASH + " will") == "1990 - will"
    assert normalise("10" + EN_DASH + "20") == "10-20"


def test_a_quote_across_an_em_dash_matches_typed_with_the_dash_or_a_spaced_hyphen():
    copy = "The company" + EM_DASH + "founded in 1990" + EM_DASH + "will add two lines at Plant North."
    for quote in ("founded in 1990" + EM_DASH + "will add two lines", "founded in 1990 - will add two lines",
                  "founded in 1990 " + EM_DASH + " will add two lines", "will add two lines at Plant North"):
        assert find_quote(quote, copy).passed, quote


def test_a_soft_hyphen_at_a_line_end_joins_the_word_in_every_variant():
    copy = "The company is un" + SOFT_HYPHEN + "\nlikely to expand capacity at Plant North."
    assert find_quote("likely to expand capacity at Plant North", copy).reason == "not_found"
    r = find_quote("unlikely to expand capacity at Plant North", copy)
    assert (r.passed, r.mode) == (True, "exact")
    assert find_quote("expand capacity at Plant North", copy).passed
    assert normalise("un" + SOFT_HYPHEN + "\nlikely") == "unlikely"
    assert normalise("10" + SOFT_HYPHEN + "\n20") == "1020"   # also after a digit (fix round 2, ruling g)


def test_round_2_keeps_ordinary_boundaries():
    assert find_quote("syringe lines for customers, starting in 2028",
                      "Two syringe lines for customers, starting in 2028 (subject to approval).").passed
    assert find_quote("Output at Plant North grew by 20%", "Output at Plant North grew by 20% in 2025.").passed
    quote = "The company will spend " + EURO + "20 million for the new site"
    assert find_quote(quote, quote + ".").passed
    copy = "The company is unlikely to expand capacity at Plant North."
    assert find_quote("expand capacity at Plant North", copy).passed
    copy = "Output fell by -20 percent of capacity at Plant North."
    assert find_quote("-20 percent of capacity at Plant North", copy).passed


def test_a_quote_ending_right_before_a_footnote_mark_must_include_the_mark():
    # Ruling e: a raised digit directly after the match refuses it, whatever the quote's last character is.
    copy = "The plant will open in 2026." + SUP_ONE + " Costs are not yet known."
    assert find_quote("The plant will open in 2026.", copy).reason == "not_found"
    assert find_quote("The plant will open in 2026." + SUP_ONE, copy).passed


# --- fix round 1: a quote covers whole words as they stand between spaces -----------------------------------------

# The reviewer's cases that still matched, lengthened to five words where they were shorter.
FIX_1_ROWS = [
    (EURO + "20 million net income in 2025", "The company reported -" + EURO + "20 million net income in 2025."),
    *[("$20 million for the new site", f"It will spend {prefix}$20 million for the new site.")
      for prefix in ("A", "HK", "C", "R")],
    *[("20 percent of revenue came from Plant North", sign + "20 percent of revenue came from Plant North.")
      for sign in ("<", ">", chr(0x2264), chr(0x2265), "~", chr(0xB1))],
    *[("Output at Plant North grew by 20%", "Output at Plant North grew by 20%" + dash + "30%.")
      for dash in ("-", EN_DASH)],
    ("The company plans to invest " + EURO + "20m",
     "The company plans to invest " + EURO + "20m" + EN_DASH + EURO + "30m."),
    ("-30% of capacity at Plant North", "Lines ran at 20%-30% of capacity at Plant North."),
    ("The plant will start production in 2025", "The plant will start production in 2025/26."),
    ("4 of the shares in the company", "The fund holds 3/4 of the shares in the company."),
    ("Management said the company can", "Management said the company can't."),
    ("a supply contract with Drug Maker B", "It signed a supply contract with Drug Maker B's parent company."),
    ("The plant reaches a purity of 10", "The plant reaches a purity of 10" + chr(0x207B) + SUP_SIX + "."),
    ("The plant dilutes the batch 1", "The plant dilutes the batch 1:20 before filling."),
    ("The company will add 20", "The company will add 20* lines."),
    ("likely to expand capacity at Plant North", "The company is (un)likely to expand capacity at Plant North."),
    *[("20 percent of capacity at Plant North", "Output changed by " + sign + "20 percent of capacity at Plant North.")
      for sign in (chr(0x2D7), chr(0x2796), chr(0x2043))],
]


@pytest.mark.parametrize("quote, copy", FIX_1_ROWS)
def test_a_quote_must_cover_whole_words_between_spaces(quote, copy):
    r = find_quote(quote, copy)
    assert (r.passed, r.mode, r.reason) == (False, None, "not_found")


def test_only_opening_and_closing_marks_may_be_left_off_at_the_ends():
    quote = "syringe lines for customers, starting in 2028"
    for copy in ("(Two syringe lines for customers, starting in 2028)",
                 '"Two syringe lines for customers, starting in 2028."',
                 "Two syringe lines for customers, starting in 2028!"):
        assert find_quote(quote, copy).passed, copy
    quote = "The company will add two lines"
    for copy in ('He said: "The company will add two lines."', "(The company will add two lines.)",
                 "[The company will add two lines]", "{The company will add two lines};",
                 chr(0xBF) + "The company will add two lines?", chr(0xA1) + "The company will add two lines!"):
        assert find_quote(quote, copy).passed, copy
    assert find_quote("It signed a supply contract with Drug Maker B's parent",
                      "It signed a supply contract with Drug Maker B's parent company.").passed
    german = chr(0x201E) + "Die Erweiterung umfasst zwei neue Abfüllanlagen" + chr(0x201C) + ", sagte die Firma."
    assert find_quote("Die Erweiterung umfasst zwei neue Abfüllanlagen", german).passed


def test_normalise_reads_an_em_dash_between_digits_as_a_range():
    assert normalise("1990" + EM_DASH + "2000") == normalise("1990" + HORIZONTAL_BAR + "2000") == "1990-2000"
    assert normalise("1990 " + EM_DASH + " 2000") == "1990 - 2000"
    assert find_quote("The plant ran from 1990-2000 at full speed",
                      "The plant ran from 1990" + EM_DASH + "2000 at full speed.").passed


def test_normalise_joins_a_soft_hyphen_at_a_line_end_before_a_digit_and_drops_the_word_joiner():
    assert normalise("COVID" + SOFT_HYPHEN + "\n19") == "COVID19"
    assert normalise("Plant" + chr(0x2060) + " North") == "Plant North"
    copy = "The site fills vials for COVID" + SOFT_HYPHEN + "\n19 vaccines."
    assert find_quote("The site fills vials for COVID", copy).reason == "not_found"


# --- fix round 1, addendum: Chinese and Japanese punctuation (U+3000 to U+303F) is exempt at an edge ---------------

IDEO_COMMA, IDEO_STOP, CORNER_OPEN, CORNER_CLOSE = chr(0x3001), chr(0x3002), chr(0x300C), chr(0x300D)
# "to expand production capacity", in Japanese
JA_EXPAND = "".join(chr(cp) for cp in (0x751F, 0x7523, 0x80FD, 0x529B, 0x3092, 0x62E1, 0x5927, 0x3059, 0x308B))
LATIN = "Plant North adds two new lines"


@pytest.mark.parametrize("quote, copy", [
    ("2028" + chr(0x5E74) + chr(0x306B) + JA_EXPAND,                        # starts right after an ideographic comma
     chr(0x540C) + chr(0x793E) + chr(0x306F) + IDEO_COMMA + "2028" + chr(0x5E74) + chr(0x306B) + JA_EXPAND + IDEO_STOP),
    (LATIN, JA_EXPAND + IDEO_STOP + LATIN + "."),                              # starts right after an ideographic stop
    (LATIN, JA_EXPAND + CORNER_OPEN + LATIN + CORNER_CLOSE + JA_EXPAND),       # inside corner brackets
    (JA_EXPAND + IDEO_STOP, CORNER_OPEN + JA_EXPAND + IDEO_STOP + CORNER_CLOSE),  # ends on a stop before a bracket
])
def test_chinese_and_japanese_punctuation_is_exempt_at_an_edge(quote, copy):
    assert find_quote(quote, copy).passed


def test_chinese_and_japanese_punctuation_does_not_exempt_an_edge_elsewhere():
    # The exemption covers the edge next to the mark only; a Latin word cut inside stays refused.
    assert find_quote("lant North adds two new lines", JA_EXPAND + IDEO_STOP + LATIN + ".").reason == "not_found"
    assert find_quote("Plant North adds two new line", CORNER_OPEN + LATIN + CORNER_CLOSE).reason == "not_found"


# --- fix round 2 ---------------------------------------------------------------------------------------------------

# The re-review's cases that still matched, in the form the controller gave them.
FIX_2_REFUSED = [
    ("30%" + JA_CAPACITY, "20" + WAVE_DASH + "30%" + JA_CAPACITY + IDEO_STOP),                     # point 1
    ("30% of capacity at Plant North", "Lines ran at 20" + WAVE_DASH + "30% of capacity at Plant North."),
    ("Output at Plant North grew by 20%", "Output at Plant North grew by 20%" + WAVE_DASH + "30%."),
    ("5000" + JA_INVEST, JA_TOTAL + "3" + OKU + "5000" + JA_INVEST + IDEO_STOP),                  # point 3
    (JA_TOTAL + "3" + OKU, JA_TOTAL + "3" + OKU + "5000" + JA_INVEST + IDEO_STOP),
    ("2000" + JA_TONS, JA_ANNUAL + "1" + MAN + "2000" + JA_TONS + IDEO_STOP),
    *[("Management said the company can", "Management said the company can" + accent + "t.")    # point 4
      for accent in ACCENTS_AS_APOSTROPHES],
    *[("30% of capacity at Plant North", "Lines ran at 20%" + dash + "\n30% of capacity at Plant North.")  # point 5
      for dash in ("-", EN_DASH)],
    ("30 percent of capacity at Plant North",                                                      # point 6
     "Output rose by 20" + EM_DASH + "\n30 percent of capacity at Plant North."),
    ("20 percent of capacity at Plant North",                                                      # point 7
     "Output rose by 10" + SOFT_HYPHEN + "\n20 percent of capacity at Plant North."),
]


@pytest.mark.parametrize("quote, copy", FIX_2_REFUSED)
def test_fix_round_2_cases_are_not_found(quote, copy):
    r = find_quote(quote, copy)
    assert (r.passed, r.mode, r.reason) == (False, None, "not_found")


FIX_2_FOUND = [
    *[(ZH_QUOTE, ZH_SAID + mark + ZH_QUOTE + IDEO_STOP) for mark in (FULL_COLON, FULL_SEMICOLON)],   # point 2
    (LATIN_LINES, ZH_SAID + FULL_COMMA + LATIN_LINES + IDEO_STOP),
    (LATIN_LINES, LATIN_LINES + FULL_COMMA + ZH_SAID + IDEO_STOP),
    *[("Management said the company can't", "Management said the company can" + accent + "t.")    # point 4
      for accent in ACCENTS_AS_APOSTROPHES],
    ("The company will add two lines", "He said: " + chr(0x2039) + "The company will add two lines." + chr(0x203A)),
    ("Die Erweiterung umfasst zwei neue Abfüllanlagen",                                              # point 8
     chr(0x201A) + "Die Erweiterung umfasst zwei neue Abfüllanlagen" + chr(0x2018) + ", sagte die Firma."),
    ("500 million doses a year were filled", "500 million doses a year were filled at Plant North in 2025"),  # 9
]


@pytest.mark.parametrize("quote, copy", FIX_2_FOUND)
def test_fix_round_2_honest_quotes_are_found(quote, copy):
    assert find_quote(quote, copy).passed


@pytest.mark.parametrize("quote, copy", [
    (ZH_QUOTE, ZH_SAID + FULL_COMMA + ZH_QUOTE + IDEO_STOP),                    # a Han character beyond the comma
    (JA_TOTAL + "30", JA_TOTAL + "30" + FULL_COMMA + JA_PLAN + IDEO_STOP),       # quote ends in a digit before it
    (JA_TOTAL + "30", JA_TOTAL + "30" + FULL_STOP_WIDE + JA_PLAN),              # the same with a full-width stop
])
def test_a_comma_or_full_stop_with_text_beyond_is_punctuation_not_part_of_a_number(quote, copy):
    assert find_quote(quote, copy).passed


@pytest.mark.parametrize("quote, copy", [
    (JA_TOTAL + "3", JA_TOTAL + "3.5" + OKU + JA_PLAN),                          # 3.5 oku cut at the full stop
    ("500" + JA_INVEST, JA_TOTAL + "3" + FULL_COMMA + "500" + JA_INVEST),        # a full-width comma inside 3,500
    ("5" + JA_INVEST, JA_TOTAL + "1.5" + JA_INVEST),                              # 1.5 man cut after the full stop
    (JA_TOTAL + "3", JA_TOTAL + "3,500" + JA_INVEST),                             # 3,500 man cut before the comma
])
def test_a_comma_or_full_stop_inside_a_number_still_joins_it(quote, copy):
    assert find_quote(quote, copy).reason == "not_found"


# --- fix round 3: a comma or full stop is part of a number only between two ASCII digits ---------------------------

@pytest.mark.parametrize("quote, copy", [
    (ZH_INVEST_500_YI, ZH_INVEST_500_YI + FULL_COMMA + YEAR_2025 + JA_PLAN + IDEO_STOP),
    (ZH_INVEST_500_YI, ZH_INVEST_500_YI + "," + YEAR_2025 + JA_PLAN + IDEO_STOP),
    (JA_TOTAL_5_MAN, JA_TOTAL_5_MAN + FULL_COMMA + YEAR_2028 + JA_PLAN + IDEO_STOP),
    (ZH_ONE_OF, ZH_ONE_OF + "," + YEAR_2028 + JA_PLAN + IDEO_STOP),
    (MITSUBISHI, "1." + MITSUBISHI + IDEO_STOP),                                          # a list number before it
    (JA_INVEST + JA_PLAN, JA_TOTAL + "3," + JA_INVEST + JA_PLAN),                        # formerly refused: "3," + man
    (JA_TOTAL + SANJU, JA_TOTAL + SANJU + ",5" + OKU + JA_PLAN),           # formerly refused: numeral + ",5"
])
def test_a_comma_or_full_stop_next_to_a_han_numeral_is_punctuation(quote, copy):
    assert find_quote(quote, copy).passed


# --- fix round 3: a word ending in a hyphen joins only after a letter, digit, %, per mille, degree or currency -----

@pytest.mark.parametrize("copy", [
    "The price is 500,- Euro per unit at Plant North.",
    "The steps are as follows:- Euro per unit at Plant North.",
    "The plan-- Euro per unit at Plant North.",
    "The company,-- Euro per unit at Plant North.",
])
def test_a_hyphen_after_punctuation_is_an_ordinary_boundary(copy):
    assert find_quote("Euro per unit at Plant North", copy).passed


@pytest.mark.parametrize("before", ["un-", "10-", "20%-", "20" + PER_MILLE + "-", "20" + DEGREE + "-",
                                    "20" + EURO + "-", "$20-"])
def test_a_word_split_at_a_line_end_still_refuses_the_match(before):
    copy = f"It said {before}\nlikely to expand capacity at Plant North."
    assert find_quote("likely to expand capacity at Plant North", copy).reason == "not_found", before
    copy = "The lab runs pre- and post-approval checks on each batch."
    assert find_quote("and post-approval checks on each batch", copy).reason == "not_found"


def test_the_prime_is_a_unit_mark_not_an_apostrophe():
    copy = "The ceiling height at Plant North is 5" + PRIME + " in the old hall."
    assert find_quote("The ceiling height at Plant North is 5", copy).reason == "not_found"
    assert find_quote("The ceiling height at Plant North is 5" + PRIME, copy).passed
    assert find_quote("Management said the company can't", "Management said the company can" + PRIME + "t.") \
        .reason == "not_found"
    assert normalise("5" + PRIME) == "5" + PRIME


def test_a_dash_typed_as_hyphens_is_an_ordinary_boundary():
    for dash in ("--", "---"):
        copy = f"The company {dash} founded in 1990 {dash} will add two lines at Plant North."
        assert find_quote("will add two lines at Plant North", copy).passed, dash
    # Fix round 3, ruling (e) narrowed: the character before the final "-" is "-", so "20%--" is a dash as well.
    copy = "Lines ran at 20%--\n30% of capacity at Plant North."
    assert find_quote("30% of capacity at Plant North", copy).passed
    copy = "Lines ran at 20%-\n30% of capacity at Plant North."
    assert find_quote("30% of capacity at Plant North", copy).reason == "not_found"


@pytest.mark.parametrize("quote, copy", [
    (ZH_QUOTE, ZH_SAID + FULL_COLON + LEFT_DOUBLE + ZH_QUOTE + IDEO_STOP + RIGHT_DOUBLE),
    (ZH_QUOTE, ZH_SAID + LEFT_DOUBLE + ZH_QUOTE + RIGHT_DOUBLE + ZH_SAID),
    (LATIN_LINES, ZH_SAID + FULL_COLON + LEFT_DOUBLE + LATIN_LINES + RIGHT_DOUBLE + ZH_SAID),
    (ZH_QUOTE, ZH_SAID + chr(0x2018) + ZH_QUOTE + chr(0x2019) + IDEO_STOP),
    (ZH_QUOTE, ZH_SAID + "{" + ZH_QUOTE + "}" + ZH_SAID),
])
def test_quotation_marks_next_to_chinese_text_are_exempt_at_an_edge(quote, copy):
    assert find_quote(quote, copy).passed


def test_quotation_marks_next_to_chinese_text_do_not_exempt_a_cut_word():
    copy = ZH_SAID + LEFT_DOUBLE + LATIN_LINES + RIGHT_DOUBLE + ZH_SAID
    assert find_quote("lant North adds two new lines", copy).reason == "not_found"
    assert find_quote("Plant North adds two new line", copy).reason == "not_found"


def test_normalise_fix_round_2():
    assert normalise("20" + EM_DASH + "\n30") == normalise("20" + HORIZONTAL_BAR + " 30") == "20- 30"   # ruling f
    assert normalise("add 20 " + EM_DASH + " 30") == "add 20 - 30"
    assert normalise("can" + chr(0xB4) + "t") == normalise("can" + chr(0x1FBD) + "t") == "can't"     # ruling d
    assert normalise(chr(0x2039) + "neu" + chr(0x203A)) == "'neu'"                                   # ruling h
