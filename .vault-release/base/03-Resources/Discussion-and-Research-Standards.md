---
status: active
area: "[[Second-Brain-Operations]]"
tags:
  - context-engineering
created: 2026-09-15
---

# Discussion and Research Standards

> **Binding for every design discussion session** in the vault. It grew from a repeated mistake: importing outside solutions designed for a context unlike ours, and critiques that did not cover every angle.

## Rule one — separate the principle from the mechanism

Two separate things are drawn from any outside source:
- **The principle** — the general idea. It may transfer even when the source comes from a completely different world.
- **The mechanism** — how it was implemented there. It is examined separately by the gate below, and its failure does not drop the principle.

**The mistake this rule came from:** the mechanism was taken together with the principle in maturity models built for organisations with teams and custodians, cryptography built for an adversarial threat model, storage stress built for millions of series, an engine-incremented counter, and a timestamp that warehouses produce automatically.

## The gate — applied to the mechanism, not the source

| # | Question | The mechanism fails if |
|---|---|---|
| 1 | How many actors does it assume? | it assumes several actors and coordination among them (our vault: two — the owner and the agent) |
| 2 | What is the threat model? | it assumes a deliberate adversary. **Exception:** imported content has a real threat model of narrow scope |
| 3 | What is the scale difference? | it needs a scale we do not reach. **The difference never drops the principle** |
| 4 | What is its technical foundation? | it requires an engine, a pipeline, a signature or a counter we do not have |
| 5 | Who executes it? | it falls outside the ability of the owner and the agent together |

**When a mechanism fails:** the principle is recorded explicitly, with a note that its mechanism does not transfer and why. The source is not removed from the record.

## Critique angles — ordered by effect

**Dropping — one negative answer is enough to drop the proposal:**
1. **Who consumes it?** no real automatic consumer, or one planned for a set date → it falls
2. **Is the problem measured?** unmeasured → no proposal before measurement
3. **What does it cost in tokens?** a cost above the measured return → it falls
4. **Structural, or does it rely on attention?** it relies on the agent's commitment or the owner's memory → it falls or is redesigned

**Improving — mentioned, and do not drop a proposal alone:**
5. Who guards it, and is a guard possible at all
6. The exit path: how it is neglected and removed later
7. Conflict with an existing ADR or decision
8. Noise: how many alarms it produces on the day it is enabled
9. The effect on other groups
10. **The "do nothing" option** — raised explicitly with every item, not implicitly

## The stopping criterion

Deepening a discussion stops at the first of these:
- two rounds of proposal/critique/research on the same item with no substantial change in the conclusion
- the conclusion became "do nothing" in two consecutive rounds
- the item began to branch into items that belong to another group
- the last research added no new principle, only support for what had settled

**On stopping:** record what settled, move what branched to its group, and reopen the item only with new evidence.

## Methodology for examining any section — in order

Binding for every section before the discussion on it opens:

1. **Identify the section's basic goals** — what it is supposed to achieve, not what its bullet points say.
2. **Read what was discussed before** — its inbox draft if any, the section in the parent note, and what was recorded earlier in the group's log.
3. **Identify the angles not yet discussed** — written explicitly as a list, since it is the source of new value. Open items in the earlier draft and the "limits of this analysis" passages are its richest sources.
4. **Write new proposals on the new angles specifically** — do not reproduce what was discussed.
5. **The cycle:** constructive critique → research of the standards and applied solutions → a second round.
6. **Stop** by the stopping criterion above, then record.

**A precedent that proves the value of step 3:** a draft recorded that "the erosion of the trust boundary over time has no standard treatment that I found". The treatment exists in a whole literature (persistent memory poisoning) — it surfaced only because the angle was written explicitly and searched under its own name.

**Files in `00-Inbox` are a temporary reference, not a source of decision**

Analysis drafts and "session output" files in `00-Inbox` **are read as a reference** when examining any topic (step 2 of the methodology), and their decisions are not adopted as they are: every topic is re-examined through the full cycle, and what settled moves to its group's log.

**Their fate is deletion** when the planning and execution of their groups finish — so no permanent link is built on them, and no care is taken to unify their numbering or dates with the logs.

## The sample rule

Proposal and critique are made **at the level of the system and the families as an applicable model**, not on one particular sample. A sample serves as **evidence** that the problem exists, not as the **basis** for designing the solution — otherwise the design bends to serve it and not the rest of the vault.

## The measurement-verification rule

Any regular expression run over the body **is verified by opening one file** before its result is relied on.

**A zero or low result is treated as a measurement failure until the opposite is proved.**

All documented measurement errors are of one kind: a regular expression over non-English text that **caught less than what exists**:
- heading links `[[file#heading]]` were counted as tags
- a bold `**Measured On**` form was not caught, giving zero conflicts instead of eighteen
- a word carrying a definite article was not caught, giving 2 of 10 instead of 10 of 10

**A one-directional bias is the danger:** the result is a small number or zero, so it reads "no problem", and a decision **not to act** is built on it — the direction our decisions already lean toward. So the error pushes the same way as the lean, and nothing corrects it.

**The procedure:** any zero result, or one lower than expected, is followed by opening a file from the sample and verifying directly **before** any decision is built on it — and the record states that the check was done by opening a file, not by the number alone.
