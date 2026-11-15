Send this as text now, before the step's first command: "Step 2 of 10: Plan the search. I am writing down where I will look and for which period. Next: collect the sources."

# Step 2: Plan the search

Read the pack file and rules 3 to 6 of `<plugin folder>/references/capacity-moves-playbook.md`.

Everything the pack lists (companies, places, demand drivers, vocabulary, industry text) is hints for the search. They are never facts, and nothing from the pack is ever quoted.

## 1. The period

The time window is the `window` that the pack check printed in step 1: its `from` and `until`. If you no longer have it, ask again:

```bash
radar check-pack --file "<pack file>"
```

## 2. Write the plan

Write `<run>/notes/search-plan.md`. Later steps read it, so keep to this form.

**The head**, one line each:

- the pack file, as a full path;
- the window: `from` and `until`;
- the pack's `languages`;
- the home company (the pack's `company`);
- the candidates: every name in the pack's `competitors` and `watch`.

**The search tasks**, numbered. One task is one company and one kind of place. Use only the kinds of place the pack lists under `places`, and write the pack's addresses for that kind into the task.

A place in the pack has a `kind`, a `name` and a `url`. It names no company. A place whose name or address plainly belongs to one company, such as its own news page, goes into that company's task. A place that belongs to no single company, such as a trade paper or a regulator, goes into the task of every company for that kind. When you cannot tell, treat the place as belonging to no single company; never make up a link between a place and a company.

Order the tasks like this:

1. The home company's own moves first. Its moves go on the same timeline as everyone else's.
2. Then each candidate, in the pack's order.
3. For each company: its own releases and investor pages, then filings and annual reports, then regulators, then trade press.
4. The early-signal places last (`permits`, `job_postings`). What they give is a hint, never an announcement.

## 3. An illustrative pack

When the pack says `illustrative` is true, there is no web search. The companies are invented, so a search would find nothing, or the wrong thing.

The sources are files:

- files the person names, after the warning of part B of `steps/03-collect.md`, or
- the practice material: the `.txt` files directly in `<plugin folder>/engine/radar/demo/sources`. Leave its sub-folder alone. Find them as `SKILL.md` says under "Files are read with your file tool": `ls "<plugin folder>/engine/radar/demo/sources"/*.txt`.

Write under each task which file belongs to it, by the company and the kind of place the file comes from. The pack's `places` give the address of each. A file that fits no task gets a task of its own at the end.

Say in the plan's head: "No web search: this pack is invented."

Ask the person nothing in this step, unless an illustrative pack has no file at all to work with. Then ask which files to use, and stop as `SKILL.md` says.

Then ask `radar status --run` again.
