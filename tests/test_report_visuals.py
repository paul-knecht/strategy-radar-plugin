import re
from pathlib import Path

from radar import diff, store
from radar.report import visuals
from radar.report.build import build_report
from radar.report.html import render_html
from radar.report.model import build_model, load_labels
from helpers import add_fact, add_source, find, finish_run, make_run
from test_report_build import LENSES, ready_run


def fact(i, company="Competitor A", status="confirmed", **fields):
    base = {"company": company, "move_type": "expansion", "site": "Site X", "country": "Country X",
            "what_added": "lines", "size_value": None, "size_unit": None, "announced": "2026-01-01",
            "planned_start": None, "access": "open", "delivery": None}
    base.update(fields)
    return {"id": f"F{i}", "kind": "capacity_move", "status": status, "fields": base}


def texts(html, tag, **attrs):
    return [element["text"] for element in find(html, tag, **attrs)]


# --- start_year ---

def test_start_year():
    assert visuals.start_year("Q3 2028") == 2028 and visuals.start_year("2027-06") == 2027
    assert visuals.start_year("not stated") is None and visuals.start_year(None) is None

def test_start_year_takes_the_first_four_digit_year_only():
    assert visuals.start_year("2027 or 2029") == 2027
    assert visuals.start_year("12345") is None and visuals.start_year("capacity 3000000 units") is None


# --- timeline ---

def test_timeline_places_bars_by_year_and_marks_uncertain():
    html = visuals.timeline([fact(1, planned_start="2027"), fact(2, company="Competitor B",
                            status="uncertain", planned_start="2029", access="captive"), fact(3)])
    assert [th["text"] for th in find(html, "th", scope="col")] == ["2027", "2028", "2029"]
    bars = find(html, "a")
    assert {"href": "#F1", "class": "bar open"}.items() <= bars[0].items()
    assert bars[1]["class"] == "bar captive uncertain"
    assert "Start not stated" in html and "#F3" in html

def test_timeline_puts_the_home_company_first():
    html = visuals.timeline([fact(1, planned_start="2027"), fact(2, company="Zeta Pharma", planned_start="2028")],
                            home_company="zeta pharma")
    rows = find(html, "tr")
    assert rows[1].get("class") == "home" and "Zeta Pharma" in rows[1]["text"] and "own company" in rows[1]["text"]
    assert "Competitor A" in rows[2]["text"]

def test_timeline_corner_cell_is_not_a_column_header_and_companies_are_row_headers():
    html = visuals.timeline([fact(1, planned_start="2027"), fact(2, company="Competitor B", planned_start="2028")])
    header_row = html[html.index("<tr"):html.index("</tr>")]
    assert "<td" in header_row and 'scope="col"' in header_row
    assert [th["text"] for th in find(html, "th", scope="col")] == ["2027", "2028"]
    assert [th["text"] for th in find(html, "th", scope="row")] == ["Competitor A", "Competitor B"]

def test_timeline_has_one_column_for_every_year_between_the_extremes():
    html = visuals.timeline([fact(1, planned_start="2027"), fact(2, planned_start="Q2 2030")])
    assert texts(html, "th", scope="col") == ["2027", "2028", "2029", "2030"]

def test_timeline_keeps_uncertain_and_non_public_facts_recognisable():
    secret = dict(fact(1, planned_start="2027"), data_class="internal")
    html = visuals.timeline([secret, fact(2, status="uncertain", planned_start="2027")])
    first, second = find(html, "a")
    assert first["class"] == "bar open non-public" and second["class"] == "bar open uncertain"
    assert "Internal document" in html and "Uncertain" in html          # the words, not only the colour

def test_timeline_without_any_year_lists_the_facts_and_draws_no_table():
    html = visuals.timeline([fact(1), fact(2, company="Competitor B")])
    assert find(html, "table") == []
    assert "Start not stated" in html and "#F1" in html and "#F2" in html

def test_timeline_of_nothing_is_empty():
    assert visuals.timeline([]) == ""

def test_timeline_ignores_facts_that_are_not_capacity_moves():
    general = {"id": "F9", "kind": "general", "status": "confirmed", "fields": None}
    assert visuals.timeline([general]) == ""

def test_timeline_escapes_model_text():
    html = visuals.timeline([fact(1, company="<script>alert(1)</script>", site='"><img src=x>', planned_start="2027")])
    assert "<script>" not in html and "<img" not in html
    assert "&lt;script&gt;" in html


# --- move grid ---

def test_move_grid_counts():
    html = visuals.move_grid([fact(1), fact(2), fact(3, move_type="acquisition")])
    row = find(html, "tr")[1]["text"]
    assert "Competitor A" in row and "2" in row and "1" in row

def test_move_grid_has_the_five_move_types_in_order_and_empty_cells_for_zero():
    html = visuals.move_grid([fact(1), fact(2), fact(3, move_type="acquisition")])
    assert texts(html, "th", scope="col") == ["Company", "New site", "Expansion", "Acquisition", "Partnership", "Closure"]
    assert texts(html, "td") == ["", "2", "1", "", ""]                  # the corner holds the heading "Company"
    assert texts(html, "th", scope="row") == ["Competitor A"]

def test_move_grid_names_uncertain_and_non_public_facts_in_a_count():
    secret = dict(fact(2, status="uncertain"), data_class="licensed")
    html = visuals.move_grid([fact(1), secret])
    cell = texts(html, "td")[1]
    assert cell.startswith("2") and "1 uncertain" in cell and "1 non-public" in cell

def test_the_grid_has_a_company_heading_and_plain_row_headings(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "Competitor C Inc. adds a line. Competitor C builds a site. Another Co opens a plant.")
    for quote, company in (("Competitor C Inc. adds a line", "Competitor C Inc."),
                           ("Competitor C builds a site", "competitor c"), ("Another Co opens a plant", "Another Co")):
        add_fact(run, source_id="S1", primary_source=True, quote=quote, fields={"company": company})
    finish_run(run, ["F1"])
    doc = doc_for(run)
    grid = find(doc, "table", **{"class": "grid"})
    assert grid
    html = doc[doc.index('<table class="grid">'):doc.index("</table>", doc.index('<table class="grid">'))]
    assert texts(html, "th", scope="col")[0] == "Company"                  # the corner says what the rows are
    assert find(html, "th", **{"class": "corner"}) and find(html, "td", **{"class": "corner"}) == []
    assert texts(html, "th", scope="row") == ["Another", "Competitor C"]    # one tidy name for "Competitor C Inc."
    css = (Path(visuals.__file__).parent / "report.css").read_text(encoding="utf-8")
    rule = re.search(r'\.grid th\[scope="row"\][^{]*\{([^}]*)\}', css).group(1)
    assert re.search(r"font-weight:\s*(400|normal)", rule) and re.search(r"background:\s*(none|transparent)", rule)


def test_move_grid_of_nothing_is_empty():
    assert visuals.move_grid([]) == ""


# --- delivery table ---

def test_delivery_table_omitted_without_history():
    assert visuals.delivery_table([fact(1), fact(2, delivery="not_yet")]) == ""
    html = visuals.delivery_table([fact(1, delivery="on_time"), fact(2, delivery="delayed")])
    assert "Competitor A" in html

def test_delivery_table_counts_each_outcome_per_company():
    html = visuals.delivery_table([fact(1, delivery="on_time"), fact(2, delivery="on_time"),
                                   fact(3, company="Competitor B", delivery="cancelled"),
                                   fact(4, delivery="unknown"), fact(5, company="Competitor C")])
    assert texts(html, "th", scope="col") == ["On time", "Delayed", "Cancelled"]
    assert texts(html, "th", scope="row") == ["Competitor A", "Competitor B"]
    assert texts(html, "td")[1:] == ["2", "", "", "", "", "1"]
    assert find(html, "table", **{"class": "delivery"})


# --- capacity bars ---

def test_capacity_bars_only_compare_same_units():
    html = visuals.capacity_bars([fact(1, size_value="2", size_unit="lines"),
                                  fact(2, size_value="4", size_unit="Lines", access="captive"),
                                  fact(3, size_value="300", size_unit="EUR million"),
                                  fact(4, size_value="large", size_unit="lines")])
    widths = [b["style"] for b in find(html, "div", **{"class": "bar-fill open"})] + \
             [b["style"] for b in find(html, "div", **{"class": "bar-fill captive"})]
    assert widths == ["width:50%", "width:100%"]
    assert "These figures are stated in different units and cannot be compared." in html
    assert "300 EUR million" in html and "large lines" in html

def test_bar_widths_are_whole_percentages_of_the_largest_rounded_half_up():
    html = visuals.capacity_bars([fact(1, size_value="1", size_unit="lines"), fact(2, size_value="8", size_unit="lines"),
                                  fact(3, size_value="3", size_unit="lines")])
    assert [b["style"] for b in find(html, "div", **{"class": "bar-fill"})] == ["width:13%", "width:100%", "width:38%"]

def test_a_unit_with_one_number_is_listed_not_drawn():
    html = visuals.capacity_bars([fact(1, size_value="2", size_unit="lines"),
                                  fact(2, size_value="300", size_unit="EUR million"),
                                  fact(3, size_value="300", size_unit="USD million")])
    assert find(html, "div", **{"class": "bar-fill"}) == []        # a currency is never turned into another
    assert "2 lines" in html and "300 EUR million" in html and "300 USD million" in html
    assert "different units" in html

def test_money_in_one_currency_is_compared_in_one_set_of_bars_with_its_stated_form_shown():
    html = visuals.capacity_bars([fact(1, size_value="300", size_unit="EUR million"),
                                  fact(2, size_value="0.15", size_unit="EUR billion")])
    assert texts(html, "h4") == ["EUR million"]
    assert [b["style"] for b in find(html, "div", **{"class": "bar-fill"})] == ["width:100%", "width:50%"]
    assert "150 EUR million (stated: 0.15 EUR billion)" in html and "different units" not in html

def test_a_group_where_every_value_is_zero_draws_empty_bars_not_an_error():
    html = visuals.capacity_bars([fact(1, size_value="0", size_unit="lines"), fact(2, size_value="0", size_unit="lines")])
    assert [b["style"] for b in find(html, "div", **{"class": "bar-fill"})] == ["width:0%", "width:0%"]

def test_capacity_bars_keep_uncertain_and_non_public_facts_recognisable():
    secret = dict(fact(2, size_value="4", size_unit="lines", status="uncertain"), data_class="internal")
    html = visuals.capacity_bars([fact(1, size_value="2", size_unit="lines"), secret])
    assert find(html, "div", **{"class": "bar-fill open uncertain non-public"})
    assert "Uncertain" in html and "Internal document" in html

def test_capacity_bars_link_every_fact_and_name_the_access():
    html = visuals.capacity_bars([fact(1, size_value="2", size_unit="lines"),
                                  fact(2, size_value="4", size_unit="lines", access="captive")])
    assert [a["href"] for a in find(html, "a")] == ["#F1", "#F2"]
    assert [note["text"] for note in find(html, "span", **{"class": "bar-note"})] == \
        ["Open to other customers", "Captive: for the company's own use"]

def test_facts_without_any_stated_size_are_left_out_of_the_bars():
    assert visuals.capacity_bars([fact(1), fact(2)]) == ""

def test_only_engine_computed_percentages_reach_style_attributes():
    html = visuals.capacity_bars([fact(1, company='"><i>', site="</div>", size_value="2", size_unit='lines" onmouseover="x'),
                                  fact(2, size_value="4", size_unit='lines" onmouseover="x'),
                                  fact(3, size_value="large", size_unit="lines")])
    assert re.findall(r'style="([^"]*)"', html) == ["width:50%", "width:100%"]
    assert "<i>" not in html and "&lt;/div&gt;" in html and ' onmouseover="' not in html
    assert not any("onmouseover" in key for element in find(html, "div") + find(html, "span") for key in element)


# --- totals ---

def calculation(inputs, **over):
    base = {"id": "C1", "label": "Lines announced", "operation": "sum", "unit": "lines", "result": "6",
            "inputs": inputs, "whole": [], "includes_uncertain": False}
    base.update(over)
    return base

def test_totals_list_the_result_unit_and_a_link_to_every_input():
    html = visuals.totals([calculation([fact(1), fact(2)])])
    item = find(html, "li", id="C1")[0]
    assert "Lines announced: 6 lines" in item["text"]
    assert [a["href"] for a in find(html, "a")] == ["#F1", "#F2"]
    assert find(html, "ul", **{"class": "totals"}) and "Includes uncertain" not in html

def test_totals_name_uncertain_inputs_and_shares_show_a_percent_sign():
    html = visuals.totals([calculation([fact(1, status="uncertain")], operation="share", result="25", unit=None,
                                       whole=[fact(1), fact(2)], includes_uncertain=True)])
    text = find(html, "li", id="C1")[0]["text"]
    assert "25%" in text and "Includes uncertain facts" in text and "Uncertain" in text

def test_a_large_total_gets_thousands_separators():
    html = visuals.totals([calculation([fact(1)], result="1200000", unit="m²")])
    assert "Lines announced: 1,200,000 m²" in find(html, "li", id="C1")[0]["text"]

def test_totals_of_nothing_are_empty():
    assert visuals.totals([]) == ""


# --- sites by country ---

def test_sites_by_country_puts_unknown_last():
    html = visuals.sites_by_country([fact(1, country=None), fact(2, country="Country B"), fact(3, country="Country A")])
    assert html.index("Country A") < html.index("Country B") < html.index("Country not stated")

def test_sites_by_country_lists_each_site_with_its_fact_links():
    html = visuals.sites_by_country([fact(1, country="Country B", site="Plant 1"), fact(2, country="Country B", site="Plant 1"),
                                     fact(3, country="Country b", site="Plant 2"), fact(4, country="Country A", site="Plant 3")])
    assert find(html, "ul", **{"class": "countries"})
    assert texts(html, "strong", **{"class": "country-name"}) == ["Country A", "Country B"]
    assert "Plant 1" in html and [a["href"] for a in find(html, "a")] == ["#F4", "#F1", "#F2", "#F3"]

def test_sites_by_country_names_uncertain_facts_and_escapes():
    html = visuals.sites_by_country([fact(1, status="uncertain", site="<b>x</b>")])
    assert "Uncertain" in html and "<b>" not in html

def test_sites_by_country_of_nothing_is_empty():
    assert visuals.sites_by_country([]) == ""


# --- changes ---

def test_changes_view_never_claims_withdrawal():
    changes = {"new": [{"fact_id": "F2"}], "changed": [{"fact_id": "F1", "previous_fact_id": "F1",
               "fields": {"planned_start": ["2027", "2028"]}}], "source_changed": [], "source_unavailable": [],
               "not_found_again": [{"previous_fact_id": "F9"}], "possible_matches": [], "unchanged": 3}
    html = visuals.changes_view(changes, {"F1": fact(1), "F2": fact(2)})
    assert "2027" in html and "2028" in html
    assert "This does not mean the plan was withdrawn. No source says so." in html

FULL_CHANGES = {
    "previous_run": "run0", "current_run": "run1",
    "new": [{"fact_id": "F2"}],
    "changed": [{"fact_id": "F1", "previous_fact_id": "F4", "fields": {"planned_start": ["2027", "2028"],
                                                                     "status": ["confirmed", "uncertain"]}}],
    "source_changed": [{"fact_id": "F3", "previous_fact_id": "F5", "url": "https://example.com/a"}],
    "source_unavailable": [{"previous_fact_id": "F6", "url": "https://example.com/b"}],
    "not_found_again": [{"previous_fact_id": "F9"}],
    "possible_matches": [{"fact_id": "F7", "previous_fact_id": "F8", "differing_field": "site"}],
    "predictions_due": [{"prediction_id": "P1", "statement": "Both lines start", "by": "2026-12-31"}],
    "unchanged": 3,
}
FACTS = {f"F{i}": fact(i) for i in (1, 2, 3, 7)}

def test_changes_view_has_a_heading_for_every_section_and_the_unchanged_count():
    html = visuals.changes_view(FULL_CHANGES, FACTS)
    assert texts(html, "h3") == ["New", "Changed", "Source text changed", "Source no longer available",
                                 "Not found again", "Possible matches to review", "Predictions due for review"]
    assert "Unchanged facts: 3" in html and "run0" in html and "run1" in html

def test_changes_view_shows_old_arrow_new_per_field():
    html = visuals.changes_view(FULL_CHANGES, FACTS)
    assert texts(html, "li", **{"class": "field-change"}) == ["Planned start: 2027 → 2028", "Status: Confirmed → Uncertain"]
    assert texts(html, "span", **{"class": "old"})[0] == "2027" and texts(html, "span", **{"class": "new"})[0] == "2028"

def test_changes_view_links_this_runs_facts_and_names_earlier_ones_as_text():
    html = visuals.changes_view(FULL_CHANGES, FACTS)
    assert {"href": "#F2", "data-view": "facts"}.items() <= find(html, "a", href="#F2")[0].items()
    assert not find(html, "a", href="#F9") and not find(html, "a", href="#F4")
    assert "F9" in html and "F8" in html
    assert find(html, "a", href="https://example.com/a")

def test_changes_view_shows_predictions_due_without_judging_them():
    html = visuals.changes_view(FULL_CHANGES, FACTS)
    item = texts(html, "li", **{"class": "prediction-due"})
    assert len(item) == 1 and "Both lines start" in item[0] and "2026-12-31" in item[0]
    assert "came true" not in html and "failed" not in html

def test_the_withdrawal_sentence_only_appears_with_not_found_again():
    assert "withdrawn" not in visuals.changes_view(dict(FULL_CHANGES, not_found_again=[]), FACTS)

def test_changes_view_tolerates_missing_keys_and_odd_shapes():
    assert visuals.changes_view({}, {}) == ""
    assert visuals.changes_view([], {}) == ""
    assert isinstance(visuals.changes_view({"new": "F1", "changed": [5, {"fact_id": "F1"}], "unchanged": "many"}, {}), str)
    html = visuals.changes_view({"new": [{"fact_id": "F7"}]}, {})
    assert "F7" in html and not find(html, "a", href="#F7")

def test_changes_view_escapes_model_text():
    facts = {"F2": dict(fact(2), statement="<script>alert(1)</script>")}
    changes = {"new": [{"fact_id": "F2"}], "changed": [{"fact_id": "F2", "previous_fact_id": "F2",
                                                          "fields": {"planned_start": ["<b>", "\"><i>"]}}],
               "source_changed": [{"fact_id": "F2", "url": "javascript:alert(1)"}]}
    html = visuals.changes_view(changes, facts)
    assert "<script>" not in html and "<b>" not in html and "<i>" not in html
    assert not find(html, "a", href="javascript:alert(1)")


# --- the pages: the visuals are placed in their views ---

def doc_for(run):
    return render_html(build_model(run, LENSES))

def delivered_run(tmp_path):
    run = make_run(tmp_path, home_company="Competitor A")
    add_source(run, "The expansion adds two high-speed syringe lines for customers, starting in 2028.")
    add_source(run, "Competitor B delivered its new filling line on time in 2025, the company said.")
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    add_fact(run, source_id="S2", primary_source=True, quote="delivered its new filling line on time in 2025",
             fields={"company": "Competitor B", "site": "Plant West", "country": "Otherland", "planned_start": "2026",
                     "delivery": "on_time", "size_value": "3", "access": "captive"})
    finish_run(run, ["F1"])
    return run

def test_projects_view_holds_the_grid_delivery_table_and_countries(tmp_path):
    doc = doc_for(delivered_run(tmp_path))
    section = doc[doc.index('id="view-projects"'):doc.index('id="view-connections"')]
    for table in ("grid", "delivery"):
        assert find(section, "table", **{"class": table}), table
    assert find(section, "table", **{"class": "moves"}) == []
    assert find(section, "ul", **{"class": "countries"}) and "Otherland" in section
    for heading in ("Moves by type", "Delivery record", "Sites by country"):
        assert heading in texts(section, "h3"), heading

def test_projects_view_draws_capacity_bars_when_units_match(tmp_path):
    doc = doc_for(delivered_run(tmp_path))                 # F1 is 2 lines, F2 is 3 lines
    section = doc[doc.index('id="view-projects"'):doc.index('id="view-connections"')]
    assert [b["style"] for b in find(section, "div", **{"class": "bar-fill"})] == ["width:67%", "width:100%"]
    assert "Capacity" in texts(section, "h3")

def sized_run(tmp_path, *sizes):
    """One capacity move per size, each at its own site: `sizes` are (value, unit) pairs."""
    run = make_run(tmp_path)
    add_source(run, "Competitor A builds a large hall at Plant One. Competitor A builds a second hall at Plant Two. "
                    "Competitor A builds a third hall at Plant Three.")
    for number, (value, unit) in enumerate(sizes, start=1):
        site = ("One", "Two", "Three")[number - 1]
        add_fact(run, source_id="S1", primary_source=True,
                 quote=f"Competitor A builds a {('large', 'second', 'third')[number - 1]} hall at Plant {site}",
                 fields={"site": f"Plant {site}", "size_value": value, "size_unit": unit})
    finish_run(run, ["F1"])
    return run

def bars_of(doc):
    start = doc.index('class="projects-more"')
    return doc[start:doc.index('id="view-connections"')]

def test_m2_and_sqm_sizes_are_compared_in_one_set_of_bars(tmp_path):
    doc = doc_for(sized_run(tmp_path, ("2000", "m2"), ("1500", "sqm"), ("lots", "lines")))
    html = bars_of(doc)
    assert texts(html, "h4")[:1] == ["m²"] and texts(html, "h4").count("m²") == 1
    assert [b["style"] for b in find(html, "div", **{"class": "bar-fill"})] == ["width:100%", "width:75%"]
    assert "2,000 m²" in html and "1,500 m²" in html and "different units" in html and "lots lines" in html

def test_bare_facts_are_compared_by_their_tidy_unit_too():
    html = visuals.capacity_bars([fact(1, size_value="2000", size_unit="m2"), fact(2, size_value="1000", size_unit="Sqm")])
    assert [b["style"] for b in find(html, "div", **{"class": "bar-fill"})] == ["width:100%", "width:50%"]

def test_a_size_in_square_feet_shows_its_square_metres_and_what_was_stated(tmp_path):
    doc = doc_for(sized_run(tmp_path, ("21528", "ft2"), ("3000", "m²")))
    html = bars_of(doc)
    rows = find(html, "li", **{"class": "bar-row"})
    assert "about 2,000 m² (stated: 21,528 ft²)" in rows[0]["text"] and "3,000 m²" in rows[1]["text"]
    assert [b["style"] for b in find(html, "div", **{"class": "bar-fill"})] == ["width:67%", "width:100%"]
    assert texts(html, "h4")[0] == "m²"

def test_a_converted_size_is_rounded_and_large_numbers_get_separators(tmp_path):
    html = bars_of(doc_for(sized_run(tmp_path, ("160000", "ft2"), ("20000", "m²"))))
    rows = find(html, "li", **{"class": "bar-row"})
    assert "about 14,900 m² (stated: 160,000 ft²)" in rows[0]["text"] and "20,000 m²" in rows[1]["text"]

def test_the_stated_size_is_not_repeated_when_nothing_was_converted(tmp_path):
    html = bars_of(doc_for(sized_run(tmp_path, ("2000", "m2"), ("1500", "sqm"))))
    assert "stated:" not in html and "about " not in html

def test_sites_are_listed_under_each_of_their_tidy_countries(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "Competitor A builds a plant in the USA. Competitor A builds a plant in Germany and France.")
    add_fact(run, source_id="S1", primary_source=True, quote="Competitor A builds a plant in the USA",
             fields={"country": "U.S.", "site": "Plant One"})
    add_fact(run, source_id="S1", primary_source=True, quote="Competitor A builds a plant in Germany and France",
             fields={"country": "Germany and France", "site": "Plant Two"})
    finish_run(run, ["F1"])
    html = bars_of(doc_for(run))
    assert texts(html, "strong", **{"class": "country-name"}) == ["France", "Germany", "United States"]
    assert find(html, "ul", **{"class": "countries"})[0]["text"].count("Plant Two") == 2

def test_timeline_view_holds_the_timeline_table(tmp_path):
    doc = doc_for(delivered_run(tmp_path))
    section = doc[doc.index('id="view-timeline"'):doc.index('id="view-scenarios"')]
    assert find(section, "table", **{"class": "timeline"}) and find(section, "tr", **{"class": "home"})
    assert texts(section, "th", scope="col") == ["2026", "2027", "2028"]
    assert find(doc[:doc.index('id="view-timeline"')], "table", **{"class": "timeline"}) == []

def test_a_run_without_delivery_history_has_no_delivery_table(tmp_path):
    assert find(doc_for(ready_run(tmp_path)), "table", **{"class": "delivery"}) == []

def test_changes_view_page_uses_the_run_facts(tmp_path):
    run = ready_run(tmp_path)
    store.write_changes(run, {"previous_run": "run0", "current_run": "run1", "new": [{"fact_id": "F1"}],
                              "not_found_again": [{"previous_fact_id": "F9"}], "unchanged": 0})
    doc = doc_for(run)
    section = doc[doc.index('id="view-changes"'):]
    assert find(section, "a", href="#F1") and "No source says so." in section


# --- the Markdown report ---

def sealed(run, changes):
    """`changes` with the two digests `radar compare` would store for the run as it is, so a hand-written comparison
    passes the gate."""
    record = store.load_run(run)
    changes = dict({"current_run": record.get("run_id")}, **changes,
                   facts_digest=diff.facts_digest(store.read_facts(run)),
                   previous_illustrative=record.get("illustrative") is True)
    return dict(changes, file_digest=diff.file_digest(changes))

def built_markdown(run):
    build_report(run, LENSES)
    return (run / "report" / "report.md").read_text(encoding="utf-8")

def test_markdown_has_the_move_grid_and_delivery_table(tmp_path):
    md = built_markdown(delivered_run(tmp_path))
    labels = load_labels()
    competitors = md.split("## Projects")[1].split("\n## ")[0]
    assert f"### {labels['sec_grid']}" in competitors and f"### {labels['sec_delivery']}" in competitors
    assert "| Company | New site | Expansion | Acquisition | Partnership | Closure |" in competitors
    assert "| Competitor A |  | 1 |  |  |  |" in competitors
    assert "| Company | On time | Delayed | Cancelled |" in competitors and "| Competitor B | 1 |  |  |" in competitors

def test_markdown_without_delivery_history_has_no_delivery_table(tmp_path):
    assert "Delivery record" not in built_markdown(ready_run(tmp_path))

def test_markdown_changes_use_the_fixed_headings_and_never_claim_withdrawal(tmp_path):
    run = ready_run(tmp_path)
    store.write_changes(run, sealed(run, dict(FULL_CHANGES, new=[{"fact_id": "F1"}])))
    section = built_markdown(run).split("## What changed since last time")[1]
    for heading in ("### New", "### Changed", "### Source text changed", "### Source no longer available",
                    "### Not found again", "### Possible matches to review", "### Predictions due for review"):
        assert heading in section, heading
    assert "Planned start: 2027 → 2028" in section and "Unchanged facts: 3" in section
    assert "This does not mean the plan was withdrawn. No source says so." in section
    assert "not_found_again" not in section and "Both lines start" in section and "2026-12-31" in section

def test_markdown_changes_escape_model_text(tmp_path):
    run = ready_run(tmp_path)
    store.write_changes(run, sealed(run, {"changed": [{"fact_id": "F1", "previous_fact_id": "F1",
                                                        "fields": {"planned_start": ["<b>x</b>", "[a](http://evil.example)"]}}]}))
    section = built_markdown(run).split("## What changed since last time")[1]
    assert "<b>" not in section and "[a](" not in section
