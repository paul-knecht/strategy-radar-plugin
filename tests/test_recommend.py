"""The lens recommendation: the record the program writes for the lens advisor, its form check, the shape check that
`check-data` runs, and what the advisor is given to read. Everything here is invented."""
import io
import json
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from radar import cli, demo, recommend, store, verify
from radar.explain import explain
from radar.gate import gate
from radar.report.build import build_report
from radar.schema import Problem, check_data
from helpers import add_fact, add_source, finish_run, make_run, minimal_analysis

LENSES = demo.LENSES
QUESTION = "Which competitors are adding filling capacity, and for whom?"
TEXT = ("Competitor A will add a second filling line at Plant North by 2028. "
        "Competitor B opens a new filling hall at Plant South for one customer in 2027.")
NOW = datetime(2026, 11, 16, 9, 30, tzinfo=timezone.utc)


def recommend_run(tmp_path, question=QUESTION) -> Path:
    """A run whose F1 and F2 count (confirmed) and whose F3 was rejected (its quote is not in the copy)."""
    run = make_run(tmp_path, question=question)
    add_source(run, TEXT, publisher="Competitor A")
    add_fact(run, source_id="S1", primary_source=True)
    add_fact(run, source_id="S1", primary_source=True, statement="Competitor B opens a filling hall for one customer.",
             quote="Competitor B opens a new filling hall at Plant South for one customer in 2027.")
    add_fact(run, source_id="S1", primary_source=True, quote="Competitor A will add nine filling lines at Plant North.")
    finish_run(run, ["F1"], lens_id="firm-boundaries")
    assert {fid: fact["status"] for fid, fact in store.read_facts(run).items()} == {
        "F1": "confirmed", "F2": "confirmed", "F3": "rejected"}
    return run


def entry(**over) -> dict:
    result = {"lens": "firm-boundaries", "question_part": "adding filling capacity",
              "why": "Two facts describe plant built for a single customer.", "facts": ["F1", "F2"],
              "missing": "Nothing found on what protects that plant."}
    result.update(over)
    return result


def messages(problems) -> list[str]:
    return [problem.message for problem in problems]


def check(run, entries, note=None, lenses_dir=LENSES):
    return recommend.check_recommendation(run, lenses_dir, entries, note)


# --- the constants -----------------------------------------------------------------------------------------------

def test_the_constants():
    assert recommend.RECORD == "lens-recommendation.json"
    assert recommend.MAX_ENTRIES == 4
    assert recommend.ADVISOR == "lens-advisor"


# --- which facts count ---------------------------------------------------------------------------------------------

def test_a_fact_counts_when_confirmed_or_uncertain_and_not_withdrawn():
    assert recommend.counts({"status": "confirmed"}) and recommend.counts({"status": "uncertain"})
    assert not recommend.counts({"status": "rejected"}) and not recommend.counts({"status": "proposed"})
    assert not recommend.counts({})
    assert not recommend.counts({"status": "confirmed", "withdrawn": {"reason": "r", "at": "x"}})


# --- the rules, one by one -------------------------------------------------------------------------------------------

def test_a_good_list_passes(tmp_path):
    run = recommend_run(tmp_path)
    assert check(run, [entry(), entry(lens="capacity-commitment", facts=[])]) == []


def test_at_most_four_entries(tmp_path):
    run = recommend_run(tmp_path)
    folder = tmp_path / "lenses"
    shutil.copytree(LENSES, folder)
    for number in range(3):   # five lenses in all, so five different ones can be named
        lens = json.loads((folder / "firm-boundaries.json").read_text(encoding="utf-8"))
        lens["id"] = f"copy-{number}"
        (folder / f"copy-{number}.json").write_text(json.dumps(lens), encoding="utf-8")
    four = [entry(), entry(lens="capacity-commitment"), entry(lens="copy-0"), entry(lens="copy-1")]
    assert check(run, four, lenses_dir=folder) == []
    problems = check(run, four + [entry(lens="copy-2")], lenses_dir=folder)
    assert messages(problems) == [recommend.TOO_MANY] and problems[0].field == "entries"


def test_an_empty_list_with_a_note_is_recorded(tmp_path):
    run = recommend_run(tmp_path)
    recommend.record_recommendation(run, LENSES, [], "No lens fits a question about who the customers are.",
                                    recommend.ADVISOR, now=NOW)
    record = recommend.read_record(run)
    assert record["entries"] == [] and record["note"] == "No lens fits a question about who the customers are."


@pytest.mark.parametrize("note", [None, "", "   "])
def test_an_empty_list_without_a_note_is_refused(tmp_path, note):
    run = recommend_run(tmp_path)
    problems = check(run, [], note)
    assert messages(problems) == [recommend.NOTE_NEEDED] and problems[0].field == "note"
    with pytest.raises(recommend.RecommendationRefused):
        recommend.record_recommendation(run, LENSES, [], note, recommend.ADVISOR)
    assert recommend.read_record(run) is None


def test_entries_that_are_not_a_list_are_refused(tmp_path):
    run = recommend_run(tmp_path)
    assert messages(check(run, {"lens": "firm-boundaries"})) == [recommend.ENTRIES_NOT_A_LIST]


def test_every_lens_is_a_lens_file_of_the_folder(tmp_path):
    run = recommend_run(tmp_path)
    for lens in ("no-such-lens", "Firm-Boundaries", "themes", 7, None):
        problems = check(run, [entry(lens=lens)])
        assert messages(problems) == [recommend.LENS_NOT_FOUND], lens
        assert problems[0].field == "entries[0].lens"


def test_a_lens_that_fails_the_lens_check_is_refused(tmp_path):
    run = recommend_run(tmp_path)
    folder = tmp_path / "lenses"
    shutil.copytree(LENSES, folder)
    lens = json.loads((folder / "firm-boundaries.json").read_text(encoding="utf-8"))
    lens["questions"] = lens["questions"][:2]
    (folder / "firm-boundaries.json").write_text(json.dumps(lens), encoding="utf-8")
    problems = check(run, [entry()], lenses_dir=folder)
    assert messages(problems) == [recommend.LENS_FAILS_CHECK]


def test_a_lens_folder_that_cannot_be_listed_is_named(tmp_path, monkeypatch):
    run = recommend_run(tmp_path)
    monkeypatch.setattr(recommend.lenses, "lens_files", lambda folder: None)
    problems = check(run, [entry()])
    assert [(p.file, p.message) for p in problems] == [("lenses", recommend.lenses.FOLDER_UNREADABLE)]


def test_no_lens_twice(tmp_path):
    run = recommend_run(tmp_path)
    problems = check(run, [entry(), entry(question_part="for whom")])
    assert messages(problems) == [recommend.LENS_TWICE] and problems[0].field == "entries[1].lens"


@pytest.mark.parametrize("part", ["capacity", "Which competitors are adding filling capacity, and for whom? "
                                              "Which competitors are adding filling capacity, and"])   # 1 and 16
def test_the_question_part_has_2_to_15_words(tmp_path, part):
    run = recommend_run(tmp_path, question=QUESTION + " " + QUESTION)
    problems = check(run, [entry(question_part=part)])
    assert messages(problems) == [recommend.PART_WORDS] and problems[0].field == "entries[0].question_part"


@pytest.mark.parametrize("part", ["- 2028", "2028 ?", "plant -"])
def test_a_sign_alone_is_not_a_word(tmp_path, part):
    run = recommend_run(tmp_path, question="Will the plant - due by 2028 ? - open?")
    problems = check(run, [entry(question_part=part)])
    assert messages(problems) == [recommend.PART_WORDS], part


def test_a_word_with_a_sign_in_it_is_a_word(tmp_path):
    run = recommend_run(tmp_path, question="Will the plant - due by 2028 ? - open?")
    assert check(run, [entry(question_part="- due by")]) == []


def test_a_part_of_2_and_of_15_words_passes(tmp_path):
    question = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"
    run = recommend_run(tmp_path, question=question)
    assert check(run, [entry(question_part="one two")]) == []
    assert check(run, [entry(question_part=" ".join(question.split()[:15]))]) == []


def test_the_question_part_is_copied_from_the_question(tmp_path):
    run = recommend_run(tmp_path)
    problems = check(run, [entry(question_part="building capacity")])
    assert messages(problems) == [recommend.PART_NOT_IN_QUESTION] and problems[0].field == "entries[0].question_part"


def test_a_part_cut_inside_a_word_is_refused(tmp_path):
    run = recommend_run(tmp_path)
    for part in ("ompetitors are", "competitors are add", "filling capacit", "hich competitors"):
        assert messages(check(run, [entry(question_part=part)])) == [recommend.PART_NOT_IN_QUESTION], part


def test_a_part_may_start_or_end_on_a_sign(tmp_path):
    run = recommend_run(tmp_path)
    for part in ("capacity, and", "and for whom?", "for whom"):
        assert check(run, [entry(question_part=part)]) == [], part


def test_a_later_occurrence_on_word_boundaries_counts(tmp_path):
    run = recommend_run(tmp_path, question="Will they breathe city air, and who builds for the city?")
    assert check(run, [entry(question_part="the city")]) == []   # the first find is inside "breathe"
    run2 = recommend_run(tmp_path / "second", question="Who builds capacity near the cityscape and the city?")
    assert check(run2, [entry(question_part="the city")]) == []


def test_the_question_part_match_ignores_case_and_whitespace_only(tmp_path):
    question = "Which  Competitors are\nadding  \u201cfilling capacity\u201d,\tand for WHOM?"
    run = recommend_run(tmp_path, question=question)
    for part in ("which competitors ARE adding", "competitors   are \n adding", "\u201cfilling capacity\u201d",
                 "and for whom?"):
        assert check(run, [entry(question_part=part)]) == [], part
    for part in ('"filling capacity"', "competitors are-adding", "and for whom!", "and for whom ?"):
        assert messages(check(run, [entry(question_part=part)])) == [recommend.PART_NOT_IN_QUESTION], part


def test_the_same_fact_twice_in_one_entry_is_refused(tmp_path):
    run = recommend_run(tmp_path)
    problems = check(run, [entry(facts=["F1", "F2", "F1"])])
    assert messages(problems) == [recommend.FACT_TWICE] and problems[0].field == "entries[0].facts[2]"
    assert check(run, [entry(facts=["F1"]), entry(lens="capacity-commitment", facts=["F1"])]) == []


def test_every_fact_exists(tmp_path):
    run = recommend_run(tmp_path)
    for fact in ("F9", "f1", 1, None):
        problems = check(run, [entry(facts=["F1", fact])])
        assert messages(problems) == [recommend.FACT_UNKNOWN], fact
        assert problems[0].field == "entries[0].facts[1]"


def test_facts_must_be_a_list(tmp_path):
    run = recommend_run(tmp_path)
    for facts in ("F1", None, {"F1": True}):
        assert messages(check(run, [entry(facts=facts)])) == [recommend.FACTS_NOT_A_LIST], facts


def test_every_fact_counts(tmp_path):
    run = recommend_run(tmp_path)
    problems = check(run, [entry(facts=["F3"])])
    assert messages(problems) == [recommend.FACT_DOES_NOT_COUNT] and problems[0].field == "entries[0].facts[0]"


def test_a_withdrawn_unsettled_fact_is_refused_and_not_seen(tmp_path):
    run = recommend_run(tmp_path)
    verify.withdraw_fact(run, "F2", "A duplicate of F1.")
    assert store.read_facts(run)["F2"]["status"] == "confirmed"   # still, until the next settle
    assert messages(check(run, [entry(facts=["F2"])])) == [recommend.FACT_DOES_NOT_COUNT]
    recommend.record_recommendation(run, LENSES, [entry(facts=["F1"])], None, recommend.ADVISOR)
    assert recommend.read_record(run)["facts_seen"] == {"F1": "confirmed"}


@pytest.mark.parametrize("key", ["question_part", "why", "missing"])
def test_every_text_is_filled_in(tmp_path, key):
    run = recommend_run(tmp_path)
    for value in ("", "  ", None, 3, ["a b"]):
        problems = check(run, [entry(**{key: value})])
        assert messages(problems) == [recommend.TEXT_NEEDED], (key, value)
        assert problems[0].field == f"entries[0].{key}"


@pytest.mark.parametrize("key", ["why", "missing"])
def test_every_text_is_at_most_400_characters(tmp_path, key):
    run = recommend_run(tmp_path)
    assert check(run, [entry(**{key: "x" * 400})]) == []
    problems = check(run, [entry(**{key: "x" * 401})])
    assert messages(problems) == [recommend.TEXT_TOO_LONG] and problems[0].field == f"entries[0].{key}"


def test_a_question_part_over_400_characters_is_too_long(tmp_path):
    run = recommend_run(tmp_path)
    assert recommend.TEXT_TOO_LONG in messages(check(run, [entry(question_part="adding " * 60)]))


def test_the_note_is_none_or_filled_text_of_at_most_400_characters(tmp_path):
    run = recommend_run(tmp_path)
    assert check(run, [entry()], None) == []
    assert check(run, [entry()], "y" * 400) == []
    assert messages(check(run, [entry()], "y" * 401)) == [recommend.TEXT_TOO_LONG]
    for note in ("", " ", 3, ["a"]):
        problems = check(run, [entry()], note)
        assert messages(problems) == [recommend.TEXT_NEEDED] and problems[0].field == "note", note


def test_an_entry_has_exactly_its_keys(tmp_path):
    run = recommend_run(tmp_path)
    extra = check(run, [entry(rank=1)])
    assert messages(extra) == [recommend.ENTRY_PARTS] and extra[0].field == "entries[0]"
    short = entry()
    del short["missing"]
    assert messages(check(run, [short])) == [recommend.ENTRY_PARTS]
    for not_an_object in ("firm-boundaries", None, ["firm-boundaries"]):
        assert messages(check(run, [not_an_object])) == [recommend.ENTRY_PARTS]


def test_by_is_the_advisor(tmp_path):
    run = recommend_run(tmp_path)
    for by in ("lens-link-reader", "", "Lens-Advisor", None):
        with pytest.raises(ValueError) as refused:
            recommend.record_recommendation(run, LENSES, [entry()], None, by)
        assert str(refused.value) == recommend.NOT_THE_ADVISOR
    assert recommend.read_record(run) is None


def test_every_problem_is_named_at_once(tmp_path):
    run = recommend_run(tmp_path)
    problems = check(run, [entry(lens="no-such-lens", question_part="nothing like it", facts=["F3"], why="")])
    assert messages(problems) == [recommend.LENS_NOT_FOUND, recommend.PART_NOT_IN_QUESTION, recommend.TEXT_NEEDED,
                                  recommend.FACT_DOES_NOT_COUNT]


def test_the_check_never_raises_on_odd_input(tmp_path):
    run = recommend_run(tmp_path)
    for entries in (None, "x", 3, [{}], [{"lens": ["x"], "question_part": {}, "why": 1, "facts": [[]], "missing": 2}]):
        assert check(run, entries)


# --- the record -----------------------------------------------------------------------------------------------------

def test_a_refused_list_writes_nothing(tmp_path):
    run = recommend_run(tmp_path)
    before = sorted(path.name for path in run.iterdir())
    with pytest.raises(recommend.RecommendationRefused) as refused:
        recommend.record_recommendation(run, LENSES, [entry(facts=["F3"])], None, recommend.ADVISOR)
    assert str(refused.value) == recommend.REFUSED and isinstance(refused.value, ValueError)
    assert messages(refused.value.problems) == [recommend.FACT_DOES_NOT_COUNT]
    assert sorted(path.name for path in run.iterdir()) == before   # the lock file was there already, nothing else
    assert recommend.read_record(run) is None


def test_a_refused_list_keeps_the_record_that_was_there(tmp_path):
    run = recommend_run(tmp_path)
    recommend.record_recommendation(run, LENSES, [entry()], None, recommend.ADVISOR, now=NOW)
    first = (run / recommend.RECORD).read_bytes()
    with pytest.raises(recommend.RecommendationRefused):
        recommend.record_recommendation(run, LENSES, [entry(facts=["F3"])], None, recommend.ADVISOR)
    assert (run / recommend.RECORD).read_bytes() == first


def test_the_record_holds_what_the_program_writes(tmp_path, monkeypatch):
    run = recommend_run(tmp_path)
    monkeypatch.setattr(recommend, "MODELS_FILE", tmp_path / "no-settings.json")
    entries = [entry(), entry(lens="capacity-commitment", question_part="for whom", facts=[])]
    recommend.record_recommendation(run, LENSES, entries, "Two lenses fit.", recommend.ADVISOR, now=NOW)
    record = json.loads((run / recommend.RECORD).read_text(encoding="utf-8"))
    assert list(record) == ["by", "at", "question", "entries", "note", "facts_seen", "models_set_to", "link_checks"]
    assert record == {"by": "lens-advisor", "at": "2026-11-16T09:30:00Z", "question": QUESTION, "entries": entries,
                      "note": "Two lenses fit.", "facts_seen": {"F1": "confirmed", "F2": "confirmed"},
                      "models_set_to": {"lens-advisor": None, "lens-link-reader": None,
                                        "lens-link-reader-quick": None},
                      "link_checks": []}
    assert recommend.read_record(run) == record
    assert recommend.shape_problems(record) == []


def test_the_record_holds_the_facts_it_saw_with_their_statuses(tmp_path):
    run = recommend_run(tmp_path)
    fact = store.read_facts(run)["F2"]
    fact["status"], fact["status_reason"] = "uncertain", "single source that is not a primary source"
    store.write_fact(run, fact)   # as settle leaves a fact that only one source that is not primary names
    recommend.record_recommendation(run, LENSES, [entry(facts=[])], None, recommend.ADVISOR)
    assert recommend.read_record(run)["facts_seen"] == {"F1": "confirmed", "F2": "uncertain"}


def test_models_set_to_comes_from_the_settings_file(tmp_path, monkeypatch):
    run = recommend_run(tmp_path)
    settings = tmp_path / "models.json"
    settings.write_text(json.dumps({"lens-advisor": "claude-opus-5-5", "lens-link-reader": "claude-opus-5-5",
                                    "lens-link-reader-quick": "sonnet", "support-checker": "opus"}), encoding="utf-8")
    monkeypatch.setattr(recommend, "MODELS_FILE", settings)
    recommend.record_recommendation(run, LENSES, [entry()], None, recommend.ADVISOR)
    assert recommend.read_record(run)["models_set_to"] == {
        "lens-advisor": "claude-opus-5-5", "lens-link-reader": "claude-opus-5-5", "lens-link-reader-quick": "sonnet"}
    settings.write_text(json.dumps({"lens-advisor": "claude-opus-5-5", "lens-link-reader": 5}), encoding="utf-8")
    recommend.record_recommendation(run, LENSES, [entry()], None, recommend.ADVISOR)
    assert recommend.read_record(run)["models_set_to"] == {
        "lens-advisor": "claude-opus-5-5", "lens-link-reader": None, "lens-link-reader-quick": None}
    for damaged in ("{", "[1, 2]", ""):
        settings.write_text(damaged, encoding="utf-8")
        recommend.record_recommendation(run, LENSES, [entry()], None, recommend.ADVISOR)
        assert set(recommend.read_record(run)["models_set_to"].values()) == {None}, damaged


def test_the_settings_file_is_the_one_next_to_the_engine():
    assert recommend.MODELS_FILE == Path(recommend.__file__).resolve().parents[2] / "settings" / "models.json"


def test_recording_again_replaces_the_record_and_clears_link_checks(tmp_path):
    run = recommend_run(tmp_path)
    recommend.record_recommendation(run, LENSES, [entry()], None, recommend.ADVISOR, now=NOW)
    record = recommend.read_record(run)
    record["link_checks"] = [{"lens": "firm-boundaries", "fact": "F1", "by": "lens-link-reader", "verdict": "bears",
                              "note": "", "at": "2026-11-16T09:31:00Z"}]
    (run / recommend.RECORD).write_text(json.dumps(record), encoding="utf-8")   # as a reader's verdict would be kept
    recommend.record_recommendation(run, LENSES, [entry(lens="capacity-commitment", facts=["F2"])], None,
                                    recommend.ADVISOR)
    again = recommend.read_record(run)
    assert again["entries"][0]["lens"] == "capacity-commitment" and again["link_checks"] == []


def test_read_record_is_none_without_a_record_or_with_a_damaged_one(tmp_path):
    run = recommend_run(tmp_path)
    assert recommend.read_record(run) is None
    (run / recommend.RECORD).write_text("{", encoding="utf-8")
    assert recommend.read_record(run) is None
    (run / recommend.RECORD).write_text("[]", encoding="utf-8")
    assert recommend.read_record(run) is None


def test_recording_holds_the_run_lock(tmp_path, monkeypatch):
    run = recommend_run(tmp_path)
    monkeypatch.setattr(store, "LOCK_WAIT_SECONDS", 0.2)
    with store.locked(run, wait=None):
        with pytest.raises(store.RunBusy):
            recommend.record_recommendation(run, LENSES, [entry()], None, recommend.ADVISOR)
    assert recommend.read_record(run) is None


def test_recording_refuses_a_folder_that_is_not_a_run_and_makes_no_lock_there(tmp_path):
    folder = tmp_path / "plain"
    folder.mkdir()
    with pytest.raises(ValueError):
        recommend.record_recommendation(folder, LENSES, [entry()], None, recommend.ADVISOR)
    assert list(folder.iterdir()) == []


def test_two_runs_recording_at_once_do_not_corrupt_the_file(tmp_path):
    run = recommend_run(tmp_path)
    lists = [[entry(why=f"Reason {number} for the lens.")] for number in range(2)]
    failures, start = [], threading.Barrier(2)

    def record(entries):
        try:
            start.wait()
            for _ in range(10):
                recommend.record_recommendation(run, LENSES, entries, None, recommend.ADVISOR)
        except Exception as exc:   # noqa: BLE001 - any failure fails the test below
            failures.append(exc)

    threads = [threading.Thread(target=record, args=(entries,)) for entries in lists]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failures == []
    record = json.loads((run / recommend.RECORD).read_text(encoding="utf-8"))
    assert record["entries"] in lists and recommend.shape_problems(record) == []
    assert not [path for path in run.iterdir() if path.name.endswith(".tmp")]


# --- check-data and the gate -----------------------------------------------------------------------------------------

def _record(run) -> dict:
    recommend.record_recommendation(run, LENSES, [entry()], None, recommend.ADVISOR, now=NOW)
    return recommend.read_record(run)


def _write(run, record) -> None:
    (run / recommend.RECORD).write_text(json.dumps(record), encoding="utf-8")


def test_check_data_reports_a_damaged_record_and_ignores_a_missing_one(tmp_path):
    run = recommend_run(tmp_path)
    assert check_data(run) == []
    record = _record(run)
    assert check_data(run) == []
    (run / recommend.RECORD).write_text("{", encoding="utf-8")
    assert [(p.file, p.message) for p in check_data(run)] == [(recommend.RECORD, "not valid JSON")]
    record["entries"][0]["why"] = 5
    _write(run, record)
    assert [(p.file, p.field, p.message) for p in check_data(run)] == [
        (recommend.RECORD, "entries[0].why", recommend.SHAPE_FORM)]


def test_check_data_checks_the_shape_only(tmp_path):
    run = recommend_run(tmp_path)
    record = _record(run)
    record["entries"][0].update(lens="no-such-lens", question_part="not in the question at all", facts=["F3", "F9"])
    record["question"] = "Another question"
    record["facts_seen"] = {"F7": "confirmed"}
    _write(run, record)
    assert check_data(run, LENSES) == []


@pytest.mark.parametrize("change, field, message", [
    (lambda r: r.pop("note"), "note", "SHAPE_PARTS"),
    (lambda r: r.update(extra=1), "extra", "SHAPE_PARTS"),
    (lambda r: r.update(by=3), "by", "SHAPE_FORM"),
    (lambda r: r.update(at=None), "at", "SHAPE_FORM"),
    (lambda r: r.update(question=["q"]), "question", "SHAPE_FORM"),
    (lambda r: r.update(entries="x"), "entries", "SHAPE_FORM"),
    (lambda r: r["entries"].append("x"), "entries[1]", "SHAPE_FORM"),
    (lambda r: r["entries"][0].pop("why"), "entries[0]", "SHAPE_PARTS"),
    (lambda r: r["entries"][0].update(rank=1), "entries[0]", "SHAPE_PARTS"),
    (lambda r: r["entries"][0].update(lens=None), "entries[0].lens", "SHAPE_FORM"),
    (lambda r: r["entries"][0].update(facts="F1"), "entries[0].facts", "SHAPE_FORM"),
    (lambda r: r["entries"][0].update(facts=["F1", 2]), "entries[0].facts", "SHAPE_FORM"),
    (lambda r: r["entries"][0].update(missing=""), "entries[0].missing", "TEXT_NEEDED"),
    (lambda r: r["entries"][0].update(question_part="x" * 401), "entries[0].question_part", "TEXT_TOO_LONG"),
    (lambda r: r.update(note=""), "note", "TEXT_NEEDED"),
    (lambda r: r.update(note="n" * 401), "note", "TEXT_TOO_LONG"),
    (lambda r: r.update(facts_seen=["F1"]), "facts_seen", "SHAPE_FORM"),
    (lambda r: r.update(facts_seen={"F1": 1}), "facts_seen", "SHAPE_FORM"),
    (lambda r: r.update(models_set_to={"lens-advisor": None}), "models_set_to", "SHAPE_PARTS"),
    (lambda r: r["models_set_to"].update({"lens-advisor": 5}), "models_set_to", "SHAPE_FORM"),
    (lambda r: r.update(link_checks={}), "link_checks", "SHAPE_FORM"),
    (lambda r: r.update(link_checks=["x"]), "link_checks[0]", "SHAPE_FORM"),
    (lambda r: r.update(link_checks=[{"lens": "a"}]), "link_checks[0]", "SHAPE_PARTS"),
    (lambda r: r.update(link_checks=[{"lens": "a", "fact": "F1", "by": "lens-link-reader", "verdict": "bears", "note": 3,
                                      "at": "t"}]), "link_checks[0].note", "SHAPE_FORM"),
    (lambda r: r.update(link_checks=[{"lens": "a", "fact": "F1", "by": "lens-link-reader", "verdict": "doubt", "note": "n" * 2001,
                                      "at": "t"}]), "link_checks[0].note", "LINK_NOTE_TOO_LONG"),
])
def test_check_data_names_each_shape_problem(tmp_path, change, field, message):
    run = recommend_run(tmp_path)
    record = _record(run)
    change(record)
    _write(run, record)
    assert [(p.file, p.field, p.message) for p in check_data(run)] == [
        (recommend.RECORD, field, getattr(recommend, message))]


def test_well_formed_link_checks_and_a_note_with_no_lens_pass_the_shape_check(tmp_path):
    record = {"by": "lens-advisor", "at": "t", "question": "q", "entries": [], "note": "None fits.", "facts_seen": {},
              "models_set_to": {"lens-advisor": "x", "lens-link-reader": None, "lens-link-reader-quick": None},
              "link_checks": [{"lens": "a", "fact": "F1", "by": "lens-link-reader", "verdict": "bears", "note": "", "at": "t"}]}
    assert recommend.shape_problems(record) == []
    assert messages(recommend.shape_problems([])) == [recommend.SHAPE_FORM]
    # the program never writes an empty list with no note, so a saved one was changed, and check-data says so
    record["note"] = None
    assert [(p.field, p.message) for p in recommend.shape_problems(record)] == [("note", recommend.NOTE_NEEDED)]


def test_a_record_that_may_not_be_opened_is_named(tmp_path):
    from helpers import unreadable_file
    run = recommend_run(tmp_path)
    _record(run)
    with unreadable_file(run / recommend.RECORD):
        assert [(p.file, p.message) for p in check_data(run)] == [(recommend.RECORD, "may not be opened by this user")]


@pytest.mark.parametrize("damage", ["a wrong form", "not JSON", "a folder"])
def test_a_damaged_record_is_reported_by_check_data_and_never_blocks_the_gate_or_the_report(tmp_path, capsys,
                                                                                               damage):
    run = recommend_run(tmp_path)
    record = _record(run)
    if damage == "a wrong form":
        record["entries"][0]["why"] = 5
        _write(run, record)
        expected = [(recommend.RECORD, "entries[0].why", recommend.SHAPE_FORM)]
    elif damage == "not JSON":
        (run / recommend.RECORD).write_text("{", encoding="utf-8")
        expected = [(recommend.RECORD, None, "not valid JSON")]
    else:
        (run / recommend.RECORD).unlink()
        (run / recommend.RECORD).mkdir()
        expected = [(recommend.RECORD, None, "not valid JSON")]
    assert [(p.file, p.field, p.message) for p in check_data(run, LENSES)] == expected
    assert gate(run, LENSES) == []
    assert run_cli(capsys, "gate", "--run", run, "--lenses", LENSES)[0] == 0
    assert build_report(run, LENSES)
    code, out = run_cli(capsys, "check-data", "--run", run, "--lenses", LENSES)
    assert code == 1 and [p["file"] for p in out["problems"]] == [recommend.RECORD]


def test_the_gate_still_names_every_other_problem_beside_a_damaged_record(tmp_path):
    run = recommend_run(tmp_path)
    (run / recommend.RECORD).write_text("{", encoding="utf-8")
    store.write_analysis(run, minimal_analysis(["F3"], lens_id="firm-boundaries"))
    problems = gate(run, LENSES)
    assert problems and all(problem.file != recommend.RECORD for problem in problems)


def test_a_fact_withdrawn_after_the_record_does_not_block_the_gate(tmp_path):
    run = recommend_run(tmp_path)
    store.write_analysis(run, minimal_analysis(["F1"], lens_id="firm-boundaries"))
    assert gate(run, LENSES) == []
    recommend.record_recommendation(run, LENSES, [entry(facts=["F2"])], None, recommend.ADVISOR)
    verify.withdraw_fact(run, "F2", "A duplicate of F1.")
    verify.settle(run)
    assert store.read_facts(run)["F2"]["status"] == "rejected"
    assert gate(run, LENSES) == []


def test_a_run_with_no_recommendation_passes_the_gate(tmp_path):
    assert gate(recommend_run(tmp_path), LENSES) == []


# --- the advisor's input ---------------------------------------------------------------------------------------------

def test_advisor_input_holds_no_quote_and_only_facts_that_count(tmp_path):
    run = recommend_run(tmp_path)
    add_source(run, "A planning office received an application for a new filling hall at Plant West in 2027.",
               type="permit", publisher="Planning Office")
    add_fact(run, kind="general", fields=None, source_id="S2", primary_source=True, certainty="tentative",
             tentative_reason="an application, not an announcement",
             statement="An application names a new filling hall at Plant West.",
             quote="received an application for a new filling hall at Plant West")
    verify.check_quotes(run)
    verify.record_support(run, "F4", True, "support-checker", "")
    verify.settle(run)
    verify.withdraw_fact(run, "F2", "A duplicate of F1.")   # not settled: still confirmed, but it never counts
    given = recommend.advisor_input(run, LENSES)
    assert list(given) == ["question", "frame", "lenses", "facts"]
    assert given["question"] == QUESTION and given["frame"] is None
    assert given["facts"] == [
        {"id": "F1", "statement": "Competitor A will add a second filling line at Plant North.",
         "status": "confirmed", "publisher": "Competitor A", "early_signal": False},
        {"id": "F4", "statement": "An application names a new filling hall at Plant West.",
         "status": "uncertain", "publisher": "Planning Office", "early_signal": True}]
    text = json.dumps(given)
    for fact in store.read_facts(run).values():
        assert fact["quote"] not in text
    for copy in (run / "copies").iterdir():
        assert copy.read_text(encoding="utf-8") not in text


def test_advisor_input_shows_each_lens_without_its_limits_competing_idea_or_originals(tmp_path):
    run = recommend_run(tmp_path)
    given = recommend.advisor_input(run, LENSES)
    assert [lens["id"] for lens in given["lenses"]] == ["capacity-commitment", "firm-boundaries"]
    lens = given["lenses"][1]
    source = json.loads((LENSES / "firm-boundaries.json").read_text(encoding="utf-8"))
    assert lens == {"id": "firm-boundaries", "name": source["name"], "idea": source["idea"],
                    "suggests": source["suggests"], "questions": source["questions"],
                    "level": "Invented for practice", "theme": None}
    text = json.dumps(given)
    for part in ("limits", "competing_idea"):
        assert source[part] not in text
    assert source["originals"][0]["reference"] not in text


def test_advisor_input_gives_the_theme_and_level_and_leaves_out_a_lens_that_fails(tmp_path):
    run = recommend_run(tmp_path)
    folder = tmp_path / "lenses"
    shutil.copytree(Path(__file__).parent.parent / "lenses", folder)
    lens = json.loads((folder / "absorbing-growth.json").read_text(encoding="utf-8"))
    del lens["limits"]
    (folder / "absorbing-growth.json").write_text(json.dumps(lens), encoding="utf-8")
    given = recommend.advisor_input(run, folder)
    ids = [lens["id"] for lens in given["lenses"]]
    assert "absorbing-growth" not in ids and len(ids) == 82
    first = given["lenses"][0]
    assert first["id"] == "asset-specificity" and first["theme"] == "Where the firm's boundary lies"
    assert first["level"] in ("Original read", "Secondary source read", "Course slides", "Reference confirmed")


def test_advisor_input_holds_the_frame_when_there_is_one(tmp_path):
    run = recommend_run(tmp_path)
    (run / "notes").mkdir()
    (run / "notes" / "frame.md").write_text("The question leaves out price.\n", encoding="utf-8")
    assert recommend.advisor_input(run, LENSES)["frame"] == "The question leaves out price.\n"


# --- the commands ----------------------------------------------------------------------------------------------------

def run_cli(capsys, *argv):
    code = cli.main([str(part) for part in argv])
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    return code, json.loads(out)


def _file(tmp_path, data, name="recommendation.json") -> Path:
    path = tmp_path / name
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


def _record_command(run, path, by=recommend.ADVISOR):
    return ("record-lens-recommendation", "--run", run, "--lenses", LENSES, "--by", by, "--file", path)


def test_the_command_records_a_good_list(tmp_path, capsys):
    run = recommend_run(tmp_path)
    path = _file(tmp_path, {"entries": [entry()], "note": None})
    assert run_cli(capsys, *_record_command(run, path)) == (0, {"recorded": True, "problems": [], "explained": []})
    assert recommend.read_record(run)["entries"] == [entry()]


def test_the_command_names_each_problem_with_its_explanation(tmp_path, capsys):
    run = recommend_run(tmp_path)
    path = _file(tmp_path, {"entries": [entry(facts=["F3"])], "note": None})
    code, out = run_cli(capsys, *_record_command(run, path))
    assert code == 1 and out["recorded"] is False
    assert out["problems"] == [{"file": recommend.RECORD, "field": "entries[0].facts[0]",
                                "message": recommend.FACT_DOES_NOT_COUNT}]
    assert out["explained"][0]["known"] is True
    assert recommend.read_record(run) is None


def test_the_command_refuses_another_helper(tmp_path, capsys):
    run = recommend_run(tmp_path)
    path = _file(tmp_path, {"entries": [entry()], "note": None})
    assert run_cli(capsys, *_record_command(run, path, by="support-checker")) == (
        2, {"error": recommend.NOT_THE_ADVISOR})
    assert recommend.read_record(run) is None


@pytest.mark.parametrize("data", ["{", "[]", '"x"', json.dumps({"entries": []}) + "x",
                                  '{"entries": [], "entries": [], "note": "n"}',
                                  '{"entries": [{"lens": "a", "lens": "b"}], "note": "n"}',
                                  json.dumps({"entries": [], "note": "n", "rank": 1}),
                                  json.dumps({"note": "n"})])
def test_the_command_refuses_a_file_it_cannot_read_as_a_list(tmp_path, capsys, data):
    run = recommend_run(tmp_path)
    code, out = run_cli(capsys, *_record_command(run, _file(tmp_path, data)))
    assert code == 2 and list(out) == ["error"]
    assert recommend.read_record(run) is None


def test_a_note_may_be_left_out_of_the_file(tmp_path, capsys):
    run = recommend_run(tmp_path)
    assert run_cli(capsys, *_record_command(run, _file(tmp_path, {"entries": [entry()]})))[0] == 0
    assert recommend.read_record(run)["note"] is None


def test_the_heredoc_form_records_through_main(tmp_path, capsys, monkeypatch):
    run = recommend_run(tmp_path)
    sent = json.dumps({"entries": [entry(why="Two facts describe plant built for one customer \u2013 Plant South.")],
                       "note": None}, ensure_ascii=False) + "\n"
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(sent.encode("utf-8")), encoding="utf-8"))
    assert run_cli(capsys, *_record_command(run, "-"))[0] == 0
    assert recommend.read_record(run)["entries"][0]["why"].endswith("\u2013 Plant South.")


def test_standard_input_that_is_not_utf8_is_refused(tmp_path, capsys, monkeypatch):
    run = recommend_run(tmp_path)
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b'{"entries": [], "note": "\xff"}'),
                                                      encoding="utf-8"))
    code, out = run_cli(capsys, *_record_command(run, "-"))
    assert code == 2 and list(out) == ["error"]


# --- the plain line form: the list on standard input with no curly brackets, as the lens advisor sends it --------------

TWO_ENTRIES = """lens: firm-boundaries
part: adding filling capacity
why: Two facts describe plant built for a single customer: Plant South.
facts: F1, F2
missing: Nothing found on what protects that plant.

missing: A source on what the customers committed to.
facts: none
why: The lens asks how costly the expansion would be to reverse.
part: for whom
lens: capacity-commitment
"""


def _list_command(run, by=recommend.ADVISOR):
    return ("record-lens-recommendation", "--run", run, "--lenses", LENSES, "--by", by, "--list-stdin")


def _send(monkeypatch, text):
    data = text if isinstance(text, bytes) else text.encode("utf-8")
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(data), encoding="utf-8"))


def test_the_plain_line_form_reads_two_entries_in_any_order_of_keys():
    entries, note = recommend.parse_list_lines(TWO_ENTRIES)
    assert note is None
    assert entries == [
        {"lens": "firm-boundaries", "question_part": "adding filling capacity",
         "why": "Two facts describe plant built for a single customer: Plant South.", "facts": ["F1", "F2"],
         "missing": "Nothing found on what protects that plant."},
        {"lens": "capacity-commitment", "question_part": "for whom",
         "why": "The lens asks how costly the expansion would be to reverse.", "facts": [],
         "missing": "A source on what the customers committed to."}]
    assert all(list(entry) == list(recommend.ENTRY_KEYS) for entry in entries)


def test_the_plain_line_form_takes_a_note_on_a_line_of_its_own_anywhere_outside_an_entry():
    assert recommend.parse_list_lines("note: No lens fits a question about prices.\n") == (
        [], "No lens fits a question about prices.")
    assert recommend.parse_list_lines("\n\nnote: none fits\n\n") == ([], "none fits")
    entries, note = recommend.parse_list_lines(TWO_ENTRIES + "\nnote: A last word.\n")
    assert len(entries) == 2 and note == "A last word."
    entries, note = recommend.parse_list_lines("note: First.\n\n" + TWO_ENTRIES)
    assert len(entries) == 2 and note == "First."
    assert recommend.parse_list_lines("") == ([], None)
    assert recommend.parse_list_lines(TWO_ENTRIES.replace("\n", "\r\n"))[0] == recommend.parse_list_lines(TWO_ENTRIES)[0]


@pytest.mark.parametrize("text, words", [
    ("lens firm-boundaries\n", "no ': '"),
    ("lens:firm-boundaries\n", "no ': '"),
    ("rank: 1\n", "not known"),
    ("question_part: adding filling capacity\n", "not known"),
    ("Lens: firm-boundaries\n", "not known"),
    (TWO_ENTRIES.replace("facts: none", "facts: none\nfacts: F1"), "a second time"),
    (TWO_ENTRIES.replace("missing: Nothing found on what protects that plant.\n", ""), "has no missing"),
    ("lens: firm-boundaries\n", "has no part"),
    (TWO_ENTRIES.replace("facts: F1, F2", "facts: "), "no facts"),
    ("note: one\n\nnote: two\n", "note is given twice"),
    (TWO_ENTRIES.replace("facts: none", "facts: none\nnote: inside"), "line of its own"),
    ("note: one\nnote: two\n", "line of its own"),
])
def test_a_malformed_plain_list_is_refused_with_a_plain_sentence(text, words):
    with pytest.raises(ValueError) as refused:
        recommend.parse_list_lines(text)
    assert words in str(refused.value) and str(refused.value).isascii()


def test_the_plain_line_form_records_through_main_from_a_heredoc(tmp_path, capsys, monkeypatch):
    run = recommend_run(tmp_path)
    _send(monkeypatch, TWO_ENTRIES)
    assert run_cli(capsys, *_list_command(run)) == (0, {"recorded": True, "problems": [], "explained": []})
    assert recommend.read_record(run)["entries"] == recommend.parse_list_lines(TWO_ENTRIES)[0]


def test_an_empty_plain_list_with_a_note_is_recorded(tmp_path, capsys, monkeypatch):
    run = recommend_run(tmp_path)
    _send(monkeypatch, "note: No lens fits a question about prices.\n")
    assert run_cli(capsys, *_list_command(run))[0] == 0
    record = recommend.read_record(run)
    assert record["entries"] == [] and record["note"] == "No lens fits a question about prices."


def test_a_plain_list_goes_through_the_same_form_check(tmp_path, capsys, monkeypatch):
    run = recommend_run(tmp_path)
    _send(monkeypatch, "")                                        # no entries and no note
    code, out = run_cli(capsys, *_list_command(run))
    assert code == 1 and out["problems"][0]["message"] == recommend.NOTE_NEEDED
    _send(monkeypatch, TWO_ENTRIES.replace("F1, F2", "F3"))       # a rejected fact
    code, out = run_cli(capsys, *_list_command(run))
    assert code == 1 and out["problems"][0]["message"] == recommend.FACT_DOES_NOT_COUNT
    _send(monkeypatch, TWO_ENTRIES)
    assert run_cli(capsys, *_list_command(run, by="support-checker")) == (2, {"error": recommend.NOT_THE_ADVISOR})
    assert recommend.read_record(run) is None


@pytest.mark.parametrize("text", [TWO_ENTRIES.replace("facts: none", "facts: none\nrank: 2"), "lens\n",
                                  b"note: \xff\n"])
def test_a_malformed_plain_list_is_a_usage_error_and_writes_nothing(tmp_path, capsys, monkeypatch, text):
    run = recommend_run(tmp_path)
    _send(monkeypatch, text)
    code, out = run_cli(capsys, *_list_command(run))
    assert code == 2 and list(out) == ["error"]
    assert recommend.read_record(run) is None


def test_the_list_comes_either_from_a_file_or_as_plain_lines_never_both(tmp_path, capsys, monkeypatch):
    run = recommend_run(tmp_path)
    path = _file(tmp_path, {"entries": [entry()], "note": None})
    code, out = run_cli(capsys, *_record_command(run, path), "--list-stdin")
    assert code == 2 and list(out) == ["error"]
    code, out = run_cli(capsys, *_record_command(run, path)[:-2])
    assert code == 2 and list(out) == ["error"]


def test_the_command_reports_a_busy_run(tmp_path, capsys, monkeypatch):
    run = recommend_run(tmp_path)
    path = _file(tmp_path, {"entries": [entry()], "note": None})
    monkeypatch.setattr(store, "LOCK_WAIT_SECONDS", 0.2)
    with store.locked(run, wait=None):
        code, out = run_cli(capsys, *_record_command(run, path))
    assert code == 2 and out["busy"] is True


def test_the_advisor_input_command_prints_it_and_changes_nothing(tmp_path, capsys):
    run = recommend_run(tmp_path)
    before = sorted((str(path), path.stat().st_mtime_ns) for path in run.rglob("*"))
    code, out = run_cli(capsys, "lens-advisor-input", "--run", run, "--lenses", LENSES)
    whole = recommend.advisor_input(run, LENSES)
    assert code == 0 and out == json.loads(json.dumps({"question": whole["question"], "frame": whole["frame"],
                                                       "part": 1, "parts": 1, "lenses": whole["lenses"],
                                                       "facts": whole["facts"]}))
    assert sorted((str(path), path.stat().st_mtime_ns) for path in run.rglob("*")) == before


def many_moves_run(tmp_path, count=120) -> Path:
    """A run with `count` confirmed moves F1, F2, ..., each with a quote of its own."""
    quotes = [f"Move number {number} adds a filling line." for number in range(1, count + 1)]
    run = make_run(tmp_path, question=QUESTION)
    add_source(run, " ".join(quotes), publisher="Competitor A")
    for quote in quotes:
        add_fact(run, source_id="S1", primary_source=True, quote=quote,
                 statement=f"Competitor A adds a filling line ({quote[:15].strip()}).")
    finish_run(run, ["F1"], lens_id="firm-boundaries")
    return run


def test_the_advisor_input_takes_part(tmp_path, capsys):
    run = many_moves_run(tmp_path)
    whole = recommend.advisor_input(run, LENSES)
    code, first = run_cli(capsys, "lens-advisor-input", "--run", run, "--lenses", LENSES)
    assert code == 0 and first == run_cli(capsys, "lens-advisor-input", "--run", run, "--lenses", LENSES,
                                          "--part", 1)[1]
    assert first["parts"] >= 2 and first["question"] == QUESTION and "frame" in first
    printed = [first] + [run_cli(capsys, "lens-advisor-input", "--run", run, "--lenses", LENSES, "--part", number)[1]
                         for number in range(2, first["parts"] + 1)]
    assert all("question" not in given and "frame" not in given for given in printed[1:])
    assert [fact["id"] for given in printed for fact in given.get("facts", [])] == [f"F{n}" for n in range(1, 121)]
    assert [lens["id"] for given in printed for lens in given.get("lenses", [])] == [
        lens["id"] for lens in whole["lenses"]]
    code, out = run_cli(capsys, "lens-advisor-input", "--run", run, "--lenses", LENSES, "--part", 99)
    assert code == 1 and list(out) == ["problems", "explained"]
    assert f"{first['parts']} parts" in out["problems"][0]["message"] and out["explained"][0]["known"] is True
    assert run_cli(capsys, "lens-advisor-input", "--run", run, "--lenses", LENSES, "--part", "x")[0] == 2


def test_the_advisor_input_command_refuses_a_missing_lens_folder(tmp_path, capsys):
    run = recommend_run(tmp_path)
    code, out = run_cli(capsys, "lens-advisor-input", "--run", run, "--lenses", tmp_path / "nothing")
    assert code == 2 and list(out) == ["error"]


# --- the blind readers: packets, verdicts and marks ---------------------------------------------------------------------

READER, QUICK = recommend.READERS


def recorded_run(tmp_path, entries=None):
    """A run with a recorded recommendation: firm-boundaries with F1 and F2, capacity-commitment with no fact."""
    run = recommend_run(tmp_path)
    if entries is None:
        entries = [entry(), entry(lens="capacity-commitment", question_part="filling capacity", facts=[])]
    recommend.record_recommendation(run, LENSES, entries, None, recommend.ADVISOR, now=NOW)
    return run


def link(run, fact="F1", lens="firm-boundaries", verdict="bears", by=READER, note=""):
    recommend.record_link_check(run, lens, fact, verdict, by, note, now=NOW)


def test_the_readers():
    assert recommend.READERS == ("lens-link-reader", "lens-link-reader-quick")
    assert recommend.MAX_LINK_NOTE == 2000


def test_packets_hold_the_lens_and_the_fact_and_never_the_reason(tmp_path):
    run = recorded_run(tmp_path)
    packets = recommend.link_packets(run, LENSES)
    source = json.loads((LENSES / "firm-boundaries.json").read_text(encoding="utf-8"))
    assert packets == [
        {"lens": "firm-boundaries", "lens_name": source["name"], "idea": source["idea"],
         "suggests": source["suggests"], "questions": source["questions"], "fact": fact_id,
         "statement": store.read_facts(run)[fact_id]["statement"], "status": "confirmed"}
        for fact_id in ("F1", "F2")]
    assert all(list(packet) == ["lens", "lens_name", "idea", "suggests", "questions", "fact", "statement", "status"]
               for packet in packets) and all(len(packet["questions"]) == 3 for packet in packets)
    text = json.dumps(packets)
    record = recommend.read_record(run)["entries"][0]
    for part in ("why", "question_part", "missing"):
        assert record[part] not in text
    for part in ("limits", "competing_idea"):
        assert source[part] not in text
    for fact in store.read_facts(run).values():
        assert fact["quote"] not in text


def test_an_entry_with_no_facts_has_no_packet(tmp_path):
    run = recorded_run(tmp_path)
    assert {packet["lens"] for packet in recommend.link_packets(run, LENSES)} == {"firm-boundaries"}
    run = recorded_run(tmp_path / "again", [entry(facts=[])])
    assert recommend.link_packets(run, LENSES) == []


def test_there_are_no_packets_without_a_recommendation_or_with_a_damaged_one(tmp_path):
    run = recommend_run(tmp_path)
    assert recommend.link_packets(run, LENSES) == []
    (run / recommend.RECORD).write_text("{", encoding="utf-8")
    assert recommend.link_packets(run, LENSES) == []
    (run / recommend.RECORD).write_text(json.dumps({"entries": [7, {"lens": 3, "facts": "F1"}]}), encoding="utf-8")
    assert recommend.link_packets(run, LENSES) == []


def test_packets_of_a_folder_that_cannot_be_listed_are_refused_also_without_a_recommendation(tmp_path, monkeypatch):
    from radar import lens_view, lenses
    run = recommend_run(tmp_path)
    monkeypatch.setattr(lenses, "lens_files", lambda folder: None)
    with pytest.raises(lens_view.LensFolderUnreadable):
        recommend.link_packets(run, LENSES)


def test_a_lens_that_fails_its_check_or_a_fact_that_is_gone_has_no_packet(tmp_path):
    run = recorded_run(tmp_path)
    record = recommend.read_record(run)
    record["entries"][0]["facts"] = ["F1", "F9"]
    _write(run, record)
    assert [packet["fact"] for packet in recommend.link_packets(run, LENSES)] == ["F1"]
    folder = tmp_path / "lenses"
    shutil.copytree(LENSES, folder)
    (folder / "firm-boundaries.json").write_text("{}", encoding="utf-8")
    assert recommend.link_packets(run, folder) == []


def test_a_good_verdict_is_recorded_with_its_parts(tmp_path):
    run = recorded_run(tmp_path)
    link(run, "F1", verdict="doubt", note="The fact is about plant, not about who it is built for.")
    link(run, "F2", by=QUICK)
    assert recommend.read_record(run)["link_checks"] == [
        {"lens": "firm-boundaries", "fact": "F1", "by": READER, "verdict": "doubt",
         "note": "The fact is about plant, not about who it is built for.", "at": "2026-11-16T09:30:00Z"},
        {"lens": "firm-boundaries", "fact": "F2", "by": QUICK, "verdict": "bears", "note": "",
         "at": "2026-11-16T09:30:00Z"}]
    assert recommend.shape_problems(recommend.read_record(run)) == []
    assert check_data(run) == []


def test_recording_a_verdict_keeps_every_other_part_of_the_record(tmp_path):
    run = recorded_run(tmp_path)
    before = recommend.read_record(run)
    link(run)
    after = recommend.read_record(run)
    del after["link_checks"], before["link_checks"]
    assert after == before


@pytest.mark.parametrize("lens, fact", [
    ("firm-boundaries", "F3"),            # a fact the entry does not name
    ("firm-boundaries", "F9"),            # a fact the run does not hold
    ("capacity-commitment", "F1"),        # a lens that names no facts
    ("no-such-lens", "F1"), ("", ""), (None, "F1"), ("firm-boundaries", None)])
def test_a_link_not_in_the_recommendation_is_refused(tmp_path, lens, fact):
    run = recorded_run(tmp_path)
    with pytest.raises(ValueError) as refused:
        recommend.record_link_check(run, lens, fact, "bears", READER, "")
    assert str(refused.value) == recommend.NOT_A_LINK
    assert recommend.read_record(run)["link_checks"] == []


def test_a_verdict_with_no_recommendation_or_a_damaged_one_is_refused(tmp_path):
    run = recommend_run(tmp_path)
    with pytest.raises(ValueError) as refused:
        link(run)
    assert str(refused.value) == recommend.NO_RECOMMENDATION
    for text in ("{", "[]", json.dumps({"entries": "x"})):
        (run / recommend.RECORD).write_text(text, encoding="utf-8")
        with pytest.raises(ValueError) as refused:
            link(run)
        assert str(refused.value) == recommend.NO_RECOMMENDATION
        assert (run / recommend.RECORD).read_text(encoding="utf-8") == text


def test_a_doubt_needs_a_note(tmp_path):
    run = recorded_run(tmp_path)
    for note in ("", "   ", "\n", None, 5):
        with pytest.raises(ValueError) as refused:
            link(run, verdict="doubt", note=note)
        assert str(refused.value) == recommend.DOUBT_NEEDS_NOTE
    assert recommend.read_record(run)["link_checks"] == []


def test_a_note_that_agrees_may_be_empty(tmp_path):
    run = recorded_run(tmp_path)
    link(run, note="")
    link(run, "F2", note="It names the customer.")
    assert [check["note"] for check in recommend.read_record(run)["link_checks"]] == ["", "It names the customer."]


def test_a_note_may_be_2000_characters_and_not_more(tmp_path):
    run = recorded_run(tmp_path)
    link(run, verdict="doubt", note="a" * 2000)
    with pytest.raises(ValueError) as refused:
        link(run, "F2", verdict="doubt", note="a" * 2001)
    assert str(refused.value) == recommend.READER_NOTE_TOO_LONG
    assert [check["fact"] for check in recommend.read_record(run)["link_checks"]] == ["F1"]


@pytest.mark.parametrize("verdict", ["", "maybe", "Bears", "doubts", None, True])
def test_a_verdict_is_bears_or_doubt(tmp_path, verdict):
    run = recorded_run(tmp_path)
    with pytest.raises(ValueError) as refused:
        link(run, verdict=verdict, note="x")
    assert str(refused.value) == recommend.VERDICT_UNKNOWN
    assert recommend.read_record(run)["link_checks"] == []


@pytest.mark.parametrize("by", ["lens-advisor", "support-checker", "", "Lens-Link-Reader", None, "lens-link-reader "])
def test_only_the_two_readers_may_record(tmp_path, by):
    run = recorded_run(tmp_path)
    with pytest.raises(ValueError) as refused:
        link(run, by=by)
    assert str(refused.value) == recommend.NOT_A_READER
    assert recommend.read_record(run)["link_checks"] == []


def test_a_reader_recording_again_replaces_its_verdict(tmp_path):
    run = recorded_run(tmp_path)
    link(run, verdict="doubt", note="First thought.")
    link(run, by=QUICK, verdict="doubt", note="The quick reader's doubt.")
    recommend.record_link_check(run, "firm-boundaries", "F1", "bears", READER, "", now=datetime(2026, 11, 17, tzinfo=timezone.utc))
    checks = recommend.read_record(run)["link_checks"]
    assert [(check["by"], check["verdict"]) for check in checks if check["fact"] == "F1"] == [
        (QUICK, "doubt"), (READER, "bears")]
    assert len(checks) == 2 and [check["at"] for check in checks if check["by"] == READER] == ["2026-11-17T00:00:00Z"]


def test_recording_the_recommendation_again_clears_the_readers_verdicts(tmp_path):
    run = recorded_run(tmp_path)
    link(run)
    recommend.record_recommendation(run, LENSES, [entry()], None, recommend.ADVISOR)
    assert recommend.read_record(run)["link_checks"] == [] and recommend.marks(run)["firm-boundaries/F1"]["unread_by"] == list(recommend.READERS)


def test_recording_a_verdict_holds_the_run_lock(tmp_path, monkeypatch):
    run = recorded_run(tmp_path)
    monkeypatch.setattr(store, "LOCK_WAIT_SECONDS", 0.2)
    with store.locked(run, wait=None):
        with pytest.raises(store.RunBusy):
            link(run)
    assert recommend.read_record(run)["link_checks"] == []


def test_a_verdict_refuses_a_folder_that_is_not_a_run_and_makes_no_lock_there(tmp_path):
    folder = tmp_path / "plain"
    folder.mkdir()
    with pytest.raises(ValueError):
        link(folder)
    assert list(folder.iterdir()) == []


def test_link_checks_survive_two_readers_recording_at_once(tmp_path):
    run = recorded_run(tmp_path)
    failures, start = [], threading.Barrier(2)

    def record(reader):
        try:
            start.wait()
            for _ in range(10):
                for fact in ("F1", "F2"):
                    link(run, fact, by=reader, verdict="doubt", note=f"{reader} on {fact}")
        except Exception as exc:   # noqa: BLE001 - any failure fails the test below
            failures.append(exc)

    threads = [threading.Thread(target=record, args=(reader,)) for reader in recommend.READERS]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failures == []
    record = recommend.read_record(run)
    assert sorted((check["fact"], check["by"]) for check in record["link_checks"]) == sorted(
        (fact, reader) for fact in ("F1", "F2") for reader in recommend.READERS)
    assert recommend.shape_problems(record) == []
    assert not [path for path in run.iterdir() if path.name.endswith(".tmp")]


def test_link_checks_survive_two_reader_processes_recording_at_once(tmp_path):
    import os
    import subprocess
    import sys
    run = recorded_run(tmp_path)
    code = ("import sys\nfrom radar.cli import main\n"
            "for fact in ('F1', 'F2') * 3:\n"
            "    assert main(['record-link-check', '--run', sys.argv[1], '--lens', 'firm-boundaries', '--fact', fact,"
            " '--verdict', 'doubt', '--by', sys.argv[2], '--note', 'a note']) == 0\n")
    env = {**os.environ, "PYTHONPATH": str(Path(recommend.__file__).resolve().parents[1])}
    processes = [subprocess.Popen([sys.executable, "-c", code, str(run), reader], env=env, stdout=subprocess.DEVNULL)
                 for reader in recommend.READERS]
    assert [process.wait(timeout=60) for process in processes] == [0, 0]
    record = recommend.read_record(run)
    assert sorted((check["fact"], check["by"]) for check in record["link_checks"]) == sorted(
        (fact, reader) for fact in ("F1", "F2") for reader in recommend.READERS)
    assert recommend.shape_problems(record) == []
    assert not [path for path in run.iterdir() if path.name.endswith(".tmp")]


@pytest.mark.parametrize("lens, fact", [(["firm-boundaries"], "F1"), ("firm-boundaries", {"id": "F1"}),
                                        ({"a": 1}, ["F1"]), (None, None), (3, 4)])
def test_a_link_check_with_a_list_or_a_dict_for_its_lens_or_fact_never_raises(tmp_path, lens, fact):
    run = recorded_run(tmp_path)
    record = recommend.read_record(run)
    record["link_checks"] = [{"lens": lens, "fact": fact, "by": READER, "verdict": "doubt", "note": "x", "at": "t"}]
    _write(run, record)
    assert recommend.marks(run)["firm-boundaries/F1"]["doubts"] == 0
    assert [packet["fact"] for packet in recommend.link_packets(run, LENSES)] == ["F1", "F2"]
    link(run, "F1", by=QUICK)   # a reader may still record; the stray entry is kept as it was
    assert len(recommend.read_record(run)["link_checks"]) == 2
    assert recommend.marks(run)["firm-boundaries/F1"]["read_by"] == [QUICK]


@pytest.mark.parametrize("entries", [[{"lens": ["firm-boundaries"], "facts": ["F1"]}, {"lens": {}, "facts": [["F1"]]}],
                                     [{"lens": "firm-boundaries", "facts": [["F1"], {"id": "F2"}]}]])
def test_an_entry_with_a_list_or_a_dict_for_a_lens_or_fact_never_raises(tmp_path, entries):
    run = recorded_run(tmp_path)
    record = recommend.read_record(run)
    record["entries"] = entries
    _write(run, record)
    assert recommend.marks(run) == {} and recommend.link_packets(run, LENSES) == []
    for lens, fact in (("firm-boundaries", "F1"), (["firm-boundaries"], {"id": "F1"})):
        with pytest.raises(ValueError) as refused:
            recommend.record_link_check(run, lens, fact, "bears", READER, "")
        assert str(refused.value) == recommend.NOT_A_LINK


def test_check_data_accepts_well_formed_link_checks(tmp_path):
    run = recorded_run(tmp_path)
    link(run, verdict="doubt", note="x")
    link(run, "F2", by=QUICK)
    assert check_data(run) == []
    record = recommend.read_record(run)
    record["link_checks"][0]["verdict"] = 3
    _write(run, record)
    assert [(p.file, p.field) for p in check_data(run)] == [(recommend.RECORD, "link_checks[0].verdict")]


@pytest.mark.parametrize("key, value", [("verdict", "perhaps"), ("by", "lens-advisor"), ("by", "")])
def test_check_data_names_a_verdict_or_a_reader_no_command_writes(tmp_path, key, value):
    run = recorded_run(tmp_path)
    link(run, verdict="doubt", note="x")
    record = recommend.read_record(run)
    record["link_checks"][0][key] = value
    _write(run, record)
    assert [(p.field, p.message) for p in check_data(run)] == [(f"link_checks[0].{key}", recommend.SHAPE_FORM)]


def test_marks_have_one_shape_and_name_the_reader_of_each_note(tmp_path):
    run = recorded_run(tmp_path)
    link(run, "F1", by=READER, verdict="doubt", note="Not about capacity.")
    link(run, "F1", by=QUICK, verdict="doubt", note="Unclear.")
    link(run, "F2", by=READER)
    assert recommend.marks(run) == {
        "firm-boundaries/F1": {"doubts": 2, "read_by": [READER, QUICK], "unread_by": [], "verdicts": [
            {"reader": READER, "verdict": "doubt", "note": "Not about capacity."},
            {"reader": QUICK, "verdict": "doubt", "note": "Unclear."}], "unreadable": 0},
        "firm-boundaries/F2": {"doubts": 0, "read_by": [READER], "unread_by": [QUICK], "verdicts": [
            {"reader": READER, "verdict": "bears", "note": ""}], "unreadable": 0}}
    assert json.loads(json.dumps(recommend.marks(run))) == recommend.marks(run)


def test_one_doubt_is_a_mark_and_every_link_of_the_record_has_a_key(tmp_path):
    run = recorded_run(tmp_path)
    link(run, "F1", by=QUICK, verdict="doubt", note="Unclear.")
    marks = recommend.marks(run)
    assert list(marks) == ["firm-boundaries/F1", "firm-boundaries/F2"]   # the entry with no facts has no link
    assert marks["firm-boundaries/F1"]["doubts"] == 1 and marks["firm-boundaries/F2"]["doubts"] == 0
    assert all(list(mark) == ["doubts", "read_by", "unread_by", "verdicts", "unreadable"] for mark in marks.values())


def test_a_missing_reader_is_not_agreement(tmp_path):
    run = recorded_run(tmp_path)
    link(run, "F1", by=READER)   # the other reader recorded nothing
    mark = recommend.marks(run)["firm-boundaries/F1"]
    assert mark["unread_by"] == [QUICK] and mark["read_by"] == [READER] and mark["doubts"] == 0
    nothing = recommend.marks(run)["firm-boundaries/F2"]
    assert nothing == {"doubts": 0, "read_by": [], "unread_by": list(recommend.READERS), "verdicts": [],
                       "unreadable": 0}


def test_marks_are_empty_without_a_readable_record_and_count_strays_where_they_stand(tmp_path):
    """Paul's decision 18: a verdict in a form the readers do not write (a stranger's, too) is not thrown out
    silently: it is counted as a verdict that cannot be read, next to its link."""
    run = recommend_run(tmp_path)
    assert recommend.marks(run) == {}
    (run / recommend.RECORD).write_text("{", encoding="utf-8")
    assert recommend.marks(run) == {}
    run = recorded_run(tmp_path / "other")
    record = recommend.read_record(run)
    record["link_checks"] = [
        {"lens": "firm-boundaries", "fact": "F9", "by": READER, "verdict": "doubt", "note": "x", "at": "t"},   # no link
        {"lens": "firm-boundaries", "fact": "F1", "by": "someone", "verdict": "doubt", "note": "x", "at": "t"},
        {"lens": "firm-boundaries", "fact": "F1", "by": READER, "verdict": "perhaps", "note": "x", "at": "t"},
        "damaged", 7]
    _write(run, record)
    # the first reader recorded something on F1 that cannot be read: it is not said to have recorded nothing
    assert recommend.marks(run)["firm-boundaries/F1"] == {"doubts": 0, "read_by": [], "unread_by": [QUICK],
                                                          "verdicts": [], "unreadable": 2}
    _, damage, damaged = recommend.readable_record(run)
    assert damaged and damage == [{"verdict": "firm-boundaries/F1"}, {"verdict": "firm-boundaries/F1", "by": READER},
                                  {"verdict": None}, {"verdict": None}]


def test_marks_take_the_last_verdict_of_a_reader_when_a_hand_edit_holds_two(tmp_path):
    run = recorded_run(tmp_path)
    record = recommend.read_record(run)
    base = {"lens": "firm-boundaries", "fact": "F1", "by": READER, "at": "t"}
    record["link_checks"] = [{**base, "verdict": "doubt", "note": "first"}, {**base, "verdict": "bears", "note": ""}]
    _write(run, record)
    mark = recommend.marks(run)["firm-boundaries/F1"]
    assert mark["doubts"] == 0 and mark["verdicts"] == [{"reader": READER, "verdict": "bears", "note": ""}]


# --- the reader commands -------------------------------------------------------------------------------------------

def _link_command(run, *rest, lens="firm-boundaries", fact="F1", verdict="bears", by=READER):
    return ("record-link-check", "--run", run, "--lens", lens, "--fact", fact, "--verdict", verdict, "--by", by, *rest)


def test_the_context_command_prints_the_packets_and_changes_nothing(tmp_path, capsys):
    run = recorded_run(tmp_path)
    before = sorted((str(path), path.stat().st_mtime_ns) for path in run.rglob("*"))
    code, out = run_cli(capsys, "lens-link-context", "--run", run, "--lenses", LENSES)
    assert code == 0 and list(out) == ["part", "parts", "packets"] and (out["part"], out["parts"]) == (1, 1)
    assert out["packets"] == json.loads(json.dumps(recommend.link_packets(run, LENSES))) and len(out["packets"]) == 2
    assert sorted((str(path), path.stat().st_mtime_ns) for path in run.rglob("*")) == before


def test_the_context_command_prints_no_packet_without_a_recommendation(tmp_path, capsys):
    run = recommend_run(tmp_path)
    assert run_cli(capsys, "lens-link-context", "--run", run, "--lenses", LENSES) == (
        0, {"part": 1, "parts": 1, "packets": []})


def test_the_context_command_prints_many_links_in_parts_that_fit(tmp_path, capsys):
    run = many_moves_run(tmp_path)
    facts = [f"F{number}" for number in range(1, 81)]
    recommend.record_recommendation(run, LENSES, [entry(facts=facts)], None, recommend.ADVISOR, now=NOW)
    command = ("lens-link-context", "--run", run, "--lenses", LENSES)
    code, first = run_cli(capsys, *command)
    assert code == 0 and first["parts"] >= 2 and first == run_cli(capsys, *command, "--part", 1)[1]
    printed = [first] + [run_cli(capsys, *command, "--part", n)[1] for n in range(2, first["parts"] + 1)]
    assert [packet["fact"] for given in printed for packet in given["packets"]] == facts
    assert all(len(json.dumps(given)) < 20000 for given in printed)
    code, out = run_cli(capsys, *command, "--part", 99)
    assert code == 1 and list(out) == ["problems", "explained"]
    assert f"{first['parts']} parts" in out["problems"][0]["message"] and out["explained"][0]["known"] is True
    assert run_cli(capsys, *command, "--part", "x")[0] == 2


def test_the_context_command_refuses_a_missing_lens_folder_and_a_folder_that_is_not_a_run(tmp_path, capsys):
    run = recorded_run(tmp_path)
    code, out = run_cli(capsys, "lens-link-context", "--run", run, "--lenses", tmp_path / "nothing")
    assert code == 2 and list(out) == ["error"]
    code, out = run_cli(capsys, "lens-link-context", "--run", tmp_path, "--lenses", LENSES)
    assert code == 2 and list(out) == ["error"]


def test_the_record_command_records_a_verdict(tmp_path, capsys):
    run = recorded_run(tmp_path)
    assert run_cli(capsys, *_link_command(run, "--note", "It names the customer.")) == (0, {"ok": True})
    check = recommend.read_record(run)["link_checks"][0]
    assert (check["lens"], check["fact"], check["by"], check["verdict"], check["note"]) == (
        "firm-boundaries", "F1", READER, "bears", "It names the customer.")


def test_the_record_command_cleans_the_note_as_record_support_does(tmp_path, capsys):
    run = recorded_run(tmp_path)
    run_cli(capsys, *_link_command(run, "--note", "  One line\r\nand another.  ", verdict="doubt"))
    assert recommend.read_record(run)["link_checks"][0]["note"] == "One line and another."
    code, out = run_cli(capsys, *_link_command(run, "--note", "a" * 2001, fact="F2", verdict="doubt"))
    assert code == 2 and "2,000" in out["error"]
    code, out = run_cli(capsys, *_link_command(run, "--note", "bad\x07note", fact="F2", verdict="doubt"))
    assert code == 2 and "control" in out["error"]
    assert len(recommend.read_record(run)["link_checks"]) == 1


def test_the_record_command_reads_the_note_from_standard_input(tmp_path, capsys, monkeypatch):
    run = recorded_run(tmp_path)
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO("Not about plant; it is about price.\n".encode()),
                                                       encoding="utf-8"))
    assert run_cli(capsys, *_link_command(run, "--note-stdin", verdict="doubt", by=QUICK)) == (0, {"ok": True})
    check = recommend.read_record(run)["link_checks"][0]
    assert (check["by"], check["note"]) == (QUICK, "Not about plant; it is about price.")


def test_the_record_command_needs_exactly_one_note_option_but_a_bears_note_may_be_empty(tmp_path, capsys):
    run = recorded_run(tmp_path)
    code, out = run_cli(capsys, *_link_command(run))
    assert code == 2 and out == {"error": "give either --note or --note-stdin"}
    code, out = run_cli(capsys, *_link_command(run, "--note", "x", "--note-stdin"))
    assert code == 2 and out == {"error": "give either --note or --note-stdin"}
    assert run_cli(capsys, *_link_command(run, "--note", "")) == (0, {"ok": True})


@pytest.mark.parametrize("kwargs, message", [
    ({"by": "lens-advisor"}, "NOT_A_READER"), ({"fact": "F3"}, "NOT_A_LINK"), ({"lens": "capacity-commitment"}, "NOT_A_LINK"),
    ({"verdict": "doubt"}, "DOUBT_NEEDS_NOTE")])
def test_the_record_command_refuses_with_a_fixed_message(tmp_path, capsys, kwargs, message):
    run = recorded_run(tmp_path)
    code, out = run_cli(capsys, *_link_command(run, "--note", "", **kwargs))
    assert (code, out) == (2, {"error": getattr(recommend, message)})
    assert recommend.read_record(run)["link_checks"] == []


def test_the_record_command_refuses_a_verdict_that_is_neither(tmp_path, capsys):
    run = recorded_run(tmp_path)
    assert cli.main([str(part) for part in _link_command(run, "--note", "", verdict="maybe")]) == 2
    capsys.readouterr()
    assert recommend.read_record(run)["link_checks"] == []


def test_the_record_command_reports_a_busy_run(tmp_path, capsys, monkeypatch):
    run = recorded_run(tmp_path)
    monkeypatch.setattr(store, "LOCK_WAIT_SECONDS", 0.2)
    with store.locked(run, wait=None):
        code, out = run_cli(capsys, *_link_command(run, "--note", ""))
    assert code == 2 and out["busy"] is True


# --- every message is fixed and explained by its own entry -------------------------------------------------------------

MESSAGES = ("TOO_MANY", "NOTE_NEEDED", "ENTRIES_NOT_A_LIST", "ENTRY_PARTS", "LENS_NOT_FOUND", "LENS_FAILS_CHECK",
            "LENS_TWICE", "PART_WORDS", "PART_NOT_IN_QUESTION", "FACTS_NOT_A_LIST", "FACT_UNKNOWN",
            "FACT_DOES_NOT_COUNT", "TEXT_NEEDED", "TEXT_TOO_LONG", "NOT_THE_ADVISOR", "REFUSED", "SHAPE_PARTS",
            "SHAPE_FORM", "LINK_NOTE_TOO_LONG", "FACT_TWICE", "NOT_A_READER", "NOT_A_LINK", "NO_RECOMMENDATION",
            "VERDICT_UNKNOWN", "DOUBT_NEEDS_NOTE", "READER_NOTE_TOO_LONG")


def test_every_message_is_explained_by_its_own_entry():
    entries = json.loads((Path(recommend.__file__).with_name("explanations_en.json")).read_text(encoding="utf-8"))
    for name in MESSAGES:
        message = getattr(recommend, name)
        assert message in entries, name
        assert explain(Problem(recommend.RECORD, None, message)) == {"known": True, **entries[message]}, name


def test_no_message_holds_another_explanation_key():
    entries = json.loads((Path(recommend.__file__).with_name("explanations_en.json")).read_text(encoding="utf-8"))
    for name in MESSAGES:
        message = getattr(recommend, name)
        for key in entries:
            if key == message:
                continue
            pattern = r"(?P<id>.+?)".join(re.escape(part) for part in key.split("{id}"))
            assert not re.search(pattern, message), (name, key)


def test_the_explanations_of_a_damaged_record_say_it_does_not_block():
    for name in ("SHAPE_PARTS", "SHAPE_FORM", "LINK_NOTE_TOO_LONG"):
        entry_ = explain(Problem(recommend.RECORD, None, getattr(recommend, name)))
        assert "changed after the program wrote it" in entry_["why"], name
        assert "does not stop the report" in entry_["do"] and "again" not in entry_["do"], name
        assert "only advice" in entry_["do"] and "Nothing is repaired" in entry_["do"], name
        assert "marked where it stands" in entry_["do"], name   # Paul's decision 18: kept, and flagged


# --- Paul's decision 18: every damaged place of a record is said somewhere ------------------------------------------

def _check(**over):
    return {"lens": "firm-boundaries", "fact": "F1", "by": READER, "verdict": "bears", "note": "", "at": "t", **over}


DAMAGE = {
    "an extra part": lambda r: r.update(extra=1),
    "no by": lambda r: r.pop("by"),
    "by not a text": lambda r: r.update(by=3),
    "at not a text": lambda r: r.update(at=3),
    "question not a text": lambda r: r.update(question=3),
    "note not a text": lambda r: r.update(note=5),
    "note empty": lambda r: r.update(note=" "),
    "note too long": lambda r: r.update(note="x" * 401),
    "no facts_seen": lambda r: r.pop("facts_seen"),
    "facts_seen not an object": lambda r: r.update(facts_seen=[]),
    "models not an object": lambda r: r.update(models_set_to=3),
    "models with an extra helper": lambda r: r["models_set_to"].update(other="x"),
    "a model not a text": lambda r: r["models_set_to"].update({recommend.ADVISOR: 3}),
    "entries not a list": lambda r: r.update(entries=3),
    "an entry not an object": lambda r: r["entries"].append(7),
    "an entry with no lens": lambda r: r["entries"][1].pop("lens"),
    "an entry with an extra part": lambda r: r["entries"][0].update(extra=1),
    "an entry missing a part": lambda r: r["entries"][0].pop("missing"),
    "why not a text": lambda r: r["entries"][0].update(why=5),
    "why empty": lambda r: r["entries"][0].update(why=""),
    "why too long": lambda r: r["entries"][0].update(why="x" * 401),
    "facts not a list": lambda r: r["entries"][0].update(facts="F1"),
    "a fact not a text": lambda r: r["entries"][0].update(facts=["F1", 3]),
    "link checks not a list": lambda r: r.update(link_checks=3),
    "a link check not an object": lambda r: r.update(link_checks=[7]),
    "a verdict unknown": lambda r: r.update(link_checks=[_check(verdict="maybe")]),
    "a stranger's verdict": lambda r: r.update(link_checks=[_check(by="someone")]),
    "a note too long": lambda r: r.update(link_checks=[_check(note="x" * 2001)]),
    "a check with no time": lambda r: r.update(link_checks=[{k: v for k, v in _check().items() if k != "at"}]),
    "a damaged verdict on a link the list does not hold": lambda r: r.update(
        link_checks=[_check(fact="F9", verdict="maybe")]),
    "a damaged verdict on a lens that cannot be read": lambda r: (r["entries"].append(5), r.update(
        link_checks=[_check(lens="lost", verdict="maybe")])),
}


@pytest.mark.parametrize("name", list(DAMAGE))
def test_every_damaged_place_is_said_somewhere(tmp_path, name):
    """The invariant behind "flag exactly where": a record whose form is wrong is never shown as damaged without a
    sentence that says where. Either nothing of it can be read (then the whole is said to be damaged), or at least one
    sentence stands on the record, on an entry, or next to a link."""
    from radar import lens_view
    from radar.report.model import load_labels
    run = recorded_run(tmp_path)
    record = recommend.read_record(run)
    DAMAGE[name](record)
    _write(run, record)
    assert recommend.shape_problems(recommend.read_record(run)), "the case must be damage the shape check sees"
    cleaned, damage, damaged = recommend.readable_record(run)
    assert damaged is True
    if cleaned is None:
        return
    labels = load_labels()
    said = recommend.damage_sentences(damage, labels)
    said += [flag for entry in cleaned["entries"] for flag in recommend.damage_sentences(entry["damage"], labels)]
    said += ["unreadable"] * sum(mark["unreadable"] for mark in recommend.marks(run).values())
    assert said, name
    view = lens_view.run_view(run, LENSES)
    assert view["damaged"] is True and view["recommendation"] is not None


def test_a_reader_whose_verdict_cannot_be_read_is_not_said_to_have_recorded_nothing(tmp_path):
    """Fresh review 3: "doubt" changed by hand to "Doubt" is a verdict that cannot be read, not a missing one."""
    run = recorded_run(tmp_path)
    link(run, "F1", by=READER, verdict="doubt", note="Not about capacity.")
    record = recommend.read_record(run)
    record["link_checks"][0]["verdict"] = "Doubt"
    _write(run, record)
    mark = recommend.marks(run)["firm-boundaries/F1"]
    assert mark["unread_by"] == [QUICK] and mark["unreadable"] == 1 and mark["read_by"] == []


def test_a_key_that_looks_like_a_place_is_an_extra_part_and_moves_nothing(tmp_path):
    """Fresh review 4: a hand-added key named like a place in a list is flagged as an extra part, and no verdict or
    entry is taken for damaged because of it."""
    run = recorded_run(tmp_path)
    link(run, "F1", by=READER)
    record = recommend.read_record(run)
    record["link_checks[0]"] = 1
    record["entries[0]"] = "x"
    _write(run, record)
    cleaned, damage, damaged = recommend.readable_record(run)
    assert damaged and damage == [{"part": "extra", "readable": False}]
    assert recommend.marks(run)["firm-boundaries/F1"]["read_by"] == [READER]
    assert cleaned["entries"][0]["damage"] == []


def test_an_emptied_text_is_flagged_and_not_shown(tmp_path):
    """Fresh review 6: an empty text is shown as nothing, and its flag says it was changed."""
    run = recorded_run(tmp_path)
    record = recommend.read_record(run)
    record["entries"][0]["why"] = "  "
    _write(run, record)
    cleaned, _, _ = recommend.readable_record(run)
    assert cleaned["entries"][0]["why"] is None
    assert cleaned["entries"][0]["damage"] == [{"part": "why", "readable": True}]


def test_a_fact_list_with_a_stray_keeps_its_fact_numbers_and_says_it_was_changed(tmp_path):
    """Fresh review 5: the fact numbers that are there are shown; the flag says the list was changed."""
    from radar.report.model import load_labels
    run = recorded_run(tmp_path)
    record = recommend.read_record(run)
    record["entries"][0]["facts"] = ["F1", 7]
    _write(run, record)
    cleaned, _, _ = recommend.readable_record(run)
    assert cleaned["entries"][0]["facts"] == ["F1"]
    assert recommend.damage_sentences(cleaned["entries"][0]["damage"], load_labels()) == [
        "Its list of facts was changed after the program wrote it, so it is not as the advisor wrote it."]
