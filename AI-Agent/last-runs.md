---
tags:
  - ai-agent
created: 2026-11-23
updated_by: AI-Agent
---

# Last runs

Scheduled or recurring maintenance jobs append one append-only status line per completed run:

- Format (`last_run`): `<job> · YYYY-MM-DD HH:MM · ok|fail · <note>`

`state.py` prints the latest status per recorded job. Append only; never edit historical lines.

## Runs
