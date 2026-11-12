---
name: vault-audit
description: "Structural validation, quality gate enforcement, and zero-regression checks using audit.py --ratchet. Trigger immediately on: verifying changes before git commit, checking schema compliance, link validation, trap registry verification, health audits. DO NOT trigger for: planning new features (use task-spec)."
tags:
  - ai-agent
  - skill
created: 2026-09-18
args:
  input: audit scope (ratchet baseline, links, trap registry, schema compliance)
  output: GATE CLEAR / GATE BLOCKED + error/warn counts vs audit_baseline.json
  consumer: pre-commit gate, weekly-review, task-spec cycles
---

# Vault Audit Skill

## Overview

This skill guides the execution and interpretation of the vault structural audit suite. Vault health is enforced via a ratchet mechanism that guarantees zero new errors and monotonic reduction of legacy warnings.

## Quality Gate Standards

- **Hard Failure (Error):** Any `error > 0` immediately blocks completion.
- **Ratchet Warning Gate:** Any `warn > 0` beyond the ratified baseline (`AI-Agent/audit_baseline.json`) constitutes a regression and must be corrected before concluding the session.
- **Allowed Warnings:** Only historical legacy items codified in `AI-Agent/audit_baseline.json` are tolerated.

## Audit Execution

### Comprehensive Ratchet Audit (Standard Gate)
Run before submitting any multi-file changes or concluding a milestone:
```bash
python AI-Agent/scripts/audit.py --ratchet
```
Expected output signature:
```text
SUMMARY error=0 warn=0 info=...
```

### Targeted Subtree Audit (Rapid Iteration)
When modifying a specific document or directory:
```bash
python AI-Agent/scripts/audit.py --path "<path_prefix>"
```

### Focused Rule Checks
Target specific failure domains:
```bash
# Verify links and heading references
python3 AI-Agent/scripts/audit.py --check links

# Verify heading uniqueness (R1-dup) and depth (R3)
python3 AI-Agent/scripts/audit.py --check headings

# Verify frontmatter YAML parsing and schema compliance
python3 AI-Agent/scripts/audit.py --check frontmatter,schema

# Check trap registry integrity
python3 AI-Agent/scripts/audit.py --check registry
```

## Audit Rule Reference

| Rule Code | Severity | Description | Resolution |
| :--- | :--- | :--- | :--- |
| `R1-dup` | Error | Duplicate heading in the same file | Rename duplicate heading to be unique. |
| `R13-unbalanced` | Error | Mismatched `[[` or `]]` brackets | Close all opened wikilinks. |
| `R13-glued` | Error | Arabic or Latin letter touching `[[` or `]]` | Insert space between text and wikilink brackets. |
| `FM-yaml` | Error | Malformed YAML frontmatter | Fix indentation or unquoted special characters. |
| `R4-leaf` | Warn | Leaf section exceeds 4,000 bytes (non-atomic) | Decompose section into smaller H3/H4 subsections. |
| `R5-char` | Warn | Forbidden characters in heading (`:`, `?`, etc.) | Remove forbidden punctuation from heading title. |
| `R5-hash` | Warn | Bare `#` in heading | Remove `#` or wrap in backticks if code symbol. |
| `R7-h1` | Warn | More than one H1 heading in file | Demote secondary H1s to H2 (`##`). |
| `R14-table-alias`| Warn | Bare pipe in aliased link inside table | Escape pipe as `\|` inside table cell. |
| `RG-missing` | Error | Trap ID missing required fields | Add `id`, `rule`, `tools`, and `status`. |

## Baseline Maintenance Rule

- When fixing legacy warnings, the ratchet threshold should be updated:
  ```bash
  python3 AI-Agent/scripts/audit.py --ratchet --update-baseline
  ```
- The baseline count may only decrease (ratcheting down debt); increasing the baseline count is strictly prohibited.
