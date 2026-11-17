import json
from radar import store, verify
from radar.report.model import build_model
from test_report_build import early_signal_run, ready_run, LENSES
from helpers import add_source, add_fact, minimal_analysis

TEXT_B = "Competitor B opens a new plant in Exampleland, with first output planned for 2027."


def _settle(run, fact_ids):
    verify.check_quotes(run)
    for fact_id in fact_ids:
        verify.record_support(run, fact_id, True, "support-checker", "")
    verify.settle(run)


def with_second_company(run):
    """ready_run (F1 confirmed, F2 rejected) plus Competitor B: S2 and a confirmed F3."""
    add_source(run, TEXT_B, publisher="Competitor B", title="B opens a plant", date="2026-03-02")
    add_fact(run, source_id="S2", primary_source=True, quote="opens a new plant in Exampleland",
             statement="Competitor B opens a new plant.",
             fields={"company": "Competitor B", "move_type": "new_site", "announced": "2026-03-01",
                     "stage": "under_construction", "size_value": "1", "size_unit": "plants"})
    _settle(run, ["F3"])
    return run


def ids(items):
    return [item["id"] for item in items]


def test_status_line_counts(tmp_path):
    run = with_second_company(ready_run(tmp_path))
    # an uncertain fact (one source that is not primary) and a source that could not be read
    add_fact(run, source_id="S1", primary_source=False,
             quote="two high-speed syringe lines for customers, starting in 2028",
             statement="Two lines start in 2028.")
    add_source(run, "", access="not_accessible", access_reason="HTTP 403", copy_file=None,
               orig_file=None, copy_sha256=None)
    _settle(run, ["F4"])
    model = build_model(run, LENSES)
    assert model["status_line"] == {"confirmed": 2, "uncertain": 1, "single_source": 1, "rejected": 1, "sources": 3,
                                    "not_accessible": 1}
    # confirmed and uncertain, by company (both outside the pack: "other"), then newest source date first, then id
    assert ids(model["facts"]) == ["F1", "F4", "F3"]
    assert ids(model["rejected"]) == ["F2"]
    assert model["rejected"][0]["status_reason"] == "not_found"
    assert model["facts"][1]["status"] == "uncertain" and model["facts"][1]["shown_status"] == "single_source"


def test_chain_steps_carry_resolved_facts_and_lens(tmp_path):
    run = ready_run(tmp_path)
    model = build_model(run, LENSES)
    chain = model["messages"][0]["chain"]
    assert ids(chain[0]["facts"]) == ["F1"]
    assert chain[0]["facts"][0]["source"]["id"] == "S1"
    assert chain[0]["facts"][0]["data_class"] == "public"
    assert chain[0]["lens"] is None
    assert chain[1]["facts"] == [] and chain[2]["facts"] == []
    assert chain[1]["lens"] == {"id": "firm-boundaries", "name": "Where firms draw their boundaries"}
    assert model["messages"][0]["outside_view"]["facts"] == []


def test_sources_list_their_quotes(tmp_path):
    run = with_second_company(ready_run(tmp_path))
    fact = store.read_facts(run)["F3"]
    fact["supporting"] = [{"source_id": "S1", "quote": "adds two high-speed syringe lines for customers"}]
    store.write_fact(run, fact)
    _settle(run, ["F3"])
    model = build_model(run, LENSES)
    assert ids(model["sources"]) == ["S1", "S2"]
    s1, s2 = model["sources"]
    assert s1["quotes"] == [
        {"fact_id": "F1", "quote": "adds two high-speed syringe lines for customers", "translation": None},
        {"fact_id": "F3", "quote": "adds two high-speed syringe lines for customers", "translation": None}]
    assert s2["quotes"] == [{"fact_id": "F3", "quote": "opens a new plant in Exampleland", "translation": None}]
    assert all(q["fact_id"] != "F2" for source in model["sources"] for q in source["quotes"])  # rejected: not listed


def test_competitors_grouped_and_sorted(tmp_path):
    run = with_second_company(ready_run(tmp_path))
    add_fact(run, source_id="S1", primary_source=True, quote="two high-speed syringe lines for customers",
             statement="Competitor A adds two lines.",
             fields={"company": "  COMPETITOR a ", "announced": "2026-01-10"})
    add_fact(run, source_id="S1", primary_source=True, quote="for customers, starting in 2028", statement="x",
             fields={"company": "Aardvark Ltd", "announced": "2026-02-01"})
    _settle(run, ["F4", "F5"])
    competitors = build_model(run, LENSES)["competitors"]
    assert [c["company"] for c in competitors] == ["Aardvark", "Competitor A", "Competitor B"]   # tidy names
    a = competitors[1]
    assert a["home"] is False
    assert ids(a["moves"]) == ["F4", "F1"]                    # sorted by fields.announced; spellings grouped
    assert [m["fields"]["announced"] for m in a["moves"]] == ["2026-01-10", "2026-05-14"]
    assert ids(competitors[2]["moves"]) == ["F3"]


def test_lenses_in_order_of_first_use(tmp_path):
    analysis = minimal_analysis(["F1"], lens_id="capacity-commitment")
    analysis["messages"][0]["chain"].insert(2, {"kind": "reasoning", "text": "Boundaries shift.",
                                                "fact_ids": [], "lens_id": "firm-boundaries"})
    analysis["lens_notes"] = [{"lens_id": "firm-boundaries", "here": "Here the firm buys instead of builds."},
                              {"lens_id": "capacity-commitment", "here": "Here the plant is the signal."}]
    run = ready_run(tmp_path, analysis=analysis)
    lenses = build_model(run, LENSES)["lenses"]
    assert [lens["id"] for lens in lenses] == ["capacity-commitment", "firm-boundaries"]
    assert lenses[0]["name"] == "Capacity as a commitment"
    assert lenses[0]["here"] == "Here the plant is the signal."
    assert lenses[1]["here"] == "Here the firm buys instead of builds."
    assert len(lenses[1]["questions"]) == 3 and lenses[1]["originals"][0]["level"] == "reference_confirmed"


def test_home_company_comes_first_and_is_marked(tmp_path):
    run = with_second_company(ready_run(tmp_path, home_company="Competitor B"))
    model = build_model(run, LENSES)
    assert model["home_company"] == "Competitor B"
    assert model["competitors"][0]["company"] == "Competitor B" and model["competitors"][0]["home"] is True
    assert model["competitors"][1]["company"] == "Competitor A" and model["competitors"][1]["home"] is False


def test_top_level_keys_and_public_run(tmp_path):
    model = build_model(ready_run(tmp_path), LENSES)
    assert model["question"] == "Who adds capacity?" and model["run_id"] == "run1" and model["pack"] == "demo"
    assert model["mode"] == "public" and model["confidential"] is False and model["illustrative"] is False
    assert model["changes"] is None
    # F1 is the one move that counts (F2 is rejected): ungrouped, it is a project of its own
    assert model["projects"]["state"] == "none" and [p["id"] for p in model["projects"]["items"]] == ["project-F1"]
    assert model["core_answer"]["total"] == 1 and model["connections"] == []
    assert model["compliance"] == "All sources in this report are publicly available."
    assert model["how_made"]["search_log"] == [] and model["how_made"]["excluded"] == []
    assert [c["name"] for c in model["how_made"]["checkpoints"]] == ["lenses", "final_report"]
    assert model["how_made"]["checkpoints"][0]["answered_by"] == "test"


def test_private_run_with_a_non_public_source_is_confidential(tmp_path):
    run = ready_run(tmp_path, mode="private", acknowledged=True)
    add_source(run, "Internal capacity review. " * 20, data_class="internal", url="internal capacity review")
    model = build_model(run, LENSES)
    assert model["mode"] == "private" and model["confidential"] is True
    assert model["compliance"].startswith("Non-public sources were supplied")
    assert model["sources"][1]["data_class"] == "internal"


def test_sources_read_until_falls_back_to_the_latest_save_date(tmp_path):
    run = ready_run(tmp_path)
    assert "sources_read_until" not in store.load_run(run)       # init_run no longer presets it
    assert build_model(run, LENSES)["sources_read_until"] == "2026-11-12"   # the helper's saved_at
    add_source(run, "Another text for another source, long enough.", saved_at="2026-12-24T08:00:00Z")
    assert build_model(run, LENSES)["sources_read_until"] == "2026-12-24"
    stored = store.load_run(run); stored["sources_read_until"] = "2026-12-01"; store.save_run(run, stored)
    assert build_model(run, LENSES)["sources_read_until"] == "2026-12-01"   # a date set on the run still wins


def test_judgement_sections_resolve_fact_ids(tmp_path):
    analysis = minimal_analysis(["F1"], lens_id="firm-boundaries")
    analysis["demand_signals"] = [{"text": "Orders rise", "fact_ids": ["F1"]}]
    analysis["assumptions"] = [
        {"id": "A1", "text": "Demand grows", "support": "partial", "if_wrong": "Capacity idles", "fact_ids": []},
        {"id": "A2", "text": "Plants open on time", "support": "weak", "if_wrong": "Shortage lasts", "fact_ids": ["F1"]}]
    analysis["scenarios"] = [{"id": "SC1", "name": "Tight", "description": "d", "assumption_ids": ["A1", "A2"],
                              "signposts": [{"text": "Lead times rise", "fact_ids": ["F1"]}]}]
    analysis["predictions"] = [
        {"id": "P1", "message_id": "M1", "statement": "s", "by": "2028-12-31", "resolves_when": "w", "probability": 97},
        {"id": "P2", "message_id": "M1", "statement": "t", "by": "2028-12-31", "resolves_when": "w", "probability": 3}]
    analysis["calculations"] = [{"id": "C1", "label": "Moves", "operation": "count", "unit": None,
                                 "fact_ids": ["F1"], "of_fact_ids": [], "result": "1"}]
    analysis["decision_options"]["options"] = [{"name": "Wait", "for": [{"text": "Cheap", "fact_ids": ["F1"]}],
                                                "against": [{"text": "Slow", "fact_ids": []}]}]
    analysis["decision_options"]["framing_fact_ids"] = ["F1"]
    analysis["contradictions"] = [{"text": "Two dates", "fact_ids": ["F1"]}]
    model = build_model(ready_run(tmp_path, analysis=analysis), LENSES)
    assert ids(model["demand_signals"][0]["facts"]) == ["F1"]
    a1, a2 = model["assumptions"]
    assert (a1["support_label"], a2["support_label"]) == ("Partly supported", "Weakly supported")
    assert a1["facts"] == [] and ids(a2["facts"]) == ["F1"]
    scenario = model["scenarios"][0]
    assert ids(scenario["assumptions"]) == ["A1", "A2"] and scenario["assumptions"][0]["support_label"] == "Partly supported"
    assert ids(scenario["signposts"][0]["facts"]) == ["F1"]
    assert [p["word"] for p in model["predictions"]] == ["almost certain", "remote"]
    calc = model["calculations"][0]
    assert ids(calc["inputs"]) == ["F1"] and calc["whole"] == [] and calc["includes_uncertain"] is False
    option = model["decision_options"]["options"][0]
    assert ids(option["for"][0]["facts"]) == ["F1"] and option["against"][0]["facts"] == []
    assert ids(model["decision_options"]["framing_facts"]) == ["F1"]
    assert ids(model["contradictions"][0]["facts"]) == ["F1"]


def test_calculation_over_an_uncertain_fact_says_so(tmp_path):
    run = ready_run(tmp_path)
    add_fact(run, source_id="S1", primary_source=False, quote="two high-speed syringe lines for customers",
             statement="Two lines.", fields={"size_value": "2", "size_unit": "lines"})
    _settle(run, ["F3"])
    analysis = minimal_analysis(["F1"], lens_id="firm-boundaries")
    analysis["calculations"] = [{"id": "C1", "label": "Lines", "operation": "sum", "unit": "lines",
                                 "fact_ids": ["F1", "F3"], "of_fact_ids": [], "result": "4"}]
    store.write_analysis(run, analysis)
    assert build_model(run, LENSES)["calculations"][0]["includes_uncertain"] is True


def test_changes_are_carried_when_present(tmp_path):
    run = ready_run(tmp_path)
    store.write_changes(run, {"new": ["F9"], "gone": []})
    assert build_model(run, LENSES)["changes"] == {"new": ["F9"], "gone": []}
    assert json.loads(json.dumps(build_model(run, LENSES)))      # the model is plain data


def test_changes_file_that_is_not_a_json_object_gives_no_changes_view(tmp_path):
    run = ready_run(tmp_path)
    for text in ("[]", '"text"', "3", "null", "{not json", ""):
        (run / "changes.json").write_text(text, encoding="utf-8")
        assert build_model(run, LENSES)["changes"] is None, text
    (run / "changes.json").write_text("{}", encoding="utf-8")
    assert build_model(run, LENSES)["changes"] == {}


# --- early signals and baselines ------------------------------------------------------------------

def test_early_signals_stay_in_the_facts_list_and_can_be_told_apart(tmp_path):
    from radar.report.model import split_early_signals
    model = build_model(early_signal_run(tmp_path), LENSES)
    assert "early_signals" not in model                      # one list of facts, not a second one to learn
    assert "F3" in ids(model["facts"])
    f3 = next(fact for fact in model["facts"] if fact["id"] == "F3")
    assert (f3["status"], f3["early_signal"], f3["data_class"]) == ("uncertain", True, "public")
    others, early = split_early_signals(model["facts"])
    assert ids(early) == ["F3"] and "F3" not in ids(others) and "F1" in ids(others)
    assert model["status_line"]["uncertain"] == 1             # counted as an uncertain fact
    assert [quote["fact_id"] for source in model["sources"] if source["id"] == "S2" for quote in source["quotes"]] == ["F3"]


def test_a_fact_from_a_permit_source_is_listed_as_an_early_signal_even_without_the_mark(tmp_path):
    from radar.report.model import split_early_signals
    run = early_signal_run(tmp_path)
    fact = store.read_facts(run)["F3"]
    fact["early_signal"] = False                              # hand-made; the gate refuses it, the model still sorts it
    store.write_fact(run, fact)
    others, early = split_early_signals(build_model(run, LENSES)["facts"])
    assert ids(early) == ["F3"] and "F3" not in ids(others)


def test_a_baseline_sits_with_its_company_also_when_the_company_has_no_move(tmp_path):
    model = build_model(early_signal_run(tmp_path), LENSES)
    by_name = {c["company"]: c for c in model["competitors"]}
    assert list(by_name) == ["Competitor A", "Competitor C"]
    a, c = by_name["Competitor A"], by_name["Competitor C"]
    assert ids(a["moves"]) == ["F1"] and ids(a["baseline"]) == ["F4"]          # the baseline is the facts themselves
    assert a["baseline"][0]["statement"] == "Competitor A runs two plants with about 400 staff."
    assert a["baseline"][0]["source"]["id"] == "S3" and a["baseline"][0]["data_class"] == "public"
    assert c["moves"] == [] and c["home"] is False
    assert ids(c["baseline"]) == ["F5"]


def test_a_company_without_a_baseline_has_an_empty_baseline_list(tmp_path):
    model = build_model(early_signal_run(tmp_path, baselines=False), LENSES)
    assert [c["baseline"] for c in model["competitors"]] == [[]]


def test_baselines_are_matched_to_companies_by_normalised_name_and_the_home_company_comes_first(tmp_path):
    run = early_signal_run(tmp_path, home_company="Competitor C")
    analysis = store.read_analysis(run)
    analysis["baselines"].append({"company": "  COMPETITOR a ", "fact_ids": ["F1", "F4"]})   # F4 again: shown once
    store.write_analysis(run, analysis)
    competitors = build_model(run, LENSES)["competitors"]
    assert [c["company"] for c in competitors] == ["Competitor C", "Competitor A"]
    assert competitors[0]["home"] is True
    assert ids(competitors[1]["baseline"]) == ["F4", "F1"]


def test_a_baseline_company_with_no_name_in_any_move_keeps_the_spelling_it_was_given(tmp_path):
    run = early_signal_run(tmp_path, baselines=False)
    analysis = store.read_analysis(run)
    analysis["baselines"] = [{"company": "Aardvark  Ltd", "fact_ids": ["F4"]}]
    store.write_analysis(run, analysis)
    competitors = build_model(run, LENSES)["competitors"]
    assert [c["company"] for c in competitors] == ["Aardvark", "Competitor A"]   # by its tidy name


def test_the_model_with_early_signals_and_baselines_is_plain_data(tmp_path):
    model = build_model(early_signal_run(tmp_path), LENSES)
    assert json.loads(json.dumps(model))


def test_how_made_carries_the_recommendation_as_recorded_with_its_marks(tmp_path):
    from radar import recommend
    run = ready_run(tmp_path)
    assert build_model(run, LENSES)["how_made"]["recommendation"] is None
    entry = {"lens": "firm-boundaries", "question_part": "adds capacity", "why": "Why.", "facts": ["F1"],
             "missing": "Missing."}
    recommend.record_recommendation(run, LENSES, [entry], None, recommend.ADVISOR)
    recommend.record_link_check(run, "firm-boundaries", "F1", "doubt", recommend.READERS[0], "A doubt.")
    found = build_model(run, LENSES)["how_made"]["recommendation"]
    assert found["note"] is None and len(found["entries"]) == 1
    shown = found["entries"][0]
    assert (shown["lens"], shown["name"], shown["question_part"], shown["why"], shown["missing"]) == (
        "firm-boundaries", "Where firms draw their boundaries", "adds capacity", "Why.", "Missing.")
    assert [(link["fact"]["id"], link["doubts"]) for link in shown["links"]] == [("F1", 1)]
    assert link_sentences(shown) == ["The first reader doubts that this fact bears on the lens: A doubt.",
                                     "The second reader recorded nothing on this link."]
    assert [item["helper"] for item in found["helpers"]] == ["the lens advisor", "the first reader", "the second reader"]


def link_sentences(entry):
    return entry["links"][0]["sentences"]


def test_a_damaged_record_is_shown_as_damaged_in_the_model_and_a_missing_one_as_none(tmp_path):
    """Final review I3: a damaged record is not shown, but it is told apart from a missing one."""
    from radar import recommend
    run = ready_run(tmp_path)
    assert build_model(run, LENSES)["how_made"]["recommendation"] is None
    (run / recommend.RECORD).write_text('{"by": 3}', encoding="utf-8")
    assert build_model(run, LENSES)["how_made"]["recommendation"] == {
        "damaged": True, "stale": False, "note": None, "entries": [], "helpers": [], "flags": []}


def test_the_model_says_whether_the_record_is_stale_and_which_linked_fact_no_longer_counts(tmp_path):
    """Final review I3: the same comparison as the first stop's view (`recommend.is_stale`)."""
    from radar import recommend
    run = ready_run(tmp_path)
    entry = {"lens": "firm-boundaries", "question_part": "adds capacity", "why": "Why.", "facts": ["F1"],
             "missing": "Missing."}
    recommend.record_recommendation(run, LENSES, [entry], None, recommend.ADVISOR)
    found = build_model(run, LENSES)["how_made"]["recommendation"]
    assert (found["damaged"], found["stale"]) == (False, False)
    assert [link["counts"] for link in found["entries"][0]["links"]] == [True]
    verify.withdraw_fact(run, "F1", "Taken back for the test.")
    found = build_model(run, LENSES)["how_made"]["recommendation"]
    assert (found["damaged"], found["stale"]) == (False, True)
    assert [link["counts"] for link in found["entries"][0]["links"]] == [False]   # also before a settle
