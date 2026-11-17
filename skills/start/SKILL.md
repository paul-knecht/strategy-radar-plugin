---
name: start
description: Guided start for Strategy Radar. Checks that everything needed is installed, fixes what it can with the person's permission, and asks for the company, the question and the mode one at a time. Use when someone is new to Strategy Radar, asks how to begin, or asks to set it up.
---

# Guided start

You take a person from nothing to a started run: seven parts, in order. This skill starts no run itself; the run skill does.

- One question per message. Never two. A line that starts with the word Ask is a question: say it, then stop on the line under it.
- A yes counts only in the person's own next message. A question from the person is answered, and then your question is asked again. An answer that is unclear ("ok", "continue", "maybe") is asked about again.
- Nothing is installed, written or started before a yes.
- Calls are plain `radar` calls, one command per call, nothing joined to them. The person's own words, such as their question, are never on a command line.
- Say everything in plain words. You never say a key name or a program value to the person, and you never show a code.
- Start no helper: this guide needs none. Never hand a command or a file write to any other helper, such as a general-purpose one. When Claude Code or the guard refuses a command of yours, or your shell is not available, say so to the person and stop.
- Read a file with your file tool, never with a shell command such as `cat`, `sed` or `head`. To find files, use your search tool when the session has one; when it has none, list one folder with `ls "<folder>"`, or `ls "<folder>"/*.json` (`*.txt` for texts), as a call of its own, with nothing joined to it. Outside the project folder Claude Code may ask the person first; when the listing is refused, say so to the person and stop, as the rule above says.

## 1. Check the setup

```bash
radar doctor
```

Read `python_ok`, `pypdf_ok`, `hint`, `guard` and `guard_hint`. Exit code 1 here is not a failure: it means something is missing. When it prints `guard`, tell the person in one plain sentence whether Strategy Radar's guard can run here: with `ok`, that it runs on this computer; with `not_running`, that it cannot run on this computer, with the advice of `guard_hint` in your own words. Say in the same sentence that the final check before a report is built holds either way.

- When it prints `error` and `hint` and no `python_ok`, no suitable Python was found. Tell the person that Strategy Radar needs Python 3.10 or newer and that none was found. Pass on the advice in `hint` in your own words: install Python from python.org, then start this guide again. On a Mac, a window may offer to install Apple's developer tools; installing Python from python.org is the simpler way. Stop there; no question.
- When the call ends with a message that `radar` is not found, the plugin's program cannot be reached in this session. Say so in plain words: the plugin may need to be loaded or installed again. Stop there; no question.
- When `python_ok` and `pypdf_ok` are both true, say in one sentence that everything is in place, and go on to part 2.
- When `pypdf_ok` is false, reading PDF files needs one small add-on. Say that `radar setup` makes a folder of its own, usually under `~/.strategy-radar`, and puts the add-on into it; the commands show the exact place. Claim nothing about the setup that the dry run does not show. Say that the practice tour needs no PDF add-on. Then show what it would do:

```bash
radar setup --dry-run
```

Show the person the two commands it prints, as they are. They are the one exception to the rule against showing a code. Say in plain words what they do: the first makes the folder, the second downloads the add-on into it from the Python package index on the internet.

Ask: "Shall I set this up now? It needs an internet connection. Please answer yes or no."
Stop here. End your turn after the question. Do not call any tool, and do not answer for the person. Only the person's next message can answer.

Run `radar setup` only after a yes. Then run `radar doctor` again and say in one sentence what it shows. When setup prints `error`, tell the person what it says and go on without the add-on. After a no, go on without it, and say that a PDF file cannot be read until the add-on is there; this guide can set it up when it is started again.

## 2. Offer fewer approval prompts

First, before you say anything about it, read `.claude/settings.local.json` with your file tool (a missing file is fine). Then:

- When the line is already there, say so and skip the question. Go on to part 3.
- When a `deny` or `ask` entry already matches the `radar` program (a rule that names radar, or one that matches every command), the line would be useless: say so outright, skip the question and go on.
- When the file is not valid JSON, or is not an object, or `permissions` is not an object or `allow` is not a list, tell the person what you found, write nothing and change nothing, and show the line so that they can add it themselves. Skip the question and go on.

Otherwise: Claude Code asks before each program call. One line in the project's settings file, `.claude/settings.local.json`, lets the `radar` program run without asking. The file is meant for the person alone. The line goes into the `allow` list under `permissions`:

`"Bash(radar *)"`

Say what it allows: the `radar` program, with any options, and nothing else. It allows no other command, no reading or writing of files, no other program, and a command that joins radar with something else still asks. Say honestly what it does not cover, and tell the person "I do not offer anything wider." The line also covers the checking helper when it saves its verdict on a fact. Claude Code may still ask about such a save in one rare case: a note that holds a curly bracket next to a quotation mark. The helper is told to write no curly brackets in a note, and to word the note again when such a save is turned down. Writing notes and files into the `radar` folder and reading files of this plugin may also still ask.

Ask: "Shall I add this one line to .claude/settings.local.json? Please answer yes or no."
Stop here. End your turn after the question. Do not call any tool, and do not answer for the person. Only the person's next message can answer.

Only after a yes, write the file with your file tool (no other settings file, never the one in your home folder), from what you read:

- When the file is missing, create the file with `{"permissions": {"allow": ["Bash(radar *)"]}}`.
- When it holds no `permissions`, or `permissions` has no `allow`, add them. Otherwise the line goes at the end of the `allow` list.
- The merge keeps everything the file already holds: every other key, every entry already in `allow`, and the `deny` and `ask` entries.
- When the write is refused, show the line so that the person can add it themselves, and go on.

Afterwards read the file back and tell the person what it now says about `radar`. Then read the project's `.gitignore` and say what you found: whether it lists this file, or whether there is no `.gitignore`. This looks only at that file; never say it is ignored without having looked. When it is not ignored, say so and leave the choice to the person. After a no, go on without the line.

## 3. Offer the practice tour

The tour is for someone who has not used the plugin before. Ask the program what exists:

```bash
radar status --root "radar/runs"
```
When `runs` lists any run, or a listing of `ls "radar/practice"` (as the rules at the top say) shows a run folder there because the tour was played here before, the person has used the plugin: skip the question below and go on to part 4. When the listing says that `radar/practice` is not there, the tour was not played here: that is an empty listing, not a refusal, and you go on. Say of each listed run only what the program says about that run. When its `illustrative` is true, say that the run rests on invented material. When its `next` names a step, say that the run is not finished and can be continued with the run skill (`/strategy-radar:run continue`); the run skill asks whether to continue it or to start a new one. When its `next` is null, say that the run is finished. Do not try to tell the practice tour's own run from a run the person started: the tour builds under `radar/practice`, which this list does not show.

When the list is empty:

Ask: "Shall I start a practice tour? It takes two minutes, needs no internet and uses invented data only. Please answer yes or no."
Stop here. End your turn after the question. Do not call any tool, and do not answer for the person. Only the person's next message can answer.

After a yes, hand over to the practice skill (`/strategy-radar:practice`) and end this guide. After a no, go on.

## 4. Which company

Find the packs as the rules at the top say, in two folders: `ls "radar/packs"/*.json` in the project, and `ls "${CLAUDE_PLUGIN_ROOT}/packs"/*.json`. A folder that is not there holds no pack. A pack in the project wins over a plugin pack of the same id. For each file found:

```bash
radar check-pack --file "<pack file>"
```

Read `pack` (its company and whether it is illustrative). A pack with problems is not offered: show its `explained` entries word for word.

Tell the person which packs exist, by company, and which are illustrative. Say what that means: a run on an illustrative pack is practice with invented data, and its report says so at the top. Today the plugin ships only the invented demo pack: no pack for a real company ships, and a run on a pack for a real company has been tried on real websites in only a few runs so far. For another company, offer `/strategy-radar:new-pack`; to screen a startup as an investor, offer `/strategy-radar:screen`. A company is never researched from memory, and no run starts without a pack file.

Ask: "Which company do you want to look at?" and list the packs.
Stop here. End your turn after the question. Do not call any tool, and do not answer for the person. Only the person's next message can answer.

## 5. Which question

Read the chosen pack file with your file tool. Show its `strategic_questions`, numbered, each with its `text` word for word. Say for each where it comes from: `framing` `company` means the pack says it comes from the company's own statements, with a page and a sentence as its source, and no run checks that yet; `framing` `user` means it is someone's framing, and `framed_by` names whose. A pack's companies, places and demand drivers are hints, never facts; do not present them as findings.

Ask: "Which question shall the run answer? Pick a number, or write your own question."
Stop here. End your turn after the question. Do not call any tool, and do not answer for the person. Only the person's next message can answer.
A question the person writes is kept word for word. Do not improve it.

## 6. Which mode

Ask: "The usual choice is public sources only: the run uses web pages and documents that anyone can read. The other choice is private mode, which also uses documents you hold yourself, and comes with a notice that you read and confirm first. Which do you want?"
Stop here. End your turn after the question. Do not call any tool, and do not answer for the person. Only the person's next message can answer.

- Public sources only: the mode is public. Go on to part 7.
- Private mode: the mode is private. This part only records the choice. Do not show a notice, ask for a confirmation or confirm for the person. Go on to part 7.

## 7. Hand over to the run

Say what you hand over: the pack file (name it), the question word for word, and the mode. Then start the run skill (`strategy-radar:run`) with these three. The run skill starts the run; this skill starts none, and you write no run file.

When the mode is private, say so to the run skill: it reads its `steps/private-mode.md` before its first step, and it shows the notice and asks there. What follows a no to the notice is the business of the run skill and of that file, not of this guide.
