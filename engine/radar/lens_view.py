"""What `radar list-lenses` prints: every lens in a folder, once, grouped by the themes index. `run_view` is what
`radar lens-view` prints at the first stop: the run's recommendation beside every other lens.

Each lens is shown with its name, its idea, its level in plain words and what it rests on. A lens in no theme is
under "not yet sorted"; a lens file that fails the lens check is named by its file name and never shown with a level.
A lens with an illustrative original is invented for practice and shown as that, never at a level.

The index only groups: a lens id it lists twice is shown once (where it first stands), an id with no lens file is
ignored (`check-lenses` names it), and a damaged or missing index puts every lens under "not yet sorted". Nothing
here changes a file, and nothing raises on a hand-edited file; a folder that cannot be listed raises
`LensFolderUnreadable`.
"""
from datetime import date
from pathlib import Path

from . import lenses
from .report.model import load_labels
from .schema import _load


class LensFolderUnreadable(Exception):
    """The lens folder cannot be listed. The text is the lens check's own message for it."""


def _invented(lens: dict) -> bool:
    """True when an original's reference begins with the word Illustrative: the test the lens check uses for real use."""
    return any(lenses.is_illustrative(original.get("reference")) for original in lens["originals"])


def _entry(lens: dict, labels: dict) -> dict:
    invented = _invented(lens)
    return {"id": lens["id"], "name": lens["name"], "idea": lens["idea"],
            "level": labels["level_invented" if invented else "level_" + lenses.lens_level(lens)],
            "rests_on": lenses.rests_on_text(lens, labels),
            "invented": invented}


def list_lenses(lenses_dir: Path, exclude: frozenset[str] = frozenset()) -> dict:
    """`{"themes": [{"name", "lenses": [entry]}], "not_yet_sorted": [entry], "unreadable": [file name], "count": int}`.

    An entry is `{"id", "name", "idea", "level", "rests_on", "invented"}`. Lens ids in `exclude` are left out of the
    lists but still counted; `count` is the number of lenses that passed the lens check. A theme left with no lens is
    left out. Raises `LensFolderUnreadable` when the folder cannot be listed; otherwise never raises."""
    files = lenses.lens_files(lenses_dir)
    if files is None:
        raise LensFolderUnreadable(lenses.FOLDER_UNREADABLE)
    labels, today = load_labels(), date.today()
    by_id, unreadable = {}, []
    for path in files:
        lens = None if lenses.check_lens(path, False, today) else _load(path)
        if lens is None:   # fails the lens check (or was changed or locked since)
            unreadable.append(path.name)
        else:
            by_id[path.stem] = lens
    themes, _ = lenses.read_themes(lenses_dir)
    placed, grouped = set(), []
    for theme in themes or []:
        members = []
        for lens_id in theme["lenses"]:
            if lens_id in by_id and lens_id not in placed:
                placed.add(lens_id)
                if lens_id not in exclude:
                    members.append(_entry(by_id[lens_id], labels))
        if members:
            grouped.append({"name": theme["name"], "lenses": members})
    return {"themes": grouped,
            "not_yet_sorted": [_entry(lens, labels) for lens_id, lens in by_id.items()
                               if lens_id not in placed and lens_id not in exclude],
            "unreadable": unreadable, "count": len(by_id)}


def _recommended(entry: dict, listed: dict, labels: dict) -> dict:
    """A recorded entry with its lens's name, level, what it rests on and whether it is invented, and `flags`: a plain
    sentence for each damaged part (`recommend.damage_sentences`), empty when the entry is as the advisor made it. A
    lens that no longer passes the lens check (changed, damaged or gone since it was recommended) is still shown, as
    recommended, but flagged `available: False`, named by its lens id and with no level, so no old level is ever shown
    for it."""
    from . import recommend
    lens = listed.get(entry["lens"])
    shown = {key: list(value) if isinstance(value, list) else value for key, value in entry.items() if key != "damage"}
    shown["flags"] = recommend.damage_sentences(entry.get("damage", []), labels)
    if lens is None:
        return {**shown, "name": entry["lens"], "level": None, "rests_on": None, "invented": False,
                "available": False}
    return {**shown, "name": lens["name"], "level": lens["level"], "rests_on": lens["rests_on"],
            "invented": lens["invented"], "available": True}


def run_view(run_dir: Path, lenses_dir: Path) -> dict:
    """What the first stop shows, changing nothing: `{"recommendation", "stale", "marks", "others", "damaged"}`.

    `recommendation` is None when the run holds no record, or nothing of it can be read; else `{"by", "at", "note",
    "models_set_to", "recommended", "no_facts_yet", "flags"}`: the entries with facts and the entries with none, each
    in recorded order and carrying its recorded parts (a part that cannot be read is None), its own `flags` and the
    lens's `name`, `level`, `rests_on`, `invented` and `available`; `flags` are the plain sentences for the damaged
    places of the record itself. `stale` is true when the facts that count now, with their statuses, are not the facts
    the record saw (false with no record, and when what it saw cannot be read: a flag says so). `marks` is
    `recommend.marks`. `others` is `list_lenses` with every recommended lens left out when the recommendation is
    current, and every lens when there is none or it is stale. `damaged` is true when a record file is there whose
    form is wrong or that cannot be read (`recommend.readable_record`): a damaged record is not thrown out, each part
    that can still be read is shown, and each damaged place is flagged where it stands (Paul's decision 18). Raises
    `LensFolderUnreadable` for a folder that cannot be listed."""
    from . import recommend   # here and not at the top: recommend itself imports this module
    run_dir, lenses_dir = Path(run_dir), Path(lenses_dir)
    record, damage, damaged = recommend.readable_record(run_dir)
    if record is None:
        return {"recommendation": None, "stale": False, "marks": {}, "others": list_lenses(lenses_dir),
                "damaged": damaged}
    labels = load_labels()
    everything = list_lenses(lenses_dir)
    listed = {entry["id"]: entry for entry in [*(entry for theme in everything["themes"] for entry in theme["lenses"]),
                                               *everything["not_yet_sorted"]]}
    entries = [_recommended(entry, listed, labels) for entry in record["entries"]]
    # an entry whose facts cannot be read is not one with no facts found: it stays with the lenses that have facts
    has_facts = [bool(entry["facts"]) or any(item["part"] == "facts" for item in entry["damage"])
                 for entry in record["entries"]]
    stale = recommend.is_stale(run_dir, record)
    # a stale record is not shown as the current advice (step 6 asks again, or treats it as none), so the list of the
    # other lenses then leaves no lens out
    others = everything if stale else list_lenses(lenses_dir, exclude=frozenset(entry["lens"] for entry in entries))
    return {"recommendation": {"by": record["by"], "at": record["at"], "note": record["note"],
                               "models_set_to": record["models_set_to"],
                               "recommended": [entry for entry, facts in zip(entries, has_facts) if facts],
                               "no_facts_yet": [entry for entry, facts in zip(entries, has_facts) if not facts],
                               "flags": recommend.damage_sentences(damage, labels)},
            "stale": stale, "marks": recommend.marks(run_dir), "others": others, "damaged": damaged}
