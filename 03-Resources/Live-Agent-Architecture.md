---
status: active
area: "[[Second-Brain-Operations]]"
tags: [ai-agent, architecture, live-doc]
created: 2026-10-23
---

# Live Agent Architecture

> **How it is derived:** this document is **not edited by hand** — its figures are derived from the live script tree at every audit cycle (`.venv/bin/python AI-Agent/scripts/derive_live_arch.py --derive`), and the audit check `livedoc` blocks a commit when a figure drifts. The numbers below are the reference moment; any later cycle derives them again.

## 1. The visible layer (the communication layer)

- **The main session:** the agent harness the owner talks to. Its own consumption is not recorded in the delegated-session ledger.
- **Delegated agents:** subagents launched through `agent-launch` write their deliverables to disk; their usage can be read from the harness's session database when it exposes one (`STRATUM_SESSION_DB`).

## 2. The rules layer (the instruction layer)

- **The entry gate:** `AGENTS.md` → every rule lives in `AI-Agent/` (no separate instruction file per agent; `CLAUDE.md` and `.cursor/rules/stratum.mdc` only point).
- **The approved files:** `AI-Agent/handoff.md` (the invariants and where everything lives), `AI-Agent/skills/vault-writer/SKILL.md` (how to write a note), `AI-Agent/scripts/state.py` for the current state.
- **The enforcement gate:** every commit passes `audit.py --ratchet` (GATE CLEAR, blocking=0) — a non-conforming file stops the vault's backup.

## 3. The tool layer (40 scripts)

- **The source:** the live tree `AI-Agent/scripts/*.py` (a `*-tests.py` file is not a tool). Verdict by script: **40 ✅ sound, 0 ⚠️ incomplete, 0 ❌ broken** — a script is sound when it parses; `derive_live_arch.py` counts them live.
- **The front door:** `state`, `audit`, `section`, `outline`, `tool_gate`, `restore_ready`, `entry_map` are wrapped by the `stratum-*` console commands; every script answers `--help` with exit 0 and an unknown flag with exit 2.

## 4. Conformance with public patterns

| Pattern | Status | Gap |
|---|---|---|
| MCP discovery (`tools/list`) | ⚠️ indirect | discovery is by filesystem, not by protocol |
| MCP schemas (JSON Schema) | ⚠️ indirect | no schema is mandatory in frontmatter beyond `frontmatter.yaml` |
| MCP transport (stdio) | ✅ direct | equivalent by convention (argv → stdout) |
| Orchestrator-workers | ✅ direct | `delegate` with file-ownership split |
| Blackboard (shared state) | ✅ direct | `AI-Agent/state/` + the pre-commit gate |
| Pipeline (a locked chain) | ✅ direct | cycles gated by the audit |

## 5. Accountability by measurement

- **Consumption:** a full cycle's usage is read from the delegated-session ledger when the harness provides one; the main session is the declared gap.
- **Deferred fixes:** open items are decisions proposed in [[Architecture-Decision-Records]] and wait for the vault owner.
