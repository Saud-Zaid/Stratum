---
name: ida
description: "The methodology for running architectural cycles and phases (IDA). Mandatory for any phase, cycle or architectural change, however small: six sequential steps — set the goals, critique the goals constructively, research the best standards through agents (the disk-probe skill), write a detailed execution plan, critique the plan constructively, then execute. Every step is documented in the cycle note before moving on to the next."
tags:
  - ai-agent
  - skill
created: 2026-10-23
args:
  input: scope (the phase/cycle/architectural change targeted, whatever its size) + context (a reference to the cycle plan in state/<project>/)
  output: six documented pieces in the cycle note — goals, goal critique, the standards research report (from a disk-probe agent), a detailed execution plan, plan critique, and a phased execution with GATE CLEAR and a commit per phase plus a progress-log line
  consumer: every cycle/phase/architectural change in the vault — the executing agent always calls it before the first execution step
---

# IDA — the methodology for running architectural cycles and phases

**The single rule:** no execution work before the six steps are complete. The order is not optional.

## The six steps

1. **Set the goals:** write the phase's goals explicitly and measurably in the cycle note. Each goal is one line + a success criterion.
2. **Critique the goals constructively:** for each goal: does it solve the real problem or only the apparent one? Adjust the goals based on the critique and adopt them — the adjustment is documented.
3. **Research the best standards through agents:** use the `disk-probe` skill (a parallel fleet or a single agent) to look for the relevant best practices/standards. The sub-question is separate, and the output is a file on disk with SOURCES/VERDICT sections. Never invent a standard from a guess.
4. **Write a detailed execution plan:** a multi-phase plan; each phase has a verifiable output (a test/check/gate) and its own commit.
5. **Critique the plan constructively:** for each phase: is its scope enough? Is there leniency or excess effort? Correct the plan and adopt it — the correction is documented.
6. **Execute:** go phase by phase. For each phase: GATE CLEAR, then a commit with a measuring message, then a mandatory progress-log line in the project note.

## The methodology's limits

- A very small change (one line, a typo fix with no semantic change) may shorten steps 3 and 5 to one documented line ("critique: no architectural impact") — but the six steps are never removed from the order.
- Any research result must show its effect in the plan (an adopted number, a source), otherwise it is decoration.
