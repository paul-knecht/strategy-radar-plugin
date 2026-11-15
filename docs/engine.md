# The Strategy Radar engine

The engine is a small program called `radar`. It keeps the facts of an analysis honest. It saves sources, checks that every quote really appears in the saved source, refuses to build a report that rests on something unchecked, and builds the report.

**Everything used for testing and for the demo is invented.** Every company, person, product, place, figure and source text in `engine/radar/demo/` and `tests/` is made up. `Example Pharma`, `Competitor A` and the rest do not exist. Reports built from them say "Illustrative only" at the top.

**The engine itself never contacts a language model.** It does plain checking and arithmetic. It uses the internet in two places only: `radar save-source` downloads one public web page or text PDF that you name, and `radar setup` downloads the PDF library (`pypdf`); running it again repairs or updates the environment. A language model (in the Strategy Radar plugin, whose guide is `docs/plugin.md`) proposes facts and writes the analysis. The engine then checks what the model produced.

In the examples below, `RUN` stands for a run folder such as `runs/20261112-101500`, and `LENSES` stands for the folder that holds the lens files, such as `engine/radar/demo/lenses` (the command `radar demo` prints the exact path).

## What the engine does and does not do

It does:

- save a source as a text copy and remember its fingerprint, so a later edit is noticed;
- check that a quote appears word for word in that copy. Spacing, line breaks, typographic variants of quotation marks and dashes, ligatures, soft hyphens and words split at a line end do not matter; words, capitals, numbers and all other punctuation do;
- accept a quote only where it covers whole words as they stand between spaces in the copy. Only sentence punctuation, brackets and quotation marks may be left off at its ends. So "likely" is not found in "unlikely" or "(un)likely", "add 20" is not found in "add 20%" or "add 20.5", and "Drug Maker B" is not found in "Drug Maker B's", while "starting in 2028" is found in "(starting in 2028).";
- record whether someone independent confirmed that the quote supports the fact;
- settle each fact as confirmed, uncertain or rejected, and delete nothing. A fact you no longer want is withdrawn, not deleted;
- compute totals and shares from sourced figures, in one unit, without rounding surprises;
- refuse to build a report until every check passes, and say why in plain words;
- compare two runs and say what is new, changed or gone;
- build the report: a web page, a plain-text version and two tables.

It does not:

- decide what is true. It checks that a quote is in a source and that a person or checker said it supports the fact;
- convert units or currencies;
- log in anywhere or read paid databases. Non-public material only enters as a file you export yourself;
- write the analysis. The plugin's language model writes `analysis.json`; the engine checks it.

## The run folder

A run is one folder of plain files. You can open every file in a text editor.

```
RUN/
  run.json            the question, the mode, the checkpoints, the search log, how many records were created
  sources/S1.json    one record per source
  copies/S1.txt      the saved text of each source (never goes into git; the folder has its own .gitignore)
  facts/F1.json      one record per proposed fact, with its checks and status
  analysis.json      the messages, scenarios, predictions and totals
  changes.json       written by `radar compare`
  report/            the built report and the two tables
```

A private run's `.gitignore` holds the one line `*`, so the whole run stays out of git. The data check (and so the gate) names a private run whose `.gitignore` is gone or no longer holds `*` on a line of its own, or holds a line that starts with `!` and so takes something back (`the ignore file of a private run must keep the whole run out of git`), and `add-copy` then takes no licensed or internal file into it (exit code 2, with `error` and `explained`); public material still comes in. A public run has a `.gitignore` of its own with four lines: `.lock`, `.fetch.lock`, `.last_fetch.json` (what the program keeps beside the records) and `.*.tmp` (a temporary file that a write which was cut short leaves behind). A private run is ignored whole. A file whose name starts with a dot in `sources/` or `facts/` is never a record: `status`, the data check, the gate and the report all leave it out.

Every record is written whole or not at all: to a temporary file beside it, then swapped in. The swap does not keep a file mode that was set on the record by hand, and it does not force the data onto the disk, so a power cut right after a write can still lose it.

Commands may run at the same time on one run. Every command that changes a record after reading it holds the run's lock (the file `.lock`) from the read to the write: `check-quotes` and `settle` for the whole of their work, `record-support`, `withdraw-fact`, `add-based-on`, `checkpoint`, `log-search`, `log-excluded` and the counting of a new source or fact for theirs, and `build-report` from the gate to the last report file it writes, so no record can change between the check and the report built from it. A second such command waits until the lock is free, so nothing one of them writes is lost, but for at most 60 seconds: then it ends with exit code 2 and `{"error": "Another command is still working on this run. Wait a moment and run this again.", "busy": true}`, having changed nothing. Counting a new source or fact waits as long as it takes, because the record is already written by then; the lock that spaces out downloads (`.fetch.lock`) also waits without a limit. The lock is the operating system's lock on the open `.lock` file: it ends with the command, also when the command is stopped or killed, so a command that died never blocks the next one (the empty file stays). Every command first checks that each run it names is the folder of a run (a usage error otherwise), so none ever leaves a lock file in another folder. Commands that only read (`status`, `gate`, `quote-context`, `check-data`) take no lock and always see whole files.

## Commands

Every command prints one line of JSON; only `--help` prints usage text instead. The exit code is 0 when all went well, 1 when problems were found or the gate refused, and 2 when the command was used wrongly. The line is UTF-8 whatever the terminal is set to, so a terminal that is not set to UTF-8 still gets valid JSON (a program that reads it decodes it as UTF-8); where the output has no byte stream, it is plain ASCII with `\u` escapes. A folder that is not a run (also one whose `run.json` cannot be read, or holds no record of a run: every run record has its `run_id`, its `mode` and its three lists `checkpoints`, `search_log` and `excluded`, so `{}` is no run; only `gate` and `check-data` report that as a problem), a file that does not exist and a folder given where a file is expected are usage errors that name them, and any other trouble with the disk or the system also ends as one line with exit code 2, never as a program trace.

Run them from the project folder as `bin/radar <command>`.

**init-run** starts a run. Name its pack in one of two ways. `--pack-file FILE` names a pack file: the pack is checked first, as `check-pack` checks it, and a pack with any problem starts no run (exit code 1, `problems` and `explained`, nothing made); the run then records the pack's `id`, and it is illustrative when the pack says `illustrative: true`, whether or not `--illustrative` is given. `--pack NAME` names a pack by its id. When that is the id of a pack that ships with the plugin (`packs/NAME.json`, such as `demo`), the file is read exactly as `--pack-file` reads it, so a run on a shipped invented pack is always illustrative and a shipped pack with a problem starts no run. Any other name (also one in another case, with a path or with `.json`, and one the look-up of the file cannot ask about, such as a name too long for a file name) is recorded as written and checks nothing, so with it the run is illustrative only when `--illustrative` is given. Exactly one of the two is required; both together are a usage error. A `--run-id` may only use letters, digits, `.`, `_` and `-`, so the run folder always stays inside `--root`. A run folder that already exists, and a folder that cannot be written to, are refused with one plain sentence that names the folder (exit code 2); nothing is changed or made. So is a question, pack name, home company or reply that holds characters that cannot be saved (an argument whose bytes were not UTF-8): it is checked before anything is made. The same goes for `demo`.

```
bin/radar init-run --root runs --question "Who adds filling capacity?" --pack-file packs/demo.json --home-company "Example Pharma"
```

**add-copy** saves a file you saved or exported yourself (`.txt`, `.html`, `.pdf` with text, `.csv`). A `--url` that is a web address (`http` or `https`) is refused for every character a downloaded address may not hold (a space, a separator, a control or format character, such as a zero-width character); a label in free words, such as `internal://memo`, a file name or a short description, is refused only for a control or format character, which a reader cannot see (exit code 2, nothing saved). `--data-class` is required and has no default: say for every file whether it is `public`, `licensed` or `internal`, so a file of your own (an export from a paid database, say) never lands in a run as public because nobody said what it is. Use `--based-on S1` when the source repeats another one, such as a news article written from a press release. Every id given there must be a saved source of the run, written as `S` and digits; anything else (`s1`, a web address, a source that does not exist) is refused with exit code 2 before anything is saved, in the words `add-based-on` uses. The same goes for `save-source`, before anything is downloaded. Like `save-source`, `add-copy` first checks that `--run` is the folder of a run; a folder that is not one is a usage error (exit code 2), and nothing is made in it. A text file or page is read in the character set it names: for a download, the one the server's header names, else the page's own `<meta>` declaration (`<meta charset=...>` or the `http-equiv` form, looked for in the first 2048 bytes only); only plain text encodings are honoured (UTF-8, ASCII, the ISO-8859 and Windows code pages, KOI8, and the Japanese, Korean and Chinese ones such as Shift_JIS, EUC-JP, GBK and Big5), under any of their usual spellings; any other name, such as UTF-7, UTF-16, UTF-32, EBCDIC or an escape encoding, is read as if nothing had been declared, because it could show the quote check other words than a reader of the page sees; the same goes for a `<meta>` inside an HTML comment or inside a quoted attribute value of another tag (`<p title='<meta charset=...>'>`). The tags are read as a browser's first look at a page reads them: a comment is skipped whole, so it never joins the text around it into a tag (`<me<!-- -->ta charset=...>` is no declaration), and every other tag is read to its end. Without a usable name the text is read as UTF-8 and, if that fails, as Windows-1252 (which also stands for a declared Latin-1).

```
bin/radar add-copy --run RUN --file release.txt --url https://www.example.com/news/1 --data-class public --publisher "Competitor A" --title "Competitor A adds two lines" --date 2026-05-14 --type company_release --speaker "its press office" --interest "wants to look strong" --language en
```

**save-source** downloads a public page or text PDF and saves it. First of all it checks that `--run` is the folder of a run; a folder that is not one is a usage error (exit code 2), and nothing is made in it or requested. It follows a redirect itself, one step at a time and at most five times, and for the address you give and for every address it is sent on to it checks, in this order, that the address is written in the plain form (no space, separator, control or format character anywhere, such as a no-break space, a zero-width character or a direction mark, and a space inside an address is written as `%20`; a letter outside ASCII in the path or query of the address you give is percent-encoded as UTF-8 before it is checked and requested, as a browser sends it, and the record's `url` holds that encoded form; a site name in square brackets must be an IPv6 address; a site name may hold only the plain letters a to z, digits, hyphens and dots, and a name with other letters must be given in its `xn--` form, so a name that a program could read in two ways is refused; a port, if given, is a number from 1 to 65535; a space or non-ASCII letter in the path of a redirect is encoded, as before), that the name points to the public internet (an address inside a home or company network is refused, and so is an IPv6 address of the 6to4 or Teredo kind whatever address it carries; an IPv6 address that carries an IPv4 address, by mapping (`::ffff:`) or under the NAT64 prefix `64:ff9b::/96` (its last 32 bits), is judged by that IPv4 address by the same rules, so a site reached through a network that translates IPv4 for IPv6 is saved like any other; the page is saved as "not accessible"; a name that does not resolve is saved as "not accessible" because the site could not be reached), that the site's robots.txt allows the page (read once for each site), and that at least two seconds have passed since the last download from that site (kept per site name, whatever the port). It sends no personal details. The site's robots.txt is asked for before the two-second wait, so that request is not spaced out from an earlier download from the site; and the computer's look-up of a site name has no time limit of its own (only the download itself has its 30 seconds). A page it cannot read is saved as "not accessible", with the reason. The record keeps the address you asked for in `url`. If the copy came from another address because a site passed the request on, `final_url` holds that address and the report shows both (the same page under another spelling of its address, such as a different letter case of the site name, a trailing dot or the default port, does not count as another address); otherwise `final_url` is empty (`null`), as it is for a copy added with `add-copy` and for a source that could not be saved. A source record written before `final_url` existed has no such key, and the data check reads that as empty; a `final_url` that the download's own address check would refuse (a user name, a bad site name, a space or a control character, anything that is not an http or https address) is a problem. A website name that gives a different answer when the address is checked and when the page is downloaded is not guarded against, and when the computer is set to use a proxy the request goes to the proxy, which looks the name up itself, so the check on this computer does not cover what the proxy can reach. It takes the description options of `add-copy` (`--publisher`, `--title`, `--date`, `--type`, `--speaker`, `--interest`, `--language`, `--based-on`), but not `--file`, `--data-class`, `--supplied-by` or `--basis`. It prints the whole source record and ends with exit code 0 also for a page it could not read, so read `access` and `access_reason` (see the reference at the end).

```
bin/radar save-source --run RUN --url https://www.example.com/news/1 --publisher "Competitor A" --title "Competitor A adds two lines" --date 2026-05-14 --type company_release --speaker "its press office" --interest "wants to look strong" --language en
```

**Text a page hides from its readers** is left out of the saved copy's text, so a quote is never found in words a reader of the page never sees: the copy follows what a browser without scripts shows, with two named exceptions. Left out, as in such a browser, is the content of `<script>`, `<style>`, `<template>`, `<iframe>`, `<noembed>` and `<noframes>`, of a `<dialog>` without `open`, and of any element with the `hidden` attribute or an inline `style` with `display:none` or `visibility:hidden` (in any case, with any spaces); `aria-hidden="true"` is not among them, because a browser shows such text to a sighted reader (it only keeps it from a screen reader), so a quote from it is found; a hidden `<html>` or `<body>` leaves out the whole page, and an element that holds nothing (`<br hidden>`, `<img hidden>`) hides nothing after it. The two exceptions are `<noscript>` and `<svg>`: a browser without scripts shows their text, and the copy leaves it out all the same, because the rule errs toward leaving text out. A hidden element ends where a browser ends it: at its end tag, where an end tag the standard lets authors leave out is implied (a `<p>` at the next block such as `<div>`, `<ul>`, `<h2>` or `<p>`, an `<li>` at the next `<li>` or the list's end, a `<td>` at the next cell or row), or else at the end of its parent, and at the end of the page when no parent ends it. Text hidden by a stylesheet or by a script, and markup that Python's own reading of HTML takes differently from a browser (such as `<!-->`, which a browser reads as an empty comment), are not detected; where the rules are not sure, they leave text out rather than keep it.

**add-fact** adds one proposed fact from a JSON file. It starts as "proposed". The file holds the statement, one quote from the source (5 to 50 words), the source id and, for a capacity move, the details of the move. A proposal that breaks a rule is refused before anything is written (exit code 2, with the reason): a required part is missing or empty, a value is not one of the allowed ones, the quote is shorter than 5 or longer than 50 words, or the source does not exist. A key the program does not know is refused and named (`the key early_singal is not known`): at the top of the proposal, inside a supporting entry and inside the details of a capacity move. A supporting entry holds `source_id`, `quote` (the same rule as the main quote: text of 5 to 50 words; a number or a list is `must be text`) and, if wanted, `quote_translation` (text), nothing else. It may come from the fact's own source, to state a detail the main quote does not hold; such an entry never counts as a second source. Only an entry from another source that is independent of the fact's own (see below) can confirm a fact whose main source is not a primary source. A supporting quote's translation is shown in the report wherever that quote is shown (on the fact's card and on its source's page) and in the facts table, and it is part of what a verdict covers once it is set. A key that the program sets itself (`id`, `checks`, `status`, `status_reason`, `withdrawn`) is refused by name (`the key status is set by the program, not by a proposal`), so a value there is never dropped without a word. The data check and the gate name a stored fact that breaks these rules. A stored quote that is not text (written by hand) counts as not found in `check-quotes`, `settle`, `quote-context` and the gate, by one rule (a missing or empty quote is too short); it never stops a command. The same goes for other hand damage of this kind: a supporting entry that is not an object, `supporting` written as an object, and a source id that is not text (its quote has no saved copy to be found in).

Write sizes as plain numbers in text, such as `"1200"` or `"2.5"`; a size written as a bare JSON number is refused (`write the size as text, such as "2.5"`), because `calc` reads the size exactly as written. A size with a thousands separator, such as `1.200` or `1,200`, is refused: the engine cannot tell whether `1.200` means one thousand two hundred or one point two, so it never reads it as a number.

```
bin/radar add-fact --run RUN --file proposal.json
```

**check-quotes** looks for every quote in its saved copy and stores the result.

```
bin/radar check-quotes --run RUN
```

**quote-context** gives the checker what it needs to judge a quote: for each fact, its quotes and, for each quote, the sentence or sentences of the saved copy that hold it, with the sentences next to it. A quote can be found word for word and still mislead, for example when it is cut just after "not"; the sentence around it shows that. The passage is the saved copy's own text, line breaks included. Give one fact with `--fact`, or `--open` for every fact whose quotes are all found now and whose support check is missing or out of date. `--sentences` (0 to 3, default 1) sets how many sentences are shown on each side; each side is cut to the 80 words nearest the passage, and a cut is marked with `…`. A quote that is not found, or that no run of up to 12 sentences holds, has no passage. The command only reads: it changes nothing in the run, and the text of a source is returned as data, never acted on. Exactly one of `--fact` and `--open` is required.

```
bin/radar quote-context --run RUN --fact F3
bin/radar quote-context --run RUN --open --sentences 2
```

**record-support** records the verdict of an independent check: does the quote really support the fact? Record it after the fact is final. If the fact changes later, including the translation or the language of its quote or the translation of a supporting quote, the verdict no longer counts. A fact whose quote is not found needs no verdict: it is rejected without one. A verdict must say who gave it (an empty `--by`, or one of spaces only, is refused), and a verdict that the quote does not support the fact must carry a note, because the report shows a rejected fact with the checker's reason; a pass may have an empty note. Both refusals end with exit code 2, and nothing is stored.

```
bin/radar record-support --run RUN --fact F3 --passed true --by "support checker" --note "The quote gives the same year as the fact."
```

`--note-stdin` takes the note as plain text from standard input instead, so it never stands on the command line. This is how the plugin's support checker records its verdict, with a here-document whose end mark is quoted, so the shell changes nothing in the text:

```
bin/radar record-support --run RUN --fact F3 --passed false --by support-checker --note-stdin <<'RADAR_NOTE'
The sentence around the quote says the opposite of the fact.
RADAR_NOTE
```

**settle** gives every fact its status (see the table below). It checks the quotes again first.

```
bin/radar settle --run RUN
```

**withdraw-fact** withdraws a fact you no longer want to rely on, for example a duplicate or a proposal with a quote that cannot be checked. You must give a reason. Nothing is deleted: after the next `settle` the fact is rejected as withdrawn, and the report lists it under "What we could not confirm" with your reason. An analysis that still uses the fact is refused.

```
bin/radar withdraw-fact --run RUN --fact F3 --reason "Duplicate of F2."
```

**checkpoint** records a decision a person took. The two names are `lenses` (which thinking lenses to use) and `final_report` (build the report). `--answered-by` is `person`, `test` or `unattended`, and the report shows which.

```
bin/radar checkpoint --run RUN --name lenses --answered-by person --answer "Use firm-boundaries and capacity-commitment."
```

**log-search** and **log-excluded** write the search log and the list of what was left out. Both show up under "How this report was made".

```
bin/radar log-search --run RUN --place "Company websites" --result "Found two releases"
bin/radar log-excluded --run RUN --what "A paid market forecast" --why "Behind a paywall"
```

`log-excluded` also takes `--source S4`. Use it for a saved source that was read in full and gave nothing usable, so that no fact names it. The entry then holds the source's number, and `status` counts that source as read. A source number that is not saved in the run is refused (exit code 2).

```
bin/radar log-excluded --run RUN --what "Source S4" --why "Read in full; nothing on this question." --source S4
```

**add-facts** adds every proposal of a JSON list in one go: `--file` names a file that holds a list (`-` reads standard input). Each proposal is checked as `add-fact` checks it. The good ones are written; a bad one is skipped and named. The command prints `{"added": [{"index": 0, "fact_id": "F3"}], "refused": [{"index": 1, "reasons": ["quote: quote must have 5 to 50 words"]}]}`, where `index` is the place in the list. The exit code is 0 when nothing was refused, 1 when something was, and 2 when the file is not a JSON list.

```
bin/radar add-facts --run RUN --file proposals.json
```

**add-based-on** records that a saved source repeats or draws on another one, for example when it turns out later that an article was written from a press release. It only ever adds a link; nothing is removed. A source that does not exist, a source based on itself and a link that would form a loop are refused (exit code 2). It prints `{"ok": true, "based_on": ["S1"]}`. Settle the facts again afterwards: a fact that was confirmed by two sources that are now linked is uncertain again.

```
bin/radar add-based-on --run RUN --source S6 --on S1
```

**--from-json** is accepted by every command. It takes the options from a JSON file instead of the command line, so that text from outside (a page title, a quote, a person's answer) never has to be written onto a command line, where quotation marks, `$(...)` or a backtick could break the command. `-` reads standard input. The file holds one JSON object; each key is an option name without the dashes (`based-on`, or `based_on`).

- A text becomes the option's value, a number becomes the text it was written with (`2.50` stays `2.50`; `NaN` and `Infinity` are refused), and `true` switches a flag on. `false` and `null` leave the key out, so a `false` never switches anything on. An option whose allowed values are the texts `true` and `false` (`--passed` of `record-support`) also takes the JSON values `true` and `false`, which are passed on as those texts.
- Each value is handed to the command's own parser as one argument, `--key=value`, so a value that starts with `-` is read as text, never as an option.
- `based-on` may be a list of source ids. No other option takes a list or an object.
- Refused with exit code 2: a key that is not an option of the command, the same option given twice (in the file and on the line, or under both spellings; a key counts as given whatever its value, so `false` and `null` cannot hide an option on the line), a file that is not one JSON object, a key that appears twice in the file, text that cannot be saved as UTF-8, and `--from-json -` together with `--file -` or with `--note-stdin`. Option names are never abbreviated: `--from` or `--ack` is a usage error.

The body of the example must be JSON written by a program, never typed by hand around outside text.

```
bin/radar log-search --run RUN --from-json - <<'RADAR_JSON'
{"place": "Company websites", "result": "Found two releases"}
RADAR_JSON
```

**check-data** checks every file of the run for missing or wrong fields and names each problem with its file. Like `gate`, it prints `problems` and, for each, its plain explanation in `explained`. A source, a fact, the analysis or a saved copy that is there but that this user may not open is named as such (`may not be opened by this user`), not as damaged or missing, as `run.json` is (`run.json may not be opened`).

```
bin/radar check-data --run RUN --lenses LENSES
```

**gate** runs every check again and says whether a report may be built.

```
bin/radar gate --run RUN --lenses LENSES
```

**build-report** runs the gate, and only if it is open it writes the report. This is the only way a report is made.

```
bin/radar build-report --run RUN --lenses LENSES
```

**status** says where a run stands and what comes next. With `--root` it lists all runs in a folder, newest first, and says of each whether it is illustrative (`illustrative`) and whether it is the invented practice run (`practice`): the demo's private variant, the run `radar demo --variant private` builds. The practice tour's own runs are illustrative but not marked `practice`.

```
bin/radar status --run RUN --lenses LENSES
bin/radar status --root runs
```

**calc** computes a total, a count or a share from facts of the run. A total or share in an analysis is never written by hand: ask for it here and copy `result` as printed. `--operation` is `sum`, `count` or `share`. `sum` and `share` need `--unit`, and every fact must state its size in that unit; nothing is converted. `--facts` lists the facts to use. For `share`, `--of` lists the whole they are a part of (the shared facts must be in it). Only capacity moves that are confirmed or uncertain count. The answer says whether an uncertain fact is among them. A fact whose stored status no longer follows from its checks (it was withdrawn, given a new verdict, or a source link changed, and `settle` has not run since) is refused with `input F1 has changed since the facts were settled, so settle the facts first`: settle, then calculate again. When something is wrong, `result` is `null`, each problem comes with its explanation and the exit code is 1. The command only reads: it changes nothing in the run. A folder that is not a run, an empty `--facts` or an unknown operation is a usage error (exit code 2). The gate uses the same arithmetic, so a figure from `calc` is the figure the gate expects.

```
bin/radar calc --run RUN --operation sum --unit lines --facts F1,F2,F3,F6
bin/radar calc --run RUN --operation share --unit lines --facts F4 --of F1,F2,F3,F4,F6
```

Prints `{"result": "6", "includes_uncertain": false, "problems": [], "explained": []}`.

**compare** compares an earlier run with the current one and writes `changes.json` into the current run, with a `file_digest` over the whole file. The next `build-report` then adds a "What changed since last time" tab.

```
bin/radar compare --previous runs/20261001-090000 --current RUN
```

The comparison belongs to the facts as they were when it was made. If facts are added, settled again or withdrawn afterwards, the gate refuses until you run `compare` again. The gate also refuses a `changes.json` that was edited by hand or damaged after the program wrote it (its `file_digest` does not match; a comparison written by an earlier version has none), and the remedy is the same. The digest catches a slip, not someone who recomputes it. A comparison with an earlier run that holds non-public material (a private run, or a run with a source that is not public) makes the report confidential, and a publishable build refuses it.

`compare` refuses, before it writes anything, to join runs that do not belong together (exit code 2, with `error` and `explained`): an earlier run that holds non-public material with a public run (a private run may still be compared with a private or a public earlier run); an illustrative run with one that is not, in either direction; and an earlier run that is not the practice run with the practice run that `radar demo --variant private` builds. All three rules are enforced by `compare`. `changes.json` records `previous_confidential` and `previous_illustrative` (whether the earlier run was illustrative), both covered by `file_digest`, and the gate re-derives from them, so a comparison copied over by hand is caught too: it refuses a public run whose comparison says its earlier run held non-public material, a comparison whose earlier run is illustrative when this run is not (or the other way round), a comparison whose `current_run` is not this run's own id, and a comparison without `previous_illustrative` (made by an earlier version; run `compare` again). The practice-run rule is not recorded in the file and is enforced by `compare` only. `compare` also does not take the earlier run's stored statuses on trust: when a fact there holds a status its checks no longer give it (it was withdrawn, given a new verdict or a new source link, and `settle` has not run since), it refuses in the same way with `the earlier run has facts whose status no longer follows from their checks, so settle the earlier run first`, as `calc` refuses such a fact; settle the earlier run, then compare again.

**check-pack** checks a company pack and works out the time window to search. A pack is a small settings file (`packs/demo.json` is the illustrative one) that says who the company is, which strategic question it cares about, which other companies to watch, where to look, and the words and units of its industry. It holds pointers, not facts: a company named in it is only a candidate until a source confirms what it does. `--today` (YYYY-MM-DD) is the last day of the window and defaults to today. The command prints `problems` (each with `file`, `field` and `message`), `explained` (one plain explanation for each, worded for a pack), `pack` (its `id`, `company` and `illustrative`) and `window`. `pack` and `window` are `null` when the file cannot be read, and `window` is also `null` when the pack's time window is refused. Exit code 1 means the pack has problems. A file that does not exist, or a folder, is a usage error (exit code 2). The command only reads the pack and never raises on one that was edited by hand: an empty file, a file that is not valid, a file nested too deeply, a value of the wrong kind, a missing setting and a setting the program does not know each give a named problem.

```
bin/radar check-pack --file packs/demo.json --today 2026-11-12
```

Prints `{"problems": [], "explained": [], "pack": {"id": "demo", "company": "Example Pharma", "illustrative": true}, "window": {"months": 36, "from": "2023-11-12", "until": "2026-11-12"}}`. The window starts on the same day of the month `time_window_months` months earlier, or on the last day of that month when it has no such day (one month before 31 March is 28 February). `time_window_months` is optional: a pack without it uses 36, and a value that is not a whole number from 1 to 120 is refused.

The pack format is one JSON object, and the file name is the `id` plus `.json`. Every setting below is required unless marked optional; an unknown setting is a problem.

| Setting | Rule |
|---|---|
| `id` | lower-case letters, digits and `-`, not starting or ending with `-`; the same as the file name without `.json` |
| `company`, `industry` | text, not empty |
| `illustrative` | `true` or `false` |
| `strategic_questions` | a list with at least one entry. Each has `text` and a `framing`: `user` needs `framed_by` (who framed it); `company` (taken from the company's own statements) needs `evidence`, a list of at least one `{"url", "quote"}` with a web address and a quote of 5 to 50 words, so that the question points to where it will be verified. On a `user` question, `evidence` is optional, but if it is there every `url` in it is checked in the same way |
| `competitors`, `watch` | lists, empty allowed, of `{"name", "status", "suggested_by"}`. `status` must be `candidate`. `suggested_by` is `user` or `search`; `search` also needs `found_at`, the web address where the name was found |
| `places` | a list with at least one `{"kind", "name", "url"}`. `url` is a web address. `kind` is one of `investor_relations`, `press_room`, `filings`, `annual_reports`, `regulator`, `trade_press`, `permits`, `job_postings` |
| `vocabulary` | optional list of `{"term", "meaning"}` |
| `units`, `demand_drivers` | lists of text, empty allowed |
| `languages` | a list of text with at least one entry |
| `time_window_months` | optional whole number from 1 to 120; 36 when missing |

Every web address in a pack (`url` of a place, `url` of a piece of evidence whatever the question's framing, `found_at`) is checked by the same form check `save-source` uses for the address it is given, because a pack is a file that is edited by hand and committed, and a pack must never point to an address the download would refuse: it starts with `http` or `https`, holds no user name or password, no space and no separator, control or format character, has a plain site name (the letters a to z, digits, hyphens and dots, or an IPv6 address in square brackets) and, if it has a port, a number from 1 to 65535. Each problem has a fixed message with its own explanation, such as "a pack lists candidates only", so a person who writes a pack reads wording made for packs. The explanation of a problem about a setting names that setting, and the explanation of a value that is not allowed names the allowed choices.

A pack's demand drivers, vocabulary meanings, industry text and place names are the analyst's own hypotheses and search hints. They are never facts and never appear in a report as facts.

**demo** builds the invented demo run in a folder you name, all of it or up to a stage, and prints where the run, the demo lenses and the demo source texts are. See "The planted-error demo" below.

```
bin/radar demo --root .radar-demo
```

**doctor** checks that Python and the PDF library are installed, and says which Python is running. It prints the Python version and its path (`python_path`), whether `pypdf` is there, and `environment`: `private` when that Python is the one in the folder `radar setup` made, `other` when it is not. When `pypdf` is missing the hint is `Run: radar setup`. It also says whether the plugin's guard can run on this computer: it starts `hooks/guard.sh` as the hook does (with `sh`, the computer's own settings, the event on standard input) and hands it a made-up write to the record of a made-up run in a temporary folder. `guard` is `ok` when the guard refuses that write, and `not_running` when it lets it through or cannot be started; then `guard_hint` says in plain words what that means and what to do. This tells whether the guard can run here, not whether Claude Code has loaded the hook: a plugin that is installed but switched off, or a session started without it, is not seen. The guard does not change the exit code. Apart from the temporary folder, which it removes, it only looks; it never creates anything. `bin/radar --version` prints the version.

```
bin/radar doctor
```

**setup** makes a private Python environment with the PDF library in it, so that nothing is installed into the Python of the system. It makes the folder `venv` inside the home folder (`--home DIR`, else `$RADAR_HOME`, else `~/.strategy-radar`) and installs `pypdf` there. It needs a network connection, because it downloads the PDF library (`pypdf`). `--home` is made into a full path before it is used or printed, and a home that exists but is a file is refused with one plain sentence (exit code 2) before anything runs. `--dry-run` prints the two commands it would run and changes nothing. Running it again on a home folder that already has an environment runs the same two commands once more and reports the same result; that repairs or updates the environment. If a command fails, setup stops, prints one line with `error` that says what could not be done and the last line the command printed (exit code 2), and does not run the second command after a failed first one. A Python without the `venv` module ends in that message, not in a traceback.

```
bin/radar setup --dry-run
bin/radar setup
```

### Starting the engine on your computer

`bin/radar` is a small shell script, so it runs on macOS and Linux. It does not run on Windows. The engine needs Python 3.10 or newer, and the `python3` that comes with a Mac is often older. The script therefore looks for a suitable Python in three places, in this order, and uses the first one that is version 3.10 or newer:

1. the program named in `$RADAR_PYTHON`, when that variable is set;
2. the private environment made by `radar setup`: `venv/bin/python` inside `$RADAR_HOME`, or inside `~/.strategy-radar` when `$RADAR_HOME` is not set;
3. `python3`, as found on the `PATH`.

If none of them is new enough, the script prints one line of JSON with an `error` and a `hint` that says to install Python from python.org and then run `radar setup`, and exits with code 2. The script starts the engine as a file (`engine/start_radar.py`), not as `python -m radar`, so the folder you run the command from is never searched: a file or a folder called `radar` in your project cannot take the engine's place. A `PYTHONPATH` you have set is left as it is. The question whether a candidate is new enough is asked in Python's isolated mode (`-I`) with nothing on standard input, in this script and in the guard's launcher alike, so a setting of yours such as `PYTHONINSPECT` or a broken `PYTHONPATH` cannot make a working Python look missing; the engine itself then runs with your settings, as before. The script finds the engine from the place it was started from, so start it by its own path (or put its folder on the `PATH`); a link to it in another folder does not find the engine.

The third place, `python3` on the `PATH`, is the weakest. The Python that ships with macOS is older than 3.10, and on a Mac without Apple's developer tools `/usr/bin/python3` is only a stand-in that offers to install them when it is started. So the script, and the guard's launcher `hooks/guard.sh` in the same way, passes over a candidate that is found at `/usr/bin/python3` on a Mac (a computer with `/System/Library/CoreServices/SystemVersion.plist`) unless the developer tools are there (`/Library/Developer/CommandLineTools/usr/bin/python3` or `/Applications/Xcode.app` exists); every other candidate is tried as before, and on any other computer `/usr/bin/python3` is tried as before too. The decision is one small shell function, `may_try`, written the same in both scripts; the tests run it with made-up files in the place of the three it looks at. It was not tried on a Mac without the developer tools: the Mac it was built on has them. On a Mac whose Xcode is installed under another name, the stock Python is not used; install Python 3.10 or newer from python.org and run `radar setup`, or name a Python you have with `RADAR_PYTHON`. A `python3` found somewhere else that is only a link to `/usr/bin/python3` is not recognised (the script uses shell built-ins only and does not follow links). Installing Python 3.10 or newer from python.org and running `radar setup` avoids relying on the stock Python at all.

The practice tour (`radar demo`) uses text files only and works without `pypdf`. Reading a PDF file needs it, so run `radar setup` once before you save a PDF. Without it, `add-copy` of a `.pdf` file and `save-source` of a page that turns out to be a PDF end with exit code 2 and one line, `{"error": "The PDF add-on is not installed, so a PDF cannot be read and nothing was saved. Run: radar setup, then try again."}`; nothing is saved, not even a source record marked "not accessible", because the page is not at fault.

## How a fact gets its status

Every proposed fact ends as confirmed, uncertain or rejected. Nothing is deleted. A rejected fact stays in the run and is shown in the report under "What we could not confirm".

| Status | When | Reason shown |
|---|---|---|
| rejected | The quote is not in the saved copy, or it is too short or too long, or there is no saved copy. This is decided before the support check: a quote that is not found is rejected without one. | `not_found`, `quote_too_short`, `quote_too_long`, `no_saved_copy` |
| rejected | A supporting quote is not in its source's saved copy, or that source has no saved copy. Also decided before the support check. | `supporting_quote_not_found` |
| proposed | The quote check has not been done yet, or the quotes are found but the support check has not been done yet, or the fact (its translation included) was changed after the support check. | `checks_incomplete` or `support_check_outdated` |
| rejected | The quote is there, but the support check says it does not back the fact. | `not_supported` |
| rejected | The fact was withdrawn with `withdraw-fact`. This rule comes before all others. | `withdrawn` |
| uncertain | The fact is marked tentative, for example one unnamed source. | the reason given |
| uncertain | The fact is an early signal (see below) and is not marked tentative. This can only come from a record changed by hand, and the data check names it. A fact whose main source is a permit, a job posting or a regulator record counts as an early signal here even without the mark. | `an early signal, not an announcement` |
| uncertain | The only source is not a primary source and no independent source confirms it. | `single source that is not a primary source` |
| confirmed | The quote is found, the support check passed, and the source is a primary source (the party's own statement), or a supporting entry from an independent second source backs it with a quote of its own, found word for word in that source's copy. | none |

A second source is independent only when it has a different publisher, neither source is based on the other, and the two are not one source saved twice: their saved copies differ (also once the white space in both texts is evened out, so a trailing line break does not make two copies of one text), and they were saved from different sites. The site of a source is the site name of its address (`final_url` when it has one, else `url`) in lower case, without a trailing dot and without one leading `www.`, and a name with letters outside ASCII in its encoded `xn--` form. An `xn--` label is first read back into its letters and then encoded with the rest of the name, so the two spellings of one name are one site whichever way it is written, also for the few letters, such as the sharp s, that Python's encoder writes otherwise than a browser does (both spellings then give the same, Python's, form); a name that cannot be read back or encoded is compared as written; the scheme, the port and the rest of the address do not count, so `http` and `https`, a tracking parameter or a trailing slash never make a second source. An address typed without `https://` (as `add-copy --url` allows) is read as a site only when it starts with a proper site name, followed by nothing or by `/` and a path: at least two labels separated by dots, each label made of letters, digits and inner hyphens (not empty, no hyphen at either end), and the last label letters only and not a file ending (`pdf`, `htm`, `html`, `txt`, `csv`, `json`, `xml`, `md`, `doc`, `docx`, `xls`, `xlsx`, `ppt`, `pptx`, `zip`, `png`, `jpg`, `jpeg`, `gif`). So `www.site-a.example/x` names the same site as `https://site-a.example/y`, while `annual-report-2025.pdf`, `memo.txt`, `www.` or `a..b` name no site. A source without a web address, such as one added by hand at an `internal://` address, under a file name or described in free words, is compared by its copy only. The accepted cost: two different publishers on one shared platform (one site) count as one source. A news article written from a press release does not confirm the press release. A permit, a job posting or a regulator record is never the second source that confirms a fact, however independent its publisher: its quote is still checked, but a fact backed only by such sources stays uncertain.

The reports never show these reason codes. They show the same reasons in plain words, such as "The quote was not found in the saved source." For a fact the checker turned down they also show the checker's note, and for a withdrawn fact the reason you gave.

## Early signals and competitor baselines

An **early signal** is a hint that a move may be coming, found before any announcement: a building permit or planning record, a job posting, a regulator record. Save such a source with `--type permit`, `--type job_posting` or `--type regulator_record`. A fact built on it carries `"early_signal": true` (it is `false` when the key is left out). The rules:

- A fact whose main source is one of these three types is an early signal, marked or not, and must carry the mark. A proposal without it is refused (`add-fact`, `add-facts`), and the data check names a stored fact without it. To correct one, add the fact again as an early signal and withdraw the old one; a stored fact is not edited.
- It must be tentative, with a reason that names the kind of hint, and it must be a general fact, not a capacity move. A proposal that breaks either rule is refused, and the data check names a stored fact that does.
- It can never be confirmed. However many sources back it, it is at best uncertain (a failed check still rejects it). `settle` does this even for a record that lacks the mark, and the gate refuses a record whose status was raised by hand.
- It is never an input to a total or share: `calc` and the gate refuse it like any fact that is not a settled capacity move.
- Changing the mark after the support check makes that check outdated, like any other change to the fact. A fact that is not an early signal keeps exactly the fingerprint it had before the mark existed.

An early signal stays in the one list of facts, so every link to it, its source page and the facts table find it as they find any fact. Only the listing "What the sources say" sets it apart: it appears in its own block "Early signals", opened by a fixed sentence that says these are hints, not announcements. The reference to it carries the uncertain mark, and the class mark when its source is not public. The facts table has a column `early_signal` (`yes` or empty).

A **baseline** tells the reader how big the company behind a move is. `analysis.json` may hold a list `baselines`, each item `{"company": ..., "fact_ids": [...]}`: the company and the facts that describe its size, sites or investment (at least one). A baseline has no wording of its own, and the data check refuses one that has a `text`. The report shows, under the company in "Competitors" and headed "Baseline: size, sites and investment", each of those facts' own checked statement with its fact reference. So a baseline figure is never a bare claim: it is the statement of an ordinary fact with a quote and checks, usually from the company's annual report. The gate refuses a baseline that rests on a fact that is rejected or does not exist, and an uncertain or non-public fact keeps its mark. A baseline never rests on an early signal (marked as one, or taken from a permit, a job posting or a regulator record): the data check and the gate refuse it (`a baseline may not rest on F3, an early signal`). A company that has a baseline but no move still gets its own entry.

## When the gate refuses

The gate refuses to build a report when any of these is true. `build-report` then prints each problem and an explanation of what it means.

- A record is broken, empty, or missing a required field, or a part of the analysis has the wrong form (for example one text where a list of entries belongs). An audit flag is exactly a `check` and a `text`: another key (`the key severity is not known in a flag`) or an empty text is refused. A flag may name any fact of the run, whatever its status ("M1 leans on F9"), but only one that exists (`a flag names fact F99, which does not exist`), so a flag the writer may not change never closes the gate at the build for a status, and a flag that names no fact of the run is reported by the data check while the audit can still be asked again.
- A fact or source file that the run created has been deleted.
- A saved copy was changed after it was saved. Its fingerprint no longer matches.
- `analysis.json` is missing, or one of the two checkpoints has not been recorded.
- A confirmed or uncertain fact no longer passes: its quote or a supporting quote is not found now, or its support check did not pass.
- The status or the reason of any settled fact, rejected ones included, does not follow from its checks, for example because it was changed by hand. An early signal that has been made firm or confirmed by hand is refused here.
- A fact was never settled.
- The analysis rests on a fact that is rejected, missing or never settled.
- A text of the analysis names a fact by its id ("as F9 shows": `F` and digits standing on their own, in any text, also inside a list of texts) that does not exist or does not count: rejected, withdrawn (also before it is settled again) or never settled (`a text names fact F9 with status rejected`, or `missing`, `withdrawn`, `proposed`). The lists of fact ids are judged by the rule above. A flag of the bias audit is not the analysis's own text and is left out here: the data check judges it (see above). Only the gate reports this rule; `check-data` does not.
- A key message has a step of the kind `fact` that names no fact (`a fact step must name at least one fact`), or a step after its conclusion (`the last step of a chain must be its conclusion`); a chain must also have at least one fact step and exactly one conclusion. The data check names the same.
- A total or share does not match what the engine computes from its inputs, or its inputs are in different units, or a size is written with a thousands separator.
- A prediction has no date or a probability outside 1 to 99, or there is exactly one scenario or more than four (none is fine).
- The comparison with an earlier run is out of date, or not readable, or it is a public run's comparison with an earlier run that held non-public material, or it was made for another run or with an earlier run of the other kind (illustrative or not), or by an earlier version of the program.
- With `--publishable`: a run whose mode is not public (every private run, also one whose sources are all public: `a publishable report may not be built from a private run`), any source that is not public, or a comparison with an earlier run that held non-public material.

## Public and private mode

By default a run is public. Only public sources can enter it.

Private mode is for a run that also uses documents you hold, such as an internal paper or licensed data. You switch it on when you start the run, and you must agree to a notice first:

> Private mode sends the content of your documents to the language model through your own Claude account. Check that your organisation and your data licences allow this.

Without `--acknowledge-data-flow` the run is not made. The command prints `error` (with the sentence about the option) and `notice`, which holds the two sentences above and no option name; a plugin shows the person `notice`.

With the acknowledgement goes the person's own reply to the notice, word for word, in `--acknowledged-words` (through `--from-json`, so the reply never stands on a command line). A private run is not made without it (exit code 2), and `--acknowledged-words` without `--mode private` is wrong use. The run record keeps the reply in `private_acknowledged_words`, next to the time in `private_acknowledged_at`, and the report shows it under "How this report was made", first in the list of decisions, as "Reply to the private-mode notice". The program cannot tell who wrote the reply: it records what it is given. The data check names a private run whose record holds no reply. The demo's private variant stores a reply that says it is the invented practice run and that no person was shown the notice.

```
bin/radar init-run --root runs --question "..." --pack-file packs/demo.json --mode private --acknowledge-data-flow --acknowledged-words "Yes, go ahead."
bin/radar add-copy --run RUN --file memo.txt --url internal://memo --data-class internal --supplied-by "Planning team" --basis "Own company document" ...
```

A report that uses any non-public source is marked "Confidential" and its tables are named `facts-confidential.csv` and `sources-confidential.csv`. Adding `--publishable` to `build-report` refuses such a run, so a confidential report cannot be built as a publishable one by mistake. It refuses every private run too, also one whose sources are all public: a version to publish comes from a public run with the same question.

## The report and its tables

`build-report` writes four files into `RUN/report/`:

- `report.html`: open it in any web browser. It has a summary, a view for each part, and the full thinking and sources. A "Print or save as PDF" button prints it the way a reader would want it.
- `report.md`: the same report as plain text.
- `facts.csv` and `sources.csv`: tables you can open in a spreadsheet program. Text that could be read as a spreadsheet formula is made safe, also right after a semicolon or tab inside a cell.

The tables are meant to be passed on by themselves, so they carry the marks of the report in their names. A confidential report's tables are named `facts-confidential.csv` and `sources-confidential.csv`; an illustrative run's tables `facts-illustrative.csv` and `sources-illustrative.csv`; a run that is both gets both marks, the confidential one first: `facts-confidential-illustrative.csv` and `sources-confidential-illustrative.csv`. A build removes any table of the run under another of these names, so a report folder never holds two namings. Every row of both tables also has the column `illustrative`, right after the id: `yes` in an illustrative run, empty in any other. The illustrative banner says "Illustrative only. This report was made with an invented company pack as practice material. Nothing in it is a finding about a real company.": what is always true of an illustrative run, also of one that holds a file a person named, so it does not claim that every quote is invented. Like the confidential banner, it is printed at the top of every page when the report is printed; a run that is both shows the illustrative banner below the confidential one.

On a fact's card in `report.html`, the fact's own quote comes first, then two groups of further quotes. "More from the same source" holds the extra quotes from the fact's own source: each states a detail, and none is a second source. "Also stated by" holds the quotes from other sources; one from a source recorded as based on the fact's own source says that it repeats that source and is not a second source. Only an independent one can confirm a fact, and the status of the fact says whether one did.

Both reports say on which date they were built. Counts read in the singular for exactly one ("1 fact, all quotes checked", "1 proposed fact rejected"), and so does a size of exactly one with a unit of one word that ends in a plural s ("1 line", "1 batch"); a unit of several words, such as "million vials", is shown as the fact states it, and the facts table keeps the unit as stored. Rejected facts appear in the reports only under "What we could not confirm", with their reason; they are never counted, quoted on a source's page or used in a total. The facts table lists every fact, rejected ones included, by design: it is the complete record, with the status and reason of each fact. Next to its quote, each row holds the fact's supporting quotes in one cell, `supporting_quotes`, and the source of each in another, `supporting_sources`, in the same order, joined with a space, a vertical bar and a space (`S2 | S6`), and a third cell, `supporting_translations`, holds their translations in the same way when at least one has one (else it is empty); a quote may hold a semicolon, so the bar is the mark between them. Each entry gets the same defence against a formula start as the start of a cell. A field value is written in the facts table as the program stores it, so a date that is not stated reads `not_stated` there (the reports say it in words).

The tables are comma-separated, with every cell in double quotes, and UTF-8 with a byte-order mark. A spreadsheet program set to a language that uses the semicolon as separator (German, for example) may put each line into one column when you double-click the file. Import it instead: in Excel use Data, From Text/CSV and choose "Comma" as the delimiter; in LibreOffice Calc open the file and tick only "Comma" under separator options. Line breaks inside a cell are written as spaces.

## Seeing where a run stands, and continuing it

`bin/radar status --run RUN --lenses LENSES` lists seven steps: collect, extract, verify, checkpoint_lenses, interpret, checkpoint_final, build. Each is `done`, `in_progress`, `pending` or `blocked` (only the build step is ever blocked). The build step is done only while the report is newer than everything it was built from (the run, the analysis, the comparison, every source and fact record) and the gate would still let it be built; after you edit a fact or a saved copy, build the report again. The `next` field names the first step not yet done, and `waiting_for_person` is true when that step needs a decision from you. The `sources_to_read` field lists the saved sources that nobody has read yet, in order. A source counts as read when a fact names it (as its main source or as a supporting source, whatever the fact's status) or when `log-excluded --source` names it. The extract step is done only when every saved source has been read, so a run that was interrupted in the middle of its sources continues with the remaining ones. A run whose sources are all read but hold no fact skips the verify step ("no facts to check"). The verify step does not take a stored status on trust: when a fact's status no longer follows from its stored checks, by the rules the gate uses (for example after `withdraw-fact`, `record-support` or `add-based-on` without a `settle` afterwards), the step is in progress, its detail ends with "1 fact must be settled again" (or the number of facts), and `next` is `verify`, not a decision. To continue, do that step and ask again. `bin/radar status --root runs` lists all your runs and the next step of each.

## The planted-error demo

The demo is one invented run, built by the command `radar demo` (the code is in `engine/radar/demo/`, next to the invented source texts and two illustrative lens files). It holds ten proposed facts. Six are confirmed, one is uncertain and three are rejected on purpose:

- one quote changes a number compared with its source, so it is rejected as `not_found`;
- one quote is in its source word for word but gives a different year than the fact, so the support check fails and it is rejected as `not_supported`;
- one quote is in its source word for word but is cut just after "not". The sentence around it says Competitor A does *not* plan to offer its new lines to other drug makers, while the fact says it does. No matching rule can see this. Only a checker that reads the passage (`radar quote-context`) catches it, and it is rejected as `not_supported`.

Each invented publisher has an invented site of its own under the reserved ending `.example` (`www.competitor-a.example`, `www.aseptic-trade-journal.example` and so on; the two trade-press pieces come from two different outlets), so no two demo sources count as one site; the internal memo of the private variant keeps its `internal://` address. The illustrative pack `packs/demo.json` points to the same addresses.

The scripted demo records a support verdict only for the facts `radar quote-context --open` lists. The fact with the changed number is not on that list, because the program settles it alone.

Build it and then its report:

```
bin/radar demo --root .radar-demo
bin/radar build-report --run .radar-demo/demo --lenses engine/radar/demo/lenses
```

`radar demo` prints the run folder, the folder of the lenses and the folder of the source texts, and refuses a run folder that already exists. It builds the run in a temporary folder beside its place (a folder whose name starts with a dot) and moves it into place whole at the end, so a build that fails half-way leaves nothing behind and the private variant is never seen without its mark. `--stage` builds only part of the run: `sources` (run started, searches logged, the six sources saved), `extracted` (also the ten proposed facts, none checked), `checked` (also the quotes checked, the verdicts recorded and the facts settled, ready for the first decision) or `complete` (the default). `--variant` builds `changed` (a second version for a comparison), `private` (adds an invented internal document; see below) or `tampered` (a finished run in which a rejected fact has been slipped into the analysis, so `build-report` refuses it; only with `--stage complete`).

The private variant is invented from end to end. Its private-mode notice was not shown to anyone: the demo builder scripts it, and the run record says so with `"private_acknowledged_by": "demo"`. No command sets that mark, real runs never have it, and the data check refuses it on any run that is not a private, illustrative one. A run with the mark takes no further non-public material: `add-copy` with `--data-class internal` or `licensed` is refused with an explanation (start a new run to work with your own material), while public material is still accepted. The command prints one more key, `notice`, for this variant. The report and the gate behave as for any private run, including the confidential marking and the refusal of `--publishable`.

Open `.radar-demo/demo/report/report.html`. The three rejected facts appear under "What we could not confirm" and nowhere else.

To see the gate refuse without editing anything, build the ready-made refused run with `bin/radar demo --root .radar-demo --variant tampered` and run `build-report` on `.radar-demo/demo-tampered`. To do it by hand instead, add a rejected fact to a message. Open `.radar-demo/demo/analysis.json`, add the id of a rejected fact to the first `fact_ids` list, and build again. The command prints `"built": []` and explains that the analysis uses a fact that was rejected. You can do the same by changing the `result` of a total, or by editing a saved copy in `copies/`.

The end-to-end tests do exactly this: run `uv run pytest tests/test_end_to_end.py -q`.

## Reference: what each command takes and prints

This section names exactly what every command takes and prints. The plugin's skills and helpers copy option names, key names and exit codes from here. A test (`tests/test_docs_engine.py`) compares it with the program, in both directions: every command's options (value or switch, required, allowed values, default) with the command's own option list; the keys every block says a command prints, in their order, with what the command really prints on the invented demo run; the exit code of every case it runs, success and refusal alike (at least one refusal for every command, with its printed shape), with the codes the block's `exit:` line names; and the three proposal tables with what the program's own proposal check accepts and refuses. For the tables it tries every key in four proposals (a capacity move with an English quote that is firm, the same with a quote in another language, the same as a tentative fact, and a general fact; the keys inside `fields` in the three that hold `fields`) and checks that leaving the key out is refused exactly where the Required column says the key is required; that a value of the type the Type column names is accepted where the key is required (for a key that is never required, in the first of the four), a value of every other basic type (text, number, true or false, list, object) is refused, and null is accepted exactly where the type says "or null" and the key is not required; and that the Values column lists exactly the values the program takes. When any of these drift apart, the test fails. The prose around the blocks is not checked by a program.

### How to read a block

Each command has one block. Its first line is the command. Then come its options, one per line: an option with a word in capitals takes a value (`FOLDER`, `FILE`, `TEXT`, `ID` and so on are only names for the value); an option with values in braces, such as `{public,private}`, takes exactly one of those; an option with no value is a switch. The remark after an option starts with `required` when the command cannot run without it, and says `default X` when the program fills in `X` when the option is left out; a value the program works out when the option is left out (such as today's date) is said in other words. Then come the `prints` lines: the keys of the one JSON object the command prints, in the order it prints them. `name[a, b]` is a list whose entries each have the keys `a` and `b`; `name{a, b}` is an object with those keys (or `null` where the text says so); `name{ID: a, b}` is an object with one entry per fact or source id, each with those keys; `name{ID}` is such an object whose values are plain values. A line indented by four spaces continues the line above. `prints:` without a label is what the command prints when it ends with exit code 0; a label that starts with `exit 1` or `exit 2` is what it prints in that case; any other label names the option that changes what is printed. The `exit:` line says what each exit code means for the command, as `exit: 0 <when>; 1 <when>; 2 <when>`, and names every code the command can end with.

### What holds for every command

- Every command also takes `--from-json FILE`, which takes the options from a JSON object in a file (`-` reads standard input); see `--from-json` above for its rules. It is not repeated in the blocks.
- Every command prints exactly one JSON object on one line, in UTF-8. The only exception: `--help` prints usage text, not JSON, and exits with 0 (`bin/radar --help`, `bin/radar init-run --help`).
- Exit code 0: the command did its work. Exit code 1: it found problems, or it refused because of what it found (the block says which). Exit code 2: it was used wrongly, or it refused before doing anything.
- A command used wrongly prints `{"error": "..."}` with exit code 2 and changes nothing: an option missing, given twice or not known, a value that is not allowed, a fact or source id that does not exist, a named file (`--file`, `--pack-file`, `--from-json`) that does not exist or is a folder, a `--lenses` that is not a folder, and a folder that is not a run. Every command that takes `--run`, and `compare` for both of its runs, checks that first, before it locks or makes anything: a folder without the run's `run.json` is not a run, also for `gate` and `check-data`. The `error` then names the folder: `<folder> is not the folder of a run. Give the folder that init-run made for the run.` A folder whose `run.json` is there but cannot be read as the run's record (it is empty, not JSON, not a JSON object, not a file, or may not be opened) is not a run either, and the `error` says so: `The record of the run in <folder> cannot be read: its file run.json is damaged or cannot be opened. Nothing was changed.` There are three exceptions, because finding damage is their job: `gate` and `check-data` report such a record as a problem (`run.json`: `run.json may not be opened` when this user may not open it, otherwise `not valid JSON`, each with its explanation, exit code 1), and `status --root` leaves such a folder out of its list. Some refusals add `explained`, a list with one entry, as in the blocks below. Where a command reports something as a problem instead, its block says so.
- A command that finds problems prints `problems`, a list of `{"file", "field", "message"}` (the file relative to the run folder, the field or `null`, a fixed message), and `explained`, a list in the same order of `{"known", "what", "why", "do"}`: three plain sentences for the person, and `known`, which is `false` when no explanation was written for that message and a general one stands in.
- The words in `error`, `message`, `what`, `why`, `do`, `notice` and `detail` are for people. A program reads the keys, the exit code and the fixed values named in this section, never the wording.
- `check-quotes`, `settle`, `record-support`, `withdraw-fact`, `add-based-on`, `checkpoint`, `log-search`, `log-excluded` and `build-report` take the run's lock. When another command keeps the run busy for 60 seconds, they end with exit code 2 and `{"error": "Another command is still working on this run. Wait a moment and run this again.", "busy": true}`, having changed nothing: `busy` tells a program to run the same command again, where any other `error` means the command was used wrongly. `add-fact`, `add-facts`, `save-source` and `add-copy` also take the lock, to count a record they have just written, but they wait for it without a limit (the record is written by then), so they never end busy.
- These commands never change a run: `check-data`, `gate`, `status`, `quote-context` and `calc`; `check-pack`, `doctor`, `setup --dry-run` and `--version` read no run at all.

```reference
radar --version
prints: version
exit: 0 always
```

### Starting a run

```reference
radar init-run
  --root FOLDER                 required: the folder the run folder is made in
  --question TEXT               required: the strategic question of the run
  --pack NAME                   the pack's name; a pack that ships in packs/ is read as --pack-file reads it, any other name is recorded as written; give this or --pack-file
  --pack-file FILE              a pack file, checked first; give this or --pack
  --run-id ID                   the run folder's name; letters, digits, ".", "_" and "-"; when left out, the time, such as 20261112-101500
  --illustrative                switch: the run uses invented material, and its report says so
  --home-company TEXT           the company the analysis is for
  --mode {public,private}       default public
  --acknowledge-data-flow       switch: the person has agreed to the private-mode notice; needed with --mode private
  --acknowledged-words TEXT     the person's own reply to the notice, word for word; needed with --acknowledge-data-flow
prints: run_dir
prints (exit 1, the pack file has problems): problems[file, field, message], explained[known, what, why, do]
prints (exit 2, private mode not acknowledged): error, notice
exit: 0 the run folder is made; 1 the pack file has problems (also a file that is not valid JSON), nothing is made; 2 used wrongly (both or neither of --pack and --pack-file, a run id that is not allowed, a run folder that exists, a folder that cannot be written to, private mode without the acknowledgement, the acknowledgement without the person's reply in --acknowledged-words, --acknowledged-words without --mode private), nothing is made
```

With `--pack-file`, the run records the pack's `id` as its `pack`, and it is illustrative when the pack says `"illustrative": true`, whether or not `--illustrative` is given. Without `--acknowledge-data-flow`, a private run is not made: show the person `notice`, never `error` (which names the option).

### Saving sources

```reference
radar save-source
  --run FOLDER                  required
  --url URL                     required: the address of one public web page or text PDF
  --publisher TEXT              required
  --title TEXT                  required
  --date TEXT                   required: the date of the source, such as 2026-05-14
  --type {company_release,filing,annual_report,trade_press,academic,permit,job_posting,regulator_record,other}  required
  --speaker TEXT                required: who speaks in the source
  --interest TEXT               required: what the speaker wants
  --language TEXT               required: the language of the source, such as en or de
  --based-on IDS                the saved sources this one repeats or draws on, comma-separated, such as S1,S4
prints: id, url, final_url, publisher, title, date, type, speaker, interest, language, data_class, saved_at, saved_by,
    access, access_reason, copy_file, orig_file, copy_sha256, based_on, provenance
exit: 0 a source record is written, also when the page could not be read; 2 the address is not in the plain form, a --based-on id is not a saved source of the run, or --run is not a run (nothing is requested or saved), or the page is a PDF and the PDF add-on is not installed (nothing is saved)
```

`save-source` prints the whole source record it wrote, and it ends with exit code 0 also for a page it could not read: the caller must read `access`. `access` is `ok` (the copy is saved) or `not_accessible`; then `access_reason` says why: `private_address` (the address points inside a home or company network), `network_error` (the site could not be reached, also a name that does not resolve), `robots` (the site's robots.txt does not allow it), `timeout`, `http_404` and every other `http_` followed by the status number the site answered, `too_large`, `too_many_redirects`, `unsupported_type`, `login_required`, `no_text_layer` (a PDF without text, such as a scan), `unreadable_file`, `too_little_text`. A source that was not read has `copy_file`, `orig_file` and `copy_sha256` set to `null`, and no fact can rest on it. `id` is the new source's id (`S1`, `S2`, ...); `url` is the address given; `final_url` is the address the copy came from when a site passed the request on to another address, else `null`; `data_class` is always `public`; `saved_by` is `program`; `saved_at` is the time in UTC; `based_on` is the list of ids; `provenance` is `null`.

`save-source` has the description options `--publisher`, `--title`, `--date`, `--type`, `--speaker`, `--interest`, `--language` and `--based-on`. Only `add-copy` has `--file`, `--data-class`, `--supplied-by` and `--basis`. `save-source` saves public material only, so the practice run takes it like any other run.

```reference
radar add-copy
  --run FOLDER                  required
  --file FILE                   required: a .txt, .html, .htm, .pdf (with text) or .csv file you saved or exported
  --url TEXT                    required: the page address, or where the document lives, such as internal://planning-note
  --data-class {public,licensed,internal}  required: there is no default, so every file states what it is
  --supplied-by TEXT            who supplied a source that is not public; needed for licensed and internal
  --basis TEXT                  on what basis it may be used; needed for licensed and internal
  --publisher TEXT              required
  --title TEXT                  required
  --date TEXT                   required
  --type {company_release,filing,annual_report,trade_press,academic,permit,job_posting,regulator_record,other}  required
  --speaker TEXT                required
  --interest TEXT               required
  --language TEXT               required
  --based-on IDS                the saved sources this one repeats or draws on, comma-separated
prints: id, url, final_url, publisher, title, date, type, speaker, interest, language, data_class, saved_at, saved_by,
    access, access_reason, copy_file, orig_file, copy_sha256, based_on, provenance{supplied_by, basis}
prints (exit 2, the practice run refuses non-public material): error, explained[known, what, why, do]
exit: 0 the copy is saved; 2 refused or used wrongly (no --data-class, an HTML page that shows a reader too little text, a non-public class in a public run, a non-public class without --supplied-by and --basis, a non-public class into a private run whose .gitignore no longer keeps it out of git, a file of another kind, a PDF without text, a PDF when the PDF add-on is not installed, a --based-on id that is not a saved source, --run is not a run, or the practice run offered non-public material); nothing is saved
```

An HTML file whose visible text is shorter than 200 characters (once the text it hides is left out) is refused with an `error` that names `too_little_text`, the rule `save-source` uses, and nothing is saved, so a page that shows nothing is never counted as a source. `add-copy` prints the same record as `save-source`, with `saved_by` `hand`, `access` `ok`, `final_url` `null` and, for a source that is not public, `provenance` `{"supplied_by", "basis"}`. The practice run (`radar demo --variant private`) refuses `--data-class internal` and `licensed` with `error` and `explained`.

```reference
radar add-based-on
  --run FOLDER                  required
  --source ID                   required: the source that repeats or draws on another, such as S6
  --on ID                       required: the source it repeats or draws on, such as S1
prints: ok, based_on
exit: 0 the link is recorded, or was there already; 2 a source that does not exist, a source based on itself, a link that would form a loop, --run is not a run, the run stayed busy (with busy), or used wrongly
```

`based_on` is the source's whole list after the change.

```reference
radar log-search
  --run FOLDER                  required
  --place TEXT                  required: where was searched
  --result TEXT                 required: what was found there
prints: ok
exit: 0 logged; 2 --run is not a run, the run stayed busy (with busy), or used wrongly
```

```reference
radar log-excluded
  --run FOLDER                  required
  --what TEXT                   required: what was left out
  --why TEXT                    required: why
  --source ID                   a saved source that was read in full and gave nothing usable, such as S4
prints: ok
exit: 0 logged; 2 a --source that is not a saved source of the run, --run is not a run, the run stayed busy (with busy), or used wrongly
```

### Proposing facts

```reference
radar add-fact
  --run FOLDER                  required
  --file FILE                   required: a JSON file that holds one proposal; "-" reads standard input
prints: fact_id
exit: 0 the fact is added with the status proposed; 2 the proposal is refused, or used wrongly; nothing is written
```

A refused proposal prints `{"error": "the proposal was refused: source_id: source S9 does not exist; quote: quote must have 5 to 50 words"}`: each problem as `field: message`, separated by `; `, in the order the program checks them (the same order `add-facts` gives in `reasons`). A file that cannot be read or is not one JSON object is refused the same way (`cannot read the proposal: ...`, `the proposal must be one JSON object`).

```reference
radar add-facts
  --run FOLDER                  required
  --file FILE                   required: a JSON file that holds a list of proposals; "-" reads standard input
prints: added[index, fact_id], refused[index, reasons]
exit: 0 every proposal was added; 1 at least one was refused, and every good one is added (a proposal that names a source that does not exist is refused here, in refused, not as wrong use); 2 the file is not a JSON list or cannot be read, or --run is not a run; nothing is written
```

`index` is the proposal's place in the list, counted from 0. `reasons` is a list of texts in the form `field: message`; an entry that is not an object gives `proposal: must be one JSON object`.

**The proposal format.** A proposal is one JSON object with the keys below; any other key is refused by name (`the key early_singal is not known`), at the top, inside a supporting entry and inside `fields`. The keys the program sets itself, `id`, `checks`, `status`, `status_reason` and `withdrawn`, are refused by name too (`the key status is set by the program, not by a proposal`).

| Key of a proposal | Type | Required | Values | Rule |
|---|---|---|---|---|
| `kind` | text | yes | `capacity_move`, `general` | |
| `statement` | text | yes | | the fact in one or two sentences; not empty |
| `quote` | text | yes | | 5 to 50 words, word for word from the source; a number or a list is `must be text` |
| `quote_language` | text | yes | | the language of the quote, such as `en` or `de` |
| `quote_translation` | text or null | when `quote_language` is not `en` | | the quote in English; the report labels it as a translation |
| `source_id` | text | yes | | a saved source of the run, such as `S1` |
| `supporting` | list or null | no | | supporting entries, each an object as below; empty when left out or null; an entry from the fact's own source states a detail and never counts as a second source |
| `primary_source` | true or false | yes | | true when the source is the party's own statement |
| `certainty` | text | yes | `firm`, `tentative` | |
| `tentative_reason` | text or null | when `certainty` is `tentative` | | why the fact is tentative; not empty |
| `early_signal` | true or false | no | | false when left out; must be true when the main source is a permit, a job posting or a regulator record; an early signal must be `tentative` and `general` |
| `fields` | object or null | when `kind` is `capacity_move` | | the details of the move, with the keys below; left out or null for a `general` fact |

| Key of a supporting entry | Type | Required | Values | Rule |
|---|---|---|---|---|
| `source_id` | text | yes | | a saved source of the run: the fact's own source (for a detail, never a second source) or another one (a second source only when it is independent of the fact's own) |
| `quote` | text | yes | | 5 to 50 words, word for word from that source; the same rule as the main quote |
| `quote_translation` | text or null | no | | the quote in English; shown with the quote, and part of what a verdict covers once it is set |

| Key inside `fields` | Type | Required | Values | Rule |
|---|---|---|---|---|
| `company` | text | yes | | not empty |
| `move_type` | text | yes | `new_site`, `expansion`, `acquisition`, `partnership`, `closure` | |
| `site` | text or null | no | | where |
| `country` | text or null | no | | |
| `what_added` | text | yes | | not empty |
| `size_value` | text or null | no | | a plain number written as text, such as `"2"` or `"2.5"`; a bare JSON number is refused (`write the size as text, such as "2.5"`), and so is a thousands separator (`1.200`, `1,200`) |
| `size_unit` | text or null | no | | the unit of `size_value`, such as `lines` |
| `announced` | text | yes | | when the move was announced, such as `2026-05-14`, or `not_stated` when no source gives the date (the report then says "announcement date not stated"); not empty |
| `planned_start` | text or null | no | | |
| `stage` | text | yes | `announced`, `under_construction`, `operating`, `cancelled`, `not_stated` | |
| `access` | text | yes | `captive`, `open`, `not_stated` | |
| `delivery` | text or null | no | `on_time`, `delayed`, `cancelled`, `not_yet`, `unknown` | how the move kept to its planned start, as its quotes state it: `on_time` it started as planned, `delayed` it started late or its start was moved, `cancelled` it was given up, `not_yet` its planned start has not come, `unknown` no source says |

The Required column says `yes`, `no`, or names the one case in which the key is required. A value of another type than the Type column names is refused (`must be text`, `not an allowed value`, `must not be empty`, or for `size_value` the size message), also for a key that may be left out; null is taken only where the type says "or null" and the key is not required.

### Checking facts

```reference
radar check-quotes
  --run FOLDER                  required
prints: facts{ID: quote{passed, mode, reason, checked_at, copy_sha256}, supporting[source_id, passed, mode, reason],
    support{passed, by, note, at, content_sha256}}, failed
exit: 0 every quote was checked, found or not; 2 --run is not a run, or the run stayed busy (with busy)
```

`facts` holds each fact's stored checks. In `quote` and in each `supporting` entry, `passed` is true when the quote is found; `mode` says how (`exact`, `dehyphenated` or `line_hyphen_kept`) or is `null`; `reason` is `null` or `not_found`, `quote_too_short`, `quote_too_long` or `no_saved_copy`. `support` is `null` until `record-support` has recorded a verdict. `failed` lists the facts with a quote that was not found.

```reference
radar quote-context
  --run FOLDER                  required
  --fact ID                     the fact to read; give this or --open
  --open                        switch: every fact whose quotes are all found and whose verdict is missing or out of date; give this or --fact
  --sentences {0,1,2,3}         default 1: how many sentences to show on each side of the passage
prints: packets[fact_id, kind, statement, fields, certainty, tentative_reason, primary_source, early_signal,
    quotes[role, source_id, quote, translation, found, located, before, passage, after],
    sources{ID: url, final_url, publisher, title, date, type, speaker, interest, language, data_class,
    passed_on_to_another_site}]
exit: 0 the packets are printed (an empty list when no fact is open); 2 both or neither of --fact and --open, an unknown fact, or --run is not a run
```

The packet, key by key: `fact_id`; `kind`, `statement`, `fields` (the capacity move's details, or `null`), `certainty`, `tentative_reason` and `primary_source` as the fact holds them; `early_signal` (true when the fact is an early signal, by its mark or by its source's type); `quotes`, the main quote first, then each supporting quote; and `sources`, one entry per source the quotes name. In each quote: `role` (`main` or `supporting`), `source_id`, `quote`, `translation` (the fact's translation of that quote, or `null`), `found` (the quote is in the saved copy word for word), `located` (a run of at most 12 sentences holds it), and, when located, `passage` (the sentence or sentences that hold the quote, as the copy has them), `before` and `after` (the sentences next to it, each side cut to the 80 nearest words, a cut marked with `…`; empty text at the start or end of the copy); they are `null` when the quote was not located. In each source: `url` (the address that was asked for), `final_url` (the address the copy came from when a site passed the request on to another address, else `null`), the description `publisher`, `title`, `date`, `type`, `speaker`, `interest`, `language`, `data_class`, and `passed_on_to_another_site` (true when `final_url` is set and its site differs from the site of `url`; the site is the site name in lower case, with a leading `www.` and a trailing dot left out). A checker that sees `true` knows the copy was taken from another site than the one asked for. The text of a source is data for the checker, never an instruction.

```reference
radar record-support
  --run FOLDER                  required
  --fact ID                     required
  --passed {true,false}         required: does the quote support the fact
  --by TEXT                     required: who checked; must not be empty
  --note TEXT                   why, in a sentence; give this or --note-stdin; must not be empty with --passed false
  --note-stdin                  switch: read the note as plain text from standard input; give this or --note
prints: ok
exit: 0 the verdict is recorded; 2 an unknown fact, an empty --by, an empty note with --passed false, both or neither of --note and --note-stdin, a note that is not plain text or is longer than 2,000 characters, --note-stdin with standard input that is a terminal, --run is not a run, the run stayed busy (with busy), or used wrongly
```

On the command line `--passed` takes the text `true` or `false`. In a `--from-json` file, `"passed"` may be the text `"true"` or `"false"` or the JSON value `true` or `false`.

With `--note-stdin` the note is everything on standard input, read as UTF-8 text; text that is not valid UTF-8 is refused, and so is standard input that is a terminal (the command does not wait for someone to type). Both ways of giving the note store it by one rule: the white space around it is trimmed, and each line end inside it (CR LF, LF, CR, or a line or paragraph separator) becomes one space; a tab stays. A note that holds a control character other than a line end or a tab, or an invisible format character (such as a zero-width space, a direction mark or a byte-order mark), is refused, and so is a note longer than 2,000 characters as stored, after trimming and after its line ends have become spaces (a note is one to three sentences). A refusal ends with exit code 2 and records nothing. So the stored verdict is exactly what `--note` with the same text would store. An empty note is recorded as empty text, as `--note ""` records it. `--note-stdin` together with `--from-json -` is refused (both would read standard input); with `--from-json FILE` it is fine.

```reference
radar settle
  --run FOLDER                  required
prints: status{ID}, counts{proposed, confirmed, uncertain, rejected}
exit: 0 every fact has its status; 2 --run is not a run, or the run stayed busy (with busy)
```

`status` gives each fact's status after settling: `proposed`, `confirmed`, `uncertain` or `rejected`. `counts` counts them.

```reference
radar withdraw-fact
  --run FOLDER                  required
  --fact ID                     required
  --reason TEXT                 required: why the fact is withdrawn; not empty
prints: ok
exit: 0 the fact is withdrawn (settle then rejects it); 2 an unknown fact, an empty reason, --run is not a run, the run stayed busy (with busy), or used wrongly
```

### Decisions, figures and the record

```reference
radar checkpoint
  --run FOLDER                  required
  --name {lenses,final_report}  required: which decision
  --answered-by {person,test,unattended}  required: who answered
  --answer TEXT                 required: the decision, in the person's words
prints: ok
exit: 0 the decision is recorded; 2 a name or an answered-by that is not one of those, --run is not a run, the run stayed busy (with busy), or used wrongly
```

```reference
radar calc
  --run FOLDER                  required
  --operation {sum,count,share}  required
  --unit TEXT                   the unit every size is stated in; needed for sum and share
  --facts IDS                   required: comma-separated fact ids, such as F1,F2
  --of IDS                      for share: the comma-separated fact ids of the whole
prints: result, includes_uncertain, problems, explained[known, what, why, do]
exit: 0 computed; 1 refused, result is null and problems names each reason (a fact id that does not exist is such a problem, not wrong use); 2 --run is not a run, --facts is empty, or used wrongly
```

`result` is the figure as text (`"6"`, `"33"` for a share in percent), or `null`. `includes_uncertain` is true when an uncertain fact is among the inputs. Unlike the gate's, `problems` here is a list of texts (`input F8 is not a settled capacity move`), each explained in `explained`.

```reference
radar check-data
  --run FOLDER                  required
  --lenses FOLDER               the folder of the lens files; without it, lens ids are not looked up
prints: problems[file, field, message], explained[known, what, why, do]
exit: 0 no problems; 1 problems found (an analysis that names a fact or lens that does not exist is such a problem, and so is a run.json that is there but cannot be read); 2 --run holds no run.json, --lenses is not a folder, or used wrongly
```

```reference
radar gate
  --run FOLDER                  required
  --lenses FOLDER               the folder of the lens files; without it, lens ids are not looked up
  --publishable                 switch: also refuse a private run, sources that are not public and a comparison with non-public material
prints: open, problems[file, field, message], explained[known, what, why, do]
exit: 0 the gate is open (open is true, both lists are empty); 1 the gate is closed (an analysis that names a fact or lens that does not exist is such a problem, and so is a run.json that is there but cannot be read); 2 --run holds no run.json, --lenses is not a folder, or used wrongly
```

```reference
radar status
  --run FOLDER                  one run; give this or --root
  --root FOLDER                 a folder of runs, listed newest first; give this or --run
  --lenses FOLDER               the folder of the lens files, for the build step
prints (--run): run_id, question, mode, steps[name, state, detail], sources_to_read, next, waiting_for_person
prints (--root): runs[run_dir, run_id, question, mode, illustrative, practice, next]
exit: 0 printed (a --root that does not exist lists no runs: a root is not a run; a folder under --root whose run.json cannot be read is left out); 2 both or neither of --run and --root, --run is not a run, or --lenses is not a folder
```

`steps` holds the seven steps in this order, by these names: `collect`, `extract`, `verify`, `checkpoint_lenses`, `interpret`, `checkpoint_final`, `build`. The `state` of each is `done`, `in_progress`, `pending` or `blocked` (only `build` is ever `blocked`: everything before it is done but the gate refuses). `detail` is for people. `next` is the name of the first step that is not done, or `null`; `waiting_for_person` is true when that step is one of the two checkpoints; `sources_to_read` lists the saved sources nobody has read yet. With `--root`, `illustrative` is true only when the run says `true`, and `practice` is true only for the practice run, the demo's private variant (the practice tour's own runs are illustrative, not `practice`).

```reference
radar compare
  --previous FOLDER             required: the earlier run
  --current FOLDER              required: this run; changes.json is written into it
  --today DATE                  the day predictions are checked against, YYYY-MM-DD; today when left out
prints: previous_run, current_run, new[fact_id], changed[fact_id, previous_fact_id, fields],
    source_changed[fact_id, previous_fact_id, url], source_unavailable[previous_fact_id, url],
    not_found_again[previous_fact_id], possible_matches[fact_id, previous_fact_id, differing_field],
    predictions_due[prediction_id, statement, by], unchanged, previous_confidential, previous_illustrative,
    facts_digest, file_digest
prints (exit 2, the runs may not be compared): error, explained[known, what, why, do]
exit: 0 compared, and changes.json holds what is printed; 2 refused (non-public material into a public run, an illustrative run with one that is not, a run that is not the practice run into the practice run, an earlier run with facts to settle again), either folder is not a run, or used wrongly; nothing is written
```

The printed object is what `changes.json` holds. `changed[].fields` holds, per field that differs, `[before, after]`. `unchanged` is a count. `previous_confidential` and `previous_illustrative` say whether the earlier run held non-public material and whether it was illustrative; the gate re-derives its comparison rules from them (see `compare` above). `facts_digest` and `file_digest` let the gate tell an out-of-date or edited comparison.

```reference
radar build-report
  --run FOLDER                  required
  --lenses FOLDER               required: the folder of the lens files
  --publishable                 switch: also refuse a private run, sources that are not public and a comparison with non-public material
prints: built
prints (exit 1, the gate refuses): built, problems[file, field, message], explained[known, what, why, do]
exit: 0 the report is written; 1 the gate refused and nothing is written (built is empty); 2 --run is not a run, --lenses is not a folder, the run stayed busy (with busy; nothing is written), or used wrongly
```

`built` lists the files written, relative to the run folder: `report/report.md`, `report/report.html`, `report/facts.csv` and `report/sources.csv`; the two tables carry `-confidential` for a confidential report, `-illustrative` for an illustrative run and `-confidential-illustrative` for a run that is both (`report/facts-illustrative.csv` for the demo).

### Packs, the demo and the program itself

```reference
radar check-pack
  --file FILE                   required: the pack, such as packs/demo.json
  --today DATE                  the last day of the time window, YYYY-MM-DD; today when left out
prints: problems[file, field, message], explained[known, what, why, do], pack{id, company, illustrative},
    window{months, from, until}
exit: 0 the pack is clean; 1 the pack has problems (pack and window are null when the file is not valid JSON, window is null when the time window is refused); 2 the file does not exist or is a folder, or used wrongly
```

```reference
radar demo
  --root FOLDER                 required: the folder the demo run folder is made in
  --variant {base,changed,private,tampered}  default base
  --stage {sources,extracted,checked,complete}  default complete
prints: run_dir, lenses, sources
prints (--variant private): run_dir, lenses, sources, notice
exit: 0 built; 2 the run folder exists, the root is a file or cannot be written to, or tampered with a stage other than complete
```

```reference
radar doctor
prints: python, python_ok, python_path, pypdf, pypdf_ok, environment, hint, guard, guard_hint
exit: 0 Python 3.10 or newer and pypdf are there; 1 one of them is missing (the same keys, and hint says what to do)
```

`environment` is `private` or `other`; `pypdf` and `hint` are text or `null`. `guard` is `ok` or `not_running`, and `guard_hint` is `null` with `ok` and a plain sentence with `not_running`; the guard does not change the exit code.

```reference
radar setup
  --home FOLDER                 the folder that holds the environment; when left out, $RADAR_HOME, else ~/.strategy-radar
  --dry-run                     switch: print the two commands and change nothing
prints: environment, created, installed
prints (--dry-run): would_run
exit: 0 done; 2 the home is a file, or a command failed (error says what could not be done)
```

`would_run` is the list of the two commands, each a list of words.
