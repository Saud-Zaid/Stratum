---
area: "[[Second-Brain-Operations]]"
tags:
  - ai-agent
  - mcp
  - capabilities
created: 2026-09-08
last_reviewed: 2026-11-12
review_findings: "Release form: split into Core Always-On and Opt-In; every tool named by a trap is listed."
---

# Agent Capabilities (connections, plugins, tools)

A technical reference of every capability actually available to an AI agent working in this vault, so that no one assumes a capability that is not there. It is updated whenever the connected tools change or a real (not theoretical) capability or limit is found.

**Critical loading note — two separate layers, never conflate them:**
- **Client layer (the agent app):** every connector tool, Obsidian included, is deferred → call `tool_search` before first use in every chat, regardless of persistence. The client fetches the tool list when the app starts and caches it.
- **Server layer (the Obsidian MCP Connector plugin):** `activate_tool` / `activate_tools` without `persist` lives in plugin memory until the plugin reloads; `persist: true` writes it to the plugin's `data.json`. After any activation, restart the client before expecting `tool_search` to find the tool.
- **Other connectors:** no server-side activation layer; the same client rule applies.

## Known traps — avoid them at once

> The traps live in the registry `AI-Agent/traps/` (one file each; index in [[MOC - Traps]]). This section is only a pointer.

**Before the first vault write in a chat:** run once through `search_vault`, with one `econtains` per tool you plan to use (always `econtains`, never `contains`, which matches substrings):

```
TABLE rule FROM "AI-Agent/traps" WHERE status = "active" AND (econtains(tools, "patch_vault_file") OR econtains(tools, "search_and_replace") OR econtains(tools, "*")) SORT id ASC
```

Open a trap file only when its one-line rule is not enough.

**New trap:** at the moment of the failure, create `AI-Agent/traps/TR-NNNN.md` with the next free number (never reused), frontmatter copied from any existing trap, then verify it with `get_note_property`. Never delete a trap: set `status: superseded` and `superseded_by`.

**Error-registry fields (optional, schema class `trap`):** `kind` (tool, design, process, build; `tools` is required only for tool) · `symptoms` · `cause` · `workaround` · `fix_status` (open, workaround, fixed) · `systems` · `steps` (phase tags 00 to 06) · `regression_check`.

## Core Always-On

What an agent can count on in a default setup.

### Obsidian MCP Connector — tools active on the server

| Tool | What it does | Limits |
|---|---|---|
| `search_vault_simple` | plain substring search across every vault file | no semantic search |
| `get_vault_file` | reads a whole file (text or JSON with frontmatter) | very large files are cut, with a hint to use `get_vault_file_partial` |
| `create_vault_file` | creates a new file **or fully replaces** an existing one | no partial edit; decodes four-digit `u` escapes (TR-0025) |
| `get_note_property` / `set_note_property` | reads/writes one frontmatter field without rewriting the file | `set_note_property` with `value: null` also deletes; no mixed-type lists |
| `get_vault_file_partial` | a confirmation read of exactly what a heading patch will replace; modes `heading`, `frontmatter`, `block`, `document-map`, `lines` | heading text must be exact |
| `patch_vault_file` | an edit relative to a heading, a block reference or a frontmatter key | read the traps first (TR-0001, TR-0002, TR-0003, TR-0024) |
| `append_to_vault_file` | adds content to the end of an existing file at any path | `expectedContent` is not applied to appends (TR-0003) |
| `rename_heading` | renames a heading and updates the links that point at it | verify with `audit --check links` every time (TR-0021) |
| `rename_vault_file` | moves/renames a file and updates backlinks vault-wide | free-text mentions are not updated (TR-0004) |
| `search_and_replace` | regex search and replace across the vault or given files | Markdown files only (TR-0026); dollar signs in the replacement (TR-0022) |
| `find_broken_links` | scans the vault for broken links | does not cover heading links (TR-0018) |
| `find_orphaned_notes` | every note with no incoming link | — |
| `get_backlinks` / `get_outgoing_links` | the files that link to a file / the links a file sends out | — |
| `list_tags`, `list_vault_files`, `search_vault` (Dataview DQL) | inventory and query helpers | the file list may not show every file on disk |
| `get_note_outline` | a heading outline of a note | session-active only; superseded by `get_vault_file_partial` in `document-map` mode |

### Tool activation

| Tool | What it does |
|---|---|
| `tool_search` | finds a deferred tool in the client; required before first use in each chat |
| `activate_tool` / `activate_tools` | turns a server-side tool on; `persist: true` keeps it after a reload (TR-0011, TR-0012, TR-0013) |

### Scripts and sandbox

| Tool | What it does |
|---|---|
| `run_script` | runs a vetted script from `AI-Agent/scripts/` inside a harness sandbox; elsewhere run the script directly with `python AI-Agent/scripts/<name>.py` |
| `exec_python` | runs Python in a sandbox; use it for read-only verification such as `git diff` (TR-0025) |
| `delegate` | hands a task to a subagent; never ad hoc for deliverable tasks — go through `agent-launch` and a recipe file (TR-0030) |

### Filesystem connector (direct access to the machine's files)

| Tool | What it does | Limits |
|---|---|---|
| `edit_file` | edits any file, including scripts and YAML that Markdown-only tools cannot reach | can fail in a cloud session under a particular connector prefix (TR-0027) |
| `get_file_info` | file metadata | same |
| `list_allowed_directories` | the directories the connector may touch | try it once before assuming a failure |

**The practical rule:** use the vault connector for notes and the filesystem connector for scripts and configuration; after any write, verify by reading it back.

## Opt-In Obsidian MCP (`mcp-tools-istefox` — Disabled Until Activated)

Tools the connector offers that are **off by default**. Every active tool adds a line to every message, so a tool stays off until a task needs it; turn one on with `activate_tool` and keep it only for as long as it is needed.

| Group | Tools | Why it is off |
|---|---|---|
| batch reads | `get_vault_files` | redundant with `search_vault` and section scripts |
| binary and active file | `create_vault_binary_file`, `patch_active_file`, `show_file_in_obsidian` | rarely needed |
| tag and property queries | `get_files_by_tag`, `list_property_values`, `execute_dataview_query` | redundant with `search_vault` DQL |
| canvas | `get_canvas`, `add_canvas_node`, `connect_canvas_nodes` | only for canvas work (use the `json-canvas` skill) |
| semantic search | `search_vault_smart` | needs the Smart Connections plugin |
| commands and templates | `list_obsidian_commands`, `execute_obsidian_command`, `execute_template` | widens the blast radius |
| periodic notes | `get_or_create_periodic_note`, `append_to_periodic_note` | weekly/monthly/quarterly notes only |
| destructive | `delete_vault_file`, `delete_active_file`, `delete_vault_directory`, `delete_note_property` | real deletes bypass the trash — turn on only when the owner asked for a delete |

## Plugins that shape the agent's behaviour

- **Plugins that edit files automatically (the most important):** Linter (normalises formatting and YAML lists), Git (commits and pushes on its own schedule if configured). A note an agent writes may therefore change after the save; re-read it.
- **Plugins that fix formats the agent must follow:** Templater (dynamic `created`), QuickAdd (the five capture choices), Dataview (queries read frontmatter fields).
- **A plugin that must stay off:** any plugin that rewrites `created`/`updated` on every save (TR-0009).

## The practical rule

Never assume a capability from memory: read this file, run the tool's `--help` or the skill's `SKILL.md`, and verify a write by reading it back. When a new capability or limit is found for real, update this file in the same commit.
