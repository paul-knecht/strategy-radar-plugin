---
name: screen
description: Starts a Strategy Radar screening run on one startup - a first-pass investment memo on its company, market, competition, team, traction and risks, from public sources, in which every fact carries a quote the program checked. Takes three answers - the startup's name and website, whether it is real, and the question - proposes the rest of the pack from a web search, each item with the page it was found on, and hands over to the run after one confirmation. Use when someone wants to screen a startup, write a first-pass deal memo, or look at a startup as an investor.
---

# Screen a startup

You help one person make a pack for one startup and then start a screening run on it. A screening run writes a first-pass memo. It prepares the investors' decision and does not make it: it ends with what would have to be true to invest and the questions that public sources leave open, never with "invest" or "pass", and never with a score.

Say this first, before any question, in plain words:
- The memo rests only on public sources the run saves, and every fact in it carries a quote the program found word for word. A startup's own figures are its claims, and the memo says so.
- You give the startup's name and website, say whether it is real, and give the question. The skill then searches the web and proposes the rest of the pack, each item with the page where it was found or the rule that set it; you keep or strike them in one answer. Nothing is added from memory. A pack for a real startup that you may share later must contain no non-public information. The search for competitors and pages has run in three real screening sessions; the proposals for the rest of the pack have run in one. After that, the run goes on without stopping: it chooses the lenses the lens advisor recommends and builds the report when the checks pass. It stops and asks you only when the advisor has no usable recommendation or a check fails, and it stops when a command is refused.

## Making the pack

Read `${CLAUDE_PLUGIN_ROOT}/skills/new-pack/SKILL.md` with your file tool and follow it, question by question and rule by rule. For a real startup it sends you to `${CLAUDE_PLUGIN_ROOT}/references/propose-pack.md`, the search and the one confirmation; follow that as new-pack says. These changes hold, and no others:

- The opening above replaces new-pack's "Say this first": do not say new-pack's opening as well.
- The company is the startup. At new-pack's first question its website is expected: the search starts from it, and new-pack's rule for a given website holds. When the person gives no website, go on: the propose step searches by the name.
- At the question about the strategic question, offer this one as a default, framed by the person: "What would have to be true to invest in <startup>?" The person may give another.
- The pack has `"screening": true` and `"time_window_months": 120`, the most a pack allows, so that the founders' earlier work and the early funding rounds fall inside the window. In the proposals the window is shown as set, not numbered, and it stays even if the person strikes it. When the questions of `${CLAUDE_PLUGIN_ROOT}/references/pack-questions.md` are asked, skip the one about how far back to search, and say why.
- Units are the ones the startup's figures use, such as EUR, employees or customers, as the opened pages or the person give them.

## After the pack

When `radar check-pack` shows no problems, say what was made, as new-pack says. Then say that the run comes next, and start `/strategy-radar:run` with the pack's strategic question, word for word, as the question, naming the new pack file. The run reads the screening playbook and the screening-memo reference because the pack says `"screening": true`.
