# Strategy Radar

A Claude Code plugin that researches a strategy question from public sources and builds a layered report in which **every fact carries an exact quote that a program has checked** against a saved copy of the source.

Example question: *"Which competitors are adding filling capacity, and for whom?"*

> **Read this first.** In this version every run is practice on an **invented company** (Example Pharma) with invented sources. Its reports say so at the top. Packs for real companies are not part of this version. **"Confirmed" does not mean "true"**: it means the party itself, or two independent sources, state the fact in a quote the program found word for word, and a model judged that the quote supports the fact. That model can be wrong. Nothing here is insight into any company's internals.

## What it does

1. You ask a question. The plugin saves a copy of each source it uses.
2. A helper proposes facts, each with a quote. A small program (`radar`, no model inside) looks for every quote **word for word** in the saved copy. A second helper judges whether the quote really supports the fact.
3. The run stops twice for **you**: which ideas ("lenses") the analysis uses, and whether the report is built as it stands. A helper never answers for you.
4. The report separates what could be confirmed from what could not. Rejected facts are shown, never relied on. Totals are computed by the program, never written by a model. The program refuses to build the report while a fact or a listed total is unchecked.

The free text of the analysis (key messages, reasoning, options) is the lead model's writing. The program checks its form and the facts it names, not what it says.

## Install

You need Claude Code (signed in) on a Mac or Linux, and Python 3.10 or newer. The plugin was built and tried with **Claude Code 2.1.325**.

```
claude plugin marketplace add paul-knecht/strategy-radar-plugin
claude plugin install strategy-radar@strategy-radar
```

Remove it again with:

```
claude plugin uninstall strategy-radar@strategy-radar
claude plugin marketplace remove strategy-radar
```

To try it without installing, clone the repository and start Claude Code with the plugin loaded from the folder:

```
claude --plugin-dir /full/path/to/strategy-radar
```

**What was tried:** the two commands above, on one Mac with Claude Code 2.1.325, installed the plugin, and the practice tour then ran as a real session from the installed copy and passed its checks. The other four model-driven tests (the full run, the planted errors, the private-mode notice, a question put back at a decision) ran with `--plugin-dir`, not from an installed copy. Linux and other Claude Code versions were not tried. See `docs/plugin.md`, "Known limits".

## First steps

In a Claude Code session with the plugin on:

| Command | What it does |
|---|---|
| `/strategy-radar:start` | The guided start: checks the setup, then offers a practice tour or a run. One question at a time, nothing is written without your yes. |
| `/strategy-radar:practice` | A short tour of a finished invented run, including the three planted errors the checks catch. Needs no internet. |
| `/strategy-radar:run` | A run of ten steps with the two decisions that are yours. |
| `/strategy-radar:new-pack` | Makes a pack file for a company you name. In this version a run on a real company stops before the analysis, because the lens library is not installed yet. |

## What to know before you install

- **Usage.** Every run is a real model session with helpers on your own account. The five model-driven tests together came to about 18 US dollars in the last pass; a single practice tour about half a dollar.
- **The guard.** A hook runs before every file write and shell command in any session where the plugin is on. It keeps helpers inside their rules and refuses hand edits inside a run's folder. It is a catch for slips, not a wall, and it lets the lead's calls through if it cannot run. The final check before a report is built holds either way. `radar doctor` says whether the guard can run on your computer.
- **Python.** The `radar` program needs Python 3.10 or newer. On a Mac without Apple's developer tools this was tested with made-up inputs only.
- **Private material.** Runs default to public. Adding a document that is not public only starts after the program's own notice has been shown to you and you have said yes in your own words. No version to publish is ever built from such a run.
- **Limits.** What was never verified (a printed page, the tables in a spreadsheet program, an unscripted session, Linux for the later work, live websites) is listed in `docs/plugin.md` under "What to check by hand" and "Known limits".

## Where things are

| Folder | Holds |
|---|---|
| `skills/` | The four skills (`start`, `run` with ten step files, `practice`, `new-pack`). |
| `agents/` | The four helpers: source scout, fact extractor, support checker, bias auditor. |
| `hooks/` | The guard. |
| `engine/radar/`, `bin/radar` | The model-free program: saves sources, checks quotes, settles statuses, enforces the gate, builds the report. |
| `references/` | Reference texts the lead and helpers read (evidence rules, analysis format, confidence wording). |
| `packs/`, `engine/radar/demo/` | The invented demo pack, its sources and its two example lenses. |
| `docs/engine.md` | What every `radar` command takes and prints. |
| `docs/plugin.md` | A guide for someone who does not program: what is enforced by the program, what rests on instructions, what to check by hand, known limits. |
| `tests/`, `evals/` | The test suite and the test cases for which skill starts. |

## Tests

```
uv run pytest -q
```

Runs the whole suite without any model session (about three minutes). Tests that start real Claude Code sessions are kept out of it and cost usage on your account:

```
uv run pytest -m model tests/model -q
```

## Status

Version 0.2.0. Built task by task with a review after every task and a final review of the whole branch; what was verified and what was not is stated in `docs/plugin.md`. Still to come: a lens library whose ideas are checked against their original works, packs for real companies, sample runs.

## Licence

MIT. See `LICENSE`.
