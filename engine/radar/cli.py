"""The radar command. Every subcommand prints one JSON object on one line.

Exit codes: 0 success, 1 problems found or gate refused, 2 usage error.
"""
import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

from . import (__version__, calc, claims, context, diff, fetch, join, lens_view, pack, parts, projects, recommend,
               setup_env, store, verify)
from .explain import explain
from .gate import gate
from .lenses import check_lenses
from .report.build import GateRefused, build_report
from .schema import Problem, check_data, check_proposal
from .status import list_runs, run_status


class UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs["allow_abbrev"] = False   # `--from` must never be read as `--from-json`, nor `--ack` as a flag
        super().__init__(*args, **kwargs)

    def error(self, message):
        raise UsageError(message)


# json.dumps leaves these three in a string as they are, and a reader that splits lines on them would cut the one
# line in two. In a JSON string the escape means the same character.
_LINE_BREAKS = {chr(0x85): "\\u0085", chr(0x2028): "\\u2028", chr(0x2029): "\\u2029"}


def _emit(obj: dict) -> None:
    """Print `obj` as one line of JSON. Never raises `UnicodeEncodeError`, whatever the terminal is set to.

    A stream with a byte buffer gets UTF-8 bytes, whatever its own encoding is. A stream without one is printed to
    with `ensure_ascii=True`, which only ever holds ASCII. Text that cannot be written as UTF-8 (a lone surrogate)
    is written as an escape in both cases. The line-break characters are escaped either way.
    """
    text = json.dumps(obj, ensure_ascii=False)
    for character, escape in _LINE_BREAKS.items():
        text = text.replace(character, escape)
    stream = sys.stdout
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        try:
            data = (text + "\n").encode("utf-8")
        except UnicodeEncodeError:
            data = (json.dumps(obj, ensure_ascii=True) + "\n").encode("ascii")
        stream.flush()   # whatever was printed before this goes out first
        buffer.write(data)
        buffer.flush()
    else:
        print(json.dumps(obj, ensure_ascii=True), file=stream)


def _read_pack(path: Path) -> tuple[dict | None, list[Problem]]:
    """The pack in `path` and what is wrong with it, by the pack check. Never raises."""
    data, unreadable = pack.load(path)
    return data, [unreadable] if unreadable else pack.check(data, path.name)


# The packs that ship with the plugin (packs/ next to engine/). Naming one by --pack reads its file, as --pack-file does,
# so a run on a shipped invented pack always carries the pack's illustrative mark.
SHIPPED_PACKS = Path(__file__).resolve().parents[2] / "packs"


def _shipped_pack(name: str) -> Path | None:
    """The file of the shipped pack named `name` (a plain pack id), or None. A name the look-up cannot ask about (one
    too long for a file name, say) names no shipped pack, so it is recorded as written."""
    path = SHIPPED_PACKS / f"{name}.json"
    try:
        return path if pack.is_pack_id(name) and path.is_file() else None
    except (OSError, ValueError):
        return None


def _cmd_init_run(args) -> int:
    pack_name, illustrative = args.pack, args.illustrative
    if args.acknowledged_words is not None and args.mode != "private":
        raise UsageError("--acknowledged-words goes with --mode private and --acknowledge-data-flow")
    pack_file = args.pack_file if args.pack_file is not None else _shipped_pack(args.pack)
    companies, screening = None, False
    if pack_file is not None:   # a pack with any problem starts no run
        data, problems = _read_pack(Path(pack_file))
        if problems:
            _emit(_problems_and_explanations(problems))
            return 1
        pack_name, illustrative = data["id"], illustrative or data["illustrative"] is True
        companies, screening = pack.companies_of(data), data.get("screening") is True
    try:
        run_dir = store.init_run(
            Path(args.root), args.question, pack_name, run_id=args.run_id,
            illustrative=illustrative, mode=args.mode,
            acknowledged=args.acknowledge_data_flow, home_company=args.home_company,
            acknowledged_words=args.acknowledged_words, companies=companies, screening=screening)
    except store.PrivateModeNotAcknowledged as exc:
        _emit({"error": str(exc), "notice": store.PRIVATE_NOTICE_TEXT})   # the plugin shows `notice`, never `error`
        return 2
    _emit({"run_dir": str(run_dir)})
    return 0


def _require_utf8(data, what: str) -> None:
    """Refuse data that cannot be written as UTF-8 (a lone surrogate), before anything is written."""
    todo = [data]
    while todo:
        item = todo.pop()
        if isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeEncodeError:
                raise UsageError(f"{what} holds text that cannot be saved as UTF-8")
        elif isinstance(item, dict):
            todo.extend(item.keys())
            todo.extend(item.values())
        elif isinstance(item, list):
            todo.extend(item)


def _cmd_add_fact(args) -> int:
    try:
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
        proposal = json.loads(text)
    except (OSError, ValueError, RecursionError) as exc:
        raise UsageError(f"cannot read the proposal: {exc}")
    if not isinstance(proposal, dict):
        raise UsageError("the proposal must be one JSON object")
    _require_utf8(proposal, "the proposal")
    problems = check_proposal(Path(args.run), proposal)
    if problems:
        raise UsageError("the proposal was refused: " + "; ".join(f"{p.field}: {p.message}" for p in problems))
    fact = store.new_fact(Path(args.run), proposal)
    _emit({"fact_id": fact["id"]})
    return 0


def _cmd_add_facts(args) -> int:
    try:
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
        proposals = json.loads(text)
    except (OSError, ValueError, RecursionError) as exc:
        raise UsageError(f"cannot read the proposals: {exc}")
    if not isinstance(proposals, list):
        raise UsageError("the proposals must be a JSON list")
    _require_utf8(proposals, "the proposals")
    run_dir = Path(args.run)
    store.load_run(run_dir)   # a folder that is not a run is a usage error, before anything is judged
    added, refused = [], []
    for index, proposal in enumerate(proposals):
        if not isinstance(proposal, dict):
            refused.append({"index": index, "reasons": ["proposal: must be one JSON object"]})
            continue
        problems = check_proposal(run_dir, proposal)
        if problems:
            refused.append({"index": index, "reasons": [f"{p.field}: {p.message}" for p in problems]})
        else:
            added.append({"index": index, "fact_id": store.new_fact(run_dir, proposal)["id"]})
    _emit({"added": added, "refused": refused})
    return 1 if refused else 0


def _sources_of(text: str) -> list[str]:
    """The source ids of `--sources`; a usage error unless each is `S` and digits, given once."""
    sources = text.split(",")
    if not all(join.SOURCE_ID.fullmatch(source_id) for source_id in sources) or len(set(sources)) < len(sources):
        raise UsageError("--sources must be source ids such as S3,S4, each once, separated by commas")
    return sources


def _cmd_join_proposals(args) -> int:
    sources = _sources_of(args.sources)
    merges = []
    if args.merges is not None:
        _require_file(Path(args.merges))
        try:
            merges = json.loads(Path(args.merges).read_text(encoding="utf-8"))
            join.check_merges(merges)
        except (OSError, ValueError, RecursionError) as exc:
            raise UsageError(f"cannot read the merges: {exc}")
    try:
        joined = join.join(Path(args.run), sources, merges)
    except join.JoinRefused as refused:   # nothing was written
        _emit(_problems_and_explanations(refused.problems))
        return 1
    store._write_json(Path(args.out), joined)   # whole or not at all
    _emit({"written": len(joined), "folded": sum(len(merge["fold"]) for merge in merges), "out": args.out})
    return 0


def _cmd_add_based_on(args) -> int:
    _emit({"ok": True, "based_on": store.add_based_on(Path(args.run), args.source, args.on)})
    return 0


def _cmd_checkpoint(args) -> int:
    store.record_checkpoint(Path(args.run), args.name, args.answered_by, args.answer)
    _emit({"ok": True})
    return 0


def _cmd_log_search(args) -> int:
    store.log_search(Path(args.run), args.place, args.result)
    _emit({"ok": True})
    return 0


def _cmd_log_excluded(args) -> int:
    store.log_excluded(Path(args.run), args.what, args.why, args.source)
    _emit({"ok": True})
    return 0


def _meta_from_args(args) -> dict:
    meta = {key: getattr(args, key) for key in
            ("publisher", "title", "date", "type", "speaker", "interest", "language")}
    meta["based_on"] = [part.strip() for part in (args.based_on or "").split(",") if part.strip()]
    return meta


def _cmd_save_source(args) -> int:
    _emit(fetch.save_source(Path(args.run), args.url, _meta_from_args(args)))
    return 0


def _cmd_add_copy(args) -> int:
    try:
        _emit(fetch.add_copy(Path(args.run), Path(args.file), args.url, _meta_from_args(args),
                             data_class=args.data_class, supplied_by=args.supplied_by, basis=args.basis))
    except (store.DemoRunRefused, store.PrivateRunNotIgnored) as exc:
        file = ".gitignore" if isinstance(exc, store.PrivateRunNotIgnored) else "run.json"
        _emit({"error": str(exc), "explained": [explain(Problem(file, None, str(exc)))]})
        return 2
    return 0


def _cmd_check_data(args) -> int:
    problems = check_data(Path(args.run), Path(args.lenses) if args.lenses else None)
    _emit(_problems_and_explanations(problems))
    return 1 if problems else 0


def _cmd_check_quotes(args) -> int:
    facts = verify.check_quotes(Path(args.run))
    failed = [fact_id for fact_id, checks in facts.items()
              if not checks["quote"]["passed"] or not all(entry["passed"] for entry in checks["supporting"])]
    _emit({"facts": facts, "failed": failed})
    return 0


_LINE_END = re.compile("\r\n|[\r\n" + chr(0x2028) + chr(0x2029) + "]")   # a line or paragraph separator too
_NOTE_LIMIT = 2000


def _stdin_text(missing: str, terminal: str, not_utf8: str) -> str:
    """Standard input as UTF-8 text. No standard input, standard input that is a terminal (nobody waits for typing)
    and text that is not valid UTF-8 are wrong use, each said in the caller's words."""
    stream = sys.stdin
    if stream is None:
        raise UsageError(missing)
    if stream.isatty():
        raise UsageError(terminal)
    buffer = getattr(stream, "buffer", None)
    try:
        if buffer is not None:
            text = buffer.read().decode("utf-8")
        else:
            text = stream.read()
            text.encode("utf-8")
    except UnicodeError:
        raise UsageError(not_utf8)
    return text


def _note_from_stdin() -> str:
    """The text of `--note-stdin` of `record-support` and `record-link-check`."""
    return _stdin_text("there is no standard input to read the note from",
                       "the note is expected on standard input, and standard input is a terminal. "
                       "Send the note as plain text on standard input, or give it with --note.",
                       "the note on standard input is not valid UTF-8 text. Send it as plain text.")


def _clean_note(text: str, where: str) -> str:
    """The note as it is stored, by one rule for `--note` and `--note-stdin`: the white space around it trimmed and
    each line end inside it (CR LF, LF, CR, a line or paragraph separator) turned into one space. A control or format
    character other than a line end or a tab, and a note longer than 2,000 characters, are wrong use."""
    if any(unicodedata.category(char) == "Cf" or (unicodedata.category(char) == "Cc" and char not in "\t\n\r")
           for char in text):
        raise UsageError(f"{where} holds a control character or another invisible character. Send it as plain text: "
                         "only line ends and tabs may be in it.")
    note = _LINE_END.sub(" ", text.strip())
    if len(note) > _NOTE_LIMIT:
        raise UsageError(f"{where} is longer than 2,000 characters. A note is one to three sentences: shorten it.")
    return note


def _note_of(args) -> str:
    """The cleaned note of `--note` or `--note-stdin`, exactly one of them."""
    if (args.note is None) != args.note_stdin:
        raise UsageError("give either --note or --note-stdin")
    if args.note_stdin:
        return _clean_note(_note_from_stdin(), "the note on standard input")
    return _clean_note(args.note, "the note")


def _cmd_record_support(args) -> int:
    note = _note_of(args)
    verify.record_support(Path(args.run), args.fact, args.passed == "true", args.by, note)
    _emit({"ok": True})
    return 0


def _cmd_withdraw_fact(args) -> int:
    verify.withdraw_fact(Path(args.run), args.fact, args.reason)
    _emit({"ok": True})
    return 0


def _cmd_settle(args) -> int:
    statuses = verify.settle(Path(args.run))
    counts = {name: 0 for name in store.STATUSES}
    for status in statuses.values():
        counts[status] += 1
    _emit({"status": statuses, "counts": counts})
    return 0


def _cmd_quote_context(args) -> int:
    if bool(args.fact) == bool(args.open):
        raise UsageError("give either --fact or --open")
    run_dir = Path(args.run)
    fact_ids = context.open_checks(run_dir) if args.open else [args.fact]
    _emit({"packets": [context.packet(run_dir, fact_id, args.sentences) for fact_id in fact_ids]})
    return 0


def _problems_and_explanations(problems) -> dict:
    """The problems as the command prints them, each followed by its plain-language explanation."""
    return {"problems": [{"file": p.file, "field": p.field, "message": p.message} for p in problems],
            "explained": [explain(p) for p in problems]}


def _cmd_gate(args) -> int:
    problems = gate(Path(args.run), Path(args.lenses) if args.lenses else None, args.publishable)
    _emit({"open": not problems, **_problems_and_explanations(problems)})
    return 1 if problems else 0


def _cmd_build_report(args) -> int:
    run_dir = Path(args.run)
    try:
        paths = build_report(run_dir, Path(args.lenses), args.publishable)
    except GateRefused as refused:
        _emit({"built": [], **_problems_and_explanations(refused.problems)})
        return 1
    _emit({"built": [path.relative_to(run_dir).as_posix() for path in paths]})
    return 0


def _id_list(text: str | None) -> list[str]:
    return [part.strip() for part in (text or "").split(",") if part.strip()]


def _cmd_calc(args) -> int:
    run_dir = Path(args.run)
    store.load_run(run_dir)   # a folder that is not a run is a usage error, not a calculation with no facts
    part_ids = _id_list(args.facts)
    if not part_ids:
        raise UsageError("give at least one fact id with --facts")
    calculation = {"operation": args.operation, "unit": args.unit, "fact_ids": part_ids,
                   "of_fact_ids": _id_list(args.of)}
    facts, sources = store.read_facts(run_dir), store.read_sources(run_dir)
    unsettled = calc.settle_first(part_ids + calculation["of_fact_ids"], facts, sources,
                                  verify.copy_texts(run_dir, sources))
    if unsettled:   # refused: a total never rests on a status that settle would change
        result = calc.CalcResult(None, False, unsettled)
    else:
        result = calc.compute(calculation, facts, sources)
    _emit({"result": result.value, "includes_uncertain": result.includes_uncertain, "problems": result.problems,
           "explained": [explain(Problem("analysis.json", None, message)) for message in result.problems]})
    return 1 if result.problems else 0


def _cmd_status(args) -> int:
    if bool(args.run) == bool(args.root):
        raise UsageError("give either --run or --root")
    if args.run:
        _emit(run_status(Path(args.run), Path(args.lenses) if args.lenses else None))
    else:
        _emit({"runs": list_runs(Path(args.root))})
    return 0


def _cmd_compare(args) -> int:
    try:
        changes = diff.compare_runs(Path(args.previous), Path(args.current), args.today)
    except diff.CompareRefused as refused:   # nothing is written
        _emit({"error": str(refused), "explained": [explain(Problem("changes.json", None, str(refused)))]})
        return 2
    store.write_changes(Path(args.current), changes)
    _emit(changes)
    return 0


def _cmd_check_pack(args) -> int:
    data, problems = _read_pack(Path(args.file))
    months = None if data is None else pack.months_of(data)
    _emit({**_problems_and_explanations(problems),
           "pack": None if data is None else pack.summary(data),
           "window": None if months is None else pack.window(months, args.today or date.today())})
    return 1 if problems else 0


def _cmd_check_lenses(args) -> int:
    problems = check_lenses(Path(args.lenses), real=args.real)
    _emit(_problems_and_explanations(problems))
    return 1 if problems else 0


def _cmd_list_lenses(args) -> int:
    try:
        listing = lens_view.list_lenses(Path(args.lenses))
    except lens_view.LensFolderUnreadable as unreadable:
        raise UsageError(str(unreadable))
    _emit(listing)
    return 0


def _cmd_lens_view(args) -> int:
    try:
        view = lens_view.run_view(Path(args.run), Path(args.lenses))
    except lens_view.LensFolderUnreadable as unreadable:
        raise UsageError(str(unreadable))
    _emit(view)
    return 0


RECOMMENDATION_KEYS = ("entries", "note")


def _cmd_record_lens_recommendation(args) -> int:
    what = "the lens recommendation"
    if args.list_stdin:
        text = _stdin_text(f"there is no standard input to read {what} from",
                           f"{what} is expected on standard input, and standard input is a terminal. Send it as "
                           "plain lines on standard input, or name a file with --file.",
                           f"{what} on standard input is not valid UTF-8 text. Send it as plain text.")
        try:
            entries, note = recommend.parse_list_lines(text)
        except ValueError as malformed:
            raise UsageError(str(malformed))
        data = {"entries": entries, "note": note}
    else:
        data = _recommendation_file(args.file, what)
    _require_utf8(data, what)
    try:
        recommend.record_recommendation(Path(args.run), Path(args.lenses), data["entries"], data.get("note"), args.by)
    except recommend.RecommendationRefused as refused:   # nothing was written
        _emit({"recorded": False, **_problems_and_explanations(refused.problems)})
        return 1
    _emit({"recorded": True, **_problems_and_explanations([])})
    return 0


def _recommendation_file(file: str, what: str) -> dict:
    """The JSON object of `--file` (a path, or '-' for standard input), with exactly its keys; a usage error
    otherwise."""
    try:
        if file == "-":
            text = _stdin_text(f"there is no standard input to read {what} from",
                               f"{what} is expected on standard input, and standard input is a terminal. Send it as "
                               "JSON text on standard input, or name a file with --file.",
                               f"{what} on standard input is not valid UTF-8 text. Send it as plain JSON text.")
        else:
            text = Path(file).read_text(encoding="utf-8")
        data = json.loads(text, object_pairs_hook=_object_without_repeats)   # a key given twice is refused
    except (OSError, ValueError, RecursionError) as exc:
        raise UsageError(f"cannot read {what}: {exc}")
    if not isinstance(data, dict) or "entries" not in data or not set(data) <= set(RECOMMENDATION_KEYS):
        raise UsageError(f'{what} must be one JSON object with "entries" (a list) and, if wanted, "note"')
    return data


def _part_number(text: str) -> int:
    """The number of `--part`: a positive whole number written plainly, such as 2."""
    if not re.fullmatch(r"[1-9][0-9]*", text):
        raise argparse.ArgumentTypeError(f"a part is a positive whole number, such as 2, not {text!r}")
    return int(text)


def _emit_part(found: list[dict], asked: int) -> int:
    """Print part `asked` of `found`; a part that is not there is a problem (exit 1) that names how many there are."""
    if asked > len(found):
        _emit(_problems_and_explanations([Problem(None, "part", parts.no_such_part(asked, len(found)))]))
        return 1
    _emit(found[asked - 1])
    return 0


def _cmd_lens_advisor_input(args) -> int:
    try:
        found = recommend.advisor_parts(Path(args.run), Path(args.lenses))
    except lens_view.LensFolderUnreadable as unreadable:
        raise UsageError(str(unreadable))
    return _emit_part(found, args.part)


def _cmd_lens_link_context(args) -> int:
    try:
        found = recommend.link_parts(Path(args.run), Path(args.lenses))
    except lens_view.LensFolderUnreadable as unreadable:
        raise UsageError(str(unreadable))
    return _emit_part(found, args.part)


def _cmd_record_link_check(args) -> int:
    note = _note_of(args)
    recommend.record_link_check(Path(args.run), args.lens, args.fact, args.verdict, args.by, note)
    _emit({"ok": True})
    return 0


def _cmd_project_grouper_input(args) -> int:
    return _emit_part(projects.grouper_parts(Path(args.run)), args.part)


def _cmd_record_projects(args) -> int:
    what = "the projects"
    if args.list_stdin:
        text = _stdin_text(f"there is no standard input to read {what} from",
                           f"{what} are expected on standard input, and standard input is a terminal. Send them as "
                           "plain lines on standard input, or name a file with --file.",
                           f"{what} on standard input are not valid UTF-8 text. Send them as plain text.")
        try:
            given = projects.parse_list_lines(text)
        except ValueError as malformed:
            raise UsageError(str(malformed))
    else:
        given = _projects_file(args.file, what)
    _require_utf8(given, what)
    try:
        projects.record_projects(Path(args.run), given, args.by)
    except projects.ProjectsRefused as refused:   # nothing was written
        _emit({"recorded": False, **_problems_and_explanations(refused.problems)})
        return 1
    _emit({"recorded": True, **_problems_and_explanations([])})
    return 0


def _cmd_claim_matcher_input(args) -> int:
    try:
        found = claims.matcher_parts(Path(args.run), _sources_of(args.sources))
    except join.JoinRefused as refused:
        _emit(_problems_and_explanations(refused.problems))
        return 1
    return _emit_part(found, args.part)


def _cmd_record_claim_groups(args) -> int:
    sources, what = _sources_of(args.sources), "the claim groups"
    text = _stdin_text(f"there is no standard input to read {what} from",
                       f"{what} are expected on standard input, and standard input is a terminal. Send them as "
                       "plain lines on standard input.",
                       f"{what} on standard input are not valid UTF-8 text. Send them as plain text.")
    try:
        groups = claims.parse_group_lines(text.splitlines())
    except ValueError as malformed:
        raise UsageError(str(malformed))
    try:
        problems = claims.record_groups(Path(args.run), sources, groups, args.by)
    except join.JoinRefused as refused:   # a source without a saved answer; nothing was written
        problems = refused.problems
    _emit({"recorded": not problems, **_problems_and_explanations(problems)})
    return 1 if problems else 0


def _projects_file(file: str, what: str) -> list:
    """The projects of `--file`: one JSON object with exactly the key "projects", a list of objects with exactly a
    name (a text) and a non-empty list of fact ids (texts); a usage error otherwise."""
    try:
        data = json.loads(Path(file).read_text(encoding="utf-8"), object_pairs_hook=_object_without_repeats)
    except (OSError, ValueError, RecursionError) as exc:
        raise UsageError(f"cannot read {what}: {exc}")
    given = data.get("projects") if isinstance(data, dict) and set(data) == {"projects"} else None
    if not (projects._well_formed(given) and all(isinstance(project["name"], str) for project in given)):
        raise UsageError(f'{what} must be one JSON object {{"projects": [...]}}, each project {{"name", "fact_ids"}} '
                         "with its name as text and its fact ids as a list of at least one text")
    return given


def _cmd_demo(args) -> int:
    from . import demo   # here and not at the top: the demo builder itself imports this module
    variant = args.variant
    try:
        run_dir = demo.build_demo_run(Path(args.root), changed=variant == "changed", private=variant == "private",
                                      tampered=variant == "tampered", stage=args.stage)
    except demo.DemoError as exc:
        raise UsageError(str(exc))
    printed = {"run_dir": str(run_dir), "lenses": str(demo.LENSES), "sources": str(demo.SOURCES)}
    if variant == "private":
        printed["notice"] = demo.PRIVATE_DEMO_NOTICE
    _emit(printed)
    return 0


# The plugin's guard, started the way the hook starts it: hooks/guard.sh of the folder that holds engine/.
GUARD_LAUNCHER = Path(__file__).resolve().parents[2] / "hooks" / "guard.sh"
GUARD_HINT = ("Strategy Radar's guard cannot run on this computer, so nothing stops a hand-made change to a run's "
              "records before the final check refuses the report. Install Python from python.org, or install the "
              "plugin again.")


def _guard_state() -> str:
    """`ok` when the guard, started as the hook starts it (sh, its launcher, this computer's settings), refuses a
    made-up write to the record of a made-up run in a temporary folder; `not_running` when it lets the write through
    or cannot be started. It tells whether the guard can run here, not whether Claude Code has loaded the hook."""
    import subprocess
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as scratch:
            run = Path(scratch) / "run"
            for folder in ("sources", "facts"):
                (run / folder).mkdir(parents=True)
            (run / "run.json").write_text("{}\n", encoding="utf-8")
            event = {"hook_event_name": "PreToolUse", "tool_name": "Write", "cwd": scratch,
                     "tool_input": {"file_path": str(run / "facts" / "F1.json"), "content": "{}"}}
            done = subprocess.run(["/bin/sh", str(GUARD_LAUNCHER)], input=json.dumps(event).encode("utf-8"),
                                  capture_output=True, timeout=30, cwd=scratch)
    except (OSError, subprocess.SubprocessError):
        return "not_running"
    return "ok" if done.returncode == 2 else "not_running"


def _cmd_doctor(args) -> int:
    python_ok = sys.version_info >= (3, 10)
    try:
        import pypdf
        pypdf_version = pypdf.__version__
    except ImportError:
        pypdf_version = None
    pypdf_ok = pypdf_version is not None
    private = setup_env.is_private(sys.executable, setup_env.default_home())
    guard = _guard_state()
    _emit({"python": "{}.{}.{}".format(*sys.version_info[:3]), "python_ok": python_ok, "python_path": sys.executable,
           "pypdf": pypdf_version, "pypdf_ok": pypdf_ok, "environment": "private" if private else "other",
           "hint": None if pypdf_ok else "Run: radar setup",
           "guard": guard, "guard_hint": None if guard == "ok" else GUARD_HINT})
    return 0 if python_ok and pypdf_ok else 1


def _cmd_setup(args) -> int:
    home = Path(os.path.abspath(args.home or setup_env.default_home()))   # never read as an option by a later command
    if home.exists() and not home.is_dir():
        raise UsageError(f"The folder for the private environment, {home}, is a file, so choose another folder.")
    if args.dry_run:
        _emit({"would_run": setup_env.commands(home, sys.executable)})
        return 0
    _emit(setup_env.setup(home, sys.executable))   # a command that fails is a ValueError: one plain line, exit 2
    return 0


def _iso_date(text: str) -> date:
    try:
        if len(text) != 10:
            raise ValueError(text)
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date in the form YYYY-MM-DD: {text}")


def _add_meta_options(p) -> None:
    p.add_argument("--publisher", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--type", required=True, choices=store.SOURCE_TYPES)
    p.add_argument("--speaker", required=True)
    p.add_argument("--interest", required=True)
    p.add_argument("--language", required=True)
    p.add_argument("--based-on", help="comma-separated ids of the sources this one repeats or draws on")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="radar", description="Strategy Radar engine")
    parser.add_argument("--version", action="store_true", help="print the version as JSON")
    sub = parser.add_subparsers(dest="command", metavar="command")

    p = sub.add_parser("init-run", help="create a run folder")
    p.add_argument("--root", required=True)
    p.add_argument("--question", required=True)
    which_pack = p.add_mutually_exclusive_group(required=True)
    which_pack.add_argument("--pack", help="the name of the pack; a pack that ships with the plugin (packs/NAME.json) is "
                                           "read as --pack-file reads it, any other name is taken as written")
    which_pack.add_argument("--pack-file", metavar="FILE",
                            help="a pack file; it is checked first, and the run takes its id and its illustrative mark")
    p.add_argument("--run-id")
    p.add_argument("--illustrative", action="store_true")
    p.add_argument("--home-company")
    p.add_argument("--mode", choices=store.RUN_MODES, default="public")
    p.add_argument("--acknowledge-data-flow", action="store_true")
    p.add_argument("--acknowledged-words", metavar="TEXT",
                   help="with --mode private: the person's own reply to the private-mode notice, word for word")
    p.set_defaults(func=_cmd_init_run)

    p = sub.add_parser("add-fact", help="add one proposed fact from a JSON file ('-' reads stdin)")
    p.add_argument("--run", required=True)
    p.add_argument("--file", required=True)
    p.set_defaults(func=_cmd_add_fact)

    p = sub.add_parser("add-facts", help="add every proposal of a JSON list; the good ones are written, the bad ones named")
    p.add_argument("--run", required=True)
    p.add_argument("--file", required=True, help="a JSON list of proposals ('-' reads stdin)")
    p.set_defaults(func=_cmd_add_facts)

    p = sub.add_parser("join-proposals", help="join the extractors' saved answers into one list for add-facts, "
                                              "unchanged; a merges file names the proposals to fold")
    p.add_argument("--run", required=True)
    p.add_argument("--sources", required=True, help="the source ids whose answers proposals/<id>.json are joined, "
                                                    "separated by commas, such as S3,S4")
    p.add_argument("--merges", metavar="FILE", help='a JSON list of {"keep": "S29#1", "fold": ["S21#2"]}')
    p.add_argument("--out", required=True, metavar="FILE", help="the list file to write, such as proposals/all.json")
    p.set_defaults(func=_cmd_join_proposals)

    p = sub.add_parser("checkpoint", help="record a checkpoint answer")
    p.add_argument("--run", required=True)
    p.add_argument("--name", required=True, choices=store.CHECKPOINTS)
    p.add_argument("--answered-by", required=True, choices=store.ANSWERED_BY)
    p.add_argument("--answer", required=True)
    p.set_defaults(func=_cmd_checkpoint)

    p = sub.add_parser("log-search", help="log a place that was searched")
    p.add_argument("--run", required=True)
    p.add_argument("--place", required=True)
    p.add_argument("--result", required=True)
    p.set_defaults(func=_cmd_log_search)

    p = sub.add_parser("log-excluded", help="log something that was left out")
    p.add_argument("--run", required=True)
    p.add_argument("--what", required=True)
    p.add_argument("--why", required=True)
    p.add_argument("--source", default=None, help="a saved source that was read and gave nothing usable, such as S4")
    p.set_defaults(func=_cmd_log_excluded)

    p = sub.add_parser("save-source", help="download a public page or text PDF and save a checked text copy")
    p.add_argument("--run", required=True)
    p.add_argument("--url", required=True)
    _add_meta_options(p)
    p.set_defaults(func=_cmd_save_source)

    p = sub.add_parser("add-copy", help="save a file you exported or saved yourself as a source")
    p.add_argument("--run", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--url", required=True, help="the page address, or where the document lives")
    p.add_argument("--data-class", choices=store.DATA_CLASSES, required=True,
                   help="public, licensed or internal; there is no default, so a file of the person's own is never "
                        "taken for public without a word")
    p.add_argument("--supplied-by")
    p.add_argument("--basis")
    _add_meta_options(p)
    p.set_defaults(func=_cmd_add_copy)

    p = sub.add_parser("add-based-on", help="record that a source repeats or draws on another one; only ever adds")
    p.add_argument("--run", required=True)
    p.add_argument("--source", required=True, help="the source that repeats or draws on another, for example S6")
    p.add_argument("--on", required=True, help="the source it repeats or draws on, for example S1")
    p.set_defaults(func=_cmd_add_based_on)

    p = sub.add_parser("check-data", help="check every record of a run; exit 1 if there are problems")
    p.add_argument("--run", required=True)
    p.add_argument("--lenses")
    p.set_defaults(func=_cmd_check_data)

    p = sub.add_parser("check-quotes", help="check every quote against its saved copy")
    p.add_argument("--run", required=True)
    p.set_defaults(func=_cmd_check_quotes)

    p = sub.add_parser("record-support", help="record whether a quote supports its fact")
    p.add_argument("--run", required=True)
    p.add_argument("--fact", required=True)
    p.add_argument("--passed", required=True, choices=("true", "false"))
    p.add_argument("--by", required=True)
    p.add_argument("--note", help="why, in a sentence; give this or --note-stdin")
    p.add_argument("--note-stdin", action="store_true",
                   help="read the note as plain text from standard input, so it never goes onto the command line; "
                        "give this or --note")
    p.set_defaults(func=_cmd_record_support)

    p = sub.add_parser("withdraw-fact", help="withdraw a fact with a reason; it is kept and settles as rejected")
    p.add_argument("--run", required=True)
    p.add_argument("--fact", required=True)
    p.add_argument("--reason", required=True)
    p.set_defaults(func=_cmd_withdraw_fact)

    p = sub.add_parser("quote-context", help="give the checker each quote with the sentences around it")
    p.add_argument("--run", required=True)
    p.add_argument("--fact", help="the fact to read, for example F3")
    p.add_argument("--open", action="store_true",
                   help="every fact whose quotes are found and whose support check is missing or out of date")
    p.add_argument("--sentences", type=int, choices=range(0, 4), default=1, metavar="{0..3}",
                   help="how many sentences to show on each side of the passage (default 1)")
    p.set_defaults(func=_cmd_quote_context)

    p = sub.add_parser("settle", help="settle every fact's status from its checks")
    p.add_argument("--run", required=True)
    p.set_defaults(func=_cmd_settle)

    p = sub.add_parser("gate", help="re-run every check; exit 1 if the report may not be built")
    p.add_argument("--run", required=True)
    p.add_argument("--lenses")
    p.add_argument("--publishable", action="store_true", help="also refuse sources that are not public")
    p.set_defaults(func=_cmd_gate)

    p = sub.add_parser("build-report", help="re-run the gate and build the report; exit 1 if the gate refuses")
    p.add_argument("--run", required=True)
    p.add_argument("--lenses", required=True)
    p.add_argument("--publishable", action="store_true", help="also refuse sources that are not public")
    p.set_defaults(func=_cmd_build_report)

    p = sub.add_parser("status", help="say where a run stands and what comes next, or list the runs in a folder")
    p.add_argument("--run")
    p.add_argument("--root", help="list every run in this folder, newest first")
    p.add_argument("--lenses")
    p.set_defaults(func=_cmd_status)

    p = sub.add_parser("calc", help="compute a total, a count or a share from facts of the run; changes nothing")
    p.add_argument("--run", required=True)
    p.add_argument("--operation", required=True, choices=store.CALC_OPERATIONS)
    p.add_argument("--unit", help="the unit all sizes are stated in; needed for sum and share")
    p.add_argument("--facts", required=True, help="comma-separated fact ids, for example F1,F2")
    p.add_argument("--of", help="for share: comma-separated fact ids of the whole the facts are a part of")
    p.set_defaults(func=_cmd_calc)

    p = sub.add_parser("compare", help="compare two runs; writes changes.json into the current run")
    p.add_argument("--previous", required=True)
    p.add_argument("--current", required=True)
    p.add_argument("--today", type=_iso_date, help="the date predictions are checked against (YYYY-MM-DD)")
    p.set_defaults(func=_cmd_compare)

    p = sub.add_parser("check-pack", help="check a company pack and work out its time window; exit 1 if there are problems")
    p.add_argument("--file", required=True, help="the pack, for example packs/demo.json")
    p.add_argument("--today", type=_iso_date, help="the last day of the time window (YYYY-MM-DD); today if left out")
    p.set_defaults(func=_cmd_check_pack)

    p = sub.add_parser("check-lenses", help="check every lens in a folder by the rule the gate uses; exit 1 if there "
                                            "are problems")
    p.add_argument("--lenses", required=True, help="the folder of the lens files")
    p.add_argument("--real", action="store_true",
                   help="also require the day each lens was checked and refuse an illustrative reference, as for a "
                        "lens that ships with the plugin")
    p.set_defaults(func=_cmd_check_lenses)

    p = sub.add_parser("list-lenses", help="print every lens in a folder, grouped by theme, with its level in plain words")
    p.add_argument("--lenses", required=True, help="the folder of the lens files")
    p.set_defaults(func=_cmd_list_lenses)

    p = sub.add_parser("record-lens-recommendation",
                       help="check the lens advisor's list by its form and record it; exit 1 if it is refused")
    p.add_argument("--run", required=True)
    p.add_argument("--lenses", required=True, help="the folder of the lens files")
    p.add_argument("--by", required=True, help="who made the list; only the lens advisor may record it")
    which_list = p.add_mutually_exclusive_group(required=True)
    which_list.add_argument("--file", help='a JSON object {"entries": [...], "note": ...} (\'-\' reads stdin)')
    which_list.add_argument("--list-stdin", action="store_true",
                            help="read the list from standard input in plain lines, key: value, a blank line between "
                                 "entries, so no curly bracket goes into the command; give this or --file")
    p.set_defaults(func=_cmd_record_lens_recommendation)

    p = sub.add_parser("lens-view", help="print what the first stop shows: the lens advisor's list as recorded, whether it "
                                         "is out of date, the readers' marks, and every other lens; changes nothing")
    p.add_argument("--run", required=True)
    p.add_argument("--lenses", required=True, help="the folder of the lens files")
    p.set_defaults(func=_cmd_lens_view)

    p = sub.add_parser("lens-advisor-input", help="print what the lens advisor reads: the question, the frame, every "
                                                  "lens and the facts that count, in parts; changes nothing")
    p.add_argument("--run", required=True)
    p.add_argument("--lenses", required=True, help="the folder of the lens files")
    p.add_argument("--part", type=_part_number, default=1, help="the part to print, 1 when not given; part 1 says "
                                                                 "how many parts there are")
    p.set_defaults(func=_cmd_lens_advisor_input)

    p = sub.add_parser("lens-link-context", help="print what the link readers read: each suggested lens beside each "
                                                 "of its facts, without the advisor's reasons, in parts; changes "
                                                 "nothing")
    p.add_argument("--run", required=True)
    p.add_argument("--lenses", required=True, help="the folder of the lens files")
    p.add_argument("--part", type=_part_number, default=1, help="the part to print, 1 when not given; part 1 says "
                                                                 "how many parts there are")
    p.set_defaults(func=_cmd_lens_link_context)

    p = sub.add_parser("record-link-check", help="record a link reader's verdict on one lens and one of its facts")
    p.add_argument("--run", required=True)
    p.add_argument("--lens", required=True, help="the lens of the link, for example firm-boundaries")
    p.add_argument("--fact", required=True, help="the fact of the link, for example F3")
    p.add_argument("--verdict", required=True, choices=recommend.VERDICTS,
                   help="bears when the fact bears on one of the lens's questions, doubt when it does not or it is unclear")
    p.add_argument("--by", required=True, help="the link reader; only lens-link-reader and lens-link-reader-quick are taken")
    p.add_argument("--note", help="why, in a sentence; a doubt needs one; give this or --note-stdin")
    p.add_argument("--note-stdin", action="store_true",
                   help="read the note as plain text from standard input, so it never goes onto the command line; "
                        "give this or --note")
    p.set_defaults(func=_cmd_record_link_check)

    p = sub.add_parser("project-grouper-input", help="print what the project grouper reads: the question and every "
                                                     "capacity move that counts, its company and countries tidied; "
                                                     "in parts; changes nothing")
    p.add_argument("--run", required=True)
    p.add_argument("--part", type=_part_number, default=1, help="the part to print, 1 when not given; part 1 says "
                                                                 "how many parts there are")
    p.set_defaults(func=_cmd_project_grouper_input)

    p = sub.add_parser("record-projects",
                       help="check the project grouper's grouping of the capacity moves and record it; exit 1 if it is "
                            "refused")
    p.add_argument("--run", required=True)
    p.add_argument("--by", required=True, help="who made the grouping; only the project grouper may record it")
    which_list = p.add_mutually_exclusive_group(required=True)
    which_list.add_argument("--file", help='a JSON object {"projects": [{"name": ..., "fact_ids": [...]}]}')
    which_list.add_argument("--list-stdin", action="store_true",
                            help="read the projects from standard input in plain lines, project: NAME and facts: F1, "
                                 "F2, a blank line between projects; give this or --file")
    p.set_defaults(func=_cmd_record_projects)

    p = sub.add_parser("claim-matcher-input", help="print what the claim matcher reads: the question and every "
                                                   "proposal of this round's saved answers, with its place and quote; "
                                                   "in parts; changes nothing")
    p.add_argument("--run", required=True)
    p.add_argument("--sources", required=True, help="the source ids of this round, separated by commas, such as S3,S4")
    p.add_argument("--part", type=_part_number, default=1, help="the part to print, 1 when not given; part 1 says "
                                                                 "how many parts there are")
    p.set_defaults(func=_cmd_claim_matcher_input)

    p = sub.add_parser("record-claim-groups",
                       help="check the claim matcher's groups of proposals that state the same claim and write them "
                            "as proposals/merges.json; exit 1 if they are refused")
    p.add_argument("--run", required=True)
    p.add_argument("--sources", required=True, help="the source ids of this round, separated by commas, such as S3,S4")
    p.add_argument("--by", required=True, help="who made the groups; only the claim matcher may record them")
    p.add_argument("--list-stdin", action="store_true", required=True,
                   help="read the groups from standard input in plain lines, keep: S6#1 and fold: S2#3, S9#1, a "
                        "blank line between groups; no line means no groups")
    p.set_defaults(func=_cmd_record_claim_groups)

    p = sub.add_parser("demo", help="build the invented demo run, all of it or up to a stage; the folder must not exist")
    p.add_argument("--root", required=True, help="the folder the demo run folder is made in")
    p.add_argument("--variant", choices=("base", "changed", "private", "tampered"), default="base",
                   help="changed: a second version for a comparison; private: adds an invented internal "
                        "document (the run is invented, its private-mode notice was not shown to anyone, and "
                        "it cannot take further non-public material); tampered: a finished run that "
                        "build-report refuses")
    p.add_argument("--stage", choices=("sources", "extracted", "checked", "complete"), default="complete",
                   help="how far to build the run; tampered needs complete")
    p.set_defaults(func=_cmd_demo)

    p = sub.add_parser("doctor", help="check that Python and pypdf are usable, say which Python runs and whether the "
                                      "guard can run here; exit 1 if Python or pypdf is not usable")
    p.set_defaults(func=_cmd_doctor)

    p = sub.add_parser("setup", help="make a private Python environment with pypdf in it; running it again repairs it")
    p.add_argument("--home", help="the folder that holds the environment (default: $RADAR_HOME or ~/.strategy-radar)")
    p.add_argument("--dry-run", action="store_true", help="print the two commands and change nothing")
    p.set_defaults(func=_cmd_setup)

    for command in sub.choices.values():
        command.add_argument("--from-json", metavar="FILE",
                             help="take the options from a JSON object in FILE ('-' reads stdin), so text never "
                                  "goes onto the command line")
    return parser


def _require_file(path: Path) -> None:
    """Refuse, as wrong use and in plain words, a named file that is a folder or is not there."""
    if path.is_dir():
        raise UsageError(f"{path} is a folder, not a file. Give the path of a file.")
    if not path.is_file():
        raise UsageError(f"{path} does not exist. Give the path of a file.")


# --- --from-json ------------------------------------------------------------------------

FROM_JSON = "--from-json"
LIST_OPTIONS = ("--based-on",)   # the options that take a list of ids; the file may hold a JSON list for them


def _option_strings(subparser) -> list[str]:
    return [name for name in subparser._option_string_actions if name.startswith("--") and name != "--help"]


def _option_name(token: str, options: list[str]) -> str | None:
    """The option a command-line token names (`--title` or `--title=x`), else None. Abbreviations are not accepted."""
    name = token.split("=", 1)[0] if token.startswith("--") else None
    return name if name in options else None


class _Number(str):
    """A number of the option file, kept as the text it was written with (2.50 stays 2.50)."""


def _object_without_repeats(pairs):
    keys = [key for key, _ in pairs]
    repeated = sorted({key for key in keys if keys.count(key) > 1})
    if repeated:
        raise ValueError("the key " + repeated[0] + " appears twice")
    return dict(pairs)


def _no_such_number(constant: str):
    raise ValueError(f"{constant} is not a number")


def _read_option_file(source: str) -> dict:
    if source != "-":
        _require_file(Path(source))
    try:
        text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
        data = json.loads(text, object_pairs_hook=_object_without_repeats, parse_int=_Number, parse_float=_Number,
                          parse_constant=_no_such_number)
    except (OSError, ValueError, RecursionError) as exc:
        raise UsageError(f"cannot read the {FROM_JSON} file: {exc}")
    if not isinstance(data, dict):
        raise UsageError(f"the {FROM_JSON} file must hold one JSON object")
    _require_utf8(data, f"the {FROM_JSON} file")
    return data


def _tokens_from_object(data: dict, options: list[str],
                        true_or_false: frozenset = frozenset()) -> tuple[list[str], set[str]]:
    """One `--key=value` argument per key: a value that starts with "-" is then never read as an option.

    For a switch, `true` becomes the bare flag; `false` and `null` leave the key out, so a false never switches
    anything on. For an option in `true_or_false` (its allowed values are the texts true and false), `true` and
    `false` are passed on as those texts. Returns the arguments and the names of every option the file mentions,
    whatever its value.
    """
    taken = set(options) - {FROM_JSON}
    tokens, seen = [], set()
    for key, value in data.items():
        name = "--" + key.replace("_", "-")
        if name not in taken:
            raise UsageError(f"{key!r} is not an option of this command")
        if name in seen:
            raise UsageError(f"given twice: {name}")
        seen.add(name)
        if name in true_or_false and (value is True or value is False):
            tokens.append(f"{name}={'true' if value else 'false'}")
            continue
        if value is None or value is False:
            continue
        if value is True:
            tokens.append(name)
        elif isinstance(value, (str, int, float)):
            tokens.append(f"{name}={value}")
        elif isinstance(value, list) and name in LIST_OPTIONS:
            if not all(isinstance(item, str) and not isinstance(item, _Number) and item.strip() and "," not in item
                       for item in value):
                raise UsageError(f"{key!r} must be a list of plain ids")
            tokens.append(f"{name}={','.join(value)}")
        else:
            raise UsageError(f"{key!r} must be text, a number, true or false")
    return tokens, seen


def _expand_from_json(parser, argv: list[str]) -> list[str]:
    """Replace `--from-json FILE` in `argv` by the options the file holds."""
    positions = [i for i, token in enumerate(argv) if token == FROM_JSON or token.startswith(FROM_JSON + "=")]
    if not positions:
        return argv
    commands = next((action.choices for action in parser._actions if getattr(action, "choices", None)), {})
    command = next((token for token in argv if not token.startswith("-")), None)
    if command not in commands:
        return argv   # parse_args names the problem
    if len(positions) > 1:
        raise UsageError(f"given twice: {FROM_JSON}")
    at = positions[0]
    if argv[at] == FROM_JSON:
        if at + 1 >= len(argv):
            raise UsageError(f"{FROM_JSON} needs a file name ('-' reads standard input)")
        source, rest = argv[at + 1], argv[:at] + argv[at + 2:]
    else:
        source, rest = argv[at][len(FROM_JSON) + 1:], argv[:at] + argv[at + 1:]
    options = _option_strings(commands[command])
    true_or_false = frozenset(name for name, action in commands[command]._option_string_actions.items()
                              if action.choices is not None and sorted(map(str, action.choices)) == ["false", "true"])
    given = {_option_name(token, options) for token in rest} - {None}
    tokens, mentioned = _tokens_from_object(_read_option_file(source), options, true_or_false)
    for name in sorted(mentioned & given):   # a key counts as given whatever its value, so a false cannot hide a flag
        raise UsageError(f"given twice: {name}")
    combined = rest + tokens
    if source == "-":
        for i, token in enumerate(combined):
            if _option_name(token, options) == "--file" and (token == "--file=-" or combined[i + 1:i + 2] == ["-"]):
                raise UsageError("standard input cannot hold both the options and the file")
            if _option_name(token, options) == "--note-stdin":
                raise UsageError("standard input cannot hold both the options and the note")
    return combined


# The commands whose job it is to find damage: a run whose record cannot be read is a problem they report (exit code
# 1, with its explanation), not wrong use. `status --root` leaves such a folder out of its list.
REPORT_DAMAGE = ("gate", "check-data")


STDIN_FILE = ("add-fact", "add-facts", "record-lens-recommendation")   # the commands where --file - reads stdin


def _check_named_paths(args) -> None:
    """Before a command does anything: every run it names is a run, every file it names is a file, and the lens folder
    is a folder. Otherwise it is wrong use (one plain line, exit code 2), and nothing is made, locked or asked for."""
    for name in ("run", "previous", "current"):   # --run of every command; both runs of compare
        if getattr(args, name, None) is not None:
            try:
                store.require_run(Path(getattr(args, name)))
            except store.RunRecordUnreadable:
                if args.command not in REPORT_DAMAGE:   # these two go on and report the record as a problem
                    raise
    for name in ("file", "pack_file"):
        value = getattr(args, name, None)
        if value is None or (value == "-" and name == "file" and args.command in STDIN_FILE):
            continue
        _require_file(Path(value))
    lenses = getattr(args, "lenses", None)
    if lenses is not None:
        path = Path(lenses)
        if path.exists() and not path.is_dir():
            raise UsageError(f"{path} is a file, not a folder. Give the folder of the lens files.")
        if not path.is_dir():
            raise UsageError(f"{path} does not exist. Give the folder of the lens files.")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(_expand_from_json(parser, sys.argv[1:] if argv is None else list(argv)))
        if getattr(args, "from_json", None) is not None:   # parsed but never applied: do not run without it
            raise UsageError(f"{FROM_JSON} was not applied")
        if args.version:
            _emit({"version": __version__})
            return 0
        if not getattr(args, "func", None):
            raise UsageError("a command is required")
        _check_named_paths(args)
        return args.func(args)
    except UsageError as exc:
        _emit({"error": str(exc)})
        return 2
    except PermissionError as exc:
        _emit({"error": str(exc)})
        return 2
    except (ValueError, RecursionError, FileExistsError, FileNotFoundError, NotADirectoryError) as exc:
        _emit({"error": str(exc) or exc.__class__.__name__})
        return 2
    except store.RunBusy as exc:   # the run lock stayed taken for the whole wait; nothing was changed
        _emit({"error": str(exc), "busy": True})   # so a helper can tell "run it again" from "used wrongly"
        return 2
    except IsADirectoryError as exc:   # a folder where a file is expected
        _emit({"error": f"{exc.filename} is a folder, not a file. Give the path of a file."
               if exc.filename else str(exc) or exc.__class__.__name__})
        return 2
    except OSError as exc:   # any other trouble with the disk or the system: one line, never a traceback
        _emit({"error": str(exc) or exc.__class__.__name__})
        return 2
    except SystemExit as exc:  # --help
        return exc.code if isinstance(exc.code, int) else 0
