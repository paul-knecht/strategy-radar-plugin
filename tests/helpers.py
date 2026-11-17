"""Shared test helpers: build runs, sources and facts that are complete under the record formats."""
import contextlib
import json
import os
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

from radar import demo, store, verify

BIN_RADAR = Path(__file__).parent.parent / "bin" / "radar"


def lens_folder_with_level(folder, level) -> Path:
    """A lens folder holding a copy of the demo lens firm-boundaries whose one original is at `level`. Returns the
    folder."""
    lens = json.loads((demo.LENSES / "firm-boundaries.json").read_text(encoding="utf-8"))
    lens["originals"][0]["level"] = level
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "firm-boundaries.json").write_text(json.dumps(lens, indent=2), encoding="utf-8")
    return folder


def radar_env(home, **extra) -> dict:
    """The environment for starting the real `bin/radar` inside the tests.

    The Python that runs is the test environment's own (`RADAR_PYTHON`), never whatever `python3` is on the machine,
    and the home folder is a path under `home` that nothing creates, never the real `~/.strategy-radar`.
    """
    env = {**os.environ, "RADAR_PYTHON": sys.executable, "HOME": str(home),
           "RADAR_HOME": str(Path(home) / ".radar-home")}
    env.update(extra)
    return env


def run_radar(*args, home, input=None, cwd=None, env=None) -> subprocess.CompletedProcess:
    """Start the real launcher `bin/radar` with `args` and wait for it. Output is captured as text."""
    return subprocess.run(["/bin/sh", str(BIN_RADAR), *args], capture_output=True, text=True, input=input, cwd=cwd,
                          env=radar_env(home, **(env or {})))


def make_run(tmp_path, **over) -> Path:
    """Create a run under tmp_path. `over` are init_run keyword arguments (mode, acknowledged, ...)."""
    kwargs = {"question": "Who adds capacity?", "pack": "demo", "run_id": "run1"}
    if over.get("mode") == "private" and over.get("acknowledged"):   # a private run stores the person's reply
        kwargs["acknowledged_words"] = "Yes, I agree (an invented reply for a test)."
    kwargs.update(over)
    return store.init_run(Path(tmp_path), **kwargs)


def add_source(run_dir, text: str, **over) -> dict:
    """Write copies/<id>.txt and a complete `ok` source record. `over` replaces any key.

    The id is reserved the way the engine reserves it, and the run's source counter is kept right.
    """
    run_dir = Path(run_dir)
    sid = over.pop("id", None) or store.reserve_id(run_dir, "S")
    copy = run_dir / "copies" / f"{sid}.txt"
    copy.write_text(text, encoding="utf-8")
    data_class = over.get("data_class", "public")
    source = {
        "id": sid,
        "url": f"https://{sid.lower()}.example.com/{sid}",   # every source on a site of its own
        "publisher": "Competitor A",
        "title": f"Source {sid}",
        "date": "2026-05-14",
        "type": "company_release",
        "speaker": "the company",
        "interest": "wants to look strong",
        "language": "en",
        "data_class": "public",
        "saved_at": "2026-11-12T10:15:00Z",
        "saved_by": "program",
        "access": "ok",
        "access_reason": None,
        "copy_file": f"copies/{sid}.txt",
        "orig_file": None,
        "copy_sha256": store.sha256_file(copy),
        "based_on": [],
        "provenance": (None if data_class == "public"
                       else {"supplied_by": "the tester", "basis": "own company document"}),
    }
    source.update(over)
    store.write_source(run_dir, source)
    store.record_created(run_dir, "S", sid)
    return source


def proposal(**over) -> dict:
    """A complete capacity_move proposal for an invented company, as `radar add-fact` takes it.

    Top-level keys in `over` replace the defaults; `fields` is merged into the default fields.
    """
    fields = {
        "company": "Competitor A",
        "move_type": "expansion",
        "site": "Plant North",
        "country": "Exampleland",
        "what_added": "a second filling line",
        "size_value": "2",
        "size_unit": "lines",
        "announced": "2026-05-14",
        "planned_start": "2028",
        "stage": "announced",
        "access": "open",
        "delivery": "not_yet",
        "in_question": "yes",
    }
    extra = over.pop("fields", {})
    fields = None if extra is None else {**fields, **extra}   # fields=None gives a general fact
    result = {
        "kind": "capacity_move",
        "statement": "Competitor A will add a second filling line at Plant North.",
        "quote": "Competitor A will add a second filling line at Plant North by 2028.",
        "quote_language": "en",
        "quote_translation": None,
        "source_id": "S1",
        "supporting": [],
        "primary_source": False,
        "certainty": "firm",
        "tentative_reason": None,
        "fields": fields,
    }
    result.update(over)
    return result


PERMIT_TEXT = ("The planning office received an application for a new filling hall at Plant North, "
               "with a decision due in 2027.")


def early_signal_proposal(**over) -> dict:
    """A tentative general fact marked as an early signal, as the extractor proposes one from a permit."""
    result = proposal(kind="general", fields=None, source_id="S1", primary_source=True, early_signal=True,
                      certainty="tentative", tentative_reason="a planning application, not an announcement",
                      statement="A planning application names a new filling hall at Plant North.",
                      quote="an application for a new filling hall at Plant North")
    result.update(over)
    return result


def add_early_signal(run_dir, **over) -> dict:
    """Propose an early signal; the run needs a source holding PERMIT_TEXT."""
    return store.new_fact(Path(run_dir), early_signal_proposal(**over))


def add_fact(run_dir, **over) -> dict:
    """Propose a complete capacity_move fact for an invented company (see `proposal`)."""
    return store.new_fact(Path(run_dir), proposal(**over))


def minimal_analysis(fact_ids: list[str], lens_id: str | None = None) -> dict:
    """A complete analysis with one message (fact, reasoning, conclusion); every other section is empty."""
    return {
        "messages": [{
            "id": "M1",
            "text": "Competitor A is adding capacity.",
            "confidence": "medium",
            "chain": [
                {"kind": "fact", "text": "Competitor A announced a new line.",
                 "fact_ids": list(fact_ids), "lens_id": None},
                {"kind": "reasoning", "text": "Added capacity changes what customers can expect.",
                 "fact_ids": [], "lens_id": lens_id},
                {"kind": "conclusion", "text": "Expect more supply from 2028.",
                 "fact_ids": [], "lens_id": None},
            ],
            "counter_view": "The line may be delayed.",
            "would_change": "A cancellation notice.",
            "outside_view": {"text": "Expansions often slip.", "fact_ids": []},
        }],
        "demand_signals": [],
        "decision_options": {"question": "What should we do?", "framing": "company",
                             "framing_fact_ids": [], "options": [], "internal_questions": []},
        "watch_items": [],
        "audit_flags": [],
        "not_found": [],
        "contradictions": [],
        "lens_notes": [],
        "assumptions": [],
        "scenarios": [],
        "predictions": [],
        "calculations": [],
    }


def finish_run(run_dir, analysis_fact_ids: list[str], lens_id: str | None = None,
               analysis: dict | None = None) -> None:
    """Take a run with proposed facts to a state the gate can judge.

    Checks every quote, records a passed support check for every fact, settles the facts, writes
    `analysis` (or a minimal one resting on `analysis_fact_ids`) and records both checkpoints.
    Facts whose quote is not in the saved copy still end `rejected`.
    """
    run_dir = Path(run_dir)
    verify.check_quotes(run_dir)
    for fact_id in store.read_facts(run_dir):  # the verdict is bound to the facts' final content
        verify.record_support(run_dir, fact_id, True, "support-checker", "")
    verify.settle(run_dir)
    store.write_analysis(run_dir, analysis if analysis is not None else minimal_analysis(analysis_fact_ids, lens_id))
    for name in store.CHECKPOINTS:
        store.record_checkpoint(run_dir, name, "test", "ok")


def make_pdf(lines: list[str]) -> bytes:
    """A minimal valid one-page PDF with one `Tj` per line in Helvetica, built by hand.

    Lines must be plain ASCII without parentheses or backslashes.
    """
    ops = ["BT", "/F1 12 Tf", "14 TL", "72 760 Td"]
    for i, line in enumerate(lines):
        if i:
            ops.append("T*")
        ops.append(f"({line}) Tj")
    ops.append("ET")
    stream = "\n".join(ops).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Collector(HTMLParser):
    """Collects every element with its attributes and its inner text (entities unescaped)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements: list[dict] = []
        self._open: list[dict] = []

    def handle_starttag(self, tag, attrs):
        element = {"_tag": tag, "text": ""}
        element.update({name: (value if value is not None else "") for name, value in attrs})
        self.elements.append(element)
        if tag not in _VOID:
            self._open.append(element)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self._open.pop()

    def handle_endtag(self, tag):
        for position in range(len(self._open) - 1, -1, -1):
            if self._open[position]["_tag"] == tag:
                del self._open[position:]
                return

    def handle_data(self, data):
        for element in self._open:
            element["text"] += data


def find(html: str, tag: str, **attrs) -> list[dict]:
    """Every `tag` element of `html` whose attributes match, as a dict of its attributes plus `text`.

    `text` is the element's inner text with entities unescaped. A filter matches the whole attribute
    value, except `class`, which matches when the element has every class named in the filter.
    """
    collector = _Collector()
    collector.feed(html)
    collector.close()
    found = []
    for element in collector.elements:
        if element["_tag"] != tag:
            continue
        if all(set(wanted.split()) <= set(element.get(name, "").split()) if name == "class"
               else element.get(name) == wanted for name, wanted in attrs.items()):
            found.append({key: value for key, value in element.items() if key != "_tag"})
    return found


@contextlib.contextmanager
def read_only_folder(tmp_path, name="locked"):
    """A folder nobody can write to, made read-only with chmod and restored afterwards.

    Skips the test for a user (root, for example) who can still write to it.
    """
    folder = Path(tmp_path) / name
    folder.mkdir()
    folder.chmod(0o555)
    try:
        if os.access(folder, os.W_OK):
            pytest.skip("this user can write to a folder that is read-only")
        yield folder
    finally:
        folder.chmod(0o755)


@contextlib.contextmanager
def unreadable_file(path):
    """A file nobody can read, made so with chmod and restored afterwards.

    Skips the test for a user (root, for example) who can still read it.
    """
    path = Path(path)
    mode = path.stat().st_mode
    path.chmod(0o000)
    try:
        if os.access(path, os.R_OK):
            pytest.skip("this user can read a file that nobody may read")
        yield path
    finally:
        path.chmod(mode)
