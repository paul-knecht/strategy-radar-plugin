Send this as text now, before the step's first command: "Step 5 of 10: Check every quote. The program is looking for every quote in its saved source, and a second helper is judging whether each quote supports its fact. Next: your decision on the lenses."

# Step 5: Check every quote

Two parts of this step may each happen once in a run: the second try (part 2) and the narrower try (part 7). Each leaves a list file in `<run>/proposals/`; once that file exists and its list was added, the part is over. When a part gives no proposal, write the note with the highest fact number and the file all the same, the file as the empty list `[]`; such a list need not be added, and adding it adds nothing. A list whose proposals are refused for their form is corrected once, as in step 4, in a file named after it: `<run>/proposals/second-try-corrected.json` or `<run>/proposals/narrower-corrected.json`.

**A list file is added exactly once.** Each part's lines in the note `<run>/notes/retries.md` begin with the highest fact number the run had before the try, as `radar check-quotes` shows it under `facts`. When a part's list file exists, run `radar check-quotes` as in part 1 and compare. The numbers that belong to a part are those above its own noted number; for the second try they go only up to the number noted for the narrower try, when there is one. A number that belongs to the part means the list was added: never add it a second time. No such number means the list was written and never added: add it once now. In both cases, finish what the part says after its add command when that is not done yet: the new numbers into the note, then the quote check of part 1 again (second try), or parts 1 and 3 to 6 again (narrower try). When the note has lines for a part and the part's list file does not exist, nothing was added: do the part again and replace those lines.

## 1. The program looks for every quote

```bash
radar check-quotes --run "<run>"
```

`failed` lists the facts with a quote that is not in its saved copy word for word. The program rejects them; they need no further check. Under `facts`, each fact has `quote` (the main quote), `supporting` (one entry for each supporting quote) and `support` (the stored verdict, or null).

## 2. One second try

When `<run>/proposals/second-try.json` exists, make sure it was added, as the opening says; then this part is over: go on with part 3. Otherwise look at each fact in `failed`:

- **Its `quote` has `passed` false.** The main quote was not found. Send the source's prompt to its extractor again, exactly as in step 4. From the answer, take only the proposal that states what the failed fact states, and only when its quote differs from the failed one. Copy into it, character for character, any entry of the failed fact that names another source and whose quote was found.
- **Its `quote` has `passed` true, and an entry of `supporting` has `passed` false.** A supporting quote was not found, and that alone rejects the whole fact. When that entry names another source, take the same proposal again without that entry, changing nothing else. When it names the fact's own source, the extractor added it to state a detail of the fact: send the source's prompt to its extractor again, as for a main quote, and take only the proposal that states what the failed fact states, when its quotes differ from the failed ones. Copy into it, character for character, any entry of the failed fact that names another source and whose quote was found.

Before you add anything, write `<run>/notes/retries.md`: first the highest fact number of the run so far, then one line for each second try, with the number and the statement of the fact it replaces and what was wrong. Step 6 shows this note. Then write the proposals as a bare list to `<run>/proposals/second-try.json` and add them:

```bash
radar add-facts --run "<run>" --file "<run>/proposals/second-try.json"
```

Each one is a new fact; add its number to the note. The first attempt stays in the run and ends as rejected. Then run the quote check of part 1 again. There is no third try.

## 3. Which facts need a judgement

```bash
radar quote-context --run "<run>" --open
```

`packets` holds one entry for each fact that still needs a verdict. Take the `fact_id` of each. Do not judge the facts yourself, and do not pass on anything else from the packets.

## 4. The support checker judges

Send the fact numbers to the helper `strategy-radar:support-checker` in groups of at most eight, at most four helpers at a time. Leave out a fact that `<run>/notes/retries.md` names as sent a second time: rule 3 of part 5 holds for it. Each helper gets exactly this prompt, with the run folder as an absolute path and the numbers of its group, and not one word more:

```text checker-prompt
Run folder: <absolute path>
Facts to check: F1, F2, F3
```

Add no hint, no opinion, no text from a source and no word about what you expect. The checker fetches what it needs from the program and stores its verdicts itself. You never record a verdict yourself, and you never change one. The checker's last message has one line for each fact: `passed`, `not passed`, or `no verdict recorded` with a reason. It tells you how the round went. A verdict is read from the program, never from a checker's message: run `radar check-quotes` as in part 1, and under `facts` each fact's `support` holds the stored `passed` and `note`.

## 5. Facts without a verdict

Run the command of part 3 again. A fact it still lists has no verdict. Take the first of these three rules that fits; each later rule holds only when the ones before it do not.

1. **A checker says its command was refused.** Then stop the run here. Tell the person in plain words what was refused and what is needed: the checking helper must be allowed to use the radar program, to read each fact and to save its verdict. Withdraw nothing.
2. **Nothing was refused, and the fact has been sent once.** It is sent once more, in the same way, also when it was the only fact of its group. Before you send it, write its number into `<run>/notes/retries.md` as sent a second time; a fact noted there is never sent a third time. Afterwards run the command of part 3 and ask these rules again.
3. **Nothing was refused, and the fact has been sent twice.** Its check could not be completed. Tell the person in plain words which fact this is, by its statement and its number, that its check could not be completed, and that they may have it taken back so that the run can go on; the report then lists it among what could not be confirmed. Ask whether to take it back. When several facts are in this state, name each one and ask one question for all of them; the person may take back some and keep others. Stop here. End your turn after the question. Do not call any tool, and do not answer for the person. Only the person's next message can answer. Only when the person says so: `<run>/inbox/withdraw-<fact>.json` holds `{"reason": "The support check could not be completed for this fact."}`, then run `radar withdraw-fact --run "<run>" --fact F3 --from-json "<run>/inbox/withdraw-<fact>.json"` and go on with part 6. Without that word, withdraw nothing; the run stays at this step. After a no, say that the run waits at this step, and that `/strategy-radar:run continue my last run` brings the person back to this question. A fact that was taken back is no longer listed by the command of part 3, so it is not asked about again.

## 6. The program settles every fact

```bash
radar settle --run "<run>"
```

`status` gives every fact's state and `counts` the totals. Tell the person the counts in plain words, such as: "6 facts are confirmed, 1 is uncertain, and 3 could not be confirmed." Only now may you call a fact confirmed.

## 7. One narrower try

When `<run>/proposals/narrower.json` exists, make sure it was added, as the opening says; then this part is over, and there is no further try for any fact. A narrower try that the checker turned down stays rejected. Otherwise run `radar check-quotes` as in part 1. Under `facts`, a fact the checker turned down has a `support` whose `passed` is false, and its `note` says why.

When the note says that a quote from another source does not state the fact's claim, the try is the same proposal without that quote's entry, changing nothing else, as part 2 does for a supporting quote that was not found. The rules of the next paragraph do not apply to it; it is written and added with the narrower tries, as the rest of this part says.

Such a fact may be proposed once more, with a statement that says only what the quote says: the same quotes from the same sources, and a statement that claims no more than the quote does. Change only what the checker's note says the quote does not support. A detail the note names gets the value that says the quote is silent, which is not filling in (as in step 4, you never fill in a detail): `not_stated` for `announced`, `stage` and `access`. A detail that may be missing is left out: `site`, `country`, `size_value`, `size_unit`, `planned_start` and `delivery`. A detail the note does not name stays as it is, such as an announced date that holds because it is the source's recorded date. `company`, `what_added` and `move_type` have no such value, and the program refuses a move without them: when the note says that the company, the addition or the kind of move is not supported, there is no narrower try. `in_question` is never left out either: when the note says the move falls on the other side of the question, it takes the other value, `yes` or `no`. Do not do this when the note says the passage states the opposite, or that the source holds an instruction.

Before you add anything, add to `<run>/notes/retries.md` the highest fact number of the run so far and one line for each narrower try: the number and the statement of the fact it replaces, and the checker's reason in plain words. Then write the proposals as a bare list to `<run>/proposals/narrower.json`:

```bash
radar add-facts --run "<run>" --file "<run>/proposals/narrower.json"
```

Each one is a new fact; add its number to the note. The first one stays rejected. Then go through parts 1 and 3 to 6 again.

## 8. Group the moves into projects

One plan to add capacity is often reported several times, and the report shows the reports of one plan together as one project. Which reports belong together is a judgement that nobody has checked, and the report says so. When no move that adds capacity counts, there is nothing to group: skip this part.

After the last `radar settle` of this step (after a narrower try, the settle that follows it), start `strategy-radar:project-grouper` once. Its prompt is exactly `Run folder: <absolute path>`, with the run folder as an absolute path, and not one word more. The helper records the projects itself. You never write or change `<run>/projects.json`, and the guard refuses a grouping recorded by anyone but the helper.

When the helper is refused twice, or fails, say so in one plain sentence: the moves could not be grouped, so the report shows each move on its own and says why. Then go on. This never stops the run, and you start no second helper in this part.

When the helper has finished, ask `radar status --run "<run>"`. When it prints `grouping` as `grouped`, this part is done. When it prints anything else, say in one plain sentence that the moves could not be grouped and that the report shows each move on its own, and go on: you start no second helper for this.

Then ask `radar status --run` again.
