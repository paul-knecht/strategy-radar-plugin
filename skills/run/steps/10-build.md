Send this as text now, before the step's first command: "Step 10 of 10: Build the report. The program is checking the whole run once more and building the report. Next: nothing more; the report is the end of the run."

# Step 10: Build the report

## 1. Is the decision about the analysis as it stands?

Before anything else, whatever the program says about the next step:

```bash
ls -t "<run>/notes/final-decision.md" "<run>/notes/audit.json" "<run>/analysis.json"
```

It lists the three files, the newest first. A file the command prints an error for is missing; a missing audit file means the audit has not run.

Build only when all three are listed, in exactly this order: the decision mark `notes/final-decision.md`, then `notes/audit.json`, then `analysis.json`. Then the person decided after the audit, and the audit was made after the last change to the analysis. Files saved in the same second are listed by their names, the analysis first and the decision mark last, so a tie never leads to the build.

In every other case:

- **`analysis.json` is listed before `notes/audit.json`, or the audit file is missing.** First do step 8 again.
- **Then, and in every other order or with the decision mark missing,** show the view of step 9 and ask its question again, as step 9 says, including its unattended rule; a new decision is recorded and its mark written as step 9 says, and you build nothing until then.

Every doubt ends in asking again.

The lenses are checked here too. Collect every lens the analysis names: each `lens_id` on a step of a chain and in `lens_notes`. Compare them with the last recorded decision on the lenses, read as step 7 says. When the analysis names a lens that decision does not hold, go back to step 7, then step 8, then step 9. When the decision cannot be settled, the question of step 6 comes first, as step 7 says. Then ask `radar status --run "<run>"`. When it prints `grouping` as anything but `grouped`, do part 8 of `steps/05-verify.md` once, whatever its outcome and without a question to the person: a fact that changed after step 5 leaves the report ungrouped otherwise. Only then go on with part 2.

## 2. Is there an earlier run to compare with?

```bash
radar status --root "radar/runs"
```

`runs` lists the runs, the newest first, each with its `run_dir`, its `question` and its `next`. Find this run in the list. Only a run listed after this run was started earlier. Such a run fits when all of this holds:

- it is finished: its `next` is `null`;
- its `question` is this run's question, word for word;
- it used the same pack. The list does not name the pack. Read `pack` in the file `run.json` of the earlier run and of this run, and compare. You only read these files.

Take the first run that fits, going down the list from this run. Its `run_dir` is `<earlier run>`. When none fits, there is no comparison: go on with part 4.

## 3. Compare, directly before building

```bash
radar compare --previous "<earlier run>" --current "<run>"
```

- **Exit code 0.** The comparison is saved, and the report gets a part on what changed since the earlier run. It belongs to the facts as they stand now. After any later change to a fact (one added, taken back or settled again) the comparison must be run again before the report is built.
- **Exit code 2 with `explained`.** The program refuses to join the two runs: an earlier run with material that is not public and a public run, an invented run and one that is not, or the practice run and another run. This is no fault. Tell the person the entry's `what` and `why`, word for word. Do not act on its `do`, and try no other way to join these two runs. Then try the next run that fits, further down the list, in the same way. When no run that fits is left, the report is built without a comparison; say so. One more refusal is about the earlier run alone: it has facts whose status no longer follows from their checks, so settle the earlier run first. Tell the person its `what`, `why` and `do`: settling changes the earlier run, so it is the person's decision about that run, and you never settle the earlier run yourself. Then go on as for the others.
- **Exit code 2 without `explained`.** The call was wrong. Correct it.

## 4. Build

```bash
radar build-report --run "<run>" --lenses "<lens folder>"
```

- **Exit code 0.** `built` lists the files the program wrote. Go on with part 5.
- **Exit code 1.** The program refused, and nothing was built. Show the person each different entry of `explained` once: its `what`, `why` and `do`, word for word. Then follow each `do` by the means the steps allow: a comparison that is out of date is made again as in part 3; the analysis is changed as step 9 says; a fact is handled as step 5 and step 9 say, and the moves are grouped again, as part 8 of `steps/05-verify.md` says. When this changed `analysis.json` or a fact, the person's decision was about an earlier state: do step 8 again, show the view of step 9 and ask its question again, as step 9 says, including its unattended rule, before you build. Then build again.
- **After three refusals, stop.** Tell the person plainly what is still open, entry by entry. Build nothing in any other way.

## 5. Tell the person what they have

- **The files**, in the run's folder: `report/report.html` (the report; it opens in any web browser), `report/report.md` (the same report as plain text), and two tables for a spreadsheet program. Their names carry the run's marks: `report/facts.csv` and `report/sources.csv` without a mark; `report/facts-illustrative.csv` and `report/sources-illustrative.csv` for an invented pack; `report/facts-confidential.csv` and `report/sources-confidential.csv` in a confidential report; `report/facts-confidential-illustrative.csv` and `report/sources-confidential-illustrative.csv` when both hold. In an illustrative run every row of both tables also has an `illustrative` column that says so. Name the files that `built` lists, with the full path of the report.
- **What it rests on.** Read it from the names `built` lists. When they hold the word `confidential`, the report holds a source that is not public, or it compares with an earlier run that does: it is marked confidential and is not to be shared or published. Otherwise the report rests on public sources only.
- **The date.** Up to which date the sources were read. The report says it near the top of `report/report.md`, in the line that holds the words "Sources read up to".
- **An invented pack.** When the names hold the word `illustrative`, say what the report's banner at its top says: the report was made with an invented company pack as practice material, and nothing in it is a finding about a real company.
- **What the report opens on.** The report opens on the answer to the question the run was asked, with the key messages under it. Its projects are a model's judgement: the program checks the rules a grouping must keep, and nobody has checked which reports belong together. Where the moves could not be grouped, the report shows each move on its own and says why.
- **The comparison.** Whether the report compares with an earlier run, and if it was refused, why.

## 6. A version to publish

In a run whose mode is private this part does not apply; part 4 of `steps/private-mode.md` says what to tell the person. The program refuses a version to publish of every private run as well. The option `--publishable` is added only when the person asks for a version to publish, never on your own:

```bash
radar build-report --run "<run>" --lenses "<lens folder>" --publishable
```

The program refuses when the run holds a source that is not public, or when its comparison is with an earlier run that does. Do not predict its answer: run the command and read what the program answers. When it refuses, show the `explained` entries as in part 4, and look for no way round.

Then ask `radar status --run` again.
