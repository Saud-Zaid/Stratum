---
type: area
status: active
tags:
  - area
  - second-brain
created: 2026-11-12
summary: How this vault and its agent layer are run, kept healthy and changed
---

# Second Brain Operations

The area that owns the vault itself: its folders, its agent layer (`AI-Agent/`), the commit gate and the tools that keep notes consistent.

## Standard

- `AI-Agent/scripts/audit.py --ratchet` passes on every commit.
- `AI-Agent/scripts/state.py` describes the current state without surprises.
- Every change to the agent layer is recorded where the work lives.
