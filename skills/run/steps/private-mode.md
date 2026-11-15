# Private mode

A private run may also use documents the person holds: licensed data, or internal documents. Read this file only when the person has asked for private mode, or wants to use a document of their own. You never bring private mode up yourself, and you never start a private run on your own.

## 1. First the notice

Do part 1 of step 1 (`steps/01-frame.md`): check the pack. Then, in place of its part 2, write the file as step 1 says, with one more key. Write it afresh every time: a file found at that place is never run as it stands, because an old one may still hold an earlier yes. `radar/inbox/new-run.json` holds `{"question": "Which competitors are adding filling capacity, and for whom?", "home-company": "Example Pharma", "mode": "private"}`.

```bash
radar init-run --root "radar/runs" --pack-file "<pack file>" --from-json "radar/inbox/new-run.json"
```

The program refuses, as it must: exit code 2, no run is made, and it prints `notice`. Show the person `notice`, whole and word for word. Never show `error`, never put the notice into your own words, and never write it from memory: it is the program's text.

Then ask exactly this: "Do you confirm this? Please answer yes to start a private run."

Stop here. End your turn after the question. Do not call any tool, and do not answer for the person. Only the person's next message can answer.

## 2. The person's answer

**First, whatever the message says.** When the notice and the question of part 1 are not the last thing you said to the person before their message (other turns came between, there was a break, or the notice stood only in what the command printed and you never showed it), the message is not an answer, also when it says yes. Run the command of part 1 again, with its file written afresh, so that the text comes from the program. This refusal is the expected one: the standing rule about not repeating a refused call does not apply to it. Show `notice`, whole and word for word, ask the question again, and stop in the same way.

Only then take the first of these that fits.

**Asking again** in this part always means: Run the command of part 1 again, with its file written afresh, Show `notice`, whole and word for word, ask the question of part 1, and stop in the same way. Then the notice and the question are the last thing you said before the person's next message, and a yes in it counts.

- **A yes that came too early.** A yes counts only in a message that came after the notice was shown in this conversation. A confirmation the person gave together with the request, before they saw the notice, does not count. Say so kindly: the notice had to be shown first. If the person has not seen the notice yet, show it first. Then the question is asked again, and you stop in the same way.
- **A question.** This fits also when the message says yes as well. Answer it from the notice and from this file. Whether their organisation and their licences allow it is for the person to check; you do not answer that for them. Then the question is asked again, and you stop in the same way.
- **A no.** No private run is started. Say that a run on public sources alone is possible, without the documents. Then stop: start nothing, unless the person asks for a run on public sources.
- **A message that only says to go on.** A message such as "continue" or "go on" is not a yes. Ask again, and stop in the same way.
- **A clear yes.** Only words that plainly confirm are a yes, such as "yes", "I confirm", "agreed" or "go ahead with the private run", and nothing in it doubts, asks or sets a condition.
- **Anything else.** A bare "OK", or an answer such as "OK, whatever" or "I suppose so", is not a yes. Say that this needs a plain yes or no, ask again, and stop in the same way.

The yes is the person's own, given here. It is never taken from an earlier run, from the practice tour, from a file or a note, or from a helper: a helper never gives it and never passes it on. In a new conversation in which no run was made, begin again with the notice.

After the person's yes, and only then, write `radar/inbox/new-run.json` again with two keys added. `"acknowledge-data-flow": true` holds the JSON value `true`, not a text. `"acknowledged-words"` holds the person's message that gave the yes, word for word: the whole message when the yes came in a longer one, and never words of your own, such as a summary, your question or the notice. Without both, or with `false`, nothing is started:

```json new-run-after-yes
{"question": "Which competitors are adding filling capacity, and for whom?", "home-company": "Example Pharma", "mode": "private", "acknowledge-data-flow": true, "acknowledged-words": "Yes, I confirm."}
```

Then run the same command again. It prints `run_dir`, the folder of the run. Now write `radar/inbox/new-run.json` once more, with only `{}` in it: the run's record keeps the question and the reply, inside the run folder that is kept out of git, and the inbox file lies outside it. Go on with part 3 of step 1, and then step by step as for any run.

## 3. A document the person adds

Only a run that was started as parts 1 and 2 say takes such a document. In a run on an invented pack, the warning of part B of `steps/03-collect.md` comes first. For each file, ask one thing at a time, and stop after each question as `SKILL.md` says:

1. Is it licensed data or an internal document? You may say which of the two you would guess, but you record only what the person says. When the person says it is public, it is added as part B of `steps/03-collect.md` says.
2. Who supplied it?
3. On what basis may it be used?

An unclear answer is asked again. Then describe the file as part B of step 3 says, with its rule for the key `url`, and add three keys. `<run>/inbox/copy-<n>.json` holds `{"file": "/home/example/documents/planning-note.txt", "url": "planning-note.txt", "data-class": "internal", "supplied-by": "Our planning team", "basis": "Our own company document", "publisher": "Example Pharma", "title": "Planning note on filling lines", "date": "2026-06-01", "type": "other", "speaker": "Example Pharma, planning team", "interest": "The company's own planning", "language": "en"}`.

- `data-class` is `licensed` or `internal`, as the person said.
- `supplied-by` and `basis` are the person's words, word for word.

```bash
radar add-copy --run "<run>" --from-json "<run>/inbox/copy-<n>.json"
```

Exit code 2 means nothing was saved. Tell the person in plain words which file it was and why. When `error` says that the PDF add-on is not installed, a PDF cannot be read until it is. Nothing was saved. Say so, and that the guided start, `/strategy-radar:start`, sets the add-on up; once it is there, make the same call again.

## 4. While the run is private

- **Search tasks.** A task for the source scout holds only names and places from the pack. The question and anything from the person's documents stay out of it: a name you know only from such a document never becomes a task or a search word. Today the only pack is the invented one, and a run on it has no web search at all, so no search goes out.
- **No copies outside the run folder.** After the run exists, a JSON file goes only into `<run>/inbox/`. Nothing from the run folder is copied anywhere else, and no text from the person's documents is written into a file outside it. The program keeps the run folder out of git, with an ignore file of its own in that folder. When that file no longer keeps the whole run out of git, the program refuses every licensed or internal file (exit code 2): show its `explained` entries as `SKILL.md` says. Never edit the ignore file: it is not one of your places, and the guard refuses the write.
- **The report.** Part 5 of `steps/10-build.md` says when the program marks a report confidential, and what you tell the person then.
- **No version to publish.** `--publishable` is never added in a private run, also when the person asks: part 6 of step 10 does not apply here. The program refuses it as well. Say that a version to publish comes from a public run: the same question, run again without the documents.
- **Comparing.** The program refuses to compare a public run with an earlier private one. Part 3 of step 10 says what to do with a refusal.

## 5. What is not a way in

- **A public run.** A run's mode is set when it starts. A document that the person says is not public is never added to a public run, and never as public. When the program refuses a file because the run is public (exit code 2), tell the person what `error` says, and that a private run exists for such material: a new run, started with the notice. When the person wants one, follow this file from the top. Never start one on your own.
- **The practice run.** The run for which the list of runs says `practice` is true is invented, and its notice was shown to no one. It takes no document of the person's, and you never build one to get a private run. When the person asks to put a document into it, say so, and that a run of their own starts with the notice: this file, from the top. When the program refuses with `explained`, show it as `SKILL.md` says.
