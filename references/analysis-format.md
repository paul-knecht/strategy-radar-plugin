# The analysis file

Read this before you write `analysis.json`, the lead model's one file of judgement. Facts stay in the facts; this file holds the "so what". Run `radar check-data` and `radar gate` to see what the program refuses. The lists after the rules say what that covers and what it does not. Examples use invented names only (Example Pharma, Competitor A).

The file is one object with the 13 sections below, in this order. Only `messages` and `decision_options` (with its `framing`) are needed for the check to pass; every other section may be empty. An empty section shows nothing in the report. There is no section for early signals: such a fact stays among the facts with its mark, and the report shows it in its own block.

## Rules for judgement writing

1. Every "so what" point names the facts it rests on, in a key ending in `fact_ids`. Only confirmed or uncertain facts may be named. A rejected or withdrawn fact is refused, and so is an id that does not exist. The same holds for a fact id written in a text, such as "as F2 shows"; only a flag of the bias audit may name any fact that exists, whatever its status.
2. A lens appears only as `lens_id` on a reasoning step and in `lens_notes`, and only a lens the person chose at the first stop (the `lenses` checkpoint). The lens ids are looked up in the lens files, so a made-up one is refused.
3. Scenarios, assumptions and predictions are judgement. Write them as such: "may", "would", "if". Never write them as facts.
4. Every total, count and share comes from `radar calc`. Copy its `result` as printed, into the entry under `calculations` and into the text. Never work one out yourself and never convert units. A figure that one fact states, such as its number of lines, stays in that fact: a message's text does not repeat it.
5. No scores or rankings of competitors, no market-size number, and no recommendation such as "buy X". Set out the options and the evidence; management decides.
6. Write in plain words for a business reader. Short sentences. Quotes stay out of this file; the facts hold them.

**The program checks.** `radar check-data` and `radar gate` both name a breach of each, unless the item says otherwise:
- each chain has at least one fact step and exactly one conclusion step; a fact step names at least one fact, and the conclusion is the last step;
- `confidence`, `framing`, step kinds, support levels, calculation operations and audit checks use an allowed word;
- the number of scenarios is none or two to four, each with at least one assumption that exists and at least one entry in `signposts`;
- a baseline has a company and at least one fact, no wording of its own, and no early signal;
- every fact id exists;
- the fact counts (confirmed or uncertain): only `radar gate` names this, not `radar check-data`;
- a fact id written in a text, such as "as F2 shows", names a fact that counts: only `radar gate` names this, not `radar check-data`;
- a flag of the bias audit names only facts that exist, whatever their status;
- every lens id is a lens file that exists;
- a prediction has a real date and a whole-number probability from 1 to 99;
- every calculation result equals the one the program computes again: only `radar gate` names this, not `radar check-data`.

**Only you can keep these** (nothing refuses a breach):
- every total, count or share in a text is one listed under `calculations`, written as the program printed it;
- no text restates the claim of a rejected or withdrawn fact;
- `framing` is `company` only with a confirmed fact that quotes the company;
- a lens is one the person chose at the first stop;
- one baseline entry per company;
- an outside view is honest, as described under `outside_view`;
- no recommendation, no score or ranking of competitors, no market-size number;
- no probability word in the text of a message; use the `probability` number of a prediction instead.

## `messages`

The key messages of the report. Each is one claim the evidence supports, and each has these keys.
- `id`: unique, such as `M1`. Predictions point to it.
- `text`: the claim in one or two sentences.
- `confidence`: exactly one of `high`, `medium` or `low`, chosen as `confidence-wording.md` says.
- `chain`: the steps from the facts to the claim, in order. It has at least one fact step and exactly one conclusion step, and the conclusion is last. Each step has:
  - `kind`: `fact`, `reasoning` or `conclusion`.
  - `text`: what the step says.
  - `fact_ids`: the facts it rests on. A `fact` step names at least one; a `reasoning` or `conclusion` step may name none.
  - `lens_id`: the lens used on a `reasoning` step, or `null`. A fact or conclusion step has `null`.
- `counter_view`: the strongest reason the claim may be wrong, in the same detail as the claim.
- `would_change`: what you would have to see to change your mind.
- `outside_view`: an object with `text` and `fact_ids`. Either it names a comparison class and how such cases usually turn out, and `fact_ids` names the fact of this run that states it; or, when no fact of this run does, `text` starts with "None found:" and `fact_ids` is empty. Never give a usual outcome or a figure that is not a fact of this run.

## `demand_signals`

What the evidence says about demand, each marked as a signal and never as a forecast. Each has `text` and `fact_ids`. A demand driver from the pack is a hypothesis until a source supports it.

## `decision_options`

The strategic question and the options, without a recommendation. One object with these keys.
- `question`: the question, as the pack or the person framed it.
- `framing`: `company` or `user`. It is `company` only when `framing_fact_ids` names a confirmed fact that quotes the company asking the question. Otherwise it is `user`.
- `framing_fact_ids`: the facts that show the framing. Empty for `user`.
- `options`: each with a `name`, a list `for` and a list `against`. Each point has `text` and `fact_ids`. A point with no fact says so in its words, such as "No plant for sale appears in the sources we read."
- `internal_questions`: plain text questions that only the company can answer from the inside.

## `baselines`

How big the company behind a move is: its size, sites and investment, so a move can be judged against it. One entry per company, with `company` and `fact_ids` and nothing else. At least one fact; no wording of its own, because the report shows each fact's own checked statement. A baseline never rests on an early signal.

## `watch_items`

What to look at next. Each has `text` and `trigger`, the event that would tell you something changed. It may carry `scenario_id` to tie it to a scenario.

## `assumptions`

What the messages and scenarios lean on, labelled as judgement. Each has:
- `id`: unique, such as `A1`.
- `text`: the assumption.
- `support`: `strong`, `partial` or `weak`, for how well the facts back it.
- `if_wrong`: what follows if it is false.
- `fact_ids`: the facts behind it; may be empty.

## `scenarios`

None, or two to four. Each is a story of how things may go, and the report labels it as judgement. Each has:
- `id`: unique, such as `SC1`.
- `name` and `description`.
- `assumption_ids`: at least one `id` from `assumptions`.
- `signposts`: at least one sign that this scenario is happening, each with `text` and `fact_ids` (empty if no fact yet).

## `predictions`

A prediction that can be scored later. Each has:
- `id`: unique, such as `P1`.
- `message_id`: the `id` of a message.
- `statement`: what is expected.
- `by`: the date it must be true by, as `YYYY-MM-DD`.
- `resolves_when`: how anyone will know.
- `probability`: a whole number from 1 to 99. The report adds the word.

## `calculations`

Every total, count or share the text mentions, each written in the text exactly as `result` holds it (a share as a whole number of percent). Ask the program, then copy the answer. Never type a result of your own.

```
radar calc --run RUN --operation sum --facts F1,F2,F3,F6 --from-json FILE
radar calc --run RUN --operation share --facts F4 --of F1,F2,F3,F4,F6 --from-json FILE
```

The unit is text taken from the facts, so it travels in the JSON file: FILE holds `{"unit": "lines"}`. The fact numbers stay on the line.

Each entry has `id`, `label` and:
- `operation`: `sum`, `count` or `share`.
- `unit`: the unit the facts state, such as `lines`.
- `fact_ids`: the facts used. Only capacity moves that count; never an early signal.
- `of_fact_ids`: for `share`, the whole the facts are part of; otherwise empty.
- `result`: the `result` the program printed, as text. The gate computes it again and refuses a difference.

## `contradictions`

Two facts that cannot both hold unchanged. Each has `text` and `fact_ids` naming both. Say what differs; do not choose between them.

## `not_found`

A list of plain sentences, each saying what was looked for and not found. It has no keys. The report shows gaps as findings, so do not hide them.

## `lens_notes`

What a lens shows about this run. Each has `lens_id`, a lens the person chose, and `here`: what the lens makes visible in these facts.

## `audit_flags`

The bias auditor's flags, copied word for word. The lead model adds none and removes none. A flag may name any fact of this run that exists, whatever its status: it may point at a fact the analysis should not lean on. Each has `text` and `check`, one of `framing`, `outside_view`, `uncertainty`, `competitor_response`, `evidence_symmetry`, `missing_information`, `success_stories`, `causality`, `disconfirmation` or `independence`.

## Example

One complete analysis for the invented demo run (Example Pharma). It uses the demo's facts `F1` to `F7` (all confirmed or uncertain; the three rejected ones, `F8` to `F10`, stay out) and its two invented lenses. Run `radar demo --root DIR` and `radar gate --run DIR/demo --lenses LENSES` to see it pass.

```json analysis-example
{
  "messages": [
    {
      "id": "M1",
      "text": "New filling capacity in this sample is mostly built for the builder's own use, not for outside customers.",
      "confidence": "medium",
      "chain": [{"kind": "fact", "text": "Competitor A is adding lines at Plant North and at Plant South, and Example Pharma is building a line at Site Y. Each says its lines are for its own products. Drug maker B says Competitor C bought a plant from it and will use it for its own products.", "fact_ids": ["F1", "F2", "F3", "F6"], "lens_id": null}, {"kind": "fact", "text": "The only site in the sample that is stated to be open to other customers is Competitor B's.", "fact_ids": ["F4"], "lens_id": null}, {"kind": "reasoning", "text": "A firm keeps a step inside when buying it is costly or risky. Companies that build for their own use may be protecting supply and launch timing, which would fit that idea, though the confirmed facts do not state their reasons.", "fact_ids": [], "lens_id": "firm-boundaries"}, {"kind": "conclusion", "text": "In the moves confirmed here, 6 lines are for the builder's own use, and the lines open to outside customers are 33 percent of all lines. Most of the capacity confirmed here is for the builder's own use.", "fact_ids": [], "lens_id": null}],
      "counter_view": "The sample is small and rests on public announcements. Open capacity added by companies that do not announce it would not show up here, and one trade report suggests Competitor C may open part of its plant to outside customers.",
      "would_change": "New open sites announced by other companies, or Competitor C confirming that it will sell filling slots.",
      "outside_view": {"text": "None found: no fact of this run states an outcome for comparable cases.", "fact_ids": []}
    },
    {
      "id": "M2",
      "text": "Open capacity is already scarce, so buying outside filling slots is not a quick alternative to building.",
      "confidence": "medium",
      "chain": [{"kind": "fact", "text": "Competitor B states that its contract filling slots in Country Z are booked through the end of 2027.", "fact_ids": ["F5"], "lens_id": null}, {"kind": "fact", "text": "Its lines there are open to other customers and have been running since January 2026.", "fact_ids": ["F4"], "lens_id": null}, {"kind": "reasoning", "text": "When the one open provider in the sample is full, a buyer needs either a new open site or a slot at a provider this sample does not cover.", "fact_ids": [], "lens_id": null}, {"kind": "conclusion", "text": "Outside filling capacity may stay hard to get until new open sites start. No open site among the confirmed moves is under construction.", "fact_ids": [], "lens_id": null}],
      "counter_view": "Competitor B may add lines if customers commit to them. Whether it plans to is an open question that the facts checked here do not answer.",
      "would_change": "Competitor B announcing more lines, or a customer reporting free outside slots during 2027.",
      "outside_view": {"text": "None found: no fact of this run states an outcome for comparable cases.", "fact_ids": []}
    },
    {
      "id": "M3",
      "text": "Example Pharma's own build puts it on the same path as most rivals. The open question is speed, not build versus buy.",
      "confidence": "low",
      "chain": [{"kind": "fact", "text": "Example Pharma is building one line at Site Y, for its own products, due in 2027.", "fact_ids": ["F3"], "lens_id": null}, {"kind": "fact", "text": "Drug maker B says Competitor C bought a working plant whose lines were already running, and will use it for its own products.", "fact_ids": ["F6"], "lens_id": null}, {"kind": "reasoning", "text": "A plant is hard to reverse, so these moves tell rivals how each firm means to compete. Captive lines commit their owners to supplying themselves, and rivals may read Example Pharma's line as a sign that it will need less outside capacity later.", "fact_ids": [], "lens_id": "capacity-commitment"}, {"kind": "conclusion", "text": "For Example Pharma, speed may matter more than the build-or-buy label. Drug maker B says the plant Competitor C bought was already running, while the new builds confirmed here are due in 2027 or later.", "fact_ids": [], "lens_id": null}],
      "counter_view": "The sample shows only one sale of a working plant, and no plant for sale. Buying may not be open to Example Pharma at all.",
      "would_change": "A seller of a working plant coming forward, or Example Pharma's own line slipping past its planned start.",
      "outside_view": {"text": "None found: no fact of this run states an outcome for comparable cases.", "fact_ids": []}
    }
  ],
  "demand_signals": [
    {
      "text": "Competitor B says its contract filling slots are booked through the end of 2027.",
      "fact_ids": ["F5"]
    },
    {
      "text": "Drug maker B reports that Competitor C bought a plant that was already running. That may point to a wish for capacity sooner than a new build allows.",
      "fact_ids": ["F6"]
    }
  ],
  "decision_options": {
    "question": "Should Example Pharma add its own filling capacity, buy outside capacity, or do both?",
    "framing": "user",
    "framing_fact_ids": [],
    "options": [
      {"name": "Build its own capacity", "for": [{"text": "Example Pharma is already building a line at Site Y, due in 2027.", "fact_ids": ["F3"]}, {"text": "Competitor A is adding lines for its own use at Plant North and at Plant South.", "fact_ids": ["F1", "F2"]}], "against": [{"text": "Competitor A's lines at Plant North were announced in May 2026 and are planned to start in 2028.", "fact_ids": ["F1"]}]},
      {"name": "Buy outside capacity", "for": [{"text": "Competitor B's three lines are open to other customers.", "fact_ids": ["F4"]}], "against": [{"text": "Competitor B's contract slots are booked through the end of 2027.", "fact_ids": ["F5"]}]},
      {"name": "Buy a working plant", "for": [{"text": "Drug maker B reports that Competitor C bought a plant with two lines already in operation.", "fact_ids": ["F6"]}], "against": [{"text": "No plant for sale appears in the sources we read.", "fact_ids": []}]}
    ],
    "internal_questions": [
      "How much of Example Pharma's volume could move to an outside provider without a new regulatory approval?",
      "What would a year of delay at Site Y cost?"
    ]
  },
  "baselines": [
    {
      "company": "Competitor B",
      "fact_ids": ["F4"]
    }
  ],
  "watch_items": [
    {
      "text": "Whether Competitor B announces more lines or reports free slots.",
      "trigger": "Competitor B's next annual filing, or a customer reporting free outside slots.",
      "scenario_id": "SC2"
    },
    {
      "text": "Progress at Plant North.",
      "trigger": "A construction contract award or a revised start date from Competitor A.",
      "scenario_id": "SC1"
    }
  ],
  "assumptions": [
    {
      "id": "A1",
      "text": "Outside filling capacity stays tight until at least the end of 2027.",
      "support": "partial",
      "if_wrong": "Buying outside capacity becomes a faster and cheaper route than building.",
      "fact_ids": ["F5", "F4"]
    },
    {
      "id": "A2",
      "text": "Announced lines start close to their planned dates.",
      "support": "weak",
      "if_wrong": "The tight period lasts longer, or ends sooner, than the plans suggest.",
      "fact_ids": ["F1"]
    },
    {
      "id": "A3",
      "text": "Rivals keep their new lines for their own use.",
      "support": "partial",
      "if_wrong": "More outside capacity appears than this report counts.",
      "fact_ids": ["F1", "F2", "F6"]
    },
    {
      "id": "A4",
      "text": "Some rivals open part of their new lines to outside customers.",
      "support": "weak",
      "if_wrong": "Open capacity stays scarce, as in the tight market view.",
      "fact_ids": ["F7"]
    }
  ],
  "scenarios": [
    {
      "id": "SC1",
      "name": "Tight market",
      "description": "Rivals keep building for their own use and open capacity stays scarce. Example Pharma's own line at Site Y becomes the main way to secure supply.",
      "assumption_ids": ["A1", "A3"],
      "signposts": [{"text": "Competitor A confirms its start date for Plant North.", "fact_ids": ["F1"]}, {"text": "Competitor B still reports its contract slots as fully booked.", "fact_ids": ["F5"]}]
    },
    {
      "id": "SC2",
      "name": "New outside capacity arrives",
      "description": "Some rivals open lines to outside customers, and buying becomes a real option before Example Pharma's own line starts. This scenario rests on A4, the opposite of A3.",
      "assumption_ids": ["A4"],
      "signposts": [{"text": "Competitor C confirms that it will sell filling slots to outside customers.", "fact_ids": []}, {"text": "A second contract provider reports free slots.", "fact_ids": []}]
    }
  ],
  "predictions": [
    {
      "id": "P1",
      "message_id": "M1",
      "statement": "Competitor A's Plant North will start production by the end of 2028.",
      "by": "2028-12-31",
      "resolves_when": "Competitor A, or a trade source that cites it, reports the first commercial batches from Plant North.",
      "probability": 55
    },
    {
      "id": "P2",
      "message_id": "M2",
      "statement": "Competitor B's filing for 2027 will describe its Country Z contract slots as fully booked through the end of 2027.",
      "by": "2028-12-31",
      "resolves_when": "Competitor B's filing for 2027, published in 2028, states how many contract slots are booked.",
      "probability": 65
    }
  ],
  "calculations": [
    {"id": "C1", "label": "Lines for the builder's own use, in the moves confirmed here", "operation": "sum", "unit": "lines", "fact_ids": ["F1", "F2", "F3", "F6"], "of_fact_ids": [], "result": "6"},
    {"id": "C2", "label": "Lines open to outside customers, as a share of all lines confirmed here", "operation": "share", "unit": "lines", "fact_ids": ["F4"], "of_fact_ids": ["F1", "F2", "F3", "F4", "F6"], "result": "33"}
  ],
  "contradictions": [
    {
      "text": "Drug maker B says Competitor C will use the plant only for its own products. One unnamed source says Competitor C may open a line to outside customers. Both cannot hold unchanged.",
      "fact_ids": ["F6", "F7"]
    }
  ],
  "not_found": [
    "No source says how much of Competitor A's new capacity could ever serve outside customers.",
    "No public source gives the price of outside filling slots, so costs cannot be compared."
  ],
  "lens_notes": [
    {
      "lens_id": "firm-boundaries",
      "here": "Competitor A and Example Pharma state that their new filling lines are for their own products. Drug maker B says Competitor C bought a working plant from it and will use it for its own products. The same step sits on different sides of the line for different firms."
    },
    {
      "lens_id": "capacity-commitment",
      "here": "Each captive line is a commitment that is hard to undo. The open question is how rivals and outside providers will read it."
    }
  ],
  "audit_flags": [
    {
      "check": "independence",
      "text": "The report that Competitor C may open a line to outside customers rests on one unnamed source. It is marked uncertain and no message depends on it."
    },
    {
      "check": "evidence_symmetry",
      "text": "Every message rests on what companies chose to publish: their own releases, a filing, an annual report and trade reports of them. What companies do not announce is not seen in this run. The evidence for open capacity here is one company's filing and one unnamed report."
    }
  ]
}
```
