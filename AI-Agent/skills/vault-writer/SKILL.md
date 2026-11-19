---
name: vault-writer
description: "Safe vault editing, Fuzzy OCC concurrency, unique heading enforcement (R1-dup), raw ISO dates, and KaTeX dollar escaping. Trigger immediately on: creating notes, editing files, patch_vault_file, renaming headings, modifying frontmatter. DO NOT trigger for: large refactors affecting >=4 files (use task-spec first) or canvas files (use json-canvas)."
tags:
  - ai-agent
  - skill
created: 2026-09-18
args:
  input: vault file path + content/edit operation (create/patch/rename/heading/frontmatter) + expectedContent
  output: modified/created note with all invariants preserved (OCC, R1-dup, TR-0022, R14, schema v2)
  consumer: any write cycle, task-spec execution
---

# Vault Writer Skill

## Overview

This skill defines the mandatory write invariants for modifying or creating notes in this Obsidian vault. Every write operation must preserve structural integrity, avoid race conditions, and prevent silent syntax corruptions.

## Core Writing Invariants

### 1. Optimistic Concurrency Control (Fuzzy OCC)
- Edits must include `expectedContent` verification.
- Match against whitespace-normalized text to tolerate minor spacing drift while preventing destructive overwrites.
- **On Mismatch:** Do NOT force overwrite. Inspect diffs via Advisory Replanning:
  1. Read live content around the target line.
  2. Reconcile changes made by external processes or plugins.
  3. Re-apply the edit against current content.

### 2. Heading Uniqueness (Rule R1-dup)
- Every heading within a file must be globally unique across all heading levels (H1 through H6).
- Sibling sections and nested subsections cannot share names (e.g., do not have two `## Overview` headings in the same file).
- Before creating a new heading, verify uniqueness using `AI-Agent/scripts/outline.py`.

### 3. KaTeX Dollar Escaping (Trap TR-0022)
- Markdown processors and obsidian plugins treat unescaped dollar signs (`$`) as KaTeX math delimiters.
- Pairwise occurrences turn intermediate text into math rendering and break formatting.
- **Rules:**
  - Currency amounts: write `\$100` or `100 USD`.
  - Shell variables: wrap in inline backticks `` `$PATH` ``.
  - In regex replacements: escape backreferences (`\$1`) to avoid empty string substitution.

### 4. Frontmatter Invariants (Schema v2)
- All frontmatter keys must exist in `AI-Agent/schema/frontmatter.yaml`.
- `created`: Must be a raw ISO date (`YYYY-MM-DD`), never quoted strings or timestamps (ADR-010).
- Format lists in block style (`tags:\n  - item`), avoiding JSON-style single-line arrays for multi-item properties.
- `tags`: before adding a tag, check the live inventory (`list_tags`) and reuse the spelling that already exists; never introduce a variant (case, `_` vs `-`, plural vs singular). `audit.py` reports splits as `FM-tag-variant`.

### 4b. Progress Log (where the work lives, as it happens)
- At each checkpoint (a decision taken, a step finished, a blocker hit), append one line to the work stream's own note: Projects under `## Progress Log`, Areas under `## Changelog`. Create the heading if it is missing.
- Format: `- YYYY-MM-DD — <what happened, one line> (<agent>)`. Start the line with the date and keep the section's existing order (some notes are newest-first under dated `###` headings); never rewrite earlier lines. `state.py` sorts by date, not by position.
- Do not wait for the end of the conversation: a conversation has no reliable end. `AI-Agent/scripts/state.py` reads the last lines back at the next session start.

### 5. Table Pipe Escaping (Rule R14)
- When placing aliased wikilinks inside markdown tables, always escape the separator pipe:
  ```markdown
  | Concept | Reference |
  | :--- | :--- |
  | Audit Tool | [[audit|Audit Script]] |
  ```
  *(Note: escape pipe as `\|` inside actual table cells so table parser does not split the column).*

### 6. Post-Write Verification
- Verify every non-trivial write by inspecting the targeted section:
  ```bash
  .venv/bin/python AI-Agent/scripts/section.py "<relative_path>" "<heading_title>"
  ```
- After renaming any heading, run:
  ```bash
  .venv/bin/python AI-Agent/scripts/audit.py --check links
  ```
  to verify that incoming wikilinks were properly resolved (TR-0017 / TR-0021).

### 7. Person Entity & Team Linking Invariant
- **Vault Owner Convention:** The vault owner is named in the `owner` block of `AI-Agent/config/release_profile.yaml`. As the subject of the PKM, the owner is referenced as plain text and does NOT have a note under `02-Areas/People/`.
- **External Collaborators & Teammates:** Every non-owner person listed in `team:` frontmatter or participating in projects/events must be a canonical wikilink (`[[Person Name]]`) resolving to a note under `02-Areas/People/<Person Name>.md`.
- **Pre-Creation Requirement:** If a person note does not exist when drafting or refactoring project/event notes, you MUST instantiate it immediately using `Templates/Person.md` before finalizing the project note.
- **YAML Quoting:** In frontmatter YAML, wikilinks MUST be enclosed in double quotes (e.g., `- "[[Jane-Doe]]"`) to prevent YAML parsers from interpreting brackets as nested flow lists.
- **Zero Bare Strings for Teammates:** Never record external teammates as unlinked bare strings in frontmatter `team:` properties.

