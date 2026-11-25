"""The claim matcher's input and its groups of proposals that state the same claim, written as the merges that
`join.join` reads.

`matcher_input` lists the proposals of this round's sources (their saved answers, read as `join` reads them), each
with its place (`S6#1`), its statement and its quote, in parts that fit the helper's Bash tool (`matcher_parts`). The
matcher sends groups, each a keeper and the proposals folded into it, and `record_groups` checks them and writes
`proposals/merges.json`, replacing any earlier one; a list that breaks a rule writes nothing. Whether a folded quote
counts as a second independent source stays `settle`'s decision: the program only checks that a group can be one
claim, and never changes a quote.
"""
from pathlib import Path

from . import join, parts, store, tidy, verify
from .schema import Problem

MERGES = "proposals/merges.json"   # in the run folder
MATCHER = "claim-matcher"
MOVE_FIELDS = ("company", "site", "size_value", "size_unit", "announced", "planned_start")   # what the matcher sees of a move
SAME_FIELDS = ("size_value", "size_unit", "announced", "planned_start")   # two moves of a group may not state different ones
LINE_KEYS = ("keep", "fold")

NOT_THE_MATCHER = "only the claim matcher may record the claim groups"
ONE_SOURCE = "two proposals of one source are in one group"
EARLY_SIGNAL = "an early signal is in a group"
OTHER_COMPANY = "capacity moves of different companies are in one group"
OTHER_DETAIL = "capacity moves in one group state a different"
NO_COMPANY = "a capacity move in a group names no company"
# The messages below are written out, not built from these, so the check of explanations can read them.


def _fields(item: dict) -> dict:
    return item["fields"] if isinstance(item.get("fields"), dict) else {}


def matcher_input(run: Path, sources: list[str]) -> dict:
    """`{"question", "proposals"}`: every proposal of the named sources' saved answers, in source then answer order,
    as `{"place", "source_id", "publisher", "date", "kind", "statement", "quote", "early_signal", "fields"}`. `fields`
    holds a capacity move's MOVE_FIELDS and is None for any other proposal. Raises join.JoinRefused when a source has
    no saved answer. Changes nothing."""
    run = Path(run)
    answers, saved = join._answers(run, sources), store.read_sources(run)
    found = []
    for source_id in sources:
        source = saved.get(source_id) or {}
        for place, item in enumerate(answers[source_id], start=1):
            fields = _fields(item)
            found.append({"place": f"{source_id}#{place}", "source_id": source_id,
                          "publisher": source.get("publisher"), "date": source.get("date"), "kind": item.get("kind"),
                          "statement": item.get("statement"), "quote": item.get("quote"),
                          "early_signal": verify.is_early_signal(item, saved),
                          "fields": ({key: fields.get(key) for key in MOVE_FIELDS}
                                     if item.get("kind") == "capacity_move" else None)})
    return {"question": store.load_run(run).get("question"), "proposals": found}


def matcher_parts(run: Path, sources: list[str]) -> list[dict]:
    """`matcher_input` in parts that each print shorter than `parts.PART_LIMIT`: the question on the first part only."""
    return parts.split_input(matcher_input(run, sources), ("proposals",))


def parse_group_lines(lines: list[str]) -> list[dict]:
    """The groups of a list in the plain line form: one group per block of `keep: S6#1` and `fold: S2#3, S9#1`, in
    either order, blocks separated by blank lines; no line means no groups. Raises ValueError, with a plain sentence,
    for a line that breaks the form."""
    blocks, block = [], []
    for number, line in enumerate(lines, start=1):
        if line.strip():
            block.append((number, line))
        elif block:
            blocks.append(block)
            block = []
    if block:
        blocks.append(block)
    groups = []
    for block in blocks:
        group = {}
        for number, line in block:
            key, sep, value = line.partition(":")
            key, value = key.strip(), value.strip()
            if not sep or key not in LINE_KEYS:
                raise ValueError(f"line {number} of the list is not keep: or fold: and a proposal. Write each group as "
                                 "keep: S6#1 and fold: S2#3, S9#1 on two lines.")
            if key in group:
                raise ValueError(f"line {number} of the list gives {key} a second time in one group. Leave a blank "
                                 "line between two groups.")
            places = [place.strip() for place in value.split(",")]
            if not all(join.REF.fullmatch(place) for place in places) or (key == "keep" and len(places) > 1):
                raise ValueError(f"line {number} of the list names a proposal that is not written as its source "
                                 "and its place from 1, such as S6#1; keep names one, fold one or more separated "
                                 "by commas.")
            group[key] = places[0] if key == "keep" else places
        for key in LINE_KEYS:
            if key not in group:
                raise ValueError(f"group {len(groups) + 1} of the list has no {key}. Each group needs keep and fold.")
        groups.append({"keep": group["keep"], "fold": group["fold"]})
    return groups


def _said(field: str, value):
    """What a move's `field` states, in a form two spellings of one value share; None for a blank value. A size is
    its number (`2` is `2.0`), a unit its one name (`line` is `lines`); anything else, or a size that is no plain
    number, its text whatever its case."""
    if value is None or not str(value).strip():
        return None
    if field == "size_value":
        number = tidy.size(str(value).strip(), None)["number"]
        if number is not None:
            return number
    if field == "size_unit":
        unit = tidy.unit(str(value))   # None for a unit of only invisible characters
        return unit["name"].casefold() if unit else None
    return str(value).strip().casefold()


def record_groups(run: Path, sources: list[str], groups: list[dict], by: str) -> list[Problem]:
    """Check the groups and write them as `proposals/merges.json`, replacing any earlier one; return the problems.

    A `by` other than the claim matcher and groups not in the merges form raise ValueError. Refused, with nothing
    written: a place that does not exist, a place named twice and a proposal folded into itself (join's own check), two
    places of one source in a group, an early signal in a group, a capacity move that names no company, capacity moves of
    different companies, and capacity moves that state a different size, unit, announcement date or planned start where both
    state one. Every problem is named at once: the group rules run on every group whose places are all there."""
    if by != MATCHER:
        raise ValueError(NOT_THE_MATCHER)
    join.check_merges(groups)
    run = Path(run)
    try:
        answers = join._answers(run, sources)
    except join.JoinRefused as refused:   # a source without a saved answer: no place can be read
        return refused.problems
    try:
        join.join(run, sources, groups)
        problems = []
    except join.JoinRefused as refused:
        problems = list(refused.problems)
    saved, companies = store.read_sources(run), tidy.Companies.from_run(store.load_run(run))
    for index, group in enumerate(groups):
        where = f"merges[{index}]"   # as join names a merge
        places = [group["keep"], *group["fold"]]
        refs = [join.REF.fullmatch(place).groups() for place in places]
        if group["keep"] in group["fold"] or any(int(number) > len(answers.get(source_id, []))
                                                 for source_id, number in refs):
            continue   # join has named it; the group rules need every place
        items, first_of = {}, {}
        for place, (source_id, number) in zip(places, refs):
            items[place] = answers[source_id][int(number) - 1]
            if source_id in first_of:
                problems.append(Problem(None, where, "two proposals of one source are in one group: "
                                                     f"{first_of[source_id]} and {place}"))
            first_of.setdefault(source_id, place)
        for place in places:
            if verify.is_early_signal(items[place], saved):
                problems.append(Problem(None, where, f"an early signal is in a group: {place}"))
        moves = [place for place in places if items[place].get("kind") == "capacity_move"]
        named = {place: companies.resolve(_fields(items[place]).get("company")) for place in moves}
        for place in moves:
            if named[place] is None:
                problems.append(Problem(None, where, f"a capacity move in a group names no company: {place}"))
        if len({company["key"] for company in named.values() if company}) > 1:
            problems.append(Problem(None, where, "capacity moves of different companies are in one group: "
                                                 f"{' and '.join(moves)}"))
        for field in SAME_FIELDS:
            stated = {_said(field, _fields(items[place]).get(field)) for place in moves} - {None}
            if len(stated) > 1:
                problems.append(Problem(None, where, f"capacity moves in one group state a different {field}: "
                                                     f"{' and '.join(moves)}"))
    if not problems:
        store._write_json(run / MERGES, [{"keep": group["keep"], "fold": list(group["fold"])} for group in groups])
    return problems
