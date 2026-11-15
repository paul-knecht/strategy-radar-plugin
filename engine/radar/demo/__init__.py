"""The invented demo: source texts, two lens files and the builder of the illustrative run.

Everything here is made up and labelled illustrative. The paths are built from this file's own location, so the
engine finds the material whatever folder it is run from.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCES = HERE / "sources"
LENSES = HERE / "lenses"

from .build import PRIVATE_DEMO_NOTICE, STAGES, DemoError, build_demo_run, run_id_for  # noqa: E402  (build.py reads SOURCES and LENSES from here)

__all__ = ["HERE", "LENSES", "SOURCES", "PRIVATE_DEMO_NOTICE", "STAGES", "DemoError", "build_demo_run", "run_id_for"]
