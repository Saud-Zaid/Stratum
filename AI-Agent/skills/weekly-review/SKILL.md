---
name: weekly-review
description: "Run the weekly Second Brain review (GTD Get Clear + Get Current) and write its note in 02-Areas/Weekly-Reviews/. Trigger on: the scheduled weekly review, or the vault owner asking for a weekly review. DO NOT trigger for: monthly or quarterly steps (they stay in the guide), or a single Area's day-to-day tracking."
tags:
  - ai-agent
  - skill
created: 2026-09-28
args:
  input: a scheduled weekly run or the vault owner's request for a weekly review
  output: 02-Areas/Weekly-Reviews/YYYY-MM-DD.md review note (<= 4 KB)
  consumer: the weekly scheduled run, owner-triggered
---

# Weekly Review Skill

Single source for the weekly review. The scheduled task only loads this file; the guide's weekly part points here.

## Principles

- Read by section, never whole notes over 4 KB. The guide is not read in full for this review.
- Scripts first: state, gate and due dates come from `state` and `audit`, not from opening notes.
- The review note is an index, not a report: one line + link per finding. Details go to the owning note's own log (`## Progress Log` / `## Changelog`), as the handoff Progress Log rule says.
- Unattended by default: anything that needs the vault owner's call (promotion, PARA move, delete, a new Project) is listed under decisions, not executed.

## Steps

1. **Start protocol.** Read `AI-Agent/handoff.md`; query the trap registry for the tools you will write with (`patch_vault_file`, `create_vault_file`).
2. **State.** `.venv/bin/python AI-Agent/scripts/state.py` and `.venv/bin/python AI-Agent/scripts/audit.py --ratchet`. Keep the gate line, the due list and any `error`/`DUE-now` rows. Do not restate the rest.
3. **Get Clear — Inbox.** List `00-Inbox/` (skip `README.md`). For each note decide: promote (Literature / Experiment / Permanent), merge into an existing Project or Area, or propose deletion. Promotions that change meaning go to decisions.
4. **Get Current — Projects.** From the `state` active list: for each project with no progress line in 14 days, or with a passed `due`, propose a status (`active`, `on-hold`, `done`, `someday`). Change `status` only when the note itself proves it (all steps ticked, or the owner said so in its log).
5. **Get Current — active Areas.** For each sub-guide with `review_tier: active` (search the frontmatter, do not hard-code the list), read only its periodic-review section and follow it. This includes closing a tracked week when its week has ended. `review_tier: dormant` Areas wait for the quarterly review.
6. **Deferrals.** Take the `## deferrals` block of `state` and the `DEF-*` rows of `audit`. Under `## Deferrals due` list each item that is dated within 7 days or whose condition is met: one line, its `D-NN`, owner, and the `spec::` link. Items with `snoozed:: 2` and every `DEF-snooze` go to `## Decisions waiting` marked "decision needed" (execute or kill: no third snooze). A snooze the owner asks for is `snoozed += 1` plus a one-line reason next to the item. Flag an Area holding more than 10 open items, or more than 2 falling in the same week. `DEF-archived` and `DEF-untracked` appear as one count line each, never as a list, unless new ones appeared this week.
7. **Content candidates.** Query notes with `content_candidate: true`; propose, do not create, a Project for each.
8. **Vault health.** `find_broken_links` (note-level links; `audit` covers heading links only, TR-0018) and `find_orphaned_notes` (skip README and `Templates/`). One line each; list the notes only when there are new ones.
9. **Title promise.** For the guide and each active sub-guide changed in the last 7 days (the `state` git list), run `.venv/bin/python AI-Agent/scripts/outline.py` and read only the changed H2 sections: does each still match its heading? A drift becomes a proposed ADR in [[Architecture-Decision-Records]] for the owner, never an automatic fix. Unchanged files are skipped.
10. **Links.** For notes promoted in step 3: one link to another permanent note and one MOC.
11. **Write the note** (template below), then verify it with `search_vault_simple` on its title line and `.venv/bin/python AI-Agent/scripts/audit.py --path 02-Areas/Weekly-Reviews/`.
12. **Report** to the vault owner in one short message with the note's path. Do not wait for a reply.

## Output Template

Path `02-Areas/Weekly-Reviews/YYYY-MM-DD.md` (the run date). Each finding one line with a `[[link]]`. Target <= 4 KB.

```markdown
---
date: YYYY-MM-DD
tags:
  - weekly-review
created: YYYY-MM-DD
---

# Review YYYY-MM-DD

## Status
## Inbox
## Projects
## Active Areas
## Deferrals due
## Decisions waiting
## Summary
```

Empty section → one line "nothing this week". A gap since the last review longer than 7 days → say so in `## Status`, do not expand the note.
