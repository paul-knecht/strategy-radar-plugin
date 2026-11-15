"""The company pack: its format, the check that never raises, the time window and the command."""
import json
import re
from datetime import date
from pathlib import Path

import pytest

from fixtures.build_demo_run import QUESTION, _SOURCE_LIST
from radar import pack
from radar.cli import main
from radar.explain import explain
from radar.schema import Problem
from test_status import ENGINE, _messages_in

ROOT = Path(__file__).parent.parent
DEMO = ROOT / "packs" / "demo.json"
INVENTED = {"Example Pharma", "Competitor A", "Competitor B", "Competitor C", "Competitor D", "Drug maker B"}
CANDIDATE = {"name": "Competitor A", "status": "candidate", "suggested_by": "user"}
QUOTE = "We will add two lines at our own plant next year."
COMPANY_QUESTION = {"text": "Who is building?", "framing": "company",
                    "evidence": [{"url": "https://www.example.com/a", "quote": QUOTE}]}
LINE_SEPARATOR = chr(0x2028)
INVISIBLE = "".join(chr(code) for code in (0xAD, 0xA0, 0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF))


def write_pack(tmp_path, name="demo", **over):
    """A copy of the demo pack with keys replaced; a value of None for a key in `over` removes the key."""
    data = json.loads(DEMO.read_text(encoding="utf-8"))
    for key, value in over.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    path = Path(tmp_path) / f"{name}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def found(path):
    return [(p.field, p.message) for p in pack.check_pack(path)]


def run_command(capsys, *argv):
    code = main(list(argv))
    return code, json.loads(capsys.readouterr().out)


# --- the illustrative pack ----------------------------------------------------------------

def test_the_demo_pack_is_clean():
    assert pack.check_pack(DEMO) == []


def test_the_demo_pack_holds_what_the_brief_says():
    data = json.loads(DEMO.read_text(encoding="utf-8"))
    assert (data["id"], data["illustrative"], data["company"]) == ("demo", True, "Example Pharma")
    assert data["industry"] == "Filling of injectable medicines (invented)"
    assert data["strategic_questions"] == [
        {"text": QUESTION, "framing": "user", "framed_by": "The practice material (invented)"}]
    assert [c["name"] for c in data["competitors"]] == ["Competitor A", "Competitor B", "Competitor C"]
    assert [c["name"] for c in data["watch"]] == ["Competitor D", "Drug maker B"]
    assert all(c["status"] == "candidate" and c["suggested_by"] == "user"
               for c in data["competitors"] + data["watch"])
    assert data["units"] == ["lines"] and data["languages"] == ["en", "de"]
    assert len(data["demand_drivers"]) == 2 and data["time_window_months"] == 36


def test_the_demo_pack_has_one_place_for_each_public_source_of_the_demo():
    places = json.loads(DEMO.read_text(encoding="utf-8"))["places"]
    assert [place["url"] for place in places] == [source["url"] for source in _SOURCE_LIST]
    assert all(re.fullmatch(r"https://www\.[a-z-]+\.example/[a-z0-9/-]+", place["url"]) for place in places)


def test_the_demo_pack_names_only_invented_things_and_states_no_fact():
    text = DEMO.read_text(encoding="utf-8")
    data = json.loads(text)
    assert {data["company"], *(c["name"] for c in data["competitors"] + data["watch"])} <= INVENTED
    assert all("(invented)" in place["name"] for place in data["places"])
    assert all("(invented)" in driver for driver in data["demand_drivers"])
    assert not {"found_at", "evidence"} & {key for entry in data["competitors"] + data["watch"] for key in entry}
    assert not re.search(r"https?://(?!www\.[a-z-]+\.example/)", text)   # only the reserved, invented ending
    assert not any(character in text for character in INVISIBLE)


# --- the rules ----------------------------------------------------------------------------

def test_a_competitor_can_only_be_a_candidate(tmp_path):
    path = write_pack(tmp_path, competitors=[{**CANDIDATE, "status": "confirmed"}])
    assert found(path) == [("competitors[0].status", "a pack lists candidates only")]
    path = write_pack(tmp_path, watch=[{"name": "Competitor D", "suggested_by": "user"}])
    assert found(path) == [("watch[0].status", "a pack lists candidates only")]


def test_a_company_question_needs_a_quote_and_its_address(tmp_path):
    needs = "a question taken from the company needs a quote and its address"
    cases = [None, [], "text", [{"url": "https://www.example.com/a"}],
             [{"quote": QUOTE}],
             [{"url": "ftp://www.example.com/a", "quote": QUOTE}],
             [{"url": "https://", "quote": QUOTE}],
             [{"url": "https://www.example.com/a", "quote": "Too short."}],
             [{"url": "https://www.example.com/a", "quote": " ".join(["word"] * 51)}],
             ["https://www.example.com/a"]]
    for evidence in cases:
        question = {k: v for k, v in COMPANY_QUESTION.items() if k != "evidence"}
        if evidence is not None:
            question["evidence"] = evidence
        assert found(write_pack(tmp_path, strategic_questions=[question])) == [
            ("strategic_questions[0].evidence", needs)], evidence


def test_a_company_question_with_a_good_pointer_is_clean(tmp_path):
    assert found(write_pack(tmp_path, strategic_questions=[COMPANY_QUESTION])) == []
    exact = " ".join(["word"] * 50)
    good = {**COMPANY_QUESTION, "evidence": [{"url": "http://www.example.com/a", "quote": exact},
                                              {"url": "https://www.example.com/b", "quote": "one two three four five"}]}
    assert found(write_pack(tmp_path, strategic_questions=[good])) == []


def test_a_user_question_must_say_who_framed_it(tmp_path):
    must = "a question framed by the user must say who framed it"
    for framed_by in (None, "", "  ", 5):
        question = {"text": "Who is building?", "framing": "user"}
        if framed_by is not None:
            question["framed_by"] = framed_by
        assert found(write_pack(tmp_path, strategic_questions=[question])) == [
            ("strategic_questions[0].framed_by", must)], framed_by


def test_a_question_has_a_text_and_an_allowed_framing(tmp_path):
    path = write_pack(tmp_path, strategic_questions=[{"text": " ", "framing": "boss"}])
    assert found(path) == [("strategic_questions[0].text", pack.EMPTY),
                           ("strategic_questions[0].framing", pack.FRAMING_NOT_ALLOWED)]
    assert found(write_pack(tmp_path, strategic_questions=[])) == [("strategic_questions", pack.AT_LEAST_ONE)]


def test_a_name_found_by_search_needs_its_address(tmp_path):
    needs = "a name found by search needs the address where it was found"
    for extra in ({}, {"found_at": ""}, {"found_at": "example.com/page"}, {"found_at": 3}):
        path = write_pack(tmp_path, watch=[{**CANDIDATE, "suggested_by": "search", **extra}])
        assert found(path) == [("watch[0].found_at", needs)], extra
    good = {**CANDIDATE, "suggested_by": "search", "found_at": "https://www.example.com/page"}
    assert found(write_pack(tmp_path, watch=[good])) == []
    assert found(write_pack(tmp_path, watch=[{**CANDIDATE, "suggested_by": "guess"}])) == [
        ("watch[0].suggested_by", pack.SUGGESTED_BY_NOT_ALLOWED)]


def test_the_file_name_must_match_the_id(tmp_path):
    path = write_pack(tmp_path, name="other")
    assert found(path) == [("id", pack.ID_FILE)]
    for bad in ("Demo", "demo pharma", "demo_x", "-demo", "demo-", "-", "", None, 7):
        path = write_pack(tmp_path, id=bad)
        assert [field for field, _ in found(path)] == ["id"], bad
        assert found(path)[0][1] == pack.ID_FORMAT, bad
    assert found(write_pack(tmp_path, name="demo-2", id="demo-2")) == []
    assert found(write_pack(tmp_path, name="d", id="d")) == []


def test_a_broken_file_is_named_not_raised(tmp_path):
    path = tmp_path / "demo.json"
    cases = {b"": pack.NOT_READABLE, b"{not json": pack.NOT_READABLE, b"\xff\xfe\x00": pack.NOT_READABLE,
             b"[]": pack.NOT_SETTINGS, b"42": pack.NOT_SETTINGS, b"null": pack.NOT_SETTINGS,
             b'"text"': pack.NOT_SETTINGS, b"[" * 200000: pack.TOO_DEEP,
             b'{"company": "' + b"a" * 10 + b'\\ud800"}': pack.NOT_READABLE}
    for content, message in cases.items():
        path.write_bytes(content)
        assert found(path) == [(None, message)], content[:20]
    assert found(tmp_path / "missing.json") == [(None, pack.NOT_READABLE)]
    assert found(tmp_path) == [(None, pack.NOT_READABLE)]


def test_deep_nesting_inside_a_setting_is_named_not_raised(tmp_path):
    path = tmp_path / "demo.json"
    data = json.loads(DEMO.read_text(encoding="utf-8"))
    deep = "[" * 900 + "]" * 900
    path.write_text(json.dumps(data)[:-1] + ', "colour": ' + deep + "}", encoding="utf-8")
    assert found(path) == [("colour", pack.UNKNOWN_KEY)]


WRONG = [None, True, 0, 7, 2.5, "", "text", [], {}, [1], [[]], [None], [{}], {"a": 1}, ["x"], [{"name": 5}]]


@pytest.mark.parametrize("key", ["id", "company", "industry", "illustrative", "strategic_questions", "competitors",
                                 "watch", "places", "vocabulary", "units", "demand_drivers", "languages",
                                 "time_window_months"])
def test_no_value_of_the_wrong_kind_makes_the_check_raise(tmp_path, key):
    for value in WRONG:
        data = json.loads(DEMO.read_text(encoding="utf-8"))
        data[key] = value
        path = tmp_path / "demo.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        problems = pack.check_pack(path)
        assert all(isinstance(p, Problem) and isinstance(p.message, str) for p in problems)
        assert all(explain(p)["known"] for p in problems), (key, value)


@pytest.mark.parametrize("key", ["strategic_questions", "competitors", "watch", "places", "vocabulary"])
def test_an_entry_of_the_wrong_kind_is_named(tmp_path, key):
    for entry in (None, 5, "text", [], ["x"], {}):
        problems = found(write_pack(tmp_path, **{key: [entry]}))
        assert problems or key == "vocabulary" and entry == {}, (key, entry)
    assert found(write_pack(tmp_path, **{key: ["text"]})) == [(f"{key}[0]", pack.ENTRY_NOT_SETTINGS)]


def test_missing_and_wrong_settings_are_named(tmp_path):
    for key in ("company", "industry"):
        assert found(write_pack(tmp_path, **{key: None})) == [(key, pack.EMPTY)]
        assert found(write_pack(tmp_path, **{key: "  "})) == [(key, pack.EMPTY)]
    assert found(write_pack(tmp_path, illustrative="yes")) == [("illustrative", pack.ILLUSTRATIVE_NOT_ALLOWED)]
    assert found(write_pack(tmp_path, illustrative=None)) == [("illustrative", pack.ILLUSTRATIVE_NOT_ALLOWED)]
    for key in ("strategic_questions", "competitors", "watch", "places", "units", "demand_drivers", "languages"):
        assert found(write_pack(tmp_path, **{key: None})) == [(key, pack.NOT_LIST)]
        assert found(write_pack(tmp_path, **{key: "text"})) == [(key, pack.NOT_LIST)]
    assert found(write_pack(tmp_path, vocabulary="text")) == [("vocabulary", pack.NOT_LIST)]
    assert found(write_pack(tmp_path, vocabulary=None)) == []   # optional


def test_lists_that_may_be_empty_and_lists_that_may_not(tmp_path):
    assert found(write_pack(tmp_path, competitors=[], watch=[], units=[], demand_drivers=[], vocabulary=[])) == []
    assert found(write_pack(tmp_path, places=[])) == [("places", pack.AT_LEAST_ONE)]
    assert found(write_pack(tmp_path, languages=[])) == [("languages", pack.AT_LEAST_ONE)]


def test_lists_of_text_hold_text(tmp_path):
    assert found(write_pack(tmp_path, units=["lines", 5])) == [("units[1]", pack.NOT_TEXT)]
    assert found(write_pack(tmp_path, demand_drivers=[["x"]])) == [("demand_drivers[0]", pack.NOT_TEXT)]
    assert found(write_pack(tmp_path, languages=["en", " "])) == [("languages[1]", pack.EMPTY)]


def test_places_need_an_allowed_kind_a_name_and_an_address(tmp_path):
    place = {"kind": "press_room", "name": "A press room (invented)", "url": "https://www.example.com/x"}
    assert found(write_pack(tmp_path, places=[place])) == []
    assert found(write_pack(tmp_path, places=[{**place, "kind": "rumours"}])) == [("places[0].kind", pack.KIND_NOT_ALLOWED)]
    assert found(write_pack(tmp_path, places=[{**place, "name": ""}])) == [("places[0].name", pack.EMPTY)]
    assert found(write_pack(tmp_path, places=[{"kind": "filings", "name": "x"}])) == [("places[0].url", pack.PLACE_ADDRESS)]
    for kind in pack.PLACE_KINDS:
        assert found(write_pack(tmp_path, places=[{**place, "kind": kind}])) == []


def test_the_place_kinds_are_the_ones_the_design_names():
    assert pack.PLACE_KINDS == ("investor_relations", "press_room", "filings", "annual_reports", "regulator",
                                "trade_press", "permits", "job_postings")


def test_vocabulary_entries_need_a_term_and_a_meaning(tmp_path):
    assert found(write_pack(tmp_path, vocabulary=[{"term": "a term", "meaning": "what it means"}])) == []
    assert found(write_pack(tmp_path, vocabulary=[{"term": "a term"}])) == [("vocabulary[0].meaning", pack.EMPTY)]


def test_unknown_settings_are_named_everywhere(tmp_path):
    assert found(write_pack(tmp_path, colour="red")) == [("colour", pack.UNKNOWN_KEY)]
    path = write_pack(tmp_path, competitors=[{**CANDIDATE, "size": 5}], places=[
        {"kind": "press_room", "name": "n", "url": "https://www.example.com/u", "extra": 1}],
        strategic_questions=[{"text": "t", "framing": "user", "framed_by": "me", "x": 1}])
    assert sorted(found(path)) == sorted([("competitors[0].size", pack.UNKNOWN_KEY), ("places[0].extra", pack.UNKNOWN_KEY),
                                           ("strategic_questions[0].x", pack.UNKNOWN_KEY)])
    odd = {**COMPANY_QUESTION, "evidence": [{"url": "https://www.example.com/a", "x": 1, "quote": QUOTE}]}
    assert found(write_pack(tmp_path, strategic_questions=[odd])) == [
        ("strategic_questions[0].evidence[0].x", pack.UNKNOWN_KEY)]


def test_problems_come_in_the_order_of_the_format(tmp_path):
    path = write_pack(tmp_path, languages=[], company="", time_window_months=0, colour=1)
    assert [field for field, _ in found(path)] == ["company", "languages", "time_window_months", "colour"]


# --- the time window ------------------------------------------------------------------------

def test_the_window_defaults_to_36_months_when_the_pack_has_none(tmp_path):
    data = json.loads(DEMO.read_text(encoding="utf-8"))
    del data["time_window_months"]
    assert pack.months_of(data) == 36 and pack.DEFAULT_MONTHS == 36
    assert found(write_pack(tmp_path, time_window_months=None)) == []


def test_the_pack_time_window_must_be_a_whole_number_from_1_to_120(tmp_path):
    message = "must be a whole number from 1 to 120"
    for bad in (0, -3, 121, 2.5, 36.0, "36", True, False, None, [36], {}):
        data = json.loads(DEMO.read_text(encoding="utf-8"))
        data["time_window_months"] = bad
        assert pack.months_of(data) is None, bad
        path = tmp_path / "demo.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        assert found(path) == [("time_window_months", message)], bad
    for good in (1, 12, 120):
        assert found(write_pack(tmp_path, time_window_months=good)) == []


def test_the_window_defaults_to_36_months():
    assert pack.window(36, date(2026, 11, 12)) == {"months": 36, "from": "2023-11-12", "until": "2026-11-12"}


def test_the_window_handles_the_end_of_a_month():
    assert pack.window(1, date(2026, 3, 31))["from"] == "2026-02-28"
    assert pack.window(1, date(2028, 3, 31))["from"] == "2028-02-29"
    assert pack.window(12, date(2028, 2, 29))["from"] == "2027-02-28"
    assert pack.window(3, date(2026, 1, 31))["from"] == "2025-10-31"
    assert pack.window(14, date(2026, 1, 15))["from"] == "2024-11-15"
    assert pack.window(120, date(2026, 11, 12))["from"] == "2016-11-12"


def test_the_window_refuses_what_is_not_a_positive_whole_number():
    for bad in (0, -1, 2.5, "3", True, None):
        with pytest.raises(ValueError):
            pack.window(bad, date(2026, 11, 12))


# --- the command ----------------------------------------------------------------------------

def test_check_pack_command_prints_the_window(capsys):
    code, out = run_command(capsys, "check-pack", "--file", str(DEMO), "--today", "2026-11-12")
    assert code == 0 and out == {
        "problems": [], "explained": [],
        "pack": {"id": "demo", "company": "Example Pharma", "illustrative": True},
        "window": {"months": 36, "from": "2023-11-12", "until": "2026-11-12"}}


def test_check_pack_command_uses_the_window_of_the_pack(tmp_path, capsys):
    path = write_pack(tmp_path, time_window_months=12)
    code, out = run_command(capsys, "check-pack", "--file", str(path), "--today", "2026-03-31")
    assert code == 0 and out["window"] == {"months": 12, "from": "2025-03-31", "until": "2026-03-31"}


def test_check_pack_command_explains_each_problem_in_pack_words(tmp_path, capsys):
    path = write_pack(tmp_path, competitors=[{**CANDIDATE, "status": "confirmed"}])
    code, out = run_command(capsys, "check-pack", "--file", str(path), "--today", "2026-11-12")
    assert code == 1 and len(out["problems"]) == len(out["explained"]) == 1
    assert out["problems"][0] == {"file": "demo.json", "field": "competitors[0].status",
                                  "message": "a pack lists candidates only"}
    assert out["explained"][0]["known"] is True and "pack" in out["explained"][0]["what"].lower()
    assert out["pack"]["company"] == "Example Pharma" and out["window"]["months"] == 36


def test_check_pack_command_gives_no_pack_and_no_window_for_an_unreadable_file(tmp_path, capsys):
    path = tmp_path / "demo.json"
    path.write_text("", encoding="utf-8")
    code, out = run_command(capsys, "check-pack", "--file", str(path), "--today", "2026-11-12")
    assert code == 1 and out["pack"] is None and out["window"] is None
    assert out["problems"] == [{"file": "demo.json", "field": None, "message": pack.NOT_READABLE}]
    assert out["explained"][0]["known"] is True
    code, out = run_command(capsys, "check-pack", "--file", str(tmp_path / "gone.json"))   # no file: wrong use
    assert code == 2 and out == {"error": f"{tmp_path / 'gone.json'} does not exist. Give the path of a file."}


def test_check_pack_command_gives_no_window_when_the_months_are_refused(tmp_path, capsys):
    path = write_pack(tmp_path, time_window_months=0)
    code, out = run_command(capsys, "check-pack", "--file", str(path), "--today", "2026-11-12")
    assert code == 1 and out["window"] is None and out["pack"]["id"] == "demo"


def test_check_pack_command_echoes_only_what_it_can_print_on_one_line(tmp_path, capsys):
    path = write_pack(tmp_path, company="Odd " + LINE_SEPARATOR + " name", id=7)
    code, out = run_command(capsys, "check-pack", "--file", str(path), "--today", "2026-11-12")
    assert code == 1 and out["pack"] == {"id": None, "company": "Odd " + LINE_SEPARATOR + " name", "illustrative": True}


def test_check_pack_command_takes_its_options_from_json(tmp_path, capsys):
    options = tmp_path / "options.json"
    options.write_text(json.dumps({"file": str(DEMO), "today": "2026-11-12"}), encoding="utf-8")
    code, out = run_command(capsys, "check-pack", "--from-json", str(options))
    assert code == 0 and out["window"]["until"] == "2026-11-12"


def test_check_pack_command_is_used_wrongly_without_a_file_or_with_a_bad_date(capsys):
    assert run_command(capsys, "check-pack")[0] == 2
    assert run_command(capsys, "check-pack", "--file", str(DEMO), "--today", "tomorrow")[0] == 2
    assert run_command(capsys, "check-pack", "--file", str(DEMO), "--today", "0001-01-01")[0] == 2   # no date 36 months earlier


def test_check_pack_command_changes_nothing(tmp_path, capsys):
    path = write_pack(tmp_path)
    before = path.read_bytes()
    run_command(capsys, "check-pack", "--file", str(path), "--today", "2026-11-12")
    assert path.read_bytes() == before and sorted(p.name for p in tmp_path.iterdir()) == ["demo.json"]


# --- the explanations -----------------------------------------------------------------------

def pack_messages():
    return _messages_in(ENGINE / "pack.py")


def test_the_code_reading_helper_finds_the_pack_messages():
    found_in_code = pack_messages()
    assert len(found_in_code) == 22
    for expected in ("a pack lists candidates only", "must be a whole number from 1 to 120", pack.NOT_READABLE,
                     pack.EMPTY, pack.UNKNOWN_KEY, pack.ID_FILE):
        assert expected in found_in_code


def test_every_pack_message_is_explained():
    entries = json.loads((ENGINE / "explanations_en.json").read_text(encoding="utf-8"))
    for message in sorted(pack_messages()):
        e = explain(Problem("demo.json", None, message))
        assert e["known"], message
        own = {part: text.replace("{field}", "this setting") for part, text in entries[message].items()}
        assert e == {"known": True, **own}, message   # its own entry, not a shorter one it contains


def test_the_pack_explanations_speak_of_the_pack_and_not_of_a_run():
    entries = json.loads((ENGINE / "explanations_en.json").read_text(encoding="utf-8"))
    for message in pack_messages():
        text = " ".join(entries[message].values()).lower()
        assert "pack" in text, message
        assert not re.search(r"this run|saved item|\banalysis\b|\breports?\b|\{id\}|\{value\}", text), message
    assert len({entries[message]["what"] for message in pack_messages()}) == len(pack_messages())


# --- fix round 1: web addresses -----------------------------------------------------------------

BAD_ADDRESSES = ["file:///etc/passwd", "ftp://www.example.com/a", "x", "https://user:pw@www.example.com/a",
                 "https://user@www.example.com/a", "https://:pw@www.example.com/a", "javascript:alert(1)",
                 "https:///a", "https://www.example.com/a b", "www.example.com/a",
                 "https://www.example.com/a" + chr(0), "https://www.example.com/a" + chr(127),
                 "https://www.example.com/" + chr(1) + "a", "https://www.example.com:abc/a",
                 "https://www.example.com:99999/a", "https://www.example.com:0/a", "https://www.example.com:65536/a"]
GOOD_ADDRESSES = ["http://www.example.com/a", "https://www.example.com/a?x=1#y", "https://www.example.com:8443/a@b",
                  "https://www.example.com:1/a", "https://www.example.com:65535/a", "https://[::1]:8080/a"]


def _with_address(field, address, tmp_path):
    if field == "place":
        place = {"kind": "press_room", "name": "A press room (invented)", "url": address}
        return write_pack(tmp_path, places=[place]), "places[0].url", pack.PLACE_ADDRESS
    if field == "found_at":
        entry = {**CANDIDATE, "suggested_by": "search", "found_at": address}
        return write_pack(tmp_path, watch=[entry]), "watch[0].found_at", pack.SEARCH_NEEDS_ADDRESS
    question = {**COMPANY_QUESTION, "evidence": [{"url": address, "quote": QUOTE}]}
    return write_pack(tmp_path, strategic_questions=[question]), "strategic_questions[0].evidence", pack.COMPANY_NEEDS_QUOTE


@pytest.mark.parametrize("field", ["place", "found_at", "evidence"])
def test_a_web_address_is_http_or_https_with_a_host_and_no_password(tmp_path, field):
    for address in BAD_ADDRESSES + ["", None, 5]:
        path, where, message = _with_address(field, address, tmp_path)
        assert found(path) == [(where, message)], address
    for address in GOOD_ADDRESSES:
        path, _, _ = _with_address(field, address, tmp_path)
        assert found(path) == [], address


def test_the_place_address_message_is_the_one_the_review_asked_for():
    assert pack.PLACE_ADDRESS == "a place to look needs a web address starting with http or https and holding no password"


# --- fix round 1: explanations a first-time author can act on -----------------------------------

def entries():
    return json.loads((ENGINE / "explanations_en.json").read_text(encoding="utf-8"))


def shown(e):
    """The three parts of an explanation as one text."""
    return " ".join(e[part] for part in ("what", "why", "do"))


def test_each_value_that_is_not_allowed_has_its_own_message_and_names_the_choices():
    from radar.store import FRAMING
    split = {pack.FRAMING_NOT_ALLOWED: FRAMING, pack.SUGGESTED_BY_NOT_ALLOWED: pack.SUGGESTED_BY,
             pack.ILLUSTRATIVE_NOT_ALLOWED: ("true", "false"), pack.KIND_NOT_ALLOWED: pack.PLACE_KINDS}
    assert len(split) == 4 and not hasattr(pack, "NOT_ALLOWED")
    for message, choices in split.items():
        e = explain(Problem("demo.json", "x", message))
        assert e == {"known": True, **entries()[message]}, message
        for choice in choices:
            assert choice in e["do"], (message, choice)


def test_the_generic_pack_explanations_name_the_setting_they_are_about():
    cases = {pack.EMPTY: "company", pack.AT_LEAST_ONE: "places", pack.NOT_LIST: "competitors",
             pack.NOT_TEXT: "units[1]", pack.ENTRY_NOT_SETTINGS: "watch[2]", pack.UNKNOWN_KEY: "colour"}
    for message, field in cases.items():
        e = explain(Problem("demo.json", field, message))
        assert e["known"] and field in e["what"] and not re.search(r"[{}]", shown(e)), message
        assert field not in explain(Problem("demo.json", "other", message))["what"]


def test_a_pack_problem_without_a_setting_name_still_reads_well():
    for message in (pack.EMPTY, pack.AT_LEAST_ONE, pack.NOT_LIST, pack.NOT_TEXT, pack.ENTRY_NOT_SETTINGS, pack.UNKNOWN_KEY):
        for field in (None, "", 7, ["x"]):
            e = explain(Problem("demo.json", field, message))
            assert e["known"] and "this setting" in e["what"] and not re.search(r"[{}]", shown(e)), (message, field)


def test_every_pack_explanation_fills_in_cleanly_for_every_message():
    for message in pack_messages():
        for field in (None, "company", "places[0].url"):
            e = explain(Problem("demo.json", field, message))
            assert e["known"] and not re.search(r"[{}]", shown(e))


def test_the_file_name_explanation_says_how_to_name_the_pack():
    e = explain(Problem("demo.json", "id", pack.ID_FILE))
    assert "named the id followed by .json" in e["do"]
    assert not re.search(r"\brun\b|program", e["what"] + e["why"] + e["do"], re.IGNORECASE)


def test_the_company_question_explanation_gives_the_whole_rule():
    e = explain(Problem("demo.json", "strategic_questions[0].evidence", pack.COMPANY_NEEDS_QUOTE))
    assert "no usable quote and address" in e["what"]
    assert "5 to 50 words" in e["do"] and "http or https" in e["do"] and "user" in e["do"]
    assert "no user name or password" in shown(e)


def test_the_address_explanations_say_no_user_name_or_password():
    for message in (pack.SEARCH_NEEDS_ADDRESS, pack.COMPANY_NEEDS_QUOTE, pack.PLACE_ADDRESS):
        text = shown(explain(Problem("demo.json", "x", message)))
        assert "http or https" in text and re.search(r"no (?:user name or )?password", text), message


def test_the_list_explanation_names_the_lists_that_may_be_empty():
    e = explain(Problem("demo.json", "units", pack.NOT_LIST))
    for name in ("competitors", "watch", "units", "demand drivers", "vocabulary"):
        assert name in e["do"], name


def test_the_demand_drivers_are_plainly_hypothetical_and_tied_to_the_invented_company():
    drivers = json.loads(DEMO.read_text(encoding="utf-8"))["demand_drivers"]
    assert all(driver.startswith("Example driver (invented): ") and "Example Pharma" in driver for driver in drivers)


# --- fix round 2: every evidence address is checked, whatever the framing -------------------------

def _user_question(**over):
    return {"text": "Who is building?", "framing": "user", "framed_by": "me", **over}


def test_the_evidence_address_message_is_worded_like_the_place_address_message():
    assert pack.EVIDENCE_ADDRESS == "an evidence address needs a web address starting with http or https and holding no password"


def test_an_evidence_address_on_a_user_question_is_checked(tmp_path):
    for address in ("file:///x", "ftp://example.com/a", "x", "https://u:p@example.com/a", "", None, 5):
        question = _user_question(evidence=[{"url": address}])
        assert found(write_pack(tmp_path, strategic_questions=[question])) == [
            ("strategic_questions[0].evidence[0].url", pack.EVIDENCE_ADDRESS)], address
    second = _user_question(evidence=[{"url": "https://example.com/a"}, {"url": "ftp://example.com/b"}])
    assert found(write_pack(tmp_path, strategic_questions=[second])) == [
        ("strategic_questions[0].evidence[1].url", pack.EVIDENCE_ADDRESS)]


def test_good_or_no_evidence_on_a_user_question_is_clean(tmp_path):
    good = _user_question(evidence=[{"url": "https://example.com/a"}])
    assert found(write_pack(tmp_path, strategic_questions=[good])) == []
    with_quote = _user_question(evidence=[{"url": "https://example.com/a", "quote": "short"}])
    assert found(write_pack(tmp_path, strategic_questions=[with_quote])) == []   # no quote is demanded here
    assert found(write_pack(tmp_path, strategic_questions=[_user_question()])) == []
    assert found(write_pack(tmp_path, strategic_questions=[_user_question(evidence=[])])) == []


def test_evidence_of_the_wrong_kind_on_a_user_question_is_named_not_raised(tmp_path):
    for evidence in (None, "text", 5, {"url": "https://example.com/a"}, True):
        question = _user_question(evidence=evidence)
        assert found(write_pack(tmp_path, strategic_questions=[question])) == [
            ("strategic_questions[0].evidence", pack.NOT_LIST)], evidence
    for item in (None, 5, "https://example.com/a", ["x"], []):
        question = _user_question(evidence=[item])
        assert found(write_pack(tmp_path, strategic_questions=[question])) == [
            ("strategic_questions[0].evidence[0]", pack.ENTRY_NOT_SETTINGS)], item
    odd = _user_question(evidence=[{"url": "https://example.com/a", "x": 1}])
    assert found(write_pack(tmp_path, strategic_questions=[odd])) == [
        ("strategic_questions[0].evidence[0].x", pack.UNKNOWN_KEY)]


def test_evidence_is_also_checked_when_the_framing_is_not_allowed(tmp_path):
    question = {"text": "t", "framing": "boss", "evidence": [{"url": "ftp://example.com/a"}]}
    assert found(write_pack(tmp_path, strategic_questions=[question])) == [
        ("strategic_questions[0].framing", pack.FRAMING_NOT_ALLOWED),
        ("strategic_questions[0].evidence[0].url", pack.EVIDENCE_ADDRESS)]


def test_the_evidence_address_explanation_gives_the_whole_rule():
    e = explain(Problem("demo.json", "strategic_questions[0].evidence[0].url", pack.EVIDENCE_ADDRESS))
    assert e == {"known": True, **entries()[pack.EVIDENCE_ADDRESS]}
    assert "http or https" in e["do"] and "no user name or password" in e["do"] and "leave the evidence out" in e["do"]


# --- fix round 2: the words when a problem names no setting -----------------------------------

def test_the_templates_read_as_sentences_when_the_problem_names_no_setting():
    for message in (pack.EMPTY, pack.AT_LEAST_ONE, pack.NOT_LIST, pack.NOT_TEXT, pack.ENTRY_NOT_SETTINGS, pack.UNKNOWN_KEY):
        for field in (None, ""):
            text = shown(explain(Problem("demo.json", field, message)))
            assert "this setting" in text and "a setting" not in text, text
            assert not re.search(r"\bsetting (?:this|a)\b|\b(?:this|a) setting (?:this|a)\b|\bthis setting this\b", text), text
        named = shown(explain(Problem("demo.json", "units[1]", message)))
        assert "units[1]" in named and "this setting" not in named, named


# --- Part A fix A2, item 3: one address rule for the pack and the download ---------------------------------------

DISAGREED = ["https://b" + chr(0xFC) + "cher.example/a",    # a site name with a non-ASCII letter
             "https://exa%6dple.example/a",                  # a percent sign in the site name
             "https://site_a.example/a",                     # an underscore in the site name
             "https://./a",                                  # the name "."
             "https://www.site-a.example:0/a",               # port 0
             "https://www.site-a.example:99999/a"]           # a port above 65535


def _form_check_accepts(address):
    from radar import fetch
    try:
        fetch.check_url(address)
    except ValueError:
        return False
    return True


@pytest.mark.parametrize("address", DISAGREED)
def test_the_rows_the_two_checks_disagreed_on_are_refused_by_both(tmp_path, capsys, monkeypatch, address):
    from radar import fetch

    def no_lookup(host, *args, **kwargs):
        raise AssertionError(f"{host} was looked up")

    monkeypatch.setattr(fetch, "check_address", no_lookup)   # a test never asks the network about a name
    place = {"kind": "press_room", "name": "A press room (invented)", "url": address}
    path = write_pack(tmp_path, places=[place])
    code, out = run_command(capsys, "check-pack", "--file", str(path))
    assert (code, [(p["field"], p["message"]) for p in out["problems"]]) == (1, [("places[0].url", pack.PLACE_ADDRESS)])
    assert _form_check_accepts(address) is False
    run = tmp_path / "runs" / "r1"
    assert main(["init-run", "--root", str(tmp_path / "runs"), "--question", "Q", "--pack", "demo",
                 "--run-id", "r1"]) == 0
    capsys.readouterr()
    code, out = run_command(capsys, "save-source", "--run", str(run), "--url", address, "--publisher", "P",
                            "--title", "T", "--date", "2026-05-14", "--type", "other", "--speaker", "S",
                            "--interest", "I", "--language", "en")
    assert code == 2 and list(out) == ["error"]   # refused by the form check, before anything is looked up or saved
    assert sorted(path.name for path in (run / "sources").iterdir()) == []


@pytest.mark.parametrize("address", BAD_ADDRESSES + GOOD_ADDRESSES + DISAGREED + [
    "http://www.site-a.example./x", "http://WWW.Site-A.example/x", "https://127.0.0.1/x", "https://[2001:db8::1]/x",
    "https://www.site-a.example:65535/x", "https://www.site-a.example:1/x", "https://www.site-a.example/a@b",
    "https://exa mple.example/a", "https://[::1%25en0]/x", "https://[127.0.0.1]/x"])
def test_the_pack_check_and_the_form_check_of_the_download_give_the_same_verdict(tmp_path, address):
    place = {"kind": "press_room", "name": "A press room (invented)", "url": address}
    assert (found(write_pack(tmp_path, places=[place])) == []) is _form_check_accepts(address), address


def test_the_form_check_refuses_a_port_outside_1_to_65535_in_plain_words():
    from radar import fetch
    for port in ("0", "65536", "99999", "00000"):
        with pytest.raises(ValueError) as caught:
            fetch.check_url(f"https://www.site-a.example:{port}/a")
        assert str(caught.value) == "the port of the address must be a number from 1 to 65535", port
    for port in ("1", "443", "65535", "08080"):
        fetch.check_url(f"https://www.site-a.example:{port}/a")


@pytest.mark.parametrize("order", [("radar.pack", "radar.fetch"), ("radar.fetch", "radar.pack"),
                                   ("radar.schema", "radar.pack"), ("radar.pack", "radar.cli")])
def test_the_pack_and_the_download_import_in_either_order_in_a_fresh_interpreter(order):
    import os
    import subprocess
    import sys
    code = "import importlib, sys\nfor name in sys.argv[1:]:\n    importlib.import_module(name)\n"
    result = subprocess.run([sys.executable, "-c", code, *order], capture_output=True, text=True,
                            env={**os.environ, "PYTHONPATH": str(ROOT / "engine")})
    assert (result.returncode, result.stderr) == (0, ""), order


# --- A2 fix round 2, point 6: a missing pack file is wrong use now, so the explanation no longer names it ------------

def test_the_explanation_of_a_pack_that_cannot_be_read_says_what_can_still_happen():
    entry = json.loads((ENGINE / "explanations_en.json").read_text(encoding="utf-8"))[pack.NOT_READABLE]
    assert "missing" not in " ".join(entry.values()).lower()
    assert entry == {"what": "The company pack cannot be read.",
                     "why": ("The file is empty or damaged, often after a manual edit, so it no longer holds a set "
                             "of named settings that can be read."),
                     "do": "Restore the pack from a backup, or start again from the demo pack."}


# --- fix wave A19: naming a shipped invented pack by --pack reads its file, so the run is marked illustrative --------

from radar import store   # noqa: E402

def _started(capsys, tmp_path, *more):
    code = main(["init-run", "--root", str(tmp_path / "runs"), "--question", "Q", *more])
    return code, json.loads(capsys.readouterr().out)


def test_a_shipped_pack_named_by_its_name_makes_the_run_illustrative_as_its_file_does(tmp_path, capsys):
    code, out = _started(capsys, tmp_path, "--pack", "demo", "--run-id", "by-name")
    assert code == 0
    by_name = store.load_run(Path(out["run_dir"]))
    code, out = _started(capsys, tmp_path, "--pack-file", str(ROOT / "packs" / "demo.json"), "--run-id", "by-file")
    by_file = store.load_run(Path(out["run_dir"]))
    assert (by_name["pack"], by_name["illustrative"]) == (by_file["pack"], by_file["illustrative"]) == ("demo", True)


@pytest.mark.parametrize("name", ["acme-made-up", "Demo", "DEMO", "demo.json", "../packs/demo", "packs/demo", " demo",
                                  "demo "])
def test_a_name_that_is_not_a_shipped_pack_is_recorded_as_written_and_checks_nothing(tmp_path, capsys, name):
    code, out = _started(capsys, tmp_path, "--pack", name, "--run-id", "r1")
    assert code == 0
    record = store.load_run(Path(out["run_dir"]))
    assert (record["pack"], record["illustrative"]) == (name, False)


def test_a_shipped_pack_with_a_problem_named_by_its_name_starts_no_run(tmp_path, capsys, monkeypatch):
    from radar import cli
    shipped = tmp_path / "shipped"
    shipped.mkdir()
    (shipped / "broken.json").write_text('{"id": "broken"}', encoding="utf-8")
    monkeypatch.setattr(cli, "SHIPPED_PACKS", shipped)
    code, out = _started(capsys, tmp_path, "--pack", "broken", "--run-id", "r1")
    assert code == 1 and out["problems"] and out["explained"]
    assert not (tmp_path / "runs").exists()


def test_a_pack_name_too_long_for_a_file_name_is_recorded_as_written(tmp_path, capsys):
    """Ruling FWA-5b: an error of the look-up means no shipped pack of that name, never a raw system error."""
    name = "a" * 300                                        # a plain pack id, but too long for a file name
    code, out = _started(capsys, tmp_path, "--pack", name, "--run-id", "r1")
    assert code == 0
    record = store.load_run(Path(out["run_dir"]))
    assert (record["pack"], record["illustrative"]) == (name, False)


def test_the_shipped_packs_are_the_plugin_s_own_folder():
    from radar import cli
    assert cli.SHIPPED_PACKS == ROOT / "packs" and (cli.SHIPPED_PACKS / "demo.json").is_file()
