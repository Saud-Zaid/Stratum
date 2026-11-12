---
name: task-spec
description: "Task planning, blast radius gating, and 4-state DAG execution using Templates/Task-Spec.md. Trigger immediately on: multi-file modifications (>=4 files), global schema updates, vault-wide renames, high blast radius operations, consecutive mutation failures (TR-0005). DO NOT trigger for: single-file minor text edits (use vault-writer fast-path)."
tags:
  - ai-agent
  - skill
created: 2026-09-18
args:
  input: multi-file mutation (>=4 files) or high blast radius task description
  output: Task-Spec DAG with 4-state tracking (Templates/Task-Spec.md)
  consumer: task-spec cycle, any complex mutation
---

# Task Specification Skill

## Overview

This skill guides the planning and disciplined execution of complex tasks in the vault. When a task crosses threshold risk boundaries, agents must formalize execution using the Task-Spec framework to prevent scope creep, catastrophic edits, and token-depleting loops.

## Blast Radius Gating

Before executing any modification, assess the operation's blast radius:

| Radius Tier | Scope Trigger | Required Procedure |
| :--- | :--- | :--- |
| **Low** | Single file, non-structural text addition or note creation | Direct execution using `vault-writer` (Fuzzy OCC). |
| **Medium** | 2–3 files, heading renames, or script logic adjustments | Perform pre-audit, execute changes, verify links with targeted audit. |
| **High** | $\ge 4$ files, schema changes, audit rule updates, or global renames | Instantiate `Templates/Task-Spec.md`, define scope & anti-goals, obtain user approval before mutating files. |

## Structure of a Task-Spec Note

When executing High blast radius work, create a task specification in `01-Projects/` using `Templates/Task-Spec.md`. Key sections:

### 1. Scope & Anti-Goals
- **Target Files:** Exhaustive whitelist of files permitted to be touched.
- **Anti-Goals (Strict Boundaries):** Explicit list of files, headings, and rules that must NOT be altered under any circumstances.

### 2. Behavioral Specification (Gherkin Scenarios)
- Define acceptance criteria in executable format:
  ```gherkin
  Given: The vault has 190 audited files with error=0
  When: Renaming directory Claude/ to AI-Agent/
  Then: python3 AI-Agent/scripts/audit.py --ratchet exits with error=0 and warn=0
  ```

### 3. 4-State Execution DAG
Tasks are executed sequentially through an explicit state machine:
- `[ ]` **Pending:** Not yet started.
- `[/]` **In-Progress:** Strictly ONE task may be in this state at any time.
- `[x]` **Completed:** Verified by test, audit, or section check.
- `[-]` **Blocked:** Blocked by unmet dependency or external question.

### 4. Reflexion & Failure Guard (TR-0005)
- If two consecutive mutations fail on the same target, **STOP immediately**.
- Never attempt a 3rd blind retry.
- Record the discovered constraint and root cause in Section 5 (Reflexion & Learning Log).
- Escalate to the user or execute Advisory Replanning.
