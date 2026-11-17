# The screening memo

Read this with `analysis-format.md` before you write `analysis.json` for a run whose `run.json` says `screening: true`. Every rule of `analysis-format.md` holds; this file says how a screening memo fills its sections. Examples use invented names only (Example Robotics, Investor Q).

## What the memo is

A first-pass investment memo on one startup. It prepares the investors' decision and does not make it: no "invest" or "pass", no score, no ranking. It shows what the public evidence says about six parts of the startup, what would have to be true to invest, and what is still open.

## The sections

- `messages`: the memo's findings. Each has `memo_part`, one of `company`, `market`, `competition`, `team`, `traction` or `risks`. The report shows the findings under these six headings, in this order, and a finding without a part under "Other findings". Write at least one finding for each part the facts speak to; a part with no fact gets no finding, and its gap goes into `not_found`.
- `demand_signals`: traction and demand signals, each marked as a signal and never as a forecast.
- `decision_options`: what would have to be true to invest. `question` is "What would have to be true to invest in <startup>?", or the person's own question; `framing` is `user`. Each option is one condition, such as "Pilot customers convert to paying contracts", with the evidence `for` and `against` it. Never a verdict on the conditions.
- `internal_questions` of the decision options: the questions only the founders can answer. The report shows them as questions only the company can answer.
- `not_found`: what public sources did not answer. The report shows these as the open questions for the partner meeting.
- `watch_items`, `assumptions`, `scenarios`, `predictions`, `contradictions`, `lens_notes` and `audit_flags`: as `analysis-format.md` says.

## Figures in a memo

- **Market size.** Rule 5's "no market-size number" means no market size of your own. A market figure a source states stays inside the fact that quotes it, as rule 4 says for every figure, and the fact names who claims it.
- **No totals.** `radar calc` adds only the sizes of capacity moves, so a screening memo has no totals, counts or shares of its own. A total raised appears only when a source states it, as a fact.
- **Money in open questions.** A `not_found` sentence that uses a money word, such as funding, valuation, pricing or value, must name the confirmed facts that state an amount and say why they do not answer it. The gate refuses it otherwise. Write "The valuation of the seed round is not stated: F1 gives only the amount raised." and not "The valuation is unknown."
- **Money anywhere else.** The same holds for every other text of the memo, a finding's reasoning or a condition's evidence too: a text that says an amount is missing must name a confirmed amount fact, in the text or in its item's fact ids, and say why it does not answer.
- **No figure of your own.** A lens never licenses a computed figure: the memo works out no runway, no profit per customer and no other figure; it shows only figures a source states.

## Example

The shape only; every word of a real memo comes from its own facts.

```json screening-example
{
  "messages": [
    {"id": "M1", "memo_part": "traction", "text": "Example Robotics has raised a seed round from a named lead investor.",
     "confidence": "medium",
     "chain": [{"kind": "fact", "text": "The company states a seed round of 12 million euros.", "fact_ids": ["F1"], "lens_id": null},
               {"kind": "conclusion", "text": "An outside investor has backed the company once.", "fact_ids": [], "lens_id": null}],
     "counter_view": "A seed round shows that an investor believed the plan, not that customers buy the product.",
     "would_change": "A report that the round was not closed.",
     "outside_view": {"text": "None found: no fact of this run states how such rounds usually turn out.", "fact_ids": []}},
    {"id": "M2", "memo_part": "team", "text": "The founders have built and sold a company before.",
     "confidence": "medium",
     "chain": [{"kind": "fact", "text": "The company states the founders sold a logistics software company.", "fact_ids": ["F2"], "lens_id": null},
               {"kind": "conclusion", "text": "The team has taken one company to a sale.", "fact_ids": [], "lens_id": null}],
     "counter_view": "One earlier sale in another field says little about this market.",
     "would_change": "A source that the earlier company was sold at a loss.",
     "outside_view": {"text": "None found: no fact of this run states how such teams usually fare.", "fact_ids": []}}
  ],
  "decision_options": {
    "question": "What would have to be true to invest in Example Robotics?",
    "framing": "user",
    "framing_fact_ids": [],
    "options": [
      {"name": "Pilot customers convert to paying contracts",
       "for": [{"text": "The round suggests an investor saw early demand.", "fact_ids": ["F1"]}],
       "against": [{"text": "No source we read names a paying customer.", "fact_ids": []}]},
      {"name": "The founders' earlier experience carries over",
       "for": [{"text": "They have sold a software company before.", "fact_ids": ["F2"]}],
       "against": [{"text": "No source we read shows earlier work with robots.", "fact_ids": []}]}
    ],
    "internal_questions": ["How many pilots are under contract, and on what terms?"]
  },
  "not_found": ["The valuation of the seed round is not stated: F1 gives only the amount raised.",
                "No source we read names a paying customer."]
}
```
