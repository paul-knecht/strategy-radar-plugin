"""One name per company, country and unit: fixed lists, for display only. All names are invented."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from radar import tidy

ENGINE = Path(tidy.__file__).parent


# --- units ---------------------------------------------------------------------------------------------------------

def test_m2_and_sqm_are_one_unit():
    assert tidy.unit("m2")["name"] == tidy.unit("sqm")["name"] == tidy.unit("square metres")["name"] == "m²"
    assert tidy.unit("M²")["name"] == tidy.unit("Sq  M")["name"] == tidy.unit("m^2")["name"] == "m²"


def test_dashes_and_case_are_evened_in_a_unit():
    assert tidy.unit("Square\u2011Foot")["name"] == tidy.unit("sq. ft.")["name"] == "ft²"


def test_a_unit_carries_its_family_and_factor():
    assert tidy.unit("sq ft") == {"name": "ft²", "family": "area", "factor": Decimal("0.09290304")}
    assert tidy.unit("USD billion")["factor"] == Decimal("1000")


def test_blank_or_missing_unit_is_none():
    assert tidy.unit(None) is None and tidy.unit("  ") is None and tidy.unit(5) is None


def test_square_feet_convert_to_square_metres_and_keep_what_was_stated():
    s = tidy.size("21528", "square feet")
    assert s["stated"] == "21528 ft²" and s["unit"] == "ft²" and s["number"] == Decimal("21528")
    assert s["converted"] == {"number": "2000", "unit": "m²", "about": True}
    assert s["compare_unit"] == "m²"


def test_an_exact_conversion_is_not_about():
    s = tidy.size("1562500", "ft²")
    assert s["converted"] == {"number": "145161", "unit": "m²", "about": False}


def test_a_rounding_that_leaves_a_whole_number_is_still_about():
    s = tidy.size("10000.1", "ft2")           # 929.03...
    assert s["converted"]["about"] is True
    s = tidy.size("2.5", "ft2")               # 0.2322576 -> 0.23
    assert s["converted"] == {"number": "0.232", "unit": "m²", "about": True}
    s = tidy.size("0.01", "ft2")              # 0.0009290304 -> 0.000929, about
    assert s["converted"] == {"number": "0.000929", "unit": "m²", "about": True}


def test_an_inexact_conversion_keeps_three_significant_figures():
    assert tidy.size("160000", "ft²")["converted"] == {"number": "14900", "unit": "m²", "about": True}   # 14864.49
    assert tidy.size("1", "ft²")["converted"]["number"] == "0.0929"
    assert tidy.size("10763.91", "ft²")["converted"]["number"] == "1000"                                 # 1000.0...


def test_rounding_is_half_up():
    s = tidy.size("0.5", "USD billion")       # 500 exactly
    assert s["converted"] == {"number": "500", "unit": "USD million", "about": False}


def test_usd_billion_converts_to_usd_million():
    s = tidy.size("1.2", "$ billion")
    assert s["stated"] == "1.2 USD billion"
    assert s["converted"] == {"number": "1200", "unit": "USD million", "about": False}
    assert s["compare_unit"] == "USD million"


def test_a_size_already_in_the_base_unit_has_no_conversion():
    s = tidy.size("2000", "sqm")
    assert s["converted"] is None and s["compare_unit"] == "m²" and s["unit"] == "m²"
    assert s["stated"] == "2000 m²"


def test_currencies_never_convert_into_each_other():
    assert tidy.unit("€m")["family"] != tidy.unit("$m")["family"]
    assert tidy.size("5", "€ billion")["converted"]["unit"] == "EUR million"
    assert tidy.size("5", "£m")["converted"] is None
    assert tidy.size("5", "CHF bn")["converted"]["unit"] == "CHF million"


def test_filling_production_and_syringe_lines_are_one_unit_lines():
    for written in ("lines", "line", "filling lines", "Filling Line", "production lines", "production line",
                    "prefilled syringe lines", "pre-filled syringe line"):
        assert tidy.unit(written) == {"name": "lines", "family": None, "factor": None}
    assert tidy.size("2", "filling lines")["compare_unit"] == "lines"


def test_an_unknown_unit_is_kept_as_written():
    u = tidy.unit("autoinjectors per minute")
    assert u == {"name": "autoinjectors per minute", "family": None, "factor": None}
    s = tidy.size("40", "autoinjectors  per minute")
    assert s["stated"] == "40 autoinjectors per minute" and s["converted"] is None
    assert s["compare_unit"] == "autoinjectors per minute"


def test_a_value_that_is_not_a_plain_number_is_not_converted():
    s = tidy.size("1.200", "sq ft")
    assert s["number"] is None and s["converted"] is None and s["stated"] == "1.200 ft²"
    assert tidy.size("about 20", "sqm")["number"] is None


def test_a_size_without_a_unit_or_a_value():
    s = tidy.size("12", None)
    assert s == {"stated": "12", "unit": None, "number": Decimal("12"), "converted": None, "compare_unit": None}
    s = tidy.size(None, "sqm")
    assert s["stated"] == "m²" and s["number"] is None and s["converted"] is None


# --- countries -----------------------------------------------------------------------------------------------------

def test_us_variants_are_one_country():
    assert tidy.countries("US") == tidy.countries("U.S.") == tidy.countries("USA") == ["United States"]
    assert tidy.countries(" u.s.a. ") == tidy.countries("United States of America") == ["United States"]


def test_a_value_naming_several_countries_stays_a_list():
    assert tidy.countries("Italy, Belgium, US") == ["Italy", "Belgium", "United States"]
    assert tidy.countries("Belgium; Netherlands") == ["Belgium", "Netherlands"]
    assert tidy.countries("Italy / Spain & Norway") == ["Italy", "Spain", "Norway"]
    assert tidy.countries("US and Europe") == ["United States", "Europe"]
    assert tidy.countries("Bosnia and Herzegovina") == ["Bosnia and Herzegovina"]


def test_a_country_named_twice_is_listed_once():
    assert tidy.countries("US, USA") == ["United States"]


def test_blank_country_is_an_empty_list():
    assert tidy.countries(None) == [] and tidy.countries("") == [] and tidy.countries("  ") == []


def test_an_unknown_place_is_kept_as_written_with_spaces_evened():
    assert tidy.countries("Exampleland") == ["Exampleland"]
    assert tidy.countries("Example   Islands, UK") == ["Example Islands", "United Kingdom"]


@pytest.mark.parametrize("written, country", [
    ("Great Britain", "United Kingdom"), ("Britain", "United Kingdom"), ("GBR", "United Kingdom"),
    ("Republic of Korea", "South Korea"), ("Korea", "South Korea"), ("Czech Republic", "Czechia"),
    ("Holland", "Netherlands"), ("The Netherlands", "Netherlands"), ("Swiss Confederation", "Switzerland"),
    ("UAE", "United Arab Emirates"), ("Türkiye", "Turkey"), ("DEU", "Germany"), ("pr", "Puerto Rico"),
])
def test_common_variants(written, country):
    assert tidy.countries(written) == [country]


def test_the_list_covers_the_required_countries_and_has_no_ambiguous_variant():
    data = json.loads((ENGINE / "countries_en.json").read_text(encoding="utf-8"))
    required = ("Austria Belgium Bulgaria Croatia Cyprus Czechia Denmark Estonia Finland France Germany Greece Hungary "
                "Ireland Italy Latvia Lithuania Luxembourg Malta Netherlands Poland Portugal Romania Slovakia Slovenia "
                "Spain Sweden Iceland Liechtenstein Norway Switzerland Canada Mexico Brazil Argentina China Japan India "
                "Singapore Australia Israel Turkey").split()
    required += ["United Kingdom", "United States", "South Korea", "Saudi Arabia", "United Arab Emirates",
                 "South Africa", "Puerto Rico"]
    assert not [name for name in required if name not in data]
    assert all(len(v) >= 2 and all(len(code) in (2, 3) for code in v[:2]) for v in data.values())
    seen = {}
    for name, variants in data.items():
        for written in [name, *variants]:
            key = written.casefold().replace(".", "").replace(" ", "")
            assert seen.setdefault(key, name) == name, f"{written} names two countries"


# --- company names -------------------------------------------------------------------------------------------------

def test_legal_endings_are_dropped_but_holdings_is_kept():
    assert tidy.company_key("Competitor C Inc.") == tidy.company_key("competitor c")
    assert tidy.company_key("Example Holdings") != tidy.company_key("Example Nordic")
    assert tidy.company_key("Example Holdings") == "example holdings"
    assert tidy.company_key("Example Group") == "example group"
    assert tidy.company_key("Example Pharma") == "example pharma"


@pytest.mark.parametrize("written", [
    "Example Pharma Inc", "Example Pharma, Inc.", "Example Pharma GmbH", "Example Pharma GmbH & Co. KG",
    "Example Pharma AG", "Example Pharma S.p.A.", "Example Pharma S.A.", "Example Pharma Pte Ltd",
    "Example Pharma Limited", "Example Pharma, Corp.", "Example Pharma Co., Ltd.", "Example Pharma A/S",
    "EXAMPLE   PHARMA  plc", "Example Pharma N.V.", "Example Pharma B.V.", "Example Pharma Oy", "Example Pharma AB",
    "Example Pharma S.r.l.", "Example Pharma Pty Ltd", "Example Pharma Corporation", "  \u201cExample Pharma\u201d ",
])
def test_each_legal_ending_is_dropped_from_the_end(written):
    assert tidy.company_key(written) == "example pharma"


def test_endings_are_dropped_repeatedly_but_only_at_the_end():
    assert tidy.company_key("Example Co Inc") == "example"
    assert tidy.company_key("Inc Example") == "inc example"
    assert tidy.company_key("Examplesa") == "examplesa"
    assert tidy.company_key("Inc") == "inc"             # nothing left if the ending went


def test_clean_company_keeps_the_letter_case_and_evens_spaces():
    assert tidy.clean_company("  Competitor   C, Inc. ") == "Competitor C"
    assert tidy.clean_company("Example Holdings Ltd") == "Example Holdings"
    assert tidy.clean_company("Müller GmbH & Co. KG") == "Müller"
    assert tidy.clean_company("Example\u00a0Pharma") == "Example Pharma"


# --- the companies of a run ----------------------------------------------------------------------------------------

PACK = {"companies": [
    {"name": "Example Pharma", "other_names": ["Example Holdings"], "home": True},
    {"name": "Competitor A", "other_names": ["Comp A Holding"], "home": False},
]}


def test_other_names_resolve_to_the_pack_name():
    c = tidy.Companies.from_run({"companies": [{"name": "Competitor A", "other_names": ["Comp A Holding"],
                                                "home": False}]})
    assert c.resolve("COMP A HOLDING AG") == {"key": c.resolve("Competitor A")["key"], "name": "Competitor A",
                                              "pack": True, "home": False}


def test_listed_is_the_pack_companies_in_order():
    c = tidy.Companies.from_run(PACK)
    assert [x["name"] for x in c.listed] == ["Example Pharma", "Competitor A"]
    assert c.resolve("example pharma inc")["home"] is True


def test_another_company_is_tidied_and_not_a_pack_company():
    c = tidy.Companies.from_run(PACK)
    assert c.resolve("Drug Maker B Ltd.") == {"key": "drug maker b", "name": "Drug Maker B", "pack": False,
                                              "home": False}


def test_a_blank_name_resolves_to_none():
    c = tidy.Companies.from_run(PACK)
    assert c.resolve("") is None and c.resolve("   ") is None and c.resolve(None) is None


def test_an_old_run_has_its_home_company_as_the_one_pack_company():
    c = tidy.Companies.from_run({"home_company": "Example Pharma"})
    assert c.listed == [{"name": "Example Pharma", "other_names": [], "home": True}]
    assert c.resolve("Example Pharma Inc")["home"] is True


def test_a_run_without_companies_has_none():
    assert tidy.Companies.from_run({}).listed == []
    assert tidy.Companies.from_run({"home_company": None}).listed == []
    assert tidy.Companies.from_run({"companies": [], "home_company": "Example Pharma"}).listed == []
    assert tidy.Companies.from_run({}).resolve("Competitor A")["pack"] is False


def test_names_to_find():
    c = tidy.Companies.from_run(PACK)
    assert c.names_to_find("COMP A HOLDING AG") == ["Competitor A", "Comp A Holding"]
    assert c.names_to_find("Drug  Maker B Ltd.") == ["Drug Maker B Ltd.", "Drug Maker B"]
    assert c.names_to_find("Drug Maker B") == ["Drug Maker B"]
    assert c.names_to_find("") == []


# --- a name in a text ----------------------------------------------------------------------------------------------

def test_a_name_is_found_only_as_whole_words():
    assert tidy.name_in(["Competitor A"], ["Competitor  a said"]) and not tidy.name_in(["Competitor A"], ["Competitor AB said"])
    assert not tidy.name_in(["Competitor A"], ["Supercompetitor A said"])
    assert not tidy.name_in(["Competitor A"], ["Competitor A2 said"])


def test_a_name_may_sit_beside_punctuation_and_in_any_of_the_texts():
    assert tidy.name_in(["Competitor A"], ["nothing", "(Competitor A), the maker."])
    assert tidy.name_in(["Comp A Holding", "Competitor A"], ["Competitor A\nopens a plant"])
    assert tidy.name_in(["Competitor C Inc."], ["Competitor C Inc. bought it"])


def test_no_names_or_texts_find_nothing():
    assert not tidy.name_in([], ["Competitor A"]) and not tidy.name_in(["Competitor A"], [])
    assert not tidy.name_in(["", "  "], ["Competitor A"])
    assert not tidy.name_in(["Competitor A"], [None, 5])
