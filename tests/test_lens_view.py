"""`radar list-lenses`: every lens in a folder, once, grouped by the themes index, with its level in plain words.

The folders here are copies of the shipped lenses (or of the invented demo lenses) in a temporary folder, with an
index written for the test.
"""
import json
import shutil
from pathlib import Path

import pytest

from helpers import unreadable_file
from radar import lens_view, lenses, recommend, store, verify
from radar.gate import gate
from radar.status import run_status
from radar.cli import main
from radar.demo import LENSES as DEMO_LENSES
from radar.lenses import THEMES_FILE
from radar.report.model import load_labels
from test_recommend import NOW, QUESTION, TEXT, entry, recommend_run

ROOT = Path(__file__).resolve().parent.parent
SHIPPED = ROOT / "lenses"
IDS = sorted(path.stem for path in SHIPPED.glob("*.json") if path.name != THEMES_FILE)
ENTRY_KEYS = ["id", "name", "idea", "level", "rests_on", "invented"]
PLAIN_LEVELS = {"Original read", "Secondary source read", "Course slides", "Reference confirmed", "Invented for practice"}


def folder(tmp_path, index="shipped", ids=IDS) -> Path:
    """A folder of copies of the shipped lenses `ids`, with the index `index`: "shipped" copies the real one, None
    writes none, anything else is written as the index."""
    target = tmp_path / "lenses"
    target.mkdir()
    for lens_id in ids:
        shutil.copy(SHIPPED / f"{lens_id}.json", target / f"{lens_id}.json")
    if index == "shipped":
        shutil.copy(SHIPPED / THEMES_FILE, target / THEMES_FILE)
    elif index is not None:
        (target / THEMES_FILE).write_text(json.dumps(index), encoding="utf-8")
    return target


def shown(result: dict) -> list[str]:
    """Every lens id the result shows, in the order it shows them."""
    return [entry["id"] for theme in result["themes"] for entry in theme["lenses"]] + \
           [entry["id"] for entry in result["not_yet_sorted"]]


def test_every_lens_appears_exactly_once(tmp_path):
    index = {"themes": [{"name": "One", "lenses": [IDS[0], IDS[1], IDS[0]]},   # a lens listed twice in a theme
                        {"name": "Two", "lenses": [IDS[1], IDS[2], "no-such-lens"]}]}   # and again in another theme
    target = folder(tmp_path, index)
    (target / "broken.json").write_text("{", encoding="utf-8")
    result = lens_view.list_lenses(target, exclude=frozenset({IDS[3]}))
    seen = shown(result) + result["unreadable"] + [IDS[3]]
    assert sorted(seen) == sorted([*IDS, "broken.json"]), seen
    assert len(seen) == len(set(seen))
    assert result["unreadable"] == ["broken.json"]
    assert [theme["name"] for theme in result["themes"]] == ["One", "Two"]
    assert [entry["id"] for entry in result["themes"][0]["lenses"]] == [IDS[0], IDS[1]]
    assert [entry["id"] for entry in result["themes"][1]["lenses"]] == [IDS[2]]
    assert result["count"] == len(IDS)   # the lens that is left out of the lists is still counted; the broken one is not


def test_a_lens_missing_from_the_index_is_not_yet_sorted(tmp_path):
    target = folder(tmp_path, {"themes": [{"name": "Only", "lenses": IDS[:2]}]})
    result = lens_view.list_lenses(target)
    assert [entry["id"] for entry in result["themes"][0]["lenses"]] == IDS[:2]
    assert [entry["id"] for entry in result["not_yet_sorted"]] == IDS[2:]


def test_an_index_id_with_no_file_is_ignored_here(tmp_path):
    target = folder(tmp_path, {"themes": [{"name": "Only", "lenses": ["ghost", *IDS]}]})
    result = lens_view.list_lenses(target)
    assert shown(result) == IDS and result["not_yet_sorted"] == [] and result["unreadable"] == []


def test_no_index_puts_every_lens_in_not_yet_sorted(tmp_path):
    result = lens_view.list_lenses(folder(tmp_path, None))
    assert result["themes"] == [] and [entry["id"] for entry in result["not_yet_sorted"]] == IDS
    assert result["count"] == len(IDS)


def test_a_damaged_index_leaves_every_lens_in_not_yet_sorted_and_does_not_raise(tmp_path):
    target = folder(tmp_path, None)
    (target / THEMES_FILE).write_text("{", encoding="utf-8")
    result = lens_view.list_lenses(target)
    assert result["themes"] == [] and [entry["id"] for entry in result["not_yet_sorted"]] == IDS


def test_a_theme_left_with_no_lens_is_not_shown(tmp_path):
    target = folder(tmp_path, {"themes": [{"name": "Gone", "lenses": [IDS[0]]}, {"name": "Rest", "lenses": IDS[1:]}]})
    result = lens_view.list_lenses(target, exclude=frozenset({IDS[0]}))
    assert [theme["name"] for theme in result["themes"]] == ["Rest"] and IDS[0] not in shown(result)


def test_an_unreadable_lens_is_named_and_does_not_raise(tmp_path):
    target = folder(tmp_path)
    (target / "empty.json").write_text("", encoding="utf-8")
    broken = json.loads((SHIPPED / f"{IDS[0]}.json").read_text(encoding="utf-8"))
    del broken["originals"]   # a lens that fails the lens check is never shown with a level
    (target / "no-originals.json").write_text(json.dumps({**broken, "id": "no-originals"}), encoding="utf-8")
    result = lens_view.list_lenses(target)
    assert result["unreadable"] == ["empty.json", "no-originals.json"]
    assert "empty" not in shown(result) and "no-originals" not in shown(result)
    assert sorted(shown(result)) == IDS


def test_a_lens_file_that_cannot_be_opened_is_named_and_does_not_raise(tmp_path):
    target = folder(tmp_path)
    with unreadable_file(target / f"{IDS[0]}.json"):
        result = lens_view.list_lenses(target)
    assert result["unreadable"] == [f"{IDS[0]}.json"] and sorted(shown(result)) == IDS[1:]


def test_a_folder_that_cannot_be_listed_raises_the_one_named_error(tmp_path, monkeypatch):
    target = folder(tmp_path)
    monkeypatch.setattr(lenses, "lens_files", lambda lenses_dir: None)
    with pytest.raises(lens_view.LensFolderUnreadable) as caught:
        lens_view.list_lenses(target)
    assert str(caught.value) == lenses.FOLDER_UNREADABLE


def test_a_folder_with_no_lens_shows_nothing(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert lens_view.list_lenses(empty) == {"themes": [], "not_yet_sorted": [], "unreadable": [], "count": 0}


def test_levels_are_plain_words_never_codes(tmp_path):
    target = folder(tmp_path)
    labels = load_labels()
    result = lens_view.list_lenses(target)
    entries = [entry for theme in result["themes"] for entry in theme["lenses"]] + result["not_yet_sorted"]
    assert len(entries) == len(IDS)
    for entry in entries:
        assert list(entry) == ENTRY_KEYS
        assert entry["level"] in PLAIN_LEVELS and "_" not in entry["level"]
        lens = json.loads((SHIPPED / f"{entry['id']}.json").read_text(encoding="utf-8"))
        assert entry["level"] == labels["level_" + lenses.lens_level(lens)]
        assert entry["rests_on"] == lenses.rests_on(lens)
        assert (entry["name"], entry["idea"]) == (lens["name"], lens["idea"])
        assert entry["invented"] is False
    assert {entry["id"]: entry["level"] for entry in entries}["build-abroad-market-or-cost"] == "Reference confirmed"


def test_a_secondary_source_lens_is_shown_with_its_level_and_what_it_rests_on(tmp_path):
    target = folder(tmp_path)
    path = target / f"{IDS[0]}.json"
    lens = json.loads(path.read_text(encoding="utf-8"))
    lens["originals"][0].update({"level": "secondary_source_read", "about": "An invented work (2000)",
                                 "link": "https://www.example.org/article"})
    path.write_text(json.dumps(lens), encoding="utf-8")
    entry = next(entry for entry in lens_view.list_lenses(target)["not_yet_sorted"]
                 + [e for theme in lens_view.list_lenses(target)["themes"] for e in theme["lenses"]]
                 if entry["id"] == IDS[0])
    assert entry["level"] == "Secondary source read" and "An invented work (2000)" in entry["rests_on"]


def test_the_demo_lenses_are_invented_for_practice_never_a_level():
    result = lens_view.list_lenses(DEMO_LENSES)
    entries = result["not_yet_sorted"]
    assert result["themes"] == [] and result["unreadable"] == [] and result["count"] == 2
    assert sorted(entry["id"] for entry in entries) == ["capacity-commitment", "firm-boundaries"]
    for entry in entries:
        assert entry["invented"] is True and entry["level"] == "Invented for practice"
        assert entry["rests_on"] == "Invented for practice: this lens rests on no real work."
        assert "Reference confirmed" not in json.dumps(entry)


def test_one_illustrative_original_makes_the_whole_lens_invented(tmp_path):
    target = folder(tmp_path)
    path = target / f"{IDS[0]}.json"
    lens = json.loads(path.read_text(encoding="utf-8"))
    lens["originals"][1]["reference"] = "  ILLUSTRATIVE reference, not a real work"   # after spaces, in any case
    path.write_text(json.dumps(lens), encoding="utf-8")
    result = lens_view.list_lenses(target)
    entry = next(e for e in [*result["not_yet_sorted"], *(e for t in result["themes"] for e in t["lenses"])]
                 if e["id"] == IDS[0])
    assert entry["invented"] is True and entry["level"] == "Invented for practice"
    others = [e for e in [*result["not_yet_sorted"], *(e for t in result["themes"] for e in t["lenses"])]
              if e["id"] != IDS[0]]
    assert all(not e["invented"] for e in others)


def snapshot(target: Path) -> dict:
    return {str(path.relative_to(target)): (path.stat().st_mtime_ns, path.read_bytes() if path.is_file() else None)
            for path in sorted(target.rglob("*"))}


def test_the_command_prints_one_json_line_and_changes_nothing(tmp_path, capsys):
    target = folder(tmp_path)
    before = snapshot(target)
    code = main(["list-lenses", "--lenses", str(target)])
    out = capsys.readouterr().out
    assert code == 0 and out.endswith("\n") and out.count("\n") == 1
    printed = json.loads(out)
    assert list(printed) == ["themes", "not_yet_sorted", "unreadable", "count"]
    assert printed == lens_view.list_lenses(target) and printed["count"] == len(IDS)
    assert snapshot(target) == before


def test_the_command_refuses_a_folder_that_is_missing_or_a_file(tmp_path, capsys):
    for path in (tmp_path / "missing", Path(__file__)):
        assert main(["list-lenses", "--lenses", str(path)]) == 2
        assert list(json.loads(capsys.readouterr().out)) == ["error"]
    assert main(["list-lenses"]) == 2   # --lenses is required
    capsys.readouterr()


def test_the_command_names_a_folder_that_cannot_be_read_in_the_words_of_the_lens_check(tmp_path, capsys, monkeypatch):
    target = folder(tmp_path)
    monkeypatch.setattr(lenses, "lens_files", lambda lenses_dir: None)
    assert main(["list-lenses", "--lenses", str(target)]) == 2
    assert json.loads(capsys.readouterr().out) == {"error": lenses.FOLDER_UNREADABLE}


def test_the_labels_for_an_invented_lens_are_plain_words():
    labels = load_labels()
    assert labels["level_invented"] == "Invented for practice"
    assert labels["rests_on_invented"] == "Invented for practice: this lens rests on no real work."


# --- the first stop's view: radar lens-view -----------------------------------------------------------------------------

VIEW_KEYS = ["recommendation", "stale", "marks", "others", "damaged"]
RECORDED_KEYS = ["lens", "question_part", "why", "facts", "missing"]


def recorded(tmp_path, entries, lenses_dir=None, note=None):
    """A run (F1 and F2 count) with a recorded recommendation, and the lens folder it was made against."""
    lenses_dir = folder(tmp_path) if lenses_dir is None else lenses_dir
    run = recommend_run(tmp_path)
    recommend.record_recommendation(run, lenses_dir, entries, note, recommend.ADVISOR, now=NOW)
    return run, lenses_dir


def every_lens(result: dict) -> list[str]:
    return shown(result) + result["unreadable"]


def test_the_view_splits_entries_by_facts_and_keeps_order(tmp_path):
    entries = [entry(lens=IDS[2]), entry(lens=IDS[0], facts=[], question_part="for whom"),
               entry(lens=IDS[1], facts=["F2"]), entry(lens=IDS[3], facts=[], question_part="adding filling")]
    run, target = recorded(tmp_path, entries, note="Four fit.")
    view = lens_view.run_view(run, target)
    assert list(view) == VIEW_KEYS and view["stale"] is False and view["damaged"] is False
    recommendation = view["recommendation"]
    assert list(recommendation) == ["by", "at", "note", "models_set_to", "recommended", "no_facts_yet", "flags"]
    assert recommendation["flags"] == []
    assert (recommendation["by"], recommendation["at"], recommendation["note"]) == (
        "lens-advisor", "2026-11-16T09:30:00Z", "Four fit.")
    assert recommendation["models_set_to"] == recommend.read_record(run)["models_set_to"]
    assert [item["lens"] for item in recommendation["recommended"]] == [IDS[2], IDS[1]]
    assert [item["lens"] for item in recommendation["no_facts_yet"]] == [IDS[0], IDS[3]]
    listed = {item["id"]: item for item in lens_view.list_lenses(target)["not_yet_sorted"]}
    listed.update({item["id"]: item for theme in lens_view.list_lenses(target)["themes"] for item in theme["lenses"]})
    for item, recorded_entry in zip(recommendation["recommended"] + recommendation["no_facts_yet"],
                                    [entries[0], entries[2], entries[1], entries[3]]):
        assert list(item) == RECORDED_KEYS + ["flags", "name", "level", "rests_on", "invented", "available"]
        assert item["flags"] == []
        assert {key: item[key] for key in RECORDED_KEYS} == recorded_entry
        lens = listed[item["lens"]]
        assert (item["name"], item["level"], item["rests_on"], item["invented"], item["available"]) == (
            lens["name"], lens["level"], lens["rests_on"], lens["invented"], True)


def test_the_view_does_not_share_its_lists_with_the_record(tmp_path):
    run, target = recorded(tmp_path, [entry(lens=IDS[0])])
    view = lens_view.run_view(run, target)
    view["recommendation"]["recommended"][0]["facts"].append("F9")
    assert recommend.read_record(run)["entries"][0]["facts"] == ["F1", "F2"]


@pytest.mark.parametrize("index", [{"themes": []}, None, "damaged", "shipped"])
def test_others_lists_every_lens_not_recommended_even_when_the_index_is_empty(tmp_path, index):
    entries = [entry(lens=IDS[1]), entry(lens=IDS[4], facts=[], question_part="for whom")]
    target = folder(tmp_path, "shipped" if index == "damaged" else index)
    if index == "damaged":
        (target / THEMES_FILE).write_text("{", encoding="utf-8")
    run, _ = recorded(tmp_path, entries, target)
    others = lens_view.run_view(run, target)["others"]
    assert sorted(every_lens(others)) == sorted(set(IDS) - {IDS[1], IDS[4]})
    assert others["count"] == len(IDS)   # a recommended lens is still counted, as list_lenses counts it
    if index != "shipped":
        assert others["themes"] == [] and len(others["not_yet_sorted"]) == len(IDS) - 2
    assert others == lens_view.list_lenses(target, exclude=frozenset({IDS[1], IDS[4]}))


def test_no_record_gives_the_full_list_and_no_recommendation(tmp_path):
    target = folder(tmp_path)
    run = recommend_run(tmp_path)
    view = lens_view.run_view(run, target)
    assert view == {"recommendation": None, "stale": False, "marks": {}, "damaged": False,
                    "others": lens_view.list_lenses(target)}
    assert sorted(every_lens(view["others"])) == sorted(IDS)


def test_the_demo_lens_folder_with_no_index_and_an_unreadable_lens_never_raises(tmp_path):
    run = recommend_run(tmp_path)
    broken = tmp_path / "broken-lenses"
    shutil.copytree(DEMO_LENSES, broken)
    (broken / "capacity-commitment.json").write_text("{", encoding="utf-8")
    view = lens_view.run_view(run, broken)
    assert view["recommendation"] is None and view["others"]["unreadable"] == ["capacity-commitment.json"]
    assert shown(view["others"]) == ["firm-boundaries"]
    assert sorted(every_lens(lens_view.run_view(run, DEMO_LENSES)["others"])) == ["capacity-commitment", "firm-boundaries"]


def test_a_withdrawn_fact_makes_the_view_stale_without_a_settle(tmp_path):
    run, target = recorded(tmp_path, [entry(lens=IDS[0])])
    assert lens_view.run_view(run, target)["stale"] is False
    verify.withdraw_fact(run, "F2", "A duplicate of F1.")
    assert store.read_facts(run)["F2"]["status"] == "confirmed"   # not settled again: the status still says confirmed
    view = lens_view.run_view(run, target)
    assert view["stale"] is True
    assert view["recommendation"]["recommended"][0]["facts"] == ["F1", "F2"]   # still as recorded, never rewritten


def test_a_stale_view_lists_every_lens_in_others_also_the_recommended_ones(tmp_path):
    """Final review I2: step 6 treats a view still out of date after one re-run as no recommendation and shows the
    full grouped list. That list is `others`, so it must hold every lens file then, the recommended ones too."""
    entries = [entry(lens=IDS[1]), entry(lens=IDS[4], facts=[], question_part="for whom")]
    run, target = recorded(tmp_path, entries)
    (target / "broken.json").write_text("{", encoding="utf-8")
    current = lens_view.run_view(run, target)
    assert current["stale"] is False
    assert sorted(every_lens(current["others"])) == sorted([*(set(IDS) - {IDS[1], IDS[4]}), "broken.json"])
    verify.withdraw_fact(run, "F2", "A duplicate of F1.")
    verify.settle(run)
    view = lens_view.run_view(run, target)
    assert view["stale"] is True and view["recommendation"] is not None   # still shown as recorded, marked stale
    assert sorted(every_lens(view["others"])) == sorted([*IDS, "broken.json"])
    assert view["others"] == lens_view.list_lenses(target)
    files = sorted(path.name for path in target.glob("*.json") if path.name != THEMES_FILE)
    assert sorted([f"{lens_id}.json" for lens_id in shown(view["others"])] + view["others"]["unreadable"]) == files


def test_a_new_confirmed_fact_makes_the_view_stale(tmp_path):
    from helpers import add_fact
    run, target = recorded(tmp_path, [entry(lens=IDS[0])])
    add_fact(run, source_id="S1", primary_source=True, statement="A second line is planned.",
             quote="a second filling line at Plant North")
    assert lens_view.run_view(run, target)["stale"] is False   # proposed only: it does not count yet
    verify.check_quotes(run)
    verify.record_support(run, "F4", True, "support-checker", "")
    verify.settle(run)
    assert store.read_facts(run)["F4"]["status"] == "confirmed"
    assert lens_view.run_view(run, target)["stale"] is True


def test_a_fact_that_changes_status_makes_the_view_stale_and_one_that_never_counted_does_not(tmp_path):
    run, target = recorded(tmp_path, [entry(lens=IDS[0])])
    fact = store.read_facts(run)["F3"]   # rejected, never counted
    fact["statement"] = "A changed statement of a fact that never counted."
    store.write_fact(run, fact)
    assert lens_view.run_view(run, target)["stale"] is False
    fact = store.read_facts(run)["F2"]
    fact["status"], fact["status_reason"] = "uncertain", "single source that is not a primary source"
    store.write_fact(run, fact)
    assert lens_view.run_view(run, target)["stale"] is True


def test_the_view_changes_nothing_in_the_run_folder(tmp_path):
    entries = [entry(lens=IDS[0]), entry(lens=IDS[1], facts=[], question_part="for whom")]
    run, target = recorded(tmp_path, entries)
    recommend.record_link_check(run, IDS[0], "F1", "doubt", recommend.READERS[0], "Not clear.", now=NOW)
    verify.withdraw_fact(run, "F2", "A duplicate of F1.")
    before, lenses_before = snapshot(run), snapshot(target)
    assert lens_view.run_view(run, target)["stale"] is True
    assert snapshot(run) == before and snapshot(target) == lenses_before
    (run / recommend.RECORD).write_text("{", encoding="utf-8")
    before = snapshot(run)
    lens_view.run_view(run, target)
    assert snapshot(run) == before


def test_the_marks_are_the_readers_marks_of_the_record(tmp_path):
    run, target = recorded(tmp_path, [entry(lens=IDS[0])])
    recommend.record_link_check(run, IDS[0], "F1", "doubt", recommend.READERS[1], "It names no customer.", now=NOW)
    view = lens_view.run_view(run, target)
    assert view["marks"] == recommend.marks(run) and view["marks"][f"{IDS[0]}/F1"]["doubts"] == 1


@pytest.mark.parametrize("damage", ["not JSON", "a list", "a folder", "no entry can be read"])
def test_a_record_of_which_nothing_can_be_read_is_no_recommendation_and_is_said_to_be_damaged(tmp_path, damage):
    run, target = recorded(tmp_path, [entry(lens=IDS[0])])
    path = run / recommend.RECORD
    record = recommend.read_record(run)
    if damage == "not JSON":
        path.write_text("{", encoding="utf-8")
    elif damage == "a list":
        path.write_text("[]", encoding="utf-8")
    elif damage == "a folder":
        path.unlink()
        path.mkdir()
    else:
        record["entries"] = [7]
        path.write_text(json.dumps(record), encoding="utf-8")
    view = lens_view.run_view(run, target)
    assert view == {"recommendation": None, "stale": False, "marks": {}, "damaged": True,
                    "others": lens_view.list_lenses(target)}


def test_a_damaged_record_is_kept_and_each_damaged_part_is_flagged_where_it_stands(tmp_path):
    """Paul's decision 18: "do not throw it out but flag exactly where the doubt arises from"."""
    run, target = recorded(tmp_path, [entry(lens=IDS[0]), entry(lens=IDS[1], facts=["F2"]),
                                      entry(lens=IDS[2], facts=[], question_part="for whom")])
    path = run / recommend.RECORD
    record = recommend.read_record(run)
    record["entries"][0]["why"] = 5                       # not a text: cannot be read
    record["entries"][1]["missing"] = "x" * 401           # a text, longer than the advisor may write
    record["entries"].insert(2, "lost")                   # a whole entry that cannot be read
    del record["facts_seen"]                              # what it saw of the facts
    path.write_text(json.dumps(record), encoding="utf-8")
    view = lens_view.run_view(run, target)
    assert view["damaged"] is True and view["stale"] is False
    shown = view["recommendation"]
    assert [item["lens"] for item in shown["recommended"]] == [IDS[0], IDS[1]]
    assert [item["lens"] for item in shown["no_facts_yet"]] == [IDS[2]]
    first, second = shown["recommended"]
    assert first["why"] is None and first["flags"] == ["The reason given cannot be read: it was changed after the program wrote it."]
    assert second["missing"] == "x" * 401 and second["flags"] == [
        "What was not found was changed after the program wrote it, so it is not as the advisor wrote it."]
    assert shown["no_facts_yet"][0]["flags"] == []
    assert shown["flags"] == [
        "Whether this list still fits the facts cannot be told: what it saw of the facts was changed after the "
        "program wrote it.",
        "The lens in place 3 of the advisor's list cannot be read: it was changed after the program wrote it."]
    assert view["others"] == lens_view.list_lenses(target, exclude=frozenset(IDS[:3]))


def test_an_entry_whose_facts_cannot_be_read_stays_with_the_lenses_that_have_facts(tmp_path):
    run, target = recorded(tmp_path, [entry(lens=IDS[0])])
    record = recommend.read_record(run)
    record["entries"][0]["facts"] = "F1"
    (run / recommend.RECORD).write_text(json.dumps(record), encoding="utf-8")
    shown = lens_view.run_view(run, target)["recommendation"]
    assert shown["no_facts_yet"] == [] and shown["recommended"][0]["facts"] == []
    assert shown["recommended"][0]["flags"] == ["Its list of facts cannot be read: it was changed after the program wrote it."]


def test_a_recommended_lens_that_no_longer_passes_the_lens_check_is_shown_flagged_without_a_level(tmp_path):
    run = recommend_run(tmp_path)
    target = tmp_path / "demo-lenses"
    shutil.copytree(DEMO_LENSES, target)
    recommend.record_recommendation(run, target, [entry(), entry(lens="capacity-commitment", facts=[],
                                                                question_part="for whom")],
                                    None, recommend.ADVISOR, now=NOW)
    (target / "capacity-commitment.json").write_text("{", encoding="utf-8")
    (target / "firm-boundaries.json").unlink()
    view = lens_view.run_view(run, target)
    gone, broken = view["recommendation"]["recommended"][0], view["recommendation"]["no_facts_yet"][0]
    for item, lens_id in ((gone, "firm-boundaries"), (broken, "capacity-commitment")):
        assert item["available"] is False and item["name"] == lens_id
        assert item["level"] is None and item["rests_on"] is None and item["invented"] is False
        assert item["lens"] == lens_id
    assert gone["facts"] == ["F1", "F2"] and broken["facts"] == []
    assert view["others"]["unreadable"] == ["capacity-commitment.json"] and shown(view["others"]) == []


def test_the_view_refuses_a_lens_folder_that_cannot_be_listed(tmp_path, monkeypatch):
    run, target = recorded(tmp_path, [entry(lens=IDS[0])])
    monkeypatch.setattr(lenses, "lens_files", lambda lenses_dir: None)
    with pytest.raises(lens_view.LensFolderUnreadable):
        lens_view.run_view(run, target)


def test_the_lens_checkpoint_can_be_recorded_with_no_recommendation(tmp_path):
    run = recommend_run(tmp_path)
    assert recommend.read_record(run) is None
    store.record_checkpoint(run, "lenses", "person", "Use the first lens.")
    assert [item["name"] for item in store.load_run(run)["checkpoints"] if item["answered_by"] == "person"] == ["lenses"]
    assert not (run / recommend.RECORD).exists()
    plain = (run_status(run, DEMO_LENSES), gate(run, DEMO_LENSES))
    for damage in ("{", json.dumps({"entries": 5})):   # a record, damaged or not, changes neither
        (run / recommend.RECORD).write_text(damage, encoding="utf-8")
        assert (run_status(run, DEMO_LENSES), gate(run, DEMO_LENSES)) == plain


def test_the_command_prints_the_view_on_one_line_and_changes_nothing(tmp_path, capsys):
    run, target = recorded(tmp_path, [entry(lens=IDS[0]), entry(lens=IDS[1], facts=[], question_part="for whom")])
    before, lenses_before = snapshot(run), snapshot(target)
    code = main(["lens-view", "--run", str(run), "--lenses", str(target)])
    out = capsys.readouterr().out
    assert code == 0 and out.endswith("\n") and out.count("\n") == 1
    assert json.loads(out) == json.loads(json.dumps(lens_view.run_view(run, target)))
    assert list(json.loads(out)) == VIEW_KEYS
    assert snapshot(run) == before and snapshot(target) == lenses_before


def test_the_command_with_no_record_prints_every_lens(tmp_path, capsys):
    run, target = recommend_run(tmp_path), folder(tmp_path)
    assert main(["lens-view", "--run", str(run), "--lenses", str(target)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["recommendation"] is None and sorted(every_lens(printed["others"])) == sorted(IDS)


def test_the_command_refuses_a_lens_folder_that_is_missing_and_a_folder_that_is_not_a_run(tmp_path, capsys):
    run = recommend_run(tmp_path)
    for argv in (["--run", str(run), "--lenses", str(tmp_path / "missing")],
                 ["--run", str(tmp_path), "--lenses", str(DEMO_LENSES)],
                 ["--run", str(run)], ["--lenses", str(DEMO_LENSES)]):
        assert main(["lens-view", *argv]) == 2
        assert list(json.loads(capsys.readouterr().out)) == ["error"]


def test_the_command_names_a_lens_folder_that_cannot_be_read_in_the_words_of_the_lens_check(tmp_path, capsys,
                                                                                            monkeypatch):
    run = recommend_run(tmp_path)
    monkeypatch.setattr(lenses, "lens_files", lambda lenses_dir: None)
    assert main(["lens-view", "--run", str(run), "--lenses", str(DEMO_LENSES)]) == 2
    assert json.loads(capsys.readouterr().out) == {"error": lenses.FOLDER_UNREADABLE}
