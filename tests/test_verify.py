import hashlib
import json
from urllib.parse import urlsplit

import pytest

from radar import verify, store
from radar.cli import main
from helpers import PERMIT_TEXT, add_fact, add_source, early_signal_proposal, make_run, proposal

TEXT_A = "The expansion adds two high-speed syringe lines for customers, starting in 2028."
TEXT_B = "Competitor A confirmed two new syringe lines will open in 2028, the paper reported."


def setup(tmp_path, **fact_over):
    run = make_run(tmp_path)
    a = add_source(run, TEXT_A, publisher="Competitor A")
    b = add_source(run, TEXT_B, publisher="Trade Paper")
    fact_over.setdefault("quote", "adds two high-speed syringe lines for customers")
    add_fact(run, source_id=a["id"], **fact_over)
    return run


def status(run):
    f = store.read_facts(run)["F1"]
    return f["status"], f["status_reason"]


def test_primary_source_with_both_checks_is_confirmed(tmp_path):
    run = setup(tmp_path, primary_source=True)
    checks = verify.check_quotes(run)
    assert checks["F1"]["quote"]["passed"] and checks["F1"]["quote"]["mode"] == "exact"
    verify.record_support(run, "F1", True, "support-checker", "quote states it directly")
    assert verify.settle(run) == {"F1": "confirmed"} and status(run) == ("confirmed", None)


def test_fake_quote_is_rejected(tmp_path):
    run = setup(tmp_path, primary_source=True, quote="adds five high-speed syringe lines for customers")
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", "")
    verify.settle(run)
    assert status(run) == ("rejected", "not_found")


def test_real_quote_that_does_not_support_is_rejected(tmp_path):
    run = setup(tmp_path, primary_source=True)
    verify.check_quotes(run); verify.record_support(run, "F1", False, "support-checker", "quote says 2028, fact says 2027")
    verify.settle(run)
    assert status(run) == ("rejected", "not_supported")


def test_missing_support_check_stays_proposed(tmp_path):
    run = setup(tmp_path, primary_source=True)
    verify.check_quotes(run); verify.settle(run)
    assert status(run) == ("proposed", "checks_incomplete")


def test_tentative_is_uncertain_with_its_reason(tmp_path):
    run = setup(tmp_path, primary_source=True, certainty="tentative", tentative_reason="one unnamed source")
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    assert status(run) == ("uncertain", "one unnamed source")


def test_non_primary_single_source_is_uncertain(tmp_path):
    run = setup(tmp_path, primary_source=False)
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    assert status(run) == ("uncertain", "single source that is not a primary source")


def test_second_independent_source_confirms(tmp_path):
    run = setup(tmp_path, primary_source=False,
                supporting=[{"source_id": "S2", "quote": "two new syringe lines will open in 2028"}])
    checks = verify.check_quotes(run)
    assert checks["F1"]["supporting"] == [{"source_id": "S2", "passed": True, "mode": "exact", "reason": None}]
    verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    assert status(run) == ("confirmed", None)


def test_second_source_from_same_publisher_does_not_confirm(tmp_path):
    run = setup(tmp_path, primary_source=False,
                supporting=[{"source_id": "S2", "quote": "two new syringe lines will open in 2028"}])
    s2 = store.read_sources(run)["S2"]; s2["publisher"] = "competitor  a"; store.write_source(run, s2)
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    assert status(run)[0] == "uncertain"


def test_article_written_from_the_release_does_not_confirm(tmp_path):
    run = setup(tmp_path, primary_source=False,
                supporting=[{"source_id": "S2", "quote": "two new syringe lines will open in 2028"}])
    s2 = store.read_sources(run)["S2"]; s2["based_on"] = ["S1"]; store.write_source(run, s2)
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    assert status(run) == ("uncertain", "single source that is not a primary source")


def test_inaccessible_source_fails_quote_check(tmp_path):
    run = setup(tmp_path, primary_source=True)
    s1 = store.read_sources(run)["S1"]; s1.update(access="not_accessible", access_reason="http_403"); store.write_source(run, s1)
    assert verify.check_quotes(run)["F1"]["quote"]["reason"] == "no_saved_copy"


# --- beyond the brief's list -------------------------------------------------

def test_quote_check_records_time_and_copy_hash(tmp_path):
    from datetime import datetime, timezone
    run = setup(tmp_path, primary_source=True)
    now = datetime(2026, 11, 12, 10, 15, tzinfo=timezone.utc)
    quote = verify.check_quotes(run, now=now)["F1"]["quote"]
    assert quote == {"passed": True, "mode": "exact", "reason": None,
                     "checked_at": "2026-11-12T10:15:00Z",
                     "copy_sha256": store.sha256_file(run / "copies" / "S1.txt")}
    saved = store.read_facts(run)["F1"]["checks"]
    assert saved["quote"] == quote and saved["supporting"] == []


def test_check_quotes_keeps_an_earlier_support_record(tmp_path):
    run = setup(tmp_path, primary_source=True)
    verify.check_quotes(run)
    verify.record_support(run, "F1", True, "support-checker", "direct")
    verify.check_quotes(run)
    support = store.read_facts(run)["F1"]["checks"]["support"]
    assert support["passed"] is True and support["by"] == "support-checker" and support["note"] == "direct"


def test_record_support_stores_who_what_and_when(tmp_path):
    from datetime import datetime, timezone
    run = setup(tmp_path, primary_source=True)
    now = datetime(2026, 11, 12, 11, 0, tzinfo=timezone.utc)
    verify.record_support(run, "F1", False, "support-checker", "year differs", now=now)
    fact = store.read_facts(run)["F1"]
    assert fact["checks"]["support"] == {
        "passed": False, "by": "support-checker", "note": "year differs", "at": "2026-11-12T11:00:00Z",
        "content_sha256": verify.content_digest(fact)}


def test_record_support_unknown_fact_raises(tmp_path):
    run = setup(tmp_path, primary_source=True)
    with pytest.raises(ValueError, match="F9"):
        verify.record_support(run, "F9", True, "support-checker", "")


def test_supporting_source_that_does_not_exist_gets_no_saved_copy(tmp_path):
    run = setup(tmp_path, supporting=[{"source_id": "S9", "quote": "two new syringe lines will open in 2028"}])
    entry = verify.check_quotes(run)["F1"]["supporting"][0]
    assert entry == {"source_id": "S9", "passed": False, "mode": None, "reason": "no_saved_copy"}


def test_supporting_source_without_saved_copy_gets_no_saved_copy(tmp_path):
    run = setup(tmp_path, supporting=[{"source_id": "S2", "quote": "two new syringe lines will open in 2028"}])
    s2 = store.read_sources(run)["S2"]; s2.update(access="not_accessible", access_reason="http_404", copy_file=None)
    store.write_source(run, s2)
    entry = verify.check_quotes(run)["F1"]["supporting"][0]
    assert entry["passed"] is False and entry["reason"] == "no_saved_copy"


def test_copy_that_is_not_utf8_text_counts_as_no_saved_copy(tmp_path):
    run = setup(tmp_path, primary_source=True)
    (run / "copies" / "S1.txt").write_bytes(b"\xff\xfe\x00bad bytes \x80\x81")
    quote = verify.check_quotes(run)["F1"]["quote"]
    assert quote["passed"] is False and quote["reason"] == "no_saved_copy"


def test_missing_copy_file_counts_as_no_saved_copy(tmp_path):
    run = setup(tmp_path, primary_source=True)
    (run / "copies" / "S1.txt").unlink()
    quote = verify.check_quotes(run)["F1"]["quote"]
    assert quote["passed"] is False and quote["reason"] == "no_saved_copy" and quote["copy_sha256"] is None


def test_copy_path_outside_the_run_is_not_read(tmp_path):
    run = setup(tmp_path, primary_source=True)
    outside = tmp_path / "outside.txt"; outside.write_text(TEXT_A, encoding="utf-8")
    s1 = store.read_sources(run)["S1"]; s1["copy_file"] = "../outside.txt"; store.write_source(run, s1)
    assert (run / s1["copy_file"]).resolve() == outside.resolve() and outside.is_file()   # the path really reaches it
    assert verify.check_quotes(run)["F1"]["quote"]["reason"] == "no_saved_copy"


def test_supporting_quote_that_is_not_found_rejects_the_fact(tmp_path):
    run = setup(tmp_path, primary_source=False,
                supporting=[{"source_id": "S2", "quote": "five new syringe lines will open in 2031"}])
    entry = verify.check_quotes(run)["F1"]["supporting"][0]
    assert entry["passed"] is False and entry["reason"] == "not_found"
    verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    assert status(run) == ("rejected", "supporting_quote_not_found")


def test_an_invented_supporting_quote_rejects_a_primary_source_fact(tmp_path):
    run = setup(tmp_path, primary_source=True,
                supporting=[{"source_id": "S2", "quote": "five new syringe lines will open in 2031"}])
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    assert status(run) == ("rejected", "supporting_quote_not_found")


def test_a_supporting_source_without_a_saved_copy_rejects_the_fact(tmp_path):
    run = setup(tmp_path, primary_source=True,
                supporting=[{"source_id": "S2", "quote": "two new syringe lines will open in 2028"}])
    s2 = store.read_sources(run)["S2"]; s2.update(access="not_accessible", access_reason="http_404", copy_file=None)
    store.write_source(run, s2)
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    assert status(run) == ("rejected", "supporting_quote_not_found")


def test_a_failed_main_quote_is_named_before_a_failed_supporting_quote(tmp_path):
    run = setup(tmp_path, primary_source=True, quote="adds five high-speed syringe lines for customers",
                supporting=[{"source_id": "S2", "quote": "five new syringe lines will open in 2031"}])
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    assert status(run) == ("rejected", "not_found")


def test_rejection_comes_before_tentative(tmp_path):
    run = setup(tmp_path, primary_source=True, certainty="tentative", tentative_reason="unnamed",
                quote="adds five high-speed syringe lines for customers")
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    assert status(run) == ("rejected", "not_found")


def test_settle_runs_the_quote_check_itself(tmp_path):
    run = setup(tmp_path, primary_source=True)
    verify.record_support(run, "F1", True, "support-checker", ""); verify.settle(run)
    assert status(run) == ("confirmed", None)
    assert store.read_facts(run)["F1"]["checks"]["quote"]["passed"] is True


def test_settle_returns_every_fact(tmp_path):
    run = setup(tmp_path, primary_source=True)
    add_fact(run, source_id="S1", primary_source=True, quote="adds five high-speed syringe lines for customers")
    verify.check_quotes(run)
    for fid in ("F1", "F2"):
        verify.record_support(run, fid, True, "support-checker", "")
    assert verify.settle(run) == {"F1": "confirmed", "F2": "rejected"}


# --- the pure rules ------------------------------------------------------------

def _src(sid, publisher, based_on=()):
    return {"id": sid, "publisher": publisher, "based_on": list(based_on)}


def test_independent_needs_different_publishers_and_no_shared_ancestry():
    sources = {"S1": _src("S1", "A"), "S2": _src("S2", "B"), "S3": _src("S3", "B", ["S1"]),
               "S4": _src("S4", "C", ["S9"]), "S5": _src("S5", "D", ["S9"])}
    assert verify.independent("S1", "S2", sources) is True
    assert verify.independent("S1", "S3", sources) is False  # based on S1
    assert verify.independent("S3", "S1", sources) is False  # symmetric
    assert verify.independent("S4", "S5", sources) is False  # both draw on S9, which does not exist
    assert verify.independent("S1", "S1", sources) is False


def test_independent_follows_chains_and_stops_on_loops():
    sources = {"S1": _src("S1", "A", ["S2"]), "S2": _src("S2", "B", ["S1"]),
               "S3": _src("S3", "C", ["S4"]), "S4": _src("S4", "D", ["S5"]), "S5": _src("S5", "E"),
               "S6": _src("S6", "F", ["S5"])}
    assert verify.independent("S1", "S2", sources) is False
    assert verify.independent("S3", "S6", sources) is False  # S3 -> S4 -> S5 <- S6
    assert verify.independent("S1", "S3", sources) is True


def test_independent_is_false_for_an_unknown_source():
    assert verify.independent("S1", "S2", {"S1": _src("S1", "A")}) is False


def test_expected_status_is_pure_and_follows_the_rules_in_order():
    sources = {"S1": _src("S1", "A"), "S2": _src("S2", "B")}
    base = {"source_id": "S1", "primary_source": False, "certainty": "firm", "tentative_reason": None,
            "statement": "s", "quote": "q", "supporting": [], "fields": None}
    base["checks"] = {"quote": {"passed": True},
                      "support": {"passed": True, "content_sha256": verify.content_digest(base)},
                      "supporting": [{"source_id": "S2", "passed": True}]}
    assert verify.expected_status(base, sources) == ("confirmed", None)
    assert verify.expected_status({**base, "checks": {"quote": None, "support": {"passed": True}}},
                                  sources) == ("proposed", "checks_incomplete")
    failed = {**base, "checks": {**base["checks"], "quote": {"passed": False, "reason": "quote_too_short"}}}
    assert verify.expected_status(failed, sources) == ("rejected", "quote_too_short")
    supporting_failed = {**base, "checks": {**base["checks"], "supporting": [{"source_id": "S2", "passed": False}]}}
    assert verify.expected_status(supporting_failed, sources) == ("rejected", "supporting_quote_not_found")
    with_entry = {**base, "supporting": [{"source_id": "S2", "quote": "q2"}]}
    unchecked = {**with_entry, "checks": {**base["checks"], "supporting": [],
                                          "support": {"passed": True, "content_sha256": verify.content_digest(with_entry)}}}
    assert verify.expected_status(unchecked, sources) == ("rejected", "supporting_quote_not_found")


# --- the commands ----------------------------------------------------------------

def run_cli(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    return code, json.loads(out)


def test_cli_check_record_and_settle(tmp_path, capsys):
    run = setup(tmp_path, primary_source=True)
    add_fact(run, source_id="S1", primary_source=True, quote="adds five high-speed syringe lines for customers")
    code, out = run_cli(capsys, "check-quotes", "--run", str(run))
    assert code == 0 and out["failed"] == ["F2"]
    assert out["facts"]["F1"]["quote"]["passed"] is True and out["facts"]["F2"]["quote"]["reason"] == "not_found"
    for fid, passed in (("F1", "true"), ("F2", "false")):
        code, out = run_cli(capsys, "record-support", "--run", str(run), "--fact", fid,
                            "--passed", passed, "--by", "support-checker", "--note", "n")
        assert code == 0 and out == {"ok": True}
    code, out = run_cli(capsys, "settle", "--run", str(run))
    assert code == 0
    assert out == {"status": {"F1": "confirmed", "F2": "rejected"},
                   "counts": {"confirmed": 1, "uncertain": 0, "rejected": 1, "proposed": 0}}


def test_cli_check_quotes_lists_a_fact_whose_supporting_quote_failed(tmp_path, capsys):
    run = setup(tmp_path, primary_source=True,
                supporting=[{"source_id": "S2", "quote": "five new syringe lines will open in 2031"}])
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    code, out = run_cli(capsys, "check-quotes", "--run", str(run))
    assert code == 0 and out["failed"] == ["F1"]
    assert out["facts"]["F1"]["quote"]["passed"] is True and out["facts"]["F1"]["supporting"][0]["passed"] is False


def test_cli_record_support_unknown_fact_exits_2(tmp_path, capsys):
    run = setup(tmp_path, primary_source=True)
    code, out = run_cli(capsys, "record-support", "--run", str(run), "--fact", "F9",
                        "--passed", "true", "--by", "x", "--note", "")
    assert code == 2 and "F9" in out["error"]


def test_cli_record_support_rejects_a_bad_passed_value(tmp_path, capsys):
    run = setup(tmp_path, primary_source=True)
    code, out = run_cli(capsys, "record-support", "--run", str(run), "--fact", "F1",
                        "--passed", "maybe", "--by", "x", "--note", "")
    assert code == 2 and "error" in out


# --- fix round 1: a support verdict belongs to the content the checker saw ----------

def _checked_and_supported(tmp_path, **fact_over):
    run = setup(tmp_path, primary_source=True, **fact_over)
    verify.check_quotes(run)
    verify.record_support(run, "F1", True, "support-checker", "direct")
    return run


def _edit_fact(run, **changes):
    fact = store.read_facts(run)["F1"]
    for key, value in changes.items():
        if key == "fields":
            fact["fields"] = {**fact["fields"], **value}
        else:
            fact[key] = value
    store.write_fact(run, fact)


def test_editing_the_quote_after_support_check_makes_the_check_outdated(tmp_path):
    run = _checked_and_supported(tmp_path)
    _edit_fact(run, quote="two high-speed syringe lines for customers, starting in 2028")
    assert verify.check_quotes(run)["F1"]["quote"]["passed"] is True
    verify.settle(run)
    assert status(run) == ("proposed", "support_check_outdated")


def test_editing_the_statement_after_support_check_makes_the_check_outdated(tmp_path):
    run = _checked_and_supported(tmp_path)
    _edit_fact(run, statement="Competitor A will add ten lines.")
    verify.check_quotes(run); verify.settle(run)
    assert status(run) == ("proposed", "support_check_outdated")


def test_editing_a_field_after_support_check_makes_the_check_outdated(tmp_path):
    run = _checked_and_supported(tmp_path)
    _edit_fact(run, fields={"planned_start": "2027"})
    verify.check_quotes(run); verify.settle(run)
    assert status(run) == ("proposed", "support_check_outdated")


def test_changing_the_source_after_support_check_makes_the_check_outdated(tmp_path):
    run = _checked_and_supported(tmp_path)
    add_source(run, TEXT_A, publisher="Another Paper")   # a source that holds the same quote
    _edit_fact(run, source_id="S3")
    verify.check_quotes(run); verify.settle(run)
    assert status(run) == ("proposed", "support_check_outdated")


def test_changing_the_source_to_one_without_the_quote_rejects_the_fact(tmp_path):
    # Was "support_check_outdated" before a quote that is not found settled without a support verdict.
    run = _checked_and_supported(tmp_path)
    _edit_fact(run, source_id="S2")
    verify.check_quotes(run); verify.settle(run)
    assert status(run) == ("rejected", "not_found")


def test_changing_a_supporting_entry_after_support_check_makes_the_check_outdated(tmp_path):
    run = _checked_and_supported(tmp_path)
    _edit_fact(run, supporting=[{"source_id": "S2", "quote": "two new syringe lines will open in 2028"}])
    verify.check_quotes(run); verify.settle(run)
    assert status(run) == ("proposed", "support_check_outdated")


def test_recording_support_again_after_the_edit_confirms(tmp_path):
    run = _checked_and_supported(tmp_path)
    _edit_fact(run, quote="two high-speed syringe lines for customers, starting in 2028")
    verify.check_quotes(run); verify.settle(run)
    assert status(run) == ("proposed", "support_check_outdated")
    verify.record_support(run, "F1", True, "support-checker", "re-read")
    verify.settle(run)
    assert status(run) == ("confirmed", None)


def test_support_record_without_a_content_digest_is_outdated(tmp_path):
    run = _checked_and_supported(tmp_path)
    fact = store.read_facts(run)["F1"]
    del fact["checks"]["support"]["content_sha256"]
    store.write_fact(run, fact)
    verify.settle(run)
    assert status(run) == ("proposed", "support_check_outdated")


def test_settle_alone_rejects_a_quote_edited_after_an_earlier_pass(tmp_path):
    run = _checked_and_supported(tmp_path)
    _edit_fact(run, quote="adds five high-speed syringe lines for customers")
    verify.settle(run)  # no check_quotes call
    assert store.read_facts(run)["F1"]["checks"]["quote"]["passed"] is False
    assert status(run)[0] != "confirmed"
    verify.record_support(run, "F1", True, "support-checker", "")
    verify.settle(run)
    assert status(run) == ("rejected", "not_found")


def test_a_string_false_in_the_support_check_does_not_count_as_passed(tmp_path):
    run = _checked_and_supported(tmp_path)
    fact = store.read_facts(run)["F1"]
    fact["checks"]["support"]["passed"] = "false"
    store.write_fact(run, fact)
    verify.settle(run)
    assert status(run) == ("rejected", "not_supported")


def test_a_string_true_in_a_quote_check_does_not_count_as_passed():
    sources = {"S1": _src("S1", "A"), "S2": _src("S2", "B")}
    fact = {"source_id": "S1", "supporting": [], "statement": "s", "quote": "q", "fields": None,
            "primary_source": True, "certainty": "firm", "tentative_reason": None,
            "checks": {"quote": {"passed": "true", "reason": None}, "supporting": [], "support": None}}
    fact["checks"]["support"] = {"passed": True, "content_sha256": verify.content_digest(fact)}
    assert verify.expected_status(fact, sources)[0] == "rejected"
    fact["checks"]["quote"] = {"passed": True}
    fact["checks"]["supporting"] = [{"source_id": "S2", "passed": "true"}]
    fact["primary_source"] = False
    fact["checks"]["support"]["content_sha256"] = verify.content_digest(fact)
    assert verify.expected_status(fact, sources) == ("rejected", "supporting_quote_not_found")


def test_content_digest_is_stable_and_covers_every_part():
    base = {"statement": "s", "quote": "q", "source_id": "S1",
            "supporting": [{"source_id": "S2", "quote": "q2", "extra": "ignored"}],
            "fields": {"company": "A", "size_value": "2"},
            "primary_source": False, "certainty": "firm", "tentative_reason": None}
    digest = verify.content_digest(base)
    assert digest == verify.content_digest(json.loads(json.dumps(base)))
    assert digest == verify.content_digest({**base, "status": "confirmed", "status_reason": None,
                                            "id": "F1", "fields": {"size_value": "2", "company": "A"}})
    assert len(digest) == 64
    changed = [
        {**base, "statement": "s2"},
        {**base, "quote": "q3"},
        {**base, "source_id": "S3"},
        {**base, "supporting": [{"source_id": "S2", "quote": "other"}]},
        {**base, "supporting": [{"source_id": "S9", "quote": "q2"}]},
        {**base, "supporting": []},
        {**base, "fields": {"company": "A", "size_value": "3"}},
        {**base, "fields": None},
        {**base, "primary_source": True},
        {**base, "certainty": "tentative"},
        {**base, "tentative_reason": "only one report"},
        {**base, "early_signal": True},
    ]
    digests = {verify.content_digest(fact) for fact in changed}
    assert digest not in digests and len(digests) == len(changed)


def test_making_a_fact_primary_after_support_check_makes_the_check_outdated(tmp_path):
    run = _checked_and_supported(tmp_path)
    _edit_fact(run, primary_source=False)
    verify.record_support(run, "F1", True, "support-checker", "direct")
    verify.settle(run)
    assert status(run) == ("uncertain", verify.NOT_PRIMARY_REASON)
    _edit_fact(run, primary_source=True)
    verify.settle(run)
    assert status(run) == ("proposed", "support_check_outdated")



# --- final fix I3: a withdrawn fact is rejected, and withdrawing is not an edit ---------------------

def test_a_withdrawn_fact_is_rejected_first(tmp_path):
    run = _checked_and_supported(tmp_path)
    verify.settle(run)
    assert status(run) == ("confirmed", None)
    verify.withdraw_fact(run, "F1", "the release was retracted")
    verify.settle(run)
    assert status(run) == ("rejected", "withdrawn")


def test_withdrawing_does_not_change_the_content_digest(tmp_path):
    run = _checked_and_supported(tmp_path)
    before = verify.content_digest(store.read_facts(run)["F1"])
    verify.withdraw_fact(run, "F1", "the release was retracted")
    assert verify.content_digest(store.read_facts(run)["F1"]) == before


def test_a_fact_that_was_never_checked_can_still_be_withdrawn(tmp_path):
    run = setup(tmp_path, primary_source=True, quote="two syringe lines")
    verify.withdraw_fact(run, "F1", "the quote is too short to check")
    verify.settle(run)
    assert status(run) == ("rejected", "withdrawn")


def test_withdraw_fact_refuses_an_unknown_fact_or_an_empty_reason(tmp_path):
    run = setup(tmp_path, primary_source=True)
    with pytest.raises(ValueError, match="F9"):
        verify.withdraw_fact(run, "F9", "gone")
    with pytest.raises(ValueError):
        verify.withdraw_fact(run, "F1", "  ")


# --- a quote that is not found settles without a support verdict; the translation is part of the verdict ---

def test_a_quote_that_is_not_found_is_rejected_without_a_support_verdict(tmp_path):
    run = setup(tmp_path, primary_source=True, quote="adds five high-speed syringe lines for customers")
    verify.check_quotes(run)
    verify.settle(run)
    assert status(run) == ("rejected", "not_found")


def test_a_supporting_quote_that_is_not_found_is_rejected_without_a_support_verdict(tmp_path):
    run = setup(tmp_path, primary_source=True,
                supporting=[{"source_id": "S2", "quote": "five new syringe lines will open in 2028"}])
    verify.check_quotes(run)
    verify.settle(run)
    assert status(run) == ("rejected", "supporting_quote_not_found")


def test_a_found_quote_without_a_support_verdict_still_waits(tmp_path):
    run = setup(tmp_path, primary_source=True,
                supporting=[{"source_id": "S2", "quote": "two new syringe lines will open in 2028"}])
    verify.check_quotes(run)
    verify.settle(run)
    assert status(run) == ("proposed", "checks_incomplete")


def test_a_quote_that_stopped_matching_is_rejected_even_when_the_verdict_is_outdated(tmp_path):
    run = _checked_and_supported(tmp_path)
    _edit_fact(run, statement="Competitor A will add ten lines.", quote="adds nine high-speed syringe lines")
    verify.settle(run)
    assert status(run) == ("rejected", "not_found")


def test_changing_the_translation_outdates_the_support_check(tmp_path):
    run = _checked_and_supported(tmp_path, quote_translation="A first translation.")
    fact = store.read_facts(run)["F1"]
    assert verify.expected_status(fact, store.read_sources(run)) == ("confirmed", None)
    fact["quote_translation"] = "A different translation."
    store.write_fact(run, fact)
    changed = store.read_facts(run)["F1"]
    assert verify.expected_status(changed, store.read_sources(run)) == ("proposed", "support_check_outdated")


# --- early signals: covered by the digest and never confirmed -----------------------------------

def test_flipping_early_signal_outdates_the_support_check(tmp_path):
    run = _checked_and_supported(tmp_path)
    verify.settle(run)
    assert status(run) == ("confirmed", None)
    _edit_fact(run, early_signal=True)
    verify.check_quotes(run); verify.settle(run)
    assert status(run) == ("proposed", "support_check_outdated")


def test_clearing_early_signal_outdates_the_support_check_too(tmp_path):
    run = _checked_and_supported(tmp_path, early_signal=True, certainty="tentative", tentative_reason="a permit")
    verify.settle(run)
    assert status(run) == ("uncertain", "a permit")
    _edit_fact(run, early_signal=False)
    verify.settle(run)
    assert status(run) == ("proposed", "support_check_outdated")


def test_the_digest_of_a_fact_without_early_signal_does_not_change():
    base = {"statement": "s", "quote": "q", "source_id": "S1", "supporting": [], "fields": None,
            "primary_source": True, "certainty": "firm", "tentative_reason": None}
    assert verify.content_digest({**base, "early_signal": False}) == verify.content_digest(base)
    assert verify.content_digest({**base, "early_signal": True}) != verify.content_digest(base)
    # a value that is not a boolean (check-data names it) counts as set, never as unset
    assert verify.content_digest({**base, "early_signal": "yes"}) == verify.content_digest({**base, "early_signal": True})


def _early_signal_fact(**over):
    base = {"source_id": "S1", "primary_source": True, "certainty": "firm", "tentative_reason": None,
            "statement": "s", "quote": "q", "supporting": [], "fields": None, "early_signal": True}
    base.update(over)
    base["checks"] = {"quote": {"passed": True}, "supporting": [],
                      "support": {"passed": True, "content_sha256": verify.content_digest(base)}}
    return base


def test_an_early_signal_can_never_be_confirmed():
    sources = {"S1": _src("S1", "A"), "S2": _src("S2", "B")}
    firm_and_primary = _early_signal_fact()
    assert verify.expected_status(firm_and_primary, sources) == ("uncertain", verify.EARLY_SIGNAL_REASON)
    second_source = _early_signal_fact(primary_source=False, supporting=[{"source_id": "S2", "quote": "q2"}])
    second_source["checks"]["supporting"] = [{"source_id": "S2", "passed": True}]
    second_source["checks"]["support"]["content_sha256"] = verify.content_digest(second_source)
    assert verify.expected_status(second_source, sources) == ("uncertain", verify.EARLY_SIGNAL_REASON)
    tentative = _early_signal_fact(certainty="tentative", tentative_reason="a permit, not an announcement")
    assert verify.expected_status(tentative, sources) == ("uncertain", "a permit, not an announcement")
    by_hand = _early_signal_fact(early_signal="yes")   # not a boolean: check-data refuses it, and it is still not confirmed
    assert verify.expected_status(by_hand, sources) == ("uncertain", verify.EARLY_SIGNAL_REASON)
    failed = _early_signal_fact()
    failed["checks"]["support"]["passed"] = False
    assert verify.expected_status(failed, sources) == ("rejected", "not_supported")   # the earlier rules still come first


def test_no_sequence_of_commands_confirms_an_early_signal(tmp_path, capsys):
    run = make_run(tmp_path)
    add_source(run, PERMIT_TEXT, type="permit", publisher="Planning Office")
    add_source(run, "A trade paper reports an application for a new filling hall at Plant North.", publisher="Trade Paper")
    refused = early_signal_proposal(certainty="firm", tentative_reason=None)
    path = run / "firm.json"
    path.write_text(json.dumps(refused), encoding="utf-8")
    assert main(["add-fact", "--run", str(run), "--file", str(path)]) == 2   # the engine refuses it up front
    assert store.read_facts(run) == {}
    # a record written by hand that the engine would have refused, with a second independent source behind it
    hand_made = store.proposed_fact(refused, "F1")
    hand_made["supporting"] = [{"source_id": "S2", "quote": "an application for a new filling hall at Plant North"}]
    store.write_fact(run, hand_made)
    store.record_created(run, "F", "F1")
    verify.check_quotes(run)
    verify.record_support(run, "F1", True, "support-checker", "")
    assert verify.settle(run) == {"F1": "uncertain"}
    assert status(run) == ("uncertain", verify.EARLY_SIGNAL_REASON)
    capsys.readouterr()
    assert main(["settle", "--run", str(run)]) == 0
    assert status(run)[0] == "uncertain"


# --- one helper decides what an early signal is ---------------------------------------------------------

def test_only_a_missing_key_none_or_false_means_unset():
    for unset in ({}, {"early_signal": None}, {"early_signal": False}):
        assert verify.is_early_signal(unset) is False, unset
    for set_ in ({"early_signal": True}, {"early_signal": "yes"}, {"early_signal": 1}, {"early_signal": 0},
                 {"early_signal": 0.0}, {"early_signal": ""}, {"early_signal": []}):
        assert verify.is_early_signal(set_) is True, set_


def test_a_fact_from_an_early_signal_source_type_is_one_without_the_mark():
    sources = {"S1": {"type": "job_posting"}, "S2": {"type": "company_release"}, "S3": {"type": "permit"},
               "S4": {"type": "regulator_record"}}
    for source_id, expected in (("S1", True), ("S2", False), ("S3", True), ("S4", True), ("S9", False)):
        assert verify.is_early_signal({"source_id": source_id}, sources) is expected, source_id
    assert verify.is_early_signal({"source_id": "S1", "early_signal": False}, sources) is True
    assert verify.is_early_signal({"source_id": "S1"}) is False                     # no sources, nothing to go on
    assert verify.is_early_signal({"source_id": "S1", "source": {"type": "permit"}}) is True    # a model fact carries it
    assert verify.is_early_signal({"source_id": ["S1"]}, sources) is False                      # never raises


def test_a_hand_made_fact_from_a_permit_without_the_mark_settles_uncertain_never_confirmed():
    sources = {"S1": {"id": "S1", "type": "permit", "publisher": "A"}, "S2": _src("S2", "B")}
    fact = {"source_id": "S1", "primary_source": True, "certainty": "firm", "tentative_reason": None,
            "statement": "s", "quote": "q", "supporting": [], "fields": None}
    fact["checks"] = {"quote": {"passed": True}, "supporting": [],
                      "support": {"passed": True, "content_sha256": verify.content_digest(fact)}}
    assert verify.expected_status(fact, sources) == ("uncertain", verify.EARLY_SIGNAL_REASON)
    ordinary = {**fact, "source_id": "S2"}                       # the same fact from an ordinary source
    ordinary["checks"] = {**fact["checks"], "support": {"passed": True, "content_sha256": verify.content_digest(ordinary)}}
    assert verify.expected_status(ordinary, sources) == ("confirmed", None)


def test_a_stored_fact_from_a_job_posting_settles_uncertain_through_settle(tmp_path):
    run = make_run(tmp_path)
    add_source(run, TEXT_A, type="job_posting", publisher="Careers Page")
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    verify.check_quotes(run)
    verify.record_support(run, "F1", True, "support-checker", "")
    assert verify.settle(run) == {"F1": "uncertain"}
    assert status(run) == ("uncertain", verify.EARLY_SIGNAL_REASON)


def test_the_context_packet_reports_an_early_signal_by_mark_or_by_source(tmp_path):
    from radar import context
    run = make_run(tmp_path)
    add_source(run, TEXT_A, type="job_posting", publisher="Careers Page")
    add_source(run, TEXT_B, publisher="Trade Paper")
    add_fact(run, source_id="S1", primary_source=True, quote="adds two high-speed syringe lines for customers")
    add_fact(run, source_id="S2", primary_source=True, quote="two new syringe lines will open in 2028")
    assert context.packet(run, "F1")["early_signal"] is True
    assert context.packet(run, "F2")["early_signal"] is False


# --- Part A fix A1, ruling HG3: a stored quote that is not text is a quote not found, never a traceback ------

def _run_cli(capsys, *argv):
    code = main([str(part) for part in argv])
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    return code, json.loads(out)


@pytest.mark.parametrize("bad", [42, ["adds", "two", "lines"], {"text": "adds two lines"}])
def test_a_supporting_quote_that_is_not_text_is_not_found_by_every_command(tmp_path, capsys, bad):
    run = setup(tmp_path, primary_source=False)
    fact = store.read_facts(run)["F1"]
    fact["supporting"] = [{"source_id": "S2", "quote": bad}]   # written by hand, past the proposal check
    store.write_fact(run, fact)
    code, out = _run_cli(capsys, "check-quotes", "--run", run)
    assert code == 0 and out["failed"] == ["F1"]
    assert out["facts"]["F1"]["supporting"] == [{"source_id": "S2", "passed": False, "mode": None,
                                                  "reason": "not_found"}]
    code, out = _run_cli(capsys, "quote-context", "--run", run, "--open")
    assert code == 0 and out == {"packets": []}
    code, out = _run_cli(capsys, "quote-context", "--run", run, "--fact", "F1")
    assert code == 0 and [entry["found"] for entry in out["packets"][0]["quotes"]] == [True, False]
    code, out = _run_cli(capsys, "settle", "--run", run)
    assert code == 0 and out["status"] == {"F1": "rejected"}
    assert status(run) == ("rejected", "supporting_quote_not_found")
    code, out = _run_cli(capsys, "withdraw-fact", "--run", run, "--fact", "F1", "--reason", "the quote is broken")
    assert code == 0 and out == {"ok": True}
    assert _run_cli(capsys, "settle", "--run", run) == (0, {"status": {"F1": "rejected"},
                                                            "counts": {"proposed": 0, "confirmed": 0,
                                                                       "uncertain": 0, "rejected": 1}})


def test_a_main_quote_that_is_not_text_is_not_found_either(tmp_path, capsys):
    run = setup(tmp_path, primary_source=True)
    fact = store.read_facts(run)["F1"]
    fact["quote"] = 42
    store.write_fact(run, fact)
    code, out = _run_cli(capsys, "check-quotes", "--run", run)
    assert code == 0 and out["facts"]["F1"]["quote"]["reason"] == "not_found"
    assert _run_cli(capsys, "settle", "--run", run)[1]["status"] == {"F1": "rejected"}
    code, out = _run_cli(capsys, "quote-context", "--run", run, "--fact", "F1")
    assert code == 0 and out["packets"][0]["quotes"][0]["found"] is False


# --- follow-up, point 4: neighbouring hand damage is a quote not found, never a trace --------------------------

GOOD_SUPPORT = {"source_id": "S2", "quote": "two new syringe lines will open in 2028"}
HAND_DAMAGE = {
    "a supporting entry that is a bare string": {"supporting": ["S2"]},
    "supporting written as an object": {"supporting": GOOD_SUPPORT},
    "a source_id that is a list": {"source_id": ["S1"]},
    "a source_id that is an object": {"source_id": {"id": "S1"}},
    "a supporting source_id that is a list": {"supporting": [dict(GOOD_SUPPORT, source_id=["S2"])]},
    "a supporting source_id that is an object": {"supporting": [dict(GOOD_SUPPORT, source_id={"id": "S2"})]},
}


@pytest.mark.parametrize("damage", list(HAND_DAMAGE), ids=list(HAND_DAMAGE))
def test_neighbouring_hand_damage_is_a_quote_not_found_in_every_command(tmp_path, capsys, damage):
    from radar.schema import check_data
    run = setup(tmp_path, primary_source=True, supporting=[GOOD_SUPPORT])
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", "")
    assert verify.settle(run) == {"F1": "confirmed"}
    fact = store.read_facts(run)["F1"]
    fact.update(HAND_DAMAGE[damage])                          # written by hand, past every check
    store.write_fact(run, fact)
    assert any(problem.file == "facts/F1.json" for problem in check_data(run))   # the data check names it
    code, out = _run_cli(capsys, "check-quotes", "--run", run)
    assert code == 0 and out["failed"] == ["F1"]
    assert _run_cli(capsys, "quote-context", "--run", run, "--open") == (0, {"packets": []})
    code, out = _run_cli(capsys, "quote-context", "--run", run, "--fact", "F1")
    assert code == 0 and False in [quote["found"] for quote in out["packets"][0]["quotes"]]
    code, out = _run_cli(capsys, "settle", "--run", run)
    assert code == 0 and out["status"] == {"F1": "rejected"}
    assert status(run)[1] in ("no_saved_copy", "not_found", "supporting_quote_not_found")
    assert _run_cli(capsys, "record-support", "--run", run, "--fact", "F1", "--passed", "true", "--by", "c",
                    "--note", "n") == (0, {"ok": True})
    assert _run_cli(capsys, "withdraw-fact", "--run", run, "--fact", "F1", "--reason", "damaged by hand") == \
        (0, {"ok": True})
    code, out = _run_cli(capsys, "settle", "--run", run)
    assert code == 0 and out["status"] == {"F1": "rejected"} and status(run) == ("rejected", "withdrawn")


# --- Part A fix A1, ruling HG7: two sources that are really one page are not independent ----------------------

def _page(sid, publisher, url=None, final_url=None, copy=None):
    return {"id": sid, "publisher": publisher, "based_on": [], "url": url, "final_url": final_url,
            "copy_sha256": copy}


def test_the_same_saved_copy_is_never_independent_of_itself():
    sources = {"S1": _page("S1", "Competitor A", "https://www.example.com/a", copy="c" * 64),
               "S2": _page("S2", "Trade Paper", "https://news.example.org/b", copy="c" * 64),
               "S3": _page("S3", "Other Paper", "https://news.example.net/c", copy="d" * 64)}
    assert verify.independent("S1", "S2", sources) is False
    assert verify.independent("S2", "S1", sources) is False
    assert verify.independent("S1", "S3", sources) is True


@pytest.mark.parametrize("first, second", [
    (("https://www.example.com/a", None), ("https://www.example.com/a", None)),
    (("https://www.example.com/a", None), ("HTTPS://WWW.Example.COM.:443/a", None)),      # another spelling
    (("https://www.example.com", None), ("https://www.example.com/", None)),
    (("https://www.example.com/a", None), ("https://news.example.org/b", "https://www.example.com/a")),
    (("https://old.example.com/x", "https://www.example.com/a"), ("https://www.example.com/a", None)),
    (("https://www.example.com/a", None), ("https://www.example.com/b", None)),           # HG10: same site
    (("https://example.com:8443/a", None), ("http://www.example.com/b", None)),           # port and scheme ignored
])
def test_the_same_site_is_never_independent(first, second):
    sources = {"S1": _page("S1", "Competitor A", *first, copy="a" * 64),
               "S2": _page("S2", "Trade Paper", *second, copy="b" * 64)}
    assert verify.independent("S1", "S2", sources) is False


@pytest.mark.parametrize("first, second", [
    (("https://www.example.com/a", None), ("https://news.example.org/a", None)),
    (("https://example.com/a", None), ("https://news.example.com/a", None)),              # a sub-site is another site
    (("https://www.www.example.com/a", None), ("https://example.com/a", None)),            # one leading www. only
    (("https://www.example.com/a", "https://www.example.com/z"), ("https://www.example.com/a", "https://x.example/a")),
    (("internal://example-pharma/memo", None), ("internal://example-pharma/memo", None)),   # by copy only
    (("internal capacity review", None), ("internal capacity review", None)),
])
def test_different_sites_and_sources_without_a_web_address_stay_independent(first, second):
    sources = {"S1": _page("S1", "Competitor A", *first, copy="a" * 64),
               "S2": _page("S2", "Trade Paper", *second, copy="b" * 64)}
    assert verify.independent("S1", "S2", sources) is True
    assert verify.independent("S1", "S2", sources, {"S1": "x" * 64, "S2": "y" * 64}) is True


def test_two_sources_without_a_copy_are_not_one_page_by_their_missing_copy():
    sources = {"S1": _page("S1", "Competitor A", "https://www.example.com/a"),
               "S2": _page("S2", "Trade Paper", "https://news.example.org/b")}
    assert verify.independent("S1", "S2", sources) is True
    assert verify.independent("S1", "S2", sources, {}) is True


def test_the_same_text_is_never_independent_whatever_the_address():
    sources = {"S1": _page("S1", "Competitor A", "internal://example-pharma/memo", copy="a" * 64),
               "S2": _page("S2", "Trade Paper", "https://news.example.org/b", copy="b" * 64)}
    assert verify.independent("S1", "S2", sources, {"S1": "t" * 64, "S2": "t" * 64}) is False
    assert verify.independent("S1", "S2", sources, {"S1": "t" * 64, "S2": "u" * 64}) is True


# --- Part A fix A2, item 9: an address typed without its scheme still names its site -----------------------------

@pytest.mark.parametrize("bare", ["WWW.site-a.example/x", "site-a.example", "site-a.example/", "Site-A.EXAMPLE/a/b.pdf",
                                  "www.site-a.example/annual-report-2025.pdf"])
def test_an_address_without_a_scheme_names_the_site_it_would_have_with_https(bare):
    assert verify.site_of(bare) == verify.site_of("https://www.site-a.example/y") == "site-a.example"
    sources = {"S1": _page("S1", "Competitor A", bare, copy="a" * 64),
               "S2": _page("S2", "Trade Paper", "https://www.site-a.example/y", copy="b" * 64)}
    assert verify.independent("S1", "S2", sources) is False
    assert verify.independent("S2", "S1", sources, {"S1": "x" * 64, "S2": "y" * 64}) is False


@pytest.mark.parametrize("words", [
    "internal://notes", "notes from a call", "a.b c", "notes", "", "site-a.example:8080/x", "site-a.example?x=1",
    # A2 fix round 1, IMPORTANT 4 (HG16): file names, empty or bad labels, a last label that is not letters only
    "file.pdf", "annual-report-2025.pdf", "memo.txt", "s1.json", "report.HTML", "data.xlsx", "slides.pptx",
    "export.csv", "notes.md", "archive.zip", "photo.jpeg", "Memo.Docx", "www.", ".example", "a..b", "www.site-a.example.",
    "-site.example", "site-.example", "site.example-", "site.ex-ample", "site.example2", "site.123", "1.5", "a_b.example",
    "localhost", "localhost/x"])
def test_free_words_and_other_addresses_without_a_scheme_name_no_site(words):
    assert verify.site_of(words) is None
    sources = {"S1": _page("S1", "Competitor A", words, copy="a" * 64),
               "S2": _page("S2", "Trade Paper", words, copy="b" * 64)}
    assert verify.independent("S1", "S2", sources) is True   # compared by copy only


@pytest.mark.parametrize("second_url,expected", [("https://www.site-a.example/y", "uncertain"),
                                                 ("https://www.site-b.example/y", "confirmed")])
def test_add_copy_with_an_address_typed_without_its_scheme_is_judged_by_its_site(tmp_path, second_url, expected):
    from radar import fetch
    run = make_run(tmp_path / "runs")
    meta = {"title": "Lines", "date": "2026-05-14", "type": "trade_press", "speaker": "a reporter",
            "interest": "wants readers", "language": "en"}
    for name, publisher, url, text in (("one.txt", "Trade Paper", "WWW.site-a.example/x", TEXT_A),
                                       ("two.txt", "Other Paper", second_url, TEXT_A + " One more sentence here.")):
        page = tmp_path / name
        page.write_text(text, encoding="utf-8")
        fetch.add_copy(run, page, url, {**meta, "publisher": publisher}, data_class="public")
    add_fact(run, source_id="S1", primary_source=False, quote="adds two high-speed syringe lines for customers",
             supporting=[{"source_id": "S2", "quote": "two high-speed syringe lines for customers, starting in 2028"}])
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", "")
    assert verify.settle(run) == {"F1": expected}


def test_two_hand_added_documents_with_the_same_file_name_are_compared_by_copy_only():
    sources = {"S1": _page("S1", "Competitor A", "annual-report-2025.pdf", copy="a" * 64),
               "S2": _page("S2", "Drug maker B", "annual-report-2025.pdf", copy="b" * 64)}
    assert verify.independent("S1", "S2", sources) is True
    assert verify.site_of("a.b") == "a.b" and verify.site_of("www.site-a.example/memo.txt") == "site-a.example"


# --- follow-up, ruling HG10: two sources saved from one site, or with one text, are one source ------------------

SITE_A = "https://www.example.com/news/lines"
ONE_MORE = " One more sentence that only this copy has."


def site_pair(tmp_path, second_url, second_text=TEXT_A + ONE_MORE, second_final=None):
    """S1 on SITE_A; S2 under another publisher at `second_url`. F1 rests on S1 and needs S2 to be confirmed."""
    run = make_run(tmp_path)
    add_source(run, TEXT_A, publisher="Competitor A", url=SITE_A)
    add_source(run, second_text, publisher="Trade Paper", url=second_url, final_url=second_final)
    add_fact(run, source_id="S1", primary_source=False, quote="adds two high-speed syringe lines for customers",
             supporting=[{"source_id": "S2", "quote": "two high-speed syringe lines for customers, starting in 2028"}])
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", "")
    return run


@pytest.mark.parametrize("second_url", [
    "http://www.example.com/news/lines",                       # http instead of https
    "https://example.com/news/lines",                          # without www.
    "https://www.example.com/news/lines?utm_source=newsletter",  # a tracking parameter
    "https://www.example.com/news/lines/",                     # a trailing slash
    "https://www.example.com/News/Lines",                      # the path in another case
    "https://www.example.com/news/%6Cines",                    # percent-encoding
])
def test_one_site_saved_twice_with_texts_one_sentence_apart_does_not_confirm(tmp_path, second_url):
    from radar.gate import gate
    from radar.schema import Problem
    run = site_pair(tmp_path, second_url)
    assert store.read_sources(run)["S1"]["copy_sha256"] != store.read_sources(run)["S2"]["copy_sha256"]
    assert verify.settle(run) == {"F1": "uncertain"} and status(run) == ("uncertain", verify.NOT_PRIMARY_REASON)
    fact = store.read_facts(run)["F1"]; fact["status"], fact["status_reason"] = "confirmed", None
    store.write_fact(run, fact)
    assert Problem("facts/F1.json", "status", "status does not follow from the checks") in gate(run)


def test_a_copy_passed_on_to_the_same_site_does_not_confirm(tmp_path):
    run = site_pair(tmp_path, "https://news.example.org/lines", second_final="https://example.com/news/lines")
    assert verify.settle(run) == {"F1": "uncertain"}


def test_two_pages_on_two_sites_still_confirm(tmp_path):
    run = site_pair(tmp_path, "https://news.example.org/lines")
    assert verify.settle(run) == {"F1": "confirmed"}


@pytest.mark.parametrize("second_text", [TEXT_A, TEXT_A + "\n", "  " + TEXT_A.replace(" ", "  \n ") + "\n\n"])
def test_the_same_text_on_two_sites_does_not_confirm_whatever_its_white_space(tmp_path, second_text):
    from radar.gate import gate
    from radar.schema import Problem
    run = site_pair(tmp_path, "https://news.example.org/lines", second_text=second_text)
    assert verify.settle(run) == {"F1": "uncertain"}
    fact = store.read_facts(run)["F1"]; fact["status"], fact["status_reason"] = "confirmed", None
    store.write_fact(run, fact)
    assert Problem("facts/F1.json", "status", "status does not follow from the checks") in gate(run)


def one_page_twice(tmp_path, **second):
    """A non-primary fact on S1 whose supporting quote is in S2: S2 is the same text under another publisher."""
    run = make_run(tmp_path)
    add_source(run, TEXT_A, publisher="Competitor A", url="https://www.example.com/news/lines")
    add_source(run, TEXT_A, publisher="Trade Paper", **second)
    add_fact(run, source_id="S1", primary_source=False, quote="adds two high-speed syringe lines for customers",
             supporting=[{"source_id": "S2", "quote": "two high-speed syringe lines for customers, starting in 2028"}])
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", "")
    return run


@pytest.mark.parametrize("second", [{"url": "https://www.example.com/news/lines"},          # same page, same copy
                                    {"url": "https://news.example.org/copied-release"},     # same copy elsewhere
                                    {"url": "HTTPS://WWW.Example.com:443/news/lines"}])      # another spelling
def test_the_same_page_saved_twice_under_two_publishers_does_not_confirm(tmp_path, second):
    from radar.gate import gate
    from radar.schema import Problem
    run = one_page_twice(tmp_path, **second)
    assert verify.settle(run) == {"F1": "uncertain"} and status(run) == ("uncertain", verify.NOT_PRIMARY_REASON)
    fact = store.read_facts(run)["F1"]; fact["status"], fact["status_reason"] = "confirmed", None
    store.write_fact(run, fact)
    assert Problem("facts/F1.json", "status", "status does not follow from the checks") in gate(run)


def test_the_same_address_with_a_different_copy_does_not_confirm_either(tmp_path):
    run = make_run(tmp_path)
    add_source(run, TEXT_A, publisher="Competitor A", url="https://www.example.com/news/lines")
    add_source(run, TEXT_A + " A sentence added later.", publisher="Trade Paper",
               url="https://www.example.com/news/lines")
    add_fact(run, source_id="S1", primary_source=False, quote="adds two high-speed syringe lines for customers",
             supporting=[{"source_id": "S2", "quote": "two high-speed syringe lines for customers, starting in 2028"}])
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", "")
    assert verify.settle(run) == {"F1": "uncertain"}


def test_two_different_pages_still_confirm_and_the_demo_still_settles_as_designed(tmp_path):
    run = setup(tmp_path / "pages", primary_source=False,
                supporting=[{"source_id": "S2", "quote": "two new syringe lines will open in 2028"}])
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", "")
    assert verify.settle(run) == {"F1": "confirmed"}
    from radar.demo import build_demo_run
    demo = build_demo_run(tmp_path / "demo", stage="checked")
    counts = {}
    for fact in store.read_facts(demo).values():
        counts[fact["status"]] = counts.get(fact["status"], 0) + 1
    assert counts == {"confirmed": 6, "uncertain": 1, "rejected": 3}
    # Each invented publisher of the demo has a site of its own (A2, item 8); no demo fact needs a second source to be
    # confirmed, so each settles as designed (F1 to F6 by their primary source).
    assert len({urlsplit(source["url"]).hostname for source in store.read_sources(demo).values()}) == 6
    assert {fact_id: fact["status"] for fact_id, fact in store.read_facts(demo).items()} == {
        "F1": "confirmed", "F2": "confirmed", "F3": "confirmed", "F4": "confirmed", "F5": "confirmed",
        "F6": "confirmed", "F7": "uncertain", "F8": "rejected", "F9": "rejected", "F10": "rejected"}


# --- Part A fix A1, M13: the language of the quote is part of what the verdict was given for ------------------

def test_changing_the_quote_language_after_the_verdict_makes_the_gate_refuse(tmp_path):
    from radar.gate import gate
    from radar.schema import Problem
    run = setup(tmp_path, primary_source=True, quote_language="de",
                quote_translation="adds two high-speed syringe lines for customers")
    verify.check_quotes(run); verify.record_support(run, "F1", True, "support-checker", "")
    assert verify.settle(run) == {"F1": "confirmed"}
    fact = store.read_facts(run)["F1"]; fact["quote_language"] = "fr"; store.write_fact(run, fact)
    assert Problem("facts/F1.json", "status", "status does not follow from the checks") in gate(run)
    assert verify.expected_status(store.read_facts(run)["F1"], store.read_sources(run)) == \
        ("proposed", "support_check_outdated")


def test_a_fact_without_a_quote_language_keeps_the_digest_it_always_had():
    import hashlib
    fact = {"statement": "s", "quote": "q", "quote_translation": None, "source_id": "S1",
            "supporting": [{"source_id": "S2", "quote": "q2"}], "fields": None, "primary_source": True,
            "certainty": "firm", "tentative_reason": None}
    content = dict(fact)
    text = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    before = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert verify.content_digest(fact) == before
    assert verify.content_digest({**fact, "quote_language": None}) == before
    assert verify.content_digest({**fact, "quote_language": "en"}) != before
    assert verify.content_digest({**fact, "quote_language": "en"}) != verify.content_digest({**fact, "quote_language": "de"})


# --- DH1 part 4: a supporting quote from the fact's own source -------------------------------------------------------

REPORT = ("Drug maker B sold its plant in Plant West to Competitor C in March 2026. "
          "The site holds two filling lines for vials. The new owner plans to keep both lines running.")
REPORT_SITE = "The site holds two filling lines for vials."
REPORT_MOVE = "Drug maker B sold its plant in Plant West to Competitor C in March 2026."
PAPER = "A trade paper wrote that Competitor C bought Plant West with its two vial lines from Drug maker B this year."


def cli(capsys, *argv):
    code = main([str(arg) for arg in argv])
    return code, json.loads(capsys.readouterr().out)


def same_source_fact(tmp_path, capsys, supporting_quote=REPORT_SITE, **over):
    """A run with the seller's report and a trade paper, and one fact whose main quote states the move and whose one
    supporting quote, from the same report, states the site's size."""
    run = make_run(tmp_path)
    report = add_source(run, REPORT, publisher="Drug maker B", type="annual_report")
    paper = add_source(run, PAPER, publisher="Trade Paper", type="trade_press")
    fact = proposal(source_id=report["id"], quote=REPORT_MOVE,
                    statement="Drug maker B's report says it sold Plant West, with two vial lines, to Competitor C.",
                    supporting=[{"source_id": report["id"], "quote": supporting_quote}],
                    fields={"company": "Competitor C", "move_type": "acquisition", "site": "Plant West",
                            "country": "not_stated", "what_added": "two filling lines for vials", "size_value": "2",
                            "size_unit": "lines", "announced": "not_stated", "planned_start": "not_stated",
                            "stage": "not_stated", "access": "not_stated", "delivery": "unknown"})
    fact.update(over)
    file = tmp_path / "proposals.json"
    file.write_text(json.dumps([fact]), encoding="utf-8")
    assert cli(capsys, "add-facts", "--run", run, "--file", file) == (0, {"added": [{"index": 0, "fact_id": "F1"}],
                                                                         "refused": []})
    return run, report["id"], paper["id"]


def test_the_engine_takes_a_supporting_quote_from_the_fact_s_own_source(tmp_path, capsys):
    run, report_id, _ = same_source_fact(tmp_path, capsys)
    fact = store.read_facts(run)["F1"]
    assert fact["source_id"] == report_id and fact["supporting"] == [{"source_id": report_id, "quote": REPORT_SITE}]


def test_check_quotes_checks_a_same_source_supporting_quote_found_or_not(tmp_path, capsys):
    run, report_id, _ = same_source_fact(tmp_path / "found", capsys)
    code, out = cli(capsys, "check-quotes", "--run", run)
    supporting = out["facts"]["F1"]["supporting"]
    assert code == 0 and out["failed"] == [] and len(supporting) == 1
    assert supporting[0]["source_id"] == report_id and supporting[0]["passed"] is True
    run, report_id, _ = same_source_fact(tmp_path / "changed", capsys,
                                         supporting_quote="The site holds three filling lines for vials.")
    code, out = cli(capsys, "check-quotes", "--run", run)
    assert code == 0 and out["failed"] == ["F1"] and out["facts"]["F1"]["supporting"][0]["passed"] is False
    assert cli(capsys, "record-support", "--run", run, "--fact", "F1", "--passed", "true",
               "--by", "support-checker", "--note", "n")[0] == 0
    assert cli(capsys, "settle", "--run", run)[1]["status"] == {"F1": "rejected"}
    assert store.read_facts(run)["F1"]["status_reason"] == "supporting_quote_not_found"


def test_quote_context_shows_a_same_source_supporting_quote_in_its_passage(tmp_path, capsys):
    run, report_id, _ = same_source_fact(tmp_path, capsys)
    cli(capsys, "check-quotes", "--run", run)
    code, out = cli(capsys, "quote-context", "--run", run, "--fact", "F1")
    quotes = out["packets"][0]["quotes"]
    assert code == 0 and [quote["role"] for quote in quotes] == ["main", "supporting"]
    assert quotes[1]["source_id"] == report_id and quotes[1]["quote"] == REPORT_SITE
    assert quotes[1]["found"] is True and quotes[1]["located"] is True and quotes[1]["passage"] == REPORT_SITE
    assert quotes[1]["before"] == REPORT_MOVE
    assert list(out["packets"][0]["sources"]) == [report_id]           # one source, named once
    assert cli(capsys, "quote-context", "--run", run, "--open")[1]["packets"][0]["fact_id"] == "F1"


def test_a_same_source_supporting_quote_is_never_the_second_independent_source(tmp_path, capsys):
    run, report_id, paper_id = same_source_fact(tmp_path / "alone", capsys)
    cli(capsys, "check-quotes", "--run", run)
    cli(capsys, "record-support", "--run", run, "--fact", "F1", "--passed", "true", "--by", "support-checker",
        "--note", "The report states the sale and the two lines.")
    assert cli(capsys, "settle", "--run", run)[1]["status"] == {"F1": "uncertain"}
    assert store.read_facts(run)["F1"]["status_reason"] == verify.NOT_PRIMARY_REASON
    # the same fact with a quote from the trade paper as well: that one is independent, so the fact is confirmed
    run, report_id, paper_id = same_source_fact(
        tmp_path / "with-a-second-source", capsys,
        supporting=[{"source_id": report_id, "quote": REPORT_SITE},
                    {"source_id": "S2", "quote": "Competitor C bought Plant West with its two vial lines"}])
    cli(capsys, "check-quotes", "--run", run)
    cli(capsys, "record-support", "--run", run, "--fact", "F1", "--passed", "true", "--by", "support-checker",
        "--note", "The report states the sale; the trade paper states it too.")
    assert cli(capsys, "settle", "--run", run)[1]["status"] == {"F1": "confirmed"}


# --- fix wave A23.2: a site name with letters outside ASCII and its xn-- form are one site ----------------------------

UMLAUT_SITE = "https://www.b" + chr(0xFC) + "cher-lab.example/news"          # an invented name with u-umlaut


def test_a_site_name_outside_ascii_and_its_encoded_form_are_the_same_site():
    encoded = "https://xn--bcher-lab-q9a.example/other"
    assert "bücher-lab.example".encode("idna").decode("ascii") == "xn--bcher-lab-q9a.example"
    assert verify.site_of(UMLAUT_SITE) == verify.site_of(encoded) == "xn--bcher-lab-q9a.example"
    assert verify.site_of("https://WWW.B" + chr(0xDC) + "CHER-LAB.example/x") == "xn--bcher-lab-q9a.example"
    assert verify.site_of("https://www.site-a.example/x") == "site-a.example"      # plain names as before


SHARP_S_SITE = "https://stra" + chr(0xDF) + "e.example/news"                 # an invented name with a sharp s


def test_a_name_and_its_encoded_form_are_one_site_also_where_the_codec_and_browsers_differ():
    """Ruling FWA-5c: Python's codec writes the sharp s as "ss", a browser as xn--strae-oqa; both are one site here."""
    assert verify.site_of(SHARP_S_SITE) == verify.site_of("https://xn--strae-oqa.example/other")
    assert verify.site_of("https://www.XN--STRAE-OQA.example/") == verify.site_of(SHARP_S_SITE)
    assert verify.site_of(UMLAUT_SITE) == verify.site_of("https://xn--bcher-lab-q9a.example/") == \
        "xn--bcher-lab-q9a.example"
    for odd in ("https://xn--zz.example/", "https://xn--.example/", "https://xn--a-.xn--" + "b" * 70 + ".example/"):
        assert verify.site_of(odd) == odd.split("/")[2]      # a name that cannot be read that way stays as written


def test_two_copies_from_one_site_written_both_ways_are_not_independent(tmp_path):
    run = make_run(tmp_path)
    one = add_source(run, "Competitor A adds two lines, starting in 2028.", url=UMLAUT_SITE, publisher="Paper One")
    two = add_source(run, "Competitor A will add two lines from 2028, the paper says.",
                     url="https://xn--bcher-lab-q9a.example/b", publisher="Paper Two")
    assert not verify.independent(one["id"], two["id"], store.read_sources(run))


def test_a_name_that_cannot_be_encoded_is_compared_as_written_and_never_raises():
    for address in ("https://" + "a" * 70 + chr(0xFC) + ".example/x", "https://x" + chr(0x200B) + "y.example/"):
        verify.site_of(address)                                   # no exception


# --- fix wave A23.3: a supporting quote's translation is judged with the fact and shown with the quote -------------

GERMAN = "Competitor A baut zwei neue Abfülllinien im Werk Nord bis 2028."
ENGLISH = "Competitor A is building two new filling lines at Plant North by 2028."


def _with_translated_support(tmp_path):
    run = make_run(tmp_path)
    add_source(run, "Competitor A will add a second filling line at Plant North by 2028.", publisher="Competitor A")
    add_source(run, "Bericht: " + GERMAN, publisher="Fachblatt", language="de")
    add_fact(run, source_id="S1", primary_source=True, quote="Competitor A will add a second filling line at Plant North by 2028.",
             supporting=[{"source_id": "S2", "quote": GERMAN, "quote_translation": ENGLISH}])
    return run


def test_the_translation_of_a_supporting_quote_is_part_of_the_content_digest_only_when_set(tmp_path):
    run = _with_translated_support(tmp_path)
    fact = store.read_facts(run)["F1"]
    with_it = verify.content_digest(fact)
    changed = json.loads(json.dumps(fact))
    changed["supporting"][0]["quote_translation"] = "Competitor A is building three new lines."
    assert verify.content_digest(changed) != with_it
    without = json.loads(json.dumps(fact))
    without["supporting"][0].pop("quote_translation")
    none = json.loads(json.dumps(fact))
    none["supporting"][0]["quote_translation"] = None
    assert verify.content_digest(without) == verify.content_digest(none) != with_it
    # a fact whose supporting entries hold no translation hashes exactly as it did before
    content = {"statement": fact["statement"], "quote": fact["quote"], "quote_translation": None,
               "source_id": "S1", "supporting": [{"source_id": "S2", "quote": GERMAN}], "fields": fact["fields"],
               "primary_source": True, "certainty": "firm", "tentative_reason": None, "quote_language": "en"}
    text = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert verify.content_digest(without) == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_changing_a_supporting_translation_after_the_verdict_makes_the_verdict_outdated(tmp_path):
    run = _with_translated_support(tmp_path)
    verify.check_quotes(run)
    verify.record_support(run, "F1", True, "support-checker", "")
    assert verify.settle(run)["F1"] == "confirmed"
    fact = store.read_facts(run)["F1"]
    fact["supporting"][0]["quote_translation"] = "Competitor A is building three new lines."
    store.write_fact(run, fact)
    verify.settle(run)
    assert store.read_facts(run)["F1"]["status_reason"] == "support_check_outdated"


# --- why a fact is uncertain: the codes -----------------------------------------------------------------------------

def _supported(tmp_path, **fact_over):
    """A run with one fact (F1) whose quote check and support check are done, not yet settled."""
    run = setup(tmp_path, **fact_over)
    verify.check_quotes(run)
    verify.record_support(run, "F1", True, "support-checker", "direct")
    return run


def _codes(run, fact_id="F1"):
    sources = store.read_sources(run)
    return verify.uncertain_reasons(store.read_facts(run)[fact_id], sources, verify.copy_texts(run, sources))


def test_a_fact_from_one_source_that_is_not_the_party_has_one_code(tmp_path):
    run = _supported(tmp_path, primary_source=False)
    assert verify.expected_status(store.read_facts(run)["F1"], store.read_sources(run))[0] == "uncertain"
    assert _codes(run) == ["single_source"]


def test_a_tentative_fact_from_one_source_has_both_codes(tmp_path):
    run = _supported(tmp_path, primary_source=False, certainty="tentative", tentative_reason="one unnamed source")
    assert _codes(run) == ["tentative", "single_source"]


def test_a_tentative_fact_from_the_party_itself_has_only_the_tentative_code(tmp_path):
    run = _supported(tmp_path, primary_source=True, certainty="tentative", tentative_reason="the company may change it")
    assert _codes(run) == ["tentative"]


def test_an_early_signal_from_the_party_itself_has_its_two_codes(tmp_path):
    run = make_run(tmp_path)
    add_source(run, PERMIT_TEXT, type="permit", publisher="Planning Office")
    store.new_fact(run, early_signal_proposal())
    verify.check_quotes(run)
    verify.record_support(run, "F1", True, "support-checker", "direct")
    assert _codes(run) == ["tentative", "early_signal"]


def test_a_fact_a_second_source_confirms_has_no_code_and_the_codes_follow_the_status(tmp_path):
    run = _supported(tmp_path, primary_source=False,
                     supporting=[{"source_id": "S2", "quote": "two new syringe lines will open in 2028"}])
    verify.check_quotes(run)
    verify.record_support(run, "F1", True, "support-checker", "direct")
    assert verify.expected_status(store.read_facts(run)["F1"], store.read_sources(run))[0] == "confirmed"
    assert _codes(run) == []


def test_confirmed_rejected_and_proposed_facts_have_no_codes(tmp_path):
    run = _supported(tmp_path, primary_source=True)
    assert _codes(run) == []   # confirmed
    _edit_fact(run, quote="adds nine high-speed syringe lines for customers")
    verify.check_quotes(run)
    assert _codes(run) == []   # rejected: the quote is not found
    run = setup(tmp_path / "unchecked", primary_source=False)
    assert verify.expected_status(store.read_facts(run)["F1"], store.read_sources(run))[0] == "proposed"
    assert _codes(run) == []   # proposed: nothing is checked yet


def test_a_withdrawn_fact_has_no_codes(tmp_path):
    run = _supported(tmp_path, primary_source=False)
    verify.withdraw_fact(run, "F1", "a duplicate")
    assert _codes(run) == []


def test_settle_writes_the_codes_and_changes_no_status(tmp_path):
    run = make_run(tmp_path)
    add_source(run, TEXT_A, publisher="Competitor A")
    add_source(run, TEXT_B, publisher="Trade Paper")
    add_source(run, PERMIT_TEXT, type="permit", publisher="Planning Office")
    quote = "adds two high-speed syringe lines for customers"
    add_fact(run, source_id="S1", quote=quote, primary_source=True)                                  # F1 confirmed
    add_fact(run, source_id="S1", quote=quote, primary_source=False)                                 # F2 one source
    add_fact(run, source_id="S1", quote=quote, primary_source=False, certainty="tentative",
             tentative_reason="one unnamed source")                                                  # F3 both codes
    store.new_fact(run, early_signal_proposal(source_id="S3"))                                       # F4 early signal
    add_fact(run, source_id="S1", quote="adds nine high-speed syringe lines for customers")          # F5 rejected
    verify.check_quotes(run)
    for fact_id in ("F1", "F2", "F3", "F4"):
        verify.record_support(run, fact_id, True, "support-checker", "direct")
    digests = {fid: verify.content_digest(fact) for fid, fact in store.read_facts(run).items()}
    sources = store.read_sources(run)
    texts = verify.copy_texts(run, sources)
    before = {fid: verify.expected_status(fact, sources, texts) for fid, fact in store.read_facts(run).items()}
    verify.settle(run)
    facts = store.read_facts(run)
    assert {fid: (f["status"], f["status_reason"]) for fid, f in facts.items()} == before
    assert {fid: f["uncertain_reasons"] for fid, f in facts.items()} == {
        "F1": [], "F2": ["single_source"], "F3": ["tentative", "single_source"],
        "F4": ["tentative", "early_signal"], "F5": []}
    assert {fid: verify.content_digest(f) for fid, f in facts.items()} == digests
    assert not any(verify.needs_settling(f, sources, texts) for f in facts.values())


def test_a_settled_fact_without_codes_never_needs_settling(tmp_path):
    run = _supported(tmp_path, primary_source=False)
    verify.settle(run)
    fact = store.read_facts(run)["F1"]
    fact.pop("uncertain_reasons")
    store.write_fact(run, fact)
    sources = store.read_sources(run)
    assert verify.needs_settling(store.read_facts(run)["F1"], sources, verify.copy_texts(run, sources)) is False


# --- the company a fact is about and its connections are not part of what is checked ----------------------------------

def test_the_new_keys_leave_the_digest_and_the_status_alone(tmp_path):
    from radar import context, diff
    run = _checked_and_supported(tmp_path)
    verify.settle(run)
    without_keys = store.read_facts(run)["F1"]
    without_keys.pop("about_company"), without_keys.pop("connections")
    store.write_fact(run, without_keys)
    packet = context.packet(run, "F1")
    digest = diff.facts_digest(store.read_facts(run))
    with_keys = {**without_keys, "about_company": None,
                 "connections": [{"party": "Drug maker B", "tie": "customer", "description": None}]}
    assert verify.content_digest(with_keys) == verify.content_digest(without_keys)
    store.write_fact(run, with_keys)
    assert context.packet(run, "F1") == packet
    assert diff.facts_digest(store.read_facts(run)) == digest
    sources = store.read_sources(run)
    assert verify.needs_settling(store.read_facts(run)["F1"], sources, verify.copy_texts(run, sources)) is False
    verify.settle(run)
    after = store.read_facts(run)["F1"]
    assert (after["status"], after["status_reason"]) == (without_keys["status"], without_keys["status_reason"])
    assert after["connections"] == with_keys["connections"]
