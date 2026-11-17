"""A helper's input in parts, so that each part fits what its Bash tool can read in one go.

A helper with only Bash reads what a command prints, and a printed line that is too long is cut short. So a command
whose input can grow with the run (the project grouper's, the lens advisor's) prints it in parts: each part one line
of at most `PART_LIMIT` characters, holding whole items only, in their order. The helper reads part 1, sees `parts`,
and reads the rest one by one.
"""
import json

PART_LIMIT = 20000
NO_SUCH_PART = "no such part"
_PLACEHOLDER = 10 ** 9   # measured in place of the part numbers, which are known only at the end


def no_such_part(asked: int, total: int) -> str:
    """The problem message for a part that is not there."""
    return f"{NO_SUCH_PART}: part {asked} was asked for, and the input has {total} part{'' if total == 1 else 's'}"


def _size(part: dict) -> int:
    """The length of `part` as one line with every character outside ASCII escaped. That is never shorter than the line
    the program prints, in characters or in UTF-8 bytes, whatever the text holds."""
    return len(json.dumps(part))


def _assemble(head: dict, lists: dict, number, total) -> dict:
    return {**head, "part": number, "parts": total, **lists}


def split(head: dict, items: list, limit: int = PART_LIMIT) -> list[dict]:
    """`items`, a list of `(list name, item)` in order, cut into parts that each print shorter than `limit`.

    Each part is `{**head, "part": n, "parts": total, <list name>: [...], ...}`, with `head` on the first part only
    and each list name in the order its first item came. A part holds whole items only, and as many as fit; an item
    that does not fit even alone, or together with the head, still gets a part (it is never cut). With no items there
    is one part, holding the head."""
    found = []   # (head of the part, its lists)
    lists: dict = {}
    part_head = head
    for name, item in items:
        trial = {key: list(value) for key, value in lists.items()}
        trial.setdefault(name, []).append(item)
        if lists and _size(_assemble(part_head, trial, _PLACEHOLDER, _PLACEHOLDER)) >= limit:
            found.append((part_head, lists))
            part_head, trial = {}, {name: [item]}
        lists = trial
    found.append((part_head, lists))
    total = len(found)
    return [_assemble(part_head, part_lists, number, total)
            for number, (part_head, part_lists) in enumerate(found, start=1)]


def split_input(given: dict, list_names: tuple, limit: int = PART_LIMIT) -> list[dict]:
    """A helper's whole input `given` in parts: every key not in `list_names` is the head, and the items of the lists
    named follow in that order. A list with no item at all stays on the first part as an empty list, so the helper
    always sees each list named."""
    head = {key: value for key, value in given.items() if key not in list_names}
    found = split(head, [(name, item) for name in list_names for item in given[name]], limit)
    first = found[0]
    found[0] = {**{key: value for key, value in first.items() if key not in list_names},
                **{name: first.get(name, []) for name in list_names if name in first or not given[name]}}
    return found
