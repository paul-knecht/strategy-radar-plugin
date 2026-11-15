"""Where a run stands and what comes next, for someone who comes back to it later.

Everything here only reads: nothing is ever written to a run folder. The steps are worked out from what is
in the folder, so the answer is always current. The build step asks the gate, which only reads as well.
"""
from pathlib import Path

from . import store, verify
from .gate import gate

STEPS = ("collect", "extract", "verify", "checkpoint_lenses", "interpret", "checkpoint_final", "build")
_CHECKPOINT_STEPS = {"checkpoint_lenses": "lenses", "checkpoint_final": "final_report"}
_SETTLED = ("confirmed", "uncertain", "rejected")


def _step(name: str, state: str, detail: str) -> dict:
    return {"name": name, "state": state, "detail": detail}


def _recorded(run: dict) -> set:
    checkpoints = run.get("checkpoints")
    return {item.get("name") for item in checkpoints if isinstance(item, dict)} \
        if isinstance(checkpoints, list) else set()


def _count(facts: dict, status: str) -> int:
    return sum(1 for fact in facts.values() if fact.get("status") == status)


def _sources_to_read(run: dict, sources: dict, facts: dict) -> list[str]:
    """The saved sources nobody has read yet, in id order.

    A source counts as read when a fact names it (as its main source or in `supporting`, whatever the fact's
    status) or when an `excluded` entry names it in `source_id`: the run marks a source it read in full without
    finding a usable fact that way.
    """
    named = []
    for fact in facts.values():
        named.append(fact.get("source_id"))
        supporting = fact.get("supporting")
        named += [item.get("source_id") for item in supporting if isinstance(item, dict)] \
            if isinstance(supporting, list) else []
    excluded = run.get("excluded")
    named += [entry.get("source_id") for entry in excluded if isinstance(entry, dict)] \
        if isinstance(excluded, list) else []
    read = {item for item in named if isinstance(item, str)}   # a hand-edited value of another type names nothing
    unread = [key for key, source in sources.items() if source.get("access") == "ok" and key not in read]
    return sorted(unread, key=lambda key: (len(key), key))


def _counted(n: int, one: str, many: str) -> str:
    """`n` with its noun, in the singular for exactly one."""
    return f"{n} {one if n == 1 else many}"


def _extract_step(saved: int, facts: dict, to_read: list[str]) -> dict:
    detail = (f"{_counted(len(facts), 'fact', 'facts')} proposed, "
              f"{_counted(len(to_read), 'source', 'sources')} still to read")
    if saved - len(to_read) <= 0:   # nothing saved, or nothing read yet
        return _step("extract", "pending", detail)
    return _step("extract", "in_progress" if to_read else "done", detail)


def _verify_step(facts: dict, sources: dict, texts: dict, extract_done: bool) -> dict:
    """The verify step. A stored status is not taken on trust: a fact whose status no longer follows from its stored
    checks (by the rules the gate uses) must be settled again, and until then the step is not done."""
    counts = {status: _count(facts, status) for status in _SETTLED}
    open_facts = len(facts) - sum(counts.values())   # anything not settled still has to be checked
    detail = (f"{counts['confirmed']} confirmed, {counts['uncertain']} uncertain, "
              f"{counts['rejected']} rejected, {open_facts} still to check")
    again = sum(1 for fact in facts.values() if verify.needs_settling(fact, sources, texts))
    if again:
        detail += f"; {again} fact must be settled again" if again == 1 else f"; {again} facts must be settled again"
        return _step("verify", "in_progress", detail)
    if not facts:
        return _step("verify", "done", "no facts to check") if extract_done else _step("verify", "pending", detail)
    if open_facts == 0:
        return _step("verify", "done", detail)
    return _step("verify", "in_progress" if open_facts < len(facts) else "pending", detail)


def _checkpoint_step(name: str, recorded: set) -> dict:
    done = _CHECKPOINT_STEPS[name] in recorded
    return _step(name, "done" if done else "pending", "answered" if done else "waiting for your decision")


def _report_is_current(run_dir: Path) -> bool:
    """True when report.html is not older than anything it was built from: run.json, analysis.json, changes.json
    and every record under sources/ and facts/. A saved copy that changed is caught by the gate instead."""
    try:
        built = (run_dir / "report" / "report.html").stat().st_mtime_ns
    except OSError:   # no report yet
        return False
    inputs = [run_dir / "run.json", run_dir / "analysis.json", run_dir / "changes.json"]
    for folder in ("sources", "facts"):
        # a file whose name starts with a dot is not a record: a temporary file left by a killed write, or a folder's
        # own bookkeeping file
        inputs += [path for path in (run_dir / folder).rglob("*") if path.is_file() and not path.name.startswith(".")]
    newest = 0
    for path in inputs:
        try:
            newest = max(newest, path.stat().st_mtime_ns)
        except OSError:   # a file that does not exist does not make the report older
            continue
    return built >= newest


def _build_step(run_dir: Path, earlier_done: bool, lenses_dir: Path | None) -> dict:
    """Done only while the report is current and the gate would still let it be built."""
    current = _report_is_current(run_dir)
    problems = gate(run_dir, lenses_dir) if current or earlier_done else []
    if current and not problems:
        return _step("build", "done", "report built")
    if earlier_done and problems:
        return _step("build", "blocked", "1 problem" if len(problems) == 1 else f"{len(problems)} problems")
    return _step("build", "pending", "not built yet")


def run_status(run_dir: Path, lenses_dir: Path | None = None) -> dict:
    """The seven steps of a run with their state, the next step and whether it waits for the person."""
    run_dir = Path(run_dir)
    run = store.load_run(run_dir)
    if not isinstance(run, dict):
        raise ValueError("run.json is not a run")
    sources, facts = store.read_sources(run_dir), store.read_facts(run_dir)
    recorded = _recorded(run)

    saved = sum(1 for source in sources.values() if source.get("access") == "ok")
    refused = sum(1 for source in sources.values() if source.get("access") == "not_accessible")
    written = (run_dir / "analysis.json").exists()
    to_read = _sources_to_read(run, sources, facts)
    extract = _extract_step(saved, facts, to_read)
    steps = [
        _step("collect", "done" if saved else "pending",
              f"{_counted(saved, 'source', 'sources')} saved, {refused} not accessible"),
        extract,
        _verify_step(facts, sources, verify.copy_texts(run_dir, sources), extract["state"] == "done"),
        _checkpoint_step("checkpoint_lenses", recorded),
        _step("interpret", "done" if written else "pending", "analysis written" if written else "not written yet"),
        _checkpoint_step("checkpoint_final", recorded),
    ]
    steps.append(_build_step(run_dir, all(step["state"] == "done" for step in steps), lenses_dir))

    following = next((step["name"] for step in steps if step["state"] != "done"), None)
    return {"run_id": run.get("run_id"), "question": run.get("question"), "mode": run.get("mode"),
            "steps": steps, "sources_to_read": to_read, "next": following,
            "waiting_for_person": following in _CHECKPOINT_STEPS}


def list_runs(root: Path) -> list[dict]:
    """The runs under `root`, newest first. Folders without a readable run.json are left out. Each says whether the
    run is illustrative (only a `true` counts) and whether it is the practice run (it carries the practice mark)."""
    root = Path(root)
    if not root.is_dir():
        return []
    found = []
    for folder in sorted(root.iterdir()):
        try:
            if not folder.is_dir():
                continue
            run = store.load_run(folder)
            if not store.is_run_record(run):   # `{}` or a record without its lists is not a run
                continue
            following = run_status(folder)["next"]
        except (ValueError, OSError, RecursionError):   # not a run, or its run.json is broken
            continue
        started = run.get("started_at")
        found.append((started if isinstance(started, str) else "", folder.name, {
            "run_dir": str(folder), "run_id": run.get("run_id") or folder.name,
            "question": run.get("question"), "mode": run.get("mode"),
            "illustrative": run.get("illustrative") is True, "practice": store.is_demo_private_run(run),
            "next": following}))
    found.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in found]
