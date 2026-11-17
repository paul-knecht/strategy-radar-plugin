(function () {
  "use strict";
  // Without this class every view stays visible one after another; the style sheet hides views only under html.js.
  document.documentElement.classList.add("js");

  function showViews(names) {
    var views = document.querySelectorAll(".view");
    for (var i = 0; i < views.length; i++) {
      views[i].classList.toggle("on", names.indexOf(views[i].id.replace(/^view-/, "")) !== -1);
    }
  }

  function showView(name) {
    showViews([name]);
    var tabs = document.querySelectorAll(".tabs button[data-view]");
    for (var j = 0; j < tabs.length; j++) {
      var active = tabs[j].getAttribute("data-view") === name;
      tabs[j].classList.toggle("on", active);
      tabs[j].setAttribute("aria-pressed", active ? "true" : "false");
    }
  }

  function currentView() {
    var view = document.querySelector(".view.on");
    return view ? view.id.replace(/^view-/, "") : "facts";
  }

  function viewOf(element) {
    var view = element.closest(".view");
    return view ? view.id.replace(/^view-/, "") : null;
  }

  // Show the view that holds the target, open every <details> around it, and scroll to it.
  function goTo(id, viewName) {
    var target = document.getElementById(id);
    if (!target) {
      return false;
    }
    // a target outside every view (a key message, say) leaves the view as it is
    var view = viewName || viewOf(target);
    if (companyMode && view && COMPANY_VIEWS.indexOf(view) === -1) {
      leaveCompany(false);   // the page of a company shows three views only
    }
    // a target the filter hides is shown by taking the filter off; in a company's page, by leaving the page
    if (target.closest(".filtered-out")) {
      clearFilters();
      if (companyMode && target.closest(".filtered-out")) {
        leaveCompany(false);
      }
    }
    if (view && !companyMode) {
      showView(view);
    }
    for (var node = target; node; node = node.parentElement) {
      if (node.tagName === "DETAILS") {
        node.open = true;
      }
    }
    target.scrollIntoView({ block: "start" });
    return true;
  }

  document.addEventListener("click", function (event) {
    var trigger = event.target.closest ? event.target.closest("[data-view]") : null;
    if (!trigger) {
      return;
    }
    var href = trigger.getAttribute("href");
    if (href && href.charAt(0) === "#") {
      if (goTo(decodeURIComponent(href.slice(1)), trigger.getAttribute("data-view"))) {
        event.preventDefault();
      }
    } else {
      showView(trigger.getAttribute("data-view"));
    }
  });

  // The filters. One state is shared by every bar, so it holds while the reader moves between the tabs.
  var state = { company: "all", date: "all", from: "", to: "", status: "all", access: "all", question: "all" };
  var LISTS = { facts: "details.fact", projects: "details.project", connections: "tr.connection", sources: "article.source" };
  var ITEMS = "details.fact, details.project, tr.connection, article.source, .message-item, .baseline";
  var COMPANY_VIEWS = ["projects", "connections", "sources"];
  var companyMode = null;   // the key of the company whose page is open, else null
  var viewBeforeCompany = "facts";
  var root = document.documentElement;

  // An item that lacks an attribute is not sorted by it (a baseline has no date, a fact no access).
  function tokensOf(item, name) {
    var value = item.getAttribute(name);
    return value === null ? null : value.split(" ");
  }

  function hasToken(item, name, chosen) {
    var tokens = tokensOf(item, name);
    return chosen === "all" || tokens === null || tokens.indexOf(chosen) !== -1;
  }

  // A date matches when it starts with the chosen year and lies between the chosen months (each optional); a date
  // that is only a year matches when its year lies between their years. An undated item matches only with no date
  // chosen, and a start after the end matches nothing.
  function hasDate(item, chosen) {
    var dates = tokensOf(item, "data-date");
    if (dates === null || (chosen === "all" && !state.from && !state.to)) {
      return true;
    }
    if (state.from && state.to && state.from > state.to) {
      return false;
    }
    for (var i = 0; i < dates.length; i++) {
      var size = dates[i].length < 7 ? 4 : 7;
      var part = dates[i].slice(0, size);
      if (dates[i] !== "" && (chosen === "all" || dates[i].indexOf(chosen) === 0)
          && (!state.from || part >= state.from.slice(0, size)) && (!state.to || part <= state.to.slice(0, size))) {
        return true;
      }
    }
    return false;
  }

  function shows(item) {
    // the key messages are sorted only on a company's page
    if (item.classList.contains("message-item") && !companyMode) {
      return true;
    }
    return hasToken(item, "data-company", state.company) && hasDate(item, state.date)
      && hasToken(item, "data-status", state.status) && hasToken(item, "data-access", state.access)
      && hasToken(item, "data-question", state.question);
  }

  function anyShown(items) {
    for (var i = 0; i < items.length; i++) {
      if (!items[i].classList.contains("filtered-out")) {
        return true;
      }
    }
    return false;
  }

  // The items from the one after `start` up to the next company heading, early-signals block or block of totals.
  function itemsAfter(start) {
    var found = [];
    for (var next = start.nextElementSibling; next; next = next.nextElementSibling) {
      if (next.matches("h3[data-company], .early-signals, .projects-more")) {
        break;
      }
      if (next.matches(ITEMS)) {
        found.push(next);
      }
    }
    return found;
  }

  function hideIfNone(block, items) {
    block.classList.toggle("filtered-out", items.length > 0 && !anyShown(items));
  }

  function applyFilters() {
    var items = document.querySelectorAll(ITEMS);
    for (var i = 0; i < items.length; i++) {
      items[i].classList.toggle("filtered-out", !shows(items[i]));
    }
    // a heading, a block or a table whose items are all hidden goes with them
    var headings = document.querySelectorAll("h3[data-company]");
    for (var j = 0; j < headings.length; j++) {
      hideIfNone(headings[j], itemsAfter(headings[j]));
    }
    var blocks = document.querySelectorAll(".early-signals");
    for (var k = 0; k < blocks.length; k++) {
      hideIfNone(blocks[k], blocks[k].querySelectorAll("details.fact"));
    }
    var tables = document.querySelectorAll(".table-wrap");
    for (var m = 0; m < tables.length; m++) {
      hideIfNone(tables[m], tables[m].querySelectorAll("tr.connection"));
    }
    var messages = document.getElementById("messages");
    if (messages) {
      hideIfNone(messages, messages.querySelectorAll(".message-item"));
    }
    showCounts();
  }

  // Each bar says how many items of its list the filter hides.
  function showCounts() {
    var bars = document.querySelectorAll("form.filters");
    for (var i = 0; i < bars.length; i++) {
      var list = bars[i].getAttribute("data-list");
      var line = bars[i].querySelector(".filter-count");
      var view = document.getElementById("view-" + list);
      if (!line || !view || !LISTS[list]) {
        continue;
      }
      var items = view.querySelectorAll(LISTS[list]);
      var shown = 0;
      for (var j = 0; j < items.length; j++) {
        if (!items[j].classList.contains("filtered-out")) {
          shown++;
        }
      }
      line.textContent = (shown === items.length
        ? line.getAttribute("data-all")
        : line.getAttribute("data-some").replace(/\{shown\}/g, shown).replace(/\{n\}/g, items.length)
            .replace(/\{hidden\}/g, items.length - shown))
        + (state.from && state.to && state.from > state.to ? ". " + line.getAttribute("data-reversed") : "");
    }
  }

  // Put the state into every bar; on a company's page the company is fixed.
  function showControls() {
    var selects = document.querySelectorAll("form.filters select, form.filters input");
    for (var i = 0; i < selects.length; i++) {
      selects[i].value = state[selects[i].name];
      selects[i].disabled = selects[i].name === "company" && companyMode !== null;
    }
  }

  function refresh() {
    applyFilters();
    showControls();
  }

  function clearFilters() {
    state.from = state.to = "";
    state.date = state.status = state.access = state.question = "all";
    if (!companyMode) {
      state.company = "all";
    }
    refresh();
  }

  document.addEventListener("change", function (event) {
    var select = event.target;
    if (select.closest && select.closest("form.filters") && state.hasOwnProperty(select.name)) {
      // a month field holds YYYY-MM or nothing (a browser without a month picker shows a text field, whose type
      // is then "text", and lets the reader type anything)
      var month = /^[0-9]{4}-[0-9]{2}$/.test(select.value) ? select.value : "";
      state[select.name] = select.name === "from" || select.name === "to" ? month : select.value;
      refresh();
    }
  });

  document.addEventListener("submit", function (event) {
    if (event.target.closest && event.target.closest("form.filters")) {
      event.preventDefault();
    }
  });

  // A company's page: the same report, filtered to that company, with its head on top and three views and the messages.
  function setHeads(key) {
    var heads = document.querySelectorAll("[data-company-head]");
    for (var i = 0; i < heads.length; i++) {
      var chosen = heads[i].getAttribute("data-company-head") === key;
      heads[i].hidden = !chosen;
      heads[i].classList.toggle("on", chosen);
    }
  }

  function openCompany(key) {
    if (!companyMode) {
      viewBeforeCompany = currentView();
    }
    companyMode = key;
    root.classList.add("company-mode");
    setHeads(key);
    state.company = key;
    showViews(COMPANY_VIEWS);
    refresh();
    var head = document.querySelector('[data-company-head="' + key + '"]');
    head.scrollIntoView({ block: "start" });
  }

  function leaveCompany(scroll) {
    companyMode = null;
    root.classList.remove("company-mode");
    setHeads(null);
    state.company = "all";
    showView(viewBeforeCompany);
    refresh();
    var buttons = document.getElementById("companies");
    if (scroll && buttons) {
      buttons.scrollIntoView({ block: "start" });
    }
  }

  document.addEventListener("click", function (event) {
    var source = event.target.closest ? event.target : null;
    if (!source) {
      return;
    }
    var page = source.closest("[data-company-page]");
    if (page && document.querySelector('[data-company-head="' + page.getAttribute("data-company-page") + '"]')) {
      event.preventDefault();
      openCompany(page.getAttribute("data-company-page"));
      return;
    }
    var filter = source.closest("[data-filter-company]");
    if (filter) {
      // handled here and not by the address, so that it works again after the reader has moved to another tab
      event.preventDefault();
      state.company = filter.getAttribute("data-filter-company");
      refresh();
      goTo("view-" + (filter.getAttribute("data-filter-view") || "facts"));
      return;
    }
    var question = source.closest("[data-filter-question]");
    if (question) {
      // the line under the answer: the facts list, filtered to the moves it counts apart
      event.preventDefault();
      state.question = question.getAttribute("data-filter-question");
      refresh();
      goTo("view-facts");
      return;
    }
    if (source.closest("[data-company-back]")) {
      event.preventDefault();
      leaveCompany(true);
    }
  });

  // Printing: open every <details> so each fact shows its quote, then put them back as they were.
  var openBeforePrint = [];

  window.addEventListener("beforeprint", function () {
    openBeforePrint = [];
    var all = document.querySelectorAll("details");
    for (var i = 0; i < all.length; i++) {
      openBeforePrint.push(all[i].open);
      all[i].open = true;
    }
  });

  window.addEventListener("afterprint", function () {
    var all = document.querySelectorAll("details");
    for (var i = 0; i < all.length && i < openBeforePrint.length; i++) {
      all[i].open = openBeforePrint[i];
    }
    openBeforePrint = [];
  });

  document.addEventListener("click", function (event) {
    if (event.target.closest && event.target.closest("button.print")) {
      window.print();
    }
  });

  // A link without data-view (a company button, a link to a key message) reaches its target the same way.
  function goToHash() {
    if (location.hash.length > 1) {
      goTo(decodeURIComponent(location.hash.slice(1)));
    }
  }

  document.addEventListener("DOMContentLoaded", goToHash);
  window.addEventListener("hashchange", goToHash);
})();
