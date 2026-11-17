"""Splitting a helper's input into parts that each fit what its Bash tool can read. Everything here is invented."""
import json

from radar import demo, parts, recommend
from radar.explain import explain
from radar.schema import Problem
from helpers import add_fact, add_source, finish_run, make_run


def test_the_limit():
    assert parts.PART_LIMIT == 20000


def test_parts_hold_whole_items_under_the_limit():
    items = [("facts", {"id": f"F{i}", "statement": "x" * 900}) for i in range(60)]
    ps = parts.split({"question": "Q"}, items, limit=20000)
    assert len(ps) > 1
    assert all(len(json.dumps(p)) < 20000 for p in ps)
    assert [f["id"] for p in ps for f in p.get("facts", [])] == [f"F{i}" for i in range(60)]
    assert ps[0]["question"] == "Q" and "question" not in ps[1]
    assert {p["parts"] for p in ps} == {len(ps)} and [p["part"] for p in ps] == list(range(1, len(ps) + 1))


def test_an_item_larger_than_the_limit_gets_a_part_of_its_own():
    big = ("lenses", {"id": "big", "idea": "y" * 25000})
    ps = parts.split({}, [("lenses", {"id": "a"}), big, ("lenses", {"id": "b"})], limit=20000)
    assert [[l["id"] for l in p["lenses"]] for p in ps] == [["a"], ["big"], ["b"]]


def test_the_head_comes_first_then_the_part_numbers_then_the_lists_in_their_order():
    ps = parts.split({"question": "Q", "frame": None}, [("lenses", {"id": "a"}), ("facts", {"id": "F1"})])
    assert ps == [{"question": "Q", "frame": None, "part": 1, "parts": 1, "lenses": [{"id": "a"}],
                   "facts": [{"id": "F1"}]}]


def test_no_items_give_one_part_with_the_head():
    assert parts.split({"question": "Q"}, []) == [{"question": "Q", "part": 1, "parts": 1}]


def test_text_outside_ascii_is_measured_as_it_could_be_printed():
    items = [("facts", {"id": f"F{i}", "statement": "\u2028\u00e9\U0001F600" * 300}) for i in range(40)]
    for p in parts.split({}, items, limit=20000):
        assert len(json.dumps(p)) < 20000
        assert len((json.dumps(p, ensure_ascii=False) + "\n").encode("utf-8")) <= 20000


def test_a_missing_part_is_explained():
    message = parts.no_such_part(99, 3)
    assert "99" in message and "3 parts" in message
    entry = explain(Problem("run.json", None, message))
    assert entry["known"] is True


def many_facts_run(tmp_path, count=120):
    quotes = [f"Move number {number} adds a filling line." for number in range(1, count + 1)]
    run = make_run(tmp_path)
    add_source(run, " ".join(quotes), publisher="Competitor A", date="2026-05-14")
    for quote in quotes:
        add_fact(run, source_id="S1", primary_source=True, quote=quote,
                 statement=f"Competitor A adds a filling line ({quote[:15].strip()}).")
    finish_run(run, ["F1"], lens_id="firm-boundaries")
    return run


def test_lenses_come_before_facts_in_the_advisor_parts(tmp_path):
    run = many_facts_run(tmp_path)
    ps = recommend.advisor_parts(run, demo.LENSES)
    assert len(ps) > 1
    with_lenses = [p["part"] for p in ps if p.get("lenses")]
    with_facts = [p["part"] for p in ps if p.get("facts")]
    assert with_lenses and with_facts and max(with_lenses) <= min(with_facts)
    whole = recommend.advisor_input(run, demo.LENSES)
    assert [l for p in ps for l in p.get("lenses", [])] == whole["lenses"]
    assert [f for p in ps for f in p.get("facts", [])] == whole["facts"]
    assert ps[0]["question"] == whole["question"] and ps[0]["frame"] == whole["frame"]
