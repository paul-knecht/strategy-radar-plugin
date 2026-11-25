"""The plain-text report: Markdown that reads well on GitHub.

`render_markdown` is pure. Text taken from sources, facts and the analysis is untrusted: it is escaped so it
cannot form a link, HTML or a table break. Engine words (statuses, reasons, step kinds, checkpoints, access
reasons, audit checks) are never shown: each is replaced by its label from `labels_en.json`.
"""
import re

from .. import store
from . import projects_view, visuals
from .model import (PROBABILITY_SCALE, access_reason_text, checkpoint_parts, count_label, fact_notes, field_label,
                    helpers_line, label, link_sentences, load_labels, reason_note, reason_text, split_early_signals,
                    unit_for)
from .numbers import shown
from .projects_view import ACCESS_SHOWN

EXTRA_COMPANIES = ("other", "none")   # the two company entries that are not one company
_SPECIAL = re.compile(r"([\\`*_\[\]<>|])")
_LINE_BREAKS = re.compile(r"\s*[\r\n\x0b\x0c\x85\u2028\u2029]+\s*")
_NUMBER_MARKER = re.compile(r"^(\d+)([.)])")
_AUTOLINK_SCHEME = re.compile(r"\b(https?|ftp):(?=//)", re.IGNORECASE)
_AUTOLINK_WWW = re.compile(r"\b(www)\.", re.IGNORECASE)
_PLAIN_URL = re.compile(r"https?://[^\s<>\\]+", re.IGNORECASE)


def esc(text, autolinks: bool = True) -> str:
    """Untrusted text made safe for one line of Markdown. `autolinks=False` is for text inside a link."""
    if text is None:
        return ""
    text = _SPECIAL.sub(r"\\\1", _LINE_BREAKS.sub(" ", str(text)))
    if autolinks:                                       # viewers that link bare addresses must not
        text = _AUTOLINK_SCHEME.sub(r"\1\\:", text)
        text = _AUTOLINK_WWW.sub(r"\1\\.", text)
    if text.startswith(("#", "-", "+", "~")):          # no heading, list or fence at the start of a line
        text = "\\" + text
    return _NUMBER_MARKER.sub(r"\1\\\2", text)


def _link(url) -> str:
    """A link only for http and https addresses; anything else is shown as escaped text."""
    if isinstance(url, str) and _PLAIN_URL.fullmatch(url):
        return f"[{esc(url, autolinks=False)}](<{url.replace('(', '%28').replace(')', '%29')}>)"
    return esc(url)


def _ref(fact: dict, labels: dict) -> str:
    """How the report refers to a fact: its id, with the uncertain or rejected label and, when its source is not
    public, the class label (see `fact_notes`). Every fact id in the report is written this way."""
    notes = [esc(text) for _, _, text in fact_notes(fact, labels)]
    return f"{esc(fact['id'])} ({', '.join(notes)})" if notes else esc(fact["id"])


def _refs(facts, labels: dict) -> str:
    return ", ".join(_ref(fact, labels) for fact in facts)


def _with_refs(text, facts, labels: dict) -> str:
    return f"{esc(text)} ({_refs(facts, labels)})" if facts else esc(text)


def _join(parts) -> str:
    return ", ".join(part for part in parts if part)


def _quote_block(fact: dict, labels: dict) -> list[str]:
    lines = [f"  > {esc(fact.get('quote'))}"]
    if fact.get("quote_translation"):
        lines.append(f"  > {labels['translation']}: {esc(fact['quote_translation'])}")
    return lines


def _source_line(source: dict | None, labels: dict) -> str:
    if not source:
        return ""
    if source.get("final_url"):   # the copy came from another address than the one asked for: show both
        addresses = [f"{labels['source_asked']}: {_link(source.get('url'))}",
                     f"{labels['source_saved_from']}: {_link(source.get('final_url'))}"]
    else:
        addresses = [_link(source.get("url"))]
    return _join([esc(source.get("title")), esc(source.get("publisher")), esc(source.get("date")), *addresses])


def _class_note(data_class, labels: dict) -> str:
    return f" ({labels.get('class_' + str(data_class), esc(data_class))})" if data_class not in (None, "public") else ""


def _status_line(model: dict, labels: dict) -> str:
    counts = model["status_line"]
    parts = [labels["includes_private"] if model["confidential"] else labels["public_only"],
             labels["read_until"].format(date=esc(model["sources_read_until"])),
             count_label(labels, "facts_checked", counts["confirmed"] + counts["uncertain"]).format(
                 n=counts["confirmed"] + counts["uncertain"]),
             labels["status_single_source"].format(n=counts["single_source"]),
             labels["uncertain"].format(n=counts["uncertain"] - counts["single_source"]),
             count_label(labels, "rejected", counts["rejected"]).format(n=counts["rejected"])]
    if counts["not_accessible"]:
        parts.append(f"{labels['not_accessible']}: {counts['not_accessible']}")
    return " · ".join(parts)


def _company_title(company: dict, labels: dict) -> str:
    """A company's heading: its name, or for the two entries that are not one company, their label."""
    if company.get("key") in EXTRA_COMPANIES:
        return labels[f"companies_{company['key']}"]
    return esc(company.get("name"))


def _company_name(company: dict, labels: dict) -> str:
    """A company by its own name, with the own-company mark; where it has no name, its heading."""
    return (esc(company["name"]) if company.get("name") else _company_title(company, labels)) + _home_mark(company, labels)


def _home_mark(company: dict, labels: dict) -> str:
    return f" ({labels['home_company']})" if company.get("home") else ""


def _shown_status(fact: dict, labels: dict) -> str:
    """The status a fact is shown with: "One source only" where that is the only reason it is not confirmed, else its
    own status."""
    shown = fact.get("shown_status") or fact.get("status")
    return labels.get(f"shown_{shown}", labels.get(f"status_{shown}", str(shown)))


def _grouping_note(model: dict, labels: dict) -> str:
    """What the answer rests on: the note that the grouping is a model's judgement, or, where the moves are not grouped,
    why each move counts as its own project."""
    state = model["projects"]["state"]
    return labels["answer_note"] if state == "grouped" else labels[f"answer_ungrouped_{state}"]


def _n(count, labels: dict) -> str:
    """A count with thousands separators."""
    return shown(str(count), labels["thousands_separator"])


def _answer(model: dict, labels: dict) -> list[str]:
    answer = model["core_answer"]
    if answer is None:
        return []
    lines = [f"## {labels['sec_answer']}", ""]
    lines += [f"- {labels[f'answer_{access}']}: {_n(answer[access], labels)}" for access in ACCESS_SHOWN] + [""]
    lines += [count_label(labels, "answer_total", answer["total"]).format(n=_n(answer["total"], labels)), ""]
    if answer["outside"]:   # the sentence names the moves, so a reader finds them in the facts
        sentence = count_label(labels, "answer_outside", answer["outside"]).format(n=_n(answer["outside"], labels))
        refs = _refs([fact for fact in model["facts"] if projects_view.outside(fact)], labels)
        lines += [f"{sentence.rstrip('.')} ({refs}).", ""]
    return lines + [_grouping_note(model, labels), "", labels["answer_rule"], ""]


def _companies(model: dict, labels: dict) -> list[str]:
    if not model["companies"]:
        return []
    lines = [f"## {labels['sec_companies']}", ""]
    for entry in model["companies"]:
        answer = entry.get("core_answer")
        head = f"- **{_company_title(entry, labels)}**{_home_mark(entry, labels)}: "
        if entry.get("only_connections"):
            lines.append(head + labels["company_only_connections"])
            continue
        if answer is None:   # no project: its number of facts, not a project count of zero
            facts = entry.get("facts") or 0
            lines.append(head + count_label(labels, "company_facts", facts).format(n=_n(facts, labels)))
            continue
        counts = ", ".join(f"{labels[f'answer_{access}']}: {_n(answer[access], labels)}" for access in ACCESS_SHOWN)
        total = count_label(labels, "answer_total", answer["total"]).format(n=_n(answer["total"], labels))
        lines.append(f"{head}{total}; {counts}")
    return lines + [""]


def _message_sources(message: dict, labels: dict) -> str:
    """The sources a message rests on, by publisher with the source id; the company's own statement is marked."""
    entries = []
    for source in message.get("sources") or []:
        publisher = source.get("publisher")
        marks = ([esc(source.get("id"))] if publisher else []) + ([labels["own_statement"]] if source.get("own") else [])
        name = esc(publisher or source.get("id"))
        entries.append(f"{name} ({', '.join(marks)})" if marks else name)
    return f"**{labels['message_sources']}**: {', '.join(entries)}" if entries else ""


def _messages(model: dict, labels: dict) -> list[str]:
    lines = [f"## {labels['sec_messages']}", ""]
    if not model["messages"]:
        return lines + [labels["no_facts"] if not model["facts"] else labels["none_messages"], ""]
    for message in model["messages"]:
        used = {fact["id"]: fact for step in message.get("chain") or [] for fact in step["facts"]}
        note = labels.get(f"confidence_{message.get('confidence')}", "")
        if used:
            note = f"{note} {labels['based_on']}: {', '.join(_ref(fact, labels) for fact in used.values())}".strip()
        lines += [f"- **{esc(message.get('text'))}**", ""]
        for text in (note, _message_sources(message, labels)):
            lines += [f"  {text}", ""] if text else []
        if message.get("flags"):
            lines += [f"  **{labels['message_checks']}**", ""]
            lines += [f"  - {_flag(flag, labels)}" for flag in message["flags"]] + [""]
    return lines


def _flag(flag: dict, labels: dict) -> str:
    return f"{esc(label(labels, 'audit_', flag.get('check'), store.AUDIT_CHECKS))}: {esc(flag.get('text'))}"


def _fact_block(first_line: str, fact: dict, labels: dict) -> list[str]:
    """A fact's bullet, then its quote and its source."""
    return [first_line, ""] + _quote_block(fact, labels) + ["", f"  {_source_line(fact.get('source'), labels)}", ""]


def _facts(model: dict, labels: dict) -> list[str]:
    lines = [f"## {labels['sec_facts']}", ""]
    if not model["facts"]:
        return lines + [labels["no_facts"], ""]
    others, early = split_early_signals(model["facts"])
    current = None
    for fact in others:
        company = fact.get("company") if isinstance(fact.get("company"), dict) else None
        if company is not None and company["key"] != current:
            current = company["key"]
            lines += [f"### {_company_title(company, labels)}{_home_mark(company, labels)}", ""]
        # a company outside the pack is named on its own line, since its heading is "Other companies"
        named = f"{esc(company['name'])}: " if company and company["key"] == "other" and company.get("name") else ""
        reason = reason_text(fact, labels)
        status = esc(_shown_status(fact, labels))
        lines += _fact_block(f"- {named}{esc(fact.get('statement'))}{_class_note(fact.get('data_class'), labels)}"
                             f" — {esc(fact.get('source_id'))}, {status}" + (f", {esc(reason)}" if reason else ""),
                             fact, labels)
    if early:
        lines += [f"### {labels['sec_early_signals']}", "", labels["early_signals_note"], ""]
        for fact in early:   # named by the shared fact reference, which carries the uncertain and class labels
            reason = reason_text(fact, labels)
            lines += _fact_block(f"- {esc(fact.get('statement'))} — {_ref(fact, labels)}, {esc(fact.get('source_id'))}"
                                 + (f", {esc(reason)}" if reason else ""), fact, labels)
    return lines


def _total(calculation: dict, labels: dict) -> str:
    unit, result = calculation.get("unit"), esc(shown(calculation.get("result"), labels["thousands_separator"]))
    if calculation.get("operation") == "share":
        text = f"{esc(calculation.get('label'))}: {result}%"
    else:
        text = (f"{esc(calculation.get('label'))}: {result}"
                + (f" {esc(unit_for(calculation.get('result'), unit))}" if unit else ""))
    inputs = _refs(calculation["inputs"], labels) + (f" / {_refs(calculation['whole'], labels)}"
                                                     if calculation["whole"] else "")
    return f"- {text} ({inputs})"


def _count_table(heading: str, columns: list[str], rows: list[tuple[str, list[dict]]], labels: dict) -> list[str]:
    """A Markdown table of counts; a cell with no facts is empty, and one that includes uncertain or non-public facts says so."""
    def cell(tally: dict) -> str:
        notes = visuals.tally_notes(tally, labels)
        return (f"{tally['n']} ({', '.join(notes)})" if notes else str(tally["n"])) if tally["n"] else ""

    def line(cells: list[str]) -> str:
        return "|" + "|".join(f" {text} " for text in cells) + "|"

    lines = [f"### {heading}", "", line([labels["col_company"]] + columns), line(["---"] + ["---:"] * len(columns))]
    lines += [line([esc(company)] + [cell(tally) for tally in tallies]) for company, tallies in rows]
    return lines + [""]


def _spread(item: dict, labels: dict) -> str:
    """What the reports of a project say, per value with how many say it (the count only for more than one report), on
    one line: site, country, stage, planned start and what was added."""
    several = len(item["facts"]) > 1
    shown = []
    for name, key, field in (("site", "field_site", None), ("countries", "field_country", None),
                             ("stage", "field_stage", "stage"), ("planned_start", "field_planned_start", "planned_start"),
                             ("what", "field_what_added", None)):
        values = [esc(field_label(field, value, labels) if field else value) + (f" ({number})" if several else "")
                  for value, number in item["spread"].get(name) or []]
        if values:
            shown.append(f"{labels[key]}: {', '.join(values)}")
    return " · ".join(shown)


def _counts(counts: dict, labels: dict) -> str:
    pills = [(counts["confirmed"], labels["project_confirmed"]), (counts["single_source"], labels["status_single_source"]),
             (counts["uncertain"], labels["project_uncertain"])]
    return ", ".join(text.format(n=number) for number, text in pills if number)


def _report(fact: dict, labels: dict) -> str:
    """One report of a project: its stage and statement, its size as stated, its reference with the announcement date,
    and its source with the date."""
    fields = fact.get("fields") if isinstance(fact.get("fields"), dict) else {}
    stage = labels.get(f"stage_{fields.get('stage')}", labels["stage_not_stated"])
    announced = fields.get("announced")
    when = (f", {labels['date_announced_not_stated']}" if announced == "not_stated"
            else f", {esc(announced)}" if announced else "")
    source = fact.get("source") if isinstance(fact.get("source"), dict) else {}
    size = visuals.stated_size(fact, labels["thousands_separator"])
    return (f"- {stage}: {esc(fact.get('statement'))}" + (f" ({esc(size)})" if size else "")
            + f" ({_ref(fact, labels)}{when}) — "
            + _join([esc(source.get("publisher") or fact.get("source_id")), esc(fact.get("date"))]))


def _projects(model: dict, labels: dict) -> list[str]:
    items = model["projects"]["items"]
    baselines = [group for group in model["competitors"] if group["baseline"]]
    grid = visuals.move_counts(model["facts"])
    delivery = visuals.delivery_counts(model["facts"])
    if not (items or baselines or grid or delivery or model["calculations"]):
        return []
    lines = [f"## {labels['sec_projects']}", ""]
    if items and model["projects"]["state"] != "grouped":
        lines += [_grouping_note(model, labels), ""]
    for item in items:
        company = item["company"]
        lines += [f"### {esc(item['name'])}", "",
                  " · ".join(part for part in (_company_name(company, labels), labels[f"answer_{item['access']}"],
                                               _counts(item["counts"], labels)) if part), ""]
        spread = _spread(item, labels)
        lines += [spread, ""] if spread else []
        lines += [f"**{labels['col_reports']}**", ""] + [_report(fact, labels) for fact in item["facts"]] + [""]
    for group in baselines:
        mark = f" ({labels['home_company']})" if group["home"] else ""
        lines += [f"### {esc(group['company'])}{mark} — {labels['baseline']}", ""]
        # no wording of its own: each fact's checked statement, named by the shared fact reference
        lines += [f"- {_with_refs(fact.get('statement'), [fact], labels)}" for fact in group["baseline"]] + [""]
    if grid:
        lines += _count_table(labels["sec_grid"], [labels[f"move_{move}"] for move in store.MOVE_TYPES], grid, labels)
    if delivery:
        lines += _count_table(labels["sec_delivery"], [labels[f"delivery_{outcome}"] for outcome in visuals.DELIVERY_OUTCOMES],
                              delivery, labels)
    if model["calculations"]:
        lines += [f"### {labels['sec_totals']}", ""]
        for calculation in model["calculations"]:
            note = f" — {labels['includes_uncertain']}" if calculation["includes_uncertain"] else ""
            lines.append(_total(calculation, labels) + note)
        lines.append("")
    return lines


def _connections(model: dict, labels: dict) -> list[str]:
    if not model["connections"]:
        return []
    columns = ("col_company", "col_tie", "col_party", "col_status", "col_fact")

    def line(cells: list[str]) -> str:
        return "|" + "|".join(f" {text} " for text in cells) + "|"

    lines = [f"## {labels['sec_connections']}", "", line([labels[key] for key in columns]),
             line(["---"] * len(columns))]
    for connection in model["connections"]:
        fact, company = connection["fact"], connection["company"]
        description = connection.get("description")
        if connection.get("party_name"):
            party = esc(connection["party_name"]) + (f" ({esc(description)})" if description else "")
        else:
            party = (esc(labels["party_not_named"].format(description=description)) if description
                     else labels["party_not_named_plain"])
        tie = label(labels, "tie_", connection.get("tie"), store.CONNECTION_TIES)
        lines.append(line([_company_name(company, labels), esc(tie), party, esc(_shown_status(fact, labels)),
                           _ref(fact, labels)]))
    return lines + [""]


def _demand(model: dict, labels: dict) -> list[str]:
    if not model["demand_signals"]:
        return []
    return [f"## {labels['sec_demand']}", ""] + \
        [f"- {_with_refs(signal.get('text'), signal['facts'], labels)}" for signal in model["demand_signals"]] + [""]


def _points(prefix: str, points: list, labels: dict) -> list[str]:
    return [f"- **{prefix}** {_with_refs(point.get('text'), point['facts'], labels)}" for point in points]


def _options(model: dict, labels: dict) -> list[str]:
    options = model["decision_options"] or {}
    if not (options.get("options") or options.get("internal_questions") or model["watch_items"]):
        return []
    lines = [f"## {labels['sec_options']}", ""]
    if options.get("options") or options.get("internal_questions"):
        lines += [f"**{esc(options.get('question'))}**", ""]
        framing = labels.get(f"framing_{options.get('framing')}", "")
        if framing:
            lines += [f"{framing} {_refs(options['framing_facts'], labels)}".strip(), ""]
    for option in options.get("options") or []:
        lines += [f"### {esc(option.get('name'))}", ""]
        lines += _points("+", option.get("for") or [], labels) + _points("−", option.get("against") or [], labels) + [""]
    if options.get("internal_questions"):
        lines += [f"### {labels['internal_questions']}", ""]
        lines += [f"- {esc(question)}" for question in options["internal_questions"]] + [""]
    if model["watch_items"]:
        lines += [f"### {labels['sec_watch']}", ""]
        lines += [f"- {esc(item.get('text'))} — {esc(item.get('trigger'))}" for item in model["watch_items"]] + [""]
    return lines


def _judgement(model: dict, labels: dict) -> list[str]:
    if not model["scenarios"] and not model["assumptions"]:
        return []
    lines = [f"## {labels['sec_scenarios']}", "", labels["judgement"], ""]
    for scenario in model["scenarios"]:
        lines += [f"### {esc(scenario.get('name'))}", "", esc(scenario.get("description")), ""]
        if scenario["assumptions"]:
            lines += [f"{labels['based_on']}: {', '.join(a['id'] for a in scenario['assumptions'])}", ""]
        lines += [f"- {_with_refs(signpost.get('text'), signpost['facts'], labels)}"
                  for signpost in scenario["signposts"]] + [""]
    for assumption in model["assumptions"]:
        evidence = f"; {_refs(assumption['facts'], labels)}" if assumption["facts"] else ""
        lines.append(f"- {assumption['id']}: {esc(assumption.get('text'))} ({assumption['support_label']}{evidence})"
                     f" → {esc(assumption.get('if_wrong'))}")
    return lines + [""]


def _predictions(model: dict, labels: dict) -> list[str]:
    if not model["predictions"]:
        return []
    lines = [f"## {labels['sec_predictions']}", ""]
    for p in model["predictions"]:
        lines.append(f"- {esc(p.get('statement'))}, by {esc(p.get('by'))}: {p['probability']}% ({p['word']})"
                     f" — {esc(p.get('resolves_when'))}")
    return lines + [""]


def _checks(model: dict, labels: dict) -> list[str]:
    if not model["audit_flags"]:
        return []
    return [f"## {labels['sec_checks']}", ""] + \
        [f"- {_flag(flag, labels)}" for flag in model["audit_flags"]] + [""]


def _not_confirmed(model: dict, labels: dict) -> list[str]:
    if not (model["not_found"] or model["contradictions"] or model["rejected"]):
        return []
    lines = [f"## {labels['sec_not_confirmed']}", ""]
    lines += [f"- {esc(text)}" for text in model["not_found"]]
    lines += [f"- {_with_refs(item.get('text'), item['facts'], labels)}" for item in model["contradictions"]]
    if model["not_found"] or model["contradictions"]:
        lines.append("")
    if model["rejected"]:
        lines += [f"### {count_label(labels, 'rejected', len(model['rejected'])).format(n=len(model['rejected']))}", ""]
        for fact in model["rejected"]:
            lines += [f"- {esc(fact.get('statement'))}{_class_note(fact.get('data_class'), labels)}"
                      f" — {esc(fact.get('source_id'))}, {labels['status_rejected']}: {esc(reason_text(fact, labels))}", ""]
            note = reason_note(fact, labels)
            if note:
                lines += [f"  {esc(note[0])}: {esc(note[1])}", ""]
            lines += _quote_block(fact, labels) + [""]
    return lines


def _thinking(model: dict, labels: dict) -> list[str]:
    if not model["messages"] and not model["lenses"]:
        return []
    lines = [f"## {labels['sec_thinking']}", ""]
    for message in model["messages"]:
        lines += [f"### {esc(message.get('text'))}", ""]
        for number, step in enumerate(message.get("chain") or [], start=1):
            marks = [_ref(fact, labels) for fact in step["facts"]] + ([esc(step["lens"]["name"])] if step["lens"] else [])
            tail = f" ({', '.join(marks)})" if marks else ""
            kind = label(labels, "step_", step.get("kind"), store.STEP_KINDS)
            lines.append(f"{number}. {esc(kind)}: {esc(step.get('text'))}{tail}")
        lines += ["", f"- {labels['counter_view']}: {esc(message.get('counter_view'))}",
                  f"- {labels['would_change']}: {esc(message.get('would_change'))}"]
        outside = message.get("outside_view")
        if isinstance(outside, dict):
            lines.append(f"- {labels['outside_view']}: {_with_refs(outside.get('text'), outside['facts'], labels)}")
        lines.append("")
    for lens in model["lenses"]:
        lines += [f"### {esc(lens.get('name'))}", ""]
        for key in ("idea", "suggests", "limits", "competing_idea"):
            if lens.get(key):
                lines += [f"**{labels['lens_' + key]}.** {esc(lens[key])}", ""]
        if lens.get("here"):
            lines += [esc(lens["here"]), ""]
        lines += [f"**{labels['lens_questions']}**", ""]
        lines += [f"- {esc(question)}" for question in lens.get("questions") or []] + [""]
        for original in lens.get("originals") or []:
            level = labels.get(f"level_{original.get('level')}", esc(original.get("level")))
            about = f"{labels['original_about']} {esc(original['about'])}" if original.get("about") else ""
            lines.append(f"- {_join([esc(original.get('reference')), about, level, _link(original.get('link')) if original.get('link') else ''])}")
        if lens.get("rests_on"):
            lines.append(f"- {esc(lens['rests_on'])}")
        lines.append("")
    return lines


def _sources(model: dict, labels: dict) -> list[str]:
    lines = [f"## {labels['sec_sources']}", ""]
    facts = {fact["id"]: fact for fact in model["facts"] + model["rejected"]}
    for source in model["sources"]:
        lines += [f"### {source['id']}: {esc(source.get('title'))}", "",
                  _source_line({**source, "title": None}, labels), ""]
        notes = []
        if source.get("data_class") not in (None, "public"):
            notes.append(labels.get(f"class_{source['data_class']}", esc(source["data_class"])))
        if source.get("access") == "not_accessible":
            notes.append(f"{labels['not_accessible']}: {esc(access_reason_text(source.get('access_reason'), labels))}")
        elif source.get("text_note") == store.LITTLE_RUNNING_TEXT:   # saved, but its article may be missing
            notes.append(f"{labels['little_running_text']}: {labels['text_note_little_running_text']}")
        if source.get("saved_by") == "hand":
            notes.append(labels["saved_by_hand"])
        if notes:
            lines += [f"- {note}" for note in notes]
        lines += [f"- {labels['source_speaker']}: {esc(source.get('speaker'))}",
                  f"- {labels['source_interest']}: {esc(source.get('interest'))}",
                  f"- {labels['source_saved']}: {esc(source.get('saved_at'))}"]
        if source.get("based_on"):
            lines.append(f"- {labels['based_on']}: {', '.join(esc(s) for s in source['based_on'])}")
        provenance = source.get("provenance")
        if isinstance(provenance, dict):
            lines += [f"- {labels['supplied_by']}: {esc(provenance.get('supplied_by'))}",
                      f"- {labels['basis']}: {esc(provenance.get('basis'))}"]
        lines.append("")
        for quote in source["quotes"]:
            fact = facts.get(quote["fact_id"])
            lines += [f"> {esc(quote['quote'])} ({_ref(fact, labels) if fact else esc(quote['fact_id'])})"]
            if quote.get("translation"):
                lines.append(f"> {labels['translation']}: {esc(quote['translation'])}")
            lines.append("")
    return lines


def _recommendation(found, labels: dict) -> list[str]:
    """The lens recommendation as it was made, labelled as advice that nobody checked; or, when the run holds none,
    the fixed sentence that says so. A damaged one shows what can still be read, with each damaged part marked."""
    lines = [f"### {labels['rec_heading']}", ""]
    if not found:
        return lines + [labels["rec_none"], ""]
    if found.get("damaged") and not found.get("entries") and not found.get("note"):
        return lines + [labels["rec_damaged"], ""]
    lines += [f"**{labels['rec_label']}**", ""]
    if found.get("damaged"):
        lines += [labels["rec_damaged_parts"], ""]
        lines += [f"- {esc(flag)}" for flag in found.get("flags") or []]
        lines += [""] if found.get("flags") else []
    if found.get("stale"):
        lines += [labels["rec_stale"], ""]
    if found.get("note"):
        lines += [esc(found["note"]), ""]
    for entry in found.get("entries") or []:
        facts = ", ".join(_ref(link["fact"], labels) for link in entry["links"])
        lines.append(f"- **{esc(entry['name'])}**")
        lines += [f"  - {esc(flag)}" for flag in entry.get("flags") or []]
        lines += [f"  - {labels['rec_part']}: {esc(entry['question_part'])}"] if entry["question_part"] is not None else []
        lines += [f"  - {labels['rec_why']}: {esc(entry['why'])}"] if entry["why"] is not None else []
        lines += [f"  - {labels['rec_facts']}: {facts}"] if facts else []
        lines += [f"  - {labels['rec_missing']}: {esc(entry['missing'])}"] if entry["missing"] is not None else []
        for link in entry["links"]:
            lines.append(f"  - {_ref(link['fact'], labels)}: "
                         + " ".join(esc(sentence) for sentence in link_sentences(link, labels)))
        lines.append("")
    line = helpers_line(found, labels) if found.get("entries") else ""
    return lines + ([esc(line), ""] if line else [])


def _how_made(model: dict, labels: dict) -> list[str]:
    how = model["how_made"]
    lines = [f"## {labels['sec_how_made']}", ""]
    if how["search_log"]:
        lines += [f"### {labels['how_searched']}", ""]
        lines += [f"- {esc(item.get('place'))}: {esc(item.get('result'))}" for item in how["search_log"]] + [""]
    if how["excluded"]:
        lines += [f"### {labels['how_excluded']}", ""]
        lines += [f"- {esc(item.get('what'))}: {esc(item.get('why'))}" for item in how["excluded"]] + [""]
    if how["checkpoints"] or how.get("private_acknowledged"):
        lines += [f"### {labels['how_checkpoints']}", ""]
        if how.get("private_acknowledged"):
            lines.append(f"- {labels['private_acknowledged']}: {esc(how.get('private_acknowledged'))}")
        for item in how["checkpoints"]:
            name = label(labels, "checkpoint_", item.get("name"), store.CHECKPOINTS)
            lines.append(f"- {esc(name)}: " + ": ".join(esc(part) for part in checkpoint_parts(item, labels)))
        lines.append("")
    if model["projects"]["items"]:
        lines += [f"### {labels['how_counting']}", "", _grouping_note(model, labels), "", labels["answer_rule"], ""]
    dropped = how.get("names_dropped") or {}
    if dropped.get("companies") or dropped.get("parties"):
        lines += [labels["names_dropped"].format(companies=dropped.get("companies", 0),
                                                 parties=dropped.get("parties", 0)), ""]
    lines += _recommendation(how.get("recommendation"), labels)
    lines += [model["compliance"], "", f"### {labels['sec_legend']}", ""]
    lines += [f"- {labels[f'confidence_{level}']}" for level in ("high", "medium", "low")] + [""]
    lines += [f"- {span}%: {labels[key]}" for _, span, key in PROBABILITY_SCALE] + [""]
    return lines


def spaced(*parts) -> str:
    return " ".join(part for part in parts if part)


def _changes(model: dict, labels: dict) -> list[str]:
    if model["changes"] is None:
        return []
    data = visuals.read_changes(model["changes"])
    facts = {fact["id"]: fact for fact in model["facts"] + model["rejected"]}

    def current(fact_id) -> str:
        fact = facts.get(fact_id)
        return f"{_ref(fact, labels)} {esc(visuals.describe(fact))}".strip() if fact else esc(fact_id)

    def earlier(fact_id) -> str:
        return labels["changes_earlier"].format(id=esc(fact_id))

    def values(name, value) -> str:
        return esc(visuals.field_value(name, value, labels))

    lines = [f"## {labels['sec_changes']}", ""]
    if data["compared"]:
        lines += [labels["changes_compared"].format(previous=esc(data["compared"][0]), current=esc(data["compared"][1])), ""]

    def section(key: str, items: list[str], note: str = "") -> None:
        if items:
            lines.extend([f"### {labels['changes_' + key]}", ""] + ([note, ""] if note else []) + items + [""])

    changed = []
    for entry in data["changed"]:
        changed.append("- " + spaced(current(entry["fact_id"]), earlier(entry["previous_fact_id"]) if entry["previous_fact_id"] else ""))
        changed += [f"  - {esc(visuals.field_name(name, labels))}: {values(name, before)} {visuals.ARROW} {values(name, after)}"
                    for name, before, after in entry["fields"]]
    section("new", [f"- {current(fact_id)}" for fact_id in data["new"]])
    section("changed", changed)
    section("source_changed", ["- " + spaced(current(entry["fact_id"]), _link(entry["url"]) if entry["url"] else "")
                               for entry in data["source_changed"]])
    section("source_unavailable", ["- " + spaced(earlier(entry["previous_fact_id"]), _link(entry["url"]) if entry["url"] else "")
                                   for entry in data["source_unavailable"]])
    section("not_found_again", [f"- {earlier(fact_id)}" for fact_id in data["not_found_again"]], labels["changes_not_found_note"])
    section("possible_matches", [f"- {current(entry['fact_id'])} {labels['changes_may_match']} {earlier(entry['previous_fact_id'])}. "
                                 f"{labels['changes_differs_in']}: {esc(visuals.field_name(entry['differing_field'] or '', labels))}."
                                 for entry in data["possible_matches"]])
    section("predictions_due", [f"- {esc(entry['prediction_id'])}: "
                                + labels["changes_due_form"].format(statement=esc(entry["statement"]), by=esc(entry["by"]))
                                for entry in data["predictions_due"]])
    if data["unchanged"] is not None:
        lines += [labels["changes_unchanged"].format(n=data["unchanged"]), ""]
    return lines


def render_markdown(model: dict) -> str:
    labels = load_labels()
    lines = [f"# {esc(model['question'])}", ""]
    if model["confidential"]:
        lines += [f"**{labels['confidential']}**", ""]
    if model["illustrative"]:
        lines += [f"**{labels['illustrative']}**", ""]
    lines += [_status_line(model, labels), "", labels["built_on"].format(date=esc(model["built_on"])), "",
              labels["disclaimer_private"] if model["confidential"] else labels["disclaimer"], ""]
    lines += [labels["unattended_lenses" if name == "lenses" else "unattended_final"] + "\n" for name in model.get("unattended", [])]
    for section in (_answer, _companies, _messages, _facts, _projects, _connections, _demand, _options, _judgement,
                    _predictions, _checks, _not_confirmed, _thinking, _sources, _how_made, _changes):
        lines += section(model, labels)
    return "\n".join(lines).rstrip("\n") + "\n"
