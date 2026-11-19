# Stratum

> **Beta.** This is a beta release (`1.0.0-beta.2`). It is usable and tested, but its commands, file layout and defaults may still change before `1.0.0`; every change is listed in [CHANGELOG.md](CHANGELOG.md). Please report problems in the [issue tracker](https://github.com/Saud-Zaid/Stratum/issues).

Stratum is an [Obsidian](https://obsidian.md) vault that works with AI agents. It combines **PARA** (where things go) with **Zettelkasten** (how ideas grow), and puts a commit gate, a frontmatter schema, a trap registry and a set of skills around it, so that an agent can work on your notes and be checked mechanically instead of by trust.

**Requirements:** Obsidian **>= 1.13.7**, Python 3.13 (installed for you by `uv`), [`uv`](https://docs.astral.sh/uv/), and Git.

## Quickstart

```sh
git clone https://github.com/Saud-Zaid/Stratum.git stratum
cd stratum
./setup.sh            # macOS / Linux
```

On Windows use `setup.ps1` (PowerShell) or `setup.cmd` (Command Prompt). The setup scripts are plain ASCII, install the pinned runtime with `uv sync --locked --no-dev --no-editable` (add `--extra jev` for the optional Jev decision client), create `.venv`, stamp the lock hash, fetch the tokenizer vocabulary once (hash-checked and time-bounded), and enable the pre-commit hook.

Then:

```sh
.venv/bin/stratum-state         # the current state of the vault, derived from the files
.venv/bin/stratum-audit --ratchet   # the commit gate: GATE CLEAR means you may commit
```

**The repository is the vault.** Clone it, then in Obsidian choose *Open folder as vault* and pick the cloned `stratum` folder. Do not copy it into a vault you already use: Stratum is its own vault, with its own `.obsidian/` settings, plugins, commit gate and agent layer. To bring your existing notes in, copy them into `00-Inbox/` of the new vault. Follow [GETTING-STARTED.md](GETTING-STARTED.md).

## What is inside

| Path | What it is |
|---|---|
| `00-Inbox/` … `06-MOCs/` | the PARA + Zettelkasten folders ([guide](03-Resources/Second-Brain-User-Guide.md)) |
| `AI-Agent/` | the agent layer: handoff, rules, skills, traps, schema, scripts |
| `AGENTS.md` | the one entry point for any agent (`CLAUDE.md` and `.cursor/rules/` only point to it) |
| `.githooks/pre-commit` | runs the audit ratchet and the tests of the staged files |
| `Templates/` | twelve Templater templates |
| `Active-Work.base`, `Dashboard.md` | an Obsidian Bases view and a Dataview dashboard of active work |

## Plugins

Thirteen community plugins are enabled. `mcp-tools-istefox` ships **disabled**: turn it on only when you want an MCP client to reach the vault (see [Agent Capabilities](03-Resources/Agent-Capabilities.md) and `enable_mcp.py`).

| Plugin | What it does |
|---|---|
| `obsidian-git` | backup and sync (no automatic pull or commit by default; schedule it yourself) |
| `templater-obsidian` | dynamic templates |
| `dataview` | queries over frontmatter |
| `quickadd` | five capture shortcuts into the inbox |
| `tag-wrangler`, `colored-tags-wrangler` | tag renaming and colouring |
| `obsidian-linter` | formatting, YAML lists in block style |
| `obsidian-excalidraw-plugin` | drawings |
| `obsidian-tasks-plugin` | task queries |
| `omnisearch` | full-text search |
| `consistent-attachments-and-links`, `advanced-rename-and-delete-handler` | keep links and attachments consistent on rename |
| `automatic-table-of-contents` | the generated table of contents |

Plugin code is not stored in this repository: `install_plugins.py` fetches each plugin over HTTPS and checks its SHA-256 against `.obsidian/plugins.lock.json`.

## Using it with an agent

Point your agent at `AGENTS.md`. Before it writes anything it reads `AI-Agent/handoff.md`, runs `.venv/bin/stratum-state`, and checks a tool's `--help` or a skill's `SKILL.md` instead of trusting remembered commands. Every commit passes `audit.py --ratchet` through the pre-commit hook.

## License

Stratum is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE). Third-party components keep their own licenses; see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
