#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Jev decision service — an MCP stdio server wrapping the OpenRouter Decisions API.

Purpose (per vault Jev protocol, 2026-10-25): instead of the agent asking the vault owner at
every gate, it asks Jev a typed binary question and records the verdict. The owner can
overturn asynchronously; Jev never deletes or moves anything.

Run by AI-Agent/scripts/jev_client.py, which passes OPENROUTER_API_KEY (and JEV_MODEL,
JEV_TIMEOUT when set) in the server's environment.

API reference: https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-questions-and-answers-request.md
Model:         typesafe/jev (System One). Default follows the latest stable release.
Auth:          OPENROUTER_API_KEY from the environment, with a fallback that reads
the key from goose's own config.yaml (~/.config/goose/config.yaml) so the server
works even when spawned outside goose's env block. Never hard-coded in source.
"""

import json
import hashlib
import os

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("jev")

URL = "https://openrouter.ai/api/alpha/decisions"
# Pinned release (owner decision, 2026-10-25): fixed version for stable thresholds over time.
# Override with JEV_MODEL env var if a newer release should be evaluated.
MODEL = os.getenv("JEV_MODEL", "typesafe/jev-1.14")
TIMEOUT = float(os.getenv("JEV_TIMEOUT", "60"))


def _load_key() -> str:
    """Read the OpenRouter key: environment first, then goose's config.yaml.

    The jev extension in ~/.config/goose/config.yaml declares the key in its
    `envs:` block, so goose normally passes it on spawn. This fallback makes the
    server self-sufficient when it is run directly (uv/python) or the env var
    is missing — reading the same source goose itself uses. No key in source.
    """
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if key:
        return key
    try:
        import re

        with open(os.path.expanduser("~/.config/goose/config.yaml"), encoding="utf-8") as f:
            m = re.search(r"OPENROUTER_API_KEY:\s*['\"]?([A-Za-z0-9_\-]+)", f.read())
        return m.group(1) if m else ""
    except OSError:
        return ""


def _ask(state, questions: dict) -> dict:
    """One Decisions request with one or more named questions. state may be str | dict | list."""
    if isinstance(state, str):
        state = [state]
    key = _load_key()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not found in environment or goose config")
    r = httpx.post(
        URL,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "state": state,
            "questions": questions,
        },
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Jev request failed ({r.status_code}): {r.text[:500]}")
    data = r.json()
    return {
        "model": data.get("model"),
        "answers": data["answers"],
        "cost_usd": data["usage"].get("cost"),
        "input_tokens": data["usage"]["input_tokens"],
        "output_tokens": data["usage"]["output_tokens"],
    }


@mcp.tool()
def jev_choice(state: dict | list | str, question: str, options: dict[str, str]) -> dict:
    """Pick ONE option via Jev. options = {option_name: when_to_pick_it}.
    Returns the chosen option, per-option probabilities, and confidence."""
    return _ask(state, {"q": {
        "type": "choice",
        "instructions": question,
        "criteria": options,
    }})


@mcp.tool()
def jev_check(state: dict | list | str, question: str, if_true: str, if_false: str) -> dict:
    """Yes/no judgment via Jev (noul). if_true / if_false describe each branch.
    Returns the probability that the answer is yes (0-1) with confidence."""
    return _ask(state, {"q": {
        "type": "noul",
        "instructions": question,
        "criteria": {"true": if_true, "false": if_false},
    }})


@mcp.tool()
def jev_score(state: dict | list | str, question: str, levels: list[str]) -> dict:
    """Place the state on an ordered scale via Jev. levels = ordered list, lowest first.
    Returns the level, probability-weighted position, and confidence."""
    return _ask(state, {"q": {
        "type": "score",
        "instructions": question,
        "criteria": levels,
    }})


@mcp.tool()
def jev_ask(state: dict | list | str, questions: dict[str, dict]) -> dict:
    """Batch several independent Jev questions against the same state in one request.
    questions = {name: {"type": "choice|noul|score", "instructions": ..., "criteria": ...}}.
    Returns all answers plus usage — cheaper and faster than separate calls."""
    for q in questions.values():
        if q.get("type") not in ("choice", "noul", "score"):
            raise ValueError("question type must be choice, noul or score")
    return _ask(state, questions)


@mcp.tool()
def jev_gate(dr: str, gate: str, question: str, options: dict[str, str], evidence: dict) -> dict:
    """Vault gate call: builds a CANONICAL state from mandatory fields, validates
    completeness server-side, and returns a state fingerprint for the ledger.

    - dr: cycle id (e.g. "DR-01"). gate: gate/fork id (e.g. "gate-transition").
    - question: the binary/criteria question. options = {name: when_to_pick_it}.
    - evidence: MANDATORY dict of real evidence — file paths, numbers, the recorded
      decision text. Raises if empty or missing required keys.
    - Returns: answer + canonical_state + state_hash (sha256, 16 hex chars).
      Record state_hash with the verdict so the same gate can be re-asked later
      and proven to carry the same context.
    """
    required = ("cycle_note", "recorded_state", "paths_or_numbers")
    missing = [k for k in required if k not in evidence or not evidence[k]]
    if missing:
        raise ValueError(f"incomplete state: missing evidence keys {missing}")
    canonical = {
        "protocol": "vault-jev-2026-10-25",
        "cycle": dr,
        "gate": gate,
        "evidence": {k: evidence[k] for k in sorted(evidence)},
    }
    serialized = json.dumps(canonical, ensure_ascii=False, sort_keys=True)
    state_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
    # 2026-10-31: send the canonical state as a structured dict — the Decisions API
    # accepts str | dict | list and _ask handles dicts natively. The old call passed
    # `serialized` (a JSON-dump string), so evidence reached Jev as one escaped blob
    # the model had to parse implicitly — diagnosed cause of low-confidence gates
    # (B1-S02 rows 69-70). state_hash is unchanged: still computed from `serialized`.
    result = _ask(canonical, {"q": {
        "type": "choice",
        "instructions": question,
        "criteria": options,
    }})
    result["gate"] = gate
    result["cycle"] = dr
    result["state_hash"] = state_hash
    return result


if __name__ == "__main__":
    mcp.run()
