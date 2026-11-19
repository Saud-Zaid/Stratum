---
name: vault-navigation
description: "Progressive vault exploration (B0-B5), MOC navigation, token-budgeted section extraction via section.py. Trigger on: locating notes, exploring structure, finding sections, outlines, MOC lookups. NOT for: web research (deep-research) or note modification (vault-writer)."
tags:
  - ai-agent
  - skill
created: 2026-09-18
args:
  input: search query / note path / MOC lookup / section title
  output: located note path or section content (tiered B0-B5 budget)
  consumer: any reading/retrieval cycle
---

# Vault Navigation

Escalate retrieval through explicit budget tiers; never open full files upfront.

```
[B0] -> [B1] -> [B2] -> [B3: Outline] -> [B4: Section] -> [B5: Full File*]
```

- **B0 Orientation:** `AI-Agent/handoff.md` + relevant traps (`AI-Agent/traps/TR-*.md`) before modification workflows.
- **B1 Path Discovery:** locate candidates by path/tag, no bodies: `find_by_name`, `list_tags`, `list_dir`.
- **B2 MOC:** consult `06-MOCs/` indexes (e.g. `MOC - Traps` for traps) before prose search; resolve cross-references.
- **B3 Outline:** never load files >4,000B to locate a subsection. Run `.venv/bin/python AI-Agent/scripts/outline.py "<path>"` — self-refuses on files <2,000B or <3 headings (read those directly). Returns headings, levels, line numbers, no body tokens.
- **B4 Section:** `.venv/bin/python AI-Agent/scripts/section.py "<path>" "<title>"`. Leaf sections bounded under 4,000B (R4); ceiling trips print `[SECTION-BYTES total=N returned=N remaining=N]` — continue via `--all` or narrowed `Lx-y`.
- **B5 Full File\*:** only for new architectural docs, full-file refactoring, or files known <2,000B.

## Session = Task (FX05)

- **A session is a task:** every navigation call opens under one task: `.venv/bin/python AI-Agent/scripts/fx05_task_key.py open --session <id> --task "<name>"` — one key per session; navigation with no open task counts against the general budget, not the task's.
- **The return limit:** when the result (a path or a section) is reached, close the task at once (`close`) and return the content to the original call — no extra depth without a justification recorded in the task; a task that passes the p90 ceiling while open is flagged OVER.

## Search Rules

1. **Non-ASCII normalization (vaults with Arabic notes):** search with `_vaultlib.normalize_ar` (diacritics stripped; Eastern Arabic-Indic digits mapped to ASCII). Obsidian's own search can ignore diacritics, but agent search (`search_vault` Dataview/JsonLogic, `search_vault_simple` substring) does not: on a miss retry the alef (with and without hamza) and the teh-marbuta/heh variants.
2. **Scope:** primary knowledge in `01-Projects/`, `02-Areas/`, `03-Resources/`; downrank `00-Inbox/` for established architecture; experiments in `05-Zettelkasten/`.

## Traps

- **TR-0017:** link directly to headings (`[[Note#Heading]]`), never nested paths.
- **TR-0014:** Python/filesystem tools 1-indexed; raw offsets 0-indexed.
