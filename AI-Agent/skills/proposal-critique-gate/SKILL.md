---
name: proposal-critique-gate
description: "MANDATORY loop for every design/fix decision in the vault: Propose (with disk evidence) → Constructive Critique on the proposal itself → Refine → Gate (the Jev gate when the Jev decision server is enabled, otherwise a structured critique decision recorded in the decision ledger) → record the verdict in the decision ledger → commit. Trigger whenever facing a problem that needs a fix, a new mechanism, or a trade-off decision. Never jump from problem straight to implementation, and never let a verdict pass unrecorded. LOW CONFIDENCE (any band below the gate's threshold): apply the FULL pattern — problem analysis → constructive critique → best-solution search → critique-and-merge → gate — up to 5 rounds until confidence rises; if it does not, return the decision to the vault owner with the documented cause."
tags: [ai-agent, decision-protocol]
created: 2026-11-01
args:
  input: "a problem statement + its disk evidence (file paths, numbers, ledger rows)"
  output: "a recorded gate verdict (state_hash when Jev is used) + the refined proposal file P-N-R on disk + a committed progress line"
  consumer: "any agent session solving a design/fix/trade-off problem in the vault"
---

# Proposal-Critique-Gate Skill

## Why this skill exists

When facing a problem, agents tend either to jump straight to implementation (skipping critique) or to ask the vault owner to pick without preparing a critique first. The vault owner mandated the loop:

> When you meet a problem: propose solutions → critique them constructively → put them to the gate for approval.

This skill hard-codes that loop so no session can skip a phase.

## Two modes of the gate

- **Jev mode** (the Jev decision server is enabled in the harness): Phase 4 calls `jev_gate`, and the verdict carries a `state_hash`.
- **Structured-critique mode** (no Jev server): Phase 4 is a second, independent critique pass written as a file, ending in a binary decision with probabilities and a confidence value stated explicitly; the decision is registered in the decision ledger through `append_decision` like any other gate. The rest of the loop is identical.

In both modes the verdict is registered in the decision ledger with a unique entry ID before the commit gate allows the note.

## The Loop (5 phases, all mandatory)

### Phase 1 — Propose (P-1, P-2, …)

Write the proposal to disk with:
- **Mechanism**: what exactly gets built/changed (files, scripts, rules).
- **Evidence**: current numbers from disk (counts, byte sizes, ledger rows) that define the problem.
- **Cost/Reversibility**: token budget, new files, how to roll back.
- **What it does NOT solve**: explicitly list known gaps the proposal leaves open.

### Phase 2 — Constructive Critique — ON THE PROPOSAL

**Executed by the session itself — no external agent, no subagent delegation** (keeps the critique inside the loop's trust boundary).

Critique steps (the full pattern):
1. **Problem analysis (root cause):** before attacking, state from disk evidence what exactly is broken, where, and why — no critique of symptoms without a named cause.
2. **Attack the proposal with disk evidence, not opinions.** Cover at minimum:
   1. **New failure modes** the proposal itself introduces (not just the ones it fixes).
   2. **Silent-state risks**: where the proposal could silently skip a check (for example a session that forgets to run a gate script).
   3. **Unchanged-file drift**: what happens when a previously-ok source changes content?
   4. **What remains open**: the gaps listed in Phase 1, plus any the critique found.
3. **Best-solution search:** for every attack point, search the available solutions and compare them — the critique must propose the best solution with its evidence. **An objection without a best-solution proposal = an incomplete critique; the loop returns to step 2.**
4. **Critique the solutions and merge them:** the chosen best solutions are themselves critiqued once more (one objection each, disk-backed) before being folded into Phase 3 — never merged uncritically.

Record the critique as a separate file (for example `critique-<proposal>.md`) with one section per attack point, each backed by a file path or number.

### Phase 3 — Refine (P-N-R)

**Executed by the session itself.** Apply the critique: fold each attack point back into the proposal as a named rule or mechanism. If a gap is genuinely out of scope, mark it as an OPEN GAP (never silently).

**Output contract:** Phase 3 ends with a new file `P-N-R` that folds in (not silently drops) every critique point from Phase 2 — each point either becomes a named rule/mechanism or is explicitly marked OPEN GAP with a reason. A Phase 3 without this file is a phase-skipped run.

### Phase 4 — The gate

**The only external call in the loop (Jev mode), or one more independent pass (structured mode).**

In Jev mode call `jev_gate` with:
- `dr`: the current milestone.
- `gate`: a unique gate name.
- `question`: the binary decision.
- `options`: exactly two options, each with `when_to_pick_it`.
- `evidence`: MUST include `cycle_note`, `recorded_state`, `paths_or_numbers`. **Minimum evidence count: every gate carries at least 3 distinct disk-evidence items across the three keys — a gate with fewer than 3 evidence items is invalid and must be re-armed before the call.**
- Record the returned `state_hash` with the verdict, always.

**Confidence rules** (thin-margin check first, then the full-pattern loop):
1. **Thin-margin band**: the absolute probability gap between the two options < 0.2 (for example 0.44 vs 0.56) → return to the vault owner regardless of absolute confidence. A thin margin means the evidence is not decisive enough for an autonomous call. **This check precedes the low-confidence protocol.**
2. **Low-confidence FULL-PATTERN protocol — applies to every band below the gate's required threshold:** run the full skill pattern **up to 5 rounds** — each round is the complete cycle:
   - **Problem analysis**: root-cause the current confidence deficit from disk evidence.
   - **Constructive critique**: a new critique file with at least one new piece of disk evidence not cited in any previous critique, each objection carrying its own best-solution proposal (Phase 2 steps 1–3).
   - **Best-solution search**: compare candidate solutions for every open objection and pick the best with evidence.
   - **Critique and merge**: critique the chosen solutions once, fold them into P-N-R (or mark OPEN GAPS) — Phase 2 step 4 + the Phase 3 contract.
   - **Gate**: re-gate with a new state_hash (never a verbatim evidence repeat).
   - **Early exit**: if a round's re-gate confidence crosses the required threshold, stop.
   - **Substantive-change rule**: a round only counts if real evidence changed or a substantive critique point was merged — cosmetic rephrasing alone = an invalid round, return to the owner.
   - **Substantive re-change**: if a later round's chosen option *differs* from an earlier round's and the gap between them is < 0.2, that is a flip on thin margin — return to the owner regardless of absolute confidence.
   - **Hard floor**: after the fifth round's re-gate the confidence is still below the required threshold → **return the decision to the vault owner** with the documented cause analysis — no automatic sixth round.

### Phase 5 — Record and Commit

1. `append_decision` in the ledger with the proposal name, gate, and state_hash (Jev mode).
2. One progress line in `## Progress Log` of the owning note.
3. Commit with `audit.py --ratchet` (must show GATE CLEAR before commit).

## Kill Rule

Running Phases 1-3 without a gate verdict on disk = a **declared violation of the loop**. The only sanctioned path to bypass the gate: a written permission file from the vault owner on disk (for example `P-N-R-waiver.md`) naming the proposal and the reason. No session may invent a bypass path that is not one of these two (a gate verdict or the owner's file).

## Self-critique of this skill

1. **Critique-evidence duplication**: the critique file and the proposal file may overlap (both list gaps). → Rule: the proposal lists its own known gaps; the critique file ONLY adds new ones found during attack.
2. **Gate fatigue**: batching several small gates burns tokens and reduces signal. → Rule: batch related sub-decisions into one `jev_ask` when they share the same evidence base; use `jev_gate` only for the primary fork.
3. **Critique author = proposal author**: the agent that wrote the proposal also critiques it, risking confirmation bias. → Rule: the critique must reference at least one piece of disk evidence that the proposal did NOT cite.
4. **What this skill does not solve**: semantic-duplicate detection and the choice of a fingerprint hash — those are implementation decisions, not decision-protocol decisions.

## Quick Reference

```
Proposal (P-N) → Critique (critique-P-N.md) → Refine (P-N-R) → Gate → Record → Commit

Low confidence (below threshold): [problem analysis → critique → best solutions → critique and merge → gate] × 5, or return the decision to the vault owner.
```
