# Strategy Radar

A Claude Code plugin that researches a strategy question from public sources and builds a layered report in which **every fact carries an exact quote that a program has checked** against a saved copy of the source.

Example question: *"Which competitors are adding filling capacity, and for whom?"*

> **Read this first.** The one company pack that ships is for an **invented company** (Example Pharma), with invented sources: a run on it is practice, and its reports say so at the top. The plugin also ships eighty-three lenses for real use. No pack for a real company ships: you make one with `/strategy-radar:new-pack`, and a run on such a pack has **been tried on real websites in only a few runs so far**. **"Confirmed" does not mean "true"**: it means the party itself, or two independent sources, state the fact in a quote the program found word for word, and a model judged that the quote supports the fact. That model can be wrong. Nothing here is insight into any company's internals.

## What it does

1. You ask a question. The plugin saves a copy of each source it uses.
2. A helper proposes facts, each with a quote. A small program (`radar`, no model inside) looks for every quote **word for word** in the saved copy. A second helper judges whether the quote really supports the fact.
3. The run stops twice for **you**: which ideas ("lenses") the analysis uses, and whether the report is built as it stands. A helper never answers for you.
4. The report separates what could be confirmed from what could not. Rejected facts are shown, never relied on. Totals are computed by the program, never written by a model. The program refuses to build the report while a fact or a listed total is unchecked.

The free text of the analysis (key messages, reasoning, options) is the lead model's writing. The program checks its form and the facts it names, not what it says.

## Install

### What you need first

- **A Mac or Linux computer** with **Claude Code**, signed in, and `git` (Claude Code uses it to fetch a plugin from GitHub). The plugin was built and tried with **Claude Code 2.1.325**.
- **Python 3.10 or newer.** This is the one thing people often lack: a Mac's built-in Python is often older. Check with `python3 --version`. If it is missing or too old, install it from [python.org](https://www.python.org/downloads/), or ask Claude Code in an ordinary chat, for example "Install a current Python for me". Claude Code then proposes a command and **asks for your approval before it runs anything**. On Linux that command usually needs administrator rights, so you may have to run it yourself. (Not tried with this plugin. The plugin itself never installs Python: its guided start checks, says what is missing and stops.)
- **Optional, only for PDF files:** a small add-on. After you install the plugin, `/strategy-radar:start` offers to set it up with one command, `radar setup`, which puts it in a folder of its own (`~/.strategy-radar`) and does nothing until you say yes.
- Nothing else: no Node, no extra tools. Only developers who run the tests need `uv`.

### Windows

Not supported. The program and the guard start through shell scripts and use Mac/Linux file paths and file locks, and nothing has been run on Windows. The route that should work is **WSL2** (Linux inside Windows): install it with `wsl --install` in an administrator PowerShell, start Claude Code inside the Linux side, and follow the steps above. That route has **not been tried**.

### The two commands

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
| `/strategy-radar:new-pack` | Makes a pack file for a company you name. A run on a pack for a real company uses the eighty-three lenses that ship with the plugin; such a run has been tried on real websites in only a few runs so far. |
| `/strategy-radar:screen` | Starts a screening run on one startup: a first-pass investment memo on its company, market, competition, team, traction and risks. You give its name and website; it proposes the competitors and pages to search from a web search, each with the page where it was found, and you confirm them; this search has run in two real screening sessions so far. Then it hands over to the run. The memo prepares a decision and does not make it. |

## Screening a startup

`/strategy-radar:screen` writes a first-pass investment memo on one startup from public sources only. You give the startup's name and website and confirm the competitors and pages to search; the run then has the same two stops as every run. The memo shows what the sources say about the company, market, competition, team, traction and risks, what would have to be true to invest, and the questions the sources leave open for the partner meeting. Every fact carries a checked quote, and the startup's own figures are shown as its claims. The memo holds no verdict ("invest" or "pass"), no score and no figure of its own, such as a market size or a runway.

## What to know before you install

- **Usage.** Every run is a real model session with helpers on your own account. The five model-driven tests together came to about 18 US dollars in the last pass; a single practice tour about half a dollar. Two more model-driven tests are written and have not been run.
- **The guard.** A hook runs before every file write and shell command in any session where the plugin is on. It keeps helpers inside their rules and refuses hand edits inside a run's folder. It is a catch for slips, not a wall, and it lets the lead's calls through if it cannot run. The final check before a report is built holds either way. `radar doctor` says whether the guard can run on your computer.
- **Python.** The `radar` program needs Python 3.10 or newer. On a Mac without Apple's developer tools this was tested with made-up inputs only.
- **Private material.** Runs default to public. Adding a document that is not public only starts after the program's own notice has been shown to you and you have said yes in your own words. No version to publish is ever built from such a run.
- **Limits.** What was never verified (a printed page, the tables in a spreadsheet program, an unscripted session, Linux for the later work, live websites beyond a few real runs) is listed in `docs/plugin.md` under "What to check by hand" and "Known limits".

## Where things are

| Folder | Holds |
|---|---|
| `skills/` | The five skills (`start`, `run` with ten step files, `practice`, `new-pack`, `screen`). |
| `agents/` | The eight helpers: source scout, fact extractor, support checker, bias auditor, lens advisor, the two link readers and the project grouper. |
| `hooks/` | The guard. |
| `engine/radar/`, `bin/radar` | The model-free program: saves sources, checks quotes, settles statuses, enforces the gate, builds the report. |
| `references/` | Reference texts the lead and helpers read (evidence rules, analysis format, confidence wording). |
| `packs/`, `engine/radar/demo/` | The invented demo pack, its sources and its two example lenses. |
| `lenses/` | The eighty-three lenses for real use, each with the works or slides it rests on and their level; `lenses/README.md` says what a lens holds. |
| `docs/engine.md` | What every `radar` command takes and prints. |
| `docs/plugin.md` | A guide for someone who does not program: what is enforced by the program, what rests on instructions, what to check by hand, known limits. |
| `docs/superpowers/` | The design, the plans and the build records with every decision. |
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

Version 0.4.1. Built with a plan, a review after every task and a final review of the whole branch; the decisions and what was not verified are recorded in `docs/superpowers/plans/2026-11-12-strategy-radar-plugin-ledger.md`. Real runs on public websites have been tried in only a few runs so far, among them three screening runs on startups; the web search of `/strategy-radar:screen` proposed the competitors and pages in two of them. Not done yet: sample runs.

**New in 0.4.0, for older runs:** the money check now reads every text of the analysis, not only what could not be found. Checking an older finished run again may stop there: in each named text, name one of the listed facts that state an amount and say why its amount does not answer, or reword the text, then build again.

## Licence

MIT. See `LICENSE`.
