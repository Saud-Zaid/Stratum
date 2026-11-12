---
type: moc
topic: Technical traps for the agent (TR-)
tags:
  - ai-agent
  - traps
  - moc
created: 2026-09-13
---

# Map of content: technical traps (AI-Agent/traps)

A central reference for every trap documented under `AI-Agent/traps/`. Each trap is a separate file consumed mainly through a trap query (Dataview); this file adds a thematic grouping for manual browsing and for the graph view.

**Error-registry fields (KEDB):** optional, and defined by the schema (class `trap`). Their explanation and how to write them are in the "New trap" section of [[Agent-Capabilities]]:

- `kind` (the kind of error: tool, design, process, build)
- `symptoms`
- `cause`
- `workaround`
- `fix_status`
- `systems` (the systems affected)
- `steps` (the phase tags 00 to 06 where the error shows, so each phase finds its errors)
- `regression_check`

## A) Editing headings — patch/rename/append/prepend
- [[TR-0001]] — superseded by TR-0015
- [[TR-0002]] — targetType block only with single-line text
- [[TR-0006]] — change heading text through rename_heading, not patch replace
- [[TR-0015]] — the real append/prepend behaviour at headings (fixture-verified)
- [[TR-0016]] — createTargetIfMissing is always false for heading corrections

## B) Verifying after a write
- [[TR-0003]] — expectedContent is ignored by append/prepend
- [[TR-0004]] — a text search after rename_vault_file
- [[TR-0005]] — verify after every complex patch/create; stop after two failed attempts
- [[TR-0008]] — verify at once after search_and_replace with dry_run false
- [[TR-0018]] — find_broken_links does not cover heading links
- [[TR-0020]] — the audit corruption check after any rename/move
- [[TR-0021]] — audit --check links after every rename_heading
- [[TR-0022]] — no dollar sign in any replacement; dry_run and the ordinary check miss the damage
- [[TR-0025]] — create_vault_file decodes four-digit u escapes; in code use the eight-digit form and verify with git diff
- [[TR-0026]] — search_and_replace edits Markdown files only; .py and .yaml need edit_file or a whole rewrite
- [[TR-0027]] — the Filesystem connector fails in cloud sessions linked to the computer; non-Markdown edits come from Claude Desktop
- [[TR-0028]] — requireWritePreconditions is on: replace and overwriting a file need expectedContent; on stale_precondition read again

## C) Tool activation
- [[TR-0011]] — a Claude Desktop restart is needed after any activation
- [[TR-0012]] — persist true guarantees survival after an Obsidian restart
- [[TR-0013]] — check the persisted field after activation

## D) Links and nested headings
- [[TR-0017]] — no nested-path links; link to the heading directly
- [[TR-0018]] — (shared with B) a manual check of heading links through audit

## E) General odds and ends
- [[TR-0007]] — run the trap query at the start of any write conversation, not only long ones
- [[TR-0009]] — updated/created rewritten on every save
- [[TR-0010]] — excluding .obsidian from git commands inside the sandbox
- [[TR-0014]] — line numbering differs between tool families (0 versus 1)
- [[TR-0019]] — writing pre-normalised frontmatter (quoting, block style)
- [[TR-0023]] — an audit link error can be a false positive; re-check by an independent method
- [[TR-0024]] — a standalone block id after a table cannot be patched
- [[TR-0030]] — a subagent has no final_output tool; deliver through incremental disk writes
- [[TR-0031]] — a new artifact needs its consumer map updated in the same commit

## F) Build and design errors

Errors of the kinds `design`, `process` and `build` (not `tool`): a check that failed after execution, an incident, or a design that turned out incomplete. Each becomes a trap here at its moment, with the fields `symptoms`, `cause`, `workaround` and `fix_status`, a `steps` tag for the phases where it shows (00 to 06), and `regression_check` when it has a check that can run. `tools` is not required for these kinds.

A phase's search for its errors (Dataview, copied and not run here):

```
TABLE kind, fix_status, symptoms FROM "AI-Agent/traps" WHERE contains(steps, "04")
```

- [[TR-0029]] — an empty gate commit stamps HEAD, not the files (process)
