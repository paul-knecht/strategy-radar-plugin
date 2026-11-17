# Lenses

A lens is an idea from strategy or economics, written in our own words, through which a run's analysis looks at the facts. The person chooses the lenses at step 6 of a run. This folder holds the eighty-three lenses for real use: a run on a pack for a real company uses them. The practice tour and the invented demo pack use two other lenses, invented for practice, in `engine/radar/demo/lenses`.

## What a lens file holds

Each lens is one file, named by its id with `.json` added, and it holds exactly these eight parts:

- `id`: the lens's short name, the same as the file name.
- `name`: its title.
- `idea`: the idea, in a few sentences.
- `suggests`: what to look at in a run.
- `limits`: where the idea stops.
- `competing_idea`: another view of the same question.
- `questions`: exactly three questions to ask of the facts.
- `originals`: the works or lecture slides the lens rests on, each with its `reference`, its `level` and its `link` (a web address, or none), and, for an original that is read as a source about a work, its `about`.

A lens for real use also holds `checked_on`: the day it was last checked, written as year, month and day. Nothing else may stand in a lens. Every text is at most 400 characters long, which keeps each text short. That no text repeats a passage of a work was checked by the independent review of each lens and by a program that compares the lens texts with the copies of the originals, on the author's computer.

## The four levels

Each original carries its own level. The program knows four, listed here from the highest to the lowest:

- **Original read** (`original_read`): the work itself was read.
- **Secondary source read** (`secondary_source_read`): a source about the work, such as a textbook chapter or a survey, was read, not the work itself.
- **Course slides** (`course_slides`): lecture slides that present the idea were read, not the work behind them.
- **Reference confirmed** (`reference_confirmed`): the work is named and its reference was confirmed from a public page, which the lens links to, but its text was not read: the lens is written from the model's general knowledge of the work and was not checked against it. It is used only when no free text of the work or about it could be read: the work is behind a paywall, or its free copy could not be fetched or was a file that was not downloaded.

A lens's own level is the lowest level among its originals. Reference confirmed is the lowest, then course slides, then secondary source read, then original read. A lens that rests on an article that was read and on lecture slides therefore has the level course slides. A lens never claims a higher level than the lowest of its originals.

## The `about` part of an original

An original that is read as a source about a work has the level secondary source read. Its `reference` then names the source that was read, and its `about` names the work that the source is about, in at most 400 characters. The program requires `about` exactly for this level and refuses it on any other level. It also requires the original's `link` to be a web address, so that anyone can open the source and confirm it.

## What a lens rests on

- A lens says what it rests on in one plain statement. When every original was read, it says "Rests on: the original, read". For an original that was read as a source about a work, it says "Rests on: the source, a source about the work, read; the original itself was not read", naming both. For course slides and for a confirmed reference, it says what was read and what was not. When several originals were not read as originals, it names the first after "Rests on:" and each further one after "It also rests on", so that none is left out; an original that was read adds nothing.
- A lens rests on what its works or slides state, not on whether the idea is true.
- Every sentence of its idea, its limits and its competing idea says what a work or the slides state.
- `suggests` is our own application of the idea: a plain instruction on what to look at. It makes no claim about the work.
- A limit is a condition that the work itself states, or a criticism that a second original states.
- A competing idea comes from a second original, often the work behind another lens. It may also be an alternative that the same work sets out and controls for.

## Where the evidence is

The author's copies of the works and slides are licensed. They stay on the author's computer, and so does the evidence for each lens: a private run in which each sentence of the lens's idea, limits and competing idea rests on a quote that the program found word for word in a copy, and that the support checker judged to support it. None of it is in this repository. A lens file holds only our own words, the references, the levels and the day it was checked.

## The themes index

`themes.json`, next to the lens files, sorts the lenses into themes so that a person can find the one that fits a question. It is not a lens. It holds one list, `themes`, and each theme has exactly a `name` (at most 400 characters) and `lenses`, the ids of the lenses it groups. Every lens is in exactly one theme. The program refuses an index that names a lens that has no file, that lists a lens twice, or, for the lenses that ship, that leaves a lens out. A lens that is somehow missing from the index is still offered, under "Not yet sorted". The names of the themes are our own grouping, not a classification taken from a work. A new lens goes into an existing theme where one fits.

## Checking a lens

`radar check-lenses` checks every lens in a folder by the rule a run uses. With `--real` it also checks what a lens for real use needs: the day it was checked, and no illustrative reference. In a Claude Code session with the plugin on:

```
radar check-lenses --lenses "<folder>" --real
```

For the lenses of this folder it prints `{"problems": [], "explained": []}`. The two invented demo lenses fail with `--real`, on purpose: their reference is illustrative, they carry no day checked, and their folder has no themes index.

## Adding a lens

The maintainer adds or rebuilds a lens with the `new-lens` skill of this repository, in a checkout of it, through the steps the lenses went through: a reference confirmed from a page that was found and read, a private evidence run whose quotes the program checks and the support checker judges, a fresh review, and nothing written into this folder before the maintainer's yes. Anyone who wants lenses of their own forks the repository and changes it.
