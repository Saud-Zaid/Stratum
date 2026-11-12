---
tags:
  - ai-agent
  - template
created: 2026-10-30
---
# Template: launch-ticket.md — the launch ticket

<!-- Template: mandatory before every delegate/fleet. Eight fixed fields; a ticket missing a field = a cancelled launch (preflight check). -->

## Launch ticket: <agent name>

1. **Identity and role:** <one line>.
2. **Exclusive ownership:** <a single file path> + an archclaim ownership line: `<!-- claim: <path> <- <sid> :: complete :: <bytes> -->`.
3. **Required structure:** frontmatter + empty sections written before any research.
4. **Budget:** <number of cycles> cycles, <number> page fetches.
5. **Counter-injection:** <the rule verbatim — no deviation from the approved text>.
6. **Strict termination condition:** <the sections are complete on disk, not before — completion is proved, not announced>.
7. **Bounded-failure rule:** a tool fails twice -> document and stop (no silent retry).
8. **tool-env:** <the tools actually available — written by the agent itself after checking, not planned for it>.
