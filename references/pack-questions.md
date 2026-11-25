# The pack questions

new-pack asks these when the company is invented for practice, and for a real company when no web search tool is available or the search finds nothing. The three questions new-pack has already asked (the company, whether it is real, and the strategic question) are not asked again.

The rules of new-pack hold here as well: one question per message, and every name, address and word comes from the person's messages, word for word where the format takes free text. Every name is entered as the person gave it: `status` is `candidate` and `suggested_by` is `user`.

Ask: "In your own words, what industry is it in?"
Stop here. End your turn after the question. Do not call any tool, and do not answer for the person. Only the person's next message can answer.
The answer is `industry`.

Ask: "Which companies compete with it, and which other companies should be watched? If a company, your own included, is also known by another name, such as an older name or a group name, add that name after it. You can leave this out."
Stop here. End your turn after the question. Do not call any tool, and do not answer for the person. Only the person's next message can answer.
The first group goes to `competitors`, the second to `watch`, each as `name`, `status` and `suggested_by`. Other names the person gives for a company go to its `other_names`: for the company asked about first, at the top level of the pack, and for each of these, in its own entry. Take them as given, one text for each name. When the person gives none, or says "I don't know", leave `other_names` out; never suggest one from your own knowledge.

Ask: "Where should a run look? Give each page by name and address: the company's and each competitor's press and investor pages, regulators, trade press, places for permits and job postings."
Stop here. End your turn after the question. Do not call any tool, and do not answer for the person. Only the person's next message can answer.
Each is an entry of `places` with `kind`, `name` and `url`. The `kind` is one of `investor_relations`, `press_room`, `filings`, `annual_reports`, `regulator`, `trade_press`, `permits`, `job_postings`; take it from the person's description, and ask when it is not clear.

Ask: "Which units and special words does the industry use, and in which languages do sources appear?"
Stop here. End your turn after the question. Do not call any tool, and do not answer for the person. Only the person's next message can answer.
Units go to `units`, words with their meaning to `vocabulary` (`term`, `meaning`), languages to `languages`. These are the person's hints, not facts.

Ask: "What do you think drives demand for this industry's products?"
Stop here. End your turn after the question. Do not call any tool, and do not answer for the person. Only the person's next message can answer.
Each answer is one entry of `demand_drivers`: a hypothesis, not a fact.

Ask: "How far back should a run search? The usual choice is the last 36 months. Say a number of months from 1 to 120, or keep 36."
Stop here. End your turn after the question. Do not call any tool, and do not answer for the person. Only the person's next message can answer.
The answer is `time_window_months`. The window is 36 months unless the person wants another.

Then go on with the part of new-pack headed "After the last answer".
