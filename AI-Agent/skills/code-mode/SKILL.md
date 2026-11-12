---
name: code-mode
description: "Batch multi-operation tasks into ONE code-sandbox call when the harness offers a code sandbox that can see the vault. Trigger on: 2+ file edits, read+write chains, bulk verification, multi-section reads — only after checking that the sandbox can reach the vault. DO NOT trigger for: single-call tasks, live tool outputs (a browser page state), short fixes, or any harness whose sandbox is isolated from the vault."
tags:
  - ai-agent
  - skill
created: 2026-10-19
args:
  input: a multi-operation vault task + the harness's code-sandbox capability
  output: one batched call with a minimal return, or a documented decision not to batch
  consumer: any multi-operation cycle in a harness that exposes a code sandbox
---

# Code-mode

Multi-operation tasks can run as one code batch instead of N sequential tool calls. The saving comes from replacing N round-trip envelopes with one code block and one result; a measured probe showed about 30% fewer tokens for equivalent multi-tool tasks.

## Probe before you invest

Before any investment, run the cheap decisive probe: from inside the sandbox, can it read and write a real vault file, and can it call the harness's tools? If either answer is no, stop — do not build a batching workflow on an assumption.

## Decision rule

If a step needs a vault read or write and the sandbox cannot see the vault, that step stays a plain tool call; the surrounding multi-operation logic (compare, compute, choose, format) goes into one batch. If a step needs no vault I/O, it must be batched.

## Known limits (measured)

- An isolated, stateless sandbox does not win on vault-editing tasks: the code must re-embed file contents as string literals, paying the content cost twice. A hybrid (compose in a batch, short appends, verify in a batch) measured break-even.
- A sandbox with no tool bridge cannot call the vault's tools at all; in-context data reaches it only by manual re-embedding — the same double cost.
- Use it only for self-contained operations: generation, computation, encoding.

## Never

- Rely on a virtual filesystem inside the sandbox to reach real vault paths.
- Batch a step whose result you must see before deciding the next one.
