---
last_reviewed: 2026-11-12
review_findings: ""
created: 2026-09-06
area: "[[Second-Brain-Operations]]"
tags:
  - obsidian
  - system-design
---
# The Second Brain User Guide

## Index

```table-of-contents
style: nestedList
minLevel: 2
maxLevel: 2
exclude: /^Index$/
```

---

> A complete reference — every convention the system relies on is explained here. Read it once in full at the start, then use it as a reference. **When you enter an Area that has an approved sub-guide listed in [[#Area sub-guides — the rule and the index]], go to it first for anything specific to that Area.**

**Binding sections:** "Core concepts in detail", "Folder structure", "Tag rules", "Linking between notes", "Periodic review", and "Area sub-guides". They are binding for classification, naming and linking; the rest is explanation and reference. When the guide conflicts with something else, the higher wins: the owner's preferences, then the schema and the scripts, then `AI-Agent/rules.md`, then these sections, then [[Core-Vault-Architecture]].

---

## Philosophy: why this system

The system combines two methodologies with different purposes, and understanding the difference is the key to using it right:

- **PARA** answers: *"Where do I put this?"* — a practical organisation by actionability, built on four fixed categories.
- **Zettelkasten** answers: *"How do I think deeply and build knowledge that accumulates?"* — a system for capturing atomic ideas and linking them over the long term.

They sit on two different axes and do not replace each other. PARA cares about putting things in the right place; Zettelkasten cares about developing an idea over time. That is why the folders are split the way they are: PARA has four folders built on practical purpose, and Zettelkasten has one separate flat folder because links — not folders — are its structure.

**A basic decision:** the system does not use hierarchical Folgezettel numbering (Luhmann's `1.1a`). Wide reading across scattered topics makes a strict sequence a burden with no benefit. It relies on **backlinks + maps of content (MOC)** instead.

**An explicit operating principle:** some parts of the system were built with more structural complexity than the justified minimum, by an explicit decision of the owner, because the agent — not the owner — fills the system in with discipline. Pruning follows real use after a trial period.

---

## Core concepts in detail

### PARA — the four categories

| Category | The precise definition | Example |
|---|---|---|
| **Project** | has a specific goal and a clear end | "Ship version 2 of the website" |
| **Area** | an ongoing responsibility with no end, with a "standard" you maintain | "My job", "Staying current with a field", "Public presence" |
| **Resource** | a reference or material that helps you, not tied to one project | an article, a system prompt, a list of followed sources |
| **Archive** | anything of the three above that finished or stopped | a finished project, an inactive area |

**The golden rule:** content moves between the four categories over time, but **the categories themselves are fixed at the system level**.

**An important note:** "self-development" or "understanding oneself" is **not an Area** — it lacks actionability. That content goes straight to Zettelkasten.

### Zettelkasten — three stages (+ a parallel fourth path)

1. **Fleeting note:** a quick raw capture.
2. **Literature note:** a summary of an outside source in your own words.
2b. **Experiment note (parallel to Literature):** documents a real trial of a tool/library — install, run, results.
3. **Permanent note:** one atomic, lasting idea, derived from a Literature **or** an Experiment note.

**Why the order matters:** abstracting straight away without a raw record loses fidelity to the source — the same principle applies to Experiment notes.

### MOC — a map of content

An index of a main topic that gathers the links of the related permanent ideas. A MOC can also index Resources, not only Permanent notes — for example a "System Prompts" MOC that gathers every prompt regardless of Area, because prompt engineering is a cross-cutting interest. It is created as soon as the first real Permanent note exists.

### Research and tool tracking

- **Helper sources for a paper (a video that explains it, an article that analyses it):** each source is its own Literature note, linked to the original through the "Related sources" section.
- **Code that implements a paper's algorithm:** an Experiment note (you really run it), not Literature. The "Applies an idea/algorithm from" field links it to the paper.
- **A synthesis of several papers:** an ordinary Permanent note that links all its sources under "Derived from" — no new type or mechanism.
- **Tracking discovery sources:** one living Resource, updated in place rather than a note per source.
- **Separating learning from content:** two Areas — one whose standard is regular reading/experimenting, one whose standard is publishing. **Why:** merging them bends the motive from understanding to hunting for shiny content.
- **Linking them:** the frontmatter field `content_candidate` (boolean, default false) on Literature/Permanent/Experiment notes — the publishing Area queries it with Dataview.

---

## Folder structure

```
00-Inbox/                      <- the only gate for any new idea
01-Projects/                   <- PARA: goals with an end
02-Areas/                      <- PARA: ongoing responsibilities
    People/                      <- one note per person (the canonical name)
    Weekly-Reviews/              <- the weekly review notes
03-Resources/                  <- PARA: general references
04-Archive/                    <- PARA: everything that stopped or finished
05-Zettelkasten/
    Literature/                  <- summaries of outside sources
    Experiments/                 <- real trials of tools/libraries
    Permanent/                   <- atomic ideas, flat with no sub-folders
06-MOCs/                       <- topic indexes
Templates/                     <- Templater templates
Attachments/                   <- images and attached files
AI-Agent/                      <- the agent's operational files, for any model
    handoff.md                   <- the entry point of any new session
    scripts/                     <- Python scripts
    skills/                      <- skills and their short contracts
    traps/                       <- the traps registry, one file per trap
    schema/                      <- the binding frontmatter schema
```

**The anti-duplication rule:** the folder is the source of truth for the PARA category. A `type` field exists only inside `05-Zettelkasten/` — the sub-folder plus `type` together fix the note's kind precisely.

**A system folder:** `AI-Agent/` is like `Templates/` and `Attachments/`: outside PARA, English names, operational files for any AI agent that works on the vault — not knowledge notes and not files specific to one model. Tool details are in [[Agent-Capabilities]].

---

## Installed plugins

| Plugin | What it does exactly | When you touch it |
|---|---|---|
| **MCP Connector** | opens the vault to an MCP-compatible AI client that reads/writes/searches directly | rarely — in the background |
| **Git** | backup and sync through a remote repository | daily |
| **Templater** | dynamic content at creation time from a template | automatic, behind QuickAdd |
| **Dataview** | turns frontmatter into a queryable database | automatic |
| **QuickAdd** | a shortcut that opens a template in a set folder with one press | every new capture |
| **Linter** | formats notes (YAML lists in block style) | automatic |

**This table is partial** — the full inventory is in [[Agent-Capabilities]]. Some plugins **edit files automatically whatever the source of the save**, and some force standard formats that must be respected; the agent reads that section before writing.

---

## Frontmatter schema

This section is a pointer only. The binding schema is one file: `AI-Agent/schema/frontmatter.yaml`, with every key, its type, who reads it, and the class that applies to it by folder. `audit` reads the schema directly, so a wrong key stops the commit.

Usage rules the schema does not hold:
- `status` is used in Projects and Areas, not in Resources.
- In Zettelkasten, `type` with the sub-folder fixes the kind. `source` is the source link in Literature and the tool link in Experiment, and is not put in Permanent. `tool` is for Experiment only.
- `content_candidate: true` when a note is a candidate for public content.

---

## Templates

Twelve templates sit at the root of `Templates/`: `Area`, `Project`, `Resource`, `Person`, `Permanent`, `Fleeting`, `Literature`, `MOC`, `Weekly-Tracker`, `Changelog`, `Experiment` and `Task-Spec` (indexed in [[MOC - Templates]]). Each one carries its guidance as HTML comments at the end, so the note body stays clean.

**Rules:**
- A note made through MCP does not run Templater: read the template as a skeleton, fill `created` and the title yourself, and leave no literal `<% tp %>` behind.
- A folder with no official template produces inconsistent notes — every PARA folder has one.

## QuickAdd shortcuts — daily use

Five choices create a note from its template in `00-Inbox`: **New Fleeting**, **New Literature**, **New Permanent**, **New Project** and **New MOC**. Capture first, then classify each note when you process the inbox.

---

## Tag rules

1. Lower case always. 2. kebab-case. 3. One tag per concept: before creating a tag check `list_tags` and reuse the existing spelling; do not change an existing tag's spelling over singular/plural — the forbidden thing is a split tag, and the `FM-tag-variant` audit check reports it. 4. At most two nesting levels. 5. For free topics only; do not repeat `status`/`area`. 6. Tags are added at processing time, not at capture. 7. Use the auto-suggestion. 8. A monthly review merges duplicates.

**A documented exception:** the achievement-classification tags in the Weekly Tracker (type + impact) are always in English.

**Procedural tags** (they decide what I do with a line or a file) are documented where their behaviour is defined; **topical tags** describe a file's subject and are inventoried by `list_tags`, never by a hand-written vocabulary.

---

## Linking between notes

**A link in the body:** `[[Note name]]` — in the "Connections" section (Permanent), "Core ideas" (MOC), "Related sources" (Literature).

**A link from a Properties field:** for the `area` field.

**Verification:** the "Linked mentions" section of the linked note.

**A mandatory rule:** every Permanent note needs a link to another permanent idea + at least one MOC.

**The "related sources" pattern (symbolic in both directions):** link from either side; Linked Mentions shows the relation in both directions.

**The synthesis-note pattern:** the same mechanism as an ordinary Permanent note — it links all its sources under "Derived from", with no new type or folder.

**Turning a temporary tag into a permanent link:** a tag is a temporary search tool at capture, not a permanent analytic classification. When enough (3 or more) notes gather under one tag, a real MOC is created that links them with explicit `[[ ]]` links, and it becomes the single note that carries that tag — applied specifically to [[Idea-Garden]].

**The canonical-name rule:** for any person in the people area, the person's file name is the single canonical name. Every reference anywhere in the system uses the same `[[ ]]` link, so their contributions show up in Linked Mentions with no separate relation field.

---

## A day in the life of the system

1. **Capture:** an idea or a link → a Fleeting note in `00-Inbox` through QuickAdd, no thinking about classification.
2. **Process (at a set time):** read the inbox; promote a source to Literature, a trial to Experiment, an idea to Permanent; link it to a MOC; add tags now.
3. **Work:** active projects live in `01-Projects` with a Progress Log; decisions and blockers are logged as they happen.
4. **Close:** end of session — commit (Git: Commit-and-sync).

---

## Periodic review — a maintenance agent, not a human checklist

> These are real discovery tasks that use the agent's available tools (`find_broken_links`, `find_orphaned_notes`, `get_backlinks`, `search_vault_simple`) — not a manual "open and look". Any promotion or actual move goes through a proposal to the owner and the owner's approval first (the PARA move rule).

### Weekly — the weekly-review skill
The whole weekly procedure (inbox triage, project status, active Areas and closing their weeks, content candidates, broken/orphan link checks, the "heading is a promise" check) has one source: `AI-Agent/skills/weekly-review/SKILL.md`. The scheduled task loads it and does not read this guide in full. Any change to the weekly procedure is made there, not here.

### Monthly — proactive discovery
- **Lesson-promotion review:** go through the changelogs of the `active` Areas and judge each new lesson retroactively: is it based on a principle independent of the Area's specifics, or did it recur in two different Areas? If yes, add the tag `#candidate-for-general-lesson` and propose its promotion to the general lessons ([[Lessons]]) — never classified at the moment of writing.
- **Idea garden review:** open [[Idea-Garden]] in full (browse, not search). For every active seed that found no recurrence, raise its counter `(review N/5)`; a seed that reaches 5 moves to "Dormant seeds" — never deleted. A tag with 3 or more seeds is offered to the owner as a real MOC.
- **Check the guidance files:** for every file with `last_reviewed` (this guide, the sub-guides, [[Agent-Capabilities]], [[Architecture-Decision-Records]]) check whether 30 days passed without an update — if so, verify it is still accurate and update `last_reviewed` and `review_findings`.
- Open every MOC and confirm the new additions. Look for orphan notes. Merge duplicate tags.

### Quarterly
- Review the Areas with `review_tier: dormant` — did they become active again?
- Review the "Dormant seeds" section of the idea garden for a link that the quick monthly reviews missed.

---

## Git and sync — daily use

`Git: Commit-and-sync` at the end of every session. `.gitignore` excludes tokens automatically. Every commit passes the audit ratchet through `.githooks/pre-commit`; a blocking error stops the commit until it is fixed.

---

## Area sub-guides — the rule and the index

An Area keeps its own rules in a separate sub-guide named `guide-<area-name>.md` and its history in a separate changelog named `changelog-<area-name>.md` (from `Templates/Changelog.md`) — both are created only when there is a real behavioural need (classifications, promotion criteria, recurring design decisions), not automatically for every Area. A sub-guide is the first stop for anything specific to its Area; this guide stays general. Each active sub-guide carries `review_tier: active` and a periodic-review section that the weekly review follows; a dormant one carries `review_tier: dormant` and waits for the quarterly review.

| Area | Sub-guide | Review tier |
|---|---|---|
| (none yet — add a row when the first sub-guide is created) | | |

---

## Privacy and hidden folders

- Secrets never enter the vault (rule RL-0002); write only the name of where a secret lives.
- Personal data of other people is stored only after consent, and only what the work needs.
- `.obsidian/` plugin settings and any `.vault-release/` folder are local state; `.gitignore` decides what leaves the machine.

## Connecting to models (MCP) — how it is used in practice

The MCP Connector exposes the vault to an AI client. Two layers exist and must not be confused: the **client layer** (the app defers connector tools, so a tool search runs before first use in each chat) and the **server layer** (the plugin's own tool activation). The full tool inventory, the traps registry and the loading rules are in [[Agent-Capabilities]]. Before the first write in any chat, query the traps registry for the tools you will use.

---

## General lessons

The lessons learned from corrected mistakes live in [[Lessons]] — one line per lesson, grouped by theme. Lessons from one Area that turn out to rest on an outside principle are promoted there during the monthly review.

## Glossary

| Term | Meaning |
|---|---|
| **PARA** | Projects, Areas, Resources, Archive — organisation by actionability |
| **Zettelkasten** | a slip-box method: atomic notes linked over time |
| **MOC** | map of content — an index note of a topic |
| **Fleeting / Literature / Experiment / Permanent** | the stages of a note, from raw capture to a lasting idea |
| **Backlink / Linked mentions** | the notes that link to this one, shown automatically |
| **Frontmatter** | the YAML block at the top of a note that holds its fields |
| **Gate / ratchet** | the commit check that blocks on errors and never lets warnings grow |
| **Trap** | a documented tool or environment pitfall, one file in `AI-Agent/traps/` |
| **Skill** | a packaged procedure with a short contract, in `AI-Agent/skills/` |
| **Handoff** | the entry file that tells a new session the invariants and where everything lives |
| **Progress Log** | dated one-line checkpoints in the note where the work lives |

## Final checklist before you start

- [ ] `./setup.sh` ran, `.venv` exists, and the pre-commit hook is enabled.
- [ ] `.venv/bin/stratum-state` prints the current state without errors.
- [ ] Plugins are enabled: Templater, Dataview, QuickAdd, Git, Linter.
- [ ] A first note was captured into `00-Inbox` through QuickAdd.
- [ ] `audit.py --ratchet` shows GATE CLEAR.
