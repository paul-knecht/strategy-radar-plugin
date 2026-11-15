# Strategy Radar plugin: a guide

This guide is for someone who has Claude Code and wants to know what this plugin does, how to try it, and what to trust. It describes version 0.2.0. You need no programming knowledge. The program underneath is described in `docs/engine.md`.

Everything the plugin ships is invented: the one company pack, the practice material and the two example lenses. Every run you can make today is on the invented demo pack, and its report is marked as illustrative at the top. That holds also when you add documents of your own to such a run: the run is practice, not a finding about a real company, and the plugin tells you so before it saves a file of yours. Real work needs a pack for your own company, which the next version brings.

## What the plugin does

Strategy Radar answers a question such as "which competitors are adding filling capacity, and for whom?" from sources that anyone can read. It saves a copy of each source, and every fact in the report carries a quote. A small program, called `radar`, looks for each quote word for word in the saved copy, and a second helper reads the sentence around the quote to judge whether it really supports the fact. The run stops twice, so that you decide which ideas ("lenses") the analysis uses and whether the report is built as it stands. The report then separates what could be confirmed from what could not.

"Confirmed" has a narrow meaning here. A fact is confirmed when the party itself states it, or when two independent sources state it, each in a quote that the program found word for word, and when the checking helper, a model, judged that the quote supports the fact. It does not mean that the fact is true, and the helper can be wrong. The program refuses to build the report when a fact or a listed total is not checked. The free text of the analysis (the key messages, the reasoning, the options) is the lead's writing: the program checks its form and the facts it names, not what it says.

## Try it and install it

You need Claude Code, signed in, on a Mac or on Linux. The plugin was built and tried with Claude Code 2.1.325. That version has no separate search tool, so the lead lists a folder with `ls` when it needs to find files, as a command of its own. In a session of your own, Claude Code may ask you before a listing in the plugin's folder (not tried: no unscripted session was run). You also need Python 3.10 or newer, because the `radar` program is written in it. The guided start checks this and tells you what to do if it is missing.

To try the plugin without installing it, open a terminal in a project folder (an empty one is fine) and start Claude Code with the plugin loaded from the folder you downloaded:

```
claude --plugin-dir /full/path/to/strategy-radar
```

To install it, add the repository as a marketplace (a list that Claude Code installs plugins from) and install from there. A folder on your computer works in place of the GitHub name. To remove it again, undo both steps:

```
claude plugin marketplace add paul-knecht/strategy-radar-plugin
claude plugin install strategy-radar@strategy-radar
claude plugin uninstall strategy-radar@strategy-radar
claude plugin marketplace remove strategy-radar
```

Inside a Claude Code session with the plugin loaded, the `radar` program is available as a command. Start with `/strategy-radar:start`, or with the practice tour if you only want to look.

## The four commands

**`/strategy-radar:start`** is the guided start. It goes through seven parts, one question per message, and it installs, writes and starts nothing without your yes. It checks the setup with `radar doctor`, which also says whether the guard (described below) can run on this computer. If the small add-on for reading PDF files is missing, it offers to make a folder of its own for it (usually under `~/.strategy-radar`) and shows the two commands first. It offers one line for the project's `.claude/settings.local.json` that lets the `radar` program run without asking each time. It offers the practice tour. It then asks which company, which question, and which mode (public sources only, or private mode), and hands over to the run command.

**`/strategy-radar:practice`** is a two-minute tour on invented data. It needs no internet and uses no web search and no helper. It builds a prepared run under `radar/practice` in your project, shows where it stands, and walks through the three facts that were refused on purpose: one quote that is not in its source, one that gives another year than the fact, and one that is cut just after the word "not" and so says the opposite. It builds the report, then builds a second run in which a refused fact has been slipped into the analysis, and shows the program refusing to build that one. It asks you nothing and does not stop.

**`/strategy-radar:run`** starts a run, or continues one (`/strategy-radar:run continue`). It needs a company pack and your question, and asks for what is missing. The only pack that ships is the invented demo pack. If you ask about a real company there is no pack for, the plugin says so and offers the demo pack or the practice tour. It never researches a company from memory. A run also needs at least one lens file in the lens folder; the lens library is not part of this version, and a run on a pack without lenses stops before the first step and says so. The practice tour and the demo pack work.

**`/strategy-radar:new-pack`** helps you write a company pack: a small file that says which company, which competitors to look at as candidates, and where to search. It asks one question per message and builds the pack from your answers alone; it adds no name from its own knowledge. Every name is a candidate until a run confirms it. It saves the pack as `radar/packs/<id>.json` only after your yes, never replaces a file without a yes, and then checks it with `radar check-pack`. Today a pack can be made and checked, but a run on a pack for a real company stops for lack of lenses.

## A run in ten steps

At the start of each step the plugin is told to say where the run is, in one line: the step, what is happening, and what comes next.

1. **Frame the question.** The program checks the pack and starts the run. The lead is told to pass on your question word for word; the program keeps what it is given. A short note looks at the wording only: whether it is a yes-or-no question that hides other options, what it leaves out, and whether it leans.
2. **Plan the search.** The plugin writes down where it will look and for which period, from the pack. With an invented pack there is no web search; the sources are the practice files or files you name. Before a file of your own is saved on the invented pack, the plugin says that the run is practice and asks whether to go on.
3. **Collect the sources.** For a real pack, one scout helper per search task finds candidate pages, and the program saves each copy. Pages behind a paywall or a login are left out and logged, and nothing is done to get around them. Every saved copy carries its data class (public, licensed or internal): the program saves no file without one.
4. **Read the sources.** One extractor helper per saved source proposes facts, each with an exact quote. The lead (the main Claude session that carries out the steps and calls the helpers) merges proposals that two sources make, and the program checks that each proposal is well formed.
5. **Check every quote.** The program looks for every quote word for word. A fact whose quote is not found is rejected. A failed fact may be tried once more. The support checker judges the rest, and the program settles each fact as confirmed, uncertain or rejected.
6. **Your decision: lenses.** The plugin shows what the run found and which lenses are on offer, proposes some, and stops. Your own answer is recorded, in your words.
7. **Work out what it means.** The plugin writes the analysis from the facts that count, through the lenses you chose. Every total and share is asked of the program. There is no recommendation, no ranking of competitors and no market-size number.
8. **Look for bias.** A helper that did not write the analysis reads it under ten fixed checks, named as the report names them: Framing; Outside view; Uncertainty; Competitor response; Evidence symmetry and source interest; Missing information and anchors; Success stories; Cause and effect; Disconfirmation; Independence. It gives flags only.
9. **Your decision: final report.** The plugin shows the key messages with a fixed wording for their confidence, what speaks against each, and the flags. It asks whether to build the report as it stands or change something first, and stops. After any change the look for bias is done again.
10. **Build the report.** The program checks the whole run once more. If there is an earlier finished run with the same question and pack, it compares the two, and it may refuse for a stated reason. Then it builds the report.

The two decisions are steps 6 and 9. At each one, the plugin asks and ends its turn. A question from you is answered and the question is asked again. An unclear answer is never taken as a yes. A plain no records nothing: the run waits until you come back with `/strategy-radar:run continue my last run`.

The report is a web page (`report/report.html`, opened in any browser), the same text as plain text (`report/report.md`), and two tables for a spreadsheet program (`report/facts-illustrative.csv` and `report/sources-illustrative.csv`: every run today is on the invented pack, and a run without that mark has `facts.csv` and `sources.csv`). Every row of both tables has an `illustrative` column, which says yes in an illustrative run. The facts table also holds each fact's supporting quotes, their sources and their translations (several in one cell, joined by " | "); the report shows a supporting quote's translation next to the quote. It has a summary, the thinking behind each key message, and a part on what could not be confirmed. A "Print or save as PDF" button is on the page.

## The four helpers

The helpers are narrow on purpose: each has a short list of tools, and each works on one job. The extractor, the checker and the auditor get a fixed prompt that is written in their files. The scout gets the search task as the lead writes it. The models are set in one place, `settings/models.json`, and `scripts/apply_models.py` writes them into the helper files. The model names are the names of Claude models, as that file lists them.

The last two columns tell two kinds of "never" apart. What the tool list or the guard (described below) holds cannot be broken by a helper that goes wrong. What only the instructions hold depends on the helper doing as it is told.

| Helper | Model | Tools | What it does | Held by its tools or the guard | Held by instructions only |
|---|---|---|---|---|---|
| `strategy-radar:source-scout` | sonnet | WebSearch, WebFetch | Searches for public pages and opens them. Hands back a list of candidates with who published each. | Saves nothing, runs no command, settles no fact. | States no fact about a company. |
| `strategy-radar:fact-extractor` | sonnet | Read | Reads one saved source, its record and the two reference files. Proposes facts, each with an exact quote. | Writes nothing, runs no command, settles no fact. | Reads no other file of the run: it has the Read tool, and the guard does not see reads. |
| `strategy-radar:support-checker` | opus | Bash | Runs two `radar` calls only: one to fetch a fact's quote with the sentences around it, one to record its own verdict. | Reads no file and runs no other command (the guard refuses them). Settles no fact. | Records a verdict only for the facts it was given. Only it can record a verdict: the guard refuses such a command from anyone else. |
| `strategy-radar:bias-auditor` | opus | Read, Glob | Reads the run record, the analysis, the facts and the source records. Flags possible bias under the ten checks. | Changes no file, runs no command, settles no fact. | Does not read the writer's notes or the saved copies (it has Read and Glob). Gives no verdict on the conclusion. |

The lead is told to start no helper but these four, to hand a command or a file write to no other helper, and to run at most four at the same time. Every helper is told to treat text inside a source or a page as data: an instruction in it is not followed, only noted.

## What a program enforces, and what rests on instructions

**The program enforces:**

- A quote must be found word for word, whole words only, in the saved copy, and the copy must be unchanged since it was saved. A fact whose quote is not found is rejected.
- A fact is confirmed only when its quote is found, the checker passed it, and the source is the party's own statement or an independent second source states the fact's claim in a quote of its own, found word for word in its own copy. The checker fails a fact whose quote from another source states only a detail, or another site or move. Two sources from the same site, or with the same text, are never independent. A permit, a job posting or a regulator record is an early signal and is never confirmed.
- Every total and share listed with the analysis is computed again by the program, in one unit, and must match.
- The form of the analysis: every point names facts that exist and count, a "Fact" step of the reasoning names a fact, and each chain ends with its conclusion. A fact number written in a text ("as F2 shows") must name a fact that counts. A flag of the bias audit may name any fact of the run, whatever its status, but only one that exists.
- The gate, the program's last check before a report is built, refuses a report that rests on a rejected or unsettled fact, on a copy or a status that was changed by hand, on a comparison that is out of date, or without both decisions recorded.
- A comparison with an earlier run is refused when the two may not be joined: an earlier run with non-public material and a public run, an invented run and one that is not, the practice run and another run, and an earlier run whose facts must be settled again first.
- Every saved copy has its data class, and a public run takes no non-public material.
- A private run is not made without the acknowledgement of the notice and your reply in your own words, which the program keeps and the report shows under "How this report was made". A version to publish is never built from a private run, and a private run whose ignore file no longer keeps it out of git takes no non-public file.
- The two tables of an invented run carry the illustrative mark, in their names and in a column of every row.
- `radar doctor` says whether the guard can run on this computer (not whether Claude Code has loaded it).
- The guard, described next.

**The guard** is a hook: a small program, `hooks/guard.py`, that Claude Code runs automatically before every file write and every shell command (a command typed into the computer's terminal, as opposed to a request to Claude Code's own file tools). It does three things. For every write made with Claude Code's file tools (Write, Edit and NotebookEdit), by the lead or by a helper, it refuses a hand write (a write by a model, not by the `radar` program) inside a run folder, except in the four places the lead owns: `analysis.json`, `notes/`, `proposals/` and `inbox/`. Where it cannot tell where a path leads, it refuses. For the four helpers it also judges shell commands: three may run none, and the support checker may run only its two `radar` calls, in the form its file shows. And it refuses a shell command that holds the word record-support from anyone but the support checker (the lead, a general-purpose helper, any other agent), with the sentence "Strategy Radar's guard: Only the support checker records whether a quote supports its fact. Ask the support checker to check this fact." That is the one place where it judges a command of the lead, and it is a catch for slips, not a wall. Every refusal begins with "Strategy Radar's guard: ", so you know who refused. It sees no read. A call it cannot read at all is let through, a helper's too. An error of its own while it judges a call it could read lets the lead's call through and refuses a helper's. When it cannot start at all (no Python found, a file of its own missing), its launcher refuses every call of the plugin's helpers and lets everything else through. The gate stays the real check at the end.

Once the plugin is installed, the guard runs in every Claude Code session in which the plugin is on, and its refusals apply to any file that session writes, not only inside a run.

**What rests on instructions and on tests, not on the program:**

- Which helper is called, when, and with which prompt; that no helper but the plugin's four is started, and that no command is handed to another helper.
- What the lead writes into the analysis: every point names the facts it rests on, only the lenses you chose appear, the outside view is honest, no probability word stands in a message's text, and there is no recommendation, ranking or market-size number. The program checks the form of the analysis, the facts it names and every total listed with it. It cannot check what its free text says.
- That a figure written in the text of the analysis is the one the program computed. The program checks the listed totals. It does not read the text for figures.
- That the lead writes no file of a run with a shell command, and makes no copy or script to get round a refusal. The guard does not judge the lead's shell commands, except one that records a verdict. Claude Code usually asks you before it runs a shell command outside the one line you allowed (your own settings may allow more), and the gate re-checks copies and statuses when the report is built.
- That the lead stops and waits at both decisions and at the private-mode notice, and that the yes or the answer recorded is yours. The program refuses to build without the two decision records, and to make a private run without the acknowledgement and your reply. It cannot tell who gave the answer or wrote the reply.
- That your question and your answers are kept word for word: the program keeps what the lead passes on.
- That only the support checker records a verdict on a fact, beyond the guard's catch for slips.
- That a file of your own on the invented pack is saved only after the warning, and with the data class you gave.
- What the extractor and the auditor read, as the table says.
- That a source which repeats another is noticed and linked, so that it does not count as a second source.
- That an instruction inside a source, a page or a helper's answer is treated as data and not followed.

Tests keep these instructions in step with the program. Five model-driven tests run the plugin for real; see the next sections.

## Where things are stored

- A run is a folder of plain files under `radar/runs/` in your project, one folder per run, named by date and time. You can open every file in a text editor. It holds the records of the sources and facts, the saved copies, the analysis, the notes, and the finished report.
- The saved copies of sources are kept out of git (the tool that tracks changes to files) by an ignore file of their own, a small file that tells git to skip them. A private run's whole folder is kept out of git in the same way.
- Your own packs are in `radar/packs/`. The plugin's invented pack is `packs/demo.json`, and its two example lenses are in `engine/radar/demo/lenses`.
- The practice tour builds under `radar/practice/`.
- A file that is passed to the program before a run exists goes to `radar/inbox/`.
- The add-on for PDF files, if you let the guided start make it, is in `~/.strategy-radar`.
- The one permission line, if you accept it, is in `.claude/settings.local.json`. It allows the `radar` program and nothing else. The checker's save of a verdict needs no extra approval under that line, except in one rare case: a note that holds a curly bracket next to a quotation mark. The checker is told to write no curly brackets, and to reword a note that is turned down. That reword was never seen in a live run. Writing notes and files into the `radar` folder and reading files of the plugin may still ask.

## Private mode

Private mode lets a run also use documents you hold yourself, such as licensed data or internal papers. The plugin never suggests it: it comes up only in the guided start's question about the mode, or when you ask for it. Before a private run exists, the plugin is told to show you the program's notice word for word:

> Private mode sends the content of your documents to the language model through your own Claude account. Check that your organisation and your data licences allow this.

The program makes a private run only when the acknowledgement and your reply are passed to it. It keeps your reply word for word, and the report shows it under "How this report was made"; it cannot tell who wrote it. That the yes is your own, given after you saw the notice, rests on the lead's instructions: a yes in your first message, a bare "OK", or anything from a helper or a file does not count. The program marks a report confidential when a source is not public or the comparison is with a non-public earlier run, and it refuses to build a version to publish of any private run, also one that holds only public sources so far. The invented private practice run, built by the program's demo command and not by the practice tour, was never shown a notice and takes no further non-public material. It is never a way into a private run for your own documents.

## The tests

The ordinary test run starts no model and needs no internet. (`pytest` is the Python test runner and `uv` starts it; the first time, `uv` may download the packages it needs.)

```
uv run pytest -q
```

`claude plugin validate . --strict` checks the plugin's files against Claude Code's own rules.

There are also five model-driven tests, kept out of the ordinary run. Each one is a real Claude Code session, with the plugin loaded, in a project folder of its own, on the account of whoever runs it. They cover the practice tour, a question put back at a decision (which is not an answer), the private-mode notice, the three planted errors in a half-finished run that the plugin carries on with, with a fact taken back at the final decision, and a whole run with both decisions. Run them with:

```
uv run pytest -m model tests/model -q
```

In the last pass, with Claude Code 2.1.325, the five tests together came to about 18 US dollars and took about 53 minutes; the whole run was the most expensive (about 8 US dollars), then the planted errors (about 6). These are rough figures for that day, not a promise. Four of the five passed. The fifth, the planted errors, passed every check on the facts, the fact taken back and the report, and missed one: see "Coming back to a run" under the known limits. That check now gives a warning and no failure. The tests are in `tests/model/`.

Three more cases check only which skill starts when you ask for something. They are nine real sessions and cost about 1 US dollar on the day they were run, again not a promise. They are described in `evals/README.md`, and run with:

```
sh evals/run.sh
```

## What to check by hand

A program cannot look at these. Tick each one when you have.

- [ ] **A printed page.** Open `report/report.html` of the practice tour, press "Print or save as PDF" and look at the printed page or the PDF: are the headings, the tables and the "illustrative" mark readable, and do the page breaks fall in sensible places?
- [ ] **The two tables in a German spreadsheet program.** Open `report/facts-illustrative.csv` and `report/sources-illustrative.csv` in a spreadsheet program set to German. If each line lands in one column, import the file instead and choose the comma as separator (`docs/engine.md` says how). Check that umlauts and long texts show correctly.
- [ ] **A Mac without Apple's developer tools.** On such a Mac the `python3` the system ships is only a stand-in that offers to install the developer tools. The `radar` program and the guard now pass over it on a Mac without the tools. Check that no window asking to install them comes up during a session, that the guard runs (`radar doctor` says so) once another Python is installed, and that the guided start tells you to install Python from python.org when none is found.
- [ ] **A session that is not scripted.** Go by hand, in an ordinary interactive session, from `/strategy-radar:start` to a finished practice tour. Check that one question comes at a time, that nothing is installed or allowed without your yes, and that the tour ends with a report and a refused build.
- [ ] **A listing in the plugin's folder.** In an ordinary session, start a run on the demo pack and note whether Claude Code asks you before the lead lists the plugin's lens folder or its practice files, and that the run goes on after you allow it.
- [ ] **The report in a browser.** Open the built `report.html` in the browser you normally use, and check that every tab and link works.

## Known limits

None of these is hidden in the program. They are what you should know before you rely on it.

### What the program cannot detect

- **Whether a quote means what the fact says.** The program finds words, not sense. Judging sense is the support checker's job, and a model can be wrong: a confirmed fact is one a model judged supported, not one proven true.
- **What the free text of the analysis says.** The program checks the analysis's form, the facts it names and its listed totals. What a key message, a reasoning step or an option says rests on the lead, and a figure written in a text is not read.
- **Who recorded a verdict.** The name on a verdict is whatever the caller wrote. The guard refuses a shell command that holds the word record-support unless the support checker runs it, so the lead, a general-purpose helper and any other agent are refused. It is a catch for slips, not a wall: a command written to hide the word gets past it, and so does every command when the guard cannot start (then only the plugin's helpers are held). An agent of your own that is named support-checker is treated as the plugin's support checker.
- **The verdict rule in other projects.** Where the plugin is on, a shell command that holds the word record-support is refused unless the support checker runs it, also in a project that has nothing to do with a run. The refusal names Strategy Radar's guard.
- **Text a page hides with a stylesheet or a script.** Text that a page hides by plain markup (the mark that hides an element, an inline style that hides it, a closed dialog) is left out of a saved copy. Text marked only as hidden from screen readers is kept, because a browser shows it. Text hidden by a stylesheet (the part of a page that styles it) or by a script (a program that changes the page while you read) is not detected.
- **Two publishers on one shared platform count as one source.** Two sources saved from the same site are never independent, whatever publisher was typed. A fact can therefore look less confirmed than it is. A sub-site (a name in front of the site's own name) counts as another site.
- **A file that has a second name on the computer is refused by the guard.** It cannot see where the other names are, so it refuses the hand write and says why. Places it cannot follow, such as those reached through some system shortcut folders, are refused in the same way. These refusals apply to any file a session writes, not only inside a run.
- **Whether the guard runs.** A call the guard cannot read at all is let through, a helper's too; an error of its own while it judges a call it could read lets the lead's call through and refuses a helper's; when it cannot start at all, it holds only the plugin's helpers. `radar doctor` says whether it can run here. The guard does not protect its own files, and whoever starts the session can point its launcher at another program (with `RADAR_PYTHON` or the search path). The gate stays the real check at the end.
- **A size whose unit is in the source's language.** A size is copied as the source writes it. The extractor is told to write the unit in English where it has a plain English form; when it does not, two facts with the same unit in two spellings cannot be added up by the program, and the lead can only count moves.
- **Smaller limits of the program**, each described in `docs/engine.md`: the gate computes every total again, so an unusual calculation is refused rather than trusted; a record written again keeps no file mode set by hand, and the write is not forced to the disk; the site's robots.txt is asked for before the two-second wait, and looking up a site name has no time limit of its own; a few short messages of the program (a wrong option, a refused proposal) have no explanation of their own; a source that could not be saved can still be marked as read and left out; a run folder whose record is not an ordinary file is not guarded against; the pack check does not catch every unusual entry.

### What was not tested

- **Systems.** It was built and tested in a cloud session on Linux, and then on a Mac. Only the guard fixes of the Mac check were looked at for Linux, and by reading only. The later work (the checker's save, the demo's facts, the model tests and the evals) ran on the Mac only. Windows is not supported, because the launcher of the program is a shell script.
- **Live websites.** Live websites were never fetched in a test. The download code was tested against stand-in servers on the same computer. How it behaves on real sites, such as pages that need a browser, robots rules and scanned PDFs, is not known. The source scout has never searched the real web. Every recorded run used the invented practice material.
- **Installing.** Installing from GitHub was tried once, on one Mac with Claude Code 2.1.325: it worked, and the practice tour passed as a real session from the installed copy. The other four model-driven tests loaded the plugin with `claude --plugin-dir` and were not run from an installed copy.
- **The guard in an installed copy.** The guard's rule for helpers depends on the helper name that Claude Code passes to it. That name has not been checked for an installed plugin.
- **A Mac without Apple's developer tools.** The pass over Apple's stand-in was tested with made-up files only, never on such a Mac. On a Mac whose developer tools are installed under another name the stand-in is not used either, and a `python3` elsewhere that is only a link to the stand-in is not recognised.
- **Paths no live session walked.** A "no" to the private-mode notice, the questions about a document of your own and a confidential report, a correction of a fact or another lens at the final decision, a refused comparison or build, a version to publish, a refused proposal, a source that cannot be read, a second sending to the checker, the guided start beyond its first checks, a pack made with the new-pack command from start to end, and a real web search. The extractor's instructions show no example of a quote in another language with its translation.
- **The checklist above.** A printed page, the tables in a German spreadsheet program, a Mac without developer tools and an unscripted session have not been looked at by a person.
- **Speed and accuracy of the model choices.** Which model each helper uses was not measured for speed or accuracy. The guide makes no claim that helpers are faster or better than one model.
- **Where it runs.** It is built for Claude Code only. It has not been tried in claude.ai or in Cowork, which may not run a program or a hook from a plugin.
- **No README and no icon yet.** The plugin has no README or icon, so it is not ready for a public plugin directory. The validator lists both.

### What rests on instructions and tests, not on the program

- **Coming back to a run.** When you continue a run that stopped in the middle of the quote checks (step 5), the lead does not always tell you first which step the run is at. In the last test pass it went straight to work, told you what it was doing, and named the step only when it reached your decision on the lenses. At the two decisions, where the run waits for you, it did say the step first.
- **The lead's work.** What the lead writes into the analysis, and when it asks for a decision, rests on its written instructions. The five model-driven tests are one run each, not a proof. A model can answer differently another time. Most tests of the skill files look for the sentences that state a rule, and find `radar` calls by their form (a call written in an unusual way, such as inside double quotes, would not be seen): they show that a rule is written down, not that a model follows it.
- **Your words, word for word.** That your question and your answers at the decisions are passed on unchanged rests on the lead; the program keeps what it is given.
- **A break at the wrong moment.** When a run is broken off after a corrected list of proposals was written and before it was added (steps 4 and 5), the list is not picked up on coming back; its sources are read again. Step 10 tells from the files' times whether your decision came after the last audit; files saved in the same second are listed by their names, as the usual listing does on a Mac and on Linux, and a run folder copied without its times can show any order.
- **The settings line and the setup.** The offered line covers `radar` as a plain command only; a full path to the program still asks. The guided start writes the settings file by hand, as its instructions describe. A setup that fails half-way can leave a half-made folder and the package tool's own downloads behind.
- **Where a run stands when you come back.** When you ask to continue a run, the lead is told to send first the line of the step the run stands at. In live runs it usually did. In one live turn it skipped a step's line, and the check for a run resumed at the fact check is still open. A separate, fixed sentence was tried and dropped, because the lead did not send it in eight live trials.
- **Only one pack, and two example lenses.** The lens library and packs for real companies are not part of this version. Every run is on the invented demo pack, and its report says so.
