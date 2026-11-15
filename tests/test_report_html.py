import json
import re
from pathlib import Path

from radar import store
from radar.cli import main
from radar.report.build import build_report
from radar.report.html import esc, render_html
from radar.report.markdown import render_markdown
from radar.report.model import build_model, load_labels
from helpers import add_fact, add_source, find, finish_run, make_run, minimal_analysis
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
            "status_line": {"confirmed": 0, "uncertain": 0, "rejected": 0, "sources": 0, "not_accessible": 0},
            "messages": [], "facts": [], "rejected": [], "competitors": [], "demand_signals": [],
            "decision_options": None, "watch_items": [], "audit_flags": [], "not_found": [], "contradictions": [],
            "lenses": [], "sources": [], "how_made": {"search_log": [], "excluded": [], "checkpoints": []},
            "changes": None, "assumptions": [], "scenarios": [], "predictions": [], "calculations": [],
            "compliance": labels["compliance_public"], "built_on": "2026-11-12"}


# --- the structure the brief fixes ---

def test_views_and_tabs_match(tmp_path):
    doc = html_for(ready_run(tmp_path))
    views = [e["id"] for e in find(doc, "section", **{"class": "view"})]
    tabs = [e["data-view"] for e in find(doc, "button") if "data-view" in e]
    assert views == ["view-" + t for t in tabs]
    assert tabs[:3] == ["summary", "facts", "competitors"] and "changes" not in tabs

def test_all_views_in_order_and_the_first_is_on(tmp_path):
    doc = html_for(ready_run(tmp_path))
    tabs = [e["data-view"] for e in find(doc, "button") if "data-view" in e]
    assert tabs == ["summary", "facts", "competitors", "timeline", "scenarios", "options", "checks",
                    "thinking", "sources", "how"]
    assert [e["id"] for e in find(doc, "section", **{"class": "view on"})] == ["view-summary"]
    assert [b["data-view"] for b in find(doc, "button", **{"class": "on"})] == ["summary"]

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
        [("P1", "Competitor A starts both lines, by 2028-12-31: 65% (likely)")]
    assert "The company reports the lines as operating" in find(doc, "section", id="view-scenarios")[0]["text"]

def test_competitors_table_puts_the_home_company_first_and_labels_it(tmp_path):
    run = make_run(tmp_path, home_company="Own Plant")
    add_source(run, "The expansion adds two high-speed syringe lines for customers, starting in 2028.")
    add_source(run, "Own Plant will add a third filling line at Plant South in 2027, the company said.")
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    add_fact(run, source_id="S2", primary_source=True, quote="will add a third filling line at Plant South in 2027",
             fields={"company": "Own Plant", "site": "Plant South", "planned_start": "2027", "access": "captive"})
    finish_run(run, ["F1"])
    doc = html_for(run)
    rows = find(doc, "tr", **{"class": "move"})
    assert len(rows) == 2
    assert rows[0]["text"].startswith("Own Plant") and "own company" in rows[0]["text"]
    assert "Plant South" in rows[0]["text"] and "Captive" in rows[0]["text"] and "2027" in rows[0]["text"]
    assert rows[1]["text"].startswith("Competitor A") and "own company" not in rows[1]["text"]
    headings = [h["text"] for h in find(doc, "th")]
    for heading in ("Company", "What", "Site", "Country", "Stage", "Start", "Access", "Status", "Fact"):
        assert heading in headings, heading
    assert "Announced" in rows[1]["text"] and "Exampleland" in rows[1]["text"] and "F1" in rows[1]["text"]

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
    rows = find(section, "tr")[1:]
    assert [row["text"].split(" ")[0] for row in rows] == ["Early", "Late"]            # one row per dated company
    assert [(a["href"], a["class"]) for a in find(section, "a", **{"class": "bar"})] == \
        [("#F2", "bar open"), ("#F1", "bar open")]                                      # in the column of their year
    assert "Start not stated" in section and "Undated Co" in find(section, "ul", **{"class": "undated"})[0]["text"]

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
    competitors = find(doc, "section", id="view-competitors")[0]["text"]
    assert "Orders for syringes are rising" in competitors and "Moves announced: 1" in competitors
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

def test_a_model_with_nothing_in_it_still_renders():
    doc = render_html(empty_model())
    summary = find(doc, "section", id="view-summary")[0]["text"]
    assert "No fact could be confirmed from the sources that were read." in summary
    assert len(find(doc, "section", **{"class": "view"})) == 10

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
    assert set(f2) == {"F2UncertainInternal document"}                    # link text, then the two pills
    f1 = [r["text"] for r in refs if r["text"].startswith("F1")]
    assert f1 and set(f1) == {"F1"}                                       # public and confirmed: nothing added
    fact = [f for f in find(doc, "details", **{"class": "fact"}) if f["id"] == "F2"][0]
    assert "Uncertain" in fact["text"] and "Internal document" in fact["text"]

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
    comp = md.split("## Competitors")[1].split("\n## ")[0]
    line = next(l for l in comp.splitlines() if "The line runs two shifts." in l)
    assert "F2 (Uncertain, Internal document)" in line
    public = next(l for l in comp.splitlines() if "Competitor A will add" in l)
    assert "Uncertain" not in public and "Internal" not in public

def test_markdown_chain_step_references_name_uncertain_and_non_public_facts(tmp_path):
    md = render_markdown(build_model(private_run_with_uncertain_fact(tmp_path), LENSES))
    chain = md.split("## Thinking behind this analysis")[1].split("\n## ")[0]
    step = next(l for l in chain.splitlines() if l.startswith("1. Fact:"))
    assert "F1," in step and "F2 (Uncertain, Internal document)" in step and "F1 (" not in step
    summary = md.split("## Summary")[1].split("\n## ")[0]
    assert "F2 (Uncertain, Internal document)" in summary and "F1 (" not in summary


# --- fix round 1: quotes on source pages name their fact ---

def _article(doc, source_id):
    return doc.split(f'<article class="source" id="{source_id}">')[1].split("</article>")[0]

def test_source_page_links_each_quote_to_its_fact(tmp_path):
    article = _article(html_for(ready_run(tmp_path)), "S1")
    assert '<a href="#F1" data-view="facts">F1</a>' in article
    assert [p["text"] for p in find(article, "p", **{"class": "quote-fact"})] == ["Fact F1"]

def test_source_page_quote_of_an_uncertain_non_public_fact_carries_both_labels(tmp_path):
    article = _article(html_for(private_run_with_uncertain_fact(tmp_path)), "S2")
    assert '<a href="#F2" data-view="facts">F2</a>' in article
    assert [r["text"] for r in find(article, "span", **{"class": "factref"})] == ["F2UncertainInternal document"]

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
    view = find(doc, "section", id="view-competitors")[0]
    blocks = find(doc, "div", **{"class": "baseline"})
    assert len(blocks) == 2
    first, second = blocks[0]["text"], blocks[1]["text"]
    assert first.startswith("Competitor A") and BASELINE_HEADING in first
    assert "Competitor A runs two plants with about 400 staff." in first and "F4" in first
    assert second.startswith("Competitor C") and "Competitor C runs one plant and invested 12 million last year." in second
    assert BASELINE_HEADING in view["text"]
    rows = find(doc, "tr", **{"class": "move"})
    assert len(rows) == 1                                  # a company without a move adds no empty table row


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
    assert "<script>alert(1)</script>" not in doc and "&lt;script&gt;alert(1)&lt;/script&gt;" in doc
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
    return html.split(f'<details class="fact" id="{fact_id}">')[1].split("</details>")[0]


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
