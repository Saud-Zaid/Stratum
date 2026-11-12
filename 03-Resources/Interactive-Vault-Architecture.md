---
area: "[[Second-Brain-Operations]]"
tags:
  - architecture
  - ai-agent
created: 2026-11-05
summary: How the vault's interactive architecture views are built and read — by people through full-screen HTML, by agents through the small JSON models
---

# Interactive Vault Architecture

> [!NOTE] Dual purpose
> This document is a shared reference for people and agents:
> 1. **For the vault owner:** a full-screen interactive view for moving between the architecture levels.
> 2. **For agents:** a light semantic pointer (a few KB) that reads the topology and invariants from the source JSON models directly, without spending tokens on the large HTML files.

## Where things live

- **Final HTML views and explainers:** `deliverables/diagrams/<slug>.html`, with the source model `<slug>.candidate.json` beside each one.
- **Standalone reports:** `deliverables/reports/`.
- **Transient build runs and repair attempts:** `AI-Agent/scratch/` only; they are never delivered.
- **The builder:** `AI-Agent/scripts/vault_diagram.py` — a theme matrix (`AI-Agent/schema/themes.json`) and the modes `palette`, `demo` and `mermaid-styles`; it answers `--help`.

## How an agent reads a view

1. Open the `.candidate.json` model of the view, never the HTML.
2. Read only the nodes and edges you need; the model is the source of truth for the topology.
3. If the model and the HTML disagree, the model wins and the HTML is regenerated.

## Machine-readable invariants

| Invariant | Where it is enforced |
|---|---|
| every change reaches the vault through the commit gate | `.githooks/pre-commit` → `audit.py --ratchet` |
| the schema is read by the audit, never restated | `AI-Agent/schema/frontmatter.yaml` |
| a counter inside a test is read from the consumer map | `AI-Agent/schema/consumer-map.yaml` |
| the always-loaded layer stays under its token cap | `AI-Agent/permanent-layer.md` |
| a subagent's completion is the deliverable file, not its summary | `agent-launch` skill |

## The levels

Views are built as levels you can extend: the whole-system context, the agent task lifecycle, the safety net (the audit gate), the knowledge lifecycle of a note, the decision-ledger data structure, and the folder tree with its MOCs. This document does not list the views a given release ships; read `deliverables/diagrams/` for those, and [[Core-Vault-Architecture]] for what guards each part.
