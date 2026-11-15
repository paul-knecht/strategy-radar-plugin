"""The run folder: create it, read and write its records, count ids, log checkpoints.

All JSON is UTF-8 with ensure_ascii=False, indent=2 and a trailing newline.
Timestamps are UTC in the form 2026-11-12T10:15:00Z.

Commands may run in parallel on one run. A new record's id is claimed by creating its file exclusively, and
every read-modify-write of run.json happens under an advisory lock on a lock file in the run folder.
"""
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:   # no advisory locks on this platform: the lock does nothing
    fcntl = None

SOURCE_TYPES = ("company_release", "filing", "annual_report", "trade_press", "academic", "permit", "job_posting",
                "regulator_record", "other")
EARLY_SIGNAL_SOURCE_TYPES = ("permit", "job_posting", "regulator_record")   # a fact from one of these is an early signal
MOVE_TYPES = ("new_site", "expansion", "acquisition", "partnership", "closure")
ACCESS = ("captive", "open", "not_stated")
DELIVERY = ("on_time", "delayed", "cancelled", "not_yet", "unknown")
STATUSES = ("proposed", "confirmed", "uncertain", "rejected")
COUNTING = ("confirmed", "uncertain")   # the statuses a fact may be relied on with
CERTAINTY = ("firm", "tentative")
ANSWERED_BY = ("person", "test", "unattended")
DATA_CLASSES = ("public", "licensed", "internal")
RUN_MODES = ("public", "private")
STAGES = ("announced", "under_construction", "operating", "cancelled", "not_stated")
SUPPORT_LEVELS = ("strong", "partial", "weak")
CALC_OPERATIONS = ("sum", "count", "share")
CHECKPOINTS = ("lenses", "final_report")
CONFIDENCE = ("high", "medium", "low")
LENS_LEVELS = ("original_read", "reference_confirmed")
FRAMING = ("company", "user")
STEP_KINDS = ("fact", "reasoning", "conclusion")
AUDIT_CHECKS = ("framing", "outside_view", "uncertainty", "competitor_response", "evidence_symmetry",
                "missing_information", "success_stories", "causality", "disconfirmation", "independence")

# What the person is shown (no option names in it), and the same text with the sentence about the option.
PRIVATE_NOTICE_TEXT = (
    "Private mode sends the content of your documents to the language model through your own "
    "Claude account. Check that your organisation and your data licences allow this."
)
PRIVATE_NOTICE = PRIVATE_NOTICE_TEXT + " Re-run with --acknowledge-data-flow to continue."


class PrivateModeNotAcknowledged(PermissionError):
    """A private run was asked for without the acknowledgement of the data flow."""


# The private run that the demo command builds has its notice scripted, never shown to a person. The run record
# says so with this key, and such a run takes no further non-public material.
DEMO_MARK = "private_acknowledged_by"
DEMO_MARK_VALUE = "demo"
DEMO_RUN_REFUSAL = "This is the invented practice run, so it takes no non-public material."


class DemoRunRefused(PermissionError):
    """Non-public material was offered to the invented private practice run."""


# A private run is kept out of git whole by the line * in its own .gitignore. When that line is gone (or a line that
# starts with ! takes something back), the data check names it and add-copy takes no non-public material.
PRIVATE_NOT_IGNORED = "the ignore file of a private run must keep the whole run out of git"


class PrivateRunNotIgnored(PermissionError):
    """Non-public material was offered to a private run whose .gitignore no longer keeps it out of git."""


def keeps_out_of_git(run_dir: Path) -> bool:
    """Whether the run's .gitignore holds the line * and no line that takes anything back (one that starts with !)."""
    try:
        lines = [line.strip() for line in (Path(run_dir) / ".gitignore").read_text(encoding="utf-8").splitlines()]
    except (OSError, ValueError):   # missing, a folder, not to be opened, not UTF-8
        return False
    return "*" in lines and not any(line.startswith("!") for line in lines)

_KIND_FOLDERS = {"S": "sources", "F": "facts"}
COUNTERS = {"S": "sources_created", "F": "facts_created"}
LOCK_FILE = ".lock"
# What a public run keeps out of git: the lock files, the time of the last download, and a temporary file left
# behind when a write was cut short (`_write_json` names it `.<record>.<hex>.tmp`).
PUBLIC_GITIGNORE = "\n".join((LOCK_FILE, ".fetch.lock", ".last_fetch.json", ".*.tmp")) + "\n"
_RUN_ID = re.compile(r"[A-Za-z0-9._-]+")
_RECORD_ID = {kind: re.compile(kind + r"[0-9]+") for kind in _KIND_FOLDERS}


def _stamp(now: datetime | None) -> str:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json(path: Path, data) -> Path:
    """Write the record whole or not at all: encode first, write a temporary file beside it, swap it in.

    A value that cannot be encoded as UTF-8 (a lone surrogate) raises ValueError before anything is touched, and a
    failed write never truncates the record that is already there.
    """
    payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path = Path(path)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temporary, "xb") as handle:
            handle.write(payload)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return path


def _read_json(path: Path):
    """The JSON in `path`. A file nested too deeply to read is a ValueError like any other broken JSON."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except RecursionError:
        raise ValueError("nested too deeply to read") from None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


LOCK_WAIT_SECONDS = 60   # how long a command waits for the run lock before it gives up
RUN_BUSY = "Another command is still working on this run. Wait a moment and run this again."
_WAIT = object()   # `locked` without `wait`: LOCK_WAIT_SECONDS, read when the lock is taken


class RunBusy(TimeoutError):
    """The run lock stayed taken by another command for the whole wait. Nothing was changed."""


@contextmanager
def locked(run_dir: Path, name: str = LOCK_FILE, wait=_WAIT):
    """Hold an advisory lock on the lock file `name` in the run folder while the block runs.

    The lock is the operating system's lock on the open file (`flock`): it is released when the file is closed, also
    when the process that holds it is killed, so a holder that no longer exists never blocks; the empty file stays.
    `wait` is how many seconds to wait for it (LOCK_WAIT_SECONDS unless given), then RunBusy; None waits as long as it
    takes."""
    if fcntl is None:
        yield
        return
    wait = LOCK_WAIT_SECONDS if wait is _WAIT else wait
    with open(Path(run_dir) / name, "a", encoding="utf-8") as handle:
        if wait is None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        else:
            deadline = time.monotonic() + wait
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RunBusy(RUN_BUSY) from None
                    time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


# --- the run itself -------------------------------------------------------

def _cannot_be_written_to(folder: Path) -> PermissionError:
    return PermissionError(f"The folder {folder} cannot be written to, so choose another folder for the run.")


def check_run_root(root: Path) -> None:
    """Refuse a root that is a file, that lies under a file, or whose nearest existing folder cannot be written to,
    before anything is made. Raises NotADirectoryError or PermissionError, each with a plain sentence."""
    root = Path(root)
    for part in (root, *root.parents):
        if part.exists() and not part.is_dir():
            raise NotADirectoryError(f"{part} is a file, not a folder. Choose a folder to make the run in.")
    nearest = next((part for part in (root, *root.parents) if part.exists()), None)
    if nearest is not None and not os.access(nearest, os.W_OK | os.X_OK):
        raise _cannot_be_written_to(nearest)


NO_ACKNOWLEDGED_WORDS = ("A private run needs the person's own reply to the private-mode notice, word for word: "
                         "give it with --acknowledged-words.")


def init_run(root: Path, question: str, pack: str, run_id: str | None = None,
             illustrative: bool = False, mode: str = "public", acknowledged: bool = False,
             home_company: str | None = None, now: datetime | None = None,
             acknowledged_words: str | None = None) -> Path:
    """Make the run folder. A private run needs the acknowledgement of the data flow and, with it, the person's own
    reply to the notice (`acknowledged_words`), stored word for word. The program cannot tell who wrote the reply."""
    if mode not in RUN_MODES:
        raise ValueError(f"mode must be one of {', '.join(RUN_MODES)}")
    if mode == "private" and not acknowledged:
        raise PrivateModeNotAcknowledged(PRIVATE_NOTICE)
    if mode == "private" and not (isinstance(acknowledged_words, str) and acknowledged_words.strip()):
        raise ValueError(NO_ACKNOWLEDGED_WORDS)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc)
    run_id = run_id or now.strftime("%Y%m%d-%H%M%S")
    if not _RUN_ID.fullmatch(run_id) or ".." in run_id:   # the run folder must stay inside the root
        raise ValueError("run_id may only use letters, digits, '.', '_' and '-', and must not contain '..'")
    for name, text in (("question", question), ("pack", pack), ("home company", home_company),
                       ("reply to the private-mode notice", acknowledged_words)):
        if isinstance(text, str) and not _savable(text):   # checked before anything is made
            raise ValueError(f"The {name} holds characters that cannot be saved, so no run was made. "
                             "Give it again as plain text.")
    root = Path(root)
    check_run_root(root)
    run_dir = root / run_id
    try:
        root.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir()
    except FileExistsError:
        raise FileExistsError(f"The run folder {run_dir} already exists, "
                              "so choose another run name or another folder.") from None
    except PermissionError:   # the check above passed, but something it cannot see (an access list) refuses
        raise _cannot_be_written_to(root) from None
    for sub in ("sources", "copies", "facts", "report"):
        (run_dir / sub).mkdir()
    (run_dir / "copies" / ".gitignore").write_text("*\n", encoding="utf-8")   # saved copies never enter git
    # a private run is ignored whole; a public one is committed, without what the program keeps beside the records
    (run_dir / ".gitignore").write_text("*\n" if mode == "private" else PUBLIC_GITIGNORE, encoding="utf-8")
    save_run(run_dir, {
        "run_id": run_id,
        "question": question,
        "pack": pack,
        "language": "en",
        "home_company": home_company,
        "illustrative": illustrative,
        "mode": mode,
        "private_acknowledged_at": _stamp(now) if mode == "private" else None,
        "private_acknowledged_words": acknowledged_words if mode == "private" else None,
        "started_at": _stamp(now),
        "checkpoints": [],
        "search_log": [],
        "excluded": [],
        "sources_created": 0,
        "facts_created": 0,
    })
    return run_dir


def _savable(text: str) -> bool:
    """Whether `text` can be written as UTF-8 (an argument whose bytes were not UTF-8 holds half a pair that cannot)."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def mark_demo_run(run_dir: Path) -> None:
    """Mark a private, illustrative run as the demo's scripted one. Only the demo builder calls this."""
    with locked(run_dir):
        run = load_run(run_dir)
        if run.get("mode") != "private" or run.get("illustrative") is not True:
            raise ValueError("only a private, illustrative run can be marked as the demo's")
        run[DEMO_MARK] = DEMO_MARK_VALUE
        save_run(run_dir, run)


def is_demo_private_run(run: dict) -> bool:
    return run.get(DEMO_MARK) == DEMO_MARK_VALUE


def load_run(run_dir: Path) -> dict:
    return _read_json(Path(run_dir) / "run.json")


class RunRecordUnreadable(ValueError):
    """The folder holds a run.json that cannot be read as the record of a run."""


# What every run record has had since the first version: a record without it (`{}`, written by hand) is not a run.
RUN_RECORD_LISTS = ("checkpoints", "search_log", "excluded")
RUN_RECORD_KEYS = ("run_id", "mode") + RUN_RECORD_LISTS


def is_run_record(record) -> bool:
    """Whether `record` has what every run record has: its id, its mode and its three lists, each a list."""
    return (isinstance(record, dict) and all(key in record for key in RUN_RECORD_KEYS)
            and all(isinstance(record[key], list) for key in RUN_RECORD_LISTS))


def require_run(run_dir: Path) -> None:
    """Refuse, with one plain sentence (ValueError), a folder that is not a run: nothing is made in it or asked for.

    A folder without a run.json is not the folder of a run. A folder whose run.json is there but cannot be read as a
    run's record (empty, not JSON, not a JSON object, not a file, not to be opened, or without what every run record
    has, see `is_run_record`) is refused as `RunRecordUnreadable`, in a sentence that says so."""
    path = Path(run_dir) / "run.json"
    if not os.path.lexists(path):
        raise ValueError(f"{run_dir} is not the folder of a run. Give the folder that init-run made for the run.")
    try:
        record = _read_json(path)
    except (OSError, ValueError):   # a folder, no permission, not UTF-8, not JSON, nested too deeply
        record = None
    if not is_run_record(record):
        raise RunRecordUnreadable(f"The record of the run in {run_dir} cannot be read: its file run.json is damaged "
                                  "or cannot be opened. Nothing was changed.")


def save_run(run_dir: Path, run: dict) -> None:
    _write_json(Path(run_dir) / "run.json", run)


# --- ids and records ------------------------------------------------------

def _numbered_files(run_dir: Path, kind: str) -> list[tuple[int, Path]]:
    """The record files of one kind, by number. Only `S12.json` or `F3.json` counts: a file whose name starts with a
    dot (the temporary file of a write that was cut short) is never a record."""
    pattern = re.compile(rf"^{kind}(\d+)\.json$")
    found = []
    for path in (Path(run_dir) / _KIND_FOLDERS[kind]).glob(f"{kind}*.json"):
        match = pattern.match(path.name)
        if match:
            found.append((int(match.group(1)), path))
    return sorted(found)


def next_id(run_dir: Path, kind: str) -> str:
    if kind not in _KIND_FOLDERS:
        raise ValueError("kind must be 'S' or 'F'")
    files = _numbered_files(run_dir, kind)
    return f"{kind}{(files[-1][0] if files else 0) + 1}"


def reserve_id(run_dir: Path, kind: str) -> str:
    """Claim the next free id by creating its record file exclusively; when another command was faster, try the next."""
    if kind not in _KIND_FOLDERS:
        raise ValueError("kind must be 'S' or 'F'")
    folder = Path(run_dir) / _KIND_FOLDERS[kind]
    while True:
        record_id = next_id(run_dir, kind)
        try:
            with open(folder / f"{record_id}.json", "x", encoding="utf-8"):
                return record_id
        except FileExistsError:
            continue


def record_created(run_dir: Path, kind: str, record_id: str) -> None:
    """Count a new record in run.json, so a record file that is deleted later is noticed.

    The counter holds the highest id number created. A run without the counter (an older run) is left as it is.
    It waits for the lock as long as it takes: the record is already written, and a command that gave up here would
    tell the person to run it again, which would make the record twice.
    """
    _check_id(kind, record_id)
    with locked(run_dir, wait=None):
        try:
            run = load_run(run_dir)
        except (ValueError, OSError, RecursionError):   # a broken run.json is named by the data check; the new record stays
            return
        key = COUNTERS[kind]
        if isinstance(run, dict) and type(run.get(key)) is int:
            run[key] = max(run[key], int(record_id[1:]))
            save_run(run_dir, run)


def _check_id(kind: str, record_id) -> None:
    if not (isinstance(record_id, str) and _RECORD_ID[kind].fullmatch(record_id)):
        raise ValueError(f"a record id must be {kind} followed by digits, not {record_id!r}")


def _read_records(run_dir: Path, kind: str) -> dict[str, dict]:
    records = {}
    for _, path in _numbered_files(run_dir, kind):
        try:
            data = _read_json(path)
        except (ValueError, OSError, RecursionError):  # not valid JSON, too deeply nested or not readable text: Task 3 reports it
            continue
        if isinstance(data, dict):
            records[path.stem] = data
    return records


def add_based_on(run_dir: Path, source_id: str, on_id: str) -> list[str]:
    """Record that source `source_id` repeats or draws on `on_id`. Only ever adds; returns the source's based_on list.

    Refused (ValueError): an id that is no source of the run, a source based on itself, a link that would form a loop.
    """
    from .schema import _forms_loop   # schema imports this module
    run_dir = Path(run_dir)
    _check_id("S", source_id)
    _check_id("S", on_id)
    with locked(run_dir):
        sources = read_sources(run_dir)
        for record_id in (source_id, on_id):
            if record_id not in sources:
                raise ValueError(f"source {record_id} does not exist")
        if source_id == on_id:
            raise ValueError(f"source {source_id} cannot be based on itself")
        source = sources[source_id]
        current = source.get("based_on")
        if current is None:
            current = []
        if not isinstance(current, list):
            raise ValueError(f"based_on of source {source_id} is not a list")
        if on_id in current:
            return list(current)
        links = {key: [t for t in (record.get("based_on") or []) if isinstance(t, str) and t in sources]
                 if isinstance(record.get("based_on"), list) else []
                 for key, record in sources.items()}
        links[source_id] = links[source_id] + [on_id]
        if _forms_loop(source_id, links):
            raise ValueError(f"source {source_id} cannot be based on {on_id}: the links would form a loop")
        source["based_on"] = list(current) + [on_id]
        write_source(run_dir, source)
        return list(source["based_on"])


def write_source(run_dir: Path, source: dict) -> Path:
    _check_id("S", source.get("id"))
    return _write_json(Path(run_dir) / "sources" / f"{source['id']}.json", source)


def read_sources(run_dir: Path) -> dict[str, dict]:
    return _read_records(run_dir, "S")


def write_fact(run_dir: Path, fact: dict) -> Path:
    _check_id("F", fact.get("id"))
    return _write_json(Path(run_dir) / "facts" / f"{fact['id']}.json", fact)


def read_facts(run_dir: Path) -> dict[str, dict]:
    return _read_records(run_dir, "F")


def proposed_fact(proposal: dict, fact_id: str | None = None) -> dict:
    """The fact record a proposal becomes: defaults for missing keys, no checks yet, status `proposed`.

    The caller's id, checks, status and withdrawal are never taken over.
    """
    fact = {
        "id": fact_id,
        "kind": None,
        "statement": None,
        "quote": None,
        "quote_language": None,
        "quote_translation": None,
        "source_id": None,
        "supporting": [],
        "primary_source": None,
        "certainty": None,
        "tentative_reason": None,
        "early_signal": False,
        "fields": None,
    }
    fact.update(proposal)
    fact.pop("withdrawn", None)
    fact["id"] = fact_id
    fact["checks"] = {"quote": None, "supporting": [], "support": None}
    fact["status"] = "proposed"
    fact["status_reason"] = None
    return fact


def new_fact(run_dir: Path, proposal: dict) -> dict:
    """Write a proposal as a new fact under a freshly reserved id, and count it."""
    fact_id = reserve_id(run_dir, "F")
    fact = proposed_fact(proposal, fact_id)
    try:
        write_fact(run_dir, fact)
    except BaseException:   # give the id back: no empty record stays under it
        (Path(run_dir) / "facts" / f"{fact_id}.json").unlink(missing_ok=True)
        raise
    record_created(run_dir, "F", fact_id)
    return fact


def read_analysis(run_dir: Path) -> dict | None:
    path = Path(run_dir) / "analysis.json"
    return _read_json(path) if path.exists() else None


def write_analysis(run_dir: Path, analysis: dict) -> Path:
    return _write_json(Path(run_dir) / "analysis.json", analysis)


def write_changes(run_dir: Path, changes: dict) -> Path:
    return _write_json(Path(run_dir) / "changes.json", changes)


# --- checkpoints and logs -------------------------------------------------

def record_checkpoint(run_dir: Path, name: str, answered_by: str, answer: str,
                      now: datetime | None = None) -> None:
    if name not in CHECKPOINTS:
        raise ValueError(f"checkpoint name must be one of {', '.join(CHECKPOINTS)}")
    if answered_by not in ANSWERED_BY:
        raise ValueError(f"answered_by must be one of {', '.join(ANSWERED_BY)}")
    _append(run_dir, "checkpoints", {"name": name, "answered_by": answered_by, "answer": answer, "at": _stamp(now)})


def log_search(run_dir: Path, place: str, result: str) -> None:
    _append(run_dir, "search_log", {"place": place, "result": result})


def log_excluded(run_dir: Path, what: str, why: str, source_id: str | None = None) -> None:
    """Log something left out. With `source_id`, the entry also marks that saved source as read (a source whose
    proposals were all refused has no fact, and a resumed run must not read it twice). An unknown source is refused."""
    entry = {"what": what, "why": why}
    if source_id is not None:
        _check_id("S", source_id)
        if source_id not in read_sources(Path(run_dir)):
            raise ValueError(f"source {source_id} does not exist")
        entry["source_id"] = source_id
    _append(run_dir, "excluded", entry)


def _append(run_dir: Path, key: str, entry: dict) -> None:
    """Add one entry to a list in run.json, under the lock so a command running in parallel cannot lose it."""
    with locked(run_dir):
        run = load_run(run_dir)
        run[key].append(entry)
        save_run(run_dir, run)
