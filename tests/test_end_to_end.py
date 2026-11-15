import json
from pathlib import Path
from radar import demo, store
from radar.cli import main
from fixtures.build_demo_run import build_demo_run

LENSES = str(demo.LENSES)

def test_demo_run_settles_as_designed(tmp_path):
    run = build_demo_run(tmp_path)
    facts = store.read_facts(run)
    counts = {}
    for f in facts.values(): counts[f["status"]] = counts.get(f["status"], 0) + 1
    assert counts == {"confirmed": 6, "uncertain": 1, "rejected": 3}
    reasons = sorted(f["status_reason"] for f in facts.values() if f["status"] == "rejected")
    assert reasons == ["not_found", "not_supported", "not_supported"]

def test_demo_run_builds_and_shows_the_rejected_facts(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    assert main(["build-report", "--run", str(run), "--lenses", LENSES]) == 0
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["built"] == \
        ["report/report.md", "report/report.html", "report/facts-illustrative.csv", "report/sources-illustrative.csv"]
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    assert "Illustrative only." in md and "3 proposed facts rejected" in md
    not_confirmed = md.split("## What we could not confirm")[1].split("\n## ")[0]
    assert "The quote was not found in the saved source." in not_confirmed
    assert "The checker judged that the quote does not support the fact." in not_confirmed

def test_forcing_a_rejected_fact_into_the_analysis_is_refused(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    rejected = next(f["id"] for f in store.read_facts(run).values() if f["status_reason"] == "not_found")
    analysis = store.read_analysis(run)
    analysis["messages"][0]["chain"][0]["fact_ids"].append(rejected)
    store.write_analysis(run, analysis)
    assert main(["build-report", "--run", str(run), "--lenses", LENSES]) == 1
    out = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert out["built"] == []
    assert any(p["message"] == f"rests on fact {rejected} with status rejected" for p in out["problems"])
    assert not (run / "report" / "report.html").exists()

def test_editing_a_saved_copy_after_the_fact_is_refused(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    copy = run / "copies" / "S1.txt"
    copy.write_text(copy.read_text(encoding="utf-8").replace("2028", "2031"), encoding="utf-8")
    assert main(["build-report", "--run", str(run), "--lenses", LENSES]) == 1
    problems = json.loads(capsys.readouterr().out.splitlines()[-1])["problems"]
    assert {"file": "sources/S1.json", "field": "copy_sha256", "message": "saved copy has changed"} in problems
    assert {"file": "facts/F1.json", "field": "quote", "message": "quote not found in saved copy"} in problems

def test_demo_run_is_publishable_and_a_private_variant_is_not(tmp_path, capsys):
    run = build_demo_run(tmp_path / "public")
    assert main(["build-report", "--run", str(run), "--lenses", LENSES, "--publishable"]) == 0
    private = build_demo_run(tmp_path / "private", private=True)
    assert main(["build-report", "--run", str(private), "--lenses", LENSES]) == 0
    assert "Confidential." in (private / "report" / "report.md").read_text(encoding="utf-8")
    capsys.readouterr()
    assert main(["build-report", "--run", str(private), "--lenses", LENSES, "--publishable"]) == 1
    out = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert out["built"] == [] and out["problems"] == [
        {"file": "run.json", "field": "mode", "message": "a publishable report may not be built from a private run"},
        {"file": "sources/S7.json", "field": "data_class", "message": "a publishable report may use public sources only"}]

def test_a_total_that_was_changed_by_hand_is_refused(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    analysis = store.read_analysis(run)
    analysis["calculations"][0]["result"] = str(int(analysis["calculations"][0]["result"]) + 1)
    store.write_analysis(run, analysis)
    assert main(["build-report", "--run", str(run), "--lenses", LENSES]) == 1
    out = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert any("result does not match its inputs" in p["message"] for p in out["problems"])

def test_demo_run_status_and_explained_refusal(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    assert main(["status", "--run", str(run), "--lenses", LENSES]) == 0
    st = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert st["next"] == "build" and st["steps"][2]["detail"] == "6 confirmed, 1 uncertain, 3 rejected, 0 still to check"
    rejected = next(f["id"] for f in store.read_facts(run).values() if f["status_reason"] == "not_found")
    analysis = store.read_analysis(run); analysis["messages"][0]["chain"][0]["fact_ids"].append(rejected)
    store.write_analysis(run, analysis)
    assert main(["build-report", "--run", str(run), "--lenses", LENSES]) == 1
    out = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert out["explained"][0]["what"] == f"The analysis uses fact {rejected}, but that fact was rejected."

def test_second_run_shows_what_changed(tmp_path, capsys):
    from radar.diff import facts_digest
    first = build_demo_run(tmp_path / "a")
    second = build_demo_run(tmp_path / "b", changed=True)   # one planned_start moved, one fact added, one dropped
    assert main(["compare", "--previous", str(first), "--current", str(second), "--today", "2026-11-12"]) == 0
    changes = json.loads((second / "changes.json").read_text(encoding="utf-8"))
    assert changes["previous_run"] == "demo" and changes["current_run"] == "demo-changed"
    assert changes["changed"] == [{"fact_id": "F1", "previous_fact_id": "F1",
                                   "fields": {"planned_start": ["2028", "2030"]}}]
    assert changes["source_changed"] == [{"fact_id": "F2", "previous_fact_id": "F2",
                                          "url": "https://www.competitor-a.example/news/plant-north-expansion"}]
    new_id = next(f["id"] for f in store.read_facts(second).values() if "Competitor D" in f["statement"])
    assert new_id == "F10"   # the planted negation is F9 here, because the trade rumour about Competitor C is left out
    assert changes["new"] == [{"fact_id": new_id}] and changes["not_found_again"] == [{"previous_fact_id": "F7"}]
    assert changes["possible_matches"] == [] and changes["source_unavailable"] == [] and changes["predictions_due"] == []
    assert changes["unchanged"] == 3 and changes["previous_confidential"] is False
    assert changes["facts_digest"] == facts_digest(store.read_facts(second))
    assert main(["build-report", "--run", str(second), "--lenses", LENSES]) == 0
    html = (second / "report" / "report.html").read_text(encoding="utf-8")
    assert 'id="view-changes"' in html and "This does not mean the plan was withdrawn." in html


# --- final fix I5: readers see labels, never engine tokens --------------------------------------

import re
from html.parser import HTMLParser


class _VisibleText(HTMLParser):
    """The text a reader sees: everything outside script and style elements."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._hidden = [], 0

    def handle_starttag(self, tag, attrs):
        self._hidden += tag in ("script", "style")

    def handle_endtag(self, tag):
        self._hidden -= tag in ("script", "style")

    def handle_data(self, data):
        if not self._hidden:
            self.parts.append(data)


def visible_text(html):
    parser = _VisibleText(); parser.feed(html); parser.close()
    return "\n".join(parser.parts)


RAW_TOKENS = ("not_found", "not_supported", "quote_too_short", "quote_too_long", "no_saved_copy",
              "supporting_quote_not_found", "checks_incomplete", "support_check_outdated", "final_report",
              "network_error", "too_large", "unsupported_type", "no_text_layer", "unreadable_file", "too_little_text",
              "login_required", "outside_view", "competitor_response", "evidence_symmetry", "missing_information",
              "success_stories", "single_source", "under_construction", "not_stated", "not_yet")


def test_the_demo_reports_show_no_engine_tokens(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    assert main(["build-report", "--run", str(run), "--lenses", LENSES]) == 0
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    page = visible_text((run / "report" / "report.html").read_text(encoding="utf-8"))
    for name, text in (("report.md", md.replace("\\_", "_")), ("report.html", page)):   # Markdown escapes "_"
        snake = re.findall(r"(?<![\w/.-])[a-z]+(?:_[a-z0-9]+)+(?![\w/-])", text)
        assert snake == [], (name, snake)
        for token in RAW_TOKENS:
            assert token not in text, (name, token)
        assert not re.search(r"http_\d", text), name
        assert not re.search(r"(?m)^(?:\d+\. )?(?:fact|reasoning|conclusion): ", text), name
        assert not re.search(r"(?m)^(?:- )?(?:lenses|final_report): ", text), name
        assert not re.search(r", (?:confirmed|uncertain|rejected)\b", text), name
        assert not re.search(r"(?m)^(?:- )?(?:independence|framing|uncertainty|causality|disconfirmation): ", text), name
    for label in ("The quote was not found in the saved source.",
                  "The checker judged that the quote does not support the fact.",
                  "The quote says the line starts filling in 2027, but the fact says 2029.",
                  "Independence", "Evidence symmetry and source interest", "Before choosing lenses",
                  "Before the final report"):
        assert label in md and label in page, label



# --- final fix S5 and S6: the demo claims nothing it has not checked; planted figures stay put ----

def test_the_demo_states_no_regularity_as_measured(tmp_path):
    analysis = store.read_analysis(build_demo_run(tmp_path))
    for message in analysis["messages"]:
        # fix wave A23.15: as the analysis format asks, an outside view no fact states says so ("None found:")
        assert message["outside_view"]["text"].startswith("None found:"), message["id"]
        assert "usually" not in message["outside_view"]["text"], message["id"]
    assert "filing says" not in analysis["messages"][1]["counter_view"]


def _outside_what_we_could_not_confirm(md, html):
    md_rest = md.split("## What we could not confirm")[0] + "\n## " + \
        md.split("## What we could not confirm")[1].split("\n## ", 1)[1]
    checks_start = html.index("<h3>What we could not confirm</h3>")
    checks_end = html.index("</section>", checks_start)
    return md_rest, html[:checks_start] + html[checks_end:]


def test_the_planted_figures_appear_only_under_what_we_could_not_confirm(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    assert main(["build-report", "--run", str(run), "--lenses", LENSES]) == 0
    md = (run / "report" / "report.md").read_text(encoding="utf-8")
    html = (run / "report" / "report.html").read_text(encoding="utf-8")
    for planted in ("54 million", "2029", "plans to offer its new filling lines"):
        assert planted in md and planted in html, planted              # shown where rejected facts belong
    md_rest, html_rest = _outside_what_we_could_not_confirm(md, html)
    for planted in ("54 million", "2029", "plans to offer its new filling lines"):
        assert planted not in md_rest and planted not in html_rest, planted


# --- DH1 follow-up: the built demo report suggests no second source where there is none -----------------------

def demo_report(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    assert main(["build-report", "--run", str(run), "--lenses", LENSES]) == 0
    capsys.readouterr()
    return run, (run / "report" / "report.md").read_text(encoding="utf-8"), \
        (run / "report" / "report.html").read_text(encoding="utf-8")


def fact_card(html, fact_id):
    """The text a reader sees in the card of one fact in the facts view."""
    return visible_text(re.search(rf'<details class="fact" id="{fact_id}">(.*?)</details>', html, re.S).group(1))


def test_a_quote_from_the_fact_s_own_source_is_not_shown_as_a_second_source(tmp_path, capsys):
    """Ruling DH1a: own-source quotes under their own label; "Also stated by" only for other sources."""
    _, _, html = demo_report(tmp_path, capsys)
    for fact_id, own in (("F3", 2), ("F4", 1)):
        card = fact_card(html, fact_id)
        assert "More from the same source" in card and "Also stated by" not in card, fact_id
        assert card.split("More from the same source", 1)[1].count("S" + {"F3": "2", "F4": "3"}[fact_id]) == own
    for fact_id in ("F1", "F6"):                       # F1: the trade piece; F6: the trade journal
        card = fact_card(html, fact_id)
        assert "Also stated by" in card and "More from the same source" not in card, fact_id
    for fact_id in ("F2", "F5", "F7"):                 # no supporting quote: neither heading
        card = fact_card(html, fact_id)
        assert "Also stated by" not in card and "More from the same source" not in card, fact_id


def test_a_date_that_is_not_stated_is_said_in_words(tmp_path, capsys):
    """Ruling DH1b: no code reaches the reader, also not with its underscore escaped for Markdown."""
    _, md, html = demo_report(tmp_path, capsys)
    for name, text in (("report.md", md), ("report.html", visible_text(html))):
        assert "not_stated" not in text.replace("\\_", "_"), name
    competitors = md.split("## Competitors", 1)[1].split("\n## ", 1)[0]
    assert "(F6, announcement date not stated)" in competitors
    assert "(F7 (Uncertain), announcement date not stated)" in competitors


def test_a_decision_answered_by_a_test_says_so_once(tmp_path, capsys):
    """The answer of a test begins with the words of the label itself, so the label is not printed again."""
    _, md, html = demo_report(tmp_path, capsys)
    for name, text in (("report.md", md), ("report.html", visible_text(html))):
        assert "Recorded test answer: Recorded test answer" not in text, name
        for line in ("Before choosing lenses: Recorded test answer: use the lenses firm-boundaries and "
                     "capacity-commitment.", "Before the final report: Recorded test answer: build the report."):
            assert line in text, (name, line)
