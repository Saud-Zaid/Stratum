# Stratum

> **Beta.** This is a beta release (`1.0.0-beta.6`). It is usable and tested, but its commands, file layout and defaults may still change before `1.0.0`; every change is listed in [CHANGELOG.md](CHANGELOG.md). Please report problems in the [issue tracker](https://github.com/Saud-Zaid/Stratum/issues).

Stratum is an [Obsidian](https://obsidian.md) vault that works with AI agents. It combines **PARA** (where things go) with **Zettelkasten** (how ideas grow), and puts a commit gate, a frontmatter schema, a trap registry and a set of skills around it, so that an agent can work on your notes and be checked mechanically instead of by trust.

**Requirements:** Obsidian **>= 1.13.7**, Python 3.13 (installed for you by `uv`), [`uv`](https://docs.astral.sh/uv/), and Git.

## Quickstart

```sh
git clone https://github.com/Saud-Zaid/Stratum.git stratum
cd stratum
./setup.sh            # macOS / Linux
```

On Windows use `setup.ps1` (PowerShell) or `setup.cmd` (Command Prompt). The setup scripts are plain ASCII, install the pinned runtime with `uv sync --locked --no-dev --no-editable` (add `--extra jev` for the optional [Jev decision gate](#optional-the-jev-decision-gate)), create `.venv`, stamp the lock hash, fetch the tokenizer vocabulary once (hash-checked and time-bounded), and enable the pre-commit hook.

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

Fourteen community plugins are enabled. `mcp-tools-istefox` ships **disabled**: turn it on only when you want an MCP client to reach the vault (see [Agent Capabilities](03-Resources/Agent-Capabilities.md) and `enable_mcp.py`).

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
| `stratum-iso-dates` | dates with ASCII digits (`2026-11-19`) when the interface language prints Arabic-Indic or Persian digits |

Plugin code is not stored in this repository: `install_plugins.py` fetches each plugin over HTTPS and checks its SHA-256 against `.obsidian/plugins.lock.json`.

## Using it with an agent

Point your agent at `AGENTS.md`. Before it writes anything it reads `AI-Agent/handoff.md`, runs `.venv/bin/stratum-state`, and checks a tool's `--help` or a skill's `SKILL.md` instead of trusting remembered commands. Every commit passes `audit.py --ratchet` through the pre-commit hook.

## Optional: the Jev decision gate

The `proposal-critique-gate` skill ends each design decision at a gate. Without Jev, the gate is a second written critique recorded in the decision ledger. With Jev, the agent asks [Jev](https://openrouter.ai/typesafe/jev-1.14), a decision model made by [TypeSafe](https://docs.typesafe.ai), a typed question and records its answer and a `state_hash` fingerprint. Stratum ships both pieces: the client `AI-Agent/scripts/jev_client.py` and the server `AI-Agent/scripts/jev_mcp.py`.

**You need one key: an OpenRouter API key.** Jev is reached through OpenRouter's Decisions API (`POST https://openrouter.ai/api/alpha/decisions`), billed to your OpenRouter account. There is no separate TypeSafe key.

1. Create a key at [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys) and add credits to your account.
2. Install the optional libraries:

   ```sh
   uv sync --locked --no-dev --no-editable --extra jev
   ```

3. Put the key in your shell, never in the vault:

   ```sh
   export OPENROUTER_API_KEY="your-key"                # macOS / Linux: add the line to ~/.zshrc or ~/.bashrc
   ```

   ```powershell
   setx OPENROUTER_API_KEY "your-key"                  # Windows: then open a new terminal
   ```

4. Check that it works:

   ```sh
   .venv/bin/python AI-Agent/scripts/jev_client.py jev_check '{"state":"The file count is 3.","question":"Is the file count greater than 2?","if_true":"count above 2","if_false":"count 2 or less"}'
   ```

   A working setup prints JSON with `"noul"` close to `1` and a `cost_usd`. On Windows use `.venv\Scripts\python.exe`, and in PowerShell wrap the JSON in single quotes.

**Good to know**

- **Model.** The server is pinned to `typesafe/jev-1.14` so that confidence thresholds stay stable. To try another release, set `JEV_MODEL`, and treat the change as a decision of its own.
- **Cost.** A question costs about `0.00001` to `0.00003` USD (measured on `jev-1.14`).
- **What leaves your machine.** Everything in a question (the question, the options and the evidence: file paths, numbers and note text) goes to OpenRouter and to the model provider. Do not put secrets or private notes in the evidence.
- **The key stays out of the vault.** The commit gate's secret scan rejects a commit that contains an OpenRouter key.
- **Alpha API.** OpenRouter marks the Decisions API as alpha, so its shape may change.
- **Another server.** Set `JEV_MCP_PATH` to run a server other than the shipped one.

**Asking Jev well.** One question asks about one thing and fits in one sentence of at most 40 words (the client warns when it does not). Write each option's criterion in terms that can be seen in the evidence, not as an opinion, and never hint at the answer you want. Give a gate at least three pieces of evidence from disk. A refusal or an error from Jev is never a pass.

## License

Stratum is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE). Third-party components keep their own licenses; see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
