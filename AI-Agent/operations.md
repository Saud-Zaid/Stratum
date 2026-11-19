---
tags:
  - ai-agent
created: 2026-11-19
updated_by: AI-Agent
---

# Operation log

Multi-file changes are recorded as append-only operation and step entries using structured IDs:

- Format (`op`): `OP-0001 · YYYY-MM-DDTHH:MM+00:00 · agent · open|applied|rolled_back|failed · base=<commit> · <title>`
- Format (`step`): `OP-0001 · 1 · <path> · before=<12 hex>|new · after=<12 hex>|pending|deleted`

Use `g10_operations.py stats` or `g10_operations.py query OP-NNNN` to inspect recorded operations.

## Operations
