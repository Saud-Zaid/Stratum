---
status: active
area: ""
tags:
  - task-spec
  - planning
created: <% tp.date.now("YYYY-MM-DD") %>
---

# Task Specification — <% tp.file.title %>

> **Status:** Draft / Approved / In-Progress
> **Active Task:** `T-01` (or None)
> **Last Updated:** <% tp.date.now("YYYY-MM-DD") %>

---

## 1. Scope & Invariants

### 1.1 Intent & Deliverables (In-Scope)
* **Objective:** <!-- Concise, unambiguous statement of the target outcome -->
* **Target Files:**
  * `<!-- path/to/target/file_1.md -->`
  * `<!-- path/to/target/file_2.md -->`

### 1.2 Anti-Goals & Strict Boundaries (Out-of-Scope) 🛑
* ❌ **DO NOT touch:** <!-- Any files outside the explicit Target Files list -->
* ❌ **DO NOT rename:** <!-- Existing headings with inbound wikilinks or audit hooks -->
* ❌ **DO NOT patch:** <!-- Linter rules (audit.py) to mask underlying vault schema flaws -->
* ❌ **DO NOT exceed:** <!-- Context token limits, leaf byte caps (3,500B), or B5 session budgets -->

---

## 2. Behavioral Specification (Gherkin Scenarios)

* **Verification Scenario (Given-When-Then):**
  * **Given:** <!-- Initial system state or pre-existing file state before mutation -->
  * **When:** <!-- Conditional mutation executed via patch_vault_file or script -->
  * **Then:** <!-- Machine-verifiable outcome (exit code 0, 0 audit errors, byte threshold) -->

---

## 3. Clarification & Decision Log

<!-- Populated prior to execution whenever ambiguity or architectural divergence arises -->
* [x] **Decision 1:** <!-- Agreed scope boundary or architectural decision with the vault owner -->
* [x] **Decision 2:** <!-- Implementation decision, tool selection, or fallback strategy -->

---

## 4. Execution DAG (4-State Task Machine)

<!-- States: [ ] Pending | [/] In-Progress (Strictly ONE at a time) | [x] Completed (Verified) | [-] Blocked -->
- [ ] **T-01** | <!-- Discrete, atomic task with clear completion criteria --> ^step-01
- [ ] **T-02** | <!-- Next sequential task in the execution DAG --> ^step-02
- [ ] **T-03** | Final automated verification and regression check via audit.py ^step-03

---

## 5. Reflexion & Learning Log

<!-- Populated upon step failure (TR-0005: 2 consecutive failures) to record constraints and prevent looping -->
* **Constraint Discovered:** <!-- What failed, root cause, and the discovered invariant -->
* **Compensating Action:** <!-- Adapted approach or escalation requirement -->
