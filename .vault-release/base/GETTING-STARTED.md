# Getting started

A first-run walkthrough. It assumes you finished the Quickstart in [README.md](README.md).

## 1. Open the vault

The repository **is** the vault; there is nothing to import. In order:

1. Clone the repository and run the setup script for your system (see the README).
2. In Obsidian **1.13.7 or newer** choose *Open folder as vault* and select the cloned folder. Do not clone it inside another vault.
3. When Obsidian asks, turn community plugins on.
4. Install the plugins from a terminal in that folder: `.venv/bin/python AI-Agent/scripts/install_plugins.py`. Plugin code is not stored in the repository: the script downloads it over HTTPS from the allowed hosts and verifies every file's SHA-256 against `.obsidian/plugins.lock.json` (`--check` verifies without downloading).
5. Reload Obsidian (command palette, *Reload app without saving*) so the plugins load. Until step 4, the plugin list in Obsidian shows plugins that are enabled but not installed; that is expected.

Your existing notes are not touched. To bring them in, copy them into `00-Inbox/` and process them from there.

Windows support is experimental in this beta: the setup scripts and the whole test suite pass on Windows in the project's CI, but they have not been tried by hand on Windows hardware. Linux and macOS are the supported systems for now. On Windows replace `.venv/bin/python` with `.venv\Scripts\python.exe` and `.venv/bin/stratum-state` with `.venv\Scripts\stratum-state.exe` in the commands of this guide. Windows on ARM (`win_arm64`) is not supported yet: the pinned `tiktoken` release has no wheel for it, so the install would try to build it from source.

## 2. Check the state

```sh
.venv/bin/stratum-state
.venv/bin/stratum-audit --ratchet
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

Open the repository with your agent and tell it to read `AGENTS.md`. Ask it to run `.venv/bin/stratum-state` first. To let an MCP client reach the vault, run `.venv/bin/python AI-Agent/scripts/enable_mcp.py`; it turns on the connector plugin, writes a local `.mcp.json` (owner-readable only) for a `streamable-http` server on `127.0.0.1`, and keeps the plugin's own settings in step. Turn it off the same way.

## 6. Commit

```sh
git add -A
git commit -m "first note"
```

The pre-commit hook runs the audit and the tests of the files you staged. If it blocks, the message says which note or test to fix.

## 7. Syncing the vault between devices

The ledgers in `AI-Agent/state/` (`decision-ledger.sqlite3`, `operations.sqlite3`, `social-ledger.sqlite3`) are binary SQLite files tracked by Git. Two devices that both write to them and then sync (for example with the Obsidian Git plugin) produce a conflict that cannot be merged automatically. Work on one device at a time, or sync only after the other device has committed and pushed.

If a link-repair plugin leaves a `consistency-report.md` in the vault root, delete it before committing: it has no frontmatter and the commit gate blocks it.
