"""Screening runs: the VC screening memo (design 2026-11-17). The run steps, references and helpers that a run whose
`run.json` says `screening: true` reads instead of, or beside, the capacity-move ones."""
import re

from plugin_helpers import ROOT, unknown_calls

REFS = ROOT / "references"
STEPS = ROOT / "skills" / "run" / "steps"
PLAYBOOK = REFS / "screening-playbook.md"
INVISIBLE = "".join(chr(code) for code in (0xAD, 0xA0, 0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF))


def text(path):
    return path.read_text(encoding="utf-8")


def test_the_screening_playbook_is_short_plain_and_names_only_real_commands():
    body = text(PLAYBOOK)
    assert len(body.splitlines()) < 150 and not [c for c in body if c in INVISIBLE]
    assert unknown_calls(body) == [] and "bin/radar" not in body
    assert not re.search(r'"[^"\n]*\bradar [a-z]', body)


def test_the_screening_playbook_states_the_window_the_fact_kind_and_the_search_order():
    body = text(PLAYBOOK)
    assert "`time_window_months` to `120`" in body
    assert "Propose no `capacity_move` fact" in body and "`in_question`" in body
    order = ["own site", "commercial register", "funding announcements", "trade press", "job postings",
             "competitors' own sites"]
    places = [body.index(item) for item in order]
    assert places == sorted(places)


def test_steps_two_and_four_pick_the_playbook_by_the_screening_mark():
    for name in ("02-plan-search.md", "04-extract.md"):
        body = text(STEPS / name)
        assert "capacity-moves-playbook.md" in body and "screening-playbook.md" in body, name
        assert "`screening: true`" in body, name
        assert len(body.splitlines()) <= 80, name


def test_the_extractor_reads_the_playbook_step_four_names_and_proposes_only_general_facts_in_a_screening_run():
    body = text(ROOT / "agents" / "fact-extractor.md")
    assert "`references/screening-playbook.md`" in body
    assert "In a screening run, propose only general facts; the capacity-move fields and in_question do not apply." in body


def test_the_screen_skill_makes_a_screening_pack_through_new_pack_and_hands_over_to_the_run():
    body = text(ROOT / "skills" / "screen" / "SKILL.md")
    for needed in ("skills/new-pack/SKILL.md", '"screening": true', '"time_window_months": 120', "/strategy-radar:run",
                   "What would have to be true to invest in <startup>?"):
        assert needed in body, needed


def test_the_screen_skill_proposes_competitors_and_pages_from_a_search_never_from_memory():
    """Paul, 2026-11-17: the person gives name and website; the AI finds the rest, each with the page it was found on."""
    body = text(ROOT / "skills" / "screen" / "SKILL.md")
    for needed in ('"suggested_by": "search"', "`found_at`", "Propose only pages you opened",
                   "never proposed, whatever you know", "Answer all, or name the numbers to strike"):
        assert needed in body, needed
    assert "Every name and address still comes from the person's words" not in body


def test_the_readme_lists_the_screen_command():
    assert "`/strategy-radar:screen`" in text(ROOT / "README.md")


# --- Task 4b: the screening-memo reference ------------------------------------------------------

MEMO = REFS / "screening-memo.md"
MEMO_SOURCE = ("Example Robotics raised 12 million euros in a seed round led by Investor Q. "
               "The founders previously built and sold a logistics software company in 2019.")


def _general(run, statement, quote):
    from helpers import proposal
    from radar import store
    fact = proposal(kind="general", about_company="Example Robotics", primary_source=True, statement=statement,
                    quote=quote)
    fact.pop("fields")
    return store.new_fact(run, fact)


def memo_run(tmp_path):
    from helpers import add_source, make_run
    from radar import store, verify
    run = make_run(tmp_path, question="What would have to be true to invest in Example Robotics?", screening=True)
    add_source(run, MEMO_SOURCE, publisher="Example Robotics")
    _general(run, "Example Robotics raised 12 million euros in a seed round.",
             "raised 12 million euros in a seed round led by Investor Q")
    _general(run, "The founders built and sold a logistics software company.",
             "previously built and sold a logistics software company in 2019")
    verify.check_quotes(run)
    for fact_id in ("F1", "F2"):
        verify.record_support(run, fact_id, True, "support-checker", "")
    verify.settle(run)
    store.record_checkpoint(run, "lenses", "test", "use none of the lenses on offer")
    store.record_checkpoint(run, "final_report", "test", "build it")
    return run


def memo_example():
    from plugin_helpers import fenced_json
    return fenced_json(MEMO, "screening-example")


def test_the_memo_reference_is_short_plain_and_names_only_real_commands():
    body = text(MEMO)
    assert len(body.splitlines()) < 150 and not [c for c in body if c in INVISIBLE]


def test_the_memo_example_passes_the_data_check_and_the_gate(tmp_path):
    from radar import store
    from radar.gate import gate
    from radar.schema import check_data
    from test_report_build import LENSES
    run = memo_run(tmp_path)
    store.write_analysis(run, memo_example())
    assert check_data(run, LENSES) == [] and gate(run, LENSES) == []


def test_a_money_question_that_names_no_amount_fact_is_refused_as_the_reference_warns(tmp_path):
    from radar import store
    from radar.gate import gate
    from test_report_build import LENSES
    run = memo_run(tmp_path)
    analysis = memo_example()
    analysis["not_found"] = ["The valuation is unknown."]
    store.write_analysis(run, analysis)
    assert any("not-found entry about money" in p.message for p in gate(run, LENSES))
    assert "The valuation is unknown." in text(MEMO)


def test_step_seven_reads_the_memo_reference_in_a_screening_run():
    body = text(STEPS / "07-interpret.md")
    assert "screening-memo.md" in body and "`screening: true`" in body and len(body.splitlines()) <= 80
