Send this as text now, before the step's first command: "Step 7 of 10: Work out what it means. I am writing the analysis from the facts that count, through the lenses you chose. Next: a look for bias."

# Step 7: Work out what it means

You write one file, `<run>/analysis.json`. It holds the "so what"; the facts stay in the facts.

## 1. Read first

- `<plugin folder>/references/analysis-format.md`: the form of the file, and its two lists "The program checks" and "Only you can keep these".
- `<plugin folder>/references/confidence-wording.md`: how a confidence level and a probability are chosen.
- When `<run>/run.json` says `screening: true`: `<plugin folder>/references/screening-memo.md`, how a screening memo fills the sections.
- The lenses the person chose. The program's record is what counts: the last entry named `lenses` under `checkpoints` in `<run>/run.json` holds the person's words. The note `<run>/notes/lenses.md` is a convenience: when its `Decision` line holds the number of entries named `lenses` in the record, its `Chosen` line names the lenses of that decision. When the note is missing, holds another number or holds no choice, take the lenses from the recorded words, but only when the words name them. When neither settles which lenses were chosen, never guess: go back to step 6, show the lenses on offer and ask its question again. Read the file of each chosen lens, `<lens folder>/<id>.json`, and of no other. What you say through a lens comes from its file, never from memory.
- The facts that count. Run `radar settle --run "<run>"`: under `status`, the facts that count are the confirmed and the uncertain ones. Read their records in `<run>/facts/`. A rejected fact is never used.
- `<run>/notes/frame.md`: what the question leaves out and which way its wording leans.

## 2. Write the analysis

Write `<run>/analysis.json` in the form the format file sets out, with all its sections. `audit_flags` is the empty list `[]`: only the bias auditor's flags ever stand there, and they arrive in step 8.

- Every point names the facts it rests on, and only facts that count. What rests on an uncertain fact is worded as uncertain.
- An early signal is a hint. No message treats it as settled, and it never stands in a calculation or a baseline.
- A baseline is the `company` and its `fact_ids`, and nothing else: no wording of its own.
- Only the lenses the person chose appear, each by the `id` of its file.
- Set out the options with the evidence for and against each. There is no recommendation, no score or ranking of competitors, and no market-size number. Management decides.
- Nothing comes from memory, and nothing from the pack: its companies, drivers and words are hints, not facts.

Before you go on, go through the format file's list "Only you can keep these", point by point. Nothing refuses a breach of those, so they depend on you.

## 3. Every figure comes from the program

Every total, count and share the text mentions is asked for, never worked out:

```bash
radar calc --run "<run>" --operation sum --facts F1,F2,F3,F6 --from-json "<run>/inbox/calc-unit.json"
radar calc --run "<run>" --operation share --facts F4 --of F1,F2,F3,F4,F6 --from-json "<run>/inbox/calc-unit.json"
radar calc --run "<run>" --operation count --facts F1,F2
```

`<run>/inbox/calc-unit.json` holds `{"unit": "lines"}`. The unit is the one the facts state; never convert a unit. The fact numbers stand on the line. A count needs no unit. A share is printed in percent, as a whole number such as `33`.

- Exit code 0: copy `result` as printed into the `result` of the entry under `calculations`, and write the figure in the text only as printed. When `includes_uncertain` is true, say in the entry's `label` that the figure includes an uncertain move.
- Exit code 1: there is no figure, and `result` is null. `problems` and `explained` say why. Use only capacity moves that count, all in one unit, and ask again. Never fill in a figure yourself.

## 4. Let the program check the file

```bash
radar check-data --run "<run>" --lenses "<lens folder>"
```

Run it until it reports no problems: exit code 0 and an empty `problems`. Each entry of `explained` says what to correct. A problem in `analysis.json` is yours to correct, and it is not shown to the person as a finding. When `radar check-data` says that a flag names a message which does not exist, a key message was dropped and the audit no longer fits the analysis: set `audit_flags` back to the empty list `[]`, as step 8 does for an answer that is not usable, and do step 8 again; this is the one case in which the flags are taken out. A problem that `radar check-data` names in the file `lens-recommendation.json` is advice: it does not stop this step, and it is not yours or the person's to repair. Go on, also when the check exits with code 1 for problems of that file alone. A problem that `radar check-data` names in the file `projects.json` is advice in the same way: it does not stop this step, and it is not yours or the person's to repair. Go on, also when the check exits with code 1 for problems of the two files `lens-recommendation.json` and `projects.json` alone. Only the project grouper mends that file, when part 8 of `steps/05-verify.md` is done again. A problem in any other file is not yours to repair: tell the person what the program says, and stop.

The program counts this step as done as soon as the file exists. You are done only when the check reports no problems, or only problems of `lens-recommendation.json` or `projects.json`.

Then ask `radar status --run` again.
