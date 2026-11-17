# Coming back to a run

Read this when the person asks to go on with a run. You find the run, you ask the program where it stands, you go into the file of that step, and the first thing you send the person is that step's own line. Every step file has rules of its own for work that is half done. This file says where to look first, and it adds only what no step file says. Where this file and a step file seem to differ, the step file holds. The one exception is part 5 below: its rules are for coming back, and they come first.

## 1. Which run

`SKILL.md` makes this call before it sends you here; read its answer, and do not make the call twice.

```bash
radar status --root "radar/runs"
```

`runs` lists every run the program can read, the newest first, each with its `run_dir`, `question`, `mode` and `next`. A run is unfinished when its `next` names a step. It is finished when its `next` is `null`.

- **One unfinished run.** Take it.
- **Several.** Name each one by its question, its folder and its next step, in plain words: the name the step table of `SKILL.md` gives the step (for `collect`, "Collect the sources"; for `checkpoint_final`, "Your decision: final report"). Ask which one to go on with. Stop here. End your turn after the question. Do not call any tool, and do not answer for the person. Only the person's next message can answer.
- **None.** Say so. A finished run's report is `report/report.html` in its folder; name it when the person asks for a finished run. Offer to start a new run, as `SKILL.md` says under "Where to begin": it needs a pack and a question.
- **A run the list does not show.** The list leaves out a folder whose record the program cannot read. When the person asks for such a run, say that its record is damaged, that the program cannot say where it stands, and that it cannot be continued. Repair nothing by hand. Offer a new run on the same question.

Say what kind of run it is after the step's line of part 3, in plain words and never with a field name. When `illustrative` is true, the run uses invented practice material. When `practice` is true, it is the invented practice run itself: it can be continued, and it takes no document of the person's own.

## 2. What you need again

- `<run>` is the run's `run_dir`.
- `<lens folder>`: `SKILL.md` names it under "Where things are", by whether the pack is illustrative. The list says that of the run.
- `<pack file>`: steps 1 to 4 need it. Read `pack` in `<run>/run.json`; it is the pack's id, and `SKILL.md` says in which two folders a pack is looked up. You only read this file. When the pack is in neither folder, tell the person that the pack of this run is missing, and stop.
- When `mode` is `private`, read `steps/private-mode.md` as well. Its parts 3 to 5 hold for this run. The notice is not shown again for a run that exists.

## 3. Where it stands

```bash
radar status --run "<run>" --lenses "<lens folder>"
```

Take `next` to the step table of `SKILL.md`, and make the checks that the table and the paragraph under it name: the first row that fits is the step.

Then read that step's file and follow it from its top. The first thing you send the person is that step's own line, the first line of its file, as text, before the step's first command; nothing else comes before it. That line is the line of the step you continue with: when a rule of part 5 sends you to an earlier step first, it is that earlier step's line, and the sentence of part 5 that says why comes after it. Never go by what an earlier conversation or a note says is done: the program says what is done.

## 4. Where to look first

| The program says | The step file | Look at this first | The rule is in |
|---|---|---|---|
| `collect` | `steps/01-frame.md`, `steps/02-plan-search.md`, `steps/03-collect.md` | Which of `notes/frame.md` and `notes/search-plan.md` are there; then which tasks of the plan are logged | the step table; part 5 below |
| `extract` | `steps/04-extract.md` | First the tasks without a log entry (part 5 below). Then `sources_to_read`, and which files `<run>/proposals/` holds | step 4, parts 2 and 4 |
| `verify` | `steps/05-verify.md` | What `radar check-quotes` prints, the list files in `<run>/proposals/` and `notes/retries.md`. Then `radar quote-context --run "<run>" --open` lists the facts still to judge | the opening of step 5, and its parts 2, 5, 7 and 8 |
| `checkpoint_lenses` | `steps/06-checkpoint-lenses.md` | `waiting_for_person` is true: the view, then the question | step 6, parts 1 to 3 |
| `interpret` | `steps/07-interpret.md` | The last recorded decision on the lenses | step 7, part 1 |
| `checkpoint_final` | `steps/08-bias-audit.md`, `steps/09-checkpoint-final.md` | Which of `analysis.json` and `notes/audit.json` is the newer one; then the lenses the analysis names | `SKILL.md`, under the step table; the opening of step 9 |
| `build` | `steps/10-build.md` | The three files that step 10 lists first, then the lenses, whatever the program says | step 10, part 1 |
| `null` | none | The run is finished; nothing is done again | part 1 above |

## 5. What no step file says

These rules are this file's own. They hold only when you come back to a run. The first time a rule of this part sends you to an earlier step than the one the step table gave, tell the person why, in this form: `Before step N can go on, step M has to be finished: <what is still open>.` Step 10's own first check can lead back in the same way; say it in the same form.

- **The run exists.** When `next` is `collect` and `notes/frame.md` is missing, step 1 is the step, but its part 2 is over: the run was started. Never start it a second time. Do its part 1 and its part 3.
- **Tasks without a log entry.** The program counts collecting as done from the first saved source. So when `next` is `collect` or `extract` and `notes/search-plan.md` is there, read `search_log` in `<run>/run.json`. Each entry's `place` names a company and a kind of place, as the plan does. A task of the plan with no such entry is still to do: go back to step 3 and finish these tasks before any source is read. Before you save anything in such a task, look at the records in `<run>/sources/`: a page or a file whose `url` is saved already is not saved a second time. When the plan is missing, there is nothing to compare: go on with the step.
- **A list file from before the break.** In step 4, never add a list file that is already there, such as `proposals/all.json`: you cannot know whether it was added. Part 4 of step 4 builds a new list from the sources still to read, under the next free name. Step 5 has its own way to tell for its two list files. For a correction of step 9, `proposals/correction-<n>.json`, look into `<run>/facts/`: when a fact holds the proposal's statement and quote, the list was added; when none does, add it once, as step 9 says.
- **A fact sent to the checker.** Which facts were sent before the break is not known. An open fact that `notes/retries.md` does not name as sent a second time counts as not sent yet.
- **An analysis that may be half done.** When `next` is `checkpoint_final` and `notes/audit.json` is missing, the analysis was never audited, and it may have been left in the middle. Before step 8, read step 7 and finish the file as its parts 2 and 3 say. Then run `radar check-data --run "<run>" --lenses "<lens folder>"` until it reports no problems, as part 4 of step 7 says; a problem it names in `lens-recommendation.json` or in `projects.json` is advice and does not hold you here.
- **Notes a break swallowed.** When `next` is `extract`, every task is logged and `notes/collect-notes.md` is missing, write it as part D of step 3 says, from the records of the run. When `next` is `verify`, `<run>/proposals/` holds answers and `notes/extract-notes.md` is missing, write it as part 7 of step 4 says, from the `notes` of each `proposals/<id>.json`. Say in such a note that it was written after a break. From step 6 on, a missing note is not written any more; step 6 says what to tell the person.
- **A question that was open.** When `waiting_for_person` is true and the table leads to step 6 or step 9, show that step's view again and ask its question; an earlier message in the conversation is not an answer. When the table leads to step 8, the audit comes first. Any other question a step had asked before the break is asked again by that step.
- **A report that was refused.** When the state of `build` is `blocked`, the program refused the report before. Part 4 of step 10 shows the person why at the next try; its three tries are counted from one again.
