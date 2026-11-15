"""The interactive report: one self-contained HTML page with three levels of depth.

Level 1 is the key messages, level 2 the reasoning behind each one, level 3 one page per source.
`render_html` is pure. Everything that comes from the model is untrusted text, and it reaches the page
through `esc` and nothing else: no model text goes into the script, the style sheet, an event-handler
attribute or an unquoted attribute. Fixed text comes from `labels_en.json`, and engine words (statuses,
reasons, step kinds, checkpoints, access reasons, audit checks) are always shown by their label. `esc` and the
small parts shared with the visuals (pills, fact links, addresses) are defined in `visuals.py`, so there is one
escaping path.
"""
import re
from pathlib import Path

from .. import store, verify
from . import visuals
from .model import (PROBABILITY_SCALE, access_reason_text, checkpoint_parts, count_label, field_label, label,
                    load_labels, reason_note, reason_text, split_early_signals, unit_for)
from .visuals import esc, join as _join, token as _token

_HERE = Path(__file__).parent
_LANG = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*")
_VIEWS = (("summary", "sec_summary"), ("facts", "sec_facts"), ("competitors", "sec_competitors"),
          ("timeline", "sec_timeline"), ("scenarios", "sec_scenarios"), ("options", "sec_options"),
          ("checks", "sec_checks"), ("thinking", "sec_thinking"), ("sources", "sec_sources"),
          ("how", "sec_how_made"))


def _lang(value) -> str:
    return f' lang="{esc(value)}"' if isinstance(value, str) and _LANG.fullmatch(value) else ""


class _Page:
    def __init__(self, model: dict):
        self.model = model
        self.labels = load_labels()
        self.sources = {source["id"]: source for source in model["sources"]}
        self.facts = {fact["id"]: fact for fact in model["facts"] + model["rejected"]}

    # --- fixed text and small parts ---

    def t(self, key: str) -> str:
        """A label, escaped. A missing key gives nothing."""
        return esc(self.labels.get(key, ""))

    def fmt(self, key: str, **values) -> str:
        """A label with `{placeholders}` filled from escaped values."""
        return esc(self.labels[key]).format(**{name: esc(value) for name, value in values.items()})

    def count(self, key: str, n) -> str:
        """A label for a count of `n`, in its singular form for exactly one where it has one."""
        return esc(count_label(self.labels, key, n)).format(n=esc(n))

    def pill(self, css: str, text) -> str:
        return visuals.pill(css, text)

    def class_pill(self, data_class) -> str:
        return visuals.class_pill(data_class, self.labels)

    def fact_ref(self, fact: dict) -> str:
        return visuals.fact_ref(fact, self.labels)

    def refs(self, facts) -> str:
        return " ".join(self.fact_ref(fact) for fact in facts or [])

    def with_refs(self, text, facts) -> str:
        return _join([esc(text), self.refs(facts)])

    def source_link(self, source_id, text=None) -> str:
        source = self.sources.get(source_id)
        if source is None:
            return esc(text if text is not None else source_id)
        link = f'<a href="#{esc(source_id)}" data-view="sources">{esc(text if text is not None else source_id)}</a>'
        return link + self.class_pill(source.get("data_class"))

    def address(self, url) -> str:
        return visuals.address(url)

    def quote(self, text, translation=None, lang=None) -> str:
        block = f"<blockquote{_lang(lang)}>{esc(text)}</blockquote>"
        if translation:
            block += f'<p class="translation">{self.t("translation")}: {esc(translation)}</p>'
        return block

    def listing(self, items, css="") -> str:
        items = [item for item in items if item]
        if not items:
            return ""
        attribute = f' class="{esc(css)}"' if css else ""
        return f"<ul{attribute}>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>"

    def nothing(self) -> str:
        return f'<p class="none">{self.t("none_here")}</p>'

    def reason(self, fact: dict, tag: str = "p") -> str:
        """Why a fact has its status, in words, with the checker's note or the analyst's reason where there is one."""
        text = reason_text(fact, self.labels)
        note = reason_note(fact, self.labels)
        parts = [f'<{tag} class="reason">{esc(text)}</{tag}>' if text else "",
                 f'<{tag} class="reason-note">{esc(note[0])}: {esc(note[1])}</{tag}>' if note else ""]
        return _join(parts)

    # --- level 1 and 2: the key messages and the reasoning behind them ---

    def message(self, message: dict) -> str:
        confidence = message.get("confidence")
        short = self.labels.get(f"confidence_short_{confidence}")
        pill = self.pill(f"confidence-{_token(confidence)}", short) if short else ""
        steps = []
        for step in message.get("chain") or []:
            kind = _token(step.get("kind"))
            lens = step.get("lens")
            lens_link = (f'<a class="lens" href="#lens-{esc(lens["id"])}" data-view="thinking">{esc(lens["name"])}</a>'
                         if isinstance(lens, dict) else "")
            kind_label = label(self.labels, "step_", step.get("kind"), store.STEP_KINDS)
            steps.append(f'<li class="step {esc(kind)}"><span class="step-kind">{esc(kind_label)}</span> '
                         + _join([esc(step.get("text")), self.refs(step.get("facts")), lens_link]) + "</li>")
        blocks = []
        for css, key, text in (("counter-view", "counter_view", message.get("counter_view")),
                               ("would-change", "would_change", message.get("would_change"))):
            if text:
                blocks.append(f'<div class="{css}"><h4>{self.t(key)}</h4><p>{esc(text)}</p></div>')
        outside = message.get("outside_view")
        if isinstance(outside, dict):
            blocks.append(f'<div class="outside-view"><h4>{self.t("outside_view")}</h4>'
                          f'<p>{self.with_refs(outside.get("text"), outside.get("facts"))}</p></div>')
        note = self.labels.get(f"confidence_{confidence}")
        return (f'<details class="message" id="{esc(message.get("id"))}"><summary>'
                f'<span class="message-text">{esc(message.get("text"))}</span> {pill}</summary>'
                + (f'<p class="confidence-note">{esc(note)}</p>' if note else "")
                + f'<ol class="chain">{"".join(steps)}</ol>{"".join(blocks)}</details>')

    def summary_view(self) -> str:
        if not self.model["messages"]:
            return f'<p>{self.t("no_facts") if not self.model["facts"] else self.t("none_here")}</p>'
        return "\n".join(self.message(message) for message in self.model["messages"])

    # --- the facts ---

    def fact(self, fact: dict, show_ref: bool = False) -> str:
        fields = fact.get("fields") if isinstance(fact.get("fields"), dict) else None
        pills = [self.pill(f"status-{_token(fact.get('status'))}",
                           self.labels.get(f"status_{fact.get('status')}", fact.get("status")))]
        if fields:
            access = fields.get("access")
            pills.append(self.pill(f"access-{_token(access)}", self.labels.get(f"access_{access}", self.labels["access_not_stated"])))
            stage = fields.get("stage")
            pills.append(self.pill(f"stage-{_token(stage)}", self.labels.get(f"stage_{stage}", self.labels["stage_not_stated"])))
        pills.append(self.class_pill(fact.get("data_class")))
        source = fact.get("source")
        body = [f'<p class="fact-ref">{self.t("label_fact")} {self.fact_ref(fact)}</p>'] if show_ref else []
        body.append(self.quote(fact.get("quote"), fact.get("quote_translation"), fact.get("quote_language")))
        if source is not None:
            body.append(f'<p class="fact-source">{self.source_link(fact.get("source_id"), self._source_name(source))}</p>')
        supporting = [entry for entry in fact.get("supporting") or [] if isinstance(entry, dict)]
        same = [entry for entry in supporting if entry.get("source_id") == fact.get("source_id")]
        other = [entry for entry in supporting if entry.get("source_id") != fact.get("source_id")]
        # a quote from the fact's own source states a detail; only a quote from another source is a second source,
        # and one from a source recorded as based on the fact's own says that it repeats it
        for key, entries in (("supporting_same_source", same), ("supporting_sources", other)):
            if entries:
                body.append(f'<h4>{self.t(key)}</h4>')
                body += [self.quote(entry.get("quote"), entry.get("quote_translation"),
                                    (self.sources.get(entry.get("source_id")) or {}).get("language"))
                         + f'<p>{self.source_link(entry.get("source_id"))}</p>'
                         + self._repeats(entry.get("source_id"), fact.get("source_id")) for entry in entries]
        body.append(self.reason(fact))
        return (f'<details class="fact" id="{esc(fact.get("id"))}"><summary>'
                f'<span class="fact-statement">{esc(fact.get("statement"))}</span> {_join(pills)}</summary>'
                + "".join(body) + "</details>")

    def _repeats(self, source_id, main_id) -> str:
        """A plain note when `source_id` is recorded as based on the fact's own source `main_id`, directly or through
        other sources: it repeats that source and is never a second source (the program does not count it)."""
        if not (isinstance(source_id, str) and isinstance(main_id, str) and source_id != main_id
                and main_id in verify._lineage(source_id, self.sources)):
            return ""
        return f'<p class="repeats">{self.fmt("supporting_repeats", source=main_id)}</p>'

    def _source_name(self, source: dict) -> str:
        return _join([f'{source.get("id")}:', _join([str(part) for part in (source.get("title"), source.get("publisher"),
                                                                           source.get("date")) if part], ", ")])

    def early_signals(self, facts: list[dict]) -> str:
        """The early signals in a block of their own, opened by what they are. Each is named by the shared fact
        reference, so it keeps its uncertain mark and, from a source that is not public, its class mark."""
        cards = "\n".join(self.fact(fact, show_ref=True) for fact in facts)
        return (f'<div class="early-signals"><h3>{self.t("sec_early_signals")}</h3>'
                f'<p class="early-signals-note">{self.t("early_signals_note")}</p>\n{cards}</div>')

    def facts_view(self) -> str:
        if not self.model["facts"]:
            return f'<p>{self.t("no_facts")}</p>'
        others, early = split_early_signals(self.model["facts"])
        parts = [self.fact(fact) for fact in others]
        if early:
            parts.append(self.early_signals(early))
        return "\n".join(parts)

    # --- competitors, timeline, demand ---

    def _what(self, fields: dict) -> str:
        value = fields.get("size_value")
        size = _join([str(value or ""), str(unit_for(value, fields.get("size_unit")) or "")])
        return _join([esc(fields.get("what_added")), f"({esc(size)})" if size else ""])

    def _home_pill(self, company: dict) -> str:
        return self.pill("home", self.labels["home_company"]) if company["home"] else ""

    def _move_row(self, company: dict, move: dict) -> str:
        fields = move["fields"]
        stage = self.labels.get(f"stage_{fields.get('stage')}", self.labels["stage_not_stated"])
        access = self.labels.get(f"access_{fields.get('access')}", self.labels["access_not_stated"])
        status = self.labels.get(f"status_{move.get('status')}", move.get("status"))
        cells = [_join([esc(company["company"]), self._home_pill(company)]), self._what(fields), esc(fields.get("site")),
                 esc(fields.get("country")), esc(stage),
                 esc(field_label("planned_start", fields.get("planned_start"), self.labels)), esc(access), esc(status),
                 self.fact_ref(move)]
        return f'<tr class="move{" home" if company["home"] else ""}">' + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"

    def competitors_view(self) -> str:
        model, parts = self.model, []
        if any(company["moves"] for company in model["competitors"]):
            columns = ("company", "what", "site", "country", "stage", "start", "access", "status", "fact")
            head = "".join(f"<th>{self.t('col_' + column)}</th>" for column in columns)
            rows = "".join(self._move_row(company, move) for company in model["competitors"] for move in company["moves"])
            parts.append(f'<div class="table-wrap"><table class="moves"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>')
        for company in model["competitors"]:
            if company["baseline"]:
                # no wording of its own: each fact's checked statement, named by the shared fact reference
                items = self.listing([self.with_refs(fact.get("statement"), [fact]) for fact in company["baseline"]])
                parts.append(f'<div class="baseline"><h3>{_join([esc(company["company"]), self._home_pill(company)])}</h3>'
                             f'<h4>{self.t("baseline")}</h4>{items}</div>')
        for heading, fragment in (("sec_grid", visuals.move_grid(model["facts"])),
                                  ("sec_delivery", visuals.delivery_table(model["facts"])),
                                  ("sec_capacity", visuals.capacity_bars(model["facts"])),
                                  ("sec_countries", visuals.sites_by_country(model["facts"])),
                                  ("sec_totals", visuals.totals(model["calculations"]))):
            if fragment:
                parts.append(f'<h3>{self.t(heading)}</h3>\n{fragment}')
        if model["demand_signals"]:
            parts.append(f'<h3>{self.t("sec_demand")}</h3>'
                         + self.listing([self.with_refs(signal.get("text"), signal["facts"]) for signal in model["demand_signals"]]))
        return "\n".join(parts) or self.nothing()

    def timeline_view(self) -> str:
        return visuals.timeline(self.model["facts"], self.model["home_company"]) or self.nothing()

    # --- scenarios and predictions ---

    def _assumption(self, assumption: dict) -> str:
        support = assumption.get("support")
        return (f'<li class="assumption" id="{esc(assumption.get("id"))}"><strong>{esc(assumption.get("id"))}</strong> '
                + _join([esc(assumption.get("text")), self.pill(f"support-{_token(support)}", assumption.get("support_label")),
                         self.refs(assumption["facts"])])
                + f' <span class="if-wrong">{self.t("if_wrong")}: {esc(assumption.get("if_wrong"))}</span></li>')

    def _scenario(self, scenario: dict) -> str:
        links = ", ".join(f'<a href="#{esc(a.get("id"))}" data-view="scenarios">{esc(a.get("id"))}</a>' for a in scenario["assumptions"])
        signposts = "".join(f'<li class="signpost">{self.with_refs(s.get("text"), s["facts"])}</li>' for s in scenario["signposts"])
        return (f'<article class="scenario" id="{esc(scenario.get("id"))}"><h3>{esc(scenario.get("name"))}</h3>'
                f'<p>{esc(scenario.get("description"))}</p>'
                + (f'<p class="based-on">{self.t("based_on")}: {links}</p>' if links else "")
                + (f"<ul>{signposts}</ul>" if signposts else "") + "</article>")

    def scenarios_view(self) -> str:
        model = self.model
        parts = [f'<p class="judgement">{self.t("judgement")}</p>']
        parts += [self._scenario(scenario) for scenario in model["scenarios"]]
        if model["assumptions"]:
            parts.append('<ul class="assumptions">' + "".join(self._assumption(a) for a in model["assumptions"]) + "</ul>")
        if model["predictions"]:
            items = []
            for p in model["predictions"]:
                form = self.fmt("prediction_form", statement=p.get("statement"), by=p.get("by"),
                                probability=p.get("probability"), word=p.get("word"))
                items.append(f'<li class="prediction" id="{esc(p.get("id"))}">{form}</li>'
                             f'<li class="resolves-when">{self.t("resolves_when")}: {esc(p.get("resolves_when"))}</li>')
            parts.append(f'<h3>{self.t("sec_predictions")}</h3><ul class="predictions">{"".join(items)}</ul>')
        return "\n".join(parts)

    # --- decision options ---

    def options_view(self) -> str:
        model = self.model
        options = model["decision_options"] or {}
        parts = []
        if options.get("options") or options.get("internal_questions"):
            parts.append(f'<p class="question"><strong>{esc(options.get("question"))}</strong></p>')
            framing = self.labels.get(f"framing_{options.get('framing')}")
            if framing:
                parts.append(f'<p class="framing">{_join([esc(framing), self.refs(options.get("framing_facts"))])}</p>')
        for option in options.get("options") or []:
            sides = "".join(f'<h4>{self.t("option_" + side)}</h4>'
                            + (self.listing([self.with_refs(point.get("text"), point["facts"]) for point in option.get(key) or []], side))
                            for side, key in (("for", "for"), ("against", "against")))
            parts.append(f'<article class="option"><h3>{esc(option.get("name"))}</h3>{sides}</article>')
        if options.get("internal_questions"):
            parts.append(f'<h3>{self.t("internal_questions")}</h3>' + self.listing([esc(q) for q in options["internal_questions"]]))
        if model["watch_items"]:
            parts.append(f'<h3>{self.t("sec_watch")}</h3>' + self.listing(
                [f'{esc(item.get("text"))} <span class="trigger">{self.t("watch_trigger")}: {esc(item.get("trigger"))}</span>'
                 for item in model["watch_items"]]))
        return "\n".join(parts) or self.nothing()

    # --- checks and what could not be confirmed ---

    def checks_view(self) -> str:
        model, parts = self.model, []
        if model["audit_flags"]:
            parts.append(self.listing(
                [f'<strong class="check">{esc(label(self.labels, "audit_", flag.get("check"), store.AUDIT_CHECKS))}</strong> '
                 f'{esc(flag.get("text"))}' for flag in model["audit_flags"]], "flags"))
        if model["not_found"] or model["contradictions"] or model["rejected"]:
            parts.append(f'<h3>{self.t("sec_not_confirmed")}</h3>')
            parts.append(self.listing([esc(text) for text in model["not_found"]]
                                      + [self.with_refs(item.get("text"), item["facts"]) for item in model["contradictions"]]))
        if model["rejected"]:
            items = []
            for fact in model["rejected"]:
                items.append('<li class="rejected-fact">'
                             + _join([esc(fact.get("statement")), self.class_pill(fact.get("data_class")),
                                      self.source_link(fact.get("source_id")), self.reason(fact, "span")])
                             + self.quote(fact.get("quote"), fact.get("quote_translation"), fact.get("quote_language")) + "</li>")
            parts.append(f'<h4>{self.count("rejected", len(model["rejected"]))}</h4><ul class="rejected">{"".join(items)}</ul>')
        return "\n".join(parts) or self.nothing()

    # --- the thinking behind the analysis ---

    def _lens(self, lens: dict) -> str:
        parts = "".join(f'<dt>{self.t("lens_" + key)}</dt><dd>{esc(lens[key])}</dd>'
                        for key in ("idea", "suggests", "limits", "competing_idea") if lens.get(key))
        originals = []
        for original in lens.get("originals") or []:
            level = self.labels.get(f"level_{original.get('level')}", original.get("level"))
            originals.append(_join([esc(original.get("reference")), self.pill(f"level-{_token(original.get('level'))}", level),
                                    self.address(original.get("link"))]))
        return (f'<article class="lens-card" id="lens-{esc(lens.get("id"))}"><h3>{esc(lens.get("name"))}</h3>'
                f'<dl>{parts}</dl>'
                + (f'<p class="lens-here">{esc(lens["here"])}</p>' if lens.get("here") else "")
                + f'<h4>{self.t("lens_questions")}</h4>' + self.listing([esc(q) for q in lens.get("questions") or []])
                + self.listing(originals, "originals") + "</article>")

    def thinking_view(self) -> str:
        return "\n".join(self._lens(lens) for lens in self.model["lenses"]) or self.nothing()

    # --- level 3: one page per source ---

    def _source(self, source: dict) -> str:
        labels = self.labels
        rows = [("source_publisher", esc(source.get("publisher"))),
                ("source_type", esc(labels.get(f"type_{source.get('type')}", source.get("type")))),
                ("source_date", esc(source.get("date"))),
                ("source_speaker", esc(source.get("speaker"))),
                ("source_interest", esc(source.get("interest"))),
                ("source_saved", esc(source.get("saved_at")))]
        if source.get("final_url"):   # the copy came from another address than the one asked for: show both
            rows += [("source_asked", self.address(source.get("url"))),
                     ("source_passed_on", self.address(source.get("final_url")))]
        else:
            rows.append(("source_link", self.address(source.get("url"))))
        if source.get("based_on"):
            rows.append(("based_on", ", ".join(self.source_link(source_id) for source_id in source["based_on"])))
        provenance = source.get("provenance")
        if isinstance(provenance, dict):
            rows += [("supplied_by", esc(provenance.get("supplied_by"))), ("basis", esc(provenance.get("basis")))]
        flags = [self.class_pill(source.get("data_class"))]
        if source.get("access") == "not_accessible":
            flags.append(self.pill("not-accessible", labels["not_accessible"]))
            rows.append(("not_accessible", esc(access_reason_text(source.get("access_reason"), labels))))
        if source.get("saved_by") == "hand":
            flags.append(self.pill("saved-by-hand", labels["saved_by_hand"]))
        quotes = []
        for entry in source["quotes"]:
            fact = self.facts.get(entry["fact_id"])
            ref = self.fact_ref(fact) if fact is not None else esc(entry["fact_id"])
            quotes.append(f'<div class="source-quote">{self.quote(entry.get("quote"), entry.get("translation"), source.get("language"))}'
                          f'<p class="quote-fact">{self.t("label_fact")} {ref}</p></div>')
        return (f'<article class="source" id="{esc(source.get("id"))}"><h3>{esc(source.get("id"))}: {esc(source.get("title"))} '
                f'{_join(flags)}</h3><dl>' + "".join(f"<dt>{self.t(key)}</dt><dd>{value}</dd>" for key, value in rows)
                + "</dl>" + "".join(quotes) + "</article>")

    def sources_view(self) -> str:
        return "\n".join(self._source(source) for source in self.model["sources"]) or self.nothing()

    # --- how the report was made ---

    def how_view(self) -> str:
        how, parts = self.model["how_made"], []
        if how["search_log"]:
            parts.append(f'<h3>{self.t("how_searched")}</h3>'
                         + self.listing([f'{esc(item.get("place"))}: {esc(item.get("result"))}' for item in how["search_log"]]))
        if how["excluded"]:
            parts.append(f'<h3>{self.t("how_excluded")}</h3>'
                         + self.listing([f'{esc(item.get("what"))}: {esc(item.get("why"))}' for item in how["excluded"]]))
        if how["checkpoints"] or how.get("private_acknowledged"):
            items = ([f'{self.t("private_acknowledged")}: {esc(how.get("private_acknowledged"))}']
                     if how.get("private_acknowledged") else [])
            for item in how["checkpoints"]:
                name = label(self.labels, "checkpoint_", item.get("name"), store.CHECKPOINTS)
                items.append(f"{esc(name)}: " + ": ".join(esc(part) for part in checkpoint_parts(item, self.labels)))
            parts.append(f'<h3>{self.t("how_checkpoints")}</h3>' + self.listing(items))
        parts.append(f'<p class="compliance">{esc(self.model["compliance"])}</p>')
        confidence = self.listing([self.t(f"confidence_{level}") for level in ("high", "medium", "low")])
        scale = self.listing([f"{esc(span)}%: {self.t(key)}" for _, span, key in PROBABILITY_SCALE])
        parts.append(f'<div class="legend"><h3>{self.t("sec_legend")}</h3>{confidence}{scale}</div>')
        return "\n".join(parts)

    # --- what changed since the last run ---

    def changes_view(self) -> str:
        return visuals.changes_view(self.model["changes"], self.facts) or self.nothing()

    # --- the whole page ---

    def status_line(self) -> str:
        model, counts = self.model, self.model["status_line"]
        parts = [self.t("includes_private") if model["confidential"] else self.t("public_only"),
                 self.fmt("read_until", date=model["sources_read_until"]),
                 self.count("facts_checked", counts["confirmed"] + counts["uncertain"]),
                 self.fmt("uncertain", n=counts["uncertain"]),
                 self.count("rejected", counts["rejected"])]
        if counts["not_accessible"]:
            parts.append(f'{self.t("not_accessible")}: {esc(counts["not_accessible"])}')
        return " · ".join(parts)

    def document(self) -> str:
        model = self.model
        views = [(key, title, getattr(self, f"{key}_view")()) for key, title in _VIEWS]
        if model["changes"] is not None:
            views.append(("changes", "sec_changes", self.changes_view()))
        banners = ""
        if model["confidential"]:
            banners += f'<div class="banner confidential">{self.t("confidential")}</div>\n'
        if model["illustrative"]:
            banners += f'<div class="banner illustrative">{self.t("illustrative")}</div>\n'
        tabs = ""
        for number, (key, title, _) in enumerate(views):
            state = ' class="on" aria-pressed="true"' if number == 0 else ' aria-pressed="false"'
            tabs += f'<button type="button" data-view="{key}"{state}>{self.t(title)}</button>'
        sections = "\n".join(f'<section class="view{" on" if number == 0 else ""}" id="view-{key}">\n'
                             f'<h2>{self.t(title)}</h2>\n{body}\n</section>'
                             for number, (key, title, body) in enumerate(views))
        disclaimer = self.t("disclaimer_private") if model["confidential"] else self.t("disclaimer")
        return (f'<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
                f'<meta name="color-scheme" content="light dark">\n<title>{esc(model["question"])}</title>\n'
                f'<style>\n{_read("report.css")}\n</style>\n<script>\n{_read("report.js")}\n</script>\n</head>\n'
                f'<body>\n{banners}<header class="masthead">\n<h1>{esc(model["question"])}</h1>\n'
                f'<p class="status-line">{self.status_line()}</p>\n'
                f'<p class="built-on">{self.fmt("built_on", date=model["built_on"])}</p>\n'
                f'<p class="disclaimer">{disclaimer}</p>\n'
                f'<button class="print" type="button">{self.t("print")}</button>\n</header>\n'
                f'<nav class="tabs">{tabs}</nav>\n<main>\n{sections}\n</main>\n</body>\n</html>\n')


def _read(name: str) -> str:
    return (_HERE / name).read_text(encoding="utf-8").strip()


def render_html(model: dict) -> str:
    return _Page(model).document()
