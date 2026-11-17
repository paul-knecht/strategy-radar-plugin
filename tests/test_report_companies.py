"""The report model's companies, shown status and tidy values (invented fixtures only)."""
import json

from radar import store, verify
from radar.report import companies
from radar.report.html import render_html
from radar.report.markdown import render_markdown
from radar.report.model import build_model, fact_notes, group_by_company, load_labels
from helpers import add_fact, add_source, find, make_run, minimal_analysis
from test_report_build import LENSES

PACK = [{"name": "Example Pharma", "other_names": ["Example Pharma Group"], "home": True},
        {"name": "Competitor A", "other_names": ["CompA"], "home": False},
        {"name": "Competitor B", "other_names": [], "home": False}]

TEXT_A = ("Competitor A will add a second filling line at Plant North by 2028. "
          "CompA also signed a supply deal with Drug maker B, its new customer, and with a buyer it did not name.")


def settle(run):
    verify.check_quotes(run)
    for fact_id in store.read_facts(run):
        verify.record_support(run, fact_id, True, "support-checker", "")
    verify.settle(run)


def finish(run, fact_ids=("F1",)):
    settle(run)
    store.write_analysis(run, minimal_analysis(list(fact_ids)))
    for name in store.CHECKPOINTS:
        store.record_checkpoint(run, name, "test", "ok")
    return build_model(run, LENSES)


def by_id(model):
    return {fact["id"]: fact for fact in model["facts"]}


def single_source_run(tmp_path):
    """F1: a capacity move from one source that is not the party itself: uncertain, single source only."""
    run = make_run(tmp_path, companies=PACK, home_company="Example Pharma")
    add_source(run, TEXT_A, publisher="Trade Journal", type="trade_press")
    add_fact(run, source_id="S1", primary_source=False)
    return run


# --- the shown status ------------------------------------------------------------------------------------------------

def test_a_fact_from_one_source_shows_one_source_only_and_keeps_its_status(tmp_path):
    model = finish(single_source_run(tmp_path))
    fact = by_id(model)["F1"]
    assert fact["status"] == "uncertain" and fact["shown_status"] == "single_source"
    assert model["status_line"]["single_source"] == 1 and model["status_line"]["uncertain"] == 1
    labels = load_labels()
    assert fact_notes(fact, labels) == [("status", "single_source", "One source only")]


def test_a_run_settled_before_codes_still_shows_one_source_only(tmp_path):
    run = single_source_run(tmp_path)
    settle(run)
    fact = store.read_facts(run)["F1"]
    del fact["uncertain_reasons"]
    store.write_fact(run, fact)
    model = finish(run)
    assert by_id(model)["F1"]["shown_status"] == "single_source"
    assert model["status_line"]["single_source"] == 1


def test_a_fact_named_in_a_message_carries_the_same_label_as_in_the_facts_list(tmp_path):
    run = single_source_run(tmp_path)
    model = finish(run)
    chain_fact = model["messages"][0]["chain"][0]["facts"][0]
    listed_fact = by_id(model)["F1"]
    assert chain_fact["shown_status"] == listed_fact["shown_status"] == "single_source"
    html = render_html(model)
    assert 'class="pill status-uncertain status-single_source">One source only</span>' in html
    assert "F1 (One source only)" in render_markdown(model)


def test_a_bare_fact_gets_its_shown_status_from_itself():
    labels = load_labels()
    bare = {"id": "F9", "status": "uncertain", "status_reason": verify.NOT_PRIMARY_REASON, "certainty": "firm",
            "source": {"type": "trade_press"}}
    assert fact_notes(bare, labels) == [("status", "single_source", "One source only")]
    assert fact_notes(dict(bare, source={"type": "permit"}), labels) == [("status", "uncertain", "Uncertain")]


def test_a_tentative_fact_from_one_source_shows_uncertain(tmp_path):
    run = make_run(tmp_path, companies=PACK)
    add_source(run, TEXT_A, publisher="Trade Journal", type="trade_press")
    add_fact(run, source_id="S1", primary_source=False, certainty="tentative", tentative_reason="planned only")
    fact = by_id(finish(run))["F1"]
    assert fact["status"] == "uncertain" and fact["shown_status"] == "uncertain"


def test_shown_status_by_the_codes_and_by_the_old_fallback():
    assert companies.shown_status({"status": "confirmed"}, {}) == "confirmed"
    assert companies.shown_status({"status": "rejected", "status_reason": "not_found"}, {}) == "rejected"
    coded = {"status": "uncertain", "uncertain_reasons": ["early_signal", "single_source"]}
    assert companies.shown_status(coded, {}) == "uncertain"
    assert companies.shown_status(dict(coded, uncertain_reasons=["single_source"]), {}) == "single_source"
    old = {"status": "uncertain", "status_reason": verify.NOT_PRIMARY_REASON, "certainty": "firm",
           "source_id": "S1"}
    assert companies.shown_status(old, {"S1": {"type": "news"}}) == "single_source"
    assert companies.shown_status(old, {"S1": {"type": "job_posting"}}) == "uncertain"
    assert companies.shown_status(dict(old, certainty="tentative"), {}) == "uncertain"
    assert companies.shown_status(dict(old, status_reason="planned only"), {}) == "uncertain"


def test_a_fact_date_is_read_from_the_start_of_the_source_date():
    assert companies.fact_date({"date": "2026-05-14"}) == "2026-05-14"
    assert companies.fact_date({"date": "2026-05-14T10:00:00Z"}) == "2026-05-14"
    assert companies.fact_date({"date": "2026-05"}) == "2026-05"
    assert companies.fact_date({"date": "2026"}) == "2026"
    for undated in ("May 2026", "20261", "2026-5-14", "2026-13", "", None, 2026):
        assert companies.fact_date({"date": undated}) is None, undated
    assert companies.fact_date(None) is None


# --- a fact's company ------------------------------------------------------------------------------------------------

def general(run, quote, about=None, connections=None, source_id="S1", statement="A general statement.", **over):
    return add_fact(run, kind="general", fields=None, source_id=source_id, primary_source=True, quote=quote,
                    statement=statement, about_company=about, connections=connections or [], **over)


def test_a_general_fact_without_a_company_is_not_about_one_company(tmp_path):
    run = make_run(tmp_path, companies=PACK)
    add_source(run, TEXT_A)
    general(run, "signed a supply deal with Drug maker B")
    model = finish(run)
    assert by_id(model)["F1"]["company"] == {"key": "none", "name": None, "group": "none", "home": False}
    assert model["companies"][-1] == {"key": "none", "name": None, "home": False, "group": "none", "facts": 1,
                                      "core_answer": None, "outside": 0}   # no project is about no company


def test_a_company_name_not_in_the_quote_is_dropped_and_counted(tmp_path):
    run = make_run(tmp_path, companies=PACK)
    add_source(run, TEXT_A)
    general(run, "signed a supply deal with Drug maker B", about="Competitor B")
    settle(run)
    record_status = store.read_facts(run)["F1"]["status"]
    model = finish(run)
    fact = by_id(model)["F1"]
    assert fact["company"]["key"] == "none" and model["how_made"]["names_dropped"]["companies"] == 1
    assert fact["status"] == record_status


def test_a_company_name_found_in_the_statement_or_a_translation_is_kept(tmp_path):
    run = make_run(tmp_path, companies=PACK)
    add_source(run, TEXT_A)
    general(run, "signed a supply deal with Drug maker B", about="Competitor B",
            statement="Competitor B signed a supply deal.")
    model = finish(run)
    assert by_id(model)["F1"]["company"]["name"] == "Competitor B"
    assert model["how_made"]["names_dropped"] == {"companies": 0, "parties": 0}


def test_a_capacity_move_keeps_its_company_from_its_fields(tmp_path):
    run = make_run(tmp_path, companies=PACK)
    add_source(run, TEXT_A)
    add_fact(run, source_id="S1", primary_source=True, fields={"company": "Competitor B"})   # name not in the quote
    model = finish(run)
    fact = by_id(model)["F1"]
    assert fact["company"] == {"key": "c3", "name": "Competitor B", "group": "pack", "home": False}
    assert model["how_made"]["names_dropped"]["companies"] == 0


def test_another_name_of_a_pack_company_shows_as_its_pack_name(tmp_path):
    run = make_run(tmp_path, companies=PACK)
    add_source(run, TEXT_A)
    add_fact(run, source_id="S1", primary_source=True, fields={"company": "CompA"})
    general(run, "CompA also signed a supply deal", about="CompA")
    model = finish(run)
    for fact_id in ("F1", "F2"):
        assert by_id(model)[fact_id]["company"] == {"key": "c2", "name": "Competitor A", "group": "pack",
                                                    "home": False}
    assert [(c["key"], c["name"], c["home"], c["facts"]) for c in model["companies"]] == [
        ("c1", "Example Pharma", True, 0), ("c2", "Competitor A", False, 2), ("c3", "Competitor B", False, 0)]


def test_an_old_run_without_companies_has_its_home_company_as_the_one_pack_company(tmp_path):
    run = make_run(tmp_path, home_company="Competitor A")
    add_source(run, TEXT_A)
    add_fact(run, source_id="S1", primary_source=True)
    model = finish(run)
    assert by_id(model)["F1"]["company"] == {"key": "c1", "name": "Competitor A", "group": "pack", "home": True}


def outside_run(tmp_path, based_on=False):
    """Three sources on Competitor X (outside the pack); S3 repeats S2 when `based_on`."""
    run = make_run(tmp_path, companies=PACK)
    for number in (1, 2, 3):
        add_source(run, f"Competitor X adds line {number} at Plant South.", publisher=f"Paper {number}",
                   based_on=["S2"] if based_on and number == 3 else [])
        add_fact(run, source_id=f"S{number}", primary_source=True, quote=f"Competitor X adds line {number}",
                 fields={"company": "Competitor X Inc."})
    add_source(run, "Competitor Y adds a line. Competitor Y adds a hall.")
    add_fact(run, source_id="S4", primary_source=True, quote="Competitor Y adds a line",
             fields={"company": "Competitor Y"})
    add_source(run, "Competitor Y adds a hall at Plant East.")
    add_fact(run, source_id="S5", primary_source=True, quote="Competitor Y adds a hall",
             fields={"company": "Competitor Y"})
    return run


def test_an_outside_company_in_three_sources_gets_its_own_entry_and_one_in_two_does_not(tmp_path):
    model = finish(outside_run(tmp_path))
    assert [(c["key"], c["name"], c["group"], c["facts"]) for c in model["companies"]] == [
        ("c1", "Example Pharma", "pack", 0), ("c2", "Competitor A", "pack", 0), ("c3", "Competitor B", "pack", 0),
        ("c4", "Competitor X", "own", 3), ("other", None, "other", 2)]
    facts = by_id(model)
    assert facts["F1"]["company"] == {"key": "c4", "name": "Competitor X", "group": "own", "home": False}
    assert facts["F4"]["company"] == {"key": "other", "name": "Competitor Y", "group": "other", "home": False}


def test_a_source_that_repeats_another_counts_once_toward_three(tmp_path):
    model = finish(outside_run(tmp_path, based_on=True))
    assert "Competitor X" not in [c["name"] for c in model["companies"]]
    assert by_id(model)["F1"]["company"]["key"] == "other"


def test_a_rejected_fact_and_a_dropped_name_do_not_count_toward_three(tmp_path):
    run = outside_run(tmp_path)
    general(run, "Competitor Y adds a hall", about="Competitor X", source_id="S5")   # name not in the quote
    settle(run)
    verify.withdraw_fact(run, "F3", "Taken back for the test.")
    model = finish(run)
    assert by_id(model)["F1"]["company"]["key"] == "other"
    assert model["how_made"]["names_dropped"]["companies"] == 1


def test_clusters_join_sources_whose_lineages_overlap():
    sources = {"S1": {"based_on": ["S9"]}, "S2": {"based_on": ["S9"]}, "S3": {"based_on": []},
               "S4": {"based_on": ["S5"]}, "S5": {"based_on": ["S3"]}}
    assert companies.count_clusters(["S1", "S2", "S3"], sources) == 2
    assert companies.count_clusters(["S1", "S3", "S4"], sources) == 2
    assert companies.count_clusters(["S1", "S1"], sources) == 1
    assert companies.count_clusters([], sources) == 0


# --- connections -----------------------------------------------------------------------------------------------------

def test_a_party_named_in_the_quote_is_kept_and_one_that_is_not_is_dropped(tmp_path):
    run = make_run(tmp_path, companies=PACK)
    add_source(run, TEXT_A)
    general(run, "CompA also signed a supply deal with Drug maker B, its new customer", about="Competitor A",
            statement="Competitor D buys from Competitor A.",
            connections=[{"party": "Drug maker B", "tie": "customer", "description": None},
                         {"party": "Competitor D", "tie": "buyer", "description": None}])
    model = finish(run)
    assert by_id(model)["F1"]["connections"] == [
        {"party": {"key": "other", "name": "Drug maker B", "group": "other", "home": False},
         "party_name": "Drug maker B", "tie": "customer", "description": None}]
    assert model["how_made"]["names_dropped"] == {"companies": 0, "parties": 1}


def test_an_unnamed_party_is_kept_with_its_description(tmp_path):
    run = make_run(tmp_path, companies=PACK)
    add_source(run, TEXT_A)
    general(run, "with a buyer it did not name", about=None,
            connections=[{"party": None, "tie": "buyer", "description": "a buyer it did not name"}])
    model = finish(run)
    assert by_id(model)["F1"]["connections"] == [
        {"party": None, "party_name": None, "tie": "buyer", "description": "a buyer it did not name"}]


def test_a_party_counts_toward_its_company_s_own_entry(tmp_path):
    run = make_run(tmp_path, companies=PACK)
    for number in (1, 2, 3):
        add_source(run, f"Competitor A sold plant {number} to Competitor Z.", publisher=f"Paper {number}")
        general(run, f"Competitor A sold plant {number} to Competitor Z", about="Competitor A",
                source_id=f"S{number}", connections=[{"party": "Competitor Z", "tie": "buyer", "description": None}])
    model = finish(run)
    assert ("c4", "Competitor Z", "own", 0) in [(c["key"], c["name"], c["group"], c["facts"])
                                                 for c in model["companies"]]
    assert by_id(model)["F1"]["connections"][0]["party"] == {"key": "c4", "name": "Competitor Z", "group": "own",
                                                             "home": False}


def party_only_run(tmp_path):
    """Competitor Z is named as the buyer in three facts from three sources and is the company of none of them."""
    run = make_run(tmp_path, companies=PACK)
    for number in (1, 2, 3):
        add_source(run, f"Competitor A sold plant {number} to Competitor Z.", publisher=f"Paper {number}")
        general(run, f"Competitor A sold plant {number} to Competitor Z", about="Competitor A",
                source_id=f"S{number}", connections=[{"party": "Competitor Z", "tie": "buyer", "description": None}])
    return run


def test_a_party_that_is_the_company_of_no_fact_is_marked_as_only_in_connections(tmp_path):
    model = finish(party_only_run(tmp_path))
    entries = {entry["name"]: entry for entry in model["companies"]}
    assert entries["Competitor Z"]["only_connections"] is True
    assert entries["Competitor A"]["only_connections"] is False and entries["Competitor B"]["only_connections"] is False


def test_the_markdown_says_a_party_appears_only_as_a_customer_partner_seller_or_buyer(tmp_path):
    md = render_markdown(finish(party_only_run(tmp_path)))
    assert "- **Competitor Z**: appears only as a customer, partner, seller or buyer" in md
    assert "Competitor Z**: 0 facts" not in md


def test_the_button_of_a_party_opens_the_connections_filtered_to_it(tmp_path):
    doc = render_html(finish(party_only_run(tmp_path)))
    button = [b for b in find(doc, "a", **{"class": "company-button"}) if b["text"].startswith("Competitor Z")][0]
    assert (button["href"], button["data-filter-company"], button["data-filter-view"]) == ("#view-connections", "c4",
                                                                                          "connections")
    assert "appears only as a customer, partner, seller or buyer" in button["text"] and "data-company-page" not in button
    assert not find(doc, "section", **{"data-company-head": "c4"})
    assert 'data-filter-view' in open(companies.__file__.replace("companies.py", "report.js")).read()


# --- tidy values, order and plain data -------------------------------------------------------------------------------

def test_a_capacity_move_carries_tidy_countries_and_size_and_a_general_fact_none(tmp_path):
    run = make_run(tmp_path, companies=PACK)
    add_source(run, TEXT_A)
    add_fact(run, source_id="S1", primary_source=True, fields={"country": "Exampleland", "size_value": "2.5",
                                                               "size_unit": "lines"})
    general(run, "signed a supply deal with Drug maker B")
    facts = by_id(finish(run))
    assert facts["F1"]["countries"] == ["Exampleland"]
    assert facts["F1"]["size"]["number"] == "2.5" and facts["F1"]["size"]["stated"].startswith("2.5 ")
    assert facts["F2"]["countries"] == [] and facts["F2"]["size"] is None
    assert facts["F1"]["date"] == "2026-05-14"


def test_facts_are_ordered_by_company_then_newest_first(tmp_path):
    run = make_run(tmp_path, companies=PACK)
    for date in ("2025-01-02", "2026-03", "not dated", "2026-03-01"):
        add_source(run, TEXT_A, date=date)
    add_fact(run, source_id="S1", primary_source=True, fields={"company": "Competitor B"})    # F1, B, 2025
    add_fact(run, source_id="S2", primary_source=True, fields={"company": "Competitor B"})    # F2, B, 2026-03
    add_fact(run, source_id="S3", primary_source=True, fields={"company": "Competitor B"})    # F3, B, undated
    add_fact(run, source_id="S4", primary_source=True)                                       # F4, A
    general(run, "signed a supply deal with Drug maker B", source_id="S4")   # F5, none
    add_fact(run, source_id="S2", primary_source=True, fields={"company": "Competitor Q"})    # F6, other
    add_fact(run, source_id="S2", primary_source=True, fields={"company": "Competitor B"})    # F7, B, 2026-03
    model = finish(run)
    assert [fact["id"] for fact in model["facts"]] == ["F4", "F2", "F7", "F1", "F3", "F6", "F5"]
    assert [c["key"] for c in model["companies"]] == ["c1", "c2", "c3", "other", "none"]
    assert set(companies.arrange(store.load_run(run), [], {})["by_id"]) == set()


def test_arrange_returns_the_arranged_facts_by_id(tmp_path):
    run = single_source_run(tmp_path)
    settle(run)
    fact = dict(store.read_facts(run)["F1"])
    sources = store.read_sources(run)
    arranged = companies.arrange(store.load_run(run), [fact], sources)
    assert set(arranged) == {"companies", "names_dropped", "by_id"}
    assert arranged["by_id"]["F1"] is fact and fact["company"]["key"] == "c2"
    assert set(fact) >= {"shown_status", "date", "company", "countries", "size", "connections"}


def test_two_small_outside_companies_stay_two_groups_of_competitors(tmp_path):
    run = make_run(tmp_path, companies=PACK)
    add_source(run, TEXT_A)
    add_fact(run, source_id="S1", primary_source=True, fields={"company": "Competitor Q"})
    add_fact(run, source_id="S1", primary_source=True, fields={"company": "Competitor R"})
    model = finish(run)
    assert [group["company"] for group in model["competitors"]] == ["Competitor Q", "Competitor R"]
    bare = [{"id": "F1", "kind": "capacity_move", "fields": {"company": "Competitor Q"}}]
    assert [group["company"] for group in group_by_company(bare, None)] == ["Competitor Q"]


def test_the_model_is_still_plain_data(tmp_path):
    run = make_run(tmp_path, companies=PACK)
    add_source(run, TEXT_A)
    add_fact(run, source_id="S1", primary_source=True, fields={"size_value": "2", "size_unit": "m2"})
    general(run, "CompA also signed a supply deal with Drug maker B", about="CompA",
            connections=[{"party": "Drug maker B", "tie": "customer", "description": None}])
    model = finish(run)
    assert json.loads(json.dumps(model)) == model


def test_a_baseline_joins_its_company_s_moves_under_another_name_or_with_a_legal_ending(tmp_path):
    run = make_run(tmp_path, companies=PACK)
    add_source(run, TEXT_A)
    add_fact(run, source_id="S1", primary_source=True, fields={"company": "Competitor A"})          # F1
    add_fact(run, source_id="S1", primary_source=True, fields={"company": "Aardvark Ltd"})          # F2
    general(run, "CompA also signed a supply deal with Drug maker B")                               # F3
    settle(run)
    analysis = minimal_analysis(["F1"])
    analysis["baselines"] = [{"company": "CompA", "fact_ids": ["F3"]}, {"company": "Aardvark Ltd", "fact_ids": ["F3"]}]
    store.write_analysis(run, analysis)
    for name in store.CHECKPOINTS:
        store.record_checkpoint(run, name, "test", "ok")
    groups = build_model(run, LENSES)["competitors"]
    assert [(g["company"], [m["id"] for m in g["moves"]], [b["id"] for b in g["baseline"]]) for g in groups] == [
        ("Aardvark", ["F2"], ["F3"]), ("Competitor A", ["F1"], ["F3"])]


def test_a_company_named_only_in_a_supporting_quote_or_a_translation_is_kept(tmp_path):
    run = make_run(tmp_path, companies=PACK)
    add_source(run, TEXT_A)
    add_source(run, "Competitor B also confirmed the supply deal with Drug maker B last week.")
    general(run, "signed a supply deal with Drug maker B", about="Competitor B",
            supporting=[{"source_id": "S2", "quote": "Competitor B also confirmed the supply deal"}])
    general(run, "signed a supply deal with Drug maker B", about="Competitor B",
            quote_translation="Competitor B signed a supply deal with Drug maker B")
    model = finish(run)
    assert [by_id(model)[f]["company"]["name"] for f in ("F1", "F2")] == ["Competitor B", "Competitor B"]
    assert model["how_made"]["names_dropped"] == {"companies": 0, "parties": 0}


def test_a_party_named_only_in_the_statement_is_dropped(tmp_path):
    run = make_run(tmp_path, companies=PACK)
    add_source(run, TEXT_A)
    general(run, "signed a supply deal with Drug maker B", statement="Competitor D buys from Drug maker B.",
            connections=[{"party": "Competitor D", "tie": "buyer", "description": None}])
    model = finish(run)
    assert by_id(model)["F1"]["connections"] == []
    assert model["how_made"]["names_dropped"] == {"companies": 0, "parties": 1}


def test_outside_companies_with_their_own_entry_are_sorted_without_regard_to_case(tmp_path):
    run = make_run(tmp_path, companies=[])
    for name in ("beta works", "Alpha Works", "Gamma Works"):
        for number in (1, 2, 3):
            source = add_source(run, f"{name} adds line {number} at Plant South.", publisher=f"{name} {number}")
            add_fact(run, source_id=source["id"], primary_source=True, quote=f"{name} adds line {number}",
                     fields={"company": name})
    model = finish(run)
    assert [c["name"] for c in model["companies"]] == ["Alpha Works", "beta works", "Gamma Works"]
