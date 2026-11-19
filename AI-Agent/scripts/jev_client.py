#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""MCP stdio client for the Jev decision server (jev_mcp.py) — production client.

Usage (from the vault root):
  uv run --with httpx --with 'mcp<2' --with pyyaml python3 AI-Agent/scripts/jev_client.py '<tool>' '<json_args>'

Server path resolution (first hit wins, no silent fallback):
  1. JEV_MCP_PATH environment variable (set in the vault or session)
  2. jev extension args in the agent config (JEV_CONFIG, else $XDG_CONFIG_HOME/goose/config.yaml,
     else ~/.config/goose/config.yaml): the `- <path>.py` entry

Fails LOUDLY (non-zero exit) if the server path cannot be resolved or the file is
missing — per the constitution's infrastructure rule (no silent degradation).
Resolution happens BEFORE any optional-library import, so a missing path is
reported as an error even when mcp/yaml are absent (J1-S01 probe lesson).

Key handling mirrors the server's own _load_key(): the OPENROUTER_API_KEY is
read from that same config file by the client if not already exported
(lesson 2026-10-30: goose does not pass config envs blocks to generated
servers, so the key must be loaded by code, never by assumption).

Jev tool signatures (jev_mcp.py):
  jev_choice(state, question, options: dict[str, str])   -> probabilities, NO state_hash
  jev_check(state, question, if_true, if_false)          -> probabilities, NO state_hash
  jev_score(state, question, levels: list[str])          -> probabilities, NO state_hash
  jev_ask(state, questions: dict[str, dict])             -> batched, NO state_hash
  jev_gate(dr, gate, question, options, evidence)        -> verdict + state_hash
"""

import asyncio
import json
import os
import sys
from pathlib import Path


def config_path() -> Path:
    """The agent config that may name the jev server: JEV_CONFIG, else XDG_CONFIG_HOME, else ~/.config."""
    if os.environ.get("JEV_CONFIG"):
        return Path(os.environ["JEV_CONFIG"]).expanduser()
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "goose" / "config.yaml"


def resolve_server_path() -> Path:
    env_path = os.environ.get("JEV_MCP_PATH")
    if env_path:
        p = Path(env_path).expanduser()
        if p.is_file():
            return p
        sys.exit(f"ERROR jev-client: JEV_MCP_PATH set but file missing: {p}")

    cfg = config_path()
    if not cfg.is_file():
        sys.exit(
            f"ERROR jev-client: JEV_MCP_PATH unset and {cfg} missing — "
            "set JEV_MCP_PATH. Failing loudly per the vault's infrastructure rule."
        )
    try:
        import yaml  # provided by AI-Agent/vault-python's pinned pylib (PyYAML==6.0.3)
    except ImportError:
        sys.exit("ERROR jev-client: pyyaml unavailable and JEV_MCP_PATH unset — "
                 "run via AI-Agent/vault-python or uv --with pyyaml")
    try:
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        sys.exit(f"ERROR jev-client: config.yaml unreadable: {e}")
    for entry in (data.get("extensions") or {}).values():
        if not isinstance(entry, dict) or entry.get("name", "").lower() != "jev":
            continue
        for arg in entry.get("args") or []:
            if isinstance(arg, str) and arg.endswith(".py"):
                p = Path(arg).expanduser()
                if p.is_file():
                    return p
        sys.exit("ERROR jev-client: jev extension in config.yaml has no resolvable .py server arg")
    sys.exit("ERROR jev-client: no jev extension in config.yaml and JEV_MCP_PATH unset")


def load_api_key() -> None:
    """Ensure OPENROUTER_API_KEY is exported for the server child process.

    Mirrors the server's _load_key(): goose does not pass config `envs` blocks
    to generated servers, so the key is read from the config file by code.
    Never prints or logs the key.
    """
    if os.environ.get("OPENROUTER_API_KEY"):
        return
    cfg = config_path()
    if not cfg.is_file():
        sys.exit(f"ERROR jev-client: OPENROUTER_API_KEY unset and {cfg} missing — export the key")
    try:
        import yaml
    except ImportError:
        sys.exit("ERROR jev-client: pyyaml unavailable and OPENROUTER_API_KEY unset — "
                 "run via AI-Agent/vault-python or export the key yourself")
    data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    for entry in (data.get("extensions") or {}).values():
        if isinstance(entry, dict) and entry.get("name", "").lower() == "jev":
            key = (entry.get("envs") or {}).get("OPENROUTER_API_KEY")
            if key:
                os.environ["OPENROUTER_API_KEY"] = key
                return
    sys.exit("ERROR jev-client: OPENROUTER_API_KEY not found in jev extension envs")


def question_warnings(question: str) -> list[str]:
    """LES-SYS-001 lint (warn only): long or multi-sentence gate questions predicted every
    low-confidence Jev gate in a 12-question backtest (AI-Agent/fixtures/jev-gate-questions-20261117.json:
    7/7 gates under 0.90 flagged, 1/5 at or above). Returns human-readable reasons, empty when clean."""
    import re
    words = len(question.split())
    sentences = len(re.findall(r"[.;\u061b]\s", question.split("?")[0]))   # \u061b: the Arabic semicolon, as an escape (no Arabic in the script)
    reasons = []
    if words > 40:
        reasons.append(f"{words} words (> 40)")
    if sentences >= 2:
        reasons.append(f"{sentences} sentences before the question (>= 2)")
    return reasons


async def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    if len(sys.argv) != 3:
        sys.exit("usage: jev_client.py '<tool_name>' '<json_args>'")
    tool_name, args_json = sys.argv[1], sys.argv[2]
    if tool_name == "check-ledger":
        # Ledger sequence floor (lesson: a gate ran before its predecessor was recorded).
        # Every gate call starts here: last 5 rows + row count, read-only.
        ledger = Path(__file__).resolve().parents[1] / "state" / "decision-ledger.sqlite3"
        import sqlite3
        if not ledger.is_file():
            sys.exit(f"ERROR jev-client: ledger missing at {ledger} — record the previous gate first (no gate before ledger)")
        conn = sqlite3.connect(ledger.resolve().as_uri() + "?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT id, ts, kind, substr(title, 1, 80) FROM decisions ORDER BY id DESC LIMIT 5"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*), MAX(content_hash) FROM decisions").fetchone()
        conn.close()
        print(f"ledger rows: {total[0]} | last per-row hash: {total[1][:16] if total[1] else 'none'}")
        for rid, ts, kind, title in reversed(rows):
            print(f"  {rid} | {ts} | {kind} | {title}")
        print("RULE no-gate-before-ledger: the PREVIOUS gate decision must appear above "
              "(append_decision) before calling jev_gate — if the latest gate is missing, record it first.")
        return
    try:
        args = json.loads(args_json)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR jev-client: args not valid JSON: {e}")
    if tool_name == "jev_gate" and isinstance(args, dict):
        warn = question_warnings(str(args.get("question", "")))
        if warn:  # stderr only: the output and the exit code stay unchanged (contract tests)
            print("WARN jev-client LES-SYS-001: compound-risk gate question: " + "; ".join(warn)
                  + " — split it into one fact-based question", file=sys.stderr)

    # Loud infrastructure checks BEFORE any optional-library import: a broken
    # environment must be reported as an error, never as a silent transport
    # failure inside the MCP handshake (constitution article 4).
    server = resolve_server_path()
    load_api_key()
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        sys.exit("ERROR jev-client: mcp<2 not installed — run via uv with "
                 "--with 'mcp<2' --with httpx --with pyyaml")

    params = StdioServerParameters(
        command="uv",
        args=["run", "--with", "httpx", "--with", "mcp<2", "python3", str(server)],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, args)
            for block in result.content:
                if hasattr(block, "text"):
                    print(block.text)
            if result.isError:
                sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
