# AGENTS.md — entry point for any AI agent working in this vault

This file is a door, not a rulebook. The rules live in one place, `AI-Agent/`, shared by every agent (Claude, Gemini, Codex, Cursor). `CLAUDE.md` and `.cursor/rules/stratum.mdc` are thin pointers to this file; do not create other instruction files (`GEMINI.md`, `.agents/rules/`); extend the files below instead.

## Agent launch — mandatory before every delegate

Before launching ANY subagent (`delegate`, any recipe, any parallel fleet), the launching agent must invoke the `agent-launch` skill first: no ad-hoc delegate for deliverable tasks (TR-0030), a launch plan written to `AI-Agent/scratch/launch-plan-*.md`, the instruction template with the final_output injection counter-rule, and verification of the deliverable FILE (never the subagent's summary) before retry or acceptance. See `AI-Agent/skills/agent-launch/SKILL.md`.

## Before writing anything

1. Read `AI-Agent/handoff.md` — invariants, and where everything lives.
2. Read `AI-Agent/skills/vault-writer/SKILL.md` — how to write a note (frontmatter, tags, headings, progress log).
3. Run `.venv/bin/stratum-state` (or `.venv/bin/python AI-Agent/scripts/state.py`) — the current state, derived from the vault. Never trust a state written in prose.
4. Live reference: before you use a tool or a skill, run the tool's `--help` (exit 0) or read the skill's `SKILL.md`, and read `.vault-release/pending-review.json` when it exists. Never rely on a command remembered from a note under `01-Projects/` or from compressed memory.

Every commit runs `audit.py --ratchet` through the pre-commit hook (`.githooks/pre-commit`). A note whose frontmatter breaks `AI-Agent/schema/frontmatter.yaml` blocks the commit, so the vault's backup stops until it is fixed.

Agent files are written in English. Reply to the vault owner in the language the owner writes in.
