# Getting started

A first-run walkthrough. It assumes you finished the Quickstart in [README.md](README.md).

## 1. Open the vault

The repository **is** the vault; there is nothing to import. In order:

1. Clone the repository and run the setup script for your system (see the README).
2. In Obsidian **1.13.7 or newer** choose *Open folder as vault* and select the cloned folder. Do not clone it inside another vault.
3. When Obsidian asks, turn community plugins on.
4. Install the plugins from a terminal in that folder: `python AI-Agent/scripts/install_plugins.py`. Plugin code is not stored in the repository: the script downloads it over HTTPS from the allowed hosts and verifies every file's SHA-256 against `.obsidian/plugins.lock.json` (`--check` verifies without downloading).
5. Reload Obsidian (command palette, *Reload app without saving*) so the plugins load. Until step 4, the plugin list in Obsidian shows plugins that are enabled but not installed; that is expected.

Your existing notes are not touched. To bring them in, copy them into `00-Inbox/` and process them from there.

Windows support is experimental in this beta: the setup scripts exist, but the test suite is not yet fully green there. Linux and macOS are the supported systems for now.

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
