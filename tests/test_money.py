"""Whether a text states an amount of money, and whether it speaks of money at all."""
from radar import money


def test_an_amount_is_a_currency_near_a_number_or_a_scale_word():
    for text in ("Example Pharma will invest almost half a billion euros in the site.", "€480 million", "for $11 billion",
                 "CHF 1.46 billion", "DKK 16 billion"):
        assert money.states_money(text) is True, text


def test_a_figure_without_a_currency_is_no_amount():
    for text in ("180,000 liters", "2029", "50,000 sqm", "The euro zone grew, the paper said in its last spring issue."):
        assert money.states_money(text) is False, text


def test_money_words_count_as_whole_words_in_any_case():
    assert money.speaks_of_money("No source gives the PRICE of buying a site.") is True
    assert money.speaks_of_money("Nothing on what it would cost to invest.") is True
    assert money.speaks_of_money("No source names a precise date or a payload.") is False


def test_common_phrasings_of_money_count_as_speaking_of_it():
    for text in ("No investments were disclosed.", "No pricing found.", "Financial terms were not disclosed."):
        assert money.speaks_of_money(text) is True, text


def test_words_are_read_with_their_accented_letters():
    # "Müller" read as "M" and "ller" would give the scale word "m" next to the currency word "won"
    assert money.states_money("Müller won the tender.") is False
