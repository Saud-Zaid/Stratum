---
tags:
  - adr
created: 2026-09-08
last_reviewed: 2026-11-12
review_findings: ""
area: "[[Second-Brain-Operations]]"
---

# Architecture Decision Records (ADR)

> **Scope:** structural decisions about the system itself — how files are built, where their boundaries lie, how sections are split. **It differs from [[Idea-Garden]]:** if a discovery changes the shape or boundary of a file → here (an ADR). If it adds knowledge or an idea inside the existing boundaries with no structural change → the idea garden.

**How it works:**
- Every proposed decision is recorded as a separate entry: the context (what problem was found) + the proposed decision + the status (`proposed` / `accepted` / `rejected`).
- It is created from the weekly review when a section is found that does not match its declared heading (the "heading is a promise" test).
- **Never executed automatically** — it is presented to the vault owner, whose decision is final.
- **A mandatory reference when creating any new structure:** before creating a sub-guide or a new system file, check this record — is there a similar pattern (scope overlap, a swollen section) documented before that deserves to be avoided from the start?
- Entry order: newest at the top (the Keep a Changelog convention). An accepted entry is never rewritten; a change goes through a new decision that amends it.

## Decisions log

### ADR-017 — The vault architecture is an index that points at the sources of truth, and a script checks it
**Status:** accepted.
**Context:** an earlier architecture document copied the schema, the rules and the scripts, and drifted: names added in later batches were missing from it.
**Decision:** the architecture is an index, [[Core-Vault-Architecture]]: one line per component, where its truth lives and what guards it. It copies nothing. Priority when sources conflict: the owner's preferences, then the schema and scripts, then `rules`, then the binding guide sections, then the index. A script compares the index with what exists and warns; it never stops the backup.
**Rejected alternatives:** a full architecture document that restates the rules (it drifts); an index with no checking script (it drifts silently).
**Confirmation:** the index check reports zero warnings after the change, and the first structural change touches the file of truth alone.

### ADR-012 — The frontmatter schema binds on paper only unless the audit reads it
**Status:** accepted and implemented; enforcement is `enforce`.
**Context:** `AI-Agent/schema/frontmatter.yaml` declares itself the single source of truth, but a check that does not read it enforces nothing.
**Decision:** `audit.py` reads the schema file itself under `--check schema` and applies `FM-required`, `FM-unknown` (a key that is unregistered or not allowed for the file's class), `FM-status-enum`, `FM-created-type`, `FM-area-target` and `FM-unclassed` (a note that matches no class). Findings are capped at warning while `enforcement: report`; once the old balance is cleared it is `enforce` and `FM-*` errors block the commit. A waiver (`audit_waive`) applies to `FM-*` findings of its own file only.
**Confirmation:** the schema check returns zero findings; a deliberate bad key in a test vault is rejected.

### ADR-011 — The system folder is model-neutral: `AI-Agent/`
**Status:** accepted.
**Context:** the vault runs under more than one model, so a folder named after one model suggests the instructions belong to it.
**Decision:** the system folder is `AI-Agent/`; operational files and skills are written without assuming a particular model. An accepted record is not rewritten: the older records that name the previous folder are read with the new name.
**Confirmation:** an audit rule warns on a reference to the previous folder name followed by a name that exists inside the system folder.

### ADR-010 — `created` must be a comparable date
**Status:** accepted.
**Context:** a `created` value written as a quoted string fails silently in a Dataview time comparison: the note simply does not appear in the result and no error is raised.
**Decision:** `created` (and any date key later consumed by a Dataview comparison) is written as a raw `date`, never a `str`. The exact format is `YYYY-MM-DD`. A template's `created` holds a Templater placeholder, which is a string by necessity until QuickAdd instantiates a note from it.
**Confirmation:** the audit check `FM-created-type` is an error everywhere except under `Templates/`.

### ADR-009 — Pinned libraries are allowed beside the standard library
**Status:** accepted; amends ADR-006 on libraries only.
**Context:** structural Markdown analysis needs a real parser instead of text patterns, which gave false alarms and missed real cases.
**Decision:** scripts may use the standard library, the shared `_vaultlib`, and a small set of pinned third-party libraries (`markdown-it-py`, `mdit-py-plugins`, `PyYAML`, and the other packages locked in `pyproject.toml`/`uv.lock`). Pinning is by hash, not by version alone; adding a library means locking it, updating the allow-list that the import check reads, and updating this record.
**Confirmation:** `./setup.sh` installs the lock with hashes; an import outside the allow-list fails the import check.

### ADR-008 — Indexes inside notes are generated, not written by hand
**Status:** accepted.
**Context:** a hand-kept contents list drifted from the real headings: a second copy of the headings kept by attention alone goes stale.
**Decision:** a table of contents inside a note is generated by a `table-of-contents` block with its options declared inside the block, not inherited from global settings. A bullet list is used, not a numbered one, because automatic numbers invite new numeric references.
**Confirmation:** the heading and reference checks find no numeric reference to a generated list.

### ADR-007 — Append-only registries are one file per entry, starting with the traps
**Status:** accepted.
**Context:** a single "known traps" section that every session must read kept growing, and Dataview inline fields attach to the whole file, not to a section, so a trap cannot carry queryable data while it is a section inside a large file.
**Decision:** `AI-Agent/traps/TR-NNNN.md`, one file per trap, a sequential number that is never reused, and the file name is the identifier and is never renamed. Frontmatter: `id`, `title`, `tools` (a list; `"*"` for general traps), `rule` (one quoted line), `status` (`active` / `superseded`), `since`, `superseded_by`. A trap is never deleted: it is superseded. The query at the start of a write conversation uses `econtains`, never `contains`, which matches substrings.
**Confirmation:** the registry audit checks the id against the file name and the tool names against the capabilities document.

### ADR-006 — A root system folder for the agent's operational files
**Status:** accepted; its library clause is amended by ADR-009.
**Context:** scripts are not knowledge notes, so they belong to no PARA category and to no Zettelkasten stage, and keeping them outside the vault loses their version history.
**Decision:** a root folder in the pattern of `Templates/` and `Attachments/` (a system folder, not a PARA category) with English file names. `scripts/` holds the Python scripts; a file starting with `_` is a shared hidden library. The promotion rule: free code that recurs twice becomes a script here.
**Rejected alternatives:** scripts outside the vault (no Git history); inside `03-Resources/` (mixes operational code with reference knowledge); inside `Templates/` (conflicts with Templater's job).
**Confirmation:** the import check reads every script's imports against the allow-list.
