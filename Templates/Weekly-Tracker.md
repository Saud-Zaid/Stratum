---
status: active
area: ""
tags:
  - weekly-tracking
created: <% tp.date.now("YYYY-MM-DD") %>
---

# <% tp.file.title %> — current week

<!-- A general pattern for tracking weekly tasks/achievements inside any Area — extracted from the Current-Week.md model after a standards-based review (see the guide). Before cloning it for a new Area, update the area field above and the file name itself (instead of Current-Week, pick a name tied to this area to avoid name clashes when more than one weekly tracker exists). The changelog of this file's design (not the task log) goes to `changelog-<area>.md` — there is no "changelog" section here, to avoid two places for the same purpose. -->

> A task and its completion on the same line: `- [ ]` when the task is announced, it becomes `- [x]` on completion. Every day is a separate sub-heading.

**Classifying each line (two tags at the end of the line, always in English):**
- **Type:** `#report` `#automation` `#dashboard` `#problem-solving` `#data-infra` `#learning` `#meeting` (or another type as the context requires)
- **Impact:** `#impact-high` `#impact-medium` `#impact-low`
- They are added when I am told about the task/achievement — if the description does not make the type or impact clear, ask then instead of guessing.
- **One compound question:** the type and the impact are always asked in the same single message, never in two separate consecutive rounds — one semantic category (task classification), not two.

**Deadline — optional:**
- For any task with a pressing date (a meeting at a set time, or a completion deadline), add `📅 YYYY-MM-DD` at the end of the line — a standard format that Dataview/Tasks read automatically, not free text.
- In the weekly review, any open `[ ]` task whose date is near or past today is named explicitly.

**When closing any task (`[x]`):**
- One light question: *"What exactly did you do, and why did it matter?"* — if there is nothing worth adding, move on with no addition.
- If there is an answer, it is written **raw as it is** as a folded line directly under the task (no immediate classification) — the decision is deferred entirely to the weekly review.
- **If the answer is "nothing worth adding", it is written explicitly as a folded line** (not left silent) — it records that the question was asked.

**Postponed/blocked state:** a task not yet done is never closed `[x]`, but there is a difference between two states:
- **Postponed** (no symbol, a folded line `↳ postponed: <reason>`): the reason concerns the work logic itself — a priority change, a business decision, a change in how it is done.
- **Blocked ⏸️** (a folded line `↳ blocked ⏸️: waiting for <who/what>`): blocked technically — waiting for someone else to finish something before you can continue, unrelated to a business decision.
- Both stay a normal `[ ]`, are exempt from the light closing question, and are never deleted.

**The extended-task mechanism:**
1. **A simple task** → a normal checkbox line under the day, with the two classification tags.
2. **An extended task** → if it goes past a week, or its details grow too long for one line, or you ask to promote it then — it is promoted to a separate file in `01-Projects/` using the `Project.md` template, linked to the right `area` with the field `promoted_from_weekly: true`. The line here becomes a link.
3. **When the Project itself is closed:** the three questions (problem / solution / lesson) are always mandatory.
4. **Duplication warning:** on promotion, the accumulated details are deleted from this file at once — keeping them in both places breaks lesson 1 of the guide.

## <% tp.date.now("dddd D MMMM") %>
