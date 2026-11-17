"""The invented demo run as a command: `radar demo`, its stages, its variants and its third planted error."""
import re
import json
import subprocess
import sys
from pathlib import Path

import pytest

from radar import context, demo, store
from radar.cli import main
from radar.status import run_status
from helpers import read_only_folder, run_radar

ROOT = Path(__file__).parent.parent
ENGINE = ROOT / "engine"


def last_json(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def fact_id_of(run, text):
    return next(f["id"] for f in store.read_facts(run).values() if text in f["statement"])


def test_demo_command_builds_the_complete_run(tmp_path, capsys):
    assert main(["demo", "--root", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert Path(out["lenses"]) == demo.LENSES and Path(out["sources"]) == demo.SOURCES
    assert Path(out["run_dir"]) == tmp_path / "demo"
    assert main(["build-report", "--run", out["run_dir"], "--lenses", out["lenses"]]) == 0


def test_the_three_planted_errors_end_as_rejected(tmp_path):
    run = demo.build_demo_run(tmp_path)
    facts = store.read_facts(run)
    assert [(f, facts[f]["status"], facts[f]["status_reason"]) for f in ("F8", "F9", "F10")] == [
        ("F8", "rejected", "not_found"), ("F9", "rejected", "not_supported"), ("F10", "rejected", "not_supported")]
    assert facts["F8"]["checks"]["support"] is None          # settled by the program alone
    assert "does not plan" in facts["F10"]["checks"]["support"]["note"]
    counts = {}
    for fact in facts.values():
        counts[fact["status"]] = counts.get(fact["status"], 0) + 1
    assert len(facts) == 10 and counts == {"confirmed": 6, "uncertain": 1, "rejected": 3}


def test_the_passage_of_the_planted_negation_shows_the_not(tmp_path):
    run = demo.build_demo_run(tmp_path)
    fact_id = fact_id_of(run, "plans to offer its new filling lines")
    entry = context.packet(run, fact_id)["quotes"][0]
    assert entry["found"] and entry["located"]
    assert "does not plan to offer" in entry["passage"]
    assert entry["quote"] == "plan to offer the new lines to other drug makers"


def test_the_demo_records_a_verdict_only_for_the_facts_the_checker_would_be_asked_about(tmp_path):
    run = demo.build_demo_run(tmp_path, stage="checked")
    facts = store.read_facts(run)
    assert context.open_checks(run) == []                      # nothing is left to judge
    without_verdict = [f for f in facts if facts[f]["checks"]["support"] is None]
    assert without_verdict == ["F8"]                           # the changed number: the program settled it alone
    assert len(facts) - len(without_verdict) == 9


def test_stage_sources_has_sources_and_nothing_else(tmp_path):
    run = demo.build_demo_run(tmp_path, stage="sources")
    assert len(store.read_sources(run)) == 6 and store.read_facts(run) == {}
    status = run_status(run)
    assert status["next"] == "extract" and status["sources_to_read"] == [f"S{n}" for n in range(1, 7)]
    assert not (run / "analysis.json").exists() and store.load_run(run)["checkpoints"] == []
    assert len(store.load_run(run)["search_log"]) == 3


def test_stage_extracted_has_ten_unchecked_proposals(tmp_path):
    run = demo.build_demo_run(tmp_path, stage="extracted")
    facts = store.read_facts(run)
    assert len(facts) == 10 and {f["status"] for f in facts.values()} == {"proposed"}
    assert all(f["checks"]["quote"] is None for f in facts.values())
    assert store.load_run(run)["checkpoints"] == [] and not (run / "analysis.json").exists()
    assert run_status(run)["next"] == "verify"


def test_stage_checked_waits_for_the_first_decision(tmp_path):
    run = demo.build_demo_run(tmp_path, stage="checked")
    facts = store.read_facts(run)
    assert "proposed" not in {f["status"] for f in facts.values()}
    assert store.load_run(run)["checkpoints"] == [] and not (run / "analysis.json").exists()
    status = run_status(run)
    assert status["next"] == "checkpoint_lenses" and status["waiting_for_person"] is True


def test_the_tampered_variant_is_refused_and_explained(tmp_path, capsys):
    assert main(["demo", "--root", str(tmp_path), "--variant", "tampered"]) == 0
    out = last_json(capsys)
    assert out["run_dir"] == str(tmp_path / "demo-tampered")
    run = Path(out["run_dir"])
    rejected = next(f["id"] for f in store.read_facts(run).values() if f["status"] == "rejected")
    assert rejected in store.read_analysis(run)["messages"][0]["chain"][0]["fact_ids"]
    assert main(["build-report", "--run", str(run), "--lenses", out["lenses"]]) == 1
    result = last_json(capsys)
    assert result["built"] == []
    assert result["explained"][0]["what"] == f"The analysis uses fact {rejected}, but that fact was rejected."


def test_demo_refuses_an_existing_run(tmp_path, capsys):
    assert main(["demo", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert main(["demo", "--root", str(tmp_path)]) == 2
    assert "already exists" in last_json(capsys)["error"]
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")) == before


def test_demo_refuses_an_existing_run_of_a_later_stage_too(tmp_path, capsys):
    assert main(["demo", "--root", str(tmp_path), "--stage", "sources"]) == 0
    capsys.readouterr()
    assert main(["demo", "--root", str(tmp_path), "--stage", "checked"]) == 2


@pytest.mark.parametrize("stage", ["sources", "extracted", "checked"])
def test_tampered_with_a_stage_before_complete_is_refused_and_builds_nothing(tmp_path, capsys, stage):
    assert main(["demo", "--root", str(tmp_path / "x"), "--variant", "tampered", "--stage", stage]) == 2
    assert "tampered" in last_json(capsys)["error"] and not (tmp_path / "x").exists()
    with pytest.raises(ValueError, match="tampered"):
        demo.build_demo_run(tmp_path / "y", tampered=True, stage=stage)
    assert not (tmp_path / "y").exists()


def test_an_unknown_variant_or_stage_is_a_usage_error(tmp_path, capsys):
    assert main(["demo", "--root", str(tmp_path), "--variant", "other"]) == 2
    assert main(["demo", "--root", str(tmp_path), "--stage", "other"]) == 2
    with pytest.raises(ValueError, match="stage"):
        demo.build_demo_run(tmp_path / "z", stage="other")
    assert list(tmp_path.iterdir()) == []


def test_the_changed_and_private_variants_build_from_the_command_line(tmp_path, capsys):
    assert main(["demo", "--root", str(tmp_path), "--variant", "changed"]) == 0
    changed = Path(last_json(capsys)["run_dir"])
    assert changed.name == "demo-changed"
    assert main(["demo", "--root", str(tmp_path), "--variant", "private", "--stage", "extracted"]) == 0
    private = Path(last_json(capsys)["run_dir"])
    assert private.name == "demo-private" and store.load_run(private)["mode"] == "private"
    assert len(store.read_facts(private)) == 11 and len(store.read_sources(private)) == 7


def test_in_the_changed_variant_the_ids_shift_by_one(tmp_path):
    run = demo.build_demo_run(tmp_path, changed=True)
    facts = store.read_facts(run)
    assert "plans to offer its new filling lines" in facts["F9"]["statement"]
    assert "Competitor D" in facts["F10"]["statement"]


def test_the_data_lives_inside_the_package_and_the_paths_are_absolute():
    assert demo.LENSES.is_absolute() and demo.SOURCES.is_absolute()
    assert demo.LENSES.parent == demo.SOURCES.parent == ENGINE / "radar" / "demo"
    assert len(list(demo.LENSES.glob("*.json"))) == 2
    assert len(list(demo.SOURCES.glob("s*.txt"))) == 6


@pytest.mark.parametrize("first,second", [("radar.demo", "radar.cli"), ("radar.cli", "radar.demo")])
def test_demo_and_cli_import_in_either_order(first, second):
    code = (f"import sys\nsys.path.insert(0, {str(ENGINE)!r})\n"
            f"import {first}\nimport {second}\nimport radar.demo as d\nassert d.build_demo_run")
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_command_finds_its_data_from_any_working_directory(tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    result = run_radar("demo", "--root", str(tmp_path / "runs"), home=tmp_path, cwd=other)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert Path(out["lenses"]).is_dir() and Path(out["sources"]).is_dir() and Path(out["run_dir"]).is_dir()


# --- a root that is a file, or lies under a file, is a usage error ---------------------------------

def _file_roots(tmp_path):
    afile = tmp_path / "afile"
    afile.write_text("not a folder", encoding="utf-8")
    return [afile, afile / "sub"]


def test_demo_refuses_a_root_that_is_a_file_or_lies_under_one(tmp_path, capsys):
    for root in _file_roots(tmp_path):
        assert main(["demo", "--root", str(root)]) == 2
        out = last_json(capsys)
        assert list(out) == ["error"] and "is a file" in out["error"], root
    assert sorted(p.name for p in tmp_path.iterdir()) == ["afile"]


@pytest.mark.parametrize("command", [["demo"], ["init-run", "--question", "Q", "--pack", "demo"]])
def test_a_bad_root_prints_one_json_line_and_no_traceback(tmp_path, command):
    for root in _file_roots(tmp_path):
        result = run_radar(*command, "--root", str(root), home=tmp_path)
        assert result.returncode == 2, (root, result.stdout, result.stderr)
        assert result.stderr == "" and "Traceback" not in result.stdout
        lines = result.stdout.splitlines()
        assert len(lines) == 1 and "error" in json.loads(lines[0])
    assert sorted(p.name for p in tmp_path.iterdir()) == ["afile"]


# --- the private demo run: its notice was never shown, so it is marked and takes no more non-public material ----

from radar.explain import explain
from radar import schema
from radar.schema import Problem, check_data


def _copy_args(run, file, *extra):
    return ["add-copy", "--data-class", "public", "--run", str(run), "--file", str(file), "--url", "https://www.example.com/note",
            "--publisher", "Example Pharma", "--title", "A note", "--date", "2026-11-01", "--type", "other",
            "--speaker", "someone", "--interest", "none", "--language", "en", *extra]


def _note(tmp_path):
    note = tmp_path / "note.txt"
    note.write_text("An invented note. It says nothing real.", encoding="utf-8")
    return note


@pytest.mark.parametrize("stage", ["sources", "extracted", "checked", "complete"])
def test_the_private_demo_run_carries_the_mark_at_every_stage(tmp_path, stage):
    run = demo.build_demo_run(tmp_path, private=True, stage=stage)
    assert store.load_run(run)["private_acknowledged_by"] == "demo"


def test_other_demo_runs_and_real_runs_have_no_mark(tmp_path):
    for name, options in (("base", {}), ("changed", {"changed": True}), ("tampered", {"tampered": True})):
        run = demo.build_demo_run(tmp_path / name, **options)
        assert "private_acknowledged_by" not in store.load_run(run), name
    real = store.init_run(tmp_path / "real", "Q?", "demo", mode="private", acknowledged=True, acknowledged_words="Yes (an invented reply).")
    assert "private_acknowledged_by" not in store.load_run(real)


def test_the_private_demo_run_refuses_internal_and_licensed_material(tmp_path, capsys):
    run = demo.build_demo_run(tmp_path / "runs", private=True, stage="sources")
    note = _note(tmp_path)
    before = sorted(p.name for p in (run / "sources").iterdir())
    for data_class in ("internal", "licensed"):
        code = main(_copy_args(run, note, "--data-class", data_class, "--supplied-by", "someone", "--basis", "x"))
        out = last_json(capsys)
        assert code == 2 and out["error"] == store.DEMO_RUN_REFUSAL, data_class
        assert out["explained"][0]["known"] is True
        assert "never shown" in out["explained"][0]["why"] and "new run" in out["explained"][0]["do"]
    assert explain(Problem("run.json", None, store.DEMO_RUN_REFUSAL))["known"]
    assert sorted(p.name for p in (run / "sources").iterdir()) == before


def test_the_private_demo_run_still_takes_public_material(tmp_path, capsys):
    run = demo.build_demo_run(tmp_path / "runs", private=True, stage="sources")
    assert main(_copy_args(run, _note(tmp_path))) == 0
    assert last_json(capsys)["id"] == "S8"


def test_the_private_demo_run_still_builds_its_report_and_keeps_its_gate(tmp_path, capsys):
    run = demo.build_demo_run(tmp_path / "a")
    private = demo.build_demo_run(tmp_path / "b", private=True)
    assert check_data(private, demo.LENSES) == []
    assert main(["build-report", "--run", str(private), "--lenses", str(demo.LENSES)]) == 0
    assert "Confidential." in (private / "report" / "report.md").read_text(encoding="utf-8")
    capsys.readouterr()
    assert main(["build-report", "--run", str(private), "--lenses", str(demo.LENSES), "--publishable"]) == 1
    assert main(["build-report", "--run", str(run), "--lenses", str(demo.LENSES), "--publishable"]) == 0


def test_a_run_record_may_carry_the_mark_only_on_an_illustrative_private_run(tmp_path):
    problem = Problem("run.json", "private_acknowledged_by", schema.DEMO_MARK_PROBLEM)
    cases = {
        "a public run": dict(mode="public"),
        "a private run that is not illustrative": dict(mode="private", illustrative=False),
        "another value": dict(mode="private", illustrative=True, private_acknowledged_by="person"),
    }
    for label, changes in cases.items():
        run = store.init_run(tmp_path / label.replace(" ", "-"), "Q?", "demo", illustrative=True,
                             mode="private", acknowledged=True, home_company="Example Pharma", acknowledged_words="Yes (an invented reply).")
        record = {**store.load_run(run), "private_acknowledged_by": "demo", **changes}
        if record["mode"] == "public":
            record["private_acknowledged_at"] = None
        store.save_run(run, record)
        found = [p for p in check_data(run) if p.file == "run.json"]
        assert found == [problem], label
    assert explain(problem)["known"]


def test_marking_a_run_that_is_not_a_private_illustrative_run_is_refused(tmp_path):
    public = store.init_run(tmp_path / "a", "Q?", "demo", illustrative=True)
    private = store.init_run(tmp_path / "b", "Q?", "demo", mode="private", acknowledged=True, acknowledged_words="Yes (an invented reply).")
    for run in (public, private):
        with pytest.raises(ValueError):
            store.mark_demo_run(run)
        assert "private_acknowledged_by" not in store.load_run(run)


def test_the_private_variant_says_what_it_is_and_the_others_do_not(tmp_path, capsys):
    assert main(["demo", "--root", str(tmp_path), "--variant", "private", "--stage", "sources"]) == 0
    out = last_json(capsys)
    assert list(out) == ["run_dir", "lenses", "sources", "notice"]
    assert out["notice"] == demo.PRIVATE_DEMO_NOTICE and out["notice"].count(".") == 1
    for words in ("invented", "not shown", "non-public"):
        assert words in out["notice"]
    for variant in ("base", "changed", "tampered"):
        assert main(["demo", "--root", str(tmp_path / variant), "--variant", variant, "--stage", "complete"]) == 0
        assert list(last_json(capsys)) == ["run_dir", "lenses", "sources"], variant


def test_the_help_and_the_docs_say_the_private_variant_is_invented(tmp_path):
    result = run_radar("demo", "--help", home=tmp_path)
    flat = " ".join(result.stdout.split())
    assert "invented" in flat and "notice was not shown" in flat and "non-public" in flat
    docs = " ".join((ROOT / "docs" / "engine.md").read_text(encoding="utf-8").split())
    assert "notice was not shown to anyone" in docs and "--variant tampered" in docs


# --- Task 9 (carried over): a folder that cannot be written to is named in plain words ----------------------------

def test_demo_on_a_read_only_folder_says_so_in_plain_words(tmp_path, capsys):
    with read_only_folder(tmp_path) as folder:
        for root in (folder, folder / "runs"):
            assert main(["demo", "--root", str(root)]) == 2
            out = last_json(capsys)
            assert out == {"error": f"The folder {folder} cannot be written to, "
                                    "so choose another folder for the run."}
        assert list(folder.iterdir()) == []


def test_demo_on_a_read_only_folder_prints_one_json_line_and_no_traceback(tmp_path):
    with read_only_folder(tmp_path) as folder:
        result = run_radar("demo", "--root", str(folder), home=tmp_path)
        assert result.returncode == 2 and result.stderr == "" and "Traceback" not in result.stdout
        lines = result.stdout.splitlines()
        assert len(lines) == 1 and "Errno" not in lines[0] and "--question" not in lines[0]


# --- Part A fix A2, item 8: each invented publisher of the demo has a site of its own -----------------------------

def test_each_invented_publisher_has_its_own_invented_site_under_the_reserved_ending(tmp_path):
    from radar import verify
    run = demo.build_demo_run(tmp_path, private=True, stage="sources")
    sources = store.read_sources(run)
    public = [source for source in sources.values() if source["data_class"] == "public"]
    sites = {source["publisher"]: verify.site_of(source["url"]) for source in public}
    assert len(public) == 6 and len(sites) == 6 and len(set(sites.values())) == 6
    assert all(site.endswith(".example") and site.count(".") == 1 for site in sites.values())
    # the two trade-press pieces come from two different outlets, so from two different sites
    trade = [source for source in public if source["type"] == "trade_press"]
    assert len(trade) == 2 and verify.site_of(trade[0]["url"]) != verify.site_of(trade[1]["url"])
    # no two public demo sources count as one site; the internal memo keeps its internal address
    assert all(verify._site(a) != verify._site(b) for a in public for b in public if a is not b)
    assert [source["url"] for source in sources.values() if source["data_class"] == "internal"] == [
        "internal://example-pharma/planning-note-2026-08"]


def test_the_demo_pack_points_to_the_same_invented_sites_as_the_demo(tmp_path):
    from fixtures.build_demo_run import _SOURCE_LIST
    places = json.loads((ROOT / "packs" / "demo.json").read_text(encoding="utf-8"))["places"]
    assert [place["url"] for place in places] == [spec["url"] for spec in _SOURCE_LIST]
    assert "example.com" not in json.dumps(places)


# --- ruling DH1: the demo's facts meet the plugin's own evidence rules ---------------------------------------------

# The checker judges these four from what the quotes say, not by their words: the kind of move, the stage, captive or
# open, and what became of the plan (point 3 of agents/support-checker.md); whether the move is inside the question
# is judged against the run's question.
JUDGED_BY_RULE = ("move_type", "stage", "access", "delivery", "in_question")
SILENT = (None, "", "not_stated", "unknown", "not_yet")            # the values that say the quotes are silent
NUMBER_WORDS = {"1": ("one", "single"), "2": ("two", "zwei"), "3": ("three", "drei")}
MONTHS = {"01": ("january", "januar"), "03": ("march", "märz"), "05": ("may", "mai"), "07": ("july", "juli"),
          "12": ("december", "dezember")}


def quoted_text(fact) -> str:
    """Every quote of a fact and its translation, as one text in lower case."""
    parts = [fact["quote"], fact["quote_translation"] or ""]
    for entry in fact["supporting"]:
        parts += [entry["quote"], entry.get("quote_translation") or ""]
    return " ".join(parts).casefold()


def date_stated(value: str, text: str) -> bool:
    """A date written as YYYY, YYYY-MM or YYYY-MM-DD is stated when its year, its month's name and its day stand in
    the text."""
    year, month, day = (value.split("-") + [None, None])[:3]
    return (year in text and (month is None or any(name in text for name in MONTHS[month]))
            and (day is None or f"{int(day)} " in text))


def stated(name: str, value: str, fact: dict, source: dict, text: str) -> bool:
    if name == "announced":   # point 3: stated by a quote, or the party's own statement's recorded date
        return (fact["primary_source"] is True and value == source["date"]) or date_stated(value, text)
    if name == "planned_start":
        return date_stated(value, text)
    if name == "size_value":
        return value in text or any(f" {word} " in f" {text} " for word in NUMBER_WORDS.get(value, ()))
    if name == "size_unit":   # one line is counted in lines
        return value in text or value.rstrip("s") in text
    return value.casefold() in text


def unstated_details(run, fact_ids=None) -> list:
    """(fact, field, value) for every filled detail no quote of the fact states: of the given facts, or of every
    capacity move the demo counts (confirmed or uncertain)."""
    facts, sources = store.read_facts(run), store.read_sources(run)
    missing = []
    for fact in facts.values():
        if fact["kind"] != "capacity_move":
            continue
        if (fact["id"] not in fact_ids) if fact_ids is not None else fact["status"] not in ("confirmed", "uncertain"):
            continue
        text = quoted_text(fact)
        for name, value in fact["fields"].items():
            if name not in JUDGED_BY_RULE and value not in SILENT and \
                    not stated(name, value, fact, sources[fact["source_id"]], text):
                missing.append((fact["id"], name, value))
    return missing


@pytest.mark.parametrize("variant", [{}, {"changed": True}])
def test_every_detail_of_a_fact_the_demo_counts_is_stated_by_one_of_its_quotes(tmp_path, variant):
    run = demo.build_demo_run(tmp_path, stage="checked", **variant)
    assert unstated_details(run) == []
    moves = [fact for fact in store.read_facts(run).values()
             if fact["kind"] == "capacity_move" and fact["status"] in ("confirmed", "uncertain")]
    assert len(moves) == 6 and sum(fact["status"] == "confirmed" for fact in moves) == 5


def test_the_check_of_the_details_finds_a_detail_no_quote_states(tmp_path):
    run = demo.build_demo_run(tmp_path, stage="checked")
    path = run / "facts" / "F2.json"
    fact = json.loads(path.read_text(encoding="utf-8"))
    fact["fields"].update(country="Country X", planned_start="2029-05")
    path.write_text(json.dumps(fact), encoding="utf-8")
    assert unstated_details(run) == [("F2", "country", "Country X"), ("F2", "planned_start", "2029-05")]


def test_details_stated_next_to_the_main_quote_are_covered_by_a_wider_quote_or_one_from_the_same_source(tmp_path):
    run = demo.build_demo_run(tmp_path, stage="extracted")
    facts = store.read_facts(run)
    assert "Plant North in Country X" in facts["F1"]["quote"]                    # F1: the main quote is widened
    for fact_id in ("F3", "F4"):                                                  # F3, F4: a quote from the same source
        own = [entry for entry in facts[fact_id]["supporting"] if entry["source_id"] == facts[fact_id]["source_id"]]
        assert own, fact_id
    assert any("prefilled syringes" in entry["quote"] for entry in facts["F3"]["supporting"])
    assert any("Site Y plant in Country Y" in entry["quote"] for entry in facts["F3"]["supporting"])


def test_the_plant_sale_rests_on_the_seller_s_report_and_an_independent_second_source(tmp_path):
    run = demo.build_demo_run(tmp_path)
    fact, sources = store.read_facts(run)["F6"], store.read_sources(run)
    assert sources[fact["source_id"]]["publisher"] == "Drug maker B"
    assert fact["primary_source"] is False                     # the seller's report is not the buyer's own statement
    assert fact["fields"]["announced"] == "not_stated"         # the quote dates the sale, not its announcement
    assert "Drug maker B says Competitor C will use the plant only for its own products" in fact["statement"]
    own, second = fact["supporting"]   # a quote of the seller's own report that names it, then the second source
    assert own["source_id"] == fact["source_id"] and "Drug maker B" in own["quote"]
    assert sources[second["source_id"]]["publisher"] not in ("Drug maker B", "Competitor C")
    assert (fact["status"], fact["status_reason"]) == ("confirmed", None)


def test_the_one_uncertain_fact_says_only_what_its_quote_says(tmp_path):
    run = demo.build_demo_run(tmp_path)
    fact = store.read_facts(run)["F7"]
    assert (fact["status"], fact["status_reason"]) == ("uncertain", "one unnamed source, not confirmed by the company")
    assert fact["primary_source"] is False and fact["certainty"] == "tentative" and fact["supporting"] == []
    fields = fact["fields"]
    assert fields["country"] is None and fields["site"] is None and fields["planned_start"] is None
    assert fields["announced"] == "not_stated" and fields["move_type"] == "partnership"
    assert "partnership" in fact["quote"] and "the person said" in fact["quote"]
    assert "could offer" in fact["statement"] and "A person quoted by a trade journal said" in fact["statement"]


def test_the_demo_s_places_are_plainly_invented():
    """DH1 follow-up: a dateline that matches real place names gives way to a name in the style of Country Y."""
    texts = {path.name: path.read_text(encoding="utf-8") for path in demo.SOURCES.rglob("*.txt")}
    assert not [name for name, text in texts.items() if "Harbour" in text]
    release = texts["s2_example_pharma_release.txt"]
    assert release.count("Town Y") == 3 and "Town Y, 2 July 2026." in release


F9_SUPPORTING = [{"source_id": "S2", "quote": "Example Pharma today confirmed that work has begun on a new sterile "
                                             "filling line at its Site Y plant in Country Y."},
                 {"source_id": "S2", "quote": "The new line is a single high-speed unit for prefilled syringes."},
                 {"source_id": "S2", "quote": "The line will be used only for Example Pharma's own products."}]


def test_the_three_planted_errors_are_proposed_as_ruled(tmp_path):
    """Ruling DH1: the planted errors keep their statements, main quotes and scripted notes. Ruling DH1c: F9 carries
    the same quotes from its own source and the same addition as F3, so the year is the one thing wrong with it."""
    run = demo.build_demo_run(tmp_path, stage="checked")
    facts = store.read_facts(run)
    wanted = {
        "F8": ("The three lines at Competitor B's Country Z site have a combined capacity of 54 million vials a year.",
               "The three lines have a combined capacity of 54 million vials a year.", "S3", [], None, None),
        "F9": ("Example Pharma's new line at Site Y is scheduled to start filling in 2029.",
               "Construction of the new line began in March 2026 and the line is scheduled to start filling in 2027.",
               "S2", F9_SUPPORTING,
               {"company": "Example Pharma", "move_type": "expansion", "site": "Site Y", "country": "Country Y",
                "what_added": "a single high-speed unit for prefilled syringes", "size_value": "1",
                "size_unit": "lines", "announced": "2026-07-02", "planned_start": "2029",
                "stage": "under_construction", "access": "captive", "delivery": "not_yet", "in_question": "yes"},
               "The quote says the line starts filling in 2027, but the fact says 2029."),
        "F10": ("Competitor A plans to offer its new filling lines to other drug makers.",
                "plan to offer the new lines to other drug makers", "S1", [], None,
                "The sentence around the quote says the opposite: Competitor A does not plan to offer the new lines."),
    }
    for fact_id, (statement, quote, source_id, supporting, fields, note) in wanted.items():
        fact = facts[fact_id]
        assert (fact["statement"], fact["quote"], fact["source_id"], fact["supporting"], fact["fields"]) == \
            (statement, quote, source_id, supporting, fields), fact_id
        assert fact["primary_source"] is True and fact["certainty"] == "firm", fact_id
        assert (fact["checks"]["support"] or {}).get("note") == note, fact_id
    assert facts["F9"]["fields"]["what_added"] == facts["F3"]["fields"]["what_added"]
    assert all(entry in facts["F9"]["supporting"] for entry in facts["F3"]["supporting"])


def test_the_year_is_the_one_detail_of_the_planted_year_error_that_its_quotes_do_not_state(tmp_path):
    run = demo.build_demo_run(tmp_path)
    assert unstated_details(run, ["F9"]) == [("F9", "planned_start", "2029")]
    fact = store.read_facts(run)["F9"]
    assert (fact["status"], fact["status_reason"]) == ("rejected", "not_supported")


# --- fix wave A23.1: the demo is built beside its place and moved there whole at the end -----------------------------

from radar.demo import build as demo_build   # noqa: E402


@pytest.mark.parametrize("variant, failing", [({}, "settle"), ({"private": True}, "mark"),
                                              ({"changed": True}, "add-fact")])
def test_a_demo_build_that_fails_half_way_leaves_nothing_behind(tmp_path, monkeypatch, variant, failing):
    real_radar, real_mark = demo_build._radar, store.mark_demo_run

    def radar(*argv, **kwargs):
        if argv[0] == failing:
            raise demo.DemoError(f"radar {failing} failed here, on purpose")
        return real_radar(*argv, **kwargs)

    def mark(run_dir):
        if failing == "mark":
            raise ValueError("the mark could not be written, on purpose")
        return real_mark(run_dir)

    monkeypatch.setattr(demo_build, "_radar", radar)
    monkeypatch.setattr(store, "mark_demo_run", mark)
    root = tmp_path / "runs"
    with pytest.raises((demo.DemoError, ValueError)):
        demo.build_demo_run(root, **variant)
    assert not root.exists() or list(root.iterdir()) == []


@pytest.mark.parametrize("stage", demo.STAGES)
def test_a_demo_build_leaves_only_its_run_folder_at_every_stage(tmp_path, stage):
    root = tmp_path / "runs"
    (root / "other").mkdir(parents=True)
    run = demo.build_demo_run(root, private=True, stage=stage)
    assert run == root / "demo-private" and sorted(p.name for p in root.iterdir()) == ["demo-private", "other"]
    assert store.load_run(run)["run_id"] == "demo-private"
    assert store.is_demo_private_run(store.load_run(run))       # never seen without its mark
    for source in store.read_sources(run).values():
        assert (run / source["copy_file"]).is_file()            # every path in it still holds after the move


# --- fix wave A23.15: the demo's outside views follow the analysis format, as the model run must -------------------

@pytest.mark.parametrize("variant", [{}, {"changed": True}, {"private": True}])
def test_every_outside_view_of_the_demo_rests_on_a_fact_or_says_none_found_and_claims_nothing(tmp_path, variant):
    run = demo.build_demo_run(tmp_path, **variant)
    facts = store.read_facts(run)
    for message in store.read_analysis(run)["messages"]:
        view = message["outside_view"]
        if view["fact_ids"]:
            assert all(facts[fact_id]["status"] in store.COUNTING for fact_id in view["fact_ids"]), message["id"]
        else:
            assert view["text"].startswith("None found:"), message["id"]
            for claim in ("usually", "often", "typically", "tend to", "most "):
                assert claim not in view["text"], (message["id"], claim)


# --- ruling FWB-1: a quote from another source states the fact's claim itself (the checker's point 9) ----------------

@pytest.mark.parametrize("variant", [{}, {"changed": True}, {"private": True}, {"tampered": True}])
def test_every_quote_the_demo_takes_from_another_source_names_the_company_and_what_is_added(tmp_path, variant):
    """What a program can see of point 9: the quote names the fact's company and the size words of what is added."""
    run = demo.build_demo_run(tmp_path, **variant)
    checked = []
    for fact in store.read_facts(run).values():
        for entry in fact["supporting"]:
            if entry["source_id"] == fact["source_id"]:
                continue                                              # a detail from the fact's own source
            fields = fact["fields"] or {}
            assert fact["kind"] == "capacity_move", fact["id"]
            for words in (fields["company"], fields["what_added"]):
                assert words in entry["quote"], (fact["id"], words, entry["quote"])
            checked.append(fields["what_added"])
    assert checked == ["two filling lines", "two filling lines"]      # Competitor A's Plant North, Competitor C's plant
    facts = store.read_facts(run)
    assert all(fact["checks"]["quote"]["passed"] for fact in facts.values()
               if fact["status"] != "rejected" or fact["status_reason"] != "not_found"), "every quote is still found"


# --- the new report: companies on general facts, one connection, and the moves grouped into projects ----------------

def test_the_demo_s_moves_are_grouped_into_projects(tmp_path):
    from radar import projects
    from radar.report.model import build_model
    run = demo.build_demo_run(tmp_path)
    grouped, state = projects.current(run)
    assert state == "grouped" and run_status(run)["grouping"] == "grouped"
    facts = store.read_facts(run)
    moves = {fact_id for fact_id, fact in facts.items()
             if fact["kind"] == "capacity_move" and fact["status"] in store.COUNTING}
    assert sorted(fact_id for project in grouped for fact_id in project["fact_ids"]) == sorted(moves)
    assert len(grouped) == 5 and len(moves) == 6                 # the plant sale and the rumour about it share one
    # the grouper's form of a name: "<company>, <site or programme>"
    assert all(re.fullmatch(r"(Competitor [A-D]|Example Pharma), .+", project["name"]) for project in grouped)
    model = build_model(run, demo.LENSES)
    assert model["projects"]["state"] == "grouped" and len(model["projects"]["items"]) == 5
    assert model["core_answer"]["total"] == 5


@pytest.mark.parametrize("stage", ["checked", "complete"])
def test_the_grouping_is_recorded_once_the_facts_are_final(tmp_path, stage):
    from radar import projects
    run = demo.build_demo_run(tmp_path, stage=stage)
    assert projects.current(run)[1] == "grouped"
    for stage_before in ("sources", "extracted"):
        assert projects.current(demo.build_demo_run(tmp_path / stage_before, stage=stage_before))[1] == "none"


@pytest.mark.parametrize("variant", [{"changed": True}, {"private": True}, {"tampered": True}])
def test_every_variant_of_the_demo_has_a_grouping_that_fits(tmp_path, variant):
    from radar import projects
    assert projects.current(demo.build_demo_run(tmp_path, **variant))[1] == "grouped"


def test_the_demo_shows_drug_maker_b_as_the_named_seller_to_competitor_c(tmp_path):
    from radar.report.model import build_model
    run = demo.build_demo_run(tmp_path)
    connections = build_model(run, demo.LENSES)["connections"]
    assert [(c["company"]["name"], c["party_name"], c["tie"], c["description"]) for c in connections] == \
        [("Competitor C", "Drug maker B", "seller", None)]
    assert connections[0]["party_name"] != connections[0]["company"]["name"]   # never a tie to the fact's own company
    assert "Drug maker B" in connections[0]["fact"]["statement"]


def test_the_demo_names_the_company_of_its_general_facts(tmp_path):
    from radar.report.model import build_model
    run = demo.build_demo_run(tmp_path)
    general = {fact_id: fact["about_company"] for fact_id, fact in store.read_facts(run).items()
               if fact["kind"] == "general"}
    assert sorted(name for name in general.values() if name) == ["Competitor A", "Competitor B", "Competitor B"]
    shown = [fact for fact in build_model(run, demo.LENSES)["facts"] if fact["kind"] == "general"]
    assert [(fact["statement"][:12], fact["company"]["name"]) for fact in shown] == [("Competitor B", "Competitor B")]
