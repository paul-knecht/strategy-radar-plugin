"""The interactive report: one self-contained HTML page with three levels of depth.

The page opens on the answer to the core question, then the buttons for one company, then the key messages (level 1,
each with its sources and its checks, level 2 the reasoning behind it), then the tabs; level 3 is one page per source.
`render_html` is pure. Everything that comes from the model is untrusted text, and it reaches the page
through `esc` and nothing else: no model text goes into the script, the style sheet, an event-handler
attribute or an unquoted attribute. Fixed text comes from `labels_en.json`, and engine words (statuses,
reasons, step kinds, checkpoints, access reasons, audit checks) are always shown by their label. `esc` and the
small parts shared with the visuals (pills, fact links, addresses) are defined in `visuals.py`, so there is one
escaping path.
"""
import re
from decimal import Decimal
from pathlib import Path

from .. import store, tidy, verify
from . import visuals
from .companies import fact_date
from .numbers import shown
from .model import (PROBABILITY_SCALE, access_reason_text, checkpoint_parts, count_label, field_label, helpers_line,
                    label, link_sentences, load_labels, reason_note, reason_text, split_early_signals)
from .projects_view import ACCESS_SHOWN, COUNTED_AS, outside as outside_question
from .visuals import esc, join as _join, token as _token

_HERE = Path(__file__).parent
_LANG = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*")
_VIEWS = (("facts", "sec_facts"), ("projects", "sec_projects"), ("connections", "sec_connections"),
          ("timeline", "sec_timeline"), ("scenarios", "sec_scenarios"), ("options", "sec_options"),
          ("checks", "sec_checks"), ("thinking", "sec_thinking"), ("sources", "sec_sources"),
          ("how", "sec_how_made"))
EXTRA_COMPANIES = ("other", "none")   # the two entries that are not one company
FILTERED_LISTS = ("facts", "projects", "connections", "sources")   # the views that open with a filter bar
FILTER_STATUSES = (("confirmed", "shown_confirmed"), ("single_source", "shown_single_source"),
                   ("uncertain", "shown_uncertain"))
_COMPANY_TOKEN = re.compile(r"c[0-9]+|other|none")
_DATE_TOKEN = re.compile(r"[0-9]{4}(?:-[0-9]{2}(?:-[0-9]{2})?)?")
_STATUS_TOKEN = re.compile(r"confirmed|single_source|uncertain|rejected")


def _tokens(values, allowed: "re.Pattern", fallback: str = "") -> str:
    """The values that fit the token pattern, once each, joined by spaces; `fallback` where none is left. The filters
    match on these, so no text of a model ever reaches a `data-` attribute."""
    kept = dict.fromkeys(value for value in values if isinstance(value, str) and allowed.fullmatch(value))
    return " ".join(kept) or fallback


def _key(company):
    """The key of a company entry of the model, or None."""
    return company.get("key") if isinstance(company, dict) else None


def _item_data(companies, dates, statuses) -> str:
    """The attributes every item of a list carries for the filters: its companies, dates and statuses as tokens (D11)."""
    return (f' data-company="{_tokens(companies, _COMPANY_TOKEN, "none")}" data-date="{_tokens(dates, _DATE_TOKEN)}"'
            f' data-status="{_tokens(statuses, _STATUS_TOKEN)}"')


def _lang(value) -> str:
    return f' lang="{esc(value)}"' if isinstance(value, str) and _LANG.fullmatch(value) else ""


class _Page:
    def __init__(self, model: dict):
        self.model = model
        self.labels = load_labels()
        self.sources = {source["id"]: source for source in model["sources"]}
        self.facts = {fact["id"]: fact for fact in model["facts"] + model["rejected"]}
        self.main_facts, self.early_facts = split_early_signals(model["facts"])
        self.projects_of = self._by_company(model["projects"]["items"], lambda item: item["company"]["key"])
        self.baselines_of = self._by_company([group for group in model["competitors"] if group["baseline"]],
                                             self._baseline_key)
        # the companies that have a heading in the Projects view and in the list of facts, in the order of the buttons
        self.project_companies = [entry for entry in self._companies_with_extras()
                                  if entry["key"] in self.projects_of or entry["key"] in self.baselines_of]
        self.project_keys = {entry["key"] for entry in self.project_companies}
        self.fact_keys = {fact["company"]["key"] for fact in self.main_facts if isinstance(fact.get("company"), dict)}

    @staticmethod
    def _by_company(items: list, key_of) -> dict[str, list]:
        found: dict[str, list] = {}
        for item in items:
            found.setdefault(key_of(item), []).append(item)
        return found

    def _baseline_key(self, group: dict) -> str:
        """The key of the company a baseline belongs to: its entry among the buttons by name, else "other"."""
        if not group["company"]:
            return "none"
        wanted = tidy.company_key(group["company"])
        for entry in self.model["companies"]:
            if entry["name"] and tidy.company_key(entry["name"]) == wanted:
                return entry["key"]
        return "other"

    def _companies_with_extras(self) -> list[dict]:
        """The company entries, and "other" or "none" where a baseline belongs to one that has no entry yet."""
        entries = list(self.model["companies"])
        known = {entry["key"] for entry in entries}
        for key in EXTRA_COMPANIES:
            if key not in known and any(self._baseline_key(group) == key for group in self.model["competitors"]
                                        if group["baseline"]):
                entries.append({"key": key, "name": None, "home": False, "group": key, "facts": 0})
        return entries

    # --- fixed text and small parts ---

    def t(self, key: str) -> str:
        """A label, escaped. A missing key gives nothing."""
        return esc(self.labels.get(key, ""))

    def fmt(self, key: str, **values) -> str:
        """A label with `{placeholders}` filled from escaped values."""
        return esc(self.labels[key]).format(**{name: esc(value) for name, value in values.items()})

    def number(self, n) -> str:
        """A count with thousands separators."""
        return shown(str(n), self.labels["thousands_separator"])

    def count(self, key: str, n) -> str:
        """A label for a count of `n`, in its singular form for exactly one where it has one."""
        return esc(count_label(self.labels, key, n)).format(n=esc(self.number(n)))

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

    def nothing(self, key: str) -> str:
        return f'<p class="none">{self.t(key)}</p>'

    def group_title(self, company: dict) -> str:
        """The heading of a company: its name, or for the two entries that are not one company, their label."""
        if company.get("key") == "other":
            return self.t("companies_other")
        if company.get("key") == "none":
            return self.t("companies_none")
        return esc(company.get("name"))

    def home_pill(self, company: dict) -> str:
        return self.pill("home", self.labels["home_company"]) if company.get("home") else ""

    def status_pill(self, fact: dict) -> str:
        """The status a fact is shown with: "One source only" (still an uncertain look) where that is the only reason
        it is not confirmed, else its own status."""
        shown = fact.get("shown_status") or fact.get("status")
        if shown == "single_source":
            return self.pill("status-uncertain status-single_source", self.labels["shown_single_source"])
        return self.pill(f"status-{_token(shown)}", self.labels.get(f"shown_{shown}", self.labels.get(f"status_{shown}", shown)))

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
        details = (f'<details class="message" id="{esc(message.get("id"))}"><summary>'
                   f'<span class="message-text">{esc(message.get("text"))}</span> {pill}</summary>'
                   + (f'<p class="confidence-note">{esc(note)}</p>' if note else "")
                   + f'<ol class="chain">{"".join(steps)}</ol>{"".join(blocks)}</details>')
        # the sources and the checks stand outside the fold, so they show without opening the message; a message that
        # rests on no fact is about no company
        companies = " ".join(esc(key) for key in message.get("companies") or []) or "none"
        return (f'<div class="message-item" data-company="{companies}">{details}'
                f'{self.message_sources(message)}{self.message_checks(message)}</div>')

    def message_sources(self, message: dict) -> str:
        """The sources a message rests on, by publisher; the company's own statement is marked."""
        entries = []
        for source in message.get("sources") or []:
            link = (f'<a href="#{esc(source.get("id"))}" data-view="sources">'
                    f'{esc(source.get("publisher") or source.get("id"))}</a>')
            entries.append(_join([link, f'({self.t("own_statement")})' if source.get("own") else ""]))
        if not entries:
            return ""
        return f'<p class="message-sources"><strong>{self.t("message_sources")}</strong>: {", ".join(entries)}</p>'

    def message_checks(self, message: dict) -> str:
        """The findings of the bias audit that name this message."""
        flags = message.get("flags") or []
        if not flags:
            return ""
        return (f'<div class="message-checks"><h4>{self.t("message_checks")}</h4>'
                + self.listing([self.flag(flag, with_messages=False) for flag in flags], "flags") + "</div>")

    def messages_block(self) -> str:
        messages = self.model["messages"]
        if messages and self.model.get("screening"):   # a memo: the findings under its parts, in their order
            groups = [(part, [m for m in messages if m.get("memo_part") == part]) for part in store.MEMO_PARTS]
            groups.append(("other", [m for m in messages if m.get("memo_part") not in store.MEMO_PARTS]))
            body = "\n".join(f'<h3>{self.t("memo_part_" + part)}</h3>\n' + "\n".join(self.message(m) for m in group)
                              for part, group in groups if group)
        elif messages:
            body = "\n".join(self.message(message) for message in messages)
        else:
            body = f'<p>{self.t("no_facts") if not self.model["facts"] else self.t("none_messages")}</p>'
        return f'<section id="messages">\n<h2>{self.t("sec_messages")}</h2>\n{body}\n</section>'

    # --- the answer to the core question, and the buttons for one company ---

    def grouping_note(self) -> str:
        """What the answer rests on: the note that the grouping is a model's judgement, or, where the moves are not
        grouped, why each move counts as its own project."""
        state = self.model["projects"]["state"]
        return self.t("answer_note") if state == "grouped" else self.t(f"answer_ungrouped_{_token(state)}")

    def answer_bar(self, answer: dict, link: bool) -> str:
        """The bar of projects by who the capacity is for, with its legend and total. The parts of the main bar are
        links to the Projects view; those of a company's own bar are plain."""
        total = answer["total"]
        parts, legend = [], []
        for access in ACCESS_SHOWN:
            number, name = answer[access], self.t(f"answer_{access}")
            if number:
                width = visuals._width(Decimal(number), Decimal(total))
                text = f'<span class="visually-hidden">{name}: </span><span class="answer-count">{self.number(number)}</span>'
                style = f'style="width:{width}%" title="{name}: {self.number(number)}"'
                parts.append(f'<a class="answer-part {access}" href="#view-projects" data-view="projects" '
                             f'data-access="{access}" {style}>{text}</a>' if link
                             else f'<span class="answer-part {access}" {style}>{text}</span>')
            legend.append(f'<li><span class="answer-swatch {access}"></span> {name}: <strong>{self.number(number)}</strong></li>')
        return (f'<div class="answer-bar">{"".join(parts)}</div>\n'
                f'<ul class="answer-legend">{"".join(legend)}</ul>\n'
                f'<p class="answer-total">{self.count("answer_total", total)}</p>')

    def answer_block(self) -> str:
        answer = self.model["core_answer"]
        if answer is None:
            return ""
        # the moves outside the question are counted apart; the line opens the facts list filtered to them
        more = (f'<p class="answer-outside"><a href="#view-facts" data-filter-question="outside">'
                f'{self.count("answer_outside", answer["outside"])}</a></p>\n' if answer["outside"] else "")
        return (f'<section id="answer">\n<h2>{self.t("sec_answer")}</h2>\n{self.answer_bar(answer, True)}\n{more}'
                f'<p class="answer-note">{self.grouping_note()}</p>\n'
                f'<p class="answer-rule">{self.t("answer_rule")}</p>\n</section>')

    def companies_nav(self) -> str:
        entries = self.model["companies"]
        if not entries:
            return ""
        buttons = []
        for entry in entries:
            key = entry["key"]
            if key in EXTRA_COMPANIES:
                buttons.append(f'<a class="company-button" href="#view-facts" data-filter-company="{esc(key)}">'
                               f'{self.group_title(entry)}</a>')
                continue
            if entry.get("only_connections"):   # no page of its own: the connections that name it
                buttons.append(f'<a class="company-button" href="#view-connections" data-filter-company="{esc(key)}" '
                               f'data-filter-view="connections">{self.group_title(entry)} '
                               f'<span class="company-note">{self.t("company_only_connections")}</span></a>')
                continue
            # the heading of the company's projects, else the heading of its facts, else the Projects tab itself
            if key in self.project_keys:
                href = f"#projects-{key}"
            elif key in self.fact_keys:
                href = f"#facts-{key}"
            else:
                href = "#view-projects"
            buttons.append(f'<a class="company-button" href="{esc(href)}" data-company-page="{esc(key)}">'
                           + _join([self.group_title(entry), self.home_pill(entry)]) + "</a>")
        return (f'<nav id="companies">\n<h2>{self.t("sec_companies")}</h2>\n'
                f'<div class="company-buttons">{"".join(buttons)}</div>\n</nav>')

    def company_heads(self) -> str:
        """One head for each company with a button of its own. A head stays hidden until the script opens that company's
        page: the report, filtered to that company. It names the company and holds the way back and the company's own
        answer, counted by the program (none for a company with no project), with how many of its moves fall outside the
        question. It holds no fact, no project and no id."""
        heads = []
        for entry in self.model["companies"]:
            if entry["key"] in EXTRA_COMPANIES or entry.get("only_connections"):
                continue
            answer = entry.get("core_answer")
            outside = (f'<p class="answer-outside">{self.count("answer_outside", entry["outside"])}</p>\n'
                       if entry.get("outside") else "")
            heads.append(f'<section class="company-head" data-company-head="{esc(entry["key"])}" hidden>\n'
                         f'<button type="button" class="company-back" data-company-back>{self.t("company_back")}</button>\n'
                         f'<h2>{_join([self.group_title(entry), self.home_pill(entry)])}</h2>\n'
                         f'<p class="company-head-note">{self.t("company_head_note")}</p>\n'
                         + (self.answer_bar(answer, False) if answer else "") + "\n" + outside + "</section>")
        return "\n".join(heads)

    # --- the filters ---

    def _date_inputs(self) -> tuple[str, str]:
        """One option per year in which a fact or a source is dated, and the first and last month present, which bound
        the two month fields; one list for every bar, so the date chosen in one bar is there in the others."""
        dates = [fact.get("date") for fact in self.model["facts"]] + [fact_date(source) for source in self.model["sources"]]
        dates = [date for date in dates if isinstance(date, str) and _DATE_TOKEN.fullmatch(date)]
        years = "".join(f'<option value="{year}">{year}</option>' for year in sorted({date[:4] for date in dates}, reverse=True))
        months = sorted(date[:7] for date in dates if len(date) >= 7)
        return years, f' min="{months[0]}" max="{months[-1]}"' if months else ""

    def filter_bar(self, view: str, count: int) -> str:
        """The bar at the top of a list: what to show by company, date and status (and, for projects, by who the
        capacity is for), and the line that says how many of the list's `count` items the filter hides. A list with
        nothing in it has no bar."""
        if not count:
            return ""
        companies = "".join(f'<option value="{esc(entry["key"])}">{self.group_title(entry)}</option>'
                            for entry in self.model["companies"])
        statuses = "".join(f'<option value="{code}">{self.t(key)}</option>' for code, key in FILTER_STATUSES)
        access = "".join(f'<option value="{code}">{self.t(f"answer_{code}")}</option>' for code in ACCESS_SHOWN)
        years, month_bounds = self._date_inputs()
        controls = [("company", "filter_company", "filter_all", companies),
                    ("date", "filter_date", "filter_all_dates", years),
                    ("status", "filter_status", "filter_all", statuses)]
        if view == "projects":
            controls.append(("access", "filter_access", "filter_all", access))
        answer = self.model["core_answer"]
        if view == "facts" and answer and answer["outside"]:
            controls.append(("question", "filter_question", "filter_all",
                             f'<option value="outside">{self.t("filter_outside")}</option>'))
        month_fields = "".join(f'<label class="filter"><span class="filter-label">{self.t(title)}</span> '
                               f'<input type="month" name="{name}"{month_bounds} placeholder="YYYY-MM" '
                               f'pattern="[0-9]{{4}}-[0-9]{{2}}"></label>'
                               for name, title in (("from", "filter_from"), ("to", "filter_to")))
        selects = "".join(
            f'<label class="filter"><span class="filter-label">{self.t(title)}</span> <select name="{name}">'
            f'<option value="all">{self.t(everything)}</option>{options}</select></label>'
            + (month_fields if name == "date" else "")
            for name, title, everything, options in controls)
        return (f'<form class="filters" data-list="{view}" aria-label="{self.t("filter_bar")}" autocomplete="off">'
                f'{selects}<p class="filter-count" data-all="{self.fmt("filter_count_all", n=count)}" '
                f'data-some="{self.t("filter_count_some")}" data-reversed="{self.t("filter_from_after_to")}">'
                f'{self.fmt("filter_count_all", n=count)}</p></form>')

    # --- the facts ---

    def fact(self, fact: dict, show_ref: bool = False) -> str:
        fields = fact.get("fields") if isinstance(fact.get("fields"), dict) else None
        pills = [self.status_pill(fact)]
        if fields:
            access = fields.get("access")
            pills.append(self.pill(f"access-{_token(access)}", self.labels.get(f"access_{access}", self.labels["access_not_stated"])))
            stage = fields.get("stage")
            pills.append(self.pill(f"stage-{_token(stage)}", self.labels.get(f"stage_{stage}", self.labels["stage_not_stated"])))
        pills.append(self.class_pill(fact.get("data_class")))
        if outside_question(fact):   # marked in the card itself, so it shows without the script and in print
            pills.append(self.pill("outside", self.labels["pill_outside"]))
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
        if fact.get("shown_status") == "single_source":
            body.append(f'<p class="single-source-note">{self.t("single_source_note")}</p>')
        body.append(self.reason(fact))
        # a company outside the pack is named on its own row, since its heading is "Other companies"
        company = fact.get("company")
        named = (f'<span class="fact-company">{esc(company["name"])}</span> '
                 if isinstance(company, dict) and company.get("key") == "other" and company.get("name") else "")
        shown = fact.get("shown_status") or fact.get("status")
        data = _item_data([_key(fact.get("company"))], [fact.get("date")], [shown])
        data += f' data-question="{"outside" if outside_question(fact) else "inside"}"'
        return (f'<details class="fact" id="{esc(fact.get("id"))}"{data}><summary>'
                f'{named}<span class="fact-statement">{esc(fact.get("statement"))}</span> {_join(pills)}</summary>'
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
        companies = _tokens([_key(fact.get("company")) for fact in facts], _COMPANY_TOKEN, "none")
        return (f'<div class="early-signals" data-company="{companies}"><h3>{self.t("sec_early_signals")}</h3>'
                f'<p class="early-signals-note">{self.t("early_signals_note")}</p>\n{cards}</div>')

    def facts_view(self) -> str:
        if not self.model["facts"]:
            return f'<p>{self.t("no_facts")}</p>'
        parts, current = [], None
        for fact in self.main_facts:
            company = fact.get("company") if isinstance(fact.get("company"), dict) else None
            if company is not None and company["key"] != current:
                current = company["key"]
                parts.append(f'<h3 id="facts-{esc(current)}" data-company="{esc(current)}">'
                             + _join([self.group_title(company), self.home_pill(company)]) + "</h3>")
            parts.append(self.fact(fact))
        if self.early_facts:
            parts.append(self.early_signals(self.early_facts))
        return "\n".join(parts)

    # --- projects and connections ---

    def _project_counts(self, counts: dict) -> str:
        pills = [(counts["confirmed"], "count-confirmed", self.labels["project_confirmed"]),
                 (counts["single_source"], "count-single_source", self.labels["status_single_source"]),
                 (counts["uncertain"], "count-uncertain", self.labels["project_uncertain"])]
        return _join([self.pill(css, text.format(n=number)) for number, css, text in pills if number])

    def _spread(self, item: dict) -> tuple[str, str]:
        """What the reports of a project say, per value with how many say it (the count only for more than one
        report): the row of the project (site, country, stage, start) as spans for its summary, and, for the fold,
        what was added."""
        several = len(item["facts"]) > 1
        shown = {}
        for name, key, field in (("site", "field_site", None), ("countries", "field_country", None),
                                 ("stage", "field_stage", "stage"), ("planned_start", "field_planned_start", "planned_start"),
                                 ("what", "field_what_added", None)):
            values = [(field_label(field, value, self.labels) if field else str(value)) + (f" ({number})" if several else "")
                      for value, number in item["spread"].get(name) or []]
            if values:
                shown[name] = (key, ", ".join(values))
        row = "".join(f'<span class="spread-item"><span class="spread-label">{self.t(key)}</span> {esc(text)}</span>'
                      for name, (key, text) in shown.items() if name != "what")
        what = (f'<dl class="spread"><dt>{self.t(shown["what"][0])}</dt><dd>{esc(shown["what"][1])}</dd></dl>'
                if "what" in shown else "")
        return (f'<span class="spread-row">{row}</span>' if row else ""), what

    def _report(self, fact: dict) -> str:
        source = fact.get("source") if isinstance(fact.get("source"), dict) else {}
        source_id = fact.get("source_id")
        where = (f'<a href="#{esc(source_id)}" data-view="sources">{esc(source.get("publisher") or source_id)}</a>'
                 if source_id in self.sources else esc(source_id))
        size = visuals.stated_size(fact, self.labels["thousands_separator"])
        return ('<li class="project-report">'
                + _join([f'<span class="report-statement">{esc(fact.get("statement"))}</span>',
                         f'<span class="report-size">({esc(size)})</span>' if size else "", self.fact_ref(fact),
                         f'<span class="report-source">{_join([where, esc(fact.get("date"))], ", ")}</span>']) + "</li>")

    def project(self, item: dict) -> str:
        company = item["company"]
        who = (f'<span class="project-company">{esc(company.get("name") or "")}</span>'
               if company["key"] in EXTRA_COMPANIES and company.get("name") else "")
        access = item["access"]
        row, what = self._spread(item)
        summary = _join([f'<span class="project-name">{esc(item["name"])}</span>', who,
                         self.pill(f"project-access-{_token(access)}", self.labels[f"answer_{access}"]),
                         self._project_counts(item["counts"]), row])
        reports = (f'<h4>{self.t("col_reports")}</h4><ul class="project-reports">'
                   + "".join(self._report(fact) for fact in item["facts"]) + "</ul>")
        data = _item_data([_key(company)], item["dates"], [status for status in COUNTED_AS if item["counts"][status]])
        return (f'<details class="project" id="{esc(item["id"])}"{data} data-access="{_token(access)}">'
                f'<summary>{summary}</summary>'
                f'{what}{reports}</details>')

    def baseline(self, group: dict, key: str) -> str:
        """The facts a company's baselines rest on, each with its checked statement and its fact reference. Where the
        heading is "Other companies", the block names its own company."""
        who = f'<p class="baseline-company"><strong>{esc(group["company"])}</strong></p>' if key in EXTRA_COMPANIES else ""
        items = self.listing([self.with_refs(fact.get("statement"), [fact]) for fact in group["baseline"]])
        return f'<div class="baseline" data-company="{esc(key)}">{who}<h4>{self.t("baseline")}</h4>{items}</div>'

    def projects_more(self) -> str:
        """What speaks of all companies at once: capacity, sites by country, totals, demand signals, delivery, grid."""
        model, facts, parts = self.model, self.model["facts"], []
        demand = ""
        if model["demand_signals"]:
            demand = self.listing([self.with_refs(signal.get("text"), signal["facts"]) for signal in model["demand_signals"]])
        for heading, fragment in (("sec_capacity", visuals.capacity_bars(facts)),
                                  ("sec_countries", visuals.sites_by_country(facts)),
                                  ("sec_totals", visuals.totals(model["calculations"])),
                                  ("sec_demand", demand),
                                  ("sec_delivery", visuals.delivery_table(facts)),
                                  ("sec_grid", visuals.move_grid(facts))):
            if fragment:
                parts.append(f'<h3>{self.t(heading)}</h3>\n{fragment}')
        return f'<div class="projects-more">\n{chr(10).join(parts)}\n</div>' if parts else ""

    def projects_view(self) -> str:
        parts = []
        if self.model["projects"]["items"] and self.model["projects"]["state"] != "grouped":
            parts.append(f'<p class="note">{self.grouping_note()}</p>')
        for entry in self.project_companies:
            key = entry["key"]
            parts.append(f'<h3 id="projects-{esc(key)}" data-company="{esc(key)}">'
                         + _join([self.group_title(entry), self.home_pill(entry)]) + "</h3>")
            parts += [self.project(item) for item in self.projects_of.get(key, [])]
            parts += [self.baseline(group, key) for group in self.baselines_of.get(key, [])]
        parts.append(self.projects_more())
        return "\n".join(part for part in parts if part) or self.nothing("none_projects")

    def connections_view(self) -> str:
        if not self.model["connections"]:
            if self.model["connections_old"]:
                return self.nothing("none_connections_old")
            dropped = (self.model["how_made"].get("names_dropped") or {}).get("parties", 0)
            return self.nothing("none_connections_dropped" if dropped else "none_connections")
        head = "".join(f'<th scope="col">{self.t(key)}</th>'
                       for key in ("col_company", "col_tie", "col_party", "col_status", "col_fact"))
        rows = []
        for connection in self.model["connections"]:
            fact, company = connection["fact"], connection["company"]
            description = connection.get("description")
            if connection.get("party_name"):
                party = esc(connection["party_name"]) + (f' <span class="connection-description">{esc(description)}</span>'
                                                         if description else "")
            else:
                party = self.fmt("party_not_named", description=description) if description else self.t("party_not_named_plain")
            tie = label(self.labels, "tie_", connection.get("tie"), store.CONNECTION_TIES)
            cells = [_join([esc(company.get("name")) or self.group_title(company), self.home_pill(company)]), esc(tie), party,
                     self.status_pill(fact), self.fact_ref(fact)]
            data = _item_data([_key(company), _key(connection.get("party"))], [fact.get("date")],
                              [fact.get("shown_status") or fact.get("status")])
            rows.append(f'<tr class="connection"{data}>' + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
        return (f'<div class="table-wrap"><table class="connections"><thead><tr>{head}</tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table></div>')

    def timeline_view(self) -> str:
        return visuals.timeline(self.model["facts"], self.model["home_company"]) or self.nothing("none_timeline")

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
                items.append(f'<li class="prediction" id="prediction-{esc(p.get("id"))}">{form}</li>'
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
        return "\n".join(parts) or self.nothing("none_options")

    # --- checks and what could not be confirmed ---

    def flag(self, flag: dict, with_messages: bool = True) -> str:
        """One finding of the bias audit; in the list of checks it also links to the messages it names."""
        text = (f'<strong class="check">{esc(label(self.labels, "audit_", flag.get("check"), store.AUDIT_CHECKS))}</strong> '
                f'{esc(flag.get("text"))}')
        links = ", ".join(f'<a href="#{esc(message_id)}">{esc(message_id)}</a>' for message_id in flag.get("message_ids") or [])
        if with_messages and links:
            text += f' <span class="flag-messages">{self.t("flag_about")}: {links}</span>'
        return text

    def checks_view(self) -> str:
        model, parts = self.model, []
        if model["audit_flags"]:
            parts.append(self.listing([self.flag(flag) for flag in model["audit_flags"]], "flags"))
        if model["not_found"] or model["contradictions"] or model["rejected"]:
            parts.append(f'<h3>{self.t("sec_open_questions" if model.get("screening") else "sec_not_confirmed")}</h3>')
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
        return "\n".join(parts) or self.nothing("none_checks")

    # --- the thinking behind the analysis ---

    def _lens(self, lens: dict) -> str:
        parts = "".join(f'<dt>{self.t("lens_" + key)}</dt><dd>{esc(lens[key])}</dd>'
                        for key in ("idea", "suggests", "limits", "competing_idea") if lens.get(key))
        originals = []
        for original in lens.get("originals") or []:
            level = self.labels.get(f"level_{original.get('level')}", original.get("level"))
            about = f'<span class="lens-about">{self.t("original_about")} {esc(original["about"])}</span>' if original.get("about") else ""
            originals.append(_join([esc(original.get("reference")), about, self.pill(f"level-{_token(original.get('level'))}", level),
                                    self.address(original.get("link"))]))
        return (f'<article class="lens-card" id="lens-{esc(lens.get("id"))}"><h3>{esc(lens.get("name"))}</h3>'
                f'<dl>{parts}</dl>'
                + (f'<p class="lens-here">{esc(lens["here"])}</p>' if lens.get("here") else "")
                + (f'<p class="lens-rests-on">{esc(lens["rests_on"])}</p>' if lens.get("rests_on") else "")
                + f'<h4>{self.t("lens_questions")}</h4>' + self.listing([esc(q) for q in lens.get("questions") or []])
                + self.listing(originals, "originals") + "</article>")

    def thinking_view(self) -> str:
        return "\n".join(self._lens(lens) for lens in self.model["lenses"]) or self.nothing("none_thinking")

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
        elif source.get("text_note") == store.LITTLE_RUNNING_TEXT:   # saved, but its article may be missing
            flags.append(self.pill("little-running-text", labels["little_running_text"]))
            rows.append(("little_running_text", esc(labels["text_note_little_running_text"])))
        if source.get("saved_by") == "hand":
            flags.append(self.pill("saved-by-hand", labels["saved_by_hand"]))
        quotes = []
        for entry in source["quotes"]:
            fact = self.facts.get(entry["fact_id"])
            ref = self.fact_ref(fact) if fact is not None else esc(entry["fact_id"])
            quotes.append(f'<div class="source-quote">{self.quote(entry.get("quote"), entry.get("translation"), source.get("language"))}'
                          f'<p class="quote-fact">{self.t("label_fact")} {ref}</p></div>')
        quoted = [self.facts[entry["fact_id"]] for entry in source["quotes"] if entry["fact_id"] in self.facts]
        data = _item_data([_key(fact.get("company")) for fact in quoted], [fact_date(source)],
                          [fact.get("shown_status") or fact.get("status") for fact in quoted])
        return (f'<article class="source" id="{esc(source.get("id"))}"{data}><h3>{esc(source.get("id"))}: {esc(source.get("title"))} '
                f'{_join(flags)}</h3><dl>' + "".join(f"<dt>{self.t(key)}</dt><dd>{value}</dd>" for key, value in rows)
                + "</dl>" + "".join(quotes) + "</article>")

    def sources_view(self) -> str:
        return "\n".join(self._source(source) for source in self.model["sources"]) or self.nothing("none_sources")

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
        if self.model["projects"]["items"]:
            parts.append(f'<div class="counting"><h3>{self.t("how_counting")}</h3>'
                         f'<p>{self.grouping_note()}</p><p>{self.t("answer_rule")}</p></div>')
        dropped = how.get("names_dropped") or {}
        if dropped.get("companies") or dropped.get("parties"):
            parts.append(f'<p class="names-dropped">{self.fmt("names_dropped", companies=dropped.get("companies", 0), parties=dropped.get("parties", 0))}</p>')
        parts.append(self.recommendation_block(how.get("recommendation")))
        parts.append(f'<p class="compliance">{esc(self.model["compliance"])}</p>')
        confidence = self.listing([self.t(f"confidence_{level}") for level in ("high", "medium", "low")])
        scale = self.listing([f"{esc(span)}%: {self.t(key)}" for _, span, key in PROBABILITY_SCALE])
        parts.append(f'<div class="legend"><h3>{self.t("sec_legend")}</h3>{confidence}{scale}</div>')
        return "\n".join(parts)

    def recommendation_block(self, found) -> str:
        """The lens recommendation as it was made, labelled as advice that nobody checked; or, when the run holds none,
        the fixed sentence that says so."""
        heading = f'<h3>{self.t("rec_heading")}</h3>'
        if not found:
            return f'<div class="recommendation">{heading}<p class="none">{self.t("rec_none")}</p></div>'
        if found.get("damaged") and not found.get("entries") and not found.get("note"):
            return f'<div class="recommendation">{heading}<p class="none">{self.t("rec_damaged")}</p></div>'
        parts = [heading, f'<p class="unchecked">{self.t("rec_label")}</p>']
        if found.get("damaged"):
            parts.append(f'<p class="damaged">{self.t("rec_damaged_parts")}</p>')
            if found.get("flags"):
                parts.append(self.listing([esc(flag) for flag in found["flags"]], "damage"))
        if found.get("stale"):
            parts.append(f'<p class="stale">{self.t("rec_stale")}</p>')
        if found.get("note"):
            parts.append(f'<p class="recommendation-note">{esc(found["note"])}</p>')
        items = []
        for entry in found.get("entries") or []:
            facts = " ".join(self.fact_ref(link["fact"]) for link in entry["links"])
            details = [f'<span class="damage">{esc(flag)}</span>' for flag in entry.get("flags") or []]
            details += [f'{self.t("rec_part")}: {esc(entry["question_part"])}' if entry["question_part"] is not None else "",
                        f'{self.t("rec_why")}: {esc(entry["why"])}' if entry["why"] is not None else "",
                        f'{self.t("rec_facts")}: {facts}' if facts else "",
                        f'{self.t("rec_missing")}: {esc(entry["missing"])}' if entry["missing"] is not None else ""]
            marks = [f'{self.fact_ref(link["fact"])} '
                     f'{" ".join(esc(sentence) for sentence in link_sentences(link, self.labels))}'
                     for link in entry["links"]]
            items.append(f'<strong>{esc(entry["name"])}</strong>' + self.listing(details)
                         + self.listing(marks, "marks"))
        parts.append(self.listing(items, "recommendation-list"))
        line = helpers_line(found, self.labels) if items else ""
        if line:
            parts.append(f'<p class="helpers">{esc(line)}</p>')
        return f'<div class="recommendation">{"".join(parts)}</div>'

    # --- what changed since the last run ---

    def changes_view(self) -> str:
        return visuals.changes_view(self.model["changes"], self.facts) or self.nothing("none_changes")

    # --- the whole page ---

    def status_line(self) -> str:
        model, counts = self.model, self.model["status_line"]
        parts = [self.t("includes_private") if model["confidential"] else self.t("public_only"),
                 self.fmt("read_until", date=model["sources_read_until"]),
                 self.count("facts_checked", counts["confirmed"] + counts["uncertain"]),
                 self.fmt("status_single_source", n=counts["single_source"]),
                 self.fmt("uncertain", n=counts["uncertain"] - counts["single_source"]),
                 self.count("rejected", counts["rejected"])]
        if counts["not_accessible"]:
            parts.append(f'{self.t("not_accessible")}: {esc(counts["not_accessible"])}')
        return " · ".join(parts)

    def document(self) -> str:
        model = self.model
        screening = model.get("screening")
        views = [(key, "sec_options_screening" if screening and key == "options" else title, getattr(self, f"{key}_view")())
                 for key, title in _VIEWS if not (screening and key in ("projects", "timeline"))]   # a memo has no capacity moves
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
        counts = {"facts": len(self.model["facts"]), "projects": len(self.model["projects"]["items"]),
                  "connections": len(self.model["connections"]), "sources": len(self.model["sources"])}
        sections = "\n".join(f'<section class="view{" on" if number == 0 else ""}" id="view-{key}">\n'
                             f'<h2>{self.t(title)}</h2>\n{self.filter_bar(key, counts[key]) if key in counts else ""}\n{body}\n</section>'
                             for number, (key, title, body) in enumerate(views))
        # a memo shows only its findings on top: the answer bar and company pages lead to the capacity views it has not
        blocks = (self.messages_block(),) if screening else (self.company_heads(), self.answer_block(), self.companies_nav(),
                                                             self.messages_block())
        top = "".join(f"{block}\n" for block in blocks if block)
        disclaimer = self.t("disclaimer_private") if model["confidential"] else self.t("disclaimer")
        memo_kind = f'<p class="memo-kind">{self.t("screening_title")}</p>\n' if screening else ""
        memo_note = f'<p class="memo-note">{self.t("screening_note")}</p>\n' if screening else ""
        unattended = "".join(f'<p class="unattended">{self.t("unattended_lenses" if name == "lenses" else "unattended_final")}</p>\n'
                             for name in model.get("unattended", []))
        return (f'<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
                f'<meta name="color-scheme" content="light dark">\n<title>{esc(model["question"])}</title>\n'
                f'<style>\n{_read("report.css")}\n</style>\n<script>\n{_read("report.js")}\n</script>\n</head>\n'
                f'<body>\n{banners}<header class="masthead">\n{memo_kind}<h1>{esc(model["question"])}</h1>\n{memo_note}'
                f'<p class="status-line">{self.status_line()}</p>\n'
                f'<p class="built-on">{self.fmt("built_on", date=model["built_on"])}</p>\n'
                f'<p class="disclaimer">{disclaimer}</p>\n'
                f'{unattended}'
                f'<button class="print" type="button">{self.t("print")}</button>\n</header>\n'
                f'<main>\n{top}<nav class="tabs">{tabs}</nav>\n{sections}\n</main>\n</body>\n</html>\n')


def _read(name: str) -> str:
    return (_HERE / name).read_text(encoding="utf-8").strip()


def render_html(model: dict) -> str:
    return _Page(model).document()
