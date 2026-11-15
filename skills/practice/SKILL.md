---
name: practice
description: A two-minute practice tour of Strategy Radar on invented data, without the internet. Shows checked facts, three refused facts, the finished report and a refused build. Use when someone wants to try Strategy Radar, see how it works, or asks for a demo.
---

# Practice tour

Your very first output, before you run any command or read any file, is one sentence to the person: everything in this tour, every company, figure and source, is invented, and no model judges anything here. Send that sentence as text now, then start part 1.

The tour plays back a prepared run and shows what the program recorded. It needs no internet, uses no web tool and no helper, and writes only under `radar/practice` in the person's project.

The tour asks nothing and does not stop: it runs through its six parts in one go.

- Start no helper: the tour needs none, and never hand a command to one. When Claude Code or the guard refuses a command, or your shell is not available, say so to the person and stop.
- Calls are plain `radar` calls, one command per call, nothing joined to them, folders in double quotes. Run only the calls shown here. Never write a file by hand, and never start a real run.
- Say everything in plain words. Never say a key name or a stored word to the person. Name a fact by its statement as well as its number.
- Every number and text you say comes from what the program prints or from the files named below, never from memory.

## 1. Build the invented run

```bash
radar demo --root "radar/practice"
```

It prints the run folder, the folder of the lenses and the folder of the source texts. Below, `<run>` is the run folder and `<lenses>` is the folder of the lenses, as printed. Tell the person where the run is.

When the folder already exists, the program prints a message that says so and builds nothing. Tell the person, and build in `radar/practice/2` instead: the same call with that folder (then `radar/practice/3`, and so on). Use that folder for the rest of the tour, including part 5.

## 2. Where it stands

```bash
radar status --run "<run>" --lenses "<lenses>"
```

Read out the seven steps in plain words, in this order: Collect the sources, Read the sources, Check every quote, Your decision: lenses, Work out what it means, Your decision: final report, Build the report. The first six are done; the next step is to build the report. Say what the program says about the sources, the facts and how many were confirmed, uncertain and rejected.

Say that the two decisions in this run were answered by recorded test answers, which the run's record shows. In a real run the tool stops and waits for the person.

## 3. Three refused facts

Three of the ten facts were rejected on purpose. For each, read its record, `<run>/facts/F8.json`, `F9.json` and `F10.json`, with your file tool, never with a shell command. Say what the fact claims and what its quote is, then why it was refused, in two sentences each. The plain reason of F8 is "The quote was not found in the saved source." The plain reason of F9 and of F10 is "The checker judged that the quote does not support the fact."

- F8: the quote has a number that the source does not have. The program looked for the quote word for word in the saved copy (`<run>/copies/<source number>.txt`, with the source number taken from the fact's record; not the file ending in `.orig.txt`) and did not find it, so it refused the fact alone. Read the saved copy with your file tool, find the sentence on the same subject and say which number it gives.
- F9: the quote is in the source word for word, but it gives another year than the fact. The quote check passed and the checker said no. Read out the checker's note from the fact's record, word for word, with the plain reason.
- F10: the quote is in the source word for word, but it is cut just after the word "not". Show the passage around it:

```bash
radar quote-context --run "<run>" --fact F10
```

Show the `passage`, the whole sentence, and the `quote` inside it, and say that the quote starts right after "not", so the sentence says the opposite of the fact. No matching rule sees this; only a reader of the passage does. Read out the checker's note from the record, word for word.

Say that the checks in this tour were recorded in advance. In a real run a second reader reads the passage and writes the note.

## 4. Build the report

```bash
radar build-report --run "<run>" --lenses "<lenses>"
```

It prints the files it wrote. Tell the person to open `<run>/report/report.html` in a browser; `report.md` holds the same text, and the two tables are for a spreadsheet. Say that the report is marked as illustrative at the top: it was made with an invented company pack as practice material, and nothing in it is a finding about a real company.

Say where to look: the "Summary", with three key messages and the facts each rests on; "Thinking behind this analysis", where all three key messages are opened, each from its facts through the reasoning to its conclusion; and, in "Checks on this analysis", the part "What we could not confirm", where the three refused facts are listed with their quotes and reasons.

## 5. A refused build

```bash
radar demo --root "radar/practice" --variant tampered
```

This builds a second invented run, in its own folder next to the first, in which a rejected fact has been slipped into the analysis. If part 1 used `radar/practice/2`, use that folder here too. Use the run folder it prints as `<run>`.

```bash
radar build-report --run "<run>" --lenses "<lenses>"
```

The program refuses to build this report and writes nothing. Tell the person that the program refused to build the report, and why, in the program's own words: show each entry of `explained`, its `what`, `why`, `do`, word for word. Never name the exit code or any other code. Do not act on the `do` line: the tour changes nothing. Say in one sentence that this is the rule the whole tool rests on: no fact without its checked quote.

## 6. Next

End by offering `/strategy-radar:start`, which shows which company packs are available and starts a run; do not say a real company can be looked at today.
