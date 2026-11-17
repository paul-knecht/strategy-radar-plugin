import json
from pathlib import Path

from radar.cli import main
from fixtures.build_demo_run import build_demo_run

# Fact numbers follow the order in build_demo_run: F1 a_north, F2 a_south, F3 example_own, F4 b_site,
# F6 c_buy, F7 c_open (uncertain), F9 planted_year (rejected).


def run_calc(capsys, run, *args):
    code = main(["calc", "--run", str(run), *args])
    return code, json.loads(capsys.readouterr().out)


def snapshot(folder):
    """Every file under `folder` with its bytes and modification time."""
    return {str(p.relative_to(folder)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(Path(folder).rglob("*")) if p.is_file()}


def test_calc_adds_the_lines_of_the_demo(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    code, out = run_calc(capsys, run, "--operation", "sum", "--unit", "lines", "--facts", "F1,F2,F3,F6")
    assert code == 0
    assert out == {"result": "6", "includes_uncertain": False, "problems": [], "explained": []}


def test_calc_share_matches_the_demo(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    code, out = run_calc(capsys, run, "--operation", "share", "--unit", "lines",
                         "--facts", "F4", "--of", "F1,F2,F3,F4,F6")
    assert code == 0 and out["result"] == "33"


def test_calc_refuses_a_rejected_fact_and_explains(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    code, out = run_calc(capsys, run, "--operation", "sum", "--unit", "lines", "--facts", "F1,F9")
    assert code == 1
    assert out["result"] is None
    assert out["problems"] == ["input F9 is not a settled capacity move"]
    assert out["explained"][0]["known"] is True


def test_calc_says_when_uncertain_facts_are_included(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    code, out = run_calc(capsys, run, "--operation", "count", "--facts", "F1,F7")
    assert code == 0
    assert out["result"] == "2" and out["includes_uncertain"] is True


def test_calc_refuses_a_unit_that_does_not_match_and_explains(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    code, out = run_calc(capsys, run, "--operation", "sum", "--unit", "tonnes", "--facts", "F1,F2")
    assert code == 1 and out["result"] is None
    assert len(out["problems"]) == 2 and all(' not "tonnes"' in p for p in out["problems"])
    assert all(entry["known"] for entry in out["explained"])


def test_calc_share_without_a_whole_is_refused(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    code, out = run_calc(capsys, run, "--operation", "share", "--unit", "lines", "--facts", "F4")
    assert code == 1 and out["result"] is None
    assert out["problems"] == ["share inputs must be part of the whole"]
    assert out["explained"][0]["known"] is True


def test_calc_sum_without_a_unit_is_refused(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    code, out = run_calc(capsys, run, "--operation", "sum", "--facts", "F1,F2")
    assert code == 1 and out["result"] is None and out["problems"] == ["unit is required"]


def test_calc_names_an_unknown_fact(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    code, out = run_calc(capsys, run, "--operation", "count", "--facts", "F1,F99")
    assert code == 1 and out["problems"] == ["input F99 is not a settled capacity move"]


def test_calc_refuses_a_fact_listed_twice(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    code, out = run_calc(capsys, run, "--operation", "count", "--facts", "F1,F1")
    assert code == 1 and out["result"] is None
    assert out["problems"] == ["input F1 is listed more than once"]


def test_calc_ignores_spaces_around_the_fact_ids(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    code, out = run_calc(capsys, run, "--operation", "count", "--facts", " F1 , F2 ,")
    assert code == 0 and out["result"] == "2"


def test_calc_needs_at_least_one_fact(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    code, out = run_calc(capsys, run, "--operation", "sum", "--unit", "lines", "--facts", " , ")
    assert code == 2 and "fact" in out["error"]


def test_calc_rejects_an_unknown_operation_and_a_missing_facts_option(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    assert run_calc(capsys, run, "--operation", "average", "--facts", "F1")[0] == 2
    assert run_calc(capsys, run, "--operation", "count")[0] == 2


def test_calc_on_a_folder_that_is_not_a_run_is_a_usage_error(tmp_path, capsys):
    code, out = run_calc(capsys, tmp_path / "nothing-here", "--operation", "count", "--facts", "F1")
    assert code == 2 and "error" in out


def test_calc_writes_nothing_into_the_run(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    before = snapshot(run)
    run_calc(capsys, run, "--operation", "sum", "--unit", "lines", "--facts", "F1,F2,F3,F6")
    run_calc(capsys, run, "--operation", "sum", "--unit", "lines", "--facts", "F1,F9")
    assert snapshot(run) == before


# --- Part A fix A1, ruling HG6: calc does not trust a stored status that no longer follows from the checks ------

from radar import store, verify   # noqa: E402
from helpers import add_fact, add_source, make_run   # noqa: E402

SETTLE_FIRST = "input {} has changed since the facts were settled, so settle the facts first"


def assert_settle_first(capsys, run, facts, changed):
    code, out = run_calc(capsys, run, "--operation", "sum", "--unit", "lines", "--facts", facts)
    assert code == 1 and out["result"] is None and out["includes_uncertain"] is False
    assert out["problems"] == [SETTLE_FIRST.format(fact_id) for fact_id in changed]
    assert all(entry["known"] for entry in out["explained"])
    assert "F1" in out["explained"][0]["what"]


def test_calc_refuses_a_withdrawn_fact_that_was_not_settled(tmp_path, capsys):
    run = build_demo_run(tmp_path)
    verify.withdraw_fact(run, "F1", "the release was retracted")     # an interrupted run: no settle afterwards
    assert_settle_first(capsys, run, "F1,F2,F3,F6", ["F1"])
    verify.settle(run)
    code, out = run_calc(capsys, run, "--operation", "sum", "--unit", "lines", "--facts", "F1,F2,F3,F6")
    assert code == 1 and out["problems"] == ["input F1 is not a settled capacity move"]
    assert run_calc(capsys, run, "--operation", "sum", "--unit", "lines", "--facts", "F2,F3,F6")[1]["result"] == "4"


def two_source_run(tmp_path):
    """F1, a capacity move of two lines, is confirmed only because S2, an independent second source, also holds it."""
    run = make_run(tmp_path)
    add_source(run, "Competitor A will add a second filling line at Plant North by 2028.", publisher="Competitor A")
    add_source(run, "The paper says Competitor A will add a second filling line at Plant North by 2028.",
               publisher="Trade Paper")
    add_fact(run, source_id="S1", primary_source=False,
             supporting=[{"source_id": "S2", "quote": "Competitor A will add a second filling line at Plant North"}])
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    assert store.read_facts(run)["F1"]["status"] == "confirmed"
    return run


def test_calc_refuses_a_fact_whose_sources_were_linked_after_it_was_settled(tmp_path, capsys):
    run = two_source_run(tmp_path)
    assert run_calc(capsys, run, "--operation", "sum", "--unit", "lines", "--facts", "F1")[1]["result"] == "2"
    store.add_based_on(run, "S2", "S1")
    assert_settle_first(capsys, run, "F1", ["F1"])
    verify.settle(run)
    code, out = run_calc(capsys, run, "--operation", "sum", "--unit", "lines", "--facts", "F1")
    assert code == 0 and out == {"result": "2", "includes_uncertain": True, "problems": [], "explained": []}


def test_calc_adds_filling_and_plain_lines_but_refuses_an_unrelated_unit(tmp_path, capsys):
    run = two_source_run(tmp_path)      # F1: size_unit "lines"
    add_fact(run, source_id="S1", primary_source=False, fields={"size_unit": "Filling Lines"},
             supporting=[{"source_id": "S2", "quote": "Competitor A will add a second filling line at Plant North"}])
    verify.check_quotes(run); verify.record_support(run, "F2", True, "support-checker", ""); verify.settle(run)
    assert run_calc(capsys, run, "--operation", "sum", "--unit", "lines", "--facts", "F1,F2")[1]["result"] == "4"
    code, out = run_calc(capsys, run, "--operation", "sum", "--unit", "m²", "--facts", "F1,F2")
    assert code == 1 and out["result"] is None and len(out["problems"]) == 2


def test_calc_refuses_a_fact_with_a_fresh_verdict_that_was_not_settled(tmp_path, capsys):
    run = two_source_run(tmp_path)
    verify.record_support(run, "F1", False, "support-checker", "the paper names another plant")
    assert_settle_first(capsys, run, "F1", ["F1"])
    verify.settle(run)
    code, out = run_calc(capsys, run, "--operation", "sum", "--unit", "lines", "--facts", "F1")
    assert code == 1 and out["problems"] == ["input F1 is not a settled capacity move"]
