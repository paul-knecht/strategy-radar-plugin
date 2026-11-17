import json
import re
from decimal import Decimal
from pathlib import Path

from radar import store
from radar.cli import main
from radar.report.build import build_report
from radar.report.html import esc, render_html
from radar.report.markdown import render_markdown
from radar.report.model import build_model, load_labels
from helpers import add_fact, add_source, find, finish_run, lens_folder_with_level, make_run, minimal_analysis, proposal
from test_report_build import LENSES, ready_run

REPORT_DIR = Path(__file__).parent.parent / "engine" / "radar" / "report"


def html_for(run):
    return render_html(build_model(run, LENSES))


def private_run_with_uncertain_fact(tmp_path, extra=None):
    """F1 is confirmed and public; F2 comes from an internal source with no second source, so it is uncertain."""
    run = make_run(tmp_path, mode="private", acknowledged=True, home_company="Own plant")
    add_source(run, "The expansion adds two high-speed syringe lines for customers, starting in 2028.")
    add_source(run, "Internal review: the line will run two shifts from 2027, says the plant manager.",
               data_class="internal", url="internal capacity review", publisher="Own plant")
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    add_fact(run, source_id="S2", primary_source=False, quote="the line will run two shifts from 2027",
             statement="The line runs two shifts.", fields={"company": "Own plant", "planned_start": "2027"})
    analysis = minimal_analysis(["F1", "F2"], "firm-boundaries")
    analysis.update(extra or {})
    finish_run(run, [], analysis=analysis)
    return run


def empty_model():
    labels = load_labels()
    return {"question": "Q", "run_id": "r", "pack": "p", "illustrative": False, "sources_read_until": "2026-11-12",
            "home_company": None, "mode": "public", "confidential": False,
            "status_line": {"confirmed": 0, "uncertain": 0, "single_source": 0, "rejected": 0, "sources": 0,
                            "not_accessible": 0},
            "messages": [], "facts": [], "rejected": [], "competitors": [], "demand_signals": [],
            "companies": [], "projects": {"state": "none", "items": []}, "core_answer": None, "connections": [],
            "connections_old": False, "decision_options": None, "watch_items": [], "audit_flags": [], "not_found": [], "contradictions": [],
            "lenses": [], "sources": [], "how_made": {"search_log": [], "excluded": [], "checkpoints": [],
                                                "names_dropped": {"companies": 0, "parties": 0}},
            "changes": None, "assumptions": [], "scenarios": [], "predictions": [], "calculations": [],
            "compliance": labels["compliance_public"], "built_on": "2026-11-12"}


# --- the structure the brief fixes ---

def test_views_and_tabs_match(tmp_path):
    doc = html_for(ready_run(tmp_path))
    views = [e["id"] for e in find(doc, "section", **{"class": "view"})]
    tabs = [e["data-view"] for e in find(doc, "button") if "data-view" in e]
    assert views == ["view-" + t for t in tabs]
    assert tabs[:3] == ["facts", "projects", "connections"] and "changes" not in tabs

def test_all_views_in_order_and_the_first_is_on(tmp_path):
    doc = html_for(ready_run(tmp_path))
    tabs = [e["data-view"] for e in find(doc, "button") if "data-view" in e]
    assert tabs == ["facts", "projects", "connections", "timeline", "scenarios", "options", "checks",
                    "thinking", "sources", "how"]
    assert [e["id"] for e in find(doc, "section", **{"class": "view on"})] == ["view-facts"]
    assert [b["data-view"] for b in find(doc, "button", **{"class": "on"})] == ["facts"]

def test_changes_view_appears_when_changes_exist(tmp_path):
    run = ready_run(tmp_path)
    store.write_changes(run, {"previous_run": "run0", "current_run": "run1", "new": [{"fact_id": "F1"}],
                              "changed": [], "unchanged": 3})
    doc = html_for(run)
    tabs = [e["data-view"] for e in find(doc, "button") if "data-view" in e]
    assert tabs[-1] == "changes"
    view = find(doc, "section", id="view-changes")[0]
    assert "What changed since last time" in view["text"] and "F1" in view["text"] and "run0" in view["text"]

def test_message_chain_links_down_to_fact_and_lens(tmp_path):
    doc = html_for(ready_run(tmp_path))
    assert any(a.get("href") == "#F1" and a.get("data-view") == "facts" for a in find(doc, "a"))
    assert any(a.get("href") == "#lens-firm-boundaries" and a.get("data-view") == "thinking" for a in find(doc, "a"))
    assert [d["id"] for d in find(doc, "details", **{"class": "message"})] == ["M1"]

def test_message_has_summary_chain_and_the_three_blocks(tmp_path):
    doc = html_for(ready_run(tmp_path))
    message = find(doc, "details", **{"class": "message"})[0]
    summary = find(doc, "summary")[0]["text"]
    assert "Competitor A is adding capacity." in summary and "Medium confidence" in summary
    assert len(find(doc, "ol", **{"class": "chain"})) == 1
    for kind in ("fact", "reasoning", "conclusion"):
        assert len(find(doc, "li", **{"class": f"step {kind}"})) == 1
    for block in ("counter-view", "would-change", "outside-view"):
        assert len(find(doc, "div", **{"class": block})) == 1
    for part in ("The line may be delayed.", "A cancellation notice.", "Expansions often slip.",
                 "Counter-view", "What would change this", "Outside view"):
        assert part in message["text"], part

def test_fact_shows_quote_and_links_to_source(tmp_path):
    doc = html_for(ready_run(tmp_path))
    quotes = [q["text"] for q in find(doc, "blockquote")]
    assert "adds two high-speed syringe lines for customers" in quotes
    assert any(a.get("href") == "#S1" and a.get("data-view") == "sources" for a in find(doc, "a"))
    assert [f["id"] for f in find(doc, "details", **{"class": "fact"})] == ["F1"]   # rejected F2 is not a fact

def test_fact_carries_status_and_access_pills(tmp_path):
    doc = html_for(ready_run(tmp_path))
    assert [p["text"] for p in find(doc, "span", **{"class": "pill status-confirmed"})] == ["Confirmed"]
    assert [p["text"] for p in find(doc, "span", **{"class": "pill access-open"})] == ["Open to other customers"]

def test_rejected_fact_appears_only_in_checks_with_quote_and_reason(tmp_path):
    doc = html_for(ready_run(tmp_path))
    checks = find(doc, "section", id="view-checks")[0]["text"]
    assert "What we could not confirm" in checks and "adds nine high-speed syringe lines for customers" in checks
    assert "The quote was not found in the saved source." in checks and "not_found" not in checks
    assert "adds nine" not in find(doc, "section", id="view-facts")[0]["text"]
    assert "adds nine" not in find(doc, "section", id="view-sources")[0]["text"]
    assert [f["id"] for f in find(doc, "details", **{"class": "fact"})] == ["F1"]

def test_source_page_lists_its_quotes(tmp_path):
    doc = html_for(ready_run(tmp_path))
    source = find(doc, "article", **{"class": "source"})[0]
    assert source["id"] == "S1" and "adds two high-speed syringe lines for customers" in source["text"]
    assert "wants to look strong" in source["text"]            # the interest of the speaker
    for part in ("Competitor A", "Company release", "the company", "2026-11-12", "F1"):
        assert part in source["text"], part
    link = [a for a in find(doc, "a") if a.get("href") == "https://s1.example.com/S1"][0]
    assert link["rel"] == "noopener noreferrer"

def test_thinking_view_has_a_card_per_lens_with_its_parts(tmp_path):
    analysis = minimal_analysis(["F1"], "firm-boundaries")
    analysis["lens_notes"] = [{"lens_id": "firm-boundaries", "here": "Here the firm builds its own lines."}]
    doc = html_for(ready_run(tmp_path, analysis=analysis))
    card = find(doc, "article", **{"class": "lens-card"})[0]
    assert card["id"] == "lens-firm-boundaries"
    for part in ("Where firms draw their boundaries", "The idea", "What it suggests here", "Where it falls short",
                 "A competing idea", "Questions to ask", "Has the company recently moved a step across that line?",
                 "Here the firm builds its own lines.", "Illustrative reference, not a real work",
                 "Reference confirmed"):
        assert part in card["text"], part

def test_the_lens_card_shows_the_course_slides_level_as_a_pill(tmp_path):
    lenses = lens_folder_with_level(tmp_path / "lenses", "course_slides")
    run = ready_run(tmp_path)
    doc = render_html(build_model(run, lenses))
    card = find(doc, "article", **{"class": "lens-card"})[0]
    assert "Course slides" in card["text"]
    assert [p["text"] for p in find(doc, "span", **{"class": "pill level-course_slides"})] == ["Course slides"]

def test_scenarios_view_has_judgement_assumptions_scenarios_and_predictions(tmp_path):
    analysis = minimal_analysis(["F1"], "firm-boundaries")
    analysis["assumptions"] = [
        {"id": "A1", "text": "Demand keeps growing", "support": "partial", "if_wrong": "Open capacity stays unused", "fact_ids": []},
        {"id": "A2", "text": "Announced plants open on time", "support": "weak", "if_wrong": "The shortage lasts longer", "fact_ids": ["F1"]}]
    analysis["scenarios"] = [
        {"id": "SC1", "name": "Tight market", "description": "Demand outruns supply", "assumption_ids": ["A1", "A2"],
         "signposts": [{"text": "Lead times rise", "fact_ids": ["F1"]}]}]
    analysis["predictions"] = [{"id": "P1", "message_id": "M1", "statement": "Competitor A starts both lines",
                                "by": "2028-12-31", "resolves_when": "The company reports the lines as operating",
                                "probability": 65}]
    doc = html_for(ready_run(tmp_path, analysis=analysis))
    assert [p["text"] for p in find(doc, "p", **{"class": "judgement"})] == ["Judgement, not fact"]
    assumptions = {a["id"]: a["text"] for a in find(doc, "li", **{"class": "assumption"})}
    assert set(assumptions) == {"A1", "A2"}
    assert "Partly supported" in assumptions["A1"] and "Open capacity stays unused" in assumptions["A1"]
    assert "Weakly supported" in assumptions["A2"] and "The shortage lasts longer" in assumptions["A2"]
    scenario = find(doc, "article", **{"class": "scenario"})[0]
    assert scenario["id"] == "SC1" and "Demand outruns supply" in scenario["text"]
    assert [s["text"].split(" F1")[0] for s in find(doc, "li", **{"class": "signpost"})] == ["Lead times rise"]
    hrefs = {a["href"] for a in find(doc, "a") if a.get("data-view") == "scenarios"}
    assert {"#A1", "#A2"} <= hrefs
    assert [(p["id"], p["text"]) for p in find(doc, "li", **{"class": "prediction"})] == \
        [("prediction-P1", "Competitor A starts both lines, by 2028-12-31: 65% (likely)")]   # not "P1": a project's id
    assert "The company reports the lines as operating" in find(doc, "section", id="view-scenarios")[0]["text"]

def test_projects_put_the_home_company_first_and_label_it(tmp_path):
    run = make_run(tmp_path, home_company="Own Plant")
    add_source(run, "The expansion adds two high-speed syringe lines for customers, starting in 2028.")
    add_source(run, "Own Plant will add a third filling line at Plant South in 2027, the company said.")
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    add_fact(run, source_id="S2", primary_source=True, quote="will add a third filling line at Plant South in 2027",
             fields={"company": "Own Plant", "site": "Plant South", "planned_start": "2027", "access": "captive"})
    finish_run(run, ["F1"])
    doc = html_for(run)
    view = view_html(doc, "projects")
    headings = [h["text"] for h in find(view, "h3") if h.get("data-company")]
    assert headings == ["Own Plant own company", "Other companies"]       # the home company is first and labelled
    cards = find(view, "details", **{"class": "project"})
    assert len(cards) == 2 and cards[0]["id"] == "project-F2" and cards[1]["id"] == "project-F1"
    assert "Plant South" in cards[0]["text"] and "For own use" in cards[0]["text"] and "2027" in cards[0]["text"]
    assert "Competitor A" in cards[1]["text"] and "own company" not in cards[1]["text"]
    assert "Announced" in cards[1]["text"] and "Exampleland" in cards[1]["text"] and "F1" in cards[1]["text"]

def test_timeline_orders_moves_by_planned_start(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "One adds a line in 2029. Two adds a line in 2027. Three gives no date at all.")
    for quote, company, start in (("adds a line in 2029", "Late Co", "2029"), ("adds a line in 2027", "Early Co", "2027"),
                                  ("gives no date at all", "Undated Co", None)):
        add_fact(run, source_id="S1", primary_source=True, quote=quote,
                 fields={"company": company, "planned_start": start})
    finish_run(run, ["F1"])
    doc = html_for(run)
    section = doc[doc.index('id="view-timeline"'):doc.index('id="view-scenarios"')]
    assert [th["text"] for th in find(section, "th", scope="col")] == ["2027", "2028", "2029"]
    assert [th["text"] for th in find(section, "th", scope="row")] == ["Early", "Late"]  # one row per dated company,
    # by its tidy name ("Early Co" without its legal ending)
    assert [(a["href"], a["class"]) for a in find(section, "a", **{"class": "bar"})] == \
        [("#F2", "bar open"), ("#F1", "bar open")]                                      # in the column of their year
    assert "Start not stated" in section and "Undated" in find(section, "ul", **{"class": "undated"})[0]["text"]

def test_demand_signals_totals_and_options_are_shown(tmp_path):
    analysis = minimal_analysis(["F1"], "firm-boundaries")
    analysis["demand_signals"] = [{"text": "Orders for syringes are rising", "fact_ids": ["F1"]}]
    analysis["calculations"] = [{"id": "C1", "label": "Moves announced", "operation": "count", "unit": None,
                                 "fact_ids": ["F1"], "of_fact_ids": [], "result": "1"}]
    analysis["decision_options"] = {"question": "Should we add a line?", "framing": "company", "framing_fact_ids": ["F1"],
                                    "options": [{"name": "Add a line", "for": [{"text": "Demand is up", "fact_ids": ["F1"]}],
                                                 "against": [{"text": "Rivals add capacity", "fact_ids": []}]}],
                                    "internal_questions": ["What is our spare capacity?"]}
    analysis["watch_items"] = [{"text": "Plant North permits", "trigger": "A permit is refused"}]
    doc = html_for(ready_run(tmp_path, analysis=analysis))
    projects = find(doc, "section", id="view-projects")[0]["text"]
    assert "Orders for syringes are rising" in projects and "Moves announced: 1" in projects
    options = find(doc, "section", id="view-options")[0]["text"]
    for part in ("Should we add a line?", "Add a line", "Demand is up", "Rivals add capacity",
                 "What is our spare capacity?", "Plant North permits", "A permit is refused",
                 "Questions only the company can answer", "What to watch"):
        assert part in options, part

def test_checks_view_lists_flags_and_what_was_not_found(tmp_path):
    analysis = minimal_analysis(["F1"], "firm-boundaries")
    analysis["audit_flags"] = [{"check": "outside_view", "text": "The outside view is thin."}]
    analysis["not_found"] = ["No filing for Plant East was found."]
    analysis["contradictions"] = [{"text": "Two start dates are given.", "fact_ids": ["F1"]}]
    checks = find(html_for(ready_run(tmp_path, analysis=analysis)), "section", id="view-checks")[0]["text"]
    assert "outside_view" not in checks
    for part in ("Checks on this analysis", "Outside view", "The outside view is thin.",
                 "No filing for Plant East was found.", "Two start dates are given."):
        assert part in checks, part

def test_how_view_ends_with_compliance_and_legend(tmp_path):
    doc = html_for(ready_run(tmp_path))
    how = find(doc, "section", id="view-how")[0]["text"]
    assert "Recorded test answer" in how and "How to read the confidence words" in how
    assert "very likely" in how and "Medium confidence: the evidence points one way but has gaps." in how
    assert how.index("All sources in this report are publicly available.") < how.index("How to read the confidence words")
    view = doc.split('id="view-how"')[1]
    assert view.index('class="compliance"') < view.index('class="legend"')

def test_a_model_without_a_recommendation_part_says_no_recommendation_was_made():
    doc = render_html(empty_model())
    how = find(doc, "section", id="view-how")[0]["text"]
    assert ("No recommendation was made: the advisor did not run, or its list was refused twice by the program's "
            "form check.") in how


def test_a_model_with_nothing_in_it_still_renders():
    doc = render_html(empty_model())
    assert "No fact could be confirmed from the sources that were read." in find(doc, "section", id="messages")[0]["text"]
    assert "No fact could be confirmed from the sources that were read." in find(doc, "section", id="view-facts")[0]["text"]
    assert len(find(doc, "section", **{"class": "view"})) == 10 and find(doc, "section", id="answer") == []

def test_run_with_no_usable_facts_renders(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "The expansion adds two high-speed syringe lines for customers, starting in 2028.")
    add_fact(run, source_id="S1", primary_source=True, quote="adds nine high-speed syringe lines for customers")
    empty = minimal_analysis([])
    empty["messages"] = []
    finish_run(run, [], analysis=empty)
    doc = html_for(run)
    assert find(doc, "details", **{"class": "fact"}) == []
    assert "No fact could be confirmed from the sources that were read." in doc


# --- escaping: source text is data, never markup ---

def test_markup_in_source_text_is_escaped(tmp_path):
    run = make_run(tmp_path)
    add_source(run, 'He said "<script>alert(1)</script> two new lines open in 2028" today.',
               publisher='Evil <b>Corp</b>', title='A "quoted" <img src=x onerror=alert(1)> title')
    add_fact(run, source_id="S1", primary_source=True,
             quote='<script>alert(1)</script> two new lines open in 2028')
    finish_run(run, ["F1"])
    doc = html_for(run)
    assert "<script>alert(1)</script>" not in doc and "<img src=x" not in doc and "<b>Corp</b>" not in doc
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in doc

def test_markup_cannot_reach_attributes_or_add_elements(tmp_path):
    run = make_run(tmp_path)
    nasty = '"><svg onload=alert(1)>'
    add_source(run, "The expansion adds two high-speed syringe lines for customers, starting in 2028.",
               url='https://example.com/x"onmouseover="alert(1)', publisher=nasty, speaker=nasty, interest=nasty,
               title=nasty)
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers",
             statement=nasty, fields={"company": nasty, "site": nasty})
    analysis = minimal_analysis(["F1"])
    analysis["messages"][0]["text"] = nasty
    analysis["messages"][0]["counter_view"] = nasty
    finish_run(run, [], analysis=analysis)
    doc = html_for(run)
    assert "<svg" not in doc and find(doc, "svg") == []
    handlers = [name for tag in ("a", "div", "span", "details", "article", "section", "li", "td", "tr", "blockquote")
                for element in find(doc, tag) for name in element if name.lower().startswith("on")]
    assert handlers == []
    link = [a for a in find(doc, "a") if a.get("href", "").startswith("https://example.com/x")][0]
    assert link["href"] == 'https://example.com/x"onmouseover="alert(1)' and "onmouseover" not in link

def test_only_http_and_https_addresses_become_links(tmp_path):
    run = ready_run(tmp_path)
    for url in ("javascript:alert(1)", "data:text/html,<b>x</b>", "ftp://example.com/x", "https://"):
        source = store.read_sources(run)["S1"]
        source["url"] = url
        store.write_source(run, source)
        doc = html_for(run)
        assert [a["href"] for a in find(doc, "a") if not a.get("href", "#").startswith("#")] == [], url
        assert esc(url) in doc
    source = store.read_sources(run)["S1"]
    source["url"] = "HTTPS://example.com/ok"
    store.write_source(run, source)
    assert [a["href"] for a in find(html_for(run), "a") if not a.get("href", "#").startswith("#")] == \
        ["HTTPS://example.com/ok"]

def test_esc_escapes_quotes_and_angle_brackets_and_none():
    assert esc('<a href="x">\'&') == "&lt;a href=&quot;x&quot;&gt;&#x27;&amp;"
    assert esc(None) == "" and esc(65) == "65"

def test_the_page_has_one_static_script_and_one_static_style(tmp_path):
    doc = html_for(ready_run(tmp_path))
    script = re.search(r"<script>(.*?)</script>", doc, re.S).group(1)
    style = re.search(r"<style>(.*?)</style>", doc, re.S).group(1)
    assert script.strip() == (REPORT_DIR / "report.js").read_text(encoding="utf-8").strip()
    assert style.strip() == (REPORT_DIR / "report.css").read_text(encoding="utf-8").strip()
    assert doc.count("<style") == 1

def test_script_and_style_carry_no_model_text(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "The expansion adds two high-speed syringe lines for customers, starting in 2028.",
               publisher="ZZZ-marker-publisher")
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    finish_run(run, ["F1"])
    doc = html_for(run)
    code = "".join(re.findall(r"<(?:script|style)>.*?</(?:script|style)>", doc, re.S))
    assert "ZZZ-marker-publisher" not in code and "ZZZ-marker-publisher" in doc

def test_german_quote_is_kept_and_translation_is_labelled(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "Die Erweiterung umfasst zwei neue Abfüllanlagen bis 2028, teilte das Unternehmen mit.", language="de")
    add_fact(run, source_id="S1", primary_source=True, quote_language="de",
             quote="Die Erweiterung umfasst zwei neue Abfüllanlagen bis 2028",
             quote_translation="The expansion comprises two new filling lines by 2028")
    finish_run(run, ["F1"])
    doc = html_for(run)
    assert any(q.get("lang") == "de" and "Abfüllanlagen" in q["text"] for q in find(doc, "blockquote"))
    assert any("Translation" in p["text"] and "two new filling lines" in p["text"]
               for p in find(doc, "p", **{"class": "translation"}))


# --- confidential and uncertain material is recognisable wherever it is shown ---

def test_confidential_banner_and_class_pills(tmp_path):
    run = make_run(tmp_path, mode="private", acknowledged=True)
    add_source(run, "Internal review: the board approved two additional syringe lines for 2029.",
               data_class="internal", url="internal capacity review")
    add_fact(run, source_id="S1", primary_source=True, quote="the board approved two additional syringe lines for 2029")
    finish_run(run, ["F1"])
    doc = html_for(run)
    assert [b["text"] for b in find(doc, "div", **{"class": "banner confidential"})] == \
        ["Confidential. This report contains non-public information. Do not share or publish it."]
    assert any(p["text"] == "Internal document" for p in find(doc, "span", **{"class": "pill class-internal"}))
    assert "internal capacity review" in doc and 'href="internal capacity review"' not in doc
    body = doc.split("<body>")[1]
    assert body.lstrip().startswith('<div class="banner confidential">')
    assert body.index('class="banner confidential"') < body.index('<nav class="tabs"')

def test_public_run_has_no_confidential_banner(tmp_path):
    assert find(html_for(ready_run(tmp_path)), "div", **{"class": "banner confidential"}) == []

def test_illustrative_run_carries_the_banner(tmp_path):
    doc = html_for(ready_run(tmp_path, illustrative=True))
    assert [b["text"] for b in find(doc, "div", **{"class": "banner illustrative"})] == \
        [BANNER]

def test_a_link_to_an_uncertain_fact_carries_the_uncertain_label(tmp_path):
    run = private_run_with_uncertain_fact(
        tmp_path, {"demand_signals": [{"text": "Shifts are being added", "fact_ids": ["F2"]}]})
    doc = html_for(run)
    refs = find(doc, "span", **{"class": "factref"})
    f2 = [r["text"] for r in refs if r["text"].startswith("F2")]
    assert len(f2) >= 3                                                   # chain step, demand signal, table, ...
    assert set(f2) == {"F2One source onlyInternal document"}                    # link text, then the two pills
    f1 = [r["text"] for r in refs if r["text"].startswith("F1")]
    assert f1 and set(f1) == {"F1"}                                       # public and confirmed: nothing added
    fact = [f for f in find(doc, "details", **{"class": "fact"}) if f["id"] == "F2"][0]
    assert "One source only" in fact["text"] and "Internal document" in fact["text"]

def test_source_page_of_a_non_public_source_names_who_supplied_it(tmp_path):
    run = private_run_with_uncertain_fact(tmp_path)
    source = [s for s in find(html_for(run), "article", **{"class": "source"}) if s["id"] == "S2"][0]
    for part in ("Internal document", "Supplied by", "the tester", "Basis for use", "own company document",
                 "internal capacity review", "F2"):
        assert part in source["text"], part

def test_stage_pill_based_on_link_and_compliance_line(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "The expansion adds two high-speed syringe lines for customers, starting in 2028.")
    add_source(run, "Competitor A confirmed two new syringe lines will open in 2028, the paper reported.",
               publisher="Trade Paper", based_on=["S1"])
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers",
             fields={"stage": "under_construction"})
    finish_run(run, ["F1"])
    doc = html_for(run)
    assert [p["text"] for p in find(doc, "span", **{"class": "pill stage-under_construction"})] == ["Under construction"]
    s2 = [a for a in find(doc, "article", **{"class": "source"}) if a["id"] == "S2"][0]
    assert "Based on" in s2["text"] and "S1" in s2["text"]
    assert any(a.get("href") == "#S1" and a.get("data-view") == "sources" for a in find(doc, "a"))
    assert [p["text"] for p in find(doc, "p", **{"class": "compliance"})] == ["All sources in this report are publicly available."]


# --- the page itself ---

def test_report_is_self_contained(tmp_path):
    doc = html_for(ready_run(tmp_path))
    assert "<link" not in doc and "src=\"http" not in doc and "@import" not in doc
    assert doc.count("<script") == 1

def test_the_only_external_address_is_the_source_link(tmp_path):
    doc = html_for(ready_run(tmp_path))
    assert set(re.findall(r"https?://[^\s\"'<>]+", doc)) == {"https://s1.example.com/S1"}
    assert "url(" not in doc

def test_works_without_javascript_in_light_and_dark_at_phone_width(tmp_path):
    doc = html_for(ready_run(tmp_path))
    css = (REPORT_DIR / "report.css").read_text(encoding="utf-8")
    js = (REPORT_DIR / "report.js").read_text(encoding="utf-8")
    hiding = [selector.strip() for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
              if "display:none" in body.replace(" ", "") and ".view" in selector]
    assert hiding and all(selector.startswith("html.js ") for selector in hiding)   # views hide only under html.js
    assert "prefers-color-scheme: dark" in css and "max-width" in css
    assert 'name="viewport"' in doc and 'name="color-scheme"' in doc
    assert 'classList.add("js")' in js and "data-view" in js and "scrollIntoView" in js
    assert "js" not in doc.split("<body>")[0].split("<html")[1].split(">")[0]         # the class is added by script only

def test_build_writes_html_next_to_markdown(tmp_path):
    run = ready_run(tmp_path)
    assert [p.name for p in build_report(run, LENSES)] == ["report.md", "report.html", "facts.csv", "sources.csv"]
    assert (run / "report" / "report.html").read_text(encoding="utf-8").startswith("<!DOCTYPE html>")

def test_build_report_command_lists_both_files(tmp_path, capsys):
    run = ready_run(tmp_path)
    assert main(["build-report", "--run", str(run), "--lenses", str(LENSES)]) == 0
    assert json.loads(capsys.readouterr().out) == {"built": ["report/report.md", "report/report.html", "report/facts.csv", "report/sources.csv"]}

def test_rendering_writes_nothing(tmp_path):
    run = ready_run(tmp_path)
    before = sorted(p.relative_to(run).as_posix() for p in run.rglob("*"))
    html_for(run)
    assert sorted(p.relative_to(run).as_posix() for p in run.rglob("*")) == before


# --- the same small fix in the plain-text report ---

def test_markdown_competitor_lines_name_uncertain_and_non_public_facts(tmp_path):
    md = render_markdown(build_model(private_run_with_uncertain_fact(tmp_path), LENSES))
    comp = md.split("## Projects")[1].split("\n## ")[0]
    line = next(l for l in comp.splitlines() if "The line runs two shifts." in l)
    assert "F2 (One source only, Internal document)" in line
    public = next(l for l in comp.splitlines() if "Competitor A will add" in l)
    assert "Uncertain" not in public and "Internal" not in public

def test_markdown_chain_step_references_name_uncertain_and_non_public_facts(tmp_path):
    md = render_markdown(build_model(private_run_with_uncertain_fact(tmp_path), LENSES))
    chain = md.split("## Thinking behind this analysis")[1].split("\n## ")[0]
    step = next(l for l in chain.splitlines() if l.startswith("1. Fact:"))
    assert "F1," in step and "F2 (One source only, Internal document)" in step and "F1 (" not in step
    summary = md.split("## Key messages")[1].split("\n## ")[0]
    assert "F2 (One source only, Internal document)" in summary and "F1 (" not in summary


# --- fix round 1: quotes on source pages name their fact ---

def _article(doc, source_id):
    return doc.split(f'<article class="source" id="{source_id}"')[1].split("</article>")[0]

def test_source_page_links_each_quote_to_its_fact(tmp_path):
    article = _article(html_for(ready_run(tmp_path)), "S1")
    assert '<a href="#F1" data-view="facts">F1</a>' in article
    assert [p["text"] for p in find(article, "p", **{"class": "quote-fact"})] == ["Fact F1"]

def test_source_page_quote_of_an_uncertain_non_public_fact_carries_both_labels(tmp_path):
    article = _article(html_for(private_run_with_uncertain_fact(tmp_path)), "S2")
    assert '<a href="#F2" data-view="facts">F2</a>' in article
    assert [r["text"] for r in find(article, "span", **{"class": "factref"})] == ["F2One source onlyInternal document"]

def test_source_page_quote_of_a_rejected_fact_is_text_with_the_rejected_label(tmp_path):
    model = build_model(ready_run(tmp_path), LENSES)
    model["sources"][0]["quotes"].append({"fact_id": "F2", "quote": "adds nine high-speed syringe lines for customers",
                                          "translation": None})
    article = _article(render_html(model), "S1")
    assert 'href="#F2"' not in article
    assert "F2Rejected" in [r["text"] for r in find(article, "span", **{"class": "factref"})]


def test_changes_tab_appears_only_with_changes(tmp_path):
    run = ready_run(tmp_path)
    assert find(html_for(run), "section", id="view-changes") == []
    store.write_changes(run, {"previous_run": "run0", "current_run": "run1", "new": [{"fact_id": "F1"}],
                              "unchanged": 3})
    doc = html_for(run)
    tabs = [e["data-view"] for e in find(doc, "button") if "data-view" in e]
    assert tabs[-1] == "changes" and tabs.count("changes") == 1
    assert len(find(doc, "section", id="view-changes")) == 1


def test_a_changes_file_that_is_not_an_object_adds_no_tab(tmp_path):
    run = ready_run(tmp_path)
    (run / "changes.json").write_text("[]", encoding="utf-8")
    doc = html_for(run)
    assert "changes" not in [e["data-view"] for e in find(doc, "button") if "data-view" in e]
    assert find(doc, "section", id="view-changes") == []


# --- early signals and baselines in the interactive report ------------------------------------------

from test_report_build import early_signal_run

EARLY_NOTE = ("Early signals are hints such as building permits, job postings and regulator records. "
              "They are not announcements, and each one is marked uncertain.")
BASELINE_HEADING = "Baseline: size, sites and investment"


def test_the_early_signals_block_carries_its_fixed_note(tmp_path):
    doc = html_for(early_signal_run(tmp_path))
    blocks = find(doc, "div", **{"class": "early-signals"})
    assert len(blocks) == 1
    text = blocks[0]["text"]
    assert text.startswith("Early signals") and EARLY_NOTE in text
    assert "A planning application names a new filling hall at Plant North." in text
    assert "Uncertain" in text and "an application for a new filling hall at Plant North" in text
    view = find(doc, "section", id="view-facts")[0]["text"]
    assert "Early signals" in view and "Planning application" in view       # the block sits inside "What the sources say"
    assert view.index("adds two high-speed syringe lines for customers") < view.index("Early signals")
    # the signal is listed once, in its own block, and not among the other facts
    assert doc.count('id="F3"') == 1 and doc.count("A planning application names a new filling hall") == 1


def test_an_early_signal_is_still_found_by_every_link_to_it(tmp_path):
    doc = html_for(early_signal_run(tmp_path))
    source_page = find(doc, "article", id="S2")[0]["text"]
    assert "F3" in source_page and "an application for a new filling hall at Plant North" in source_page
    refs = find(doc, "a", href="#F3")
    assert refs and all(ref["data-view"] == "facts" for ref in refs)


def test_an_early_signal_from_a_non_public_source_keeps_its_class_mark(tmp_path):
    run = ready_run(tmp_path, mode="private", acknowledged=True)
    add_source(run, "The planning office received an application for a new filling hall at Plant North, "
                    "with a decision due in 2027.", type="permit", data_class="internal", url="internal permit register")
    from helpers import add_early_signal
    add_early_signal(run, source_id="S2")
    from radar import verify
    verify.check_quotes(run); verify.record_support(run, "F3", True, "support-checker", ""); verify.settle(run)
    text = find(html_for(run), "div", **{"class": "early-signals"})[0]["text"]
    assert "Internal document" in text and "Uncertain" in text


def test_a_run_with_only_early_signals_does_not_say_that_no_fact_was_confirmed(tmp_path):
    from helpers import PERMIT_TEXT, add_early_signal
    run = make_run(tmp_path)
    add_source(run, PERMIT_TEXT, type="permit")
    add_early_signal(run)
    empty = minimal_analysis(fact_ids=[]); empty["messages"] = []
    finish_run(run, [], analysis=empty)
    view = find(html_for(run), "section", id="view-facts")[0]["text"]
    assert "Early signals" in view and "No fact could be confirmed" not in view


def test_the_baseline_is_shown_under_its_company(tmp_path):
    doc = html_for(early_signal_run(tmp_path))
    view = find(doc, "section", id="view-projects")[0]
    blocks = find(doc, "div", **{"class": "baseline"})
    assert len(blocks) == 2
    first, second = blocks[0]["text"], blocks[1]["text"]
    assert first.startswith("Competitor A") and BASELINE_HEADING in first     # outside the pack: the block names its company
    assert "Competitor A runs two plants with about 400 staff." in first and "F4" in first
    assert second.startswith("Competitor C") and "Competitor C runs one plant and invested 12 million last year." in second
    assert BASELINE_HEADING in view["text"] and all(block["data-company"] == "other" for block in blocks)
    assert len(find(doc, "details", **{"class": "project"})) == 1   # a company without a move adds no empty project


def test_a_baseline_resting_on_an_uncertain_fact_carries_the_uncertain_mark(tmp_path):
    run = early_signal_run(tmp_path, baselines=False)
    analysis = store.read_analysis(run)
    analysis["baselines"] = [{"company": "Competitor C", "fact_ids": ["F3"]}]
    store.write_analysis(run, analysis)
    text = find(html_for(run), "div", **{"class": "baseline"})[0]["text"]
    assert "A planning application names a new filling hall at Plant North." in text and "Uncertain" in text


def test_a_baseline_with_two_facts_shows_both_statements_with_their_references(tmp_path):
    run = early_signal_run(tmp_path, baselines=False)
    analysis = store.read_analysis(run)
    analysis["baselines"] = [{"company": "Competitor A", "fact_ids": ["F4", "F1"]}]
    store.write_analysis(run, analysis)
    doc = html_for(run)
    block = find(doc, "div", **{"class": "baseline"})[0]["text"]
    assert "Competitor A runs two plants with about 400 staff." in block
    assert "Competitor A will add a second filling line at Plant North." in block
    assert block.index("F4") < block.index("F1")
    assert {ref["href"] for ref in find(doc, "a", **{"data-view": "facts"})} >= {"#F4", "#F1"}


def test_a_baseline_resting_on_a_non_public_fact_carries_the_class_mark(tmp_path):
    run = early_signal_run(tmp_path, baselines=False, mode="private", acknowledged=True)
    add_source(run, "Internal review: the plant employs about 90 people on two shifts.", data_class="internal",
               url="internal staffing review", publisher="Competitor C", type="other")
    add_fact(run, kind="general", fields=None, source_id="S4", primary_source=True,
             statement="The plant employs about 90 people.", quote="the plant employs about 90 people on two shifts")
    from radar import verify
    verify.check_quotes(run); verify.record_support(run, "F6", True, "support-checker", ""); verify.settle(run)
    analysis = store.read_analysis(run)
    analysis["baselines"] = [{"company": "Competitor C", "fact_ids": ["F6"]}]
    store.write_analysis(run, analysis)
    assert "Internal document" in find(html_for(run), "div", **{"class": "baseline"})[0]["text"]


def test_a_run_without_early_signals_or_baselines_shows_neither_block(tmp_path):
    doc = html_for(ready_run(tmp_path))
    assert not find(doc, "div", **{"class": "early-signals"}) and not find(doc, "div", **{"class": "baseline"})
    assert EARLY_NOTE not in doc and BASELINE_HEADING not in doc
    doc = html_for(early_signal_run(tmp_path / "again", baselines=False))
    assert find(doc, "div", **{"class": "early-signals"}) and not find(doc, "div", **{"class": "baseline"})


def test_a_baseline_company_name_is_escaped(tmp_path):
    run = early_signal_run(tmp_path, baselines=False)
    analysis = store.read_analysis(run)
    analysis["baselines"] = [{"company": "A <b>Co</b><script>alert(1)</script>", "fact_ids": ["F4"]}]
    store.write_analysis(run, analysis)
    doc = html_for(run)
    # the tidy name drops the outer ">"; the rest is escaped
    assert "<script>alert(1)</script" not in doc and "&lt;script&gt;alert(1)&lt;/script" in doc
    assert "<b>Co</b>" not in doc


def test_the_new_source_types_have_labels():
    labels = load_labels()
    assert labels["type_permit"] == "Building permit or planning record"
    assert labels["type_job_posting"] == "Job posting"
    assert labels["type_regulator_record"] == "Regulator record"
    for source_type in store.SOURCE_TYPES:
        assert "type_" + source_type in labels, source_type


def test_a_permit_source_page_shows_its_type_in_words(tmp_path):
    doc = html_for(early_signal_run(tmp_path))
    assert "Building permit or planning record" in find(doc, "article", id="S2")[0]["text"]
    values = [entry["text"] for entry in find(doc, "dd")]
    assert "Building permit or planning record" in values and "permit" not in values     # the label, never the engine word
    assert "Annual report" in values and "annual_report" not in values


# --- a source whose copy came from another address than the one asked for ---

def _passed_on_run(tmp_path, **over):
    run = make_run(tmp_path)
    add_source(run, "The expansion adds two high-speed syringe lines for customers, starting in 2028.", **over)
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    finish_run(run, ["F1"])
    return run


def test_a_source_that_was_passed_on_shows_both_addresses_on_its_page(tmp_path):
    labels = load_labels()
    doc = html_for(_passed_on_run(tmp_path, final_url="https://other.example/page"))
    page = [a for a in find(doc, "article", **{"class": "source"}) if a["id"] == "S1"][0]["text"]
    assert labels["source_asked"] in page and labels["source_passed_on"] in page
    assert 'href="https://s1.example.com/S1"' in doc and 'href="https://other.example/page"' in doc
    assert labels["source_link"] not in page   # the asked-for address is named as such


def test_a_source_that_was_not_passed_on_shows_what_it_always_showed(tmp_path):
    labels = load_labels()
    for name, over in (("a", {}), ("b", {"final_url": None})):
        doc = html_for(_passed_on_run(tmp_path / name, **over))
        page = [a for a in find(doc, "article", **{"class": "source"}) if a["id"] == "S1"][0]["text"]
        assert labels["source_link"] in page
        assert labels["source_asked"] not in page and labels["source_passed_on"] not in page


def test_the_markdown_report_names_both_addresses_of_a_passed_on_source(tmp_path):
    labels = load_labels()
    text = render_markdown(build_model(_passed_on_run(tmp_path / "a", final_url="https://other.example/page"), LENSES))
    assert labels["source_saved_from"] == "Saved from (the site passed the request on)"
    assert labels["source_saved_from"] in text and "https://other.example/page" in text
    assert "," not in labels["source_saved_from"]   # the source line is joined with commas
    assert labels["source_passed_on"] not in text
    assert labels["source_asked"] in text
    plain = render_markdown(build_model(_passed_on_run(tmp_path / "b"), LENSES))
    assert labels["source_asked"] not in plain and labels["source_saved_from"] not in plain


# --- DH1 follow-up: a date that is not stated, and a quote from the fact's own source ---------------------------

def test_a_date_that_is_not_stated_is_shown_in_words_in_both_reports_and_in_the_changes(tmp_path):
    from radar.report import visuals
    labels = load_labels()
    run = make_run(tmp_path)
    add_source(run, "Competitor A will add a second filling line at Plant North by 2028.")
    add_fact(run, source_id="S1", primary_source=True,
             fields={"announced": "not_stated", "planned_start": "not_stated"})
    finish_run(run, [])
    model = build_model(run, LENSES)
    page = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", render_html(model), flags=re.S)
    markdown = render_markdown(model).replace("\\_", "_")
    for name, text in (("html", page), ("markdown", markdown)):
        assert "not_stated" not in text, name
    assert labels["date_announced_not_stated"] in markdown
    for name in ("announced", "planned_start"):
        assert visuals.field_value(name, "not_stated", labels) == labels["value_not_stated"], name
    assert visuals.field_value("announced", "2026-05-14", labels) == "2026-05-14"


def test_a_quote_from_another_source_and_one_from_the_same_source_go_under_their_own_headings(tmp_path):
    labels = load_labels()
    run = make_run(tmp_path)
    add_source(run, "Competitor A will add a second filling line at Plant North by 2028. Plant North is in "
                    "Exampleland and makes syringes.", publisher="Competitor A")
    add_source(run, "A trade paper says Competitor A will add a second filling line at Plant North.",
               publisher="Trade Paper", type="trade_press")
    add_fact(run, source_id="S1", primary_source=True,
             supporting=[{"source_id": "S1", "quote": "Plant North is in Exampleland and makes syringes."},
                         {"source_id": "S2", "quote": "Competitor A will add a second filling line"}])
    finish_run(run, ["F1"])
    card = find(html_for(run), "details", **{"class": "fact"})[0]["text"]
    same, other = card.index(labels["supporting_same_source"]), card.index(labels["supporting_sources"])
    assert same < card.index("Exampleland and makes syringes") < other
    assert "Competitor A will add a second filling line" in card[other:] and "Exampleland" not in card[other:]
    assert labels["supporting_same_source"] == "More from the same source"


# --- fix wave A18: the illustrative banner says only what is always true of an illustrative run ----------------------

BANNER = ("Illustrative only. This report was made with an invented company pack as practice material. "
          "Nothing in it is a finding about a real company.")


from radar import demo   # noqa: E402
from test_report_build import TEXT   # noqa: E402


# --- fix wave A23.5: a supporting source that repeats the fact's own source says so on the card ----------------------

def _card(html, fact_id):
    return html.split(f'<details class="fact" id="{fact_id}"')[1].split("</details>")[0]


def test_a_supporting_source_based_on_the_main_source_is_marked_as_repeating_it(tmp_path):
    run = demo.build_demo_run(tmp_path)
    build_report(run, demo.LENSES)
    html = (run / "report" / "report.html").read_text(encoding="utf-8")
    facts, sources = store.read_facts(run), store.read_sources(run)
    labels = load_labels()
    repeating = next(fact_id for fact_id, fact in facts.items()
                     if any(sources[entry["source_id"]].get("based_on") == [fact["source_id"]]
                            for entry in fact["supporting"]))
    card = _card(html, repeating)
    note = labels["supporting_repeats"].format(source=facts[repeating]["source_id"])
    assert labels["supporting_sources"] in card and esc(note) in card
    assert card.index(labels["supporting_sources"]) < card.index(esc(note))
    independent = next(fact_id for fact_id, fact in facts.items()
                       if fact["status"] == "confirmed" and fact["primary_source"] is False)
    assert labels["supporting_sources"] in _card(html, independent)
    assert "class=\"repeats\"" not in _card(html, independent)


def test_the_repeat_mark_follows_the_whole_chain_of_based_on(tmp_path):
    run = make_run(tmp_path)
    add_source(run, TEXT, publisher="Competitor A")
    add_source(run, "Paper one: " + TEXT, publisher="Paper One", based_on=["S1"])
    add_source(run, "Paper two: " + TEXT, publisher="Paper Two", based_on=["S2"])
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers",
             supporting=[{"source_id": "S3", "quote": "adds two high-speed syringe lines for customers"}])
    finish_run(run, ["F1"])
    html = render_html(build_model(run, LENSES))
    assert esc(load_labels()["supporting_repeats"].format(source="S1")) in _card(html, "F1")


# --- Task 10: the answer first, then the companies and the key messages, then the tabs --------------------------------

from radar import projects, verify                                     # noqa: E402
from radar.report import visuals                                       # noqa: E402
from test_report_projects import analysis_with_flags, group, moves_run  # noqa: E402

ANSWER_NOTE = ("Counted by project. The grouping into projects is a model's judgement; the program checked only that "
               "each move sits in one project, and that a project holds one company and one country.")


def grouped_page(tmp_path, analysis=None):
    run = moves_run(tmp_path, analysis)
    group(run)
    return run, html_for(run)


def view_of(doc, name):
    return find(doc, "section", id=f"view-{name}")[0]


def test_the_page_opens_on_the_answer_then_companies_then_messages_then_the_tabs(tmp_path):
    _, doc = grouped_page(tmp_path)
    marks = ['<div class="banner', '<header class="masthead">', "<main>", '<section id="answer"', '<nav id="companies"',
             '<section id="messages"', '<nav class="tabs"', '<section class="view on" id="view-facts"']
    marks = [mark for mark in marks if mark in doc]
    assert marks == ['<header class="masthead">', "<main>", '<section id="answer"', '<nav id="companies"',
                     '<section id="messages"', '<nav class="tabs"', '<section class="view on" id="view-facts"']
    assert [doc.index(mark) for mark in marks] == sorted(doc.index(mark) for mark in marks)
    assert "Who is the new capacity for?" in find(doc, "section", id="answer")[0]["text"]
    assert "Look at one company" in find(doc, "nav", id="companies")[0]["text"]
    assert "Key messages" in find(doc, "section", id="messages")[0]["text"]
    assert find(doc, "section", id="messages")[0]["text"].count("Competitor A is adding capacity.") == 1


def test_the_tabs_are_the_new_views_in_order(tmp_path):
    _, doc = grouped_page(tmp_path)
    tabs = [e["data-view"] for e in find(doc, "button") if "data-view" in e]
    assert tabs == ["facts", "projects", "connections", "timeline", "scenarios", "options", "checks", "thinking",
                    "sources", "how"]
    assert find(doc, "section", id="view-summary") == [] and find(doc, "section", id="view-competitors") == []
    assert [b["text"] for b in find(doc, "button") if b.get("data-view") in ("projects", "connections")] == \
        ["Projects", "Connections"]


def test_the_answer_bar_shows_the_model_s_counts_and_its_note_and_rule(tmp_path):
    run, doc = grouped_page(tmp_path)
    answer = build_model(run, LENSES)["core_answer"]
    assert answer == {"open": 1, "captive": 1, "disagree": 0, "not_stated": 0, "total": 2, "outside": 0}
    parts = find(doc, "a", **{"class": "answer-part"})
    assert [(p["data-access"], p["class"]) for p in parts] == [("open", "answer-part open"),
                                                              ("captive", "answer-part captive")]
    assert all(p["href"] == "#view-projects" and p["data-view"] == "projects" for p in parts)
    assert [p["style"] for p in parts] == ["width:%d%%" % visuals._width(Decimal(1), Decimal(2))] * 2 == ["width:50%"] * 2
    assert "Open to customers" in parts[0]["text"] and "For own use" in parts[1]["text"]
    text = find(doc, "section", id="answer")[0]["text"]
    assert ANSWER_NOTE in text and "A project counts as open to customers when at least one of its reports says so" in text
    assert "2 projects" in text and "Reports disagree" in text and "Not stated" in text   # all four are named, even at zero
    assert "every move counts as its own project" not in text


def test_the_widths_of_the_answer_bar_are_percentages_of_the_projects(tmp_path):
    run = moves_run(tmp_path)           # four moves, each its own project: three open, one for own use
    parts = find(html_for(run), "a", **{"class": "answer-part"})
    assert [(p["data-access"], p["style"]) for p in parts] == [("open", "width:75%"), ("captive", "width:25%")]


def test_the_bar_says_how_many_moves_fall_outside(tmp_path):
    from test_report_projects import five_moves_run
    labels = load_labels()
    assert labels["answer_outside"] == "{n} more moves were found that fall outside the question."
    doc = html_for(five_moves_run(tmp_path / "two"))
    answer = find(doc, "section", id="answer")[0]
    assert "2 more moves were found that fall outside the question." in answer["text"]
    [link] = find(doc, "a", **{"data-filter-question": "outside"})
    assert link["href"] == "#view-facts" and "2 more moves" in link["text"]
    facts = find(doc, "details", **{"class": "fact"})
    assert sorted(f["id"] for f in facts if f["data-question"] == "outside") == ["F4", "F5"]
    assert all(f["data-question"] == "inside" for f in facts if f["id"] not in ("F4", "F5"))
    # the moves outside are facts, so only the facts bar has the choice
    bars = re.findall(r'<form class="filters" data-list="(\w+)".*?</form>', doc, re.S)
    assert len(find(doc, "select", name="question")) == 1 and len(find(doc, "option", value="outside")) == 1
    assert [list_name for list_name in bars if 'name="question"' in
            re.search(rf'<form class="filters" data-list="{list_name}".*?</form>', doc, re.S).group(0)] == ["facts"]
    doc = html_for(five_moves_run(tmp_path / "none", in_question=("yes",) * 5))
    assert "outside the question" not in find(doc, "section", id="answer")[0]["text"]
    assert find(doc, "select", name="question") == [] and 'class="answer-outside"' not in doc
    assert find(doc, "a", **{"data-filter-question": "outside"}) == []
    markdown = render_markdown(build_model(five_moves_run(tmp_path / "md"), LENSES))
    assert "2 more moves were found that fall outside the question (F4, F5)." in markdown
    assert "1 more move was found that falls outside the question." == \
        labels["answer_outside_one"].format(n=1)


def _bare_move(fact_id, inside, **fields):
    return {"id": fact_id, "kind": "capacity_move", "status": "confirmed",
            "fields": {"company": "Competitor A", "move_type": "expansion", "site": f"Plant {fact_id}",
                       "country": "Exampleland", "size_value": "2", "size_unit": "lines", "planned_start": "2028",
                       "access": "open", "delivery": "on_time", "in_question": inside, **fields}}


def _pieces(fragment, start, fact_id):
    """The pieces of `fragment` that begin with `start` and link to `fact_id`."""
    return [piece for piece in fragment.split(start)[1:] if f'href="#{fact_id}"' in piece]


def test_moves_outside_the_question_are_left_out_of_bars_and_grid_and_marked_elsewhere():
    from radar.report import visuals
    labels = load_labels()
    assert labels["pill_outside"] == "outside the question"
    assert labels["grid_outside"] == "{n} outside the question"
    mark = '<span class="pill outside">outside the question</span>'
    facts = [_bare_move("F1", "yes"), _bare_move("F2", "yes", size_value="3"),
             _bare_move("F3", "no", size_value="9"), _bare_move("F4", "no", planned_start=None)]
    bars = visuals.capacity_bars(facts)
    assert 'href="#F1"' in bars and 'href="#F2"' in bars and "F3" not in bars and "F4" not in bars
    assert [sum(tally["n"] for tally in tallies) for _, tallies in visuals.move_counts(facts)] == [2]
    timeline = visuals.timeline(facts)
    [inside], [outside] = _pieces(timeline, '<span class="entry">', "F1"), _pieces(timeline, '<span class="entry">', "F3")
    assert mark in outside and mark not in inside
    [undated] = _pieces(timeline, "<li>", "F4")
    assert mark in undated
    sites = visuals.sites_by_country(facts)
    assert mark in _pieces(sites, "<li>", "F3")[0] and mark not in _pieces(sites, "<li>", "F1")[0]
    assert "2 outside the question" in visuals.delivery_table(facts)
    assert "outside the question" not in visuals.delivery_table(facts[:2])


def test_the_facts_list_the_markdown_and_the_company_head_show_the_moves_outside(tmp_path):
    from test_report_projects import five_moves_run
    model = build_model(five_moves_run(tmp_path), LENSES)
    doc = render_html(model)
    mark = '<span class="pill outside">outside the question</span>'
    facts = {f["id"]: f for f in find(doc, "details", **{"class": "fact"})}
    for fact_id in facts:
        card = re.search(rf'<details class="fact" id="{fact_id}".*?</summary>', doc, re.S).group(0)
        assert (mark in card) == (fact_id in ("F4", "F5")), fact_id
    [company] = [entry for entry in model["companies"] if entry["name"] == "Competitor A"]
    head = find(doc, "section", **{"data-company-head": company["key"]})[0]["text"]
    assert "2 more moves were found that fall outside the question." in head
    bars = re.search(r'<div class="capacity-group">.*?</ul></div>', doc, re.S).group(0)
    assert 'href="#F1"' in bars and 'href="#F4"' not in bars and 'href="#F5"' not in bars
    markdown = render_markdown(model)
    assert "2 more moves were found that fall outside the question (F4, F5)." in markdown


def test_an_ungrouped_run_says_why_each_move_counts_as_its_own_project(tmp_path):
    labels = load_labels()
    run = moves_run(tmp_path)
    reasons = {}
    reasons["none"] = find(html_for(run), "section", id="answer")[0]["text"]
    group(run)
    verify.withdraw_fact(run, "F2", "a duplicate of F1")
    verify.settle(run)
    reasons["outdated"] = find(html_for(run), "section", id="answer")[0]["text"]
    (run / projects.RECORD).write_text("{not json", encoding="utf-8")
    reasons["damaged"] = find(html_for(run), "section", id="answer")[0]["text"]
    for state, text in reasons.items():
        assert labels[f"answer_ungrouped_{state}"] in text and "its own project" in labels[f"answer_ungrouped_{state}"]
        assert ANSWER_NOTE not in text and labels["answer_rule"] in text
    assert len({labels[f"answer_ungrouped_{state}"] for state in reasons}) == 3
    page = html_for(run)
    assert labels["answer_ungrouped_damaged"] in find(page, "section", id="view-projects")[0]["text"]


def test_a_run_without_a_counting_move_has_no_answer_section(tmp_path):
    assert find(html_for(ready_run(tmp_path / "e")), "section", id="answer") != []     # a move counts here
    run = make_run(tmp_path / "x")
    add_source(run, TEXT)
    add_fact(run, kind="general", fields=None, source_id="S1", primary_source=True,
             quote="adds two high-speed syringe lines for customers")
    finish_run(run, ["F1"])
    assert find(html_for(run), "section", id="answer") == []


def test_company_buttons_carry_their_final_markup(tmp_path):
    run, doc = grouped_page(tmp_path)
    buttons = find(doc, "a", **{"class": "company-button"})
    assert [(b["data-company-page"], b["href"]) for b in buttons] == \
        [("c1", "#view-projects"), ("c2", "#projects-c2"), ("c3", "#projects-c3")]   # c1 has no fact: no heading
    assert [b["text"] for b in buttons][1:] == ["Competitor A", "Competitor B"]
    assert "own company" in buttons[0]["text"] and buttons[0]["text"].startswith("Example Pharma")
    assert find(doc, "h3", id="projects-c2") and find(doc, "h3", id="projects-c3") and not find(doc, "h3", id="projects-c1")


def test_a_company_without_a_project_links_to_its_facts_and_the_two_extra_buttons_open_the_facts(tmp_path):
    run = make_run(tmp_path, companies=[{"name": "Competitor A", "other_names": [], "home": False}])
    add_source(run, "Competitor A employs about 400 people. Drug maker X reports a fire.")
    add_fact(run, kind="general", fields=None, source_id="S1", primary_source=True, about_company="Competitor A",
             statement="Competitor A employs about 400 people.", quote="Competitor A employs about 400 people")
    add_fact(run, kind="general", fields=None, source_id="S1", primary_source=True,
             statement="A fire was reported.", quote="Drug maker X reports a fire")
    finish_run(run, ["F1"])
    doc = html_for(run)
    buttons = find(doc, "a", **{"class": "company-button"})
    assert [(b.get("data-company-page"), b.get("data-filter-company"), b["href"]) for b in buttons] == \
        [("c1", None, "#facts-c1"), (None, "none", "#view-facts")]
    assert buttons[1]["text"] == "Not about one company"
    nav = find(doc, "nav", id="companies")[0]["text"]
    assert "0 projects" not in nav and "project" not in nav.replace("Look at one company", "")   # no count, no empty bar
    assert find(doc, "h3", id="facts-c1") and find(doc, "h3", id="facts-none") and not find(doc, "h3", id="projects-c1")
    other = find(html_for(ready_run(tmp_path / "other")), "a", **{"class": "company-button"})
    assert [(b["data-filter-company"], b["href"], b["text"]) for b in other] == \
        [("other", "#view-facts", "Other companies")]


def test_the_facts_are_listed_under_a_heading_for_each_company(tmp_path):
    _, doc = grouped_page(tmp_path)
    view = view_of(doc, "facts")
    headings = [(h["id"], h["data-company"], h["text"]) for h in find(view_html(doc, "facts"), "h3")]
    assert headings == [("facts-c2", "c2", "Competitor A"), ("facts-c3", "c3", "Competitor B")]
    assert [f["id"] for f in find(view_html(doc, "facts"), "details", **{"class": "fact"})] == ["F3", "F1", "F2", "F5", "F4"]
    assert view["text"].index("Competitor A") < view["text"].index("Competitor B")


def view_html(doc, name):
    start = doc.index(f'id="view-{name}"')
    following = [doc.find(f'id="view-{other}"', start + 1) for other in
                 ("projects", "connections", "timeline", "scenarios", "options", "checks", "thinking", "sources", "how")]
    return doc[start:min([end for end in following if end != -1] or [len(doc)])]


def test_a_message_names_its_sources_and_shows_its_checks_outside_the_fold(tmp_path):
    _, doc = grouped_page(tmp_path, analysis_with_flags())
    [item] = find(doc, "div", **{"class": "message-item"})
    assert item["data-company"] == "c2 c3"
    [details] = find(doc, "details", **{"class": "message"})
    sources = find(doc, "p", **{"class": "message-sources"})[0]
    assert sources["text"] == "Sources: Competitor A (the company's own statement), Trade Journal, " \
                              "Competitor A (the company's own statement)"
    assert [(a["href"], a["data-view"]) for a in find(doc, "a") if a.get("href") in ("#S1", "#S2", "#S3")
            and a["text"] in ("Competitor A", "Trade Journal")][:3] == [("#S1", "sources"), ("#S2", "sources"),
                                                                       ("#S3", "sources")]
    [checks] = find(doc, "div", **{"class": "message-checks"})
    assert "Checks on this message" in checks["text"] and "Framing" in checks["text"]
    assert "The message leans on Competitor A's own words." in checks["text"]
    assert "The message leans" not in details["text"] and "Sources" not in details["text"]
    block = doc[doc.index('<div class="message-item"'):doc.index('<nav class="tabs"')]
    assert block.index("</details>") < block.index('class="message-sources"') < block.index('class="message-checks"')
    assert "No base rate was looked for." not in checks["text"]            # it names no message: Checks tab only


def test_a_message_without_checks_shows_no_checks_box_and_one_without_facts_belongs_to_none(tmp_path):
    run, doc = grouped_page(tmp_path)
    assert find(doc, "div", **{"class": "message-checks"}) == []
    model = build_model(run, LENSES)
    model["messages"][0]["companies"] = []
    model["messages"][0]["sources"] = []
    page = render_html(model)
    assert find(page, "div", **{"class": "message-item"})[0]["data-company"] == "none"
    assert find(page, "p", **{"class": "message-sources"}) == []


def test_the_checks_tab_links_each_flag_to_its_messages(tmp_path):
    _, doc = grouped_page(tmp_path, analysis_with_flags())
    flags = find(view_html(doc, "checks"), "li")
    assert len(flags) == 2
    assert [(a["href"], a["text"]) for a in find(view_html(doc, "checks"), "a")] == [("#M1", "M1")]
    assert "About" in flags[0]["text"] and "About" not in flags[1]["text"]
    assert all("data-view" not in a for a in find(view_html(doc, "checks"), "a"))      # a message is not in a view


def test_a_project_shows_its_spread_and_every_report_underneath(tmp_path):
    _, doc = grouped_page(tmp_path)
    projects_html = view_html(doc, "projects")
    cards = {d["id"]: d for d in find(projects_html, "details", **{"class": "project"})}
    assert list(cards) == ["P2", "P1"]
    card = cards["P2"]["text"]
    assert "Competitor A, Plant North" in card and "Open to customers" in card and "3 confirmed" in card
    row = find(projects_html[projects_html.index('id="P2"'):], "summary")[0]["text"]     # on the row, closed
    for part in ("Stage", "Announced (2), Operating (1)", "Site", "Plant North (2)", "Planned start", "2028 (3)",
                 "Country", "Exampleland (3)"):
        assert part in row, part
    assert "What was added" in card and "a second filling line (3)" in card and "What was added" not in row
    inner = projects_html[projects_html.index('id="P2"'):projects_html.index('id="P1"')]
    reports = find(inner, "li", **{"class": "project-report"})
    assert len(reports) == 3 and [a["href"] for a in find(inner, "a") if a["href"].startswith("#F")] == ["#F3", "#F1", "#F2"]
    assert all("2026" in report["text"] and "(2 lines)" in report["text"] for report in reports)   # the stated size
    single = cards["P1"]["text"]
    assert "Captive" not in single and "For own use" in single and "1 from one source only" in single
    assert "(1)" not in single                                              # one report: no counts in the spread
    assert not [e for e in find(projects_html, "details") + find(projects_html, "li") if e.get("id", "").startswith("F")]
    assert [h["id"] for h in find(projects_html, "h3", **{"data-company": "c2"})] == ["projects-c2"]


def test_the_projects_view_holds_the_company_totals_after_the_projects(tmp_path):
    _, doc = grouped_page(tmp_path)
    projects_html = view_html(doc, "projects")
    assert find(projects_html, "div", **{"class": "projects-more"})
    more = projects_html[projects_html.index('class="projects-more"'):]
    order = [more.index(f"<h3>{name}") for name in ("Capacity", "Sites by country", "Moves by type")]
    assert order == sorted(order)
    assert projects_html.index('id="P1"') < projects_html.index('class="projects-more"')
    assert "Moves by type" in [h["text"] for h in find(more, "h3")]


def test_the_connections_tab_says_who_is_tied_to_whom(tmp_path):
    run, doc = grouped_page(tmp_path)
    [row] = find(view_html(doc, "connections"), "tr", **{"class": "connection"})
    for part in ("Competitor A", "Customer", "Drug maker B", "F5", "Confirmed"):
        assert part in row["text"], part
    assert [a["href"] for a in find(view_html(doc, "connections"), "a")] == ["#F5"]
    heads = [th["text"] for th in find(view_html(doc, "connections"), "th", scope="col")]
    assert heads == ["Company", "Tie", "Party", "Status", "Fact"]


def test_a_party_that_is_not_named_shows_its_description(tmp_path):
    run = make_run(tmp_path, companies=[{"name": "Competitor A", "other_names": [], "home": False}])
    add_source(run, "Competitor A sold its plant to a major biopharma partner.")
    add_fact(run, kind="general", fields=None, source_id="S1", primary_source=True, about_company="Competitor A",
             statement="Competitor A sold a plant.", quote="Competitor A sold its plant to a major biopharma partner",
             connections=[{"party": None, "tie": "buyer", "description": "a major biopharma partner"}])
    finish_run(run, ["F1"])
    row = find(html_for(run), "tr", **{"class": "connection"})[0]["text"]
    assert "Buyer" in row and "Not named: a major biopharma partner" in row


def test_the_connections_tab_of_a_run_without_connections_says_so(tmp_path):
    run = ready_run(tmp_path)   # its facts carry `connections: []`: the run recorded none
    view = view_of(html_for(run), "connections")
    assert load_labels()["none_connections"] in view["text"] and load_labels()["none_connections_old"] not in view["text"]
    assert find(html_for(run), "tr", **{"class": "connection"}) == []


def test_the_connections_tab_says_when_every_party_was_dropped_for_want_of_a_quote(tmp_path):
    labels = load_labels()
    assert labels["none_connections_dropped"] == ("This run recorded customers, partners, sellers or buyers, "
                                                  "but no quote names them, so none are shown.")
    run = make_run(tmp_path, companies=[{"name": "Competitor A", "other_names": [], "home": False}])
    add_source(run, "Competitor A sold its plant to a major biopharma partner.")
    add_fact(run, kind="general", fields=None, source_id="S1", primary_source=True, about_company="Competitor A",
             statement="Competitor A sold a plant.", quote="Competitor A sold its plant to a major biopharma partner",
             connections=[{"party": "Drug maker Z", "tie": "buyer", "description": None}])
    finish_run(run, ["F1"])
    text = view_of(html_for(run), "connections")["text"]
    assert labels["none_connections_dropped"] in text and labels["none_connections"] not in text


def test_the_connections_tab_of_a_run_made_before_connections_were_recorded_says_so(tmp_path):
    run = ready_run(tmp_path)
    for fact in store.read_facts(run).values():
        del fact["connections"]
        store.write_fact(run, fact)
    text = view_of(html_for(run), "connections")["text"]
    assert load_labels()["none_connections_old"] in text and load_labels()["none_connections"] not in text


def test_every_empty_tab_says_why_it_is_empty():
    model, labels = empty_model(), load_labels()
    model["changes"] = {}
    doc = render_html(model)
    for view, key in (("projects", "none_projects"), ("connections", "none_connections"), ("timeline", "none_timeline"),
                      ("options", "none_options"), ("checks", "none_checks"), ("thinking", "none_thinking"),
                      ("sources", "none_sources"), ("changes", "none_changes")):
        assert labels[key] in view_of(doc, view)["text"], view
    assert "Nothing to show here." not in doc and "none_here" not in labels


def test_a_run_with_facts_but_no_key_messages_says_so_in_both_reports(tmp_path):
    run = ready_run(tmp_path, analysis=dict(minimal_analysis(["F1"], "firm-boundaries"), messages=[]))
    model, labels = build_model(run, LENSES), load_labels()
    assert labels["none_messages"] in find(render_html(model), "section", id="messages")[0]["text"]
    assert labels["none_messages"] in render_markdown(model)


def test_a_fact_from_one_source_carries_the_one_source_only_pill(tmp_path):
    _, doc = grouped_page(tmp_path)
    cards = {d["id"]: d["text"] for d in find(doc, "details", **{"class": "fact"})}
    pills = [p for p in find(doc, "span", **{"class": "pill status-single_source"})]
    assert pills and all(p["class"] == "pill status-uncertain status-single_source" and p["text"] == "One source only"
                         for p in pills)
    assert "One source only" in cards["F4"] and "Confirmed" in cards["F1"] and "One source only" not in cards["F1"]
    assert load_labels()["single_source_note"] in cards["F4"] and load_labels()["single_source_note"] not in cards["F1"]
    assert "Uncertain" not in cards["F4"]
    summary = doc[doc.index('id="F4"'):].split("</summary>")[0]
    assert 'class="pill status-uncertain status-single_source"' in summary


def test_an_uncertain_fact_that_is_not_only_single_source_keeps_the_uncertain_pill(tmp_path):
    doc = html_for(early_signal_run(tmp_path))
    card = [f for f in find(doc, "details", **{"class": "fact"}) if f["id"] == "F3"][0]["text"]
    assert "Uncertain" in card and "One source only" not in card
    assert load_labels()["single_source_note"] not in card


def test_rejected_facts_still_appear_only_under_checks(tmp_path):
    run = moves_run(tmp_path)
    group(run)
    verify.withdraw_fact(run, "F4", "not about a plant")
    verify.settle(run)
    doc = html_for(run)
    checks = view_of(doc, "checks")["text"]
    assert "Competitor B builds a plant" in checks and "Withdrawn by the analyst." in checks
    for name in ("facts", "projects", "connections", "timeline", "sources"):
        assert "Competitor B builds a plant" not in view_html(doc, name), name
    assert [f["id"] for f in find(doc, "details", **{"class": "fact"})] == ["F3", "F1", "F2", "F5"]
    assert "F4" not in view_html(doc, "projects")


def test_the_status_line_counts_one_source_only_apart_from_the_other_uncertain(tmp_path):
    _, doc = grouped_page(tmp_path)
    line = find(doc, "p", **{"class": "status-line"})[0]["text"]
    parts = line.split(" · ")
    assert parts[2:] == ["5 facts, all quotes checked", "1 from one source only", "0 marked uncertain",
                         "0 proposed facts rejected"]
    run = private_run_with_uncertain_fact(tmp_path / "private")
    assert "1 from one source only · 0 marked uncertain" in find(html_for(run), "p", **{"class": "status-line"})[0]["text"]
    model = build_model(moves_run(tmp_path / "again"), LENSES)
    model["status_line"].update(uncertain=4, single_source=1)
    assert "1 from one source only · 3 marked uncertain" in find(render_html(model), "p", **{"class": "status-line"})[0]["text"]


def test_how_this_report_was_made_explains_the_grouping_the_rule_and_the_names_dropped(tmp_path):
    labels = load_labels()
    run, doc = grouped_page(tmp_path)
    how = view_of(doc, "how")["text"]
    assert ANSWER_NOTE in how and labels["answer_rule"] in how and "were not found in their quotes" not in how
    assert how.index(labels["answer_rule"]) < how.index("How to read the confidence words")
    model = build_model(run, LENSES)
    model["how_made"]["names_dropped"] = {"companies": 2, "parties": 1}
    text = view_of(render_html(model), "how")["text"]
    assert "2 company names and 1 names of other parties were not found in their quotes, so they are not shown." in text
    assert "Recorded test answer" in text and "The lens recommendation" in text
    ungrouped = view_of(html_for(moves_run(tmp_path / "u")), "how")["text"]
    assert labels["answer_ungrouped_none"] in ungrouped and ANSWER_NOTE not in ungrouped


def test_the_lens_recommendation_block_still_shows(tmp_path):
    doc = html_for(ready_run(tmp_path))
    assert "No recommendation was made" in view_of(doc, "how")["text"]


def test_markup_in_a_company_or_project_name_is_escaped(tmp_path):
    nasty = '"><svg onload=alert(1)> <script>alert(1)</script>'
    run = make_run(tmp_path, companies=[{"name": nasty, "other_names": [], "home": True}], home_company=nasty)
    add_source(run, "Competitor A will add a filling line at Plant North, and so will " + nasty + " here.")
    add_fact(run, source_id="S1", primary_source=True, quote="Competitor A will add a filling line at Plant North",
             fields={"company": nasty, "site": '<img src=x onerror=alert(1)>', "what_added": "<b>lines</b>"})
    add_fact(run, source_id="S1", primary_source=True, quote="Competitor A will add a filling line at Plant North",
             fields={"company": nasty, "site": "x"}, statement="<i>second</i>")
    finish_run(run, ["F1"])
    projects.record_projects(run, [{"name": "<u>Big</u> project " + nasty, "fact_ids": ["F1", "F2"]}], projects.GROUPER)
    doc = html_for(run)
    assert "<svg" not in doc and "<script>alert" not in doc and "<img src=x" not in doc and "<u>" not in doc
    assert "<b>lines</b>" not in doc and "<i>second</i>" not in doc
    assert find(doc, "svg") == [] and find(doc, "img") == []
    handlers = [name for tag in ("a", "div", "span", "details", "h3", "section", "nav", "li", "p", "summary")
                for element in find(doc, tag) for name in element if name.lower().startswith("on")]
    assert handlers == []
    assert "&lt;u&gt;Big&lt;/u&gt; project" in doc


def test_no_id_appears_twice_on_a_grouped_page_with_predictions(tmp_path):
    analysis = minimal_analysis(["F1"], "firm-boundaries")
    analysis["predictions"] = [{"id": "P1", "message_id": "M1", "statement": "Both lines start", "by": "2028-12-31",
                                "resolves_when": "The company says so", "probability": 65}]
    _, doc = grouped_page(tmp_path, analysis)
    ids = re.findall(r'\bid="([^"]+)"', doc)
    assert len(ids) == len(set(ids)) and "P1" in ids and "prediction-P1" in ids


def test_the_script_opens_the_view_of_a_target_and_leaves_it_for_a_target_outside_a_view():
    js = (REPORT_DIR / "report.js").read_text(encoding="utf-8")
    assert '"summary"' not in js and "viewName || viewOf(target)" in js
    assert 'goTo(decodeURIComponent(location.hash.slice(1)))' in js and "hashchange" in js


def test_a_pack_company_s_baseline_stands_under_its_heading_and_gives_a_company_with_no_move_a_heading(tmp_path):
    analysis = minimal_analysis(["F1"], "firm-boundaries")
    analysis["baselines"] = [{"company": "Competitor A", "fact_ids": ["F5"]}, {"company": "Example Pharma", "fact_ids": ["F5"]}]
    _, doc = grouped_page(tmp_path, analysis)
    projects_html = view_html(doc, "projects")
    blocks = find(projects_html, "div", **{"class": "baseline"})
    assert [b["data-company"] for b in blocks] == ["c1", "c2"]
    assert all("Competitor A will sell vials to Drug maker B." in b["text"] for b in blocks)
    assert not any(b["text"].startswith(("Example Pharma", "Competitor A")) for b in blocks)   # the heading names it
    assert [h["id"] for h in find(projects_html, "h3") if h.get("data-company")] == ["projects-c1", "projects-c2", "projects-c3"]
    assert projects_html.index('id="projects-c2"') < projects_html.index('id="P2"') < projects_html.index('data-company="c2"', projects_html.index('id="P2"'))
    assert [b["href"] for b in find(doc, "a", **{"class": "company-button"})] == \
        ["#projects-c1", "#projects-c2", "#projects-c3"]


# --- Task 11: filters on every list, and a page for each company --------------------------------------------------------

import html as html_module                                              # noqa: E402

CSS = (REPORT_DIR / "report.css").read_text(encoding="utf-8")
JS = (REPORT_DIR / "report.js").read_text(encoding="utf-8")
LISTS = (("facts", "details", "fact"), ("projects", "details", "project"), ("connections", "tr", "connection"),
         ("sources", "article", "source"))
COMPANY_TOKENS = re.compile(r"(c[0-9]+|other|none)( (c[0-9]+|other|none))*")
DATE_TOKENS = re.compile(r"([0-9]{4}(-[0-9]{2}(-[0-9]{2})?)?( [0-9]{4}(-[0-9]{2}(-[0-9]{2})?)?)*)?")
STATUS_TOKENS = re.compile(r"(confirmed|single_source|uncertain|rejected)( (confirmed|single_source|uncertain|rejected))*")


def items_of(doc, view):
    _, tag, css = [entry for entry in LISTS if entry[0] == view][0]
    return find(view_html(doc, view) if view != "facts" else view_html(doc, "facts"), tag, **{"class": css})


def test_every_list_item_carries_company_date_and_status_tokens(tmp_path):
    _, doc = grouped_page(tmp_path)
    facts = {item["id"]: item for item in items_of(doc, "facts")}
    assert {fact_id: (item["data-company"], item["data-date"], item["data-status"]) for fact_id, item in facts.items()} == {
        "F1": ("c2", "2026-05-14", "confirmed"), "F2": ("c2", "2026-05-14", "confirmed"),
        "F3": ("c2", "2026-09-01", "confirmed"), "F4": ("c3", "2026-03-02", "single_source"),
        "F5": ("c2", "2026-05-14", "confirmed")}
    projects_found = {item["id"]: item for item in items_of(doc, "projects")}
    assert [(i, p["data-company"], p["data-date"], p["data-status"], p["data-access"])
            for i, p in sorted(projects_found.items())] == [
        ("P1", "c3", "2026-03-02", "single_source", "captive"),
        ("P2", "c2", "2026-09-01 2026-05-14", "confirmed", "open")]
    [row] = items_of(doc, "connections")
    assert (row["data-company"], row["data-date"], row["data-status"]) == ("c2 other", "2026-05-14", "confirmed")
    sources = {item["id"]: item for item in items_of(doc, "sources")}
    assert {i: (s["data-company"], s["data-date"], s["data-status"]) for i, s in sources.items()} == {
        "S1": ("c2", "2026-05-14", "confirmed"), "S2": ("c3", "2026-03-02", "single_source"),
        "S3": ("c2", "2026-09-01", "confirmed")}
    for view, tag, css in LISTS:
        assert items_of(doc, view), view
        assert all(set(("data-company", "data-date", "data-status")) <= set(item) for item in items_of(doc, view))
    assert all("data-access" not in item for view in ("facts", "connections", "sources") for item in items_of(doc, view))


def test_an_early_signal_and_the_early_signals_block_carry_tokens_too(tmp_path):
    run = make_run(tmp_path, companies=[{"name": "Competitor A", "other_names": [], "home": False}])
    add_source(run, "Competitor A may add a line at Plant North, a rumour says.", date="2026-06")
    add_fact(run, source_id="S1", primary_source=True, quote="Competitor A may add a line at Plant North",
             certainty="tentative", tentative_reason="a rumour", early_signal=True,
             fields={"company": "Competitor A"})
    finish_run(run, [])
    doc = html_for(run)
    [block] = find(doc, "div", **{"class": "early-signals"})
    assert block["data-company"] == "c1"
    [card] = find(doc, "details", **{"class": "fact"})
    assert (card["data-company"], card["data-date"], card["data-status"]) == ("c1", "2026-06", "uncertain")


def test_the_tokens_hold_no_model_text(tmp_path):
    nasty = '"><svg onload=alert(1)> c1'
    run = make_run(tmp_path, companies=[{"name": nasty, "other_names": [], "home": True}], home_company=nasty)
    add_source(run, "Competitor A will add a filling line at Plant North, and so will " + nasty + " here.",
               date='spring "2026" <b>')
    add_fact(run, source_id="S1", primary_source=True, quote="Competitor A will add a filling line at Plant North",
             fields={"company": nasty, "site": "x"})
    add_fact(run, kind="general", fields=None, source_id="S1", primary_source=True, about_company="Drug maker X",
             statement="Drug maker X is mentioned.", quote="Competitor A will add a filling line at Plant North")
    finish_run(run, ["F1"])
    doc = html_for(run)
    attributes = {name: re.findall(rf'\bdata-{name}="([^"]*)"', doc) for name in ("company", "date", "status")}
    assert attributes["company"] and attributes["date"] and attributes["status"]
    assert all(COMPANY_TOKENS.fullmatch(value) for value in attributes["company"])
    assert all(DATE_TOKENS.fullmatch(value) for value in attributes["date"])
    assert all(STATUS_TOKENS.fullmatch(value) for value in attributes["status"])
    [source] = items_of(doc, "sources")
    assert source["data-date"] == ""                  # a date that is not YYYY, YYYY-MM or YYYY-MM-DD is undated
    for filter_value in re.findall(r'<option value="([^"]*)"', doc):
        assert re.fullmatch(r"all|c[0-9]+|other|none|confirmed|single_source|uncertain|open|captive|disagree|not_stated"
                            r"|[0-9]{4}(-[0-9]{2})?", filter_value), filter_value


def test_every_filter_bar_says_how_many_it_hides(tmp_path):
    _, doc = grouped_page(tmp_path)
    bars = find(doc, "form", **{"class": "filters"})
    assert [bar["data-list"] for bar in bars] == ["facts", "projects", "connections", "sources"]
    for bar in bars:
        view = bar["data-list"]
        line = find(bar_html(doc, view), "p", **{"class": "filter-count"})[0]
        total = len(items_of(doc, view))
        assert line["data-all"] == f"Showing all {total}" and line["text"] == line["data-all"]
        assert line["data-some"] == "Showing {shown} of {n}; {hidden} hidden by the filter"
    assert [len(find(bar_html(doc, view), "select")) for view in ("facts", "projects", "connections", "sources")] == [3, 4, 3, 3]
    assert [s["name"] for s in find(bar_html(doc, "projects"), "select")] == ["company", "date", "status", "access"]
    assert [s["name"] for s in find(bar_html(doc, "facts"), "select")] == ["company", "date", "status"]
    assert all('id="' not in bar_html(doc, view) for view in ("facts", "projects", "connections", "sources"))


def bar_html(doc, view):
    start = doc.index(f'<form class="filters" data-list="{view}"')
    return doc[start:doc.index("</form>", start) + 7]


def test_a_list_with_nothing_in_it_gets_no_filter_bar(tmp_path):
    doc = html_for(ready_run(tmp_path))
    assert [bar["data-list"] for bar in find(doc, "form", **{"class": "filters"})] == ["facts", "projects", "sources"]


def options_of(doc, view, name):
    select = bar_html(doc, view)
    start = select.index(f'<select name="{name}">')
    return re.findall(r'<option value="([^"]*)">([^<]*)</option>', select[start:select.index("</select>", start)])


def test_the_company_filter_offers_each_company_then_other_then_none(tmp_path):
    run = make_run(tmp_path, companies=[{"name": "Competitor A", "other_names": [], "home": False},
                                        {"name": "Competitor B", "other_names": [], "home": False}])
    add_source(run, "Competitor A employs about 400 people. Drug maker X reports a fire. Competitor B lost a customer.")
    add_fact(run, kind="general", fields=None, source_id="S1", primary_source=True, about_company="Competitor A",
             statement="Competitor A employs about 400 people.", quote="Competitor A employs about 400 people")
    add_fact(run, kind="general", fields=None, source_id="S1", primary_source=True, statement="A fire was reported.",
             quote="Drug maker X reports a fire")
    add_fact(run, kind="general", fields=None, source_id="S1", primary_source=True, about_company="Competitor B",
             statement="Competitor B lost a customer.", quote="Competitor B lost a customer")
    add_fact(run, kind="capacity_move", source_id="S1", primary_source=True, quote="Drug maker X reports a fire",
             statement="Drug maker X adds a line.", fields={"company": "Drug maker X"})
    finish_run(run, ["F1"])
    doc = html_for(run)
    assert options_of(doc, "facts", "company") == [("all", "All"), ("c1", "Competitor A"), ("c2", "Competitor B"),
                                                   ("other", "Other companies"), ("none", "Not about one company")]
    assert options_of(doc, "facts", "status") == [("all", "All"), ("confirmed", "Confirmed"),
                                                  ("single_source", "One source only"), ("uncertain", "Uncertain")]
    assert options_of(doc, "projects", "access") == [("all", "All"), ("open", "Open to customers"),
                                                     ("captive", "For own use"), ("disagree", "Reports disagree"),
                                                     ("not_stated", "Not stated")]


def test_the_date_filter_offers_years_and_a_month_range(tmp_path):
    _, doc = grouped_page(tmp_path)
    assert options_of(doc, "facts", "date") == [("all", "All dates"), ("2026", "2026")]
    assert "<optgroup" not in doc
    for view in ("facts", "projects", "connections", "sources"):
        bar = bar_html(doc, view)
        months = find(bar, "input", type="month")
        assert [(m["name"], m["min"], m["max"]) for m in months] == [("from", "2026-03", "2026-09"), ("to", "2026-03", "2026-09")]
        # a browser without a month picker shows a text field: the hint and the pattern say what to type
        assert [(m["placeholder"], m["pattern"]) for m in months] == [("YYYY-MM", "[0-9]{4}-[0-9]{2}")] * 2
        assert find(bar, "p", **{"class": "filter-count"})[0]["data-reversed"] == "From is after To."
        assert re.findall(r'<span class="filter-label">([^<]*)</span> <input', bar) == ["From", "To"]
    assert options_of(doc, "sources", "date") == options_of(doc, "projects", "date")      # one list for every bar


def test_a_company_page_is_the_report_filtered(tmp_path):
    run, doc = grouped_page(tmp_path)
    model = build_model(run, LENSES)
    heads = find(doc, "section", **{"class": "company-head"})
    assert [head["data-company-head"] for head in heads] == [entry["key"] for entry in model["companies"]
                                                             if entry["key"] not in ("other", "none")]
    assert all("hidden" in head for head in heads)                                  # shown only by the script
    for entry in model["companies"]:
        if entry["key"] in ("other", "none"):
            continue
        start = doc.index(f'data-company-head="{entry["key"]}"')
        head = doc[start:doc.index("</section>", start)]
        answer = entry["core_answer"]
        if answer is None:
            assert "answer-bar" not in head
            continue
        counts = {part["class"].split()[-1]: int(part["text"].split(":")[-1]) for part in find(head, "span", **{"class": "answer-part"})
                  if "title" in part}
        assert counts == {key: answer[key] for key in ("open", "captive", "disagree", "not_stated") if answer[key]}
        assert f'{answer["total"]} project' in find(head, "p", **{"class": "answer-total"})[0]["text"]
        assert find(head, "button", **{"data-company-back": ""}) and "Back to the full report" in head
        assert not any(f"<{tag}" in head for tag in ("details", "tr", "article"))      # no fact, project or source
        assert not re.findall(r'\bid="', head) and "data-company=" not in head
    # every element that carries a company stands in a view (or is a key message), once, and the heads hold none
    outside = re.sub(r"<section class=\"view.*</main>", "", doc, flags=re.S)
    assert re.findall(r'data-company="[^"]*"', outside) and all(
        'class="message-item"' in tag for tag in re.findall(r'<[^>]*\bdata-company="[^"]*"[^>]*>', outside))
    ids = re.findall(r'\bid="([^"]+)"', doc)
    assert len(ids) == len(set(ids))
    cards = {fact["id"]: fact for fact in model["facts"]}
    for card in items_of(doc, "facts"):
        assert card["data-status"] == cards[card["id"]]["shown_status"]
        assert card["data-company"] == cards[card["id"]]["company"]["key"]
    assert [m["data-company"] for m in find(doc, "div", **{"class": "message-item"})] == \
        [" ".join(m["companies"]) or "none" for m in model["messages"]]
    assert doc.count('class="projects-more"') == 1 and all("data-company" not in tag for tag in
                                                           re.findall(r'<div class="projects-more"[^>]*>', doc))


def test_the_buttons_and_the_script_make_company_mode_work_without_a_second_copy_of_anything():
    assert "data-company-page" in JS and "data-filter-company" in JS and "data-company-back" in JS
    assert JS.count("preventDefault") >= 3 and "company-mode" in JS and "filtered-out" in JS
    assert '"filtered-out"' in JS and "hidden" in JS and "textContent" in JS


def rules(css):
    """(media text, selector, body) for every rule of the style sheet, the rules inside @media blocks with theirs."""
    found, position = [], 0
    pattern = re.compile(r"@media([^{]*)\{|([^{}@]+)\{([^}]*)\}|\}")
    stack = []
    for match in pattern.finditer(re.sub(r"/\*.*?\*/", "", css, flags=re.S)):
        if match.group(1) is not None:
            stack.append(match.group(1).strip())
        elif match.group(2) is not None:
            found.append((" and ".join(stack), match.group(2).strip(), match.group(3)))
        elif stack:
            stack.pop()
    return found


def test_no_script_and_print_show_the_whole_report():
    all_rules = rules(CSS)
    hiding = [(media, selector) for media, selector, body in all_rules if "display:none" in body.replace(" ", "")]
    for media, selector in hiding:
        for name in (".company-head", ".filter-count"):
            assert name not in selector or selector.startswith("html:not(.js)"), (media, selector)
        if ".filters" in selector:
            assert selector.startswith("html:not(.js)") or media == "print", (media, selector)
        if ".filtered-out" in selector:
            assert media == "screen" or (media == "print" and selector.startswith("html.company-mode")), (media, selector)
    assert ("", "html:not(.js) .filters, html:not(.js) .company-head, html:not(.js) .filter-count") in hiding
    assert ("screen", ".filtered-out") in hiding
    assert ("print", "html.company-mode .filtered-out") in hiding
    # printing without a company page shows every view; with one, only the views that page shows
    printed = [selector for media, selector, body in all_rules if media == "print" and "display:block" in body.replace(" ", "")]
    assert any(selector.startswith("html.js:not(.company-mode) .view") for selector in printed)
    assert not any(selector.strip() == "html.js .view" for selector in printed)
    assert "html.js   " not in CSS and "html.js .tabs" in CSS
    assert any(media == "print" and "#companies" in selector for media, selector in hiding)
    assert any(media == "" and selector.startswith("html.company-mode") and "main" in selector
               for media, selector, body in all_rules if "flex" in body)


def test_the_script_and_style_still_carry_no_model_text_with_filters_and_heads(tmp_path):
    _, doc = grouped_page(tmp_path)
    code = "".join(re.findall(r"<(?:script|style)>.*?</(?:script|style)>", doc, re.S))
    for name in ("Competitor A", "Competitor B", "Plant North", "Trade Journal", "Example Pharma", "Showing"):
        assert name not in code


# --- thousands separators on counts ---

def big_answer_model():
    """A model whose answer and one company's answer have counts above 999."""
    model = empty_model()
    answer = {"open": 1234, "captive": 5, "disagree": 0, "not_stated": 0, "total": 1239, "outside": 2345}
    model["core_answer"] = answer
    model["companies"] = [{"key": "a", "name": "Competitor A", "home": False, "facts": 1, "core_answer": dict(answer)},
                          {"key": "b", "name": "Competitor B", "home": False, "facts": 1500, "core_answer": None}]
    return model


def test_the_html_answer_counts_have_thousands_separators():
    answer = find(render_html(big_answer_model()), "section", id="answer")[0]["text"]
    assert "1,234" in answer and "1,239 projects" in answer and "2,345 more moves" in answer
    assert "1234" not in answer and "2345" not in answer


def test_the_markdown_answer_and_company_counts_have_thousands_separators():
    md = render_markdown(big_answer_model())
    assert "Open to customers: 1,234" in md and "1,239 projects" in md and "2,345 more moves" in md
    assert "Competitor A**: 1,239 projects; Open to customers: 1,234" in md
    assert "Competitor B**: 1,500 facts" in md
    assert "1234" not in md and "2345" not in md and "1500" not in md


# --- the memo layout of a screening run (design 2026-11-17) ---------------------------------------

MEMO_TEXT = ("Example Robotics raised 12 million euros in a seed round led by Investor Q. "
             "The founders previously built and sold a logistics software company in 2019.")


def _memo_message(message_id, text, part=None):
    message = {"id": message_id, "text": text, "confidence": "medium",
               "chain": [{"kind": "fact", "text": "A fact.", "fact_ids": ["F1"], "lens_id": None},
                         {"kind": "conclusion", "text": "A conclusion.", "fact_ids": [], "lens_id": None}],
               "counter_view": "It may not hold.", "would_change": "A contrary report.",
               "outside_view": {"text": "None found: no comparison class in this run.", "fact_ids": []}}
    if part:
        message["memo_part"] = part
    return message


def screening_run(tmp_path, screening=True):
    run = make_run(tmp_path, question="What would have to be true to invest in Example Robotics?",
                   screening=screening)
    add_source(run, MEMO_TEXT, publisher="Example Robotics")
    general = proposal(kind="general", about_company="Example Robotics", primary_source=True,
                       statement="Example Robotics raised 12 million euros in a seed round.",
                       quote="raised 12 million euros in a seed round led by Investor Q")
    general.pop("fields")
    store.new_fact(run, general)
    verify.check_quotes(run)
    verify.record_support(run, "F1", True, "support-checker", "")
    verify.settle(run)
    analysis = minimal_analysis(fact_ids=["F1"])
    analysis["messages"] = [_memo_message("M1", "The team has sold a company before.", "team"),
                            _memo_message("M2", "The seed round is large for the stage.", "market"),
                            _memo_message("M3", "An untagged finding.")]
    analysis["not_found"] = ["Whether pilot customers pay: no source states it."]
    store.write_analysis(run, analysis)
    return run


def test_a_screening_report_reads_as_a_memo(tmp_path):
    page = html_for(screening_run(tmp_path))
    assert "Screening memo" in page and "It does not make one." in page
    order = [page.index(f"<h3>{name}</h3>") for name in ("Market", "Team", "Other findings")]
    assert order == sorted(order)
    assert page.index("The seed round is large") > order[0] and page.index("The team has sold") > order[1]
    assert "<h3>Company</h3>" not in page   # a part with no message is left out
    assert "What would have to be true</button>" in page
    assert "Open questions for the partner meeting" in page
    tabs = [e["data-view"] for e in find(page, "button") if "data-view" in e]
    assert "projects" not in tabs and "timeline" not in tabs and 'id="answer"' not in page
    shown = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", page, flags=re.S)
    assert "capacity" not in shown.lower()


def test_a_strategy_report_keeps_its_own_layout(tmp_path):
    page = html_for(screening_run(tmp_path, screening=False))
    for label in ("Screening memo", "Other findings", "What would have to be true</button>",
                  "Open questions for the partner meeting"):
        assert label not in page
    assert page.index("The team has sold") < page.index("The seed round is large") < page.index("An untagged finding")
    tabs = [e["data-view"] for e in find(page, "button") if "data-view" in e]
    assert "projects" in tabs and "timeline" in tabs


def test_a_memo_with_a_capacity_move_shows_no_answer_bar_and_no_link_to_a_removed_view(tmp_path):
    """Review 2026-11-17: a move in a screening run brought back the answer bar, whose links opened a view the memo has not."""
    run = screening_run(tmp_path)
    add_fact(run, source_id="S1", primary_source=True, quote="raised 12 million euros in a seed round")
    verify.check_quotes(run)
    verify.record_support(run, "F2", True, "support-checker", "")
    verify.settle(run)
    page = html_for(run)
    assert 'id="answer"' not in page
    assert 'href="#view-projects"' not in page and 'data-view="projects"' not in page
