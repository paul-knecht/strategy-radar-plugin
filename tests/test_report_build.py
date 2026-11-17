import json
import re
from datetime import datetime, timezone
import pytest
from html import escape as html_escape
from pathlib import Path
from radar.report.build import build_report, GateRefused
from radar.report.markdown import esc, render_markdown
from radar.report.model import build_model, load_labels, probability_word
from radar import demo, verify, store
from radar.cli import main
from helpers import (PERMIT_TEXT, add_early_signal, find, lens_folder_with_level, make_run, add_source, add_fact,
                     finish_run, minimal_analysis)

LENSES = demo.LENSES
TEXT = "The expansion adds two high-speed syringe lines for customers, starting in 2028."

def ready_run(tmp_path, analysis=None, **run_over):
    run = make_run(tmp_path, **run_over)
    add_source(run, TEXT, publisher="Competitor A")
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    add_fact(run, source_id="S1", primary_source=True, quote="adds nine high-speed syringe lines for customers")
    verify.check_quotes(run)
    for f in ("F1", "F2"): verify.record_support(run, f, True, "support-checker", "")
    verify.settle(run)
    store.write_analysis(run, analysis or minimal_analysis(fact_ids=["F1"], lens_id="firm-boundaries"))
    store.record_checkpoint(run, "lenses", "test", "use firm-boundaries")
    store.record_checkpoint(run, "final_report", "test", "build it")
    return run

REPORT_TEXT = ("Competitor A runs two plants and employs about 400 people. "
               "Competitor C operates one plant and invested 12 million in the last year.")

def early_signal_run(tmp_path, baselines=True, **run_over):
    """ready_run (F1 confirmed, F2 rejected) plus F3, an early signal from a permit (S2), and two baseline facts from
    an annual report (S3): F4 for Competitor A and F5 for Competitor C, who has no move."""
    run = ready_run(tmp_path, **run_over)
    add_source(run, PERMIT_TEXT, type="permit", publisher="Planning Office", title="Planning application")
    add_early_signal(run, source_id="S2")
    add_source(run, REPORT_TEXT, type="annual_report", publisher="Competitor A", title="Annual report")
    add_fact(run, kind="general", fields=None, source_id="S3", primary_source=True,
             statement="Competitor A runs two plants with about 400 staff.",
             quote="runs two plants and employs about 400 people")
    add_fact(run, kind="general", fields=None, source_id="S3", primary_source=True,
             statement="Competitor C runs one plant and invested 12 million last year.",
             quote="operates one plant and invested 12 million in the last year")
    verify.check_quotes(run)
    for fact_id in ("F3", "F4", "F5"): verify.record_support(run, fact_id, True, "support-checker", "")
    verify.settle(run)
    analysis = minimal_analysis(fact_ids=["F1"], lens_id="firm-boundaries")
    if baselines:
        analysis["baselines"] = [
            {"company": "Competitor A", "fact_ids": ["F4"]},
            {"company": "Competitor C", "fact_ids": ["F5"]}]
    store.write_analysis(run, analysis)
    return run

def test_build_writes_markdown_with_required_parts(tmp_path):
    run = ready_run(tmp_path)
    paths = build_report(run, LENSES)
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    assert paths[0] == run / "report" / "report.md"
    assert "This report uses public sources only. It is not insight into any company's internals." in md
    assert "1 fact, all quotes checked" in md and "1 proposed fact rejected" in md
    assert "adds two high-speed syringe lines for customers" in md        # the quote
    assert "## What we could not confirm" in md                            # F2 is listed with its reason
    assert "The quote was not found in the saved source." in md.split("## What we could not confirm")[1]
    assert "adds nine high-speed" in md.split("## What we could not confirm")[1]
    assert "Where firms draw their boundaries" in md.split("## Thinking behind this analysis")[1]
    assert "Recorded test answer" in md.split("## How this report was made")[1]
    assert md.index("## Key messages") < md.index("## What the sources say") < md.index("## Sources")

def test_build_refuses_when_gate_is_closed(tmp_path):
    run = ready_run(tmp_path, analysis=minimal_analysis(fact_ids=["F1", "F2"]))
    with pytest.raises(GateRefused) as err:
        build_report(run, LENSES)
    assert any(p.message == "rests on fact F2 with status rejected" for p in err.value.problems)
    assert not (run / "report" / "report.md").exists()

def test_run_with_no_usable_facts_still_builds(tmp_path):
    run = make_run(tmp_path)
    add_source(run, TEXT)
    add_fact(run, source_id="S1", primary_source=True, quote="adds nine high-speed syringe lines for customers")
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    empty = minimal_analysis(fact_ids=[]); empty["messages"] = []
    store.write_analysis(run, empty)
    store.record_checkpoint(run, "lenses", "test", "none"); store.record_checkpoint(run, "final_report", "test", "ok")
    build_report(run, LENSES)
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    assert "No fact could be confirmed from the sources that were read." in md

def test_private_run_is_confidential_and_not_publishable(tmp_path):
    run = ready_run(tmp_path, mode="private", acknowledged=True)
    add_source(run, "Internal capacity review. " * 20, data_class="internal", url="internal capacity review")
    build_report(run, LENSES)
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    assert "Confidential. This report contains non-public information. Do not share or publish it." in md
    assert "Includes non-public sources" in md and "Public sources only" not in md
    assert "It is not insight into any company's internals." not in md
    assert "This report combines public sources with non-public material supplied by its user." in md
    with pytest.raises(GateRefused):
        build_report(run, LENSES, publishable=True)

def test_judgement_sections_and_totals_appear(tmp_path):
    analysis = minimal_analysis(fact_ids=["F1"], lens_id="firm-boundaries")
    analysis["assumptions"] = [
        {"id": "A1", "text": "Demand keeps growing", "support": "partial", "if_wrong": "Open capacity stays unused", "fact_ids": []},
        {"id": "A2", "text": "Announced plants open on time", "support": "weak", "if_wrong": "The shortage lasts longer", "fact_ids": ["F1"]}]
    analysis["scenarios"] = [
        {"id": "SC1", "name": "Tight market", "description": "Demand outruns supply", "assumption_ids": ["A1"],
         "signposts": [{"text": "Lead times rise", "fact_ids": []}]},
        {"id": "SC2", "name": "Oversupply", "description": "Supply outruns demand", "assumption_ids": ["A2"],
         "signposts": [{"text": "Price cuts are announced", "fact_ids": []}]}]
    analysis["predictions"] = [{"id": "P1", "message_id": "M1", "statement": "Competitor A starts both lines",
                                "by": "2028-12-31", "resolves_when": "The company reports the lines as operating", "probability": 65}]
    analysis["calculations"] = [{"id": "C1", "label": "Moves announced", "operation": "count", "unit": None,
                                 "fact_ids": ["F1"], "of_fact_ids": [], "result": "1"}]
    run = ready_run(tmp_path, analysis=analysis)
    build_report(run, LENSES)
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    scen = md.split("## Scenarios and assumptions")[1].split("\n## ")[0]
    assert scen.strip().startswith("Judgement, not fact")
    assert "Tight market" in scen and "Lead times rise" in scen and "Weakly supported" in scen
    pred = md.split("## Predictions")[1].split("\n## ")[0]
    assert "Competitor A starts both lines, by 2028-12-31: 65% (likely)" in pred
    assert "Moves announced: 1" in md.split("## Projects")[1].split("\n## ")[0]
    how = md.split("## How this report was made")[1]
    assert "All sources in this report are publicly available." in how and "very likely" in how

def test_illustrative_run_carries_the_banner(tmp_path):
    run = ready_run(tmp_path, illustrative=True)
    build_report(run, LENSES)
    assert BANNER in \
        (run / "report" / "report.md").read_text(encoding="utf-8")


# --- beyond the brief's list: escaping, links, model-only purity, the scale, the command ---

def _edit_source(run, source_id, **changes):
    source = store.read_sources(run)[source_id]
    source.update(changes)
    store.write_source(run, source)

def test_source_text_cannot_form_links_or_markup(tmp_path):
    run = ready_run(tmp_path)
    _edit_source(run, "S1", title="[click](http://evil.example) <b>bold</b> *x* `y` a|b",
                 publisher="Pub_lisher\nsecond line")
    build_report(run, LENSES)
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    assert "[click](" not in md and "<b>" not in md
    assert r"\[click\](http\://evil.example)" in md       # also defused for auto-linking viewers
    assert r"\<b\>bold\</b\>" in md and r"\*x\*" in md and r"\`y\`" in md and r"a\|b" in md
    assert r"Pub\_lisher second line" in md                  # line breaks collapse to a space

def test_quote_with_markdown_and_html_is_shown_as_text(tmp_path):
    run = make_run(tmp_path)
    text = "The firm said: <script>alert(1)</script> and [more](http://evil.example) adds two lines."
    add_source(run, text)
    add_fact(run, source_id="S1", primary_source=True, quote=text, statement="# Heading attempt")
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    store.write_analysis(run, minimal_analysis(["F1"]))
    for name in store.CHECKPOINTS: store.record_checkpoint(run, name, "test", "ok")
    build_report(run, LENSES)
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    assert "<script>" not in md and "[more](" not in md
    assert r"\<script\>alert(1)\</script\>" in md
    assert "\n# Heading attempt" not in md and "- # Heading attempt" not in md

def test_only_http_links_become_links(tmp_path):
    run = ready_run(tmp_path)
    build_report(run, LENSES)
    assert "(<https://s1.example.com/S1>)" in (run / "report" / "report.md").read_text(encoding="utf-8")
    _edit_source(run, "S1", url="javascript:alert(1)")
    build_report(run, LENSES)
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    assert "](javascript" not in md and "javascript:alert" in md
    _edit_source(run, "S1", url="https://example.com/a b>c")
    build_report(run, LENSES)
    assert "](<https://example.com/a" not in (run / "report" / "report.md").read_text(encoding="utf-8")

def test_model_and_markdown_write_nothing(tmp_path):
    run = ready_run(tmp_path)
    before = sorted(p.relative_to(run).as_posix() for p in run.rglob("*"))
    render_markdown(build_model(run, LENSES))
    assert sorted(p.relative_to(run).as_posix() for p in run.rglob("*")) == before

def test_probability_word_scale():
    labels = load_labels()
    cases = {100: "prob_95", 95: "prob_95", 94: "prob_80", 80: "prob_80", 79: "prob_60", 60: "prob_60",
             59: "prob_40", 40: "prob_40", 39: "prob_20", 20: "prob_20", 19: "prob_5", 5: "prob_5",
             4: "prob_0", 0: "prob_0"}
    for probability, key in cases.items():
        assert probability_word(probability, labels) == labels[key], probability

def test_labels_are_loaded_from_the_fixed_file():
    labels = load_labels()
    assert labels["public_only"] == "Public sources only"
    assert labels["internal_questions"] == "Questions only the company can answer"

def test_markdown_lists_what_each_fact_and_move_says(tmp_path):
    run = ready_run(tmp_path, home_company="Competitor A")
    build_report(run, LENSES)
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    facts = md.split("## What the sources say")[1].split("\n## ")[0]
    assert "S1, Confirmed" in facts and "Source S1" in facts and "Competitor A" in facts
    comp = md.split("## Projects")[1].split("\n## ")[0]
    assert "Competitor A (own company)" in comp and "Announced" in comp

def test_build_report_command_prints_json(tmp_path, capsys):
    run = ready_run(tmp_path)
    assert main(["build-report", "--run", str(run), "--lenses", str(LENSES)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"built": ["report/report.md", "report/report.html", "report/facts.csv", "report/sources.csv"]}
    assert (run / "report" / "report.md").exists()

def test_build_report_command_reports_gate_problems(tmp_path, capsys):
    run = ready_run(tmp_path, analysis=minimal_analysis(fact_ids=["F1", "F2"]))
    assert main(["build-report", "--run", str(run), "--lenses", str(LENSES)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["built"] == []
    assert {"file": "analysis.json", "field": "messages[0].chain[0].fact_ids",
            "message": "rests on fact F2 with status rejected"} in out["problems"]
    assert not (run / "report" / "report.md").exists()

def test_build_report_command_publishable_refuses_private_run(tmp_path, capsys):
    run = ready_run(tmp_path, mode="private", acknowledged=True)
    add_source(run, "Internal capacity review. " * 20, data_class="internal", url="internal capacity review")
    assert main(["build-report", "--run", str(run), "--lenses", str(LENSES), "--publishable"]) == 1
    assert json.loads(capsys.readouterr().out)["built"] == []

def test_uncertain_and_non_public_material_is_named(tmp_path):
    run = ready_run(tmp_path, mode="private", acknowledged=True)
    add_source(run, "Internal capacity review says the line will run two shifts from 2027.",
               data_class="internal", url="internal capacity review", saved_by="hand", publisher="Own plant")
    add_fact(run, source_id="S2", primary_source=False, quote="the line will run two shifts from 2027",
             statement="The line runs two shifts.", fields={"company": "Own plant"})
    verify.check_quotes(run); verify.record_support(run, "F3", True, "support-checker", ""); verify.settle(run)
    for name in store.CHECKPOINTS: store.record_checkpoint(run, name, "test", "again")
    build_report(run, LENSES)
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    assert "1 from one source only · 0 marked uncertain" in md and "2 facts, all quotes checked" in md
    facts = md.split("## What the sources say")[1].split("\n## ")[0]
    line = next(l for l in facts.splitlines() if l.startswith("- Own plant: The line runs two shifts."))
    assert "(Internal document)" in line and "S2, One source only" in line
    sources = md.split("## Sources")[1]
    assert "Saved by hand" in sources and "Supplied by: the tester" in sources
    assert "Basis for use: own company document" in sources

def test_watch_items_and_lens_details_are_shown(tmp_path):
    analysis = minimal_analysis(["F1"], lens_id="firm-boundaries")
    analysis["watch_items"] = [{"text": "Plant North permits", "trigger": "A permit is refused"}]
    analysis["lens_notes"] = [{"lens_id": "firm-boundaries", "here": "Here the firm builds its own lines."}]
    run = ready_run(tmp_path, analysis=analysis)
    build_report(run, LENSES)
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    assert "### What to watch" in md and "Plant North permits — A permit is refused" in md
    thinking = md.split("## Thinking behind this analysis")[1].split("\n## ")[0]
    assert "Here the firm builds its own lines." in thinking
    assert "Has the company recently moved a step across that line?" in thinking
    assert "Illustrative reference, not a real work, Reference confirmed" in thinking


def test_every_lens_level_has_a_report_label():
    labels = load_labels()
    for level in store.LENS_LEVELS:
        assert f"level_{level}" in labels, f"no report label for the lens level {level}"


def test_the_report_names_the_course_slides_level(tmp_path):
    lenses = lens_folder_with_level(tmp_path / "lenses", "course_slides")
    analysis = minimal_analysis(["F1"], lens_id="firm-boundaries")
    analysis["lens_notes"] = [{"lens_id": "firm-boundaries", "here": "Here the firm builds its own lines."}]
    run = ready_run(tmp_path, analysis=analysis)
    build_report(run, lenses)
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    thinking = md.split("## Thinking behind this analysis")[1].split("\n## ")[0]
    assert "Illustrative reference, not a real work, Course slides" in thinking
    assert "Reference confirmed" not in thinking
    html = (run / "report" / "report.html").read_text(encoding="utf-8")
    card = find(html, "article", **{"class": "lens-card"})[0]
    assert "Course slides" in card["text"] and "Reference confirmed" not in card["text"]


def test_the_report_names_the_secondary_source_level_and_what_the_source_is_about(tmp_path):
    folder = lens_folder_with_level(tmp_path / "lenses", "secondary_source_read")
    path = folder / "firm-boundaries.json"
    lens = json.loads(path.read_text(encoding="utf-8"))
    lens["originals"][0].update({"about": "An invented work on where firms stop", "link": "https://www.example.com/a-survey"})
    path.write_text(json.dumps(lens), encoding="utf-8")
    analysis = minimal_analysis(["F1"], lens_id="firm-boundaries")
    analysis["lens_notes"] = [{"lens_id": "firm-boundaries", "here": "Here the firm builds its own lines."}]
    run = ready_run(tmp_path, analysis=analysis)
    build_report(run, folder)
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    thinking = md.split("## Thinking behind this analysis")[1].split("\n## ")[0]
    assert "Illustrative reference, not a real work, about An invented work on where firms stop, Secondary source read" in thinking
    html = (run / "report" / "report.html").read_text(encoding="utf-8")
    card = find(html, "article", **{"class": "lens-card"})[0]
    assert "Secondary source read" in card["text"] and "An invented work on where firms stop" in card["text"]
    assert "Reference confirmed" not in card["text"]


# --- final fix C1: an invented supporting quote never reaches a report as a quote from its source ---

def test_an_invented_supporting_quote_appears_only_under_what_we_could_not_confirm(tmp_path):
    invented = "five new syringe lines will open in 2031"
    run = make_run(tmp_path)
    add_source(run, "The expansion adds two high-speed syringe lines for customers, starting in 2028.")
    add_source(run, "Competitor A confirmed two new syringe lines will open in 2028, the paper reported.",
               publisher="Trade Paper")
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    add_fact(run, source_id="S1", primary_source=True, quote="two high-speed syringe lines for customers, starting in 2028",
             statement="Competitor A starts in 2028.", supporting=[{"source_id": "S2", "quote": invented}])
    finish_run(run, ["F1"])
    assert store.read_facts(run)["F2"]["status"] == "rejected"
    model = build_model(run, LENSES)
    assert [source["quotes"] for source in model["sources"] if source["id"] == "S2"] == [[]]
    build_report(run, LENSES)
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    head, rest = md.split("## What we could not confirm")
    assert invented not in head and invented not in rest.split("\n## ", 1)[1]
    html = (run / "report" / "report.html").read_text(encoding="utf-8")
    outside = re.sub(r'<ul class="rejected">.*?</ul>', "", html, flags=re.DOTALL)
    assert invented not in outside



# --- final fix I5, I9, S3 and I3: labels instead of engine words, one way to refer to a fact -------

from datetime import datetime, timezone
from radar.report.model import field_label


def built(run, **kwargs):
    build_report(run, LENSES, **kwargs)
    return ((run / "report" / "report.md").read_text(encoding="utf-8"),
            (run / "report" / "report.html").read_text(encoding="utf-8"))


def section(md, heading):
    return md.split(f"## {heading}")[1].split("\n## ")[0]


def test_the_report_states_the_date_it_was_built(tmp_path):
    md, html = built(ready_run(tmp_path), now=datetime(2026, 11, 20, 23, 30, tzinfo=timezone.utc))
    assert "Report built on 2026-11-20" in md and "Report built on 2026-11-20" in html


def test_statuses_reasons_steps_and_checkpoints_are_labels(tmp_path):
    md, _ = built(ready_run(tmp_path))
    facts = section(md, "What the sources say")
    assert "S1, Confirmed" in facts and ", confirmed" not in facts
    rejected = section(md, "What we could not confirm")
    assert "Rejected: The quote was not found in the saved source." in rejected and "not_found" not in rejected
    thinking = section(md, "Thinking behind this analysis")
    assert "1. Fact: " in thinking and "2. Reasoning: " in thinking and "3. Conclusion: " in thinking
    how = section(md, "How this report was made")
    assert "- Before choosing lenses: " in how and "- Before the final report: " in how
    assert "final_report" not in how and "- lenses:" not in how


def test_an_uncertain_reason_is_shown_as_written_and_escaped(tmp_path):
    run = make_run(tmp_path)
    add_source(run, TEXT)
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers",
             certainty="tentative", tentative_reason="one <b>unnamed</b> source")
    add_fact(run, source_id="S1", primary_source=False, quote="two high-speed syringe lines for customers, starting in 2028",
             statement="Production starts in 2028.")
    finish_run(run, ["F1"])
    md, html = built(run)
    facts = section(md, "What the sources say")
    assert "Uncertain, one \\<b\\>unnamed\\</b\\> source" in facts
    assert "One source only, single source that is not a primary source" in facts
    assert "one &lt;b&gt;unnamed&lt;/b&gt; source" in html and "<b>unnamed" not in html


def test_a_rejection_shows_the_checkers_note_and_a_withdrawal_its_reason(tmp_path):
    run = make_run(tmp_path)
    add_source(run, TEXT)
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    add_fact(run, source_id="S1", primary_source=True, quote="two high-speed syringe lines for customers, starting in 2028",
             statement="Production starts in 2027.")
    add_fact(run, source_id="S1", primary_source=True, quote="The expansion adds two high-speed syringe lines",
             statement="The expansion is confirmed.")
    finish_run(run, ["F1"])
    verify.record_support(run, "F2", False, "support-checker", "The quote says <2028>, the fact says 2027.")
    verify.withdraw_fact(run, "F3", "Duplicate of F1 & kept for the record")
    verify.settle(run)
    md, html = built(run)
    rejected = section(md, "What we could not confirm")
    assert "The checker judged that the quote does not support the fact." in rejected
    assert "Checker's note: The quote says \\<2028\\>, the fact says 2027." in rejected
    assert "Withdrawn by the analyst." in rejected and "Analyst's reason: Duplicate of F1 & kept for the record" in rejected
    assert "Duplicate of F1 &amp; kept for the record" in html and "The quote says &lt;2028&gt;" in html
    assert "Production starts in 2027." not in section(md, "What the sources say")
    assert "The expansion is confirmed." not in section(md, "What the sources say")


def test_access_reasons_are_labels(tmp_path):
    run = ready_run(tmp_path)
    add_source(run, "", access="not_accessible", access_reason="http_403", copy_file=None, copy_sha256=None)
    add_source(run, "", access="not_accessible", access_reason="timeout", copy_file=None, copy_sha256=None)
    md, html = built(run)
    sources = section(md, "Sources")
    assert "Not accessible: The site refused the request (403)." in sources
    assert "Not accessible: The site did not answer in time." in sources
    assert "http_403" not in md and "http_403" not in html.split("<body>")[1]


# Fix round 1 (finding 1): the words say what the program measures, not what the page holds; and a PDF is never judged
# by this rule, so the advice cannot send a page added by hand round again.
LITTLE_RUNNING_TEXT = ("The saved copy holds little running text, so the page's article may be missing. Save the page "
                       "as a PDF and add it as a file.")


def flagged_report_run(tmp_path):
    """ready_run plus S2, an invented web page saved with the note that it holds little running text."""
    run = ready_run(tmp_path)
    add_source(run, "Home\nAbout us\nNews\n", title="Competitor D news page", orig_file="copies/S2.orig.html",
               text_note="little_running_text")
    (run / "copies" / "S2.orig.html").write_text("<html><body><p>Home</p></body></html>", encoding="utf-8")
    return run


def test_a_page_with_little_running_text_carries_the_plain_sentence_in_both_reports(tmp_path):
    """Plan 2b, Task 10, change F: the flagged source is named with the sources that need attention, but it is saved,
    so it is not shown or counted as not accessible."""
    labels = load_labels()
    assert labels["text_note_little_running_text"] == LITTLE_RUNNING_TEXT
    assert labels["little_running_text"] == "Little running text" and "mostly_menu_text" not in labels
    md, html = built(flagged_report_run(tmp_path))
    s2 = section(md, "Sources").split("### S2: Competitor D news page")[1].split("\n### ")[0]
    assert f"- Little running text: {LITTLE_RUNNING_TEXT}" in s2 and "Not accessible" not in s2
    page = html.split('<article class="source" id="S2"')[1].split("</article>")[0]
    assert '<span class="pill little-running-text">Little running text</span>' in page
    assert ".pill.not-accessible, .pill.little-running-text {" in html.split("<body>")[0]   # styled as a warning
    assert f"<dt>Little running text</dt><dd>{html_escape(LITTLE_RUNNING_TEXT)}</dd>" in page
    assert "Not accessible" not in page and "menu" not in (s2 + page).lower()
    for text in (md, html):
        assert "Not accessible:" not in text and "little_running_text" not in text.split("<body>")[-1]
    s1 = html.split('<article class="source" id="S1"')[1].split("</article>")[0]
    assert "Little running text" not in s1 and LITTLE_RUNNING_TEXT.count(".") == 2   # two plain sentences


def test_field_labels_come_from_an_explicit_map_per_field():
    labels = load_labels()
    assert field_label("move_type", "new_site", labels) == "New site"
    assert field_label("stage", "operating", labels) == "Operating"
    assert field_label("delivery", "not_yet", labels) == labels["delivery_not_yet"]
    assert field_label("status", "uncertain", labels) == "Uncertain"
    assert field_label("site", "not_stated", labels) == "not_stated"          # a model value, not a label key
    assert field_label("company", "status_confirmed", labels) == "status_confirmed"
    assert field_label("move_type", "takeover", labels) == "takeover"


def test_every_reference_to_an_uncertain_non_public_fact_carries_both_labels(tmp_path):
    from test_report_html import private_run_with_uncertain_fact
    extra = {
        "demand_signals": [{"text": "Orders rise.", "fact_ids": ["F2"]}],
        "decision_options": {"question": "Build or buy?", "framing": "company", "framing_fact_ids": ["F2"],
                             "options": [{"name": "Build", "for": [{"text": "Shifts are planned.", "fact_ids": ["F2"]}],
                                          "against": [{"text": "It is slow.", "fact_ids": ["F2"]}]}],
                             "internal_questions": []},
        "contradictions": [{"text": "The two plans differ.", "fact_ids": ["F1", "F2"]}],
        "assumptions": [{"id": "A1", "text": "Shifts hold.", "support": "partial", "if_wrong": "Less output.",
                         "fact_ids": ["F2"]},
                        {"id": "A2", "text": "Demand holds.", "support": "weak", "if_wrong": "Spare lines.",
                         "fact_ids": []}],
        "scenarios": [{"id": "SC1", "name": "Tight", "description": "d", "assumption_ids": ["A1"],
                       "signposts": [{"text": "A second shift starts.", "fact_ids": ["F2"]}]},
                      {"id": "SC2", "name": "Loose", "description": "d", "assumption_ids": ["A2"],
                       "signposts": [{"text": "Orders fall.", "fact_ids": []}]}],
        "calculations": [{"id": "C1", "label": "Lines", "operation": "sum", "unit": "lines",
                          "fact_ids": ["F1", "F2"], "of_fact_ids": [], "result": "4"}],
    }
    run = private_run_with_uncertain_fact(tmp_path, extra)
    analysis = store.read_analysis(run)
    analysis["messages"][0]["outside_view"]["fact_ids"] = ["F2"]
    store.write_analysis(run, analysis)
    md, _ = built(run)
    references = re.findall(r"\bF2\b.{0,40}", md)
    assert len(references) >= 11, references
    for reference in references:
        assert reference.startswith("F2 (One source only, Internal document)"), reference
    for heading in ("Projects", "Demand signals", "Decision options", "Scenarios and assumptions",
                    "What we could not confirm", "Thinking behind this analysis", "Sources"):
        assert "F2 (One source only, Internal document)" in section(md, heading), heading


# --- early signals and baselines in the plain-text report -----------------------------------------

EARLY_NOTE = ("Early signals are hints such as building permits, job postings and regulator records. "
              "They are not announcements, and each one is marked uncertain.")


def test_the_early_signals_block_carries_its_fixed_note(tmp_path):
    md, _ = built(early_signal_run(tmp_path))
    facts = section(md, "What the sources say")
    assert "### Early signals" in facts
    block = facts.split("### Early signals")[1]
    assert block.strip().startswith(EARLY_NOTE)
    assert "A planning application names a new filling hall at Plant North." in block
    assert "F3 (Uncertain)" in block                      # the shared way to refer to an uncertain fact
    assert "an application for a new filling hall at Plant North" in block      # its quote
    assert "A planning application names" not in facts.split("### Early signals")[0]   # not among the other facts
    assert "adds two high-speed syringe lines for customers" in facts.split("### Early signals")[0]


def test_an_early_signal_from_a_non_public_source_stays_marked_in_its_block(tmp_path):
    run = ready_run(tmp_path, mode="private", acknowledged=True)
    add_source(run, PERMIT_TEXT, type="permit", data_class="internal", url="internal permit register")
    add_early_signal(run, source_id="S2")
    verify.check_quotes(run); verify.record_support(run, "F3", True, "support-checker", ""); verify.settle(run)
    md, _ = built(run)
    block = section(md, "What the sources say").split("### Early signals")[1]
    assert "F3 (Uncertain, Internal document)" in block


def test_a_run_with_only_early_signals_does_not_say_that_no_fact_was_confirmed(tmp_path):
    run = make_run(tmp_path)
    add_source(run, PERMIT_TEXT, type="permit")
    add_early_signal(run)
    empty = minimal_analysis(fact_ids=[]); empty["messages"] = []
    finish_run(run, [], analysis=empty)
    md, _ = built(run)
    facts = section(md, "What the sources say")
    assert "### Early signals" in facts and "No fact could be confirmed" not in facts


def test_the_baseline_is_shown_under_its_company(tmp_path):
    md, _ = built(early_signal_run(tmp_path))
    projects = section(md, "Projects")
    heading = "— Baseline: size, sites and investment"
    a = projects.split("### Competitor A " + heading)[1].split("\n### ")[0]
    assert a.strip().startswith("- Competitor A runs two plants with about 400 staff. (F4)")   # the fact's own statement
    # the baseline of a company without a move still gets its own heading
    c = projects.split("### Competitor C " + heading)[1].split("\n### ")[0]
    assert "- Competitor C runs one plant and invested 12 million last year. (F5)" in c
    assert "Moves by type" in projects                       # the counting tables are unchanged


def test_a_baseline_with_two_facts_shows_both_statements_with_their_references(tmp_path):
    run = early_signal_run(tmp_path, baselines=False)
    analysis = store.read_analysis(run)
    analysis["baselines"] = [{"company": "Competitor A", "fact_ids": ["F4", "F1"]},
                             {"company": "competitor a", "fact_ids": ["F1"]}]    # a repeated fact is shown once
    store.write_analysis(run, analysis)
    md, _ = built(run)
    block = section(md, "Projects").split("### Competitor A — Baseline: size, sites and investment")[1].split("\n###")[0]
    assert block.strip().splitlines() == ["- Competitor A runs two plants with about 400 staff. (F4)",
                                          "- Competitor A will add a second filling line at Plant North. (F1)"]


def test_a_baseline_resting_on_an_uncertain_fact_says_so(tmp_path):
    run = early_signal_run(tmp_path, baselines=False)
    add_fact(run, kind="general", fields=None, source_id="S3", primary_source=False,   # one source, not primary
             statement="Competitor C runs one plant.", quote="operates one plant and invested 12 million in the last year")
    verify.check_quotes(run); verify.record_support(run, "F6", True, "support-checker", ""); verify.settle(run)
    assert store.read_facts(run)["F6"]["status"] == "uncertain"
    analysis = store.read_analysis(run)
    analysis["baselines"] = [{"company": "Competitor C", "fact_ids": ["F6"]}]   # an early signal may not be one (M8)
    store.write_analysis(run, analysis)
    md, _ = built(run)
    assert "(F6 (One source only))" in section(md, "Projects")


def test_a_baseline_resting_on_a_non_public_fact_says_so(tmp_path):
    run = early_signal_run(tmp_path, baselines=False, mode="private", acknowledged=True)
    add_source(run, "Internal review: the plant employs about 90 people on two shifts.", data_class="internal",
               url="internal staffing review", publisher="Competitor C", type="other")
    add_fact(run, kind="general", fields=None, source_id="S4", primary_source=True,
             statement="The plant employs about 90 people.", quote="the plant employs about 90 people on two shifts")
    verify.check_quotes(run); verify.record_support(run, "F6", True, "support-checker", ""); verify.settle(run)
    analysis = store.read_analysis(run)
    analysis["baselines"] = [{"company": "Competitor C", "fact_ids": ["F6"]}]
    store.write_analysis(run, analysis)
    md, _ = built(run)
    assert "- The plant employs about 90 people. (F6 (Internal document))" in section(md, "Projects")


def test_a_run_without_early_signals_or_baselines_shows_neither_block(tmp_path):
    md, _ = built(ready_run(tmp_path))
    assert "Early signals" not in md and "Baseline: size, sites and investment" not in md
    md, _ = built(early_signal_run(tmp_path / "again", baselines=False))
    assert "Baseline: size, sites and investment" not in md and "### Early signals" in md


def test_a_baseline_company_name_cannot_form_links_or_markup(tmp_path):
    run = early_signal_run(tmp_path, baselines=False)
    analysis = store.read_analysis(run)
    analysis["baselines"] = [{"company": "A <b>Co</b> [click](http://evil.example)", "fact_ids": ["F4"]}]
    store.write_analysis(run, analysis)
    md, _ = built(run)
    assert "<b>" not in md and "[click](" not in md
    assert r"\<b\>Co\</b\>" in md


# --- fix wave A13: build-report holds the run lock from the gate to the last file ----------------------------------

from radar.report import build as build_module   # noqa: E402

def _lock_is_taken(run) -> bool:
    import fcntl
    with open(run / store.LOCK_FILE, "a", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
        return False


def test_the_run_lock_is_held_while_the_gate_runs_and_while_the_report_is_rendered_and_written(tmp_path, monkeypatch):
    run = ready_run(tmp_path)
    seen = {}
    real_gate, real_html, real_write = build_module.gate, build_module.render_html, Path.write_bytes

    def gate(*args, **kwargs):
        seen["gate"] = _lock_is_taken(run)
        return real_gate(*args, **kwargs)

    def render_html(model):
        seen["render"] = _lock_is_taken(run)
        return real_html(model)

    def write_bytes(path, data):
        if path.parent == run / "report":
            seen.setdefault("writes", []).append(_lock_is_taken(run))
        return real_write(path, data)

    monkeypatch.setattr(build_module, "gate", gate)
    monkeypatch.setattr(build_module, "render_html", render_html)
    monkeypatch.setattr(Path, "write_bytes", write_bytes)
    build_report(run, LENSES)
    assert seen == {"gate": True, "render": True, "writes": [True, True, True, True]}
    assert not _lock_is_taken(run)                      # and it is given back


def test_a_build_waits_for_a_command_that_holds_the_run_and_writes_nothing_when_it_gives_up(tmp_path, monkeypatch,
                                                                                         capsys):
    run = ready_run(tmp_path)
    monkeypatch.setattr(store, "LOCK_WAIT_SECONDS", 0.2)
    with store.locked(run):                             # another command is working on the run
        with pytest.raises(store.RunBusy):
            build_report(run, LENSES)
        assert main(["build-report", "--run", str(run), "--lenses", str(LENSES)]) == 2
    assert json.loads(capsys.readouterr().out) == {"error": store.RUN_BUSY, "busy": True}
    assert list((run / "report").iterdir()) == []


# --- fix wave A18: the illustrative banner says only what is always true of an illustrative run ----------------------

BANNER = ("Illustrative only. This report was made with an invented company pack as practice material. "
          "Nothing in it is a finding about a real company.")


def test_the_banner_claims_nothing_about_files_a_person_added_and_the_print_banner_is_the_same(tmp_path):
    labels = load_labels()
    assert labels["illustrative"] == BANNER
    assert "invented." not in labels["illustrative"] and "Every" not in labels["illustrative"]
    run = ready_run(tmp_path, illustrative=True)
    build_report(run, LENSES)
    html = (run / "report" / "report.html").read_text(encoding="utf-8")
    assert html.count(BANNER) == 1 and '<div class="banner illustrative">' in html   # one element, on screen and print


# --- fix wave A21: the reply to the private-mode notice stands next to the decisions --------------------------------

REPLY = 'Yes, go ahead <b>now</b> & "quickly"'


def test_the_reply_to_the_private_mode_notice_is_shown_under_how_this_report_was_made(tmp_path):
    run = ready_run(tmp_path, mode="private", acknowledged=True, acknowledged_words=REPLY)
    build_report(run, LENSES)
    labels = load_labels()
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    how = md.split("## " + labels["sec_how_made"])[1]
    checkpoints = how.split("### " + labels["how_checkpoints"])[1].split("\n\n", 2)[1]
    assert checkpoints.splitlines()[0] == ("- " + labels["private_acknowledged"] + ": Yes, go ahead \\<b\\>now\\</b\\> "
                                           '& "quickly"')
    html = (run / "report" / "report.html").read_text(encoding="utf-8")
    view = html.split('id="view-how"')[1].split("</section>")[0]
    assert (labels["private_acknowledged"] + ": Yes, go ahead &lt;b&gt;now&lt;/b&gt; &amp; &quot;quickly&quot;") in view
    assert view.index(labels["private_acknowledged"]) < view.index(labels["checkpoint_lenses"])


def test_a_public_run_shows_no_reply(tmp_path):
    run = ready_run(tmp_path)
    build_report(run, LENSES)
    assert load_labels()["private_acknowledged"] not in (run / "report" / "report.md").read_text(encoding="utf-8")


def test_the_demo_s_private_variant_says_its_reply_is_the_invented_practice_run_s(tmp_path):
    run = demo.build_demo_run(tmp_path, private=True)
    words = store.load_run(run)["private_acknowledged_words"]
    assert "invented practice run" in words and "no person" in words
    build_report(run, demo.LENSES)
    assert words in (run / "report" / "report.md").read_text(encoding="utf-8")


# --- fix wave A23.3: a supporting quote's translation is shown wherever the quote is -------------------------------

GERMAN_SUPPORT = "Competitor A baut zwei neue Abfülllinien im Werk Nord bis 2028."
ENGLISH_SUPPORT = "Competitor A is building two new filling lines at Plant North by 2028."


def _translated_support_run(tmp_path):
    run = make_run(tmp_path)
    add_source(run, TEXT, publisher="Competitor A")
    add_source(run, "Bericht: " + GERMAN_SUPPORT, publisher="Fachblatt", language="de")
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers",
             supporting=[{"source_id": "S2", "quote": GERMAN_SUPPORT, "quote_translation": ENGLISH_SUPPORT}])
    finish_run(run, ["F1"])
    return run


def test_a_supporting_quote_s_translation_is_shown_on_the_fact_card_and_on_the_source_page(tmp_path):
    run = _translated_support_run(tmp_path)
    build_report(run, LENSES)
    labels = load_labels()
    html = (run / "report" / "report.html").read_text(encoding="utf-8")
    card = html.split('<details class="fact" id="F1"')[1].split("</details>")[0]
    assert f'<blockquote lang="de">{GERMAN_SUPPORT}</blockquote>' in card
    assert f'{labels["translation"]}: {ENGLISH_SUPPORT}' in card
    page = html.split('<article class="source" id="S2"')[1].split("</article>")[0]
    assert f'{labels["translation"]}: {ENGLISH_SUPPORT}' in page
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    source = md.split("### S2:")[1].split("\n### ")[0]
    assert f"> {labels['translation']}: {ENGLISH_SUPPORT}" in source


def test_the_facts_table_holds_the_supporting_translations_in_order(tmp_path):
    import csv
    import io
    from radar.report.export import facts_csv
    run = _translated_support_run(tmp_path)
    row = next(csv.DictReader(io.StringIO(facts_csv(build_model(run, LENSES)))))
    assert row["supporting_translations"] == ENGLISH_SUPPORT and row["supporting_sources"] == "S2"
    plain = make_run(tmp_path / "plain")
    add_source(plain, TEXT)
    add_fact(plain, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers",
             supporting=[{"source_id": "S1", "quote": "adds two high-speed syringe lines for customers"}])
    finish_run(plain, ["F1"])
    assert next(csv.DictReader(io.StringIO(facts_csv(build_model(plain, LENSES)))))["supporting_translations"] == ""


# --- fix wave A23.4: one fact, one line and one proposed fact read as one ---------------------------------------------

def test_one_fact_and_one_rejected_fact_read_in_the_singular(tmp_path):
    run = ready_run(tmp_path)                       # F1 confirmed, F2 rejected
    build_report(run, LENSES)
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    html = (run / "report" / "report.html").read_text(encoding="utf-8")
    for text in (md, html):
        assert "1 fact, all quotes checked" in text and "1 proposed fact rejected" in text
        assert "1 facts" not in text and "1 proposed facts" not in text


def test_more_than_one_still_reads_in_the_plural(tmp_path):
    run = demo.build_demo_run(tmp_path)
    build_report(run, demo.LENSES)
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    assert "7 facts, all quotes checked" in md and "3 proposed facts rejected" in md


def test_a_size_of_one_reads_with_its_unit_in_the_singular(tmp_path):
    run = demo.build_demo_run(tmp_path)
    build_report(run, demo.LENSES)
    html = (run / "report" / "report.html").read_text(encoding="utf-8")
    assert "1 lines" not in html and "(1 line)" in html and ">1 line<" in html and "(2 lines)" in html


@pytest.mark.parametrize("value, unit, read", [
    ("1", "lines", "line"), ("1", "tonnes", "tonne"), ("1", "batches", "batch"), ("1", "boxes", "box"),
    ("1", "facilities", "facility"), ("1", "glasses", "glass"), ("1", "Lines", "Line"), ("1.0", "lines", "line"),
    ("1", "kWh", "kWh"), ("1", "gas", "gas"), ("1", "bus", "bus"), ("1", "million vials", "million vials"),
    ("2", "lines", "lines"), ("0", "lines", "lines"), ("1.5", "lines", "lines"), (None, "lines", "lines"),
    ("1", None, None), ("one", "lines", "lines")])
def test_the_unit_after_exactly_one_is_made_singular_only_where_that_is_safe(value, unit, read):
    from radar.report.model import unit_for
    assert unit_for(value, unit) == read


# --- task 9: what a lens rests on, and the recommendation as unchecked advice ---------------------------------------

from radar import recommend   # noqa: E402

LABEL = "The recommender's suggestion, not checked"
NO_RECOMMENDATION = ("No recommendation was made: the advisor did not run, or its list was refused twice by the "
                     "program's form check.")
READER_ONE, READER_TWO = recommend.READERS
SURVEY = "Smith, A. (2000). A survey of firms."


def real_lens_folder(folder, level):
    """A lens folder whose firm-boundaries names a real-looking work at `level` (the demo lens names an invented one)."""
    folder = lens_folder_with_level(folder, level)
    path = folder / "firm-boundaries.json"
    lens = json.loads(path.read_text(encoding="utf-8"))
    lens["originals"][0].update({"reference": SURVEY if level == "secondary_source_read" else "Coase, R. (1937). Firms."})
    if level == "secondary_source_read":
        lens["originals"][0].update({"about": "Coase, R. (1937). The nature of the firm.",
                                     "link": "https://www.example.com/a-survey"})
    path.write_text(json.dumps(lens), encoding="utf-8")
    return folder


def recommendation(why="Two lines were built for one customer.", **over):
    entry = {"lens": "firm-boundaries", "question_part": "adds capacity", "why": why, "facts": ["F1"],
             "missing": "Nothing found on what protects the plant."}
    entry.update(over)
    return entry


def recommended_run(tmp_path, entries=None, note=None, **run_over):
    run = ready_run(tmp_path, **run_over)
    recommend.record_recommendation(run, LENSES, [recommendation()] if entries is None else entries, note,
                                    recommend.ADVISOR)
    return run


def how_made_md(run):
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    return md.split("## How this report was made")[1].split("\n## ")[0]


def test_the_report_says_what_a_secondary_source_lens_rests_on_in_both_formats(tmp_path):
    folder = real_lens_folder(tmp_path / "lenses", "secondary_source_read")
    run = ready_run(tmp_path)
    build_report(run, folder)
    sentence = ("Rests on: Smith, A. (2000). A survey of firms, a source about Coase, R. (1937). The nature of the "
                "firm, read; the original itself was not read")
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    thinking = md.split("## Thinking behind this analysis")[1].split("\n## ")[0]
    assert esc(sentence) in thinking
    html = (run / "report" / "report.html").read_text(encoding="utf-8")
    card = find(html, "article", **{"class": "lens-card"})[0]
    assert "the original itself was not read" in card["text"] and "Rests on: Smith, A. (2000)" in card["text"]


def test_the_report_says_an_original_read_lens_rests_on_the_original(tmp_path):
    folder = real_lens_folder(tmp_path / "lenses", "original_read")
    run = ready_run(tmp_path)
    build_report(run, folder)
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    assert "Rests on: the original, read" in md.split("## Thinking behind this analysis")[1].split("\n## ")[0]
    html = (run / "report" / "report.html").read_text(encoding="utf-8")
    assert "Rests on: the original, read" in find(html, "article", **{"class": "lens-card"})[0]["text"]


def test_an_invented_lens_says_it_rests_on_no_real_work_as_the_first_stop_does(tmp_path):
    run = ready_run(tmp_path)
    build_report(run, LENSES)
    sentence = load_labels()["rests_on_invented"]
    assert sentence in (run / "report" / "report.md").read_text(encoding="utf-8")
    assert "Rests on: the original, read" not in (run / "report" / "report.md").read_text(encoding="utf-8")
    html = (run / "report" / "report.html").read_text(encoding="utf-8")
    assert sentence in find(html, "article", **{"class": "lens-card"})[0]["text"]


def test_a_lens_file_that_cannot_be_read_never_breaks_the_report_or_says_what_it_rests_on(tmp_path):
    model = build_model(ready_run(tmp_path), LENSES)
    lens = {"id": "x", "name": "x"}
    from radar.report import model as report_model
    assert report_model.lens_rests_on(lens, load_labels()) is None
    assert model["lenses"][0]["rests_on"]


def test_with_a_recommendation_the_report_shows_it_as_unchecked_advice_in_both_formats(tmp_path):
    run = recommended_run(tmp_path)
    recommend.record_link_check(run, "firm-boundaries", "F1", "doubt", READER_ONE, "The fact is about a plant.")
    recommend.record_link_check(run, "firm-boundaries", "F1", "bears", READER_TWO, "")
    build_report(run, LENSES)
    labels = load_labels()
    how = how_made_md(run)
    assert labels["rec_label"] == LABEL and LABEL in how
    assert how.index(labels["checkpoint_lenses"]) < how.index(LABEL)          # after the recorded lens decision
    for part in ("Where firms draw their boundaries", "adds capacity", "Two lines were built for one customer.",
                 "F1", "Nothing found on what protects the plant."):
        assert part in how, part
    assert "The first reader doubts that this fact bears on the lens: The fact is about a plant." in how
    assert "The second reader found that this fact bears on the lens." in how
    assert ("Helpers set to: the lens advisor: " in how
            and "; a setting on the computer of the person who ran it can override a helper's model" in how)
    assert NO_RECOMMENDATION not in how and "lens-link-reader" not in how and "lens-advisor" not in how
    html = (run / "report" / "report.html").read_text(encoding="utf-8")
    view = find(html, "section", id="view-how")[0]["text"]
    for part in (LABEL, "The first reader doubts that this fact bears on the lens: The fact is about a plant.",
                 "The second reader found that this fact bears on the lens.", "Helpers set to: the lens advisor: ",
                 "Two lines were built for one customer."):
        assert part in view, part
    assert NO_RECOMMENDATION not in view and "lens-link-reader" not in view


def test_a_reader_that_recorded_nothing_is_said_so_and_never_counts_as_agreement(tmp_path):
    run = recommended_run(tmp_path)
    recommend.record_link_check(run, "firm-boundaries", "F1", "bears", READER_ONE, "")
    build_report(run, LENSES)
    how = how_made_md(run)
    assert "The first reader found that this fact bears on the lens." in how
    assert "The second reader recorded nothing on this link." in how


def test_a_recommendation_with_no_lens_shows_its_note_under_the_label_and_no_models_line(tmp_path):
    run = recommended_run(tmp_path, entries=[], note="No lens fits a question about prices.")
    build_report(run, LENSES)
    how = how_made_md(run)
    assert LABEL in how and "No lens fits a question about prices." in how
    assert NO_RECOMMENDATION not in how and "Helpers set to" not in how
    html = find((run / "report" / "report.html").read_text(encoding="utf-8"), "section", id="view-how")[0]["text"]
    assert LABEL in html and "No lens fits a question about prices." in html and NO_RECOMMENDATION not in html


def test_without_a_record_the_report_says_no_recommendation_was_made(tmp_path):
    run = ready_run(tmp_path)
    build_report(run, LENSES)
    assert NO_RECOMMENDATION in how_made_md(run) and LABEL not in how_made_md(run)
    html = find((run / "report" / "report.html").read_text(encoding="utf-8"), "section", id="view-how")[0]["text"]
    assert NO_RECOMMENDATION in html and LABEL not in html


DAMAGED = ("No recommendation can be shown: the lens recommendation file of this run is damaged, so it can no "
           "longer be read as it was made.")
STALE = ("This list was made before the facts changed: it was made for other facts than the ones this report rests "
         "on, so it was not the current list at the final decision. It is shown as it was made.")
GONE = "This fact no longer counts."


def how_made_html(run):
    return find((run / "report" / "report.html").read_text(encoding="utf-8"), "section", id="view-how")[0]["text"]


@pytest.mark.parametrize("damage", ["not json", "no entry can be read", "a folder"])
def test_a_damaged_record_is_said_to_be_damaged_in_the_report_and_never_raises(tmp_path, damage):
    """Final review I3: a damaged record is not shown, and the reason says the file is damaged; "the advisor did not
    run" would be untrue, because it did."""
    run = recommended_run(tmp_path)
    if damage == "not json":
        (run / recommend.RECORD).write_text("{", encoding="utf-8")
    elif damage == "a folder":
        (run / recommend.RECORD).unlink()
        (run / recommend.RECORD).mkdir()
    else:
        record = json.loads((run / recommend.RECORD).read_text(encoding="utf-8"))
        record["entries"][0] = 5
        (run / recommend.RECORD).write_text(json.dumps(record), encoding="utf-8")
    build_report(run, LENSES)
    labels = load_labels()
    assert labels["rec_damaged"] == DAMAGED
    for how in (how_made_md(run), how_made_html(run)):
        assert DAMAGED in how and NO_RECOMMENDATION not in how and LABEL not in how
        assert "Two lines were built for one customer." not in how and "Helpers set to" not in how


DAMAGED_PARTS = ("Parts of this list were changed after the program wrote it, so they are not as the advisor made "
                 "them. Each such part is marked where it stands; the rest is shown as it was made.")


def test_a_partly_damaged_record_is_shown_with_each_damaged_part_marked_in_both_formats(tmp_path):
    """Paul's decision 18: the report keeps what can be read and marks exactly where it was changed."""
    run = recommended_run(tmp_path)
    record = json.loads((run / recommend.RECORD).read_text(encoding="utf-8"))
    record["entries"][0]["why"] = 5
    record["by"] = 3
    (run / recommend.RECORD).write_text(json.dumps(record), encoding="utf-8")
    build_report(run, LENSES)
    for how in (how_made_md(run), how_made_html(run)):
        assert LABEL in how and DAMAGED_PARTS in how and DAMAGED not in how and NO_RECOMMENDATION not in how
        assert "The reason given cannot be read: it was changed after the program wrote it." in how
        assert "The name of who made it cannot be read: it was changed after the program wrote it." in how
        assert "Why: " not in how


def test_a_reader_s_verdict_that_cannot_be_read_is_said_next_to_its_link(tmp_path):
    run = recommended_run(tmp_path)
    record = json.loads((run / recommend.RECORD).read_text(encoding="utf-8"))
    record["link_checks"] = [{"lens": "firm-boundaries", "fact": "F1", "by": recommend.READERS[0], "verdict": "maybe",
                              "note": "", "at": "t"}]
    (run / recommend.RECORD).write_text(json.dumps(record), encoding="utf-8")
    build_report(run, LENSES)
    for how in (how_made_md(run), how_made_html(run)):
        assert DAMAGED_PARTS in how
        assert "A reader's verdict on this link cannot be read: it was changed after the program wrote it." in how


def stale_run(tmp_path):
    """A run where F1 and F3 count and the recommendation links both; then F3 is withdrawn and settled, so the record
    is stale and one of its links names a fact that no longer counts. The analysis names only F1."""
    run = ready_run(tmp_path)
    add_fact(run, source_id="S1", primary_source=True, quote="The expansion adds two high-speed syringe lines",
             statement="The expansion is confirmed.")
    verify.check_quotes(run)
    verify.record_support(run, "F3", True, "support-checker", "")
    verify.settle(run)
    recommend.record_recommendation(run, LENSES, [recommendation(facts=["F1", "F3"])], None, recommend.ADVISOR)
    recommend.record_link_check(run, "firm-boundaries", "F3", "bears", READER_ONE, "")
    verify.withdraw_fact(run, "F3", "A duplicate of F1.")
    verify.settle(run)
    return run


def test_a_stale_record_is_shown_as_made_with_a_plain_sentence_of_its_state_in_both_formats(tmp_path):
    """Final review I3 (ruling: the record as it was made, plus a plain sentence of its state)."""
    run = stale_run(tmp_path)
    build_report(run, LENSES)
    labels = load_labels()
    assert (labels["rec_stale"], labels["rec_fact_gone"]) == (STALE, GONE)
    for how in (how_made_md(run), how_made_html(run)):
        assert LABEL in how and STALE in how and how.index(LABEL) < how.index(STALE)
        assert "Two lines were built for one customer." in how                # the list as it was made
        assert how.count(GONE) == 1, how                                       # next to F3 only, not next to F1
        assert NO_RECOMMENDATION not in how and DAMAGED not in how
    md = how_made_md(run)
    gone_line = next(line for line in md.splitlines() if GONE in line)
    assert "F3" in gone_line and "F1" not in gone_line
    assert gone_line.index(GONE) < gone_line.index("The first reader found that this fact bears on the lens.")


def test_a_current_record_has_no_state_sentence_and_no_fact_marked_as_gone(tmp_path):
    run = recommended_run(tmp_path)
    build_report(run, LENSES)
    for how in (how_made_md(run), how_made_html(run)):
        assert LABEL in how and STALE not in how and GONE not in how and DAMAGED not in how


def test_the_text_of_a_recommendation_is_escaped_in_both_formats(tmp_path):
    run = recommended_run(tmp_path, entries=[recommendation(why='It <b>bears</b> & "fits"')])
    recommend.record_link_check(run, "firm-boundaries", "F1", "doubt", READER_ONE, "<script>x</script>")
    build_report(run, LENSES)
    assert "\\<b\\>bears\\</b\\>" in how_made_md(run) and "\\<script\\>x\\</script\\>" in how_made_md(run)
    html = (run / "report" / "report.html").read_text(encoding="utf-8")
    assert "<b>bears</b>" not in html and "<script>x</script>" not in html
    assert "It &lt;b&gt;bears&lt;/b&gt; &amp; &quot;fits&quot;" in html


def test_a_private_run_with_a_recommendation_still_refuses_a_publishable_build(tmp_path):
    run = recommended_run(tmp_path, mode="private", acknowledged=True)
    add_source(run, "Internal capacity review. " * 20, data_class="internal", url="internal capacity review")
    with pytest.raises(GateRefused) as err:
        build_report(run, LENSES, publishable=True)
    assert any(p.message == "a publishable report may not be built from a private run" for p in err.value.problems)
    assert not (run / "report" / "report.md").exists()
    build_report(run, LENSES)   # the confidential report is built, and is marked so
    assert LABEL in how_made_md(run) and "Confidential" in (run / "report" / "report.md").read_text(encoding="utf-8")


def test_the_tables_are_the_same_with_and_without_a_recommendation(tmp_path):
    without = ready_run(tmp_path / "a")
    with_record = recommended_run(tmp_path / "b")
    recommend.record_link_check(with_record, "firm-boundaries", "F1", "doubt", READER_ONE, "A doubt.")
    for run in (without, with_record):
        build_report(run, LENSES, now=datetime(2026, 11, 16, tzinfo=timezone.utc))
    for name in ("facts.csv", "sources.csv"):
        assert (without / "report" / name).read_bytes() == (with_record / "report" / name).read_bytes()
    assert "A doubt." not in (with_record / "report" / "facts.csv").read_text(encoding="utf-8-sig")


# --- Task 12: the Markdown report carries the answer, the companies, the projects and the connections -----------------

ANSWER_NOTE = ("Counted by project. The grouping into projects is a model's judgement; the program checked only that "
               "each move sits in one project, and that a project holds one company and one country.")


def grouped_markdown(tmp_path, analysis=None, group_them=True):
    from test_report_projects import group, moves_run   # here and not at the top: that file imports this one
    run = moves_run(tmp_path, analysis)
    if group_them:
        group(run)
    return run, render_markdown(build_model(run, LENSES))


def test_the_markdown_opens_on_the_answer_then_companies_then_messages(tmp_path):
    _, md = grouped_markdown(tmp_path)
    headings = ["Who is the new capacity for?", "Look at one company", "Key messages", "What the sources say",
                "Projects", "Connections", "Sources", "How this report was made"]
    places = [md.index(f"\n## {heading}\n") for heading in headings]
    assert places == sorted(places) and "## Summary" not in md and "## Competitors" not in md
    answer = section(md, "Who is the new capacity for?")
    for line in ("- Open to customers: 1", "- For own use: 1", "- Reports disagree: 0", "- Not stated: 0", "2 projects",
                 ANSWER_NOTE, "A project counts as open to customers when at least one of its reports says so"):
        assert line in answer, line
    assert answer.index("- Open to customers: 1") < answer.index("- Not stated: 0") < answer.index(ANSWER_NOTE)
    companies = section(md, "Look at one company")
    assert "- **Example Pharma** (own company): 0 facts, no project" in companies
    assert ("- **Competitor A**: 1 project; Open to customers: 1, For own use: 0, Reports disagree: 0, Not stated: 0"
            in companies)
    assert "- **Competitor B**: 1 project; Open to customers: 0, For own use: 1" in companies
    assert "Competitor A is adding capacity." in section(md, "Key messages")


def test_the_markdown_shows_the_facts_of_an_entry_without_projects_not_a_count_of_zero(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "Drug maker X reports a fire. Drug maker Y reports a flood.")
    add_fact(run, kind="general", fields=None, source_id="S1", primary_source=True,
             statement="A fire was reported.", quote="Drug maker X reports a fire")
    add_fact(run, kind="general", fields=None, source_id="S1", primary_source=True,
             statement="A flood was reported.", quote="Drug maker Y reports a flood")
    finish_run(run, ["F1"])
    companies = section(render_markdown(build_model(run, LENSES)), "Look at one company")
    assert "- **Not about one company**: 2 facts, no project" in companies
    assert "0 projects" not in companies and "Open to customers" not in companies


def test_the_markdown_without_a_grouping_says_why_each_move_counts_alone(tmp_path):
    _, md = grouped_markdown(tmp_path, group_them=False)
    answer = section(md, "Who is the new capacity for?")
    assert "4 projects" in answer and ANSWER_NOTE not in answer
    assert load_labels()["answer_ungrouped_none"] in answer
    assert load_labels()["answer_ungrouped_none"] in section(md, "Projects")


def test_the_markdown_lists_projects_with_their_reports_and_connections(tmp_path):
    _, md = grouped_markdown(tmp_path)
    projects = section(md, "Projects")
    assert projects.index("### Competitor A, Plant North") < projects.index("### Competitor B, Exampleland")
    block = projects.split("### Competitor A, Plant North")[1].split("\n### ")[0]
    assert "Competitor A · Open to customers · 3 confirmed" in block
    for part in ("Stage: Announced (2), Operating (1)", "Site: Plant North (2)", "Country: Exampleland (3)",
                 "Planned start: 2028 (3)", "What was added: a second filling line (3)"):
        assert part in block, part
    reports = [line for line in block.splitlines() if line.startswith("- ")]
    assert len(reports) == 3 and [line.split("(")[-1][:2] for line in reports] == ["F3", "F1", "F2"]   # newest first
    assert all("(2 lines)" in line and "Competitor A" in line for line in reports) and "2026-09-01" in reports[0]
    single = projects.split("### Competitor B, Exampleland")[1].split("\n### ")[0]
    assert "For own use · 1 from one source only" in single and "(1)" not in single
    assert "F4 (One source only)" in single and "Trade Journal" in single
    connections = section(md, "Connections")
    assert "| Company | Tie | Party | Status | Fact |" in connections
    assert "| Competitor A | Customer | Drug maker B | Confirmed | F5 |" in connections
    assert "### Moves by type" in projects and "| Competitor A |" in projects


def test_a_party_that_is_not_named_shows_its_description_in_the_markdown(tmp_path):
    run = make_run(tmp_path, companies=[{"name": "Competitor A", "other_names": [], "home": False}])
    add_source(run, "Competitor A sold its plant to a major biopharma partner.")
    add_fact(run, kind="general", fields=None, source_id="S1", primary_source=True, about_company="Competitor A",
             statement="Competitor A sold a plant.", quote="Competitor A sold its plant to a major biopharma partner",
             connections=[{"party": None, "tie": "buyer", "description": "a major biopharma partner"}])
    finish_run(run, ["F1"])
    assert "| Competitor A | Buyer | Not named: a major biopharma partner | Confirmed | F1 |" in \
        section(render_markdown(build_model(run, LENSES)), "Connections")


def test_a_markdown_message_lists_its_checks_underneath(tmp_path):
    from test_report_projects import analysis_with_flags
    _, md = grouped_markdown(tmp_path, analysis_with_flags())
    message = section(md, "Key messages")
    assert message.index("Competitor A is adding capacity.") < message.index("**Sources**") < message.index("**Checks on this message**")
    assert "**Sources**: Competitor A (S1, the company's own statement), Trade Journal (S2), Competitor A (S3, the company's own statement)" in message
    checks = message.split("**Checks on this message**")[1]
    assert "- Framing: The message leans on Competitor A's own words." in checks
    assert "No base rate was looked for." not in message            # it names no message: the checks section only
    assert "No base rate was looked for." in section(md, "Checks on this analysis")


def test_a_message_without_checks_has_no_checks_list_in_the_markdown(tmp_path):
    _, md = grouped_markdown(tmp_path)
    assert "Checks on this message" not in md


def test_the_facts_are_listed_by_company_newest_first_with_the_status_shown(tmp_path):
    _, md = grouped_markdown(tmp_path)
    facts = section(md, "What the sources say")
    assert "### Example Pharma" not in facts                                     # it has no fact
    assert facts.index("### Competitor A") < facts.index("### Competitor B")
    first = facts.split("### Competitor A")[1].split("\n### ")[0]
    ids = re.findall(r"— (S\d), ", first)
    assert ids == ["S3", "S1", "S1", "S1"]                                       # 2026-09-01 first, then 2026-05-14
    assert "— S2, One source only" in facts.split("### Competitor B")[1]
    assert "— S1, Confirmed" in first


def test_the_markdown_how_made_says_how_the_projects_were_counted_and_which_names_were_dropped(tmp_path):
    _, md = grouped_markdown(tmp_path)
    how = section(md, "How this report was made")
    assert "### How the projects and the answer were counted" in how and ANSWER_NOTE in how
    assert "were not found in their quotes" not in how
    run, _ = grouped_markdown(tmp_path / "second")
    add_fact(run, kind="general", fields=None, source_id="S1", primary_source=True, about_company="Competitor C",
             statement="A filling line is planned.", quote="Competitor A will add a filling line at Plant North")
    verify.check_quotes(run)
    verify.record_support(run, "F6", True, "support-checker", "")
    verify.settle(run)
    how = section(render_markdown(build_model(run, LENSES)), "How this report was made")
    assert "1 company names and 0 names of other parties were not found in their quotes, so they are not shown." in how


def test_a_markdown_status_line_says_how_many_rest_on_one_source(tmp_path):
    _, md = grouped_markdown(tmp_path)
    assert "1 from one source only · 0 marked uncertain" in md.splitlines()[2]


def test_the_new_markdown_text_cannot_form_markup(tmp_path):
    run, _ = grouped_markdown(tmp_path)
    from radar import projects
    projects.record_projects(run, [{"name": "<b>Big</b> [link](http://x.example) plan", "fact_ids": ["F4"]},
                                   {"name": "Competitor A, Plant North", "fact_ids": ["F1", "F2", "F3"]}],
                             projects.GROUPER)
    md = render_markdown(build_model(run, LENSES))
    assert "<b>" not in md and "[link](" not in md and "\\<b\\>Big\\</b\\> \\[link\\]" in md
