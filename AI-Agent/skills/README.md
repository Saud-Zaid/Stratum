# AI Agent Skills Directory & Manifest

This directory contains standard Agent Skills conforming to the [Agent Skills Specification](https://agentskills.io/specification) and the official `kepano/obsidian-skills` standard.

Any AI Agent entering this vault must follow the **Three-Tier Progressive Disclosure Protocol** to conserve context tokens and maintain absolute architectural integrity.

---

## Three-Tier Progressive Disclosure Protocol

```
[User Task] ──> Tier 1: Match Triggers in Manifest (0 tokens added)
            ──> Tier 2: Adopt Micro-Contract below (~50 tokens, no file read)
            ──> Tier 3: Load full SKILL.md ONLY for obscure/deep specs
```

### Operational Invariants
1. **Never dump full `SKILL.md` into chat for routine tasks:** The Micro-Contracts in the manifest provide all mandatory invariants (~50 tokens each).
2. **Pre-flight Declaration (Micro-Contract Activation):** On structural or multi-file tasks, declare activation concisely:
   ```text
   [Pre-flight: Skill: <skill-id> | Micro-Contract Active]
   ```
3. **Deep Reading (Tier 3 on-demand only):** Read the full `SKILL.md` only when executing complex specifications you do not already know (for example the JSON Canvas 1.0 format or the full Task-Spec DAG template).
4. **Physical Enforcement:** All changes remain strictly guarded by `.githooks/pre-commit` running `audit.py --ratchet`.

---

## Master Skills Manifest & Micro-Contracts

### 1. Vault Governance & Operational Skills

| Skill Identifier | Positive Triggers (When to Activate) | Anti-Triggers (DO NOT Use For) | Micro-Contract (Mandatory Invariants) |
| :--- | :--- | :--- | :--- |
| **`vault-navigation`** | Locating notes, exploring structure, finding sections, reading outlines. | External research or modifying notes. | • Primary read: `get_vault_file_partial(mode: "heading")` or `section.py`<br>• Never call full `get_vault_file` on notes >4KB<br>• Outlines: `mode: "document-map"` or `outline.py`<br>• Check `06-MOCs/` before blind vault searches |
| **`vault-writer`** | Creating notes, editing files, `patch_vault_file`, frontmatter edits. | Large refactors (4 or more files) or canvas files. | • Fuzzy OCC: verify `expectedContent` on edit<br>• Zero unescaped dollar signs: wrap in backticks or escape them (TR-0022)<br>• Heading uniqueness (`R1-dup`): globally unique, no trailing colons<br>• Raw ISO date (`created: YYYY-MM-DD`)<br>• Escape table pipes<br>• Person Invariant: teammates in `team:` must be canonical `[[...]]` links to `02-Areas/People/` (instantiated via `Templates/Person.md`), distinguishing external collaborators from the vault owner |
| **`vault-audit`** | Pre-commit validation, schema checks, link validation, health audits. | Planning new features (`task-spec`). | • Hard quality gate: `error=0` and `warn=0` under `audit.py --ratchet`<br>• The pre-commit hook enforces the gate physically on every git commit<br>• Fast checks: `audit.py --path <prefix>`<br>• Baseline debt in `audit_baseline.json` may only decrease |
| **`task-spec`** | Multi-file edits (4 or more files), schema changes, high blast radius. | Single-file minor text edits. | • Assess blast radius: Low (1 file), Medium (2-3 files), High (4 or more files)<br>• High radius requires `Templates/Task-Spec.md`<br>• 4-State DAG: `[ ]` Pending, `[/]` In-Progress (max 1), `[x]` Done, `[-]` Blocked<br>• Stop after 2 consecutive failures (TR-0005) |
| **`weekly-review`** | The scheduled weekly review, or the owner asking for a weekly review. | Monthly/quarterly steps (guide), day-to-day Area tracking. | • `state` + `audit --ratchet` first, never the whole guide<br>• One line + link per finding; details go to the owning note's log<br>• Decisions needing the owner are listed, not executed<br>• Note in `02-Areas/Weekly-Reviews/`, target ≤ 4 KB |
| **`code-mode`** | Multi-op batches (2+ file edits, read+write chains, bulk verify) when the harness has a code sandbox that can see the vault. | Single-call tasks, live outputs, harnesses whose sandbox is isolated from the vault. | • Probe first: can the sandbox read and write a real vault file?<br>• Batch only logic with no vault I/O<br>• Filter/return small summaries only<br>• Plain calls win for 1-2 ops |
| **`ida`** | Any phase, cycle or architectural change, however small. | Pure reading or a one-line typo fix. | • Six steps in order: goals → goal critique → standards research (`disk-probe`) → execution plan → plan critique → execution<br>• Every step documented in the cycle note before the next<br>• GATE CLEAR + a commit + a progress line per phase |
| **`proposal-critique-gate`** | Any problem that needs a fix, a new mechanism, or a trade-off decision. | A change with no decision in it. | • Propose with disk evidence → critique the proposal → refine (`P-N-R`) → gate → record → commit<br>• Gate = Jev when enabled, otherwise a structured critique pass; both recorded in the decision ledger<br>• Thin margin (< 0.2) or five failed rounds returns the decision to the owner |

### 1b. Subagent Delegation Skills

| Skill Identifier | Positive Triggers (When to Activate) | Anti-Triggers (DO NOT Use For) | Micro-Contract (Mandatory Invariants) |
| :--- | :--- | :--- | :--- |
| **`agent-launch`** | **ANY delegate call, no exceptions — invoke BEFORE every launch.** | Consults that need no launch (pure in-session work). | • No ad-hoc delegate for deliverable tasks: recipe file in `.agents/recipes/` without a response block + `max_turns` (TR-0030)<br>• Launch plan on disk first (`AI-Agent/scratch/launch-plan-*.md`): id, mission, deliverable path, scope, budget per agent<br>• Instruction template verbatim: disjoint scope + tool whitelist + final_output injection counter-rule + bounded failure + finish condition<br>• One deliverable path per agent; retries read the file FIRST, never trust subagent summaries<br>• Verify file bytes/headings before accept or retry; 2 failed retries = return to the owner |
| **`disk-probe`** | A research question that fits one agent or a small parallel fleet, with a file on disk as the deliverable. | Launching without `agent-launch`; research that needs no external source. | • The deliverable is a file: skeleton first, then incremental writes<br>• Sections SOURCES / CONCEPTS / VERDICT<br>• Bounded failure: a tool fails twice → record and finish |

---

### 2. Official Obsidian Skills (Steph Ango / kepano)

| Skill Identifier | Positive Triggers (When to Activate) | Anti-Triggers (DO NOT Use For) | Micro-Contract (Mandatory Invariants) |
| :--- | :--- | :--- | :--- |
| **`obsidian-markdown`** | Formatting notes, callouts, block references, wikilinks, embeds. | CLI operations or database views. | • Standard wikilinks `[[Target]]` or `[[Target\|Alias]]`<br>• Callouts: `> [!NOTE]`, `> [!TIP]`, `> [!IMPORTANT]`, `> [!WARNING]`<br>• No glued letters touching brackets (R13-glued) |
| **`obsidian-cli`** | Terminal obsidian commands, opening notes in the GUI, properties. | Python sandbox scripts or git ops. | • Needs Obsidian 1.13.7 or newer; read-only queries use `obsidian base:query format=json`<br>• Use CLI commands when GUI interaction is needed<br>• Read-only operations go through vetted scripts |
| **`obsidian-bases`** | `.base` files, dynamic database tables, card views, formulas. | Standard markdown tables. | • Structure `.base` files with strict YAML configuration<br>• Views: Table, List, Cards with explicit filter criteria<br>• Formula fields: pure functions, avoid unbounded joins |
| **`json-canvas`** | `.canvas` files, visual maps, architectural diagrams, flowcharts. | Text-based markdown notes. | • Conforms to JSON Canvas 1.0 (`nodes` and `edges`)<br>• Strict coordinate grid: `x`, `y`, `width`, `height`<br>• Node types: `text`, `file`, `link`, `group`<br>• Standard colors: 1 (red) to 6 (purple) |
| **`defuddle`** | Parsing web URLs, ingesting external articles, web research. | Local vault file navigation. | • Clean markdown extraction from web URLs<br>• Strip ads, navigation, and telemetry tokens<br>• Progressive summarization before saving to `05-Zettelkasten/Literature/` |

---

### 3. Research Skills

| Skill Identifier | Positive Triggers (When to Activate) | Anti-Triggers (DO NOT Use For) | Micro-Contract (Mandatory Invariants) |
| :--- | :--- | :--- | :--- |
| **`deep-research`** | Investigations, literature reviews, evaluating external claims, academic rigor. | Rapid time-boxed sprints or simple note lookups. | • Multi-source triangulation (3+ primary sources)<br>• Evidence grading: Tier 1 (official/academic), Tier 2 (industry), Tier 3 (blogs)<br>• Synthesize into atomic notes with strict citation provenance |
