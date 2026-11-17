# Screening playbook

Read this before you plan the search of a screening run or propose a fact in one. A screening run's `run.json` says `screening: true`; it researches one startup for a first-pass investment memo. It replaces `capacity-moves-playbook.md` for such a run. Examples use invented names only (Example Robotics, Competitor R).

1. **The question.** What does the public evidence say about the startup's company, market, competition, team, traction and risks, and what would have to be true to invest?
   Why: every search and every fact serves this one question.

2. **Only general facts.** Every fact of a screening run is a `general` fact with `about_company` set. Propose no `capacity_move` fact, so its fields and `in_question` never apply.
   Why: a screening memo is about one company's business, not about production capacity.

3. **The time window.** A screening pack sets `time_window_months` to `120`, the most a pack allows, so that the founders' earlier work and the early funding rounds fall inside the window. Read the window from `radar check-pack --file PACK`. Log what falls outside with `radar log-excluded --run RUN --from-json FILE`, where the file holds `{"what": "Example Robotics founder's first company, 2012", "why": "outside the window"}`.
   Why: the same window makes runs comparable, and a startup's story starts with its founders.

4. **Where to search, in this order,** for the startup itself and then for each candidate from the pack:
   1. the startup's own site, news page and blog (`press_room`);
   2. the company register of its country (for example a commercial register, Companies House or SEC filings such as Form D) and its filings (`filings`);
   3. funding announcements and the pages of its investors (`press_room` of the investor, `trade_press`);
   4. trade press and interviews with the founders (`trade_press`);
   5. job postings (`job_postings`; rule 7);
   6. the competitors' own sites (`press_room`).
   Record each place searched with `radar log-search`. Never log in anywhere and never use a paid database: non-public material only enters as a file the person exports.
   Why: the company's own words come first, and the log shows what was covered.

5. **What to look for.** Each is a `general` fact, stated as the source states it:
   - the product: what it does and for whom;
   - customers, pilots and named users;
   - pricing and how the company earns money;
   - funding rounds: amount, date, stage and who invested;
   - the founders' and leaders' track records;
   - headcount and open roles;
   - revenue, growth or usage figures the company itself states;
   - partners and suppliers;
   - regulation, certifications and patents;
   - competitors, and how the company says it differs from them;
   - market claims, and who makes them.
   Why: these are the parts of a screening memo; a fact outside them rarely helps the partners.

6. **Claims are claims.** A market size, a growth rate or "the leading provider" is the claim of whoever states it. The fact says so ("Example Robotics states that ..."), and the source record names the speaker and their interest. The run never works out a market size of its own.
   Why: a startup's own figures are what it wants investors to read.

7. **Early signals.** Job postings and register entries without an announcement are early signals. Each becomes a `general` fact with `early_signal` true and `certainty` `tentative`, with a `tentative_reason` that names the kind of signal, such as: job posting, no announcement. The engine never confirms such a fact. The report shows them in their own block, "Early signals".
   Why: an open role hints at a plan; it does not announce one.

8. **A competitor on the pack's list is only a candidate.** It appears in the report only through facts. Pack content is hypotheses and search hints, never a fact.
   Why: a pack holds pointers, not evidence.

9. **Comparability.** Figures stay as stated, in the currency and unit stated. Never convert and never add figures up: a total raised appears only when a source states it.
   Why: a figure nobody stated is not a fact.
