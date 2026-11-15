(function () {
  "use strict";
  // Without this class every view stays visible one after another; the style sheet hides views only under html.js.
  document.documentElement.classList.add("js");

  function showView(name) {
    var views = document.querySelectorAll(".view");
    for (var i = 0; i < views.length; i++) {
      views[i].classList.toggle("on", views[i].id === "view-" + name);
    }
    var tabs = document.querySelectorAll(".tabs button[data-view]");
    for (var j = 0; j < tabs.length; j++) {
      var active = tabs[j].getAttribute("data-view") === name;
      tabs[j].classList.toggle("on", active);
      tabs[j].setAttribute("aria-pressed", active ? "true" : "false");
    }
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
    showView(viewName || viewOf(target) || "summary");
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

  document.addEventListener("DOMContentLoaded", function () {
    if (location.hash.length > 1) {
      goTo(decodeURIComponent(location.hash.slice(1)));
    }
  });
})();
