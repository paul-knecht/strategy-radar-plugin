"""The reader measurement (`scripts/measure_readers.py`) and its fixture: what a program can check without a model.

The measurement itself is written and never run: it starts model sessions and costs money. These tests use a fake
session that answers from a table, so no model is called and nothing is spent.
"""
import importlib.util
import json
import re
from pathlib import Path

import pytest

from plugin_helpers import ROOT, company_names_in, fenced_json
from test_plugin_shell import invisible_characters

SCRIPT = ROOT / "scripts" / "measure_readers.py"
FIXTURE = ROOT / "tests" / "fixtures" / "planted_links.json"


def load():
    spec = importlib.util.spec_from_file_location("measure_readers", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def measure():
    return load()


@pytest.fixture(scope="module")
def fixture(measure):
    return measure.load_fixture(FIXTURE)


def test_the_fixture_is_invented_labelled_so_and_plain_ascii(fixture):
    text = FIXTURE.read_text(encoding="utf-8")
    assert fixture["illustrative"] is True and "Illustrative" in fixture["note"]
    assert re.search(r"[^\x00-\x7f]", text) is None and invisible_characters(text) == []
    assert company_names_in(text) == []
    for lens in fixture["lenses"]:
        assert lens["name"].startswith("Illustrative lens") and lens["idea"].startswith("Illustrative")
        assert len(lens["questions"]) == 3


def test_the_fixture_mixes_right_and_wrong_links_plain_and_subtle(fixture):
    links = fixture["links"]
    keys = [(link["lens"], link["fact"]) for link in links]
    assert len(set(keys)) == len(keys) == 24
    assert sum(link["right"] for link in links) == 12
    for right in (True, False):
        for kind in ("plain", "subtle"):
            assert any(link["right"] is right and link["kind"] == kind for link in links), (right, kind)
    assert {link["lens"] for link in links} == {lens["id"] for lens in fixture["lenses"]}
    assert {fact["status"] for fact in fixture["facts"]} == {"confirmed", "uncertain"}


def test_a_packet_has_the_keys_the_readers_are_given_and_none_of_the_answer(measure, fixture):
    keys = fenced_json(ROOT / "agents" / "lens-link-reader.md", "packet-keys")["packet"]
    assert list(measure.PACKET_KEYS) == keys
    for packet in measure.packets(fixture):
        assert list(packet) == keys
    assert '"kind"' not in json.dumps(measure.packets(fixture)) and '"right"' not in json.dumps(measure.packets(fixture))


def test_the_readers_are_the_two_helpers_and_the_models_come_from_the_settings_file(measure):
    assert measure.READERS == ("lens-link-reader", "lens-link-reader-quick")
    models = json.loads((ROOT / "settings" / "models.json").read_text(encoding="utf-8"))
    assert measure.models_set_to() == {reader: models[reader] for reader in measure.READERS}
    for reader in measure.READERS:
        text = measure.reader_instructions(reader)
        assert not text.startswith("---") and "# Link reader" in text and "This is a measurement" in text
        assert measure.claude_command(models[reader], text)[:5] == ["claude", "-p", "--model", models[reader], "--tools"]


def test_a_reply_is_read_line_by_line_and_a_line_out_of_form_is_no_verdict(measure):
    answer = ("illustrative-one-supplier F1 bears The fact names the one supplier.\n"
              "`illustrative-one-supplier` `F7` doubt No question asks about a speech.\n"
              "some other line\n"
              "illustrative-reaction-to-entry F9 maybe unclear\n"
              "illustrative-reaction-to-entry F8 bears first\n"
              "illustrative-reaction-to-entry F8 doubt then the other\n")
    assert measure.parse_verdicts(answer) == {("illustrative-one-supplier", "F1"): "bears",
                                              ("illustrative-one-supplier", "F7"): "doubt"}


def table(fixture, rule):
    return {(link["lens"], link["fact"]): rule(link) for link in fixture["links"]}


def test_the_counts_for_a_reader_who_doubts_every_wrong_link_and_one_right_link(measure, fixture):
    first = next(link for link in fixture["links"] if link["right"] and link["kind"] == "plain")
    perfect = table(fixture, lambda link: "bears" if link["right"] else "doubt")
    perfect[(first["lens"], first["fact"])] = "doubt"
    silent = {}
    result = measure.score(fixture, {"lens-link-reader": perfect, "lens-link-reader-quick": silent})
    reader = result["lens-link-reader"]
    assert reader["wrong_caught"] == {"all": 12, "plain": 6, "subtle": 6}
    assert reader["right_marked"] == {"all": 1, "plain": 1, "subtle": 0}
    assert reader["no_verdict"] == 0
    quick = result["lens-link-reader-quick"]
    assert quick["wrong_caught"]["all"] == 0 and quick["right_marked"]["all"] == 0 and quick["no_verdict"] == 24
    assert result["pair"]["wrong_caught"]["all"] == 12 and result["pair"]["no_verdict"] == 0   # one doubt marks the link
    assert result["wrong_links"]["all"] == 12 and result["right_links"] == {"all": 12, "plain": 8, "subtle": 4}


def test_a_link_without_a_verdict_is_never_counted_as_a_doubt_or_as_agreement(measure, fixture):
    result = measure.score(fixture, {"lens-link-reader": {}, "lens-link-reader-quick": {}})
    for name in ("lens-link-reader", "lens-link-reader-quick", "pair"):
        assert result[name]["no_verdict"] == 24
        assert result[name]["wrong_caught"]["all"] == 0 and result[name]["right_marked"]["all"] == 0


def test_the_report_names_each_reader_and_says_it_is_an_indication(measure, fixture):
    both = table(fixture, lambda link: "doubt")
    text = measure.report(measure.score(fixture, {"lens-link-reader": both, "lens-link-reader-quick": both}))
    for needed in ("lens-link-reader", "lens-link-reader-quick", "The pair", "12 of 12", "not proof"):
        assert needed in text, needed


def test_without_run_nothing_is_called_and_the_cost_is_an_estimate(measure, capsys):
    def never(command, prompt):
        raise AssertionError("a session was started")
    assert measure.main([], session=never) == 0
    out = capsys.readouterr().out
    assert "Nothing was called" in out and "estimate" in out and "not measured" in out


def test_with_run_each_reader_reads_all_links_once_in_a_session_of_its_own(measure, fixture, capsys):
    calls = []

    def fake(command, prompt):
        calls.append((command[3], json.loads(prompt)))
        verdict = "bears" if len(calls) == 1 else "doubt"
        return "\n".join(f"{p['lens']} {p['fact']} {verdict} note" for p in json.loads(prompt)["packets"])

    assert measure.main(["--run"], session=fake) == 0
    models = json.loads((ROOT / "settings" / "models.json").read_text(encoding="utf-8"))
    assert [model for model, _ in calls] == [models["lens-link-reader"], models["lens-link-reader-quick"]]
    assert all(len(prompt["packets"]) == 24 for _, prompt in calls)
    out = capsys.readouterr().out
    assert "lens-link-reader-quick" in out and "wrong links it marked: 12 of 12" in out


def test_a_session_that_fails_ends_the_measurement_with_a_plain_message(measure, capsys):
    def broken(command, prompt):
        raise measure.MeasurementError("The session ended with exit code 1: no")
    assert measure.main(["--run"], session=broken) == 2
    assert "exit code 1" in capsys.readouterr().err


def test_a_fixture_that_is_not_marked_illustrative_is_refused(measure, tmp_path):
    bad = json.loads(FIXTURE.read_text(encoding="utf-8"))
    bad["illustrative"] = False
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(measure.MeasurementError):
        measure.load_fixture(path)


def test_the_script_holds_no_non_ascii_character():
    text = SCRIPT.read_text(encoding="utf-8")
    assert re.search(r"[^\x00-\x7f]", text) is None and invisible_characters(text) == []
