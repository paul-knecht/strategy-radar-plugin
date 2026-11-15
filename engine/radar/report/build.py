"""The one place that writes report files. It runs the gate first and refuses to write anything if it is closed."""
from datetime import datetime
from pathlib import Path

from .. import store
from ..gate import gate
from ..schema import Problem
from .export import facts_csv, sources_csv
from .html import render_html
from .markdown import render_markdown
from .model import build_model


# The marks a table's name carries, so a table passed on by itself still says what it is: `-confidential` when the
# report uses a source that is not public, `-illustrative` when the run is illustrative, both in that order.
TABLE_MARKS = ("", "-confidential", "-illustrative", "-confidential-illustrative")


def table_marks(confidential: bool, illustrative: bool) -> str:
    """The marks of the two tables' names: facts<marks>.csv and sources<marks>.csv."""
    return ("-confidential" if confidential else "") + ("-illustrative" if illustrative else "")


class GateRefused(Exception):
    """The gate found problems, so no report file was written."""

    def __init__(self, problems: list[Problem]):
        super().__init__(f"the gate refused to build the report: {len(problems)} problem(s)")
        self.problems = problems


def build_report(run_dir: Path, lenses_dir: Path, publishable: bool = False, now: datetime | None = None) -> list[Path]:
    """Build the report files of a run and return their paths: report.md, report.html, the facts table, the sources table.
    The tables are named facts<marks>.csv and sources<marks>.csv (see `table_marks`).

    Raises GateRefused before writing anything. Everything is rendered before the first file is written.
    `now` is the build time the reports state (default: the current time).

    The run lock is held from the gate to the last file written, so no command can change a record between the
    check and the report built from it (a build that waits longer than the lock's wait raises store.RunBusy, and
    nothing is written). Neither the gate nor the renderers take the lock, which one process cannot take twice.
    """
    run_dir = Path(run_dir)
    with store.locked(run_dir):
        return _build(run_dir, lenses_dir, publishable, now)


def _build(run_dir: Path, lenses_dir: Path, publishable: bool, now: datetime | None) -> list[Path]:
    """`build_report` without taking the lock: the caller holds it."""
    problems = gate(run_dir, lenses_dir, publishable)
    if problems:
        raise GateRefused(problems)
    model = build_model(run_dir, lenses_dir, now)
    suffix = table_marks(model["confidential"], model["illustrative"])
    # Render everything first: if any renderer fails, nothing has been written.
    rendered = [("report.md", render_markdown(model).encode("utf-8")),
                ("report.html", render_html(model).encode("utf-8")),
                (f"facts{suffix}.csv", facts_csv(model).encode("utf-8-sig")),
                (f"sources{suffix}.csv", sources_csv(model).encode("utf-8-sig"))]
    report_dir = run_dir / "report"
    report_dir.mkdir(exist_ok=True)
    for marks in TABLE_MARKS:   # a run folder holds its tables under one naming only
        if marks != suffix:
            for kind in ("facts", "sources"):
                (report_dir / f"{kind}{marks}.csv").unlink(missing_ok=True)
    paths = []
    for name, content in rendered:
        path = report_dir / name
        path.write_bytes(content)
        paths.append(path)
    return paths
