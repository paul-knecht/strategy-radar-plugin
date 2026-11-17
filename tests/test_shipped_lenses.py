"""The lenses that ship with the plugin, in `lenses/`: what a program can check about them.

Whether a sentence of a lens says what its work or its slides state was judged by the independent lens review; the
evidence stays on the author's computer. These tests pin what has a fixed answer: the shipped lenses pass the check
for real use, the folder holds exactly the approved lenses, no lens names either company the project must not
publish, every lens holds its eight parts and the day it was checked, no lens text is longer than the check allows, no
two lenses share a sentence, and each lens's level is the lowest level of its originals.
"""
import json
import re
from pathlib import Path

import pytest

from plugin_helpers import company_names_in
from radar import store
from radar.lenses import THEMES_FILE, check_lenses, read_themes

ROOT = Path(__file__).resolve().parent.parent
LENSES = ROOT / "lenses"

EXPECTED = ("absorbing-growth", "absorptive-capacity", "adapt-aggregate-arbitrage", "agency-costs",
            "architectural-innovation", "asset-specificity", "assets-built-over-time", "barriers-to-new-competition",
            "behavioural-theory-of-the-firm", "bidder-hubris", "bounded-rationality", "build-abroad-market-or-cost",
            "capacity-to-deter-entry", "co-opetition", "competence-destroying-change", "corporate-parenting",
            "corporate-strategy-tests", "cost-of-integrating", "cultural-dimensions", "default-alive",
            "deliberate-and-emergent-strategy", "diamond-of-national-advantage", "diffusion-of-innovations",
            "disruption-from-below", "distance-between-countries", "dominant-design", "dominant-logic",
            "dynamic-capabilities", "economies-of-scope", "endorsement-by-prominent-backers", "escalating-commitment",
            "exploration-and-exploitation", "fast-decisions", "first-mover-advantages", "five-competitive-forces",
            "founder-and-track-record", "free-cash-flow", "gains-from-partners", "generic-strategies",
            "governing-value-chains", "how-investors-decide", "how-much-industry-matters", "industry-life-cycle",
            "inside-and-outside-view", "integrating-acquisitions", "integration-or-local-responsiveness",
            "internalising-across-borders", "investing-abroad-for-control", "jockey-or-horse", "knowledge-based-view",
            "layers-of-responsibility", "managing-for-stakeholders", "modularity", "natural-resource-view",
            "network-effects", "organizations-becoming-alike", "population-ecology", "product-cycle-abroad",
            "product-market-fit", "product-market-growth", "profit-as-the-firms-responsibility", "regional-not-global",
            "related-or-unrelated-diversification", "resource-dependence", "resources-hard-to-copy",
            "responses-to-institutional-pressure", "responsibility-as-investment", "routines-and-evolution",
            "staged-financing", "step-by-step-entry-abroad", "strategic-groups",
            "strategy-not-operational-effectiveness", "structure-follows-strategy", "sunk-costs-and-concentration",
            "tariffs-subsidies-supply-chains", "team-production", "three-models-of-a-decision", "two-sided-markets",
            "unit-economics-of-a-customer", "value-chain", "what-a-firm-is-good-at", "who-owns-the-asset",
            "who-profits-from-innovation")
NOT_YET = {
    # Rivals' capacity decisions. The work it was to rest on states nothing on capacity, so no sentence of the lens
    # could rest on a confirmed fact, and the lens is left out.
    "interdependent-capacity": "the work it was to rest on states nothing on capacity",
}
# A lens's level is the lowest level of its originals. No shipped lens rests on lecture slides; fifty-five rest on sources about the works; twenty-one were written from the model's general knowledge of a work whose reference was confirmed.
LEVEL = {
    "absorbing-growth": "original_read",
    "absorptive-capacity": "reference_confirmed",
    "adapt-aggregate-arbitrage": "secondary_source_read",
    "agency-costs": "secondary_source_read",
    "architectural-innovation": "reference_confirmed",
    "asset-specificity": "original_read",
    "assets-built-over-time": "reference_confirmed",
    "barriers-to-new-competition": "secondary_source_read",
    "behavioural-theory-of-the-firm": "secondary_source_read",
    "bidder-hubris": "reference_confirmed",
    "bounded-rationality": "secondary_source_read",
    "build-abroad-market-or-cost": "reference_confirmed",
    "capacity-to-deter-entry": "reference_confirmed",
    "co-opetition": "secondary_source_read",
    "competence-destroying-change": "reference_confirmed",
    "corporate-parenting": "reference_confirmed",
    "corporate-strategy-tests": "secondary_source_read",
    "cost-of-integrating": "original_read",
    "cultural-dimensions": "secondary_source_read",
    "default-alive": "original_read",
    "deliberate-and-emergent-strategy": "secondary_source_read",
    "diamond-of-national-advantage": "secondary_source_read",
    "diffusion-of-innovations": "secondary_source_read",
    "disruption-from-below": "reference_confirmed",
    "distance-between-countries": "secondary_source_read",
    "dominant-design": "secondary_source_read",
    "dominant-logic": "reference_confirmed",
    "dynamic-capabilities": "secondary_source_read",
    "economies-of-scope": "reference_confirmed",
    "endorsement-by-prominent-backers": "secondary_source_read",
    "escalating-commitment": "secondary_source_read",
    "exploration-and-exploitation": "secondary_source_read",
    "fast-decisions": "reference_confirmed",
    "first-mover-advantages": "secondary_source_read",
    "five-competitive-forces": "secondary_source_read",
    "founder-and-track-record": "secondary_source_read",
    "free-cash-flow": "reference_confirmed",
    "gains-from-partners": "secondary_source_read",
    "generic-strategies": "secondary_source_read",
    "governing-value-chains": "secondary_source_read",
    "how-investors-decide": "secondary_source_read",
    "how-much-industry-matters": "secondary_source_read",
    "industry-life-cycle": "secondary_source_read",
    "inside-and-outside-view": "reference_confirmed",
    "integrating-acquisitions": "reference_confirmed",
    "integration-or-local-responsiveness": "secondary_source_read",
    "internalising-across-borders": "secondary_source_read",
    "investing-abroad-for-control": "secondary_source_read",
    "jockey-or-horse": "secondary_source_read",
    "knowledge-based-view": "secondary_source_read",
    "layers-of-responsibility": "secondary_source_read",
    "managing-for-stakeholders": "secondary_source_read",
    "modularity": "secondary_source_read",
    "natural-resource-view": "reference_confirmed",
    "network-effects": "reference_confirmed",
    "organizations-becoming-alike": "secondary_source_read",
    "population-ecology": "secondary_source_read",
    "product-cycle-abroad": "secondary_source_read",
    "product-market-fit": "secondary_source_read",
    "product-market-growth": "reference_confirmed",
    "profit-as-the-firms-responsibility": "original_read",
    "regional-not-global": "reference_confirmed",
    "related-or-unrelated-diversification": "reference_confirmed",
    "resource-dependence": "secondary_source_read",
    "resources-hard-to-copy": "secondary_source_read",
    "responses-to-institutional-pressure": "secondary_source_read",
    "responsibility-as-investment": "secondary_source_read",
    "routines-and-evolution": "secondary_source_read",
    "staged-financing": "secondary_source_read",
    "step-by-step-entry-abroad": "secondary_source_read",
    "strategic-groups": "secondary_source_read",
    "strategy-not-operational-effectiveness": "secondary_source_read",
    "structure-follows-strategy": "secondary_source_read",
    "sunk-costs-and-concentration": "secondary_source_read",
    "tariffs-subsidies-supply-chains": "original_read",
    "team-production": "secondary_source_read",
    "three-models-of-a-decision": "secondary_source_read",
    "two-sided-markets": "secondary_source_read",
    "unit-economics-of-a-customer": "secondary_source_read",
    "value-chain": "secondary_source_read",
    "what-a-firm-is-good-at": "original_read",
    "who-owns-the-asset": "secondary_source_read",
    "who-profits-from-innovation": "reference_confirmed",
}
LOWEST_FIRST = ("reference_confirmed", "course_slides", "secondary_source_read", "original_read")
PARTS = {"id", "name", "idea", "suggests", "limits", "competing_idea", "questions", "originals", "checked_on"}
# The parts in a lens's own words. A reference is left out of the sentence check: lenses share a reference by design
# (one work stands behind a lens and the competing idea of another).
OWN_WORDS = ("name", "idea", "suggests", "limits", "competing_idea")
SENTENCE_WORDS = 12
MAX_TEXT = 400

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def load(folder: Path) -> dict[str, dict]:
    """Every lens of a folder, by the name of its file. The themes index is not a lens."""
    return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json"))
            if path.name != THEMES_FILE}


def strings(value) -> list[str]:
    """Every text in a lens, at any depth."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in strings(item)]
    return []


def sentences(text: str) -> list[str]:
    """The whole sentences of a text, each in lower case, its spaces collapsed and its closing mark left off."""
    found = []
    for piece in _SENTENCE_END.split(text):
        sentence = " ".join(piece.lower().split()).rstrip(".!?")
        if sentence:
            found.append(sentence)
    return found


def long_sentences(lens: dict) -> set[str]:
    """The sentences of 12 or more words in the lens's own words: its texts and its three questions."""
    texts = [lens.get(key) for key in OWN_WORDS] + list(lens.get("questions") or [])
    return {sentence for text in texts if isinstance(text, str) for sentence in sentences(text)
            if len(sentence.split()) >= SENTENCE_WORDS}


def shared_sentences(lenses: dict[str, dict]) -> list[tuple[str, str, str]]:
    """(sentence, one lens, another lens) for each long sentence that two lenses both hold."""
    first = {}
    shared = []
    for lens_id, lens in lenses.items():
        for sentence in sorted(long_sentences(lens)):
            if sentence in first:
                shared.append((sentence, first[sentence], lens_id))
            else:
                first[sentence] = lens_id
    return shared


def lens_level(lens: dict) -> str:
    """The lowest level among all the lens's originals."""
    return min((original["level"] for original in lens["originals"]), key=LOWEST_FIRST.index)


def test_the_shipped_lenses_pass_the_check_for_real_use():
    assert check_lenses(LENSES, real=True) == []


def test_the_shipped_themes_group_the_lenses_as_approved():
    themes, problems = read_themes(LENSES)
    assert problems == []
    assert [(theme["name"], theme["lenses"]) for theme in themes] == [
        ("Where the firm's boundary lies",
         ["asset-specificity", "cost-of-integrating", "team-production", "agency-costs", "who-owns-the-asset",
          "gains-from-partners", "resource-dependence", "economies-of-scope"]),
        ("Resources, capabilities and growth",
         ["what-a-firm-is-good-at", "absorbing-growth", "resources-hard-to-copy", "absorptive-capacity",
          "product-market-growth", "assets-built-over-time", "dynamic-capabilities",
          "routines-and-evolution", "knowledge-based-view", "exploration-and-exploitation",
          "natural-resource-view"]),
        ("International business and trade",
         ["build-abroad-market-or-cost", "tariffs-subsidies-supply-chains", "diamond-of-national-advantage",
          "distance-between-countries", "adapt-aggregate-arbitrage", "product-cycle-abroad",
          "investing-abroad-for-control", "internalising-across-borders", "step-by-step-entry-abroad",
          "integration-or-local-responsiveness", "cultural-dimensions", "governing-value-chains",
          "regional-not-global"]),
        ("Positioning and competitive advantage",
         ["value-chain", "generic-strategies", "strategy-not-operational-effectiveness"]),
        ("Industry structure and profitability",
         ["barriers-to-new-competition", "strategic-groups", "how-much-industry-matters",
          "sunk-costs-and-concentration", "industry-life-cycle"]),
        ("Competitive moves and interaction", ["co-opetition", "first-mover-advantages"]),
        ("Competition and industry structure", ["five-competitive-forces", "capacity-to-deter-entry", "network-effects"]),
        ("Innovation and who gains from it",
         ["who-profits-from-innovation", "disruption-from-below", "dominant-design", "architectural-innovation",
          "competence-destroying-change", "diffusion-of-innovations"]),
        ("Judgement and forecasts", ["inside-and-outside-view"]),
        ("Platforms and modular systems", ["two-sided-markets", "modularity"]),
        ("Corporate strategy, acquisitions and organisation",
         ["corporate-parenting", "dominant-logic", "integrating-acquisitions", "bidder-hubris", "free-cash-flow",
          "corporate-strategy-tests", "related-or-unrelated-diversification", "structure-follows-strategy"]),
        ("How firms decide",
         ["bounded-rationality", "behavioural-theory-of-the-firm", "three-models-of-a-decision",
          "deliberate-and-emergent-strategy", "escalating-commitment", "fast-decisions"]),
        ("Institutions and organisational environments",
         ["organizations-becoming-alike", "population-ecology", "responses-to-institutional-pressure"]),
        ("The firm's responsibility to society",
         ["profit-as-the-firms-responsibility", "managing-for-stakeholders", "layers-of-responsibility",
          "responsibility-as-investment"]),
        ("Venture screening",
         ["product-market-fit", "jockey-or-horse", "how-investors-decide", "founder-and-track-record",
          "unit-economics-of-a-customer", "default-alive", "staged-financing",
          "endorsement-by-prominent-backers"])]
    assert sorted(lens for theme in themes for lens in theme["lenses"]) == sorted(EXPECTED)
    assert company_names_in((LENSES / THEMES_FILE).read_text(encoding="utf-8")) == []


def test_the_folder_holds_exactly_the_approved_lenses():
    assert tuple(sorted(load(LENSES))) == EXPECTED
    assert not set(NOT_YET) & set(EXPECTED)
    for lens_id, reason in NOT_YET.items():
        assert reason and not (LENSES / f"{lens_id}.json").exists(), lens_id


def test_no_lens_names_a_company_the_project_must_not_publish():
    for lens_id, lens in load(LENSES).items():
        for text in strings(lens):
            assert company_names_in(text) == [], lens_id
    for readme in (LENSES / "README.md", ROOT / "README.md"):
        assert company_names_in(readme.read_text(encoding="utf-8")) == [], readme


def test_every_lens_holds_its_eight_parts_and_the_day_it_was_checked():
    for lens_id, lens in load(LENSES).items():
        assert set(lens) == PARTS, lens_id


def test_no_lens_text_is_longer_than_400_characters():
    for lens_id, lens in load(LENSES).items():
        for text in strings(lens):
            assert len(text) <= MAX_TEXT, (lens_id, text[:40])


def test_no_two_lenses_share_a_sentence_of_twelve_or_more_words():
    lenses = load(LENSES)
    for lens_id, lens in lenses.items():
        assert long_sentences(lens), f"{lens_id} has a sentence long enough to be compared"
    assert shared_sentences(lenses) == []


def test_the_sentence_check_finds_a_shared_sentence_but_not_a_shared_run_of_words():
    """Ruling T8b: two lenses may state the same rival view in sentences of their own."""
    view = "a firm tends to grow until one more step inside costs as much as buying it on the market"
    one = {"idea": f"Something else is said first. {view.capitalize()}."}
    same = {"limits": f"  {view.upper()}!  "}
    own = {"competing_idea": f"Another view: {view}, as that work puts it."}
    assert shared_sentences({"one": one, "same": same}) == [(view, "one", "same")]
    assert shared_sentences({"one": one, "own": own}) == []
    short = {"idea": "Firms grow until the margin balances."}
    assert shared_sentences({"a": short, "b": dict(short)}) == []


def test_each_lens_has_the_lowest_level_of_its_originals():
    assert set(LOWEST_FIRST) == set(store.LENS_LEVELS)
    assert {lens_id: lens_level(lens) for lens_id, lens in load(LENSES).items()} == LEVEL


@pytest.mark.parametrize("levels, expected", [
    (["original_read", "original_read"], "original_read"),
    (["original_read", "course_slides"], "course_slides"),
    (["course_slides", "original_read"], "course_slides"),
    (["original_read", "reference_confirmed", "course_slides"], "reference_confirmed"),
])
def test_the_lowest_level_counts_every_original(levels, expected):
    assert lens_level({"originals": [{"level": level} for level in levels]}) == expected


def test_every_shipped_lens_file_is_plain_ascii():
    """The lens batches of 2026-11-16 brought curly quotes, a dash and an accented letter into three references; the
    project's files are plain ASCII, so a shipped lens file holds none."""
    for path in sorted(LENSES.glob("*.json")):
        assert path.read_text(encoding="utf-8").isascii(), path.name
