# Capacity-moves playbook

Read this before you plan a search or propose a capacity-move fact. It says what to look for and which fields a fact has. Examples use invented names only (Example Pharma, Competitor A).

1. **The question.** Where are companies in this industry adding or removing production capacity, and what does the public evidence say that means for the company's choice?
   Why: every search and every fact serves this one question.

2. **A capacity move has these fields in `fields`.** Take each value as the source states it.
   - `company`, `what_added`, `announced`: required text. `announced` is the date the quote states for the announcement itself, not another date in the quote; else the source's date when the source is the party's own statement; else `not_stated`.
   - `move_type`: `new_site`, `expansion`, `acquisition`, `partnership` or `closure`.
   - `site`, `country`, `planned_start`: text, or left out.
   - `size_value`: a plain number as text, such as `"2.5"`. `size_unit`: the unit as stated, such as `lines`.
   - `stage`: `announced`, `under_construction`, `operating`, `cancelled` or `not_stated`.
   - `access`: `captive`, `open` or `not_stated`.
   - `delivery`: see rule 9.
   Use `not_stated` where the source does not say. Never infer captive or open. The stage is what a source states, not what you expect.
   Why: a guess in a field looks like a fact in the report.

3. **The time window.** Collect moves announced inside the pack's window, plus older announcements whose planned start still lies in the future. The window is 36 months unless the pack says otherwise. Read it from `radar check-pack --file PACK`; it prints the months and the first and last day. Log what falls outside with `radar log-excluded --run RUN --from-json FILE`, where the file holds `{"what": "Competitor A site announced in 2019", "why": "outside the window"}`.
   Why: the same window makes runs comparable.

4. **Where to search, in this order,** for the company itself and for each candidate from the pack:
   1. the company's own releases and investor pages (`investor_relations`, `press_room`);
   2. filings and annual reports (`filings`, `annual_reports`);
   3. regulators (`regulator`);
   4. trade press (`trade_press`);
   5. the early-signal places (`permits`, `job_postings`; rule 6).
   These are the place kinds a pack uses. A saved record of type `regulator_record` is always an early signal and follows rule 6. A company's own announcement found through a regulator's page is saved under its own type.
   Record each place searched with `radar log-search`.
   Why: the company's own words come first, and the log shows what was covered.

5. **Collect the company's own public moves first, in the same way.** They go on the same timeline and are marked as its own.
   Why: a competitor's move means little without the company's own position.

6. **Early signals.** Building permits and planning records, job postings and regulator records are early signals. Each becomes a `general` fact with `early_signal` true and `certainty` `tentative`. Give a `tentative_reason` that names the kind of signal, such as: building permit, no announcement. The engine refuses anything else, never confirms such a fact, and does not let it back another fact or enter `radar calc`. The report shows them marked and in their own block, "Early signals". The analysis has no key for them.
   Why: a permit hints at a move; it does not announce one.

7. **A baseline per competitor.** Collect size, sites and investment from the latest annual report or filing, each as a `general` fact. In the analysis they go in `baselines` as `{"company": ..., "fact_ids": [...]}`: at least one fact, no free text, and never an early signal. The report shows each fact's own checked statement.
   Why: a move is judged against the size of the company making it.

8. **A competitor on the pack's list is only a candidate.** It appears in the report only through facts. Pack content (names, places, vocabulary, industry text) is hypotheses and search hints, never a fact.
   Why: a pack holds pointers, not evidence.

9. **Announced versus delivered.** For each competitor, look for earlier announcements and for what a source says happened to them. Set `delivery` to `on_time`, `delayed` or `cancelled` only when a source says so. Otherwise use `not_yet` or `unknown`.
   Why: "late" is a claim, and it needs a source.

10. **Demand signals.** Use the pack's demand drivers as things to look for. Write what the evidence shows and label it a signal, never a forecast. A driver from the pack is a hypothesis until a source supports it.
    Why: a signal can be wrong, and a forecast must not look certain.

11. **Decision options.** For the pack's strategic question, set out what the public evidence says for and against each option. Then list the questions only the company can answer from the inside. Do not recommend one option.
    Why: the person decides; the report informs.

12. **Comparability.** Figures stay as stated. A total is made only from one unit, by `radar calc`. When figures use different units, say they cannot be compared. Never convert.
    Why: a converted figure is a figure nobody stated.

```json radar-constants
{
  "move_types": ["new_site", "expansion", "acquisition", "partnership", "closure"],
  "stages": ["announced", "under_construction", "operating", "cancelled", "not_stated"],
  "access": ["captive", "open", "not_stated"],
  "delivery": ["on_time", "delayed", "cancelled", "not_yet", "unknown"],
  "place_kinds": ["investor_relations", "press_room", "filings", "annual_reports", "regulator", "trade_press", "permits", "job_postings"],
  "time_window_months": 36
}
```
