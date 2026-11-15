Send this as text now, before the step's first command: "Step 1 of 10: Frame the question. I am checking the pack and starting your run. Next: plan the search."

# Step 1: Frame the question

You need the person's question and the pack file. `SKILL.md` says how a pack is found and what `<pack file>`, `<run>` and `<plugin folder>` stand for.

## 1. Check the pack

```bash
radar check-pack --file "<pack file>"
```

- Exit code 0: the pack is clean. Keep what it prints: `pack` (its `id`, `company` and `illustrative`) and `window` (`from` and `until`). Step 2 needs the window.
- Exit code 1: the pack has problems. Show the person each entry of `explained`: its `what`, `why` and `do`, word for word. Then stop. No run is started on a pack with problems.

## 2. Start the run

Write the file `radar/inbox/new-run.json` with your file tool. `radar/inbox/new-run.json` holds `{"question": "Which competitors are adding filling capacity, and for whom?", "home-company": "Example Pharma"}`.

- `question` is the person's question, word for word. Do not improve it.
- `home-company` is the pack's `company`.

```bash
radar init-run --root "radar/runs" --pack-file "<pack file>" --from-json "radar/inbox/new-run.json"
```

The program reads the pack's id and its illustrative mark from the pack file. Never name the pack in another way, and never set a mark yourself.

It prints `run_dir`. That folder is `<run>` from now on. Exit code 1 means the pack has problems after all: show `explained` as above and stop.

When the pack says `illustrative` is true, tell the person once, in plain words: this run uses invented practice material, and its report will say so at the top.

## 3. Write the frame note

Write `<run>/notes/frame.md`. It is about the wording of the question only. You know no fact about any company yet, and the pack holds hints, not facts: state none.

The note has three headed parts, each two to four plain sentences:

- `## One answer, or which of several?` Is this a whether-or-not question ("should we build?") that would be better asked as "which of several" ("build, buy, or wait?")? Name the options the question leaves unsaid.
- `## What the frame leaves out` Which companies, places, periods or kinds of move does the wording shut out? What would a wider or a narrower question look at?
- `## Does the wording lean?` Does the wording already lean towards an answer, for example by a word such as "threat" or "must"? Quote the word and say which way it leans.

When a part suggests another wording, write the suggested wording under that part. It is shown to the person at the first decision.

The question of the run is not changed, here or later. If the person wants another question, that is a new run.

Ask the person nothing in this step.

Then ask `radar status --run` again.
