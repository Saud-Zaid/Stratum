#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""gate_log - one JSON line per run of the commit gate (AD13 G1, register D56). Standard library only, never raises.

The gate is `audit.py --ratchet` and `consumer_suites.py --staged --run`. A block was printed in the terminal and lost: nobody could
say how often the gate stops a commit or which check does it most. `record()` appends one line to AI-Agent/state/gate-runs.jsonl
(git-ignored: a local run log, not vault content; the weekly problem report turns it into numbers that are kept).

  {"ts": "2026-11-19T12:00:00Z", "gate": "audit" | "suites", "ctx": "hook" | "manual", "result": "pass" | "block",
   "n": <blocking items>, "blocks": [{"id": "<rule or suite>", "where": "<path:line or suite file>", "msg": "<160 characters>"}]}

`ctx` is "hook" when git set GIT_INDEX_FILE (the run is inside a commit) and "manual" otherwise, so an agent that runs the audit by hand
is not counted as a commit attempt. A failure to write (a read-only tree, a full disk) is swallowed: logging must never change the
verdict of the gate. GATE_LOG=off turns the log off for a process and its children (consumer_suites sets it for the suites it runs, so the
suites of the gate's own tools never write lines as if they were commits). The file is cut to its last half when it passes 5 MB."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

MAX_BYTES = 5_000_000
MAX_BLOCKS = 20
MSG_CHARS = 160


def log_path() -> Path:
    vault = Path(os.environ.get("VAULT") or Path(__file__).resolve().parent.parent.parent)
    return vault / "AI-Agent" / "state" / "gate-runs.jsonl"


def context() -> str:
    return "hook" if os.environ.get("GIT_INDEX_FILE") else "manual"


def record(gate: str, blocks, ctx: str | None = None, path: Path | None = None) -> bool:
    """Append one run. `blocks` is a list of (id, where, msg) tuples or dicts; empty means the gate passed. True when written."""
    if os.environ.get("GATE_LOG") == "off":       # set by consumer_suites for the suites it runs: a test of the gate is not a run of the gate
        return False
    try:
        items = []
        for b in list(blocks or [])[:MAX_BLOCKS]:
            if isinstance(b, dict):
                items.append({"id": str(b.get("id", ""))[:80], "where": str(b.get("where", ""))[:160], "msg": str(b.get("msg", ""))[:MSG_CHARS]})
            else:
                i, w, m = (list(b) + ["", "", ""])[:3]
                items.append({"id": str(i)[:80], "where": str(w)[:160], "msg": str(m)[:MSG_CHARS]})
        line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "gate": gate, "ctx": ctx or context(),
                "result": "block" if blocks else "pass", "n": len(blocks or []), "blocks": items}
        p = Path(path) if path else log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        _cut(p)
        with open(p, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        return True
    except Exception:       # noqa: BLE001 - logging never changes the verdict of the gate
        return False


def _cut(p: Path) -> None:
    try:
        if p.exists() and p.stat().st_size > MAX_BYTES:
            data = p.read_bytes()
            keep = data[len(data) // 2:]
            keep = keep[keep.find(b"\n") + 1:]          # start on a whole line
            p.write_bytes(keep)
    except OSError:
        pass


def read(path: Path | None = None) -> list[dict]:
    """Every readable line of the log, oldest first."""
    p = Path(path) if path else log_path()
    out = []
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def summarize(rows: list[dict], since: str = "") -> dict:
    """Counts of hook runs (commit attempts) by gate and result and of the blocking ids, for lines at or after `since` (an ISO prefix)."""
    runs = {}
    ids = {}
    manual = 0
    for r in rows:
        if since and str(r.get("ts", "")) < since:
            continue
        if r.get("ctx") != "hook":
            manual += 1
            continue
        k = (r.get("gate"), r.get("result"))
        runs[k] = runs.get(k, 0) + 1
        if r.get("result") == "block":
            for b in r.get("blocks", []):
                ids[(r.get("gate"), b.get("id"))] = ids.get((r.get("gate"), b.get("id")), 0) + 1
    return {"hook_runs": {f"{g}:{res}": n for (g, res), n in sorted(runs.items())},
            "blocking_ids": {f"{g}:{i}": n for (g, i), n in sorted(ids.items(), key=lambda x: -x[1])}, "manual_runs": manual}
