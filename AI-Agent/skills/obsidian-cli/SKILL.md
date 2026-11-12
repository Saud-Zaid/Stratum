---
name: obsidian-cli
description: "Interact with running Obsidian instance via the official obsidian CLI. Trigger immediately on: running obsidian terminal commands, opening notes in Obsidian GUI, obsidian property commands. DO NOT trigger for: static Python scripts (use section.py / outline.py) or git operations."
tags:
  - ai-agent
  - skill
  - kepano
created: 2026-09-18
args:
  input: "obsidian CLI command (open/read/search/append/property get|set) + target file/property"
  output: CLI stdout result
  consumer: owner-triggered, any vault interaction needing the running app
---

# Obsidian CLI Skill

## Overview

Use the official `obsidian` command-line interface to interact with a running Obsidian instance directly from the terminal or bash scripts. This requires the Obsidian desktop application to be running.

## Command Syntax Rules

Run `obsidian help` to list all live commands supported by the current app version.

- **Parameters** take values with `=`. Wrap values containing spaces in quotes:
  ```bash
  obsidian create name="Meeting Note" content="Discussion topics"
  ```
- **Flags** are boolean switches without values:
  ```bash
  obsidian create name="Temporary Note" silent overwrite
  ```
- **Multiline Content:** Escape newlines with `\n` and tabs with `\t`.

## File Targeting

Many commands accept `file` or `path` to target specific notes:
- `file=<name>`: Resolves dynamically like a wikilink (filename without directory or extension).
- `path=<path>`: Exact relative path from vault root (e.g., `01-Projects/Project-Alpha.md`).
- Omitting both targets the active focused file in the GUI.

## Common Operations

### Note Management
```bash
# Open a specific note in the active workspace
obsidian open file="Dashboard"

# Read note content to stdout
obsidian read file="Dashboard"

# Search the vault
obsidian search query="architecture"

# Append content to a note
obsidian append file="Current-Week" content="\n- Completed milestone"
```

### Property Operations
```bash
# Get property value
obsidian property:get file="Dashboard" name="status"

# Set property value
obsidian property:set file="Dashboard" name="status" value="active"
```
