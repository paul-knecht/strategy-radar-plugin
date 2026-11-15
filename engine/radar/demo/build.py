"""Builds the illustrative demo run used by the end-to-end tests and by the practice tour.

Everything in it is invented: the companies, the people, the figures and the source texts. The run is
driven through the `radar` command (`radar.cli.main`) only, the way the plugin will drive it. The one
exception is `analysis.json`: the engine has no command for it, because the plugin's lead model writes that
file, so the demo writes it with `store.write_analysis`.

The run holds ten proposed facts. Six end `confirmed`, one `uncertain` and three `rejected`. The three rejected
ones are planted errors: one quote changes a number compared with its source, one quote is word for word in its
source but states a different year than the fact, and one quote is word for word in its source but is cut just
after "not", so the sentence around it says the opposite. Only a checker that reads the passage can catch the
third one.

The run can be built in four stages, so that a practice tour or a test can start part of the way through:
`sources`, `extracted`, `checked` and `complete`.
"""
import contextlib
import io
import json
import os
import shutil
import tempfile
from pathlib import Path

from radar import store
from radar.cli import main
from radar.demo import LENSES, SOURCES   # the package defines both before it imports this module

STAGES = ("sources", "extracted", "checked", "complete")
PRIVATE_DEMO_NOTICE = ("This private demo run is invented, its private-mode notice was not shown to anyone, and it "
                       "cannot take further non-public material.")
# What the private variant stores as the reply to the private-mode notice: no person gave one.
PRIVATE_DEMO_WORDS = ("Recorded by the demo for the invented practice run: no person was shown the notice or gave this "
                      "reply.")

QUESTION = ("Is new filling capacity for injectable medicines being built for the builder's own use or for "
            "outside customers, and what does that mean for Example Pharma's choice between building and buying?")

# The year the first company release gives for the start of production. The changed variant moves it.
START_YEAR = "2028"
MOVED_START_YEAR = "2030"

# One entry per source text, in the order they are saved (S1, S2, ...).
_SOURCE_LIST = [
    dict(name="competitor_a_release", file="s1_competitor_a_release.txt",
         url="https://www.competitor-a.example/news/plant-north-expansion",
         publisher="Competitor A", title="Competitor A to expand its own filling capacity in Country X and Country Y",
         date="2026-05-14", type="company_release",
         speaker="Competitor A's chief operating officer and press office",
         interest="wants to look strong and to reassure investors about supply", language="en"),
    dict(name="example_pharma_release", file="s2_example_pharma_release.txt",
         url="https://www.example-pharma.example/news/site-y-line",
         publisher="Example Pharma", title="Example Pharma starts building its own filling line in Country Y",
         date="2026-07-02", type="company_release",
         speaker="Example Pharma's head of manufacturing",
         interest="wants to justify its own build and to look in control", language="en"),
    dict(name="competitor_b_filing", file="s3_competitor_b_filing.txt",
         url="https://www.competitor-b.example/filings/annual-2025",
         publisher="Competitor B", title="Competitor B, annual filing for 2025 (extract): Properties and capacity",
         date="2026-03-20", type="filing",
         speaker="Competitor B's management, writing for regulators and investors",
         interest="must be accurate for regulators but also wants to sound attractive to customers", language="en"),
    dict(name="drug_maker_b_report", file="s4_drug_maker_b_geschaeftsbericht.txt",
         url="https://www.drug-maker-b.example/geschaeftsbericht-2025",
         publisher="Drug maker B", title="Geschäftsbericht 2025 von Drug maker B (Auszug): Lagebericht, Produktion und Standorte",
         date="2026-04-28", type="annual_report",
         speaker="Drug maker B's management",
         interest="wants to present the sale of its plant as a sound decision", language="de"),
    dict(name="trade_unnamed", file="s5_trade_press_unnamed_source.txt",
         url="https://www.aseptic-trade-journal.example/competitor-c-plant",
         publisher="Aseptic Trade Journal", title="Competitor C may open part of its new plant to outside customers, source says",
         date="2026-09-03", type="trade_press",
         speaker="one unnamed source, quoted by a reporter",
         interest="unknown; the source may want to influence how the market reads Competitor C", language="en"),
    dict(name="trade_repeating", file="s6_trade_press_repeating_release.txt",
         url="https://www.biologics-business-daily.example/competitor-a-filling-lines",
         publisher="Biologics Business Daily", title="Competitor A adds filling lines to keep supply in-house",
         date="2026-05-16", type="trade_press",
         speaker="a reporter repeating Competitor A's announcement",
         interest="wants readers and adds no checks of its own", language="en", based_on="competitor_a_release"),
]

_INTERNAL_SOURCE = dict(
    name="internal_note", file="private/s7_example_pharma_internal_memo.txt",
    url="internal://example-pharma/planning-note-2026-08",
    publisher="Example Pharma", title="Example Pharma, internal planning note: filling capacity for prefilled syringes",
    date="2026-08-20", type="other",
    speaker="Example Pharma's manufacturing planning team",
    interest="wants support for its own plan", language="en")


class DemoError(RuntimeError):
    """A radar command ended with an exit code the demo did not expect."""


def _radar(*argv, ok=(0,)) -> dict:
    """Run one radar command through `main`; return the JSON it printed. An unexpected exit code raises."""
    args = [str(part) for part in argv]
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(args)
    output = buffer.getvalue().strip()
    if code not in ok:
        raise DemoError(f"radar {' '.join(args)} ended with code {code}: {output}")
    return json.loads(output.splitlines()[-1])


def _fields(company, move_type, site, country, what_added, size_value, announced, planned_start, stage, access,
            delivery="not_yet", size_unit="lines") -> dict:
    return {"company": company, "move_type": move_type, "site": site, "country": country,
            "what_added": what_added, "size_value": size_value, "size_unit": size_unit,
            "announced": announced, "planned_start": planned_start, "stage": stage,
            "access": access, "delivery": delivery}


def _fact(kind, statement, quote, source, fields=None, *, primary=True, tentative_reason=None,
          supporting=None, language="en", translation=None) -> dict:
    return {"kind": kind, "statement": statement, "quote": quote, "quote_language": language,
            "quote_translation": translation, "source_id": source, "supporting": supporting or [],
            "primary_source": primary, "certainty": "tentative" if tentative_reason else "firm",
            "tentative_reason": tentative_reason, "fields": fields}


def _proposals(source_ids: dict, start: str) -> dict:
    """The proposed facts by short name, each ready to be written to a JSON file for `radar add-fact`.

    Every detail of a fact the demo confirms or keeps as uncertain is stated by one of its quotes, as the support
    checker's rules ask: a detail that stands next to the main quote is covered by a wider main quote (Competitor A's
    Plant North) or by a supporting quote from the same source (Example Pharma's line, Competitor B's name), and a
    detail no quote states is left empty or set to the value that says so. Only the planted errors break the rules.
    """
    s = source_ids
    return {
        "a_north": _fact(
            "capacity_move",
            f"Competitor A will add two filling lines at Plant North in Country X for its own products, "
            f"with production planned to start in {start}.",
            f"Competitor A will add two filling lines at Plant North in Country X. The two new lines will fill "
            f"only Competitor A's own injectable products, and production is planned to start in {start}.",
            s["competitor_a_release"],
            _fields("Competitor A", "expansion", "Plant North", "Country X",
                    "two filling lines", "2", "2026-05-14", start, "announced", "captive"),
            supporting=[{"source_id": s["trade_repeating"],
                         "quote": f"According to the company's announcement, Competitor A will add two filling "
                                  f"lines at Plant North, the lines will fill only Competitor A's own injectable "
                                  f"products, and production is planned to start in {start}."}]),
        "a_south": _fact(
            "capacity_move",
            "Competitor A is building Plant South in Country Y with one filling line for its own products, "
            "expected to start operating in 2027.",
            "Plant South in Country Y, now under construction, will add one filling line reserved for "
            "Competitor A's own products and is expected to start operating in 2027.",
            s["competitor_a_release"],
            _fields("Competitor A", "new_site", "Plant South", "Country Y",
                    "one filling line", "1", "2026-05-14", "2027", "under_construction", "captive")),
        "example_own": _fact(
            "capacity_move",
            "Example Pharma is building one new filling line at Site Y in Country Y, for its own products, "
            "scheduled to start filling in 2027.",
            "Construction of the new line began in March 2026 and the line is scheduled to start filling in "
            "2027. The line will be used only for Example Pharma's own products.",
            s["example_pharma_release"],
            _fields("Example Pharma", "expansion", "Site Y", "Country Y",
                    "a single high-speed unit for prefilled syringes", "1", "2026-07-02", "2027",
                    "under_construction", "captive"),
            supporting=[{"source_id": s["example_pharma_release"],
                         "quote": "Example Pharma today confirmed that work has begun on a new sterile filling "
                                  "line at its Site Y plant in Country Y."},
                        {"source_id": s["example_pharma_release"],
                         "quote": "The new line is a single high-speed unit for prefilled syringes."}]),
        "b_site": _fact(
            "capacity_move",
            "Competitor B runs three filling lines at its site in Country Z, all open to third-party "
            "customers, in operation since January 2026.",
            "Our site in Country Z began commercial filling in January 2026 and now runs three filling "
            "lines. All three lines are open to third-party customers under multi-year contracts.",
            s["competitor_b_filing"],
            _fields("Competitor B", "new_site", None, "Country Z", "three filling lines",
                    "3", "2026-03-20", "2026-01", "operating", "open", delivery="unknown"),
            supporting=[{"source_id": s["competitor_b_filing"],
                         "quote": "Competitor B provides contract filling of injectable medicines for other drug "
                                  "makers."}]),
        "b_demand": _fact(
            "general",
            "Competitor B says its contract filling slots at the Country Z site are fully booked through the "
            "end of 2027.",
            "Contract filling slots at the Country Z site are fully booked through the end of 2027.",
            s["competitor_b_filing"]),
        # The seller's report is not the buyer's own statement: the fact says who states what, it is not a primary
        # source, the quote dates the sale and not its announcement, and the trade journal's report of the buyer's
        # own words when the purchase was completed is the independent second source that confirms it.
        "c_buy": _fact(
            "capacity_move",
            "Competitor C bought Drug maker B's filling plant in Country Y, with two filling lines already in "
            "operation, in December 2025. Drug maker B says Competitor C will use the plant only for its own "
            "products, and a trade journal reports that Competitor C said so when the purchase was completed.",
            "Wir haben unser Abfüllwerk in Country Y im Dezember 2025 an Competitor C verkauft; es umfasst "
            "zwei Abfüllanlagen, die bereits in Betrieb sind. Competitor C wird das Werk ausschließlich für "
            "eigene Produkte nutzen.",
            s["drug_maker_b_report"],
            _fields("Competitor C", "acquisition", None, "Country Y", "two filling lines", "2", "not_stated",
                    None, "operating", "captive", delivery="unknown"),
            primary=False,
            supporting=[{"source_id": s["trade_unnamed"],
                         "quote": "Competitor C declined to comment on the report. A spokesperson referred earlier "
                                  "questions to the statement issued when Competitor C completed its purchase of the "
                                  "filling plant in Country Y with its two filling lines, in which the company said "
                                  "the plant would be used for its own products."}],
            language="de",
            translation="We sold our filling plant in Country Y to Competitor C in December 2025; it comprises "
                        "two filling lines that are already in operation. Competitor C will use the plant "
                        "exclusively for its own products."),
        # One unnamed source: the fact keeps the hedge and the attribution, and states no country, date or kind of
        # move that its quote does not state.
        "c_open": _fact(
            "capacity_move",
            "A person quoted by a trade journal said Competitor C could offer one of its plant's two filling "
            "lines to outside customers in a filling partnership, once its own products have been moved over. "
            "The person called the talks early and said no customer had signed.",
            "Competitor C could offer one of the plant's two filling lines to outside customers once its own "
            "products have been moved over, the person said. The person described the talks about such a "
            "filling partnership as early and said no customer had signed.",
            s["trade_unnamed"],
            _fields("Competitor C", "partnership", None, None, "one of the plant's two filling lines", "1",
                    "not_stated", None, "not_stated", "open", delivery="unknown"),
            primary=False, tentative_reason="one unnamed source, not confirmed by the company"),
        # Planted error 1: the quote changes one number compared with the source text (45 became 54).
        "planted_number": _fact(
            "general",
            "The three lines at Competitor B's Country Z site have a combined capacity of 54 million vials "
            "a year.",
            "The three lines have a combined capacity of 54 million vials a year.",
            s["competitor_b_filing"]),
        # Planted error 2: the quote is in the source word for word, but it says 2027 and the fact says 2029. Every
        # other detail is stated by its quotes (the same quotes from its own source as Example Pharma's line, and the
        # sentence that makes the line captive), so the year is the one thing wrong.
        "planted_year": _fact(
            "capacity_move",
            "Example Pharma's new line at Site Y is scheduled to start filling in 2029.",
            "Construction of the new line began in March 2026 and the line is scheduled to start filling in "
            "2027.",
            s["example_pharma_release"],
            _fields("Example Pharma", "expansion", "Site Y", "Country Y",
                    "a single high-speed unit for prefilled syringes", "1", "2026-07-02", "2029",
                    "under_construction", "captive"),
            supporting=[{"source_id": s["example_pharma_release"],
                         "quote": "Example Pharma today confirmed that work has begun on a new sterile filling "
                                  "line at its Site Y plant in Country Y."},
                        {"source_id": s["example_pharma_release"],
                         "quote": "The new line is a single high-speed unit for prefilled syringes."},
                        {"source_id": s["example_pharma_release"],
                         "quote": "The line will be used only for Example Pharma's own products."}]),
        # Planted error 3: the quote is in the source word for word, but it is cut just after "not". The sentence
        # around it says that Competitor A does NOT plan to offer the lines. Only reading the passage shows that.
        "planted_negation": _fact(
            "general",
            "Competitor A plans to offer its new filling lines to other drug makers.",
            "plan to offer the new lines to other drug makers",
            s["competitor_a_release"]),
        # Only in the changed variant: a new rumour from the same trade article.
        "d_new": _fact(
            "capacity_move",
            "Competitor D is said to be weighing a new filling site in Country Z.",
            "Competitor D is said to be weighing a new filling site in Country Z, although the source gave no "
            "size or date.",
            s["trade_unnamed"],
            _fields("Competitor D", "new_site", None, "Country Z", "a new filling site", None, "not_stated", None,
                    "not_stated", "not_stated", delivery="unknown", size_unit=None),
            primary=False, tentative_reason="one unnamed source, not confirmed by the company"),
        "internal_note": _fact(
            "general",
            "Example Pharma's own planning note expects its outside filling contracts to cover less of its "
            "syringe volume in 2027 than they do today.",
            "Our outside filling contracts will cover less of our syringe volume in 2027 than they do today.",
            s.get("internal_note")),   # only exists in a private run
    }


# The planted errors that the support check turns down. Every other fact that needs a verdict passes. The planted
# number is not here: its quote is not found, so the program settles it alone and no verdict is asked for.
_NOT_SUPPORTED = {"planted_year", "planted_negation"}
_SUPPORT_NOTES = {
    "planted_year": "The quote says the line starts filling in 2027, but the fact says 2029.",
    "planted_negation": "The sentence around the quote says the opposite: Competitor A does not plan to offer "
                        "the new lines.",
}


def _analysis(ids: dict, start: str) -> dict:
    """The analysis. It rests on confirmed and uncertain facts only; the planted errors are not used."""
    a_n, a_s, ex, b_s, b_d, c_b = (ids[name] for name in
                                   ("a_north", "a_south", "example_own", "b_site", "b_demand", "c_buy"))
    analysis = {
        "messages": [
            {"id": "M1",
             "text": "New filling capacity in this sample is mostly built for the builder's own use, not for "
                     "outside customers.",
             "confidence": "medium",
             "chain": [
                 {"kind": "fact",
                  "text": "Competitor A is adding lines at Plant North and at Plant South, and Example Pharma is "
                          "building a line at Site Y. Each says its lines are for its own products. Drug maker B "
                          "says Competitor C bought a plant from it and will use it for its own products.",
                  "fact_ids": [a_n, a_s, ex, c_b], "lens_id": None},
                 {"kind": "fact",
                  "text": "The only site in the sample that is stated to be open to other customers is "
                          "Competitor B's.",
                  "fact_ids": [b_s], "lens_id": None},
                 {"kind": "reasoning",
                  "text": "A firm keeps a step inside when buying it is costly or risky. Companies that build "
                          "for their own use may be protecting supply and launch timing, which would fit that "
                          "idea, though the confirmed facts do not state their reasons.",
                  "fact_ids": [], "lens_id": "firm-boundaries"},
                 {"kind": "conclusion",
                  "text": "In the moves confirmed here, 6 lines are for the builder's own use, and the lines "
                          "open to outside customers are 33 percent of all lines. Most of the capacity confirmed "
                          "here is for the builder's own use.",
                  "fact_ids": [], "lens_id": None}],
             "counter_view": "The sample is small and rests on public announcements. Open capacity added by "
                             "companies that do not announce it would not show up here, and one trade report "
                             "suggests Competitor C may open part of its plant to outside customers.",
             "would_change": "New open sites announced by other companies, or Competitor C confirming that it "
                             "will sell filling slots.",
             # No fact of the run states how comparable cases turned out, so the outside view says so and claims
             # nothing, as the analysis format asks.
             "outside_view": {"text": "None found: no fact of this run states how announced capacity plans of "
                                      "this kind turned out, so the announced lines are read here as plans.",
                              "fact_ids": []}},
            {"id": "M2",
             "text": "Open capacity is already scarce, so buying outside filling slots is not a quick alternative "
                     "to building.",
             "confidence": "medium",
             "chain": [
                 {"kind": "fact",
                  "text": "Competitor B states that its contract filling slots in Country Z are booked through "
                          "the end of 2027.",
                  "fact_ids": [b_d], "lens_id": None},
                 {"kind": "fact",
                  "text": "Its lines there are open to other customers and have been running since January 2026.",
                  "fact_ids": [b_s], "lens_id": None},
                 {"kind": "reasoning",
                  "text": "When the one open provider in the sample is full, a buyer needs either a new open "
                          "site or a slot at a provider this sample does not cover.",
                  "fact_ids": [], "lens_id": None},
                 {"kind": "conclusion",
                  "text": "Outside filling capacity may stay hard to get until new open sites start. "
                          "No open site among the confirmed moves is under construction.",
                  "fact_ids": [], "lens_id": None}],
             "counter_view": "Competitor B may add lines if customers commit to them. Whether it plans to is an "
                             "open question that the facts checked here do not answer.",
             "would_change": "Competitor B announcing more lines, or a customer reporting free outside slots "
                             "during 2027.",
             "outside_view": {"text": "None found: no fact of this run states how soon booked contract capacity "
                                      "frees up in comparable cases.",
                              "fact_ids": []}},
            {"id": "M3",
             "text": "Example Pharma's own build puts it on the same path as most rivals. The open question is "
                     "speed, not build versus buy.",
             "confidence": "low",
             "chain": [
                 {"kind": "fact",
                  "text": "Example Pharma is building one line at Site Y, for its own products, due in 2027.",
                  "fact_ids": [ex], "lens_id": None},
                 {"kind": "fact",
                  "text": "Drug maker B says Competitor C bought a working plant whose lines were already "
                          "running, and will use it for its own products.",
                  "fact_ids": [c_b], "lens_id": None},
                 {"kind": "reasoning",
                  "text": "A plant is hard to reverse, so these moves tell rivals how each firm means to "
                          "compete. Captive lines commit their owners to supplying themselves, and rivals may "
                          "read Example Pharma's line as a sign that it will need less outside capacity later.",
                  "fact_ids": [], "lens_id": "capacity-commitment"},
                 {"kind": "conclusion",
                  "text": "For Example Pharma, speed may matter more than the build-or-buy label. Drug maker B "
                          "says the plant Competitor C bought was already running, while the new builds confirmed "
                          "here are due in 2027 or later.",
                  "fact_ids": [], "lens_id": None}],
             "counter_view": "The sample shows only one sale of a working plant, and no plant for sale. Buying "
                             "may not be open to Example Pharma at all.",
             "would_change": "A seller of a working plant coming forward, or Example Pharma's own line slipping "
                             "past its planned start.",
             "outside_view": {"text": "None found: no fact of this run states how buying a working plant compared "
                                      "with building one in comparable cases.",
                              "fact_ids": []}},
        ],
        "demand_signals": [
            {"text": "Competitor B says its contract filling slots are booked through the end of 2027.",
             "fact_ids": [b_d]},
            {"text": "Drug maker B reports that Competitor C bought a plant that was already running. That may "
                     "point to a wish for capacity sooner than a new build allows.",
             "fact_ids": [c_b]},
        ],
        "decision_options": {
            "question": "Should Example Pharma add its own filling capacity, buy outside capacity, or do both?",
            "framing": "user", "framing_fact_ids": [],
            "options": [
                {"name": "Build its own capacity",
                 "for": [{"text": "Example Pharma is already building a line at Site Y, due in 2027.",
                          "fact_ids": [ex]},
                         {"text": "Competitor A is adding lines for its own use at Plant North and at Plant South.",
                          "fact_ids": [a_n, a_s]}],
                 "against": [{"text": f"Competitor A's lines at Plant North were announced in May 2026 and are "
                                      f"planned to start in {start}.",
                              "fact_ids": [a_n]}]},
                {"name": "Buy outside capacity",
                 "for": [{"text": "Competitor B's three lines are open to other customers.", "fact_ids": [b_s]}],
                 "against": [{"text": "Competitor B's contract slots are booked through the end of 2027.",
                              "fact_ids": [b_d]}]},
                {"name": "Buy a working plant",
                 "for": [{"text": "Drug maker B reports that Competitor C bought a plant with two lines already in "
                                  "operation.", "fact_ids": [c_b]}],
                 "against": [{"text": "No plant for sale appears in the sources we read.", "fact_ids": []}]},
            ],
            "internal_questions": [
                "How much of Example Pharma's volume could move to an outside provider without a new "
                "regulatory approval?",
                "What would a year of delay at Site Y cost?"]},
        "watch_items": [
            {"text": "Whether Competitor B announces more lines or reports free slots.",
             "trigger": "Competitor B's next annual filing, or a customer reporting free outside slots.",
             "scenario_id": "SC2"},
            {"text": "Progress at Plant North.",
             "trigger": "A construction contract award or a revised start date from Competitor A.",
             "scenario_id": "SC1"},
        ],
        "audit_flags": [
            {"check": "independence",
             "text": "The report that Competitor C may open a line to outside customers rests on one unnamed "
                     "source. It is marked uncertain and no message depends on it."},
            {"check": "evidence_symmetry",
             "text": "Every message rests on what companies chose to publish: their own releases, a filing, an "
                     "annual report and trade reports of them. What companies do not announce is not seen in this "
                     "run. The evidence for open capacity here is one company's filing and one unnamed report."},
        ],
        "not_found": [
            "No source says how much of Competitor A's new capacity could ever serve outside customers.",
            "No public source gives the price of outside filling slots, so costs cannot be compared.",
        ],
        "contradictions": [],
        "lens_notes": [
            {"lens_id": "firm-boundaries",
             "here": "Competitor A and Example Pharma state that their new filling lines are for their own "
                     "products. Drug maker B says Competitor C bought a working plant from it and will use it for "
                     "its own products. The same step sits on different sides of the line for different firms."},
            {"lens_id": "capacity-commitment",
             "here": "Each captive line is a commitment that is hard to undo. The open question is how rivals "
                     "and outside providers will read it."},
        ],
        "assumptions": [
            {"id": "A1", "text": "Outside filling capacity stays tight until at least the end of 2027.",
             "support": "partial",
             "if_wrong": "Buying outside capacity becomes a faster and cheaper route than building.",
             "fact_ids": [b_d, b_s]},
            {"id": "A2", "text": "Announced lines start close to their planned dates.", "support": "weak",
             "if_wrong": "The tight period lasts longer, or ends sooner, than the plans suggest.",
             "fact_ids": [a_n]},
            {"id": "A3", "text": "Rivals keep their new lines for their own use.", "support": "partial",
             "if_wrong": "More outside capacity appears than this report counts.",
             "fact_ids": [a_n, a_s, c_b]},
        ],
        "scenarios": [
            {"id": "SC1", "name": "Tight market",
             "description": "Rivals keep building for their own use and open capacity stays scarce. Example "
                            "Pharma's own line at Site Y becomes the main way to secure supply.",
             "assumption_ids": ["A1", "A3"],
             "signposts": [{"text": "Competitor A confirms its start date for Plant North.", "fact_ids": [a_n]},
                           {"text": "Competitor B still reports its contract slots as fully booked.",
                            "fact_ids": [b_d]}]},
            {"id": "SC2", "name": "New outside capacity arrives",
             "description": "Some rivals open lines to outside customers, or lines arrive early, and buying "
                            "becomes a real option before Example Pharma's own line starts. This scenario "
                            "depends on A2 and A3 turning out differently from the base view.",
             "assumption_ids": ["A2", "A3"],
             "signposts": [{"text": "Competitor C confirms that it will sell filling slots to outside customers.",
                            "fact_ids": []},
                           {"text": "A second contract provider reports free slots.", "fact_ids": []}]},
        ],
        "predictions": [
            {"id": "P1", "message_id": "M1",
             "statement": f"Competitor A's Plant North will start production by the end of {start}.",
             "by": f"{start}-12-31",
             "resolves_when": "Competitor A, or a trade source that cites it, reports the first commercial "
                              "batches from Plant North.",
             "probability": 55},
            {"id": "P2", "message_id": "M2",
             "statement": "Competitor B will still describe its Country Z contract slots as fully booked at the "
                          "end of 2027.",
             "by": "2027-12-31",
             "resolves_when": "Competitor B's filing for 2027 states how many contract slots are booked.",
             "probability": 65},
        ],
        "calculations": [
            {"id": "C1", "label": "Lines for the builder's own use, in the moves confirmed here",
             "operation": "sum", "unit": "lines", "fact_ids": [a_n, a_s, ex, c_b], "of_fact_ids": [],
             "result": "6"},
            {"id": "C2", "label": "Lines open to outside customers, as a share of all lines confirmed here",
             "operation": "share", "unit": "lines", "fact_ids": [b_s], "of_fact_ids": [a_n, a_s, ex, b_s, c_b],
             "result": "33"},
        ],
    }
    if "c_open" in ids:   # the contradiction exists only when the trade report is part of the run
        analysis["contradictions"].append(
            {"text": "Drug maker B says Competitor C will use the plant only for its own products. One unnamed "
                     "source says Competitor C may open a line to outside customers. Both cannot hold unchanged.",
             "fact_ids": [c_b, ids["c_open"]]})
    return analysis


def run_id_for(changed: bool = False, private: bool = False, tampered: bool = False) -> str:
    """The id of the demo run for a variant."""
    return "demo" + ("-changed" if changed else "") + ("-private" if private else "") + \
        ("-tampered" if tampered else "")


def build_demo_run(root: Path, changed: bool = False, private: bool = False, tampered: bool = False,
                   stage: str = "complete") -> Path:
    """Create the illustrative run under `root` and return its folder.

    `changed=True` builds a second version of the run for a comparison: Competitor A's start of production
    moves, one fact is new and one is left out. `private=True` starts the run in private mode and adds one
    invented internal document and one confirmed fact resting on it. `tampered=True` (only with the stage
    `complete`) adds the id of a rejected fact to the first step of the first message, so that `build-report`
    refuses.

    `stage` says how far the run is built. `sources`: the run is started, the search is logged and the six sources
    are saved. `extracted`: also the proposed facts are added, none of them checked. `checked`: also the quotes are
    checked, the scripted support verdicts are recorded and the facts are settled; no checkpoint, no analysis.
    `complete`: everything, including both checkpoints and the analysis.

    The run is built in a temporary folder beside its place under `root` and moved there whole at the end, so a
    build that fails half-way leaves nothing behind, and the private variant is never seen without its mark.
    """
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {', '.join(STAGES)}")
    if tampered and stage != "complete":
        raise ValueError("the tampered demo is only built with the stage complete")
    root = Path(root)
    store.check_run_root(root)
    run_id = run_id_for(changed, private, tampered)
    target = root / run_id
    if target.exists():
        raise FileExistsError(f"the demo run folder already exists: {target}")
    root.mkdir(parents=True, exist_ok=True)
    building = Path(tempfile.mkdtemp(prefix=f".{run_id}-building-", dir=root))
    try:
        built = _build(building, run_id, changed, private, tampered, stage)
        if os.path.lexists(target):   # made by someone else while this one was built
            raise FileExistsError(f"the demo run folder already exists: {target}")
        os.rename(built, target)
    finally:
        shutil.rmtree(building, ignore_errors=True)
    return target


def _build(root: Path, run_id: str, changed: bool, private: bool, tampered: bool, stage: str) -> Path:
    """`build_demo_run` in the folder `root` (the temporary one); returns the run folder made there."""
    start = MOVED_START_YEAR if changed else START_YEAR
    init = ["init-run", "--root", root, "--question", QUESTION, "--pack", "demo", "--run-id", run_id,
            "--illustrative", "--home-company", "Example Pharma"]
    if private:
        init += ["--mode", "private", "--acknowledge-data-flow", "--acknowledged-words", PRIVATE_DEMO_WORDS]
    run = Path(_radar(*init)["run_dir"])

    _radar("log-search", "--run", run, "--place", "Company websites of Competitor A, Competitor B, Competitor C "
           "and Example Pharma", "--result", "Found two releases and one filing")
    _radar("log-search", "--run", run, "--place", "Drug maker B's annual report",
           "--result", "Found the sale of a filling plant, in German")
    _radar("log-search", "--run", run, "--place", "Aseptic Trade Journal and Biologics Business Daily",
           "--result", "Found two articles, one of them resting on an unnamed source")
    _radar("log-excluded", "--run", run, "--what", "A paid market forecast for filling capacity",
           "--why", "It is behind a paywall. A public run uses only sources anyone can read.")

    with tempfile.TemporaryDirectory() as scratch:
        scratch = Path(scratch)
        source_ids: dict[str, str] = {}
        specs = list(_SOURCE_LIST) + ([_INTERNAL_SOURCE] if private else [])
        for spec in specs:
            text = (SOURCES / spec["file"]).read_text(encoding="utf-8")
            if start != START_YEAR:   # the company's own release and the article that repeats it both move
                text = text.replace(START_YEAR, start)
            copy = scratch / Path(spec["file"]).name
            copy.write_text(text, encoding="utf-8")
            argv = ["add-copy", "--run", run, "--file", copy, "--url", spec["url"],
                    "--publisher", spec["publisher"], "--title", spec["title"], "--date", spec["date"],
                    "--type", spec["type"], "--speaker", spec["speaker"], "--interest", spec["interest"],
                    "--language", spec["language"]]
            if spec.get("based_on"):
                argv += ["--based-on", source_ids[spec["based_on"]]]
            if spec is _INTERNAL_SOURCE:
                argv += ["--data-class", "internal",
                         "--supplied-by", "Example Pharma manufacturing planning (invented)",
                         "--basis", "The user's own company document, supplied by its owner for this analysis"]
            else:   # every file states its class: add-copy has no default
                argv += ["--data-class", "public"]
            source_ids[spec["name"]] = _radar(*argv)["id"]
        if private:   # its notice was scripted, never shown; from here on the run takes no more non-public material
            store.mark_demo_run(run)
        if stage == "sources":
            return run

        proposals = _proposals(source_ids, start)
        names = ["a_north", "a_south", "example_own", "b_site", "b_demand", "c_buy", "c_open",
                 "planted_number", "planted_year", "planted_negation"]
        if changed:
            names.remove("c_open")    # left out of the second run
            names.append("d_new")     # new in the second run
        if private:
            names.append("internal_note")
        ids: dict[str, str] = {}
        for name in names:
            proposal_file = scratch / f"proposal-{name}.json"
            proposal_file.write_text(json.dumps(proposals[name], ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8")
            ids[name] = _radar("add-fact", "--run", run, "--file", proposal_file)["fact_id"]
    if stage == "extracted":
        return run

    _radar("check-quotes", "--run", run)
    # The support verdict is bound to each fact's content, so it is recorded only now that the facts are final.
    # Only the facts the checker would be asked about get one: a fact whose quote is not found is settled by the
    # program alone.
    names_by_id = {fact_id: name for name, fact_id in ids.items()}
    for packet in _radar("quote-context", "--run", run, "--open")["packets"]:
        name = names_by_id[packet["fact_id"]]
        _radar("record-support", "--run", run, "--fact", packet["fact_id"],
               "--passed", "false" if name in _NOT_SUPPORTED else "true",
               "--by", "demo support check (illustrative)",
               "--note", _SUPPORT_NOTES.get(name, "The quote states what the fact says."))
    _radar("settle", "--run", run)
    if stage == "checked":
        return run

    _radar("checkpoint", "--run", run, "--name", "lenses", "--answered-by", "test",
           "--answer", "Recorded test answer: use the lenses firm-boundaries and capacity-commitment.")
    _radar("checkpoint", "--run", run, "--name", "final_report", "--answered-by", "test",
           "--answer", "Recorded test answer: build the report.")
    analysis = _analysis(ids, start)
    store.write_analysis(run, analysis)
    _radar("check-data", "--run", run, "--lenses", LENSES)   # the demo itself must be a clean run
    if tampered:
        facts = store.read_facts(run)
        rejected = next(fact_id for fact_id in ids.values() if facts[fact_id]["status"] == "rejected")
        analysis["messages"][0]["chain"][0]["fact_ids"].append(rejected)
        store.write_analysis(run, analysis)
    return run
