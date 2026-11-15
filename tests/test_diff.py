import json
from datetime import date

import pytest

from radar import store, verify
from radar.cli import main
from radar.diff import compare_runs, fact_key
from helpers import add_fact, add_source, make_run, minimal_analysis

TEXT = ("Competitor A will add a second filling line at Plant North by 2028. "
        "Competitor A will add a second filling line at Plant North East by 2028. "
        "Competitor A will add a third filling line at Plant North by 2029.")
FIRST = "Competitor A will add a second filling line at Plant North by 2028."
URL = "https://example.com/a"
LATER_TEXT = TEXT + " A later sentence was added to the page."


def _settle(run, general=()):
    """Turn the named facts into general facts, then check, support and settle every fact."""
    for fact_id in general:
        fact = store.read_facts(run)[fact_id]
        fact["kind"], fact["fields"] = "general", None
        store.write_fact(run, fact)
    verify.check_quotes(run)
    for fact_id in store.read_facts(run):
        verify.record_support(run, fact_id, True, "support-checker", "")
    verify.settle(run)


def _make(root, run_id, facts, text, url, access="ok", **run_over):
    """A run with one source S1 and one settled fact per spec (add_fact keyword arguments). `run_over` goes to
    make_run (mode, acknowledged, illustrative)."""
    run = make_run(root, run_id=run_id, **run_over)
    if access == "ok":
        add_source(run, text, url=url)
    else:
        add_source(run, "", url=url, access=access, copy_file=None, copy_sha256=None)
    general = []
    for spec in facts:
        spec = dict(spec)
        is_general = spec.pop("general", False)
        spec.setdefault("primary_source", True)
        fact = add_fact(run, source_id="S1", quote=spec.pop("quote", FIRST), **spec)
        if is_general:
            general.append(fact["id"])
    _settle(run, general)
    return run


@pytest.fixture
def two_runs(tmp_path):
    def build(previous_facts, current_facts, previous_text=TEXT, current_text=TEXT,
              previous_url=URL, current_url=URL, current_access="ok"):
        previous = _make(tmp_path / "prev", "r1", previous_facts, previous_text, previous_url)
        current = _make(tmp_path / "cur", "r2", current_facts, current_text, current_url, current_access)
        return previous, current
    return build


def test_fact_key_ignores_case_and_spacing():
    a = {"fields": {"company": "Competitor  A", "site": "Site X", "move_type": "expansion", "what_added": "Syringe lines"}}
    b = {"fields": {"company": "competitor a", "site": "site x", "move_type": "expansion", "what_added": "syringe LINES"}}
    assert fact_key(a) == fact_key(b)
    assert fact_key(a) == ("competitor a", "site x", "expansion", "syringe lines")


def test_fact_key_turns_missing_parts_into_empty_text():
    fact = {"fields": {"company": "Competitor A", "site": None, "move_type": "expansion"}}
    assert fact_key(fact) == ("competitor a", "", "expansion", "")


def test_new_fact(two_runs):
    previous, current = two_runs([{}], [{}, {"fields": {"site": "Plant South"}}])
    result = compare_runs(previous, current, today=date(2026, 11, 12))
    assert result["new"] == [{"fact_id": "F2"}]
    assert result["unchanged"] == 1
    assert result["previous_run"] == "r1" and result["current_run"] == "r2"
    assert result["changed"] == [] and result["not_found_again"] == []


def test_changed_field(two_runs):
    previous, current = two_runs([{}], [{"fields": {"planned_start": "2029"}}])
    result = compare_runs(previous, current)
    assert result["changed"] == [{"fact_id": "F1", "previous_fact_id": "F1",
                                  "fields": {"planned_start": ["2028", "2029"]}}]
    assert result["unchanged"] == 0 and result["source_changed"] == []


def test_changed_status(two_runs):
    previous, current = two_runs([{}], [{"certainty": "tentative", "tentative_reason": "one unnamed source"}])
    result = compare_runs(previous, current)
    assert result["changed"] == [{"fact_id": "F1", "previous_fact_id": "F1",
                                  "fields": {"status": ["confirmed", "uncertain"]}}]


def test_case_and_spacing_in_key_fields_do_not_count_as_a_change(two_runs):
    previous, current = two_runs([{}], [{"fields": {"company": "competitor  a", "site": "PLANT north"}}])
    result = compare_runs(previous, current)
    assert result["unchanged"] == 1 and result["changed"] == [] and result["new"] == []


def test_reworded_statement_is_unchanged(two_runs):
    previous, current = two_runs([{}], [{"statement": "A second filling line is coming to Plant North."}])
    result = compare_runs(previous, current)
    assert result["unchanged"] == 1 and result["changed"] == []


def test_source_changed(two_runs):
    previous, current = two_runs([{}], [{}], current_text=LATER_TEXT)
    result = compare_runs(previous, current)
    assert result["source_changed"] == [{"fact_id": "F1", "previous_fact_id": "F1", "url": URL}]
    assert result["unchanged"] == 0 and result["changed"] == []


def test_a_changed_field_wins_over_a_changed_source(two_runs):
    previous, current = two_runs([{}], [{"fields": {"planned_start": "2029"}}], current_text=LATER_TEXT)
    result = compare_runs(previous, current)
    assert [c["fact_id"] for c in result["changed"]] == ["F1"] and result["source_changed"] == []


def test_same_copy_at_a_new_address_is_unchanged(two_runs):
    previous, current = two_runs([{}], [{}], current_url="https://example.com/moved", current_text=LATER_TEXT)
    result = compare_runs(previous, current)
    assert result["unchanged"] == 1 and result["source_changed"] == []


def test_source_unavailable(two_runs):
    previous, current = two_runs([{}], [], current_access="not_accessible")
    result = compare_runs(previous, current)
    assert result["source_unavailable"] == [{"previous_fact_id": "F1", "url": URL}]
    assert result["not_found_again"] == []


def test_source_unavailable_needs_the_same_address(two_runs):
    previous, current = two_runs([{}], [], current_url="https://example.com/other", current_access="not_accessible")
    result = compare_runs(previous, current)
    assert result["source_unavailable"] == [] and result["not_found_again"] == [{"previous_fact_id": "F1"}]


def test_a_reachable_source_does_not_make_a_fact_unavailable(two_runs):
    previous, current = two_runs([{}], [])
    result = compare_runs(previous, current)
    assert result["source_unavailable"] == [] and result["not_found_again"] == [{"previous_fact_id": "F1"}]


def test_not_found_again(two_runs):
    previous, current = two_runs([{}], [])
    result = compare_runs(previous, current)
    assert result["not_found_again"] == [{"previous_fact_id": "F1"}]
    assert result["new"] == [] and result["unchanged"] == 0


def test_possible_match_is_flagged_not_guessed(two_runs):
    previous, current = two_runs(
        [{}], [{"quote": "Competitor A will add a second filling line at Plant North East by 2028.",
                "fields": {"site": "Plant North East"}}])
    result = compare_runs(previous, current)
    assert result["possible_matches"] == [{"fact_id": "F1", "previous_fact_id": "F1", "differing_field": "site"}]
    assert result["new"] == [] and result["not_found_again"] == [] and result["source_unavailable"] == []
    assert result["unchanged"] == 0 and result["changed"] == []


def test_possible_match_names_whichever_part_differs(two_runs):
    previous, current = two_runs([{}], [{"fields": {"what_added": "a third filling line"}}])
    result = compare_runs(previous, current)
    assert result["possible_matches"] == [{"fact_id": "F1", "previous_fact_id": "F1", "differing_field": "what_added"}]


def test_two_differing_parts_is_not_a_possible_match(two_runs):
    previous, current = two_runs([{}], [{"fields": {"site": "Plant West", "what_added": "a third filling line"}}])
    result = compare_runs(previous, current)
    assert result["possible_matches"] == [] and result["new"] == [{"fact_id": "F1"}]
    assert result["not_found_again"] == [{"previous_fact_id": "F1"}]


def test_a_previous_fact_with_an_exact_match_is_never_a_possible_match(two_runs):
    previous, current = two_runs([{}], [{}, {"fields": {"site": "Plant South"}}])
    result = compare_runs(previous, current)
    assert result["possible_matches"] == [] and result["new"] == [{"fact_id": "F2"}]
    assert result["unchanged"] == 1


def test_a_previous_fact_is_used_for_one_possible_match_only(two_runs):
    previous, current = two_runs([{}], [{"fields": {"site": "Plant South"}}, {"fields": {"site": "Plant East"}}])
    result = compare_runs(previous, current)
    assert result["possible_matches"] == [{"fact_id": "F1", "previous_fact_id": "F1", "differing_field": "site"}]
    assert result["new"] == [{"fact_id": "F2"}]


def test_a_possible_match_wins_over_an_unavailable_source(tmp_path):
    previous = _make(tmp_path / "prev", "r1", [{}], TEXT, URL)
    current = make_run(tmp_path / "cur", run_id="r2")
    add_source(current, "", url=URL, access="not_accessible", copy_file=None, copy_sha256=None)
    add_source(current, TEXT, url="https://example.com/b")
    add_fact(current, source_id="S2", quote=FIRST, fields={"site": "Plant South"})
    _settle(current)
    result = compare_runs(previous, current)
    assert result["possible_matches"] == [{"fact_id": "F1", "previous_fact_id": "F1", "differing_field": "site"}]
    assert result["source_unavailable"] == [] and result["not_found_again"] == []


def test_rejected_and_general_facts_are_ignored(two_runs):
    previous, current = two_runs(
        [{}, {"quote": "this sentence is nowhere in the source", "fields": {"site": "Plant South"}},
         {"general": True, "fields": {"site": "Plant West"}}],
        [{"quote": "this sentence is nowhere in the source"},
         {"general": True, "fields": {"site": "Plant East"}}])
    assert [f["status"] for f in store.read_facts(previous).values()] == ["confirmed", "rejected", "confirmed"]
    assert [f["status"] for f in store.read_facts(current).values()] == ["rejected", "confirmed"]
    result = compare_runs(previous, current)
    assert result["new"] == [] and result["changed"] == [] and result["unchanged"] == 0
    assert result["not_found_again"] == [{"previous_fact_id": "F1"}]
    assert result["possible_matches"] == []


def test_proposed_facts_are_ignored(two_runs):
    previous, current = two_runs([{}], [{}])
    add_fact(current, source_id="S1", quote=FIRST, primary_source=True, fields={"site": "Plant South"})  # never settled: proposed
    result = compare_runs(previous, current)
    assert result["new"] == [] and result["unchanged"] == 1


def test_uncertain_facts_take_part(two_runs):
    tentative = {"certainty": "tentative", "tentative_reason": "one unnamed source"}
    previous, current = two_runs([tentative], [tentative, dict(tentative, fields={"site": "Plant South"})])
    assert [f["status"] for f in store.read_facts(previous).values()] == ["uncertain"]
    result = compare_runs(previous, current)
    assert result["unchanged"] == 1 and result["new"] == [{"fact_id": "F2"}]


def test_two_facts_with_the_same_key_pair_up_in_id_order(two_runs):
    previous, current = two_runs([{}, {"fields": {"planned_start": "2030"}}],
                                 [{}, {"fields": {"planned_start": "2031"}}, {}])
    result = compare_runs(previous, current)
    assert result["unchanged"] == 1
    assert result["changed"] == [{"fact_id": "F2", "previous_fact_id": "F2",
                                  "fields": {"planned_start": ["2030", "2031"]}}]
    assert result["new"] == [{"fact_id": "F3"}]


def test_lists_are_in_numeric_fact_id_order(tmp_path):
    specs = [{"fields": {"site": f"Plant {n}"}} for n in range(1, 12)]
    previous = _make(tmp_path / "prev", "r1", [], TEXT, URL)
    current = _make(tmp_path / "cur", "r2", specs, TEXT, URL)
    result = compare_runs(previous, current)
    assert [e["fact_id"] for e in result["new"]] == [f"F{n}" for n in range(1, 12)]
    previous = _make(tmp_path / "prev2", "r3", specs, TEXT, URL)
    current = _make(tmp_path / "cur2", "r4", [], TEXT, URL)
    result = compare_runs(previous, current)
    assert [e["previous_fact_id"] for e in result["not_found_again"]] == [f"F{n}" for n in range(1, 12)]


def _write_analysis(run, predictions):
    analysis = minimal_analysis(["F1"])
    analysis["predictions"] = predictions
    store.write_analysis(run, analysis)


def test_predictions_past_their_date_are_listed(two_runs):
    previous, current = two_runs([{}], [{}])
    _write_analysis(previous, [
        {"id": "P1", "message_id": "M1", "statement": "The line opens.", "by": "2026-12-31",
         "resolves_when": "it opens", "probability": 65},
        {"id": "P2", "message_id": "M1", "statement": "A third line opens.", "by": "2029-06-30",
         "resolves_when": "it opens", "probability": 30}])
    result = compare_runs(previous, current, today=date(2027, 1, 15))
    assert result["predictions_due"] == [{"prediction_id": "P1", "statement": "The line opens.", "by": "2026-12-31"}]
    assert [p["prediction_id"] for p in result["predictions_due"]] == ["P1"]


def test_a_prediction_due_today_is_listed(two_runs):
    previous, current = two_runs([{}], [{}])
    _write_analysis(previous, [{"id": "P1", "statement": "x", "by": "2027-01-15"}])
    assert len(compare_runs(previous, current, today=date(2027, 1, 15))["predictions_due"]) == 1
    assert compare_runs(previous, current, today=date(2027, 1, 14))["predictions_due"] == []


def test_predictions_default_to_the_current_date(two_runs):
    previous, current = two_runs([{}], [{}])
    _write_analysis(previous, [{"id": "P1", "statement": "x", "by": "2000-01-01"},
                               {"id": "P2", "statement": "y", "by": "9999-12-31"}])
    assert [p["prediction_id"] for p in compare_runs(previous, current)["predictions_due"]] == ["P1"]


def test_only_the_previous_runs_predictions_count(two_runs):
    previous, current = two_runs([{}], [{}])
    _write_analysis(current, [{"id": "P1", "statement": "x", "by": "2000-01-01"}])
    assert compare_runs(previous, current)["predictions_due"] == []


@pytest.mark.parametrize("content", [None, "{not json", "[]", '{"predictions": "soon"}', '{"predictions": [3, null]}'])
def test_a_missing_or_unreadable_analysis_contributes_nothing(two_runs, content):
    previous, current = two_runs([{}], [{}])
    if content is not None:
        (previous / "analysis.json").write_text(content, encoding="utf-8")
    assert compare_runs(previous, current, today=date(2030, 1, 1))["predictions_due"] == []


def test_a_prediction_with_a_bad_date_is_skipped(two_runs):
    previous, current = two_runs([{}], [{}])
    _write_analysis(previous, [
        {"id": "P1", "statement": "a", "by": "end of 2026"},
        {"id": "P2", "statement": "b", "by": None},
        {"id": "P3", "statement": "c", "by": "2026-13-45"},
        {"id": "P4", "statement": "d", "by": "20261231"},
        {"id": "P5", "statement": "e", "by": "2026-12-31"}])
    result = compare_runs(previous, current, today=date(2027, 1, 1))
    assert [p["prediction_id"] for p in result["predictions_due"]] == ["P5"]


def _snapshot(*runs):
    return {str(path): path.read_bytes() for run in runs for path in sorted(run.rglob("*")) if path.is_file()}


def test_compare_runs_writes_nothing(two_runs):
    previous, current = two_runs([{}], [{}, {"fields": {"site": "Plant South"}}])
    _write_analysis(previous, [{"id": "P1", "statement": "x", "by": "2000-01-01"}])
    before = _snapshot(previous, current)
    compare_runs(previous, current, today=date(2027, 1, 1))
    assert _snapshot(previous, current) == before
    assert not (current / "changes.json").exists()


def test_result_is_plain_json(two_runs):
    previous, current = two_runs([{}], [{}])
    result = compare_runs(previous, current)
    assert json.loads(json.dumps(result)) == result


# --- the command ---------------------------------------------------------------------

def test_cli_compare_writes_changes_json_and_prints_it(two_runs, capsys):
    previous, current = two_runs([{}], [{}, {"fields": {"site": "Plant South"}}])
    _write_analysis(previous, [{"id": "P1", "statement": "x", "by": "2026-12-31"}])
    assert main(["compare", "--previous", str(previous), "--current", str(current), "--today", "2027-01-15"]) == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    printed = json.loads(out)
    assert printed["new"] == [{"fact_id": "F2"}] and printed["unchanged"] == 1
    assert [p["prediction_id"] for p in printed["predictions_due"]] == ["P1"]
    assert json.loads((current / "changes.json").read_text(encoding="utf-8")) == printed
    assert not (previous / "changes.json").exists()


def test_cli_compare_without_today_uses_the_current_date(two_runs, capsys):
    previous, current = two_runs([{}], [{}])
    assert main(["compare", "--previous", str(previous), "--current", str(current)]) == 0
    assert json.loads(capsys.readouterr().out)["predictions_due"] == []


@pytest.mark.parametrize("today", ["2027-13-01", "tomorrow", "20270115", "2027-1-5"])
def test_cli_compare_rejects_a_bad_date(two_runs, capsys, today):
    previous, current = two_runs([{}], [{}])
    assert main(["compare", "--previous", str(previous), "--current", str(current), "--today", today]) == 2
    assert "error" in json.loads(capsys.readouterr().out)
    assert not (current / "changes.json").exists()


def test_cli_compare_needs_both_runs(two_runs, capsys):
    previous, _ = two_runs([{}], [{}])
    assert main(["compare", "--previous", str(previous)]) == 2


def test_cli_compare_with_a_missing_run_folder_exits_2(tmp_path, capsys):
    assert main(["compare", "--previous", str(tmp_path / "nope"), "--current", str(tmp_path / "nada")]) == 2
    assert "error" in json.loads(capsys.readouterr().out)


# --- final fix C3: what the gate needs to judge a comparison ------------------------------

def test_compare_states_whether_the_previous_run_had_non_public_sources(tmp_path, two_runs):
    previous, current = two_runs([{}], [{}])
    assert compare_runs(previous, current)["previous_confidential"] is False
    private = make_run(tmp_path / "private", run_id="r0", mode="private", acknowledged=True)
    add_source(private, TEXT, url=URL)
    add_source(private, "Internal capacity review. " * 20, data_class="internal", url="internal review")
    current = _make(tmp_path / "private-cur", "r3", [{}], TEXT, URL, mode="private", acknowledged=True)
    assert compare_runs(private, current)["previous_confidential"] is True


def test_compare_binds_the_comparison_to_the_current_facts(two_runs):
    import hashlib
    previous, current = two_runs([{}], [{}, {"fields": {"site": "Plant South"}},
                                        {"quote": "this sentence is nowhere in the source"}])
    result = compare_runs(previous, current)
    facts = store.read_facts(current)
    compared = [{"id": fact_id, "status": facts[fact_id]["status"], "fields": facts[fact_id]["fields"]}
                for fact_id in ("F1", "F2")]                     # F3 is rejected and takes no part
    text = json.dumps(compared, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert result["facts_digest"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    from radar.diff import facts_digest
    assert facts_digest(facts) == result["facts_digest"]
    facts["F2"]["status"] = "rejected"
    assert facts_digest(facts) != result["facts_digest"]


def test_the_comparison_digest_ignores_itself():
    from radar.diff import file_digest
    changes = {"previous_run": "r0", "new": [{"fact_id": "F1"}], "unchanged": 2, "facts_digest": "abc"}
    plain = file_digest(changes)
    assert len(plain) == 64 and plain == file_digest(dict(changes, file_digest="anything"))
    assert plain != file_digest(dict(changes, unchanged=3))
    assert plain != file_digest(dict(changes, new=[]))
    assert plain != file_digest(dict(changes, facts_digest="abd"))
    assert plain != file_digest({key: value for key, value in changes.items() if key != "unchanged"})


def test_the_comparison_digest_is_the_hash_of_its_canonical_text():
    import hashlib
    from radar.diff import file_digest
    changes = {"b": ["Größe", {"z": 1, "a": None}], "a": 1.5, "file_digest": "ignored"}
    text = '{"a":1.5,"b":["Größe",{"a":null,"z":1}]}'
    assert file_digest(changes) == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert file_digest({"b": ["Größe", {"a": None, "z": 1}], "a": 1.5}) == file_digest(changes)


def test_compare_stores_the_digest_of_the_whole_comparison(two_runs):
    from radar.diff import file_digest
    previous, current = two_runs([{}], [{}])
    result = compare_runs(previous, current)
    assert result["file_digest"] == file_digest(result)
    stored = json.loads(json.dumps(result, ensure_ascii=False))   # as it reads back from changes.json
    assert file_digest(stored) == result["file_digest"]


# --- Part A fix A1, ruling HG1: compare never carries non-public material into a public run ---------------

from radar.diff import CompareRefused, ILLUSTRATIVE_MIX, PRACTICE_RUN_ONLY, PRIVATE_INTO_PUBLIC   # noqa: E402
from radar.explain import explain   # noqa: E402
from radar.schema import Problem   # noqa: E402

MARKER = "MARKER-only-in-the-private-run-7c1f"


def _private_earlier_run(root):
    """A private run whose one settled capacity move holds MARKER in a field, and whose due prediction holds it too."""
    run = _make(root, "r1", [{"fields": {"planned_start": MARKER}}], TEXT, URL, mode="private", acknowledged=True)
    _write_analysis(run, [{"id": "P1", "statement": MARKER, "by": "2026-01-01"}])
    return run


def _bytes_under(folder):
    return b"".join(path.read_bytes() for path in sorted(folder.rglob("*")) if path.is_file())


def _refused(capsys, previous, current, message):
    before = _snapshot(current)
    code = main(["compare", "--previous", str(previous), "--current", str(current), "--today", "2027-01-15"])
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    printed = json.loads(out)
    assert code == 2 and printed["error"] == message, printed
    assert len(printed["explained"]) == 1 and printed["explained"][0]["known"] is True
    assert not (current / "changes.json").exists() and _snapshot(current) == before


def test_compare_refuses_a_private_earlier_run_for_a_public_run_and_its_material_stays_out(tmp_path, capsys):
    previous = _private_earlier_run(tmp_path / "prev")
    current = _make(tmp_path / "cur", "r2", [{}], TEXT, URL)
    _refused(capsys, previous, current, PRIVATE_INTO_PUBLIC)
    assert MARKER.encode() not in _bytes_under(current)
    with pytest.raises(CompareRefused, match=PRIVATE_INTO_PUBLIC):
        compare_runs(previous, current)


def test_compare_refuses_a_public_earlier_run_that_holds_one_licensed_source(tmp_path, capsys):
    previous = _make(tmp_path / "prev", "r1", [{}], TEXT, URL)
    add_source(previous, "Licensed capacity table. " * 20, data_class="licensed", url="licensed database export")
    current = _make(tmp_path / "cur", "r2", [{}], TEXT, URL)
    _refused(capsys, previous, current, PRIVATE_INTO_PUBLIC)


def test_a_private_run_may_still_be_compared_with_a_private_or_a_public_earlier_run(tmp_path, capsys):
    current = _make(tmp_path / "cur", "r2", [{}], TEXT, URL, mode="private", acknowledged=True)
    private = _private_earlier_run(tmp_path / "prev")
    add_source(private, "Internal capacity review. " * 20, data_class="internal", url="internal review")
    assert main(["compare", "--previous", str(private), "--current", str(current)]) == 0
    assert json.loads(capsys.readouterr().out)["previous_confidential"] is True
    assert store._read_json(current / "changes.json")["previous_confidential"] is True
    public = _make(tmp_path / "pub", "r0", [{}], TEXT, URL)
    assert main(["compare", "--previous", str(public), "--current", str(current)]) == 0
    assert json.loads(capsys.readouterr().out)["previous_confidential"] is False


def test_a_private_earlier_run_counts_as_confidential_even_with_only_public_sources(tmp_path):
    previous = _make(tmp_path / "prev", "r1", [{}], TEXT, URL, mode="private", acknowledged=True)
    current = _make(tmp_path / "cur", "r2", [{}], TEXT, URL, mode="private", acknowledged=True)
    assert compare_runs(previous, current)["previous_confidential"] is True


def test_the_refusal_messages_are_explained_in_plain_words():
    for message in (PRIVATE_INTO_PUBLIC, ILLUSTRATIVE_MIX, PRACTICE_RUN_ONLY):
        assert explain(Problem("changes.json", None, message))["known"] is True, message


# --- Part A fix A1, ruling HG2: compare joins only runs of the same kind ------------------------------------

def test_compare_refuses_an_illustrative_run_and_a_real_one_in_either_direction(tmp_path, capsys):
    invented = _make(tmp_path / "invented", "r1", [{}], TEXT, URL, illustrative=True)
    real = _make(tmp_path / "real", "r2", [{}], TEXT, URL)
    _refused(capsys, invented, real, ILLUSTRATIVE_MIX)
    _refused(capsys, real, invented, ILLUSTRATIVE_MIX)


def test_two_illustrative_runs_are_compared_as_before(tmp_path, capsys):
    previous = _make(tmp_path / "prev", "r1", [{}], TEXT, URL, illustrative=True)
    current = _make(tmp_path / "cur", "r2", [{}], TEXT, URL, illustrative=True)
    assert main(["compare", "--previous", str(previous), "--current", str(current)]) == 0
    assert (current / "changes.json").exists()


def test_the_practice_run_is_compared_only_with_an_earlier_practice_run(tmp_path, capsys):
    from radar.demo import build_demo_run
    practice = build_demo_run(tmp_path / "practice", private=True)
    public_demo = build_demo_run(tmp_path / "base")
    _refused(capsys, public_demo, practice, PRACTICE_RUN_ONLY)
    unmarked = _make(tmp_path / "unmarked", "r1", [{}], TEXT, URL, illustrative=True, mode="private",
                     acknowledged=True)
    _refused(capsys, unmarked, practice, PRACTICE_RUN_ONLY)
    earlier_practice = build_demo_run(tmp_path / "earlier", private=True)
    assert main(["compare", "--previous", str(earlier_practice), "--current", str(practice)]) == 0
    assert json.loads(capsys.readouterr().out)["previous_confidential"] is True


def test_compare_records_whether_the_earlier_run_was_illustrative(tmp_path, capsys):
    real = (_make(tmp_path / "a", "r1", [{}], TEXT, URL), _make(tmp_path / "b", "r2", [{}], TEXT, URL))
    invented = (_make(tmp_path / "c", "r1", [{}], TEXT, URL, illustrative=True),
                _make(tmp_path / "d", "r2", [{}], TEXT, URL, illustrative=True))
    for (previous, current), kind in ((real, False), (invented, True)):
        result = compare_runs(previous, current)
        assert result["previous_illustrative"] is kind
        from radar.diff import file_digest
        assert result["file_digest"] == file_digest(result)   # the new key is inside what the digest covers
        assert file_digest(dict(result, previous_illustrative=not kind)) != result["file_digest"]


def test_the_demo_runs_still_compare_base_with_changed(tmp_path, capsys):
    from radar.demo import build_demo_run
    base = build_demo_run(tmp_path / "base")
    changed = build_demo_run(tmp_path / "changed", changed=True)
    assert main(["compare", "--previous", str(base), "--current", str(changed), "--today", "2026-11-12"]) == 0
    assert json.loads(capsys.readouterr().out)["previous_confidential"] is False


# --- fix wave A12: compare does not trust the earlier run's stored statuses -----------------------------------------

from radar.diff import EARLIER_RUN_NOT_SETTLED   # noqa: E402


@pytest.mark.parametrize("change", ["withdrawn", "a new verdict", "a new source link"])
def test_an_earlier_run_with_facts_to_settle_again_is_refused_and_nothing_is_written(two_runs, capsys, change):
    previous, current = two_runs([{}], [{}])
    if change == "withdrawn":
        verify.withdraw_fact(previous, "F1", "Duplicate.")
    elif change == "a new verdict":
        verify.record_support(previous, "F1", False, "support-checker", "The quote does not say so.")
    else:
        fact = store.read_facts(previous)["F1"]
        store.write_fact(previous, dict(fact, primary_source=False))   # its own verdict is now out of date too
    assert verify.needs_settling(store.read_facts(previous)["F1"], store.read_sources(previous))
    with pytest.raises(CompareRefused, match=EARLIER_RUN_NOT_SETTLED):
        compare_runs(previous, current)
    code = main(["compare", "--previous", str(previous), "--current", str(current)])
    printed = json.loads(capsys.readouterr().out)
    assert code == 2 and printed["error"] == EARLIER_RUN_NOT_SETTLED and printed["explained"][0]["known"] is True
    assert "settle" in printed["explained"][0]["do"].lower()
    assert not (current / "changes.json").exists()
    verify.settle(previous)
    assert main(["compare", "--previous", str(previous), "--current", str(current)]) == 0


def test_an_earlier_run_that_is_settled_is_compared_as_before(two_runs):
    previous, current = two_runs([{}], [{}])
    assert compare_runs(previous, current)["unchanged"] == 1
