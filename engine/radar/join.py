"""The extractors' saved answers joined into the bare list `add-facts` takes, so the lead never copies a proposal.

Each answer is `proposals/<id>.json`, `{"proposals": [...], "notes": {...}}`. `join` takes the `proposals` of the
named sources, in the order given and then each answer's own order, unchanged; the notes are not joined. A merge
`{"keep": "S29#1", "fold": ["S21#2"]}` (positions counted from 1 in that source's `proposals`) appends to the
keeper's `supporting` each folded proposal's `source_id` and `quote`, and its `quote_translation` when it has one,
and leaves the folded proposal out. Which proposals state the same thing is the lead's judgement; the program only
copies. Merges that name a proposal that is not there, one proposal twice, or a proposal folded into itself are
refused whole.
"""
import json
import re
from pathlib import Path

from .schema import Problem

NO_ANSWER = "no saved answer for source"
NOT_AN_ANSWER = "the saved answer is not an extractor's answer"
NO_PROPOSAL = "no such proposal"
NAMED_TWICE = "a proposal is named twice in the merges"
INTO_ITSELF = "a proposal is folded into itself"

SOURCE_ID = re.compile(r"S[0-9]+")
REF = re.compile(r"(S[0-9]+)#([1-9][0-9]*)")


class JoinRefused(ValueError):
    """The answers or the merges break a rule; nothing was written. `problems` names each."""

    def __init__(self, problems: list[Problem]):
        super().__init__("the proposals were not joined")
        self.problems = problems


def check_merges(merges) -> None:
    """Raise ValueError, in plain words, when `merges` is not a list of `{"keep": REF, "fold": [REF, ...]}`."""
    if not isinstance(merges, list):
        raise ValueError('the merges must be a JSON list of {"keep": "S29#1", "fold": ["S21#2"]}')
    for index, merge in enumerate(merges):
        if not (isinstance(merge, dict) and set(merge) == {"keep", "fold"} and isinstance(merge["fold"], list)
                and merge["fold"] and all(isinstance(ref, str) and REF.fullmatch(ref)
                                          for ref in [merge["keep"], *merge["fold"]])):
            raise ValueError(f'merge {index + 1} must be {{"keep": "S29#1", "fold": ["S21#2"]}}: exactly these two '
                             "keys, each proposal written as its source and its place from 1")


def _answers(run: Path, sources: list[str]) -> dict[str, list]:
    found, problems = {}, []
    for source_id in sources:
        path = Path(run) / "proposals" / f"{source_id}.json"
        name = f"proposals/{source_id}.json"
        if not path.is_file():
            problems.append(Problem(name, None, f"{NO_ANSWER} {source_id}: {name} is not there"))
            continue
        try:
            answer = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError):
            answer = None
        if not (isinstance(answer, dict) and isinstance(answer.get("proposals"), list)
                and all(isinstance(item, dict) for item in answer["proposals"])):
            problems.append(Problem(name, None, f"{NOT_AN_ANSWER}: {name} holds no list of proposals"))
            continue
        found[source_id] = answer["proposals"]
    if problems:
        raise JoinRefused(problems)
    return found


def join(run: Path, sources: list[str], merges: list[dict]) -> list[dict]:
    """The joined list; raises JoinRefused, having read only, when an answer or a merge breaks a rule."""
    answers = _answers(run, sources)
    problems, seen = [], set()

    def proposal(ref, field):
        source_id, place = REF.fullmatch(ref).groups()
        if int(place) > len(answers.get(source_id, [])):
            problems.append(Problem(None, field, f"{NO_PROPOSAL}: {ref}"))
            return None
        if ref in seen:
            problems.append(Problem(None, field, f"{NAMED_TWICE}: {ref}"))
            return None
        seen.add(ref)
        return answers[source_id][int(place) - 1]

    folds = []   # (keeper, the proposals folded into it)
    for index, merge in enumerate(merges):
        if merge["keep"] in merge["fold"]:
            problems.append(Problem(None, f"merges[{index}]", f"{INTO_ITSELF}: {merge['keep']}"))
            continue
        keeper = proposal(merge["keep"], f"merges[{index}].keep")
        folded = [proposal(ref, f"merges[{index}].fold") for ref in merge["fold"]]
        folds.append((keeper, folded))
    if problems:
        raise JoinRefused(problems)
    gone, extra = set(), {}
    for keeper, folded in folds:
        gone.update(id(item) for item in folded)
        extra[id(keeper)] = [{"source_id": item.get("source_id"), "quote": item.get("quote"),
                              **({"quote_translation": item["quote_translation"]}
                                 if item.get("quote_translation") is not None else {})} for item in folded]
    joined = []
    for source_id in sources:
        for item in answers[source_id]:
            if id(item) in gone:
                continue
            if id(item) in extra:
                item = {**item, "supporting": list(item.get("supporting") or []) + extra[id(item)]}
            joined.append(item)
    return joined
