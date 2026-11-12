# Getting started

A first-run walkthrough. It assumes you finished the Quickstart in [README.md](README.md).

## 1. Open the vault

Open the repository folder as a vault in Obsidian **1.13.7 or newer**, and enable community plugins when asked. Install the plugins with `python AI-Agent/scripts/install_plugins.py` (it only downloads over HTTPS from the allowed hosts and verifies every file's SHA-256 against the lock; `--check` verifies without downloading).

## 2. Check the state

```sh
stratum-state
stratum-audit --ratchet
```

`GATE CLEAR` means the vault is consistent. A blocking error stops commits until you fix it, so fix the note it names.

## 3. Capture your first note

Press the QuickAdd shortcut for a Fleeting note (it lands in `00-Inbox/`). Capture first; classify later, when you process the inbox ([guide](03-Resources/Second-Brain-User-Guide.md)).

## 4. See active work

`Active-Work.base` is an Obsidian Bases view of the projects with `status: active`; `Dashboard.md` shows the same with Dataview. You can also query from a terminal with the Obsidian CLI (1.13.7 or newer):

```sh
obsidian base:query format=json
```

## 5. Work with an agent

Open the repository with your agent and tell it to read `AGENTS.md`. Ask it to run `stratum-state` first. To let an MCP client reach the vault, run `python AI-Agent/scripts/enable_mcp.py`; it turns on the connector plugin, writes a local `.mcp.json` (owner-readable only) for a `streamable-http` server on `127.0.0.1`, and keeps the plugin's own settings in step. Turn it off the same way.

## 6. Commit

```sh
git add -A
git commit -m "first note"
```

The pre-commit hook runs the audit and the tests of the files you staged. If it blocks, the message says which note or test to fix.
