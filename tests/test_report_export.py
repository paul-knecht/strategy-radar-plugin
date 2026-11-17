import csv, io, json
import pytest
from radar import store
from radar.report import build as build_module
from radar.report.export import csv_safe, facts_csv, sources_csv
from radar.report.model import build_model
from radar.report.html import render_html
from radar.report.build import build_report, GateRefused
from radar.cli import main
from test_report_build import ready_run, LENSES
from helpers import make_run, add_source, add_fact, finish_run, find, minimal_analysis

def rows(text): return list(csv.DictReader(io.StringIO(text)))

NEW_COLUMNS = ["about_company", "report_company", "status_shown", "uncertain_reasons", "project_id", "project_name",
               "connections", "countries", "size_shown", "size_converted"]

def test_csv_safe_defuses_formulas():
    assert csv_safe("=SUM(A1:A9)") == "'=SUM(A1:A9)" and csv_safe("@cmd") == "'@cmd"
    assert csv_safe("+49 751") == "'+49 751" and csv_safe("-2 lines") == "'-2 lines"
    assert csv_safe("Competitor A") == "Competitor A" and csv_safe(None) == "" and csv_safe(2028) == "2028"
    assert csv_safe(["S1", "S2"]) == "S1; S2"

def test_csv_safe_defuses_tab_and_carriage_return_starts():
    # a tab separates cells for some programs, so the apostrophe goes right after it; a line break becomes a space
    assert csv_safe("\t=1+1") == "\t'=1+1" and csv_safe("\r=1+1") == "' =1+1"

def test_csv_safe_defuses_formulas_hidden_behind_invisible_or_blank_starts():
    line_breaks = {"\n": " ", chr(0x2028): " ", chr(0x2029): " "}
    for lead in (" ", "\n", chr(0x200B), chr(0xFEFF), chr(0x00A0), chr(0x2028), chr(0x2029), " \n" + chr(0x200B)):
        for sign in ("=", "+", "-", "@"):
            text = lead + sign + "1"
            written = "".join(line_breaks.get(ch, ch) for ch in text)
            assert csv_safe(text) == "'" + written, repr(text)

def test_csv_safe_defuses_full_width_signs():
    for code in (0xFF1D, 0xFF0B, 0xFF0D, 0xFF20):
        text = chr(code) + "SUM(A1)"
        assert csv_safe(text) == "'" + text, hex(code)
    assert csv_safe(chr(0x00A0) + chr(0xFF1D) + "1") == "'" + chr(0x00A0) + chr(0xFF1D) + "1"

def test_csv_safe_leaves_ordinary_text_unchanged():
    for text in ("a = b", "Competitor A - Site X", "1 + 1", "x@y.example", "", " ", chr(0x200B),
                 chr(0x201E) + "Gr" + chr(0xF6) + chr(0xDF) + "e" + chr(0x201C) + " der Anlage",
                 " Competitor A"):
        assert csv_safe(text) == text, repr(text)

def test_csv_safe_defuses_list_values_by_their_joined_text():
    assert csv_safe(["=x", "S1"]) == "'=x; S1"
    assert csv_safe(["S1", "=x"]) == "S1;' =x"       # read with a semicolon separator, "=x" would start a cell

def test_facts_table_has_one_row_per_fact_including_rejected(tmp_path):
    data = rows(facts_csv(build_model(ready_run(tmp_path), LENSES)))
    assert [(r["fact_id"], r["status"], r["status_reason"]) for r in data] == \
        [("F1", "confirmed", ""), ("F2", "rejected", "not_found")]
    first = data[0]
    assert (first["company"], first["stage"], first["data_class"], first["source_id"]) == ("Competitor A", "announced", "public", "S1")
    assert first["quote"] == "adds two high-speed syringe lines for customers"
    assert list(first)[:5] == ["fact_id", "illustrative", "status", "status_reason", "data_class"]
    assert data[1]["source_id"] == "S1" and data[1]["source_title"] == "Source S1"   # a rejected fact keeps its source

def test_facts_table_columns_are_exactly_the_agreed_ones(tmp_path):
    first = rows(facts_csv(build_model(ready_run(tmp_path), LENSES)))[0]
    assert list(first) == ["fact_id", "illustrative", "status", "status_reason", "data_class", "kind", "early_signal",
        "company", "home_company", "move_type", "stage", "site", "country", "what_added", "size_value", "size_unit",
        "announced", "planned_start", "access", "delivery", "statement", "quote", "quote_language", "quote_translation",
        "supporting_quotes", "supporting_sources", "supporting_translations", "source_id", "source_title",
        "source_publisher", "source_date", "source_url", *NEW_COLUMNS]

def test_facts_are_in_numeric_id_order_and_mark_the_home_company(tmp_path):
    run = make_run(tmp_path, home_company="Competitor A")
    add_source(run, "The expansion adds two high-speed syringe lines for customers, starting in 2028.")
    for _ in range(10):
        add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers",
             fields={"company": "Other Co"})
    finish_run(run, ["F1"])
    data = rows(facts_csv(build_model(run, LENSES)))
    assert [r["fact_id"] for r in data] == [f"F{n}" for n in range(1, 12)]
    assert data[0]["home_company"] == "yes" and data[10]["home_company"] == ""

def test_stated_sizes_with_a_sign_are_defused_too(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "The expansion adds two high-speed syringe lines for customers, starting in 2028.")
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers",
             fields={"size_value": "-2"})
    finish_run(run, ["F1"])
    assert rows(facts_csv(build_model(run, LENSES)))[0]["size_value"] == "'-2"

def test_sources_table_lists_based_on_and_provenance(tmp_path):
    run = make_run(tmp_path, mode="private", acknowledged=True)
    add_source(run, "The expansion adds two high-speed syringe lines for customers, starting in 2028.")
    add_source(run, "Internal review: the board approved two additional syringe lines for 2029.",
               data_class="internal", url="internal capacity review", based_on=["S1"])
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    finish_run(run, ["F1"])
    data = rows(sources_csv(build_model(run, LENSES)))
    assert (data[1]["data_class"], data[1]["based_on"], data[1]["supplied_by"], data[1]["basis"]) == \
        ("internal", "S1", "the tester", "own company document")
    assert list(data[0]) == ["source_id", "illustrative", "data_class", "type", "publisher", "title", "date", "url", "final_url", "speaker",
        "interest", "language", "saved_at", "saved_by", "access", "access_reason", "based_on", "supplied_by", "basis"]
    assert (data[0]["supplied_by"], data[0]["basis"]) == ("", "")

def test_formula_in_a_source_title_is_defused(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "The expansion adds two high-speed syringe lines for customers, starting in 2028.",
               title='=HYPERLINK("http://example.com","click")')
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    finish_run(run, ["F1"])
    model = build_model(run, LENSES)
    assert rows(sources_csv(model))[0]["title"].startswith("'=")
    assert rows(facts_csv(model))[0]["source_title"].startswith("'=")

def test_tables_use_crlf_and_keep_umlauts_and_commas(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "The expansion adds two high-speed syringe lines for customers, starting in 2028.",
               title="Größe, Qualität")
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    finish_run(run, ["F1"])
    text = sources_csv(build_model(run, LENSES))
    assert text.endswith("\r\n") and "\r\n" in text and "\n" not in text.replace("\r\n", "")
    assert rows(text)[0]["title"] == "Größe, Qualität"

def test_build_writes_four_files_and_tables_open_in_a_spreadsheet(tmp_path):
    run = ready_run(tmp_path)
    assert [p.name for p in build_report(run, LENSES)] == ["report.md", "report.html", "facts.csv", "sources.csv"]
    assert (run / "report" / "facts.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    assert (run / "report" / "sources.csv").read_bytes().startswith(b"\xef\xbb\xbf")

def test_confidential_run_names_its_tables_confidential(tmp_path):
    run = ready_run(tmp_path, mode="private", acknowledged=True)
    add_source(run, "Internal capacity review. " * 20, data_class="internal", url="internal capacity review")
    assert [p.name for p in build_report(run, LENSES)][2:] == ["facts-confidential.csv", "sources-confidential.csv"]

def test_a_leftover_table_of_the_other_naming_is_removed(tmp_path):
    run = ready_run(tmp_path, mode="private", acknowledged=True)
    add_source(run, "Internal capacity review. " * 20, data_class="internal", url="internal capacity review")
    (run / "report" / "facts.csv").write_text("old", encoding="utf-8")
    (run / "report" / "sources.csv").write_text("old", encoding="utf-8")
    build_report(run, LENSES)
    assert sorted(p.name for p in (run / "report").iterdir()) == \
        ["facts-confidential.csv", "report.html", "report.md", "sources-confidential.csv"]
    # and the other way round: a public rebuild removes the confidential files
    (run / "report" / "facts-confidential.csv").write_text("old", encoding="utf-8")
    public = ready_run(tmp_path / "second")
    (public / "report" / "facts-confidential.csv").write_text("old", encoding="utf-8")
    (public / "report" / "sources-confidential.csv").write_text("old", encoding="utf-8")
    build_report(public, LENSES)
    assert sorted(p.name for p in (public / "report").iterdir()) == \
        ["facts.csv", "report.html", "report.md", "sources.csv"]

def test_a_refused_build_writes_no_table(tmp_path):
    run = ready_run(tmp_path)
    store.write_analysis(run, minimal_analysis(fact_ids=["F1", "F2"]))
    with pytest.raises(GateRefused):
        build_report(run, LENSES)
    assert list((run / "report").iterdir()) == []

def test_nothing_is_written_when_a_render_fails(tmp_path, monkeypatch):
    run = ready_run(tmp_path)
    def boom(model): raise RuntimeError("render failed")
    monkeypatch.setattr(build_module, "sources_csv", boom)
    with pytest.raises(RuntimeError):
        build_report(run, LENSES)
    assert list((run / "report").iterdir()) == []

def test_build_report_command_lists_four_files(tmp_path, capsys):
    run = ready_run(tmp_path)
    assert main(["build-report", "--run", str(run), "--lenses", str(LENSES)]) == 0
    assert json.loads(capsys.readouterr().out) == {"built": [
        "report/report.md", "report/report.html", "report/facts.csv", "report/sources.csv"]}

def test_report_can_be_printed(tmp_path):
    doc = render_html(build_model(ready_run(tmp_path), LENSES))
    assert "@media print" in doc and "beforeprint" in doc and "afterprint" in doc
    assert [b["text"] for b in find(doc, "button", **{"class": "print"})] == ["Print or save as PDF"]
    assert find(doc, "button", **{"class": "print"})[0]["type"] == "button"
    assert "window.print()" in doc and doc.count("<script") == 1

def test_print_rules_hide_controls_keep_facts_together_and_repeat_the_banner(tmp_path):
    doc = render_html(build_model(ready_run(tmp_path), LENSES))
    css = doc.split("@media print", 1)[1].split("</style>")[0]
    assert ".tabs" in css and ".print" in css and "break-inside: avoid" in css
    assert ".banner.confidential" in css and "position: fixed" in css



# --- final fix I7: quoted cells, no line breaks, and formulas behind a semicolon or tab -----------

def test_csv_safe_defuses_a_formula_after_a_semicolon_or_a_tab():
    assert csv_safe("a;=1+1") == "a;'=1+1"
    assert csv_safe("a\t@SUM(A1)") == "a\t'@SUM(A1)"
    assert csv_safe("x;+1;-2") == "x;'+1;'-2"
    assert csv_safe("a;" + chr(0xFF1D) + "1") == "a;'" + chr(0xFF1D) + "1"       # judged on the NFKC probe
    assert csv_safe("a; =1") == "a;' =1"                                          # like a blank start of a cell
    for ordinary in ("a;b=1", "Plant A; Plant B", "x;y", "a\tb", "a;"):
        assert csv_safe(ordinary) == ordinary, ordinary


def test_csv_safe_turns_line_breaks_into_single_spaces():
    assert csv_safe("first line\nsecond\r\nthird\rfourth") == "first line second third fourth"


def test_every_cell_is_quoted_and_a_semicolon_stays_inside_its_cell(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "The expansion adds two lines; it starts in 2028, the company said.", title="Plan; phase two")
    add_fact(run, source_id="S1", primary_source=True, quote="The expansion adds two lines; it starts in 2028")
    finish_run(run, ["F1"])
    model = build_model(run, LENSES)
    text = facts_csv(model)
    for line in text.split("\r\n")[:-1]:
        assert line.startswith('"') and line.endswith('"'), line
    assert text.split("\r\n")[0].startswith('"fact_id","illustrative","status"')
    assert rows(text)[0]["quote"] == "The expansion adds two lines; it starts in 2028"
    assert rows(sources_csv(model))[0]["title"] == "Plan; phase two"
    assert len(next(csv.reader(io.StringIO(text.split("\r\n")[1])))) == len(rows(text)[0])


def test_the_german_demo_quote_survives_a_round_trip(tmp_path):
    from fixtures.build_demo_run import LENSES as DEMO_LENSES, build_demo_run
    run = build_demo_run(tmp_path)
    build_report(run, DEMO_LENSES)
    raw = (run / "report" / "facts-illustrative.csv").read_bytes()   # the demo is illustrative
    assert raw.startswith(b"\xef\xbb\xbf")
    table = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline="")))
    german = next(row for row in table if row["quote_language"] == "de")
    stored = next(fact for fact in store.read_facts(run).values() if fact["quote_language"] == "de")
    assert german["quote"] == stored["quote"] and "; es umfasst" in german["quote"] and "Abfüllwerk" in german["quote"]


def test_the_facts_table_marks_early_signals(tmp_path):
    from test_report_build import early_signal_run
    model = build_model(early_signal_run(tmp_path), LENSES)
    data = rows(facts_csv(model))
    assert list(data[0]).index("early_signal") == list(data[0]).index("kind") + 1
    by_id = {r["fact_id"]: r for r in data}
    assert by_id["F3"]["early_signal"] == "yes" and by_id["F3"]["status"] == "uncertain"
    assert by_id["F3"]["source_id"] == "S2" and by_id["F3"]["kind"] == "general"
    assert all(r["early_signal"] == "" for fact_id, r in by_id.items() if fact_id != "F3")
    assert [r["fact_id"] for r in data] == ["F1", "F2", "F3", "F4", "F5"]       # F2 is rejected and still listed
    assert rows(sources_csv(model))[1]["type"] == "permit"


def test_the_sources_table_has_a_final_url_column_next_to_the_address(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "The expansion adds two high-speed syringe lines for customers, starting in 2028.",
               final_url="https://other.example/page")
    add_source(run, "Competitor A confirmed two new syringe lines will open in 2028, the paper reported.")
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    finish_run(run, ["F1"])
    data = rows(sources_csv(build_model(run, LENSES)))
    columns = list(data[0])
    assert columns[columns.index("url") + 1] == "final_url"
    assert (data[0]["final_url"], data[1]["final_url"]) == ("https://other.example/page", "")

def test_a_formula_in_a_final_url_is_defused(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "The expansion adds two high-speed syringe lines for customers, starting in 2028.",
               final_url="=HYPERLINK(1)")
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    finish_run(run, ["F1"])
    assert rows(sources_csv(build_model(run, LENSES)))[0]["final_url"] == "'=HYPERLINK(1)"


# --- fix wave A1: the tables of an illustrative run say so, by their names and in every row -----------------------

def _table(path):
    return rows(path.read_bytes().decode("utf-8-sig"))


def test_an_illustrative_run_names_its_tables_illustrative_and_marks_every_row(tmp_path):
    run = ready_run(tmp_path, illustrative=True)
    assert [p.name for p in build_report(run, LENSES)] == \
        ["report.md", "report.html", "facts-illustrative.csv", "sources-illustrative.csv"]
    facts, sources = _table(run / "report" / "facts-illustrative.csv"), _table(run / "report" / "sources-illustrative.csv")
    assert len(facts) == 2 and all(row["illustrative"] == "yes" for row in facts)
    assert len(sources) == 1 and all(row["illustrative"] == "yes" for row in sources)


def test_the_illustrative_column_stands_next_to_the_id_and_is_empty_in_a_run_that_is_not_illustrative(tmp_path):
    model = build_model(ready_run(tmp_path), LENSES)
    facts, sources = rows(facts_csv(model)), rows(sources_csv(model))
    assert list(facts[0])[:2] == ["fact_id", "illustrative"] and list(sources[0])[:2] == ["source_id", "illustrative"]
    assert all(row["illustrative"] == "" for row in facts + sources)


def test_a_run_that_is_both_confidential_and_illustrative_names_both_marks_confidential_first(tmp_path):
    run = ready_run(tmp_path, illustrative=True, mode="private", acknowledged=True)
    add_source(run, "Internal capacity review. " * 20, data_class="internal", url="internal capacity review")
    assert [p.name for p in build_report(run, LENSES)][2:] == \
        ["facts-confidential-illustrative.csv", "sources-confidential-illustrative.csv"]
    assert all(row["illustrative"] == "yes" for row in _table(run / "report" / "sources-confidential-illustrative.csv"))


def test_a_leftover_table_of_any_other_naming_is_removed(tmp_path):
    run = ready_run(tmp_path, illustrative=True)
    names = [f"{kind}{marks}.csv" for kind in ("facts", "sources")
             for marks in ("", "-confidential", "-illustrative", "-confidential-illustrative")]
    for name in names:
        (run / "report" / name).write_text("old", encoding="utf-8")
    build_report(run, LENSES)
    assert sorted(p.name for p in (run / "report").iterdir()) == \
        ["facts-illustrative.csv", "report.html", "report.md", "sources-illustrative.csv"]


def test_the_illustrative_banner_repeats_on_every_printed_page_and_stacks_under_the_confidential_one(tmp_path):
    doc = render_html(build_model(ready_run(tmp_path, illustrative=True), LENSES))
    css = doc.split("@media print", 1)[1].split("</style>")[0]
    fixed = next(line for line in css.splitlines() if "position: fixed" in line and ".banner" in line)
    assert ".banner.confidential" in fixed and ".banner.illustrative" in fixed
    assert ".banner.confidential + .banner.illustrative" in css   # the second banner of a run that is both, below


# --- fix wave A14: the facts table holds the supporting quotes and their sources ------------------------------------

def test_the_facts_table_lists_each_fact_s_supporting_quotes_and_their_sources_in_order(tmp_path):
    from radar.demo import LENSES as DEMO_LENSES, build_demo_run
    run = build_demo_run(tmp_path)
    facts = store.read_facts(run)
    by_id = {row["fact_id"]: row for row in rows(facts_csv(build_model(run, DEMO_LENSES)))}
    for fact_id, fact in facts.items():
        entries = fact["supporting"]
        assert by_id[fact_id]["supporting_quotes"] == " | ".join(entry["quote"] for entry in entries), fact_id
        assert by_id[fact_id]["supporting_sources"] == " | ".join(entry["source_id"] for entry in entries), fact_id
    two = next(fact_id for fact_id, fact in facts.items() if len(fact["supporting"]) == 2)
    assert by_id[two]["supporting_quotes"].count(" | ") == 1
    assert any(row["supporting_quotes"] == "" for row in by_id.values())


def test_the_supporting_columns_follow_the_quote_columns(tmp_path):
    columns = list(rows(facts_csv(build_model(ready_run(tmp_path), LENSES)))[0])
    at = columns.index("quote_translation")
    assert columns[at + 1:at + 3] == ["supporting_quotes", "supporting_sources"]


def test_a_supporting_quote_that_starts_like_a_formula_is_defused_wherever_it_stands(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "The expansion adds two high-speed syringe lines for customers, starting in 2028.")
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers",
             supporting=[{"source_id": "S1", "quote": "=HYPERLINK(1) adds two lines here"},
                         {"source_id": "S1", "quote": "+49 adds two more lines here"}])
    finish_run(run, [])
    row = rows(facts_csv(build_model(run, LENSES)))[0]
    assert row["supporting_quotes"] == "'=HYPERLINK(1) adds two lines here | '+49 adds two more lines here"
    assert row["supporting_sources"] == "S1 | S1"


def test_the_raw_value_not_stated_stays_in_the_facts_table(tmp_path):
    from radar.demo import LENSES as DEMO_LENSES, build_demo_run
    run = build_demo_run(tmp_path)
    data = rows(facts_csv(build_model(run, DEMO_LENSES)))
    assert any(row["announced"] == "not_stated" for row in data)


# --- Task 12: the facts table carries the company, the shown status, the project, the connections and the tidy forms ---

OLD_COLUMNS = ["fact_id", "illustrative", "status", "status_reason", "data_class", "kind", "early_signal", "company",
               "home_company", "move_type", "stage", "site", "country", "what_added", "size_value", "size_unit",
               "announced", "planned_start", "access", "delivery", "statement", "quote", "quote_language",
               "quote_translation", "supporting_quotes", "supporting_sources", "supporting_translations", "source_id",
               "source_title", "source_publisher", "source_date", "source_url"]


def grouped_rows(tmp_path):
    from test_report_projects import group, moves_run
    run = moves_run(tmp_path)
    group(run)
    return run, {row["fact_id"]: row for row in rows(facts_csv(build_model(run, LENSES)))}


def test_the_facts_table_gains_the_new_columns_at_the_end(tmp_path):
    first = rows(facts_csv(build_model(ready_run(tmp_path), LENSES)))[0]
    assert list(first)[:len(OLD_COLUMNS)] == OLD_COLUMNS and list(first)[len(OLD_COLUMNS):] == NEW_COLUMNS


def test_each_fact_row_names_its_company_status_project_and_connections(tmp_path):
    _, by_id = grouped_rows(tmp_path)
    f1, f4, f5 = by_id["F1"], by_id["F4"], by_id["F5"]
    assert (f1["report_company"], f1["status_shown"], f1["uncertain_reasons"]) == ("Competitor A", "confirmed", "")
    assert (f1["project_id"], f1["project_name"]) == ("P2", "Competitor A, Plant North")
    assert (by_id["F3"]["project_id"], f4["project_id"], f4["project_name"]) == ("P2", "P1", "Competitor B, Exampleland")
    assert (f4["status"], f4["status_shown"], f4["uncertain_reasons"]) == ("uncertain", "single_source", "single_source")
    assert f4["connections"] == "" and f4["about_company"] == "" and f4["report_company"] == "Competitor B"
    assert (f5["about_company"], f5["report_company"], f5["connections"]) == \
        ("Competitor A", "Competitor A", "customer: Drug maker B")
    assert f5["project_id"] == "" and f5["project_name"] == "" and f5["countries"] == ""   # a general fact is in none


def test_without_a_grouping_the_table_names_each_move_s_own_project(tmp_path):
    from test_report_projects import moves_run
    by_id = {row["fact_id"]: row for row in rows(facts_csv(build_model(moves_run(tmp_path), LENSES)))}
    assert (by_id["F1"]["project_id"], by_id["F1"]["project_name"]) == \
        ("project-F1", "Competitor A: a second filling line, Plant North")


def test_a_rejected_fact_keeps_its_stored_columns_and_has_no_project_or_company(tmp_path):
    data = rows(facts_csv(build_model(ready_run(tmp_path), LENSES)))
    rejected = data[1]
    assert (rejected["status"], rejected["status_shown"], rejected["report_company"]) == ("rejected", "rejected", "")
    assert rejected["project_id"] == "" and rejected["connections"] == "" and rejected["company"] == "Competitor A"


def test_a_stored_unit_and_country_stay_as_stored_next_to_their_tidy_forms(tmp_path):
    run = make_run(tmp_path, companies=[{"name": "Competitor A", "other_names": [], "home": False}])
    add_source(run, "Competitor A adds two filling lines in the U.S. and in Canada, on 500 sqft of floor.")
    add_fact(run, source_id="S1", primary_source=True, quote="adds two filling lines in the U.S. and in Canada",
             fields={"country": "U.S. and Canada", "size_value": "160000", "size_unit": "ft2"})
    add_fact(run, source_id="S1", primary_source=True, quote="adds two filling lines in the U.S. and in Canada",
             fields={"country": None, "size_value": "1", "size_unit": "lines"})
    finish_run(run, ["F1"])
    first, second = rows(facts_csv(build_model(run, LENSES)))
    assert (first["country"], first["size_value"], first["size_unit"]) == ("U.S. and Canada", "160000", "ft2")
    assert first["countries"] == "United States | Canada"
    assert first["size_shown"] == "160000 ft²" and first["size_converted"] == "about 14900 m²"   # plain digits, no separators
    assert (second["countries"], second["size_shown"], second["size_converted"]) == ("", "1 line", "")


def test_new_cells_are_safe_from_formulas(tmp_path):
    from radar import projects
    run = make_run(tmp_path, companies=[{"name": "Competitor A", "other_names": [], "home": False}])
    add_source(run, "=Evil Corp sold its plant to =1+1 Holdings and to a partner. It adds a line in =Exampleland.")
    add_fact(run, kind="general", fields=None, source_id="S1", primary_source=True, about_company="=Evil Corp",
             statement="A plant was sold.", quote="=Evil Corp sold its plant to =1+1 Holdings and to a partner",
             connections=[{"party": "=1+1 Holdings", "tie": "buyer", "description": None},
                          {"party": None, "tie": "partner", "description": "=a partner"}])
    add_fact(run, source_id="S1", primary_source=True, quote="It adds a line in =Exampleland",
             fields={"country": "Canada and =Exampleland", "size_value": "-2", "size_unit": "lines"})
    finish_run(run, ["F1"])
    projects.record_projects(run, [{"name": "=SUM(A1) plan", "fact_ids": ["F2"]}], projects.GROUPER)
    first, second = rows(facts_csv(build_model(run, LENSES)))
    assert first["about_company"] == "'=Evil Corp"              # as stored, defused at the start of its cell
    assert first["connections"] == "buyer: 1+1 Holdings | partner: not named (=a partner)"   # no entry starts with a sign
    assert (second["project_name"], second["countries"], second["size_shown"]) == \
        ("'=SUM(A1) plan", "Canada | '=Exampleland", "'-2 lines")


def test_a_company_the_name_check_dropped_leaves_the_about_company_cell_empty(tmp_path):
    run = make_run(tmp_path, companies=[{"name": "Competitor A", "other_names": [], "home": False}])
    add_source(run, "Competitor A sold its plant to a partner. Competitor B opened a site.")
    add_fact(run, kind="general", fields=None, source_id="S1", primary_source=True, about_company="Competitor B",
             statement="A plant was sold.", quote="Competitor A sold its plant to a partner")
    add_fact(run, kind="general", fields=None, source_id="S1", primary_source=True, about_company="Competitor A",
             statement="A plant was sold.", quote="Competitor A sold its plant to a partner")
    finish_run(run, ["F1"])
    dropped, kept = rows(facts_csv(build_model(run, LENSES)))
    assert (dropped["about_company"], dropped["report_company"]) == ("", "")   # the quote never names Competitor B
    assert (kept["about_company"], kept["report_company"]) == ("Competitor A", "Competitor A")
