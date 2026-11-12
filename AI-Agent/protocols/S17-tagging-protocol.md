---
tags:
  - protocol
  - ai-agent
created: 2026-10-19
---

# S17 tagging protocol (written text only, zero scripts)

> **Purpose:** document how gaps in non-English retrieval (S17) are tagged by hand, with no automatic tagging mechanism and no scripts.
> **Declared limits:** a text-only protocol. Zero tagging scripts. Zero synthetic sweeps.

## 1. The declared rationale

The S17 gap (found by the cycle C1 simulation, group E) shows that un-normalised non-English retrieval leads to 30–50k tokens of waste for every session that has to re-enter its context. A synthetic sweep or an automatic tagging script cannot fix this: both run against the declared condition A05-G02 (hit rate >= 80%) without a real measurement loop.

**Decision:** tagging is solely the vault owner's call. The tag is written into the source files themselves when they are reviewed, never scattered by scripts.

## 2. The tag format (written protocol)

When a file is reviewed by hand (not automatically), add this to the file's frontmatter:

```
manual_tags:
  - "[[S17-Arabic-Retrieval]]"
```

**When does it apply?** Only when there is a trace of a manual look (a read, a review, an edit) at that file by the vault owner or the agent, never on a schedule.

## 3. Ownership limits

-   **No synthetic sweep:** no automatic tagging script is published or run to look for S17 gaps in the vault.
-   **No fake tagging:** the tag is written only after the actual threshold is met (a retrieval error, wasted tokens, a re-entry).
-   **The owner's decision:** every tagging stays a pending request to the vault owner, never a completed automatic action.
-   **last_measured:** it is written by no means other than a real, scheduled hit-rate measurement (S17-stale stays live).

## 4. Relation to measurement (from the live S17 checker)

-   `hit_rate_cadence_days: 14` is declared in the baseline.
-   `S17-never-measured=1` stays a live warning until the first real measurement on a declared schedule.
-   `S17-stale` fires when more than 14 days pass without a measurement.
