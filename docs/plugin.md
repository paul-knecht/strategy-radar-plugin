# Strategy Radar plugin: a guide

This guide is for someone who has Claude Code and wants to know what this plugin does, how to try it, and what to trust. It describes version 0.5.0. You need no programming knowledge. The program underneath is described in `docs/engine.md`.

The one company pack the plugin ships is invented, and so are its practice material and its two example lenses. A run on that demo pack is marked as illustrative at the top of its report. That holds also when you add documents of your own to such a run: the run is practice, not a finding about a real company, and the plugin tells you so before it saves a file of yours. Real work needs a pack for your own company, which you make with `/strategy-radar:new-pack`. A run on it uses the eighty-three lenses that ship for real use (see "The lenses" below). Such a run is possible, but it has been tried on real websites in only a few runs so far, and no pack for a real company ships.

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

## The five commands

**`/strategy-radar:start`** is the guided start. It goes through seven parts, one question per message, and it installs, writes and starts nothing without your yes. It checks the setup with `radar doctor`, which also says whether the guard (described below) can run on this computer. If the small add-on for reading PDF files is missing, it offers to make a folder of its own for it (usually under `~/.strategy-radar`) and shows the two commands first. It offers one line for the project's `.claude/settings.local.json` that lets the `radar` program run without asking each time. It offers the practice tour. It then asks which company, which question, and which mode (public sources only, or private mode), and hands over to the run command.

**`/strategy-radar:practice`** is a two-minute tour on invented data. It needs no internet and uses no web search and no helper. It builds a prepared run under `radar/practice` in your project, shows where it stands, and walks through the three facts that were refused on purpose: one quote that is not in its source, one that gives another year than the fact, and one that is cut just after the word "not" and so says the opposite. It builds the report, then builds a second run in which a refused fact has been slipped into the analysis, and shows the program refusing to build that one. It asks you nothing and does not stop.

**`/strategy-radar:run`** starts a run, or continues one (`/strategy-radar:run continue`). It needs a company pack and your question, and asks for what is missing. The only pack that ships is the invented demo pack. If you ask about a real company there is no pack for, the plugin says so and offers to make one with `/strategy-radar:new-pack`, or the demo pack or the practice tour. It never researches a company from memory. A run also needs at least one lens file in its lens folder: a run on the demo pack uses the two example lenses, and a run on a pack for a real company uses the eighty-three lenses in `lenses/`. When that folder holds no lens, the run stops before the first step and says so.

**`/strategy-radar:new-pack`** helps you write a company pack: a small file that says which company, which competitors to look at as candidates, and where to search. It takes three answers, one per message: the company (with its website, if you know it), whether it is real or invented for practice, and your question. For a real company it then searches the web and proposes the rest of the pack in one message, each item with the page where it was found or the rule that set it, and you keep or strike them in one confirmation (`references/propose-pack.md`). An invented company is never searched: the questions in `references/pack-questions.md` fill in its pack, and they do the same when no web search is available or the search finds nothing. It adds no name from its own knowledge. Every name is a candidate until a run confirms it. It saves the pack as `radar/packs/<id>.json` only after your yes, never replaces a file without a yes, and then checks it with `radar check-pack`. A run on a pack for a real company uses the eighty-three lenses; such a run has been tried on real websites in only a few runs so far.

**`/strategy-radar:screen`** starts a screening run on one startup. It takes the same three answers as `/strategy-radar:new-pack`, with the startup's website expected and "What would have to be true to invest in <startup>?" offered as the question; it follows the same propose step, and you keep or strike the proposals in one confirmation. Nothing is added from memory. The search for competitors and pages has run in three real screening sessions; the proposals for the rest of the pack have run in one. The pack has its `screening` setting true and a window of 120 months, so that the founders' earlier work and the early funding rounds count. The run then searches and extracts by `references/screening-playbook.md` and writes its memo by `references/screening-memo.md`. Its report is a screening memo: the findings under company, market, competition, team, traction and risks, then what would have to be true to invest and the open questions for the partner meeting. It prepares a decision and does not make it: no verdict, no score, and no market size of its own.

## A run in ten steps

At the start of each step the plugin is told to say where the run is, in one line: the step, what is happening, and what comes next.

1. **Frame the question.** The program checks the pack and starts the run. The lead is told to pass on your question word for word; the program keeps what it is given. A short note looks at the wording only: whether it is a yes-or-no question that hides other options, what it leaves out, and whether it leans.
2. **Plan the search.** The plugin writes down where it will look and for which period, from the pack. With an invented pack there is no web search; the sources are the practice files or files you name. Before a file of your own is saved on the invented pack, the plugin says that the run is practice and asks whether to go on.
3. **Collect the sources.** For a real pack, one scout helper per search task finds candidate pages, and the program saves each copy. Pages behind a paywall or a login are left out and logged, and nothing is done to get around them. Every saved copy carries its data class (public, licensed or internal): the program saves no file without one.
4. **Read the sources.** One extractor helper per saved source proposes facts, each with an exact quote. The claim matcher helper names the proposals of different sources that state the same thing (when it fails or is refused twice, nothing is merged and the run goes on), the program joins the extractors' answers into one list unchanged, and the program checks that each proposal is well formed.
5. **Check every quote.** The program looks for every quote word for word. A fact whose quote is not found is rejected. A failed fact may be tried once more. The support checker judges the rest, and the program settles each fact as confirmed, uncertain or rejected. Last, the project grouper gathers the capacity moves that are reports of one plan into projects (see "The helpers"). When it is refused twice or fails, the plugin says so in one sentence and goes on: the report then shows each move on its own and says why. A step that later changes a fact (the first decision, the final decision, or a refused build) has the moves grouped again, and step 6 and step 10 each check where the grouping stands first and group once if it does not fit. A problem that the program names in the grouping's record never stops a step, and neither you nor the plugin repairs it by hand: only a new grouping mends it.
6. **Your decision: lenses.** The plugin shows what the run found. A helper, the lens advisor, suggests at most four lenses that fit your question, each with the part of the question it fits, why, the facts it could use and what is missing, and two link readers each read, on their own, whether each of those facts bears on its lens. The plugin shows that suggestion, marked as not checked, with a mark next to each link a reader doubts, and then every other lens, grouped by theme, and stops. When no suggestion can be made, it shows every lens and says why. You may pick any lens. Your own answer is recorded, in your words.
7. **Work out what it means.** The plugin writes the analysis from the facts that count, through the lenses you chose. Every total and share is asked of the program. There is no recommendation, no ranking of competitors and no market-size number.
8. **Look for bias.** A helper that did not write the analysis reads it under ten fixed checks, named as the report names them: Framing; Outside view; Uncertainty; Competitor response; Evidence symmetry and source interest; Missing information and anchors; Success stories; Cause and effect; Disconfirmation; Independence. It gives flags only.
9. **Your decision: final report.** The plugin shows the key messages with a fixed wording for their confidence, what speaks against each, and the flags. It asks whether to build the report as it stands or change something first, and stops. After any change the look for bias is done again.
10. **Build the report.** The program checks the whole run once more. The report opens on the answer to your question; its projects are a model's judgement, which nobody has checked. If there is an earlier finished run with the same question and pack, it compares the two, and it may refuse for a stated reason. Then it builds the report.

The two decisions are steps 6 and 9. At each one, the plugin asks and ends its turn. A question from you is answered and the question is asked again. An unclear answer is never taken as a yes. A plain no records nothing: the run waits until you come back with `/strategy-radar:run continue my last run`.

The report is a web page (`report/report.html`, opened in any browser), the same text as plain text (`report/report.md`), and two tables for a spreadsheet program (`report/facts-illustrative.csv` and `report/sources-illustrative.csv` for a run on the invented pack; a run without that mark has `facts.csv` and `sources.csv`). Every row of both tables has an `illustrative` column, which says yes in an illustrative run. The facts table also holds each fact's supporting quotes, their sources and their translations (several in one cell, joined by " | "); the report shows a supporting quote's translation next to the quote. It has a summary, the thinking behind each key message, and a part on what could not be confirmed. The thinking part shows each lens that was used, with the works or slides it rests on and the level of each, as the next section explains. A "Print or save as PDF" button is on the page.

## The lenses

A lens is an idea from strategy or economics, written in the plugin's own words, through which the analysis looks at the facts; you choose the lenses at step 6. A run on the demo pack has its two invented example lenses. A run on a pack for a real company has the eighty-three lenses in `lenses/`:

| Lens | Level |
|---|---|
| How fast a firm can absorb growth | Original read |
| Investments tied to one partner | Original read |
| Building abroad: for the market or for cost | Reference confirmed |
| Running it inside or buying it | Original read |
| Tariff threats and supply chains | Original read |
| What a firm is good at | Original read |
| The chain of activities that adds value | Secondary source read |
| Competing on cost or on uniqueness | Secondary source read |
| Being different, not only better | Secondary source read |
| What a home country gives its firms abroad | Secondary source read |
| Barriers that keep new competitors out | Secondary source read |
| Groups of rivals inside an industry | Secondary source read |
| How much of profit variance the industry explains | Secondary source read |
| Sunk costs and how concentrated a market gets | Secondary source read |
| How industries age from birth to maturity | Secondary source read |
| Competing and cooperating at once | Secondary source read |
| Does going first pay off | Secondary source read |
| Whether a firm can take in outside knowledge | Reference confirmed |
| Capacity as a threat to would-be entrants | Reference confirmed |
| Disruption from below | Reference confirmed |
| Distance between countries | Secondary source read |
| Five competitive forces in an industry | Secondary source read |
| Inside view and outside view in forecasts | Reference confirmed |
| When each user adds value for the others | Reference confirmed |
| Growing with new products or new markets | Reference confirmed |
| Resources that are valuable, rare and hard to copy | Secondary source read |
| Who profits from an innovation | Reference confirmed |
| Platforms serving two sides | Secondary source read |
| Assets built up over time | Reference confirmed |
| Dynamic capabilities | Secondary source read |
| Routines and evolution | Secondary source read |
| Knowledge as the key resource | Secondary source read |
| Exploring new options or exploiting old ones | Secondary source read |
| Firms as monitored teams | Secondary source read |
| Agency costs | Secondary source read |
| Who should own the asset | Secondary source read |
| Gains from partners | Secondary source read |
| Dependence on outside resources | Secondary source read |
| Modularity and design rules | Secondary source read |
| New links between known parts | Reference confirmed |
| The firm as a coalition | Secondary source read |
| Bidders who overpay | Reference confirmed |
| Good enough instead of best | Secondary source read |
| Change that destroys skills | Reference confirmed |
| What the corporate parent adds | Reference confirmed |
| How a new idea spreads | Secondary source read |
| When a market settles on one design | Secondary source read |
| The mental map at the top | Reference confirmed |
| Shared inputs and the multiproduct firm | Reference confirmed |
| Cash beyond good projects | Reference confirmed |
| How much to integrate after buying | Reference confirmed |
| Structure follows strategy | Secondary source read |
| Adapt, aggregate or arbitrage | Secondary source read |
| Three tests for diversifying | Secondary source read |
| Cultural dimensions of nations | Secondary source read |
| How a global value chain is governed | Secondary source read |
| Global integration or local responsiveness | Secondary source read |
| Keeping know-how inside the firm abroad | Secondary source read |
| Investing abroad for control | Secondary source read |
| A product's life cycle and where it is made | Secondary source read |
| Regional rather than global | Reference confirmed |
| Related or unrelated diversification | Reference confirmed |
| Entering abroad step by step | Secondary source read |
| Three models of a decision | Secondary source read |
| Deliberate and emergent strategy | Secondary source read |
| Escalating commitment to a failing course | Secondary source read |
| Deciding fast in fast markets | Reference confirmed |
| Why organizations become alike | Secondary source read |
| Selection among organizations | Secondary source read |
| Responses to institutional pressure | Secondary source read |
| Profit as the firm's one responsibility | Original read |
| Managing for all with a stake | Secondary source read |
| Four kinds of responsibility | Secondary source read |
| Responsibility weighed as an investment | Secondary source read |
| Whether the market pulls the product | Secondary source read |
| Back the team or the business | Secondary source read |
| What investors say decides a deal | Secondary source read |
| What the founders have done before | Secondary source read |
| Profit per customer against its cost | Secondary source read |
| Does the money last until profit? | Original read |
| Money in rounds, with an option to stop | Secondary source read |
| Who stands behind a young firm | Secondary source read |
| Advantage from the natural environment | Reference confirmed |

Each lens names the works or lecture slides it rests on, and each of these carries its own level: Original read (the work itself was read), Secondary source read (a source about the work was read, not the work itself, and the entry names both the source and the work), Course slides (lecture slides that present the idea were read, not the work behind them), or Reference confirmed (the work is named and its reference was confirmed from a public page, which the lens links to, but its text was not read: the lens is written from the model's general knowledge of the work and was not checked against it. It is used only when no free text of the work or about it could be read: the work is behind a paywall, or its free copy could not be fetched or was a file that was not downloaded). A lens's own level is the lowest level among the works and slides it rests on, so a lens that rests on an article that was read and on lecture slides has the level Course slides. A lens rests on what its works or slides state, not on whether the idea is true. What it suggests you look at is the plugin's own application of the idea and makes no claim about the work. The author's copies of the works and slides are licensed, so the evidence for each lens stays on the author's computer and is not in this repository. `lenses/README.md` says what a lens file holds and how `radar check-lenses` checks it.

The maintainer adds or rebuilds a lens with `/new-lens`, a skill of the repository itself (in `.claude/skills/new-lens/`). It works only in a checkout of the repository and is not part of the plugin you install. It works in batches of up to twelve lenses, with two decisions for the whole batch: first which works and copies to use, then which finished lenses to add. It takes each lens through the same steps as the lenses that ship: the reference is confirmed from a page that was found and read, each sentence rests on a quote that the program checks and the support checker judges, a fresh reviewer reads the lens against that evidence, and `scripts/check_lens_overlap.py` checks that no run of eight or more words of the lens stands in a copy of the work. A new lens never rests on course slides. If you want lenses of your own, fork the repository on GitHub and change it.

## The lens recommender

At the first decision (step 6), before you choose, three helpers work on a suggestion. The lens advisor reads your question, the facts that count and the full list of lenses, and suggests at most four lenses, or none, with a reason when none fits. For each lens it says which part of your question the lens fits (copied word for word from your question), why, which facts it could use and what is missing. Then two link readers, one on Opus 5.5 and one on Sonnet as the settings file sets them (by the short name `sonnet`, currently Sonnet 5.5), each read on their own, for every link between a suggested lens and a fact, whether the fact bears on one of the lens's three questions. A reader sees the lens's name, idea, suggestion and three questions, and the fact's statement and status. It never sees the advisor's reason or the other reader's verdict. It answers "bears" or "doubt" with one sentence.

You see the suggestion marked as not checked, with a mark beside each link that a reader doubted, and then every other lens grouped by theme (a lens that is in no theme stands under "Not yet sorted"). The list is yours: you may choose any lens, and a mark removes none. When no suggestion can be made, you see every lens and are told why. The report repeats the suggestion under "How this report was made", as advice that nobody checked, with what each reader said and the models the three helpers were set to use (set to, not necessarily run on). When the facts changed after the suggestion was made, the report still shows it as it was made, says so in one sentence, and marks each fact it names that no longer counts; when the suggestion was changed after the program wrote it in a way that breaks its form (a part missing, of the wrong kind, empty or too long), it is not thrown out: the first stop and the report show every part that can still be read, mark each such part where it stands, and propose no lens whose own entry was changed; only a suggestion of which nothing can be read is named as damaged and not shown. A change that keeps the form, such as a reworded reason, cannot be told from the advisor's own words. Beside each lens the report says what it rests on.

**What the program checks, with no model**, when the advisor's list is recorded: every lens it names is a lens of the lens folder and passes the lens check; there are at most four lenses; each part of your question is a word-for-word copy from your question (capital letters and spacing aside, two to fifteen words); every fact it names is a fact of the run that counts and is not taken back; every text is filled in and at most 400 characters; and the record is complete for the facts it saw. The program also builds the grouped list of every lens and each lens's level in plain words, not the lead. It marks a suggestion as out of date when the facts that count have changed since, and then the advisor is asked again. A reader can record only for a link of the suggestion, once, under its own name.

**What is not checked.** That a lens is a good fit for your question; the order of the list; that a reason is sound; that nothing better was left out (the full list is your protection); and that a link neither reader doubted is right. The marks are advice. A bad suggestion cannot make a false fact: the quote check and the support checker still guard every fact, and step 7 uses only facts that count. The worst outcomes are a less useful lens or a missed one.

**Known limits of this part**, in plain words:

- The word-for-word copy shows that the named words are in your question, not that the lens answers them.
- The lens advisor and the first reader are the same model, and the second reader is from the same family; they may share a blind spot. The second reader is smaller and may miss a subtle mismatch or raise a doubt without cause.
- A source about a work can misdescribe the work. The weaker level, the wording "the source states", the required link and the statement of which work it is about are the protection, and they only work if you read them in the report.
- A setting of your own account can force one model on every helper, which would remove the independence of the readers. The report says what the helpers were set to use, not what ran.
- Nobody has measured how good the suggestions are, or how many wrong links each reader catches. A written script and a set of invented links for that exist (`scripts/measure_readers.py` and `tests/fixtures/planted_links.json`), and nothing has been run: it needs your yes, because it costs money.
- What it costs is an estimate: from list prices of 2026-11-03 and guessed sizes, about 0.27 US dollars for a run with six lenses and about 0.38 with fifty, on top of the run, which the plugin's own notes put at about 8 US dollars for the invented demo run. These are guesses until a real run measures them, not a promise.
- That the grouped list stays readable with eighty-three lenses in fifteen themes has not been tried in a real session.

## The helpers

The helpers are narrow on purpose: each has a short list of tools, and each works on one job. The extractor, the checker, the auditor, the lens advisor, the two link readers and the project grouper get a fixed prompt that is written in their files. The scout gets the search task as the lead writes it. The models are set in one place, `settings/models.json`, and `scripts/apply_models.py` writes them into the helper files. The model names are the names of Claude models, as that file lists them: the lens advisor, the first link reader and the project grouper name a model by its full name, so a run does not change when a short name moves to a newer model. How hard each of the three lens helpers and the project grouper thinks is set in its own file. The three lens helpers suggest lenses for your question and read each suggested link of a lens to a fact; step 6 starts them only when no current recommendation exists, the advisor first and then the two readers at the same time, and starts a reader again only for links it has not yet read. The project grouper reads the capacity moves that count, each with its company and countries as the program tidied them and no quote, and gathers the reports that are about one plan at one site into one project: one company and one country to a project, every move in exactly one. That is a judgement and nobody has checked it. The program checks the rules the grouping must keep and records it, and it checks the same rules again when the report is built.

The last two columns tell two kinds of "never" apart. What the tool list or the guard (described below) holds cannot be broken by a helper that goes wrong. What only the instructions hold depends on the helper doing as it is told.

| Helper | Model | Tools | What it does | Held by its tools or the guard | Held by instructions only |
|---|---|---|---|---|---|
| `strategy-radar:source-scout` | sonnet | WebSearch, WebFetch | Searches for public pages and opens them. Hands back a list of candidates with who published each. | Saves nothing, runs no command, settles no fact. | States no fact about a company. |
| `strategy-radar:fact-extractor` | sonnet | Read | Reads one saved source, its record and the two reference files. Proposes facts, each with an exact quote. | Writes nothing, runs no command, settles no fact. | Reads no other file of the run: it has the Read tool, and the guard does not see reads. |
| `strategy-radar:support-checker` | opus | Bash | Runs two `radar` calls only: one to fetch a fact's quote with the sentences around it, one to record its own verdict. | Reads no file and runs no other command (the guard refuses them). Settles no fact. | Records a verdict only for the facts it was given. Only it can record a verdict: the guard refuses such a command from anyone else. |
| `strategy-radar:lens-advisor` | claude-opus-5-5 | Bash | Runs two `radar` calls only: one to fetch the question, the lenses and the facts that count, one to record its list of at most four lenses that fit the question, each with why. | Reads no file and runs no other command (the guard refuses them), and records only under its own name. The program refuses a list whose form fails its check. Settles no fact. | Says nothing about a lens from memory and never decides for you. Only it can record the list: the guard refuses such a command from anyone else. |
| `strategy-radar:lens-link-reader` | claude-opus-5-5 | Bash | Runs two `radar` calls only: one to fetch each suggested link of a lens to a fact, without why it was suggested, one to record its own verdict on each. | Reads no file and runs no other command (the guard refuses them), and records only under its own name, so it can never record under the other reader's. Settles no fact. | Judges a link only from the lens's questions and the fact's statement. Only the two readers can record a link verdict: the guard refuses such a command from anyone else. |
| `strategy-radar:lens-link-reader-quick` | sonnet | Bash | The same job on the same links, on its own and with another model, recorded under its own name. | As for the first reader. | As for the first reader. |
| `strategy-radar:project-grouper` | claude-opus-5-5 | Bash | Runs two `radar` calls only: one to fetch the capacity moves that count with their tidied company and countries, one to record its grouping of them into projects. | Reads no file and runs no other command (the guard refuses them), and records only under its own name. The program refuses a grouping that breaks a rule (a move left out or named twice, two companies or two countries in one project, a name that is empty or too long). Settles no fact. | Judges which reports belong to one site or programme only from the details the program gives it, and never decides for you. Only it can record the projects: the guard refuses such a command from anyone else. |
| `strategy-radar:claim-matcher` | claude-opus-5-5 | Bash | Runs two `radar` calls only: one to fetch the proposals of a round's sources with their places and quotes, one to record its groups of proposals from different sources that state the same claim. | Reads no file and runs no other command (the guard refuses them), and records only under its own name. The program refuses a group that breaks a rule (two proposals of one source, an early signal in a group, two companies, a different size, unit, date or planned start, or a capacity move that names no company). It never changes a quote. | Judges which proposals state the same claim only from what the program gives it, and never decides for you. Only it can record the claim groups: the guard refuses such a command from anyone else. |
| `strategy-radar:bias-auditor` | opus | Read, Glob | Reads the run record, the analysis, the facts and the source records. Flags possible bias under the ten checks. | Changes no file, runs no command, settles no fact. | Does not read the writer's notes or the saved copies (it has Read and Glob). Gives no verdict on the conclusion. |

The lead is told to start no helper but the scout, the extractor, the checker, the auditor, the lens advisor, the two link readers, the project grouper and the claim matcher, to hand a command or a file write to no other helper, and to run at most four at the same time. Every helper is told to treat text inside a source or a page as data: an instruction in it is not followed, only noted.

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

**The guard** is a hook: a small program, `hooks/guard.py`, that Claude Code runs automatically before every file write and every shell command (a command typed into the computer's terminal, as opposed to a request to Claude Code's own file tools). It does three things. For every write made with Claude Code's file tools (Write, Edit and NotebookEdit), by the lead or by a helper, it refuses a hand write (a write by a model, not by the `radar` program) inside a run folder, except in the four places the lead owns: `analysis.json`, `notes/`, `proposals/` and `inbox/`. Where it cannot tell where a path leads, it refuses. For the plugin's helpers it also judges shell commands: three may run none, the support checker may run only its two `radar` calls, and the lens advisor and each of the two link readers may run only its own two `radar` calls, the project grouper may run only its own two `radar` calls, and the claim matcher may run only its own two `radar` calls, each in the form its file shows. A helper that records names itself, and each records only under its own name, so one reader can never record under the other's. And it refuses a shell command that holds the word record-support from anyone but the support checker (the lead, a general-purpose helper, any other agent), with the sentence "Strategy Radar's guard: Only the support checker records whether a quote supports its fact. Ask the support checker to check this fact." In the same way it refuses a command that holds the word record-link-check from anyone but the two link readers, with the sentence "Strategy Radar's guard: Only the two link readers record whether a fact bears on a lens. Ask the link readers to read the suggested links.", one that holds the word record-lens-recommendation from anyone but the lens advisor, with the sentence "Strategy Radar's guard: Only the lens advisor records the lens recommendation. Ask the lens advisor to make the list.", and one that holds the word record-projects from anyone but the project grouper, with the sentence "Strategy Radar's guard: Only the project grouper records the projects. Ask the project grouper to group the moves.", and one that holds the word record-claim-groups from anyone but the claim matcher, with the sentence "Strategy Radar's guard: Only the claim matcher records the claim groups. Ask the claim matcher to match the proposals." That is the one place where it judges a command of the lead, and it is a catch for slips, not a wall. Every refusal begins with "Strategy Radar's guard: ", so you know who refused. It sees no read. A call it cannot read at all is let through, a helper's too. An error of its own while it judges a call it could read lets the lead's call through and refuses a helper's. When it cannot start at all (no Python found, a file of its own missing), its launcher refuses every call of the plugin's helpers and lets everything else through. The gate stays the real check at the end.

Once the plugin is installed, the guard runs in every Claude Code session in which the plugin is on, and its refusals apply to any file that session writes, not only inside a run.

**What rests on instructions and on tests, not on the program:**

- Which helper is called, when, and with which prompt; that no helper but the plugin's nine is started, and that no command is handed to another helper.
- What the lead writes into the analysis: every point names the facts it rests on, only the lenses you chose appear, the outside view is honest, no probability word stands in a message's text, and there is no recommendation, ranking or market-size number. The program checks the form of the analysis, the facts it names and every total listed with it. It cannot check what its free text says.
- That a figure written in the text of the analysis is the one the program computed. The program checks the listed totals. It does not read the text for figures.
- That the lead writes `proposals/merges.json` only as `[]`, as step 4's fallback when the claim matcher gives no groups. `proposals/` is a place the lead may write, so the guard does not stop a list of its own.
- That the lead writes no file of a run with a shell command, and makes no copy or script to get round a refusal. The guard does not judge the lead's shell commands, except one that records a verdict. Claude Code usually asks you before it runs a shell command outside the one line you allowed (your own settings may allow more), and the gate re-checks copies and statuses when the report is built.
- That the lead stops and waits at both decisions and at the private-mode notice, and that the yes or the answer recorded is yours. The program refuses to build without the two decision records, and to make a private run without the acknowledgement and your reply. It cannot tell who gave the answer or wrote the reply.
- That your question and your answers are kept word for word: the program keeps what the lead passes on.
- That only the support checker records a verdict on a fact, beyond the guard's catch for slips.
- That a file of your own on the invented pack is saved only after the warning, and with the data class you gave.
- What the extractor and the auditor read, as the table says.
- That a source which repeats another is noticed and linked, so that it does not count as a second source.
- That an instruction inside a source, a page or a helper's answer is treated as data and not followed.

Tests keep these instructions in step with the program. Seven model-driven tests are written; five of them have run the plugin for real, and two have not been run yet (see "The tests").

## Where things are stored

- A run is a folder of plain files under `radar/runs/` in your project, one folder per run, named by date and time. You can open every file in a text editor. It holds the records of the sources and facts, the saved copies, the analysis, the notes, and the finished report.
- The saved copies of sources are kept out of git (the tool that tracks changes to files) by an ignore file of their own, a small file that tells git to skip them. A private run's whole folder is kept out of git in the same way.
- Your own packs are in `radar/packs/`. The plugin's invented pack is `packs/demo.json`, and its two example lenses are in `engine/radar/demo/lenses`. The eighty-three lenses for real use are in `lenses/`.
- The practice tour builds under `radar/practice/`.
- A file that is passed to the program before a run exists goes to `radar/inbox/`.
- The add-on for PDF files, if you let the guided start make it, is in `~/.strategy-radar`.
- The one permission line, if you accept it, is in `.claude/settings.local.json`. It allows the `radar` program and nothing else. The checker's save of a verdict needs no extra approval under that line, except in one rare case: a note that holds a curly bracket next to a quotation mark. The checker is told to write no curly brackets, and to reword a note that is turned down. That reword was never seen in a live run. The lens advisor sends its list as plain lines, never as JSON, and it and the two link readers are told to write no curly brackets either, for the same purpose; none of their calls has been seen in a live run. Writing notes and files into the `radar` folder and reading files of the plugin may still ask.

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

There are also seven model-driven tests, kept out of the ordinary run. Five of them have been run; two more are written and have not been run. Each of the first five is a real Claude Code session, with the plugin loaded, in a project folder of its own, on the account of whoever runs it. They cover the practice tour, a question put back at a decision (which is not an answer), the private-mode notice, the three planted errors in a half-finished run that the plugin carries on with, with a fact taken back at the final decision, and a whole run with both decisions. Run these five with:

```
uv run pytest -m model tests/model -q --ignore=tests/model/test_recommender_session.py --ignore=tests/model/test_new_lens_session.py
```

The bare command `uv run pytest -m model tests/model -q` starts all seven, also the two that have not been run, and the second of those has no cost estimate.

In the last pass, with Claude Code 2.1.325, the five model-driven tests together came to about 18 US dollars and took about 53 minutes; the whole run was the most expensive (about 8 US dollars), then the planted errors (about 6). These are rough figures for that day, not a promise. Four of the five passed. The fifth, the planted errors, passed every check on the facts, the fact taken back and the report, and missed one: see "Coming back to a run" under the known limits. That check now gives a warning and no failure. The tests are in `tests/model/`.

The two more are written and have not been run, because a model-driven test costs real money and none was started while they were built. One is a real session on the invented demo pack up to the first decision: it checks that the run stops and records nothing until you answer, that the advisor's list passes the form check, that each reader recorded under its own name only, that the lead recorded nothing itself, and that the stop says the suggestion is not checked (`tests/model/test_recommender_session.py`). The other starts the maintainer's `/new-lens` skill on an invented text, in a copy of the needed files in a folder of its own, with five planted errors, and checks that the skill stops twice, that each of the five is turned down (a quote that is not in the copy and a sentence the quote does not support, by the program and the support checker in the evidence run; a text over 400 characters and a lens in no theme, by the lens check, and a run of eight words from the copy, by the overlap check, each as the command printed it), that nothing is written into the lenses folder, and that no passage of the copy reaches the repository (`tests/model/test_new_lens_session.py`). Neither has been tried, so a first run may need its checks adjusted to what Claude Code really does. The first may cost about 1 US dollar, a rough guess that was not derived from a measurement; the second costs more and has no estimate. The reader measurement above is a script, not a test, and runs only with `--run`.

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
- [ ] **A listing in the plugin's folder.** In an ordinary session, start a run on the demo pack and note whether Claude Code asks you before the lead asks the program for the lenses of the plugin's lens folder or lists its practice files, and that the run goes on after you allow it.
- [ ] **The report in a browser.** Open the built `report.html` in the browser you normally use, and check that every tab and link works.
- [ ] **The recommendation on a real question.** In an ordinary session, start a run on the demo pack and look at the first decision: is the suggestion marked as not checked, is each doubt mark readable in plain words, are all the other lenses listed, and can you choose a lens that was not suggested? Then read "How this report was made" in the built report: does it show the suggestion as unchecked advice, with what each reader said?

## Known limits

None of these is hidden in the program. They are what you should know before you rely on it.

### What the program cannot detect

- **Whether a quote means what the fact says.** The program finds words, not sense. Judging sense is the support checker's job, and a model can be wrong: a confirmed fact is one a model judged supported, not one proven true.
- **What the free text of the analysis says.** The program checks the analysis's form, the facts it names and its listed totals. What a key message, a reasoning step or an option says rests on the lead, and a figure written in a text is not read.
- **Who recorded a verdict.** The name on a verdict is whatever the caller wrote. The guard refuses a shell command that holds the word record-support unless the support checker runs it, so the lead, a general-purpose helper and any other agent are refused. It is a catch for slips, not a wall: a command written to hide the word gets past it, and so does every command when the guard cannot start (then only the plugin's helpers are held). An agent of your own that is named support-checker is treated as the plugin's support checker.
- **The verdict rule in other projects.** Where the plugin is on, a shell command that holds the word record-support is refused unless the support checker runs it, also in a project that has nothing to do with a run. The refusal names Strategy Radar's guard.
- **Text a page hides with a stylesheet or a script.** Text that a page hides by plain markup (the mark that hides an element, an inline style that hides it, a closed dialog) is left out of a saved copy. Text marked only as hidden from screen readers is kept, because a browser shows it. Text hidden by a stylesheet (the part of a page that styles it) or by a script (a program that changes the page while you read) is not detected. A web page that is saved with little running text, such as a page whose article a script builds, still counts as saved, but the program marks it, and the report asks you to save the page as a PDF and add it as a file. Text without spaces between words, such as Chinese or Japanese, counts as no running text, so such a page always gets the mark. The sources table for a spreadsheet program does not show the mark.
- **Two publishers on one shared platform count as one source.** Two sources saved from the same site are never independent, whatever publisher was typed. A fact can therefore look less confirmed than it is. A sub-site (a name in front of the site's own name) counts as another site.
- **A file that has a second name on the computer is refused by the guard.** It cannot see where the other names are, so it refuses the hand write and says why. Places it cannot follow, such as those reached through some system shortcut folders, are refused in the same way. These refusals apply to any file a session writes, not only inside a run.
- **Whether the guard runs.** A call the guard cannot read at all is let through, a helper's too; an error of its own while it judges a call it could read lets the lead's call through and refuses a helper's; when it cannot start at all, it holds only the plugin's helpers. `radar doctor` says whether it can run here. The guard does not protect its own files, and whoever starts the session can point its launcher at another program (with `RADAR_PYTHON` or the search path). The gate stays the real check at the end.
- **A size whose unit is in the source's language.** A size is copied as the source writes it. The extractor is told to write the unit in English where it has a plain English form; when it does not, two facts with the same unit in two spellings cannot be added up by the program, and the lead can only count moves.
- **Smaller limits of the program**, each described in `docs/engine.md`: the gate computes every total again, so an unusual calculation is refused rather than trusted; a record written again keeps no file mode set by hand, and the write is not forced to the disk; the site's robots.txt is asked for before the two-second wait, and looking up a site name has no time limit of its own; a few short messages of the program (a wrong option, a refused proposal) have no explanation of their own; a source that could not be saved can still be marked as read and left out; a run folder whose record is not an ordinary file is not guarded against; the pack check does not catch every unusual entry.

### What was not tested

- **Systems.** It was built and tested in a cloud session on Linux, and then on a Mac. Only the guard fixes of the Mac check were looked at for Linux, and by reading only. The later work (the checker's save, the demo's facts, the model tests and the evals) ran on the Mac only. Windows is not supported, because the launcher of the program is a shell script.
- **Live websites.** A few real runs have been made on public websites: three on one real company's question about new capacity, and four screening runs on startups. In them the source scout searched the real web, the program saved the pages it found, and pages that refused the request were logged and left out. A run on a pack for a real company, with the eighty-three lenses, has been tried in those runs only. The automated tests fetch no live website: the download code is tested against stand-in servers on the same computer. Every model-driven test that has been run used the invented practice material. The web search of `/strategy-radar:screen` that proposes competitors and pages has run in three of the screening runs; in the first, the person named them. The propose step for the whole pack and the claim matcher have run in one. A screening run that chooses its lenses without a person has not been seen through: the one run that could have shown it asked for the lenses instead, because the link readers could not read their input, which is mended since. Not tried yet: the propose step of `/strategy-radar:new-pack` on a real company, which proposes the whole pack, and any real run on Linux.
- **Installing.** Installing from GitHub was tried once, on one Mac with Claude Code 2.1.325: it worked, and the practice tour passed as a real session from the installed copy. The other four model-driven tests loaded the plugin with `claude --plugin-dir` and were not run from an installed copy.
- **The guard in an installed copy.** The guard's rule for helpers depends on the helper name that Claude Code passes to it. That name has not been checked for an installed plugin.
- **A Mac without Apple's developer tools.** The pass over Apple's stand-in was tested with made-up files only, never on such a Mac. On a Mac whose developer tools are installed under another name the stand-in is not used either, and a `python3` elsewhere that is only a link to the stand-in is not recognised.
- **Paths no live session walked.** A "no" to the private-mode notice, the questions about a document of your own and a confidential report, a correction of a fact or another lens at the final decision, a refused comparison or build, a version to publish, a refused proposal, a source that cannot be read, a second sending to the checker, the guided start beyond its first checks, and a pack made with the new-pack command from start to end. The extractor's instructions show no example of a quote in another language with its translation.
- **The checklist above.** A printed page, the tables in a German spreadsheet program, a Mac without developer tools and an unscripted session have not been looked at by a person.
- **The lens recommender.** Its form checks are tested with no model. How good its suggestions are, how many wrong links each reader catches, what a run with it costs, what Claude Code does when a helper names a model that your account cannot use, whether the full model name in a helper file is always accepted, and whether the effort line of a helper behaves as the documentation says have not been measured or tried. The two model-driven tests of it are written and have not been run.
- **Speed and accuracy of the model choices.** Which model each helper uses was not measured for speed or accuracy. The guide makes no claim that helpers are faster or better than one model.
- **Where it runs.** It is built for Claude Code only. It has not been tried in claude.ai or in Cowork, which may not run a program or a hook from a plugin.

### What rests on instructions and tests, not on the program

- **Coming back to a run.** When you continue a run that stopped in the middle of the quote checks (step 5), the lead does not always tell you first which step the run is at. In the last test pass it went straight to work, told you what it was doing, and named the step only when it reached your decision on the lenses. At the two decisions, where the run waits for you, it did say the step first.
- **The lead's work.** What the lead writes into the analysis, and when it asks for a decision, rests on its written instructions. The five model-driven tests are one run each, not a proof. A model can answer differently another time. Most tests of the skill files look for the sentences that state a rule, and find `radar` calls by their form (a call written in an unusual way, such as inside double quotes, would not be seen): they show that a rule is written down, not that a model follows it.
- **Your words, word for word.** That your question and your answers at the decisions are passed on unchanged rests on the lead; the program keeps what it is given.
- **A break at the wrong moment.** When a run is broken off after a corrected list of proposals was written and before it was added (steps 4 and 5), the list is not picked up on coming back; its sources are read again. Step 10 tells from the files' times whether your decision came after the last audit; files saved in the same second are listed by their names, as the usual listing does on a Mac and on Linux, and a run folder copied without its times can show any order.
- **The settings line and the setup.** The offered line covers `radar` as a plain command only; a full path to the program still asks. The guided start writes the settings file by hand, as its instructions describe. A setup that fails half-way can leave a half-made folder and the package tool's own downloads behind.
- **Where a run stands when you come back.** When you ask to continue a run, the lead is told to send first the line of the step the run stands at. In live runs it usually did. In one live turn it skipped a step's line, and the check for a run resumed at the fact check is still open. A separate, fixed sentence was tried and dropped, because the lead did not send it in eight live trials.
- **The eighty-three lenses, and no pack for a real company.** What a lens says rests on an independent review by a model of each of its sentences against what its works or slides state, not on the program: the program checks a lens's parts, their length, its levels and the day it was checked, not what it says. A lens on how rivals' capacity decisions interact was planned and is not shipped, because the work it was to rest on does not state it. No shipped lens rests on lecture slides any more. Fifty-five of the eighty-three rest on sources about the works (a textbook section, a web page, an encyclopedia entry, a review or an index record that reprints an abstract), not on the works themselves, so their level is Secondary source read. Twenty-one of the eighty-three have the level Reference confirmed: their text was not read, and each is written from the model's general knowledge of the work and was not checked against it. One lens rests partly on a copy that was read from a scan by text recognition, so a word may have been misread; each quote taken from that copy was compared by a model with the image of its page. No pack for a real company ships: you make your own with `/strategy-radar:new-pack`.
