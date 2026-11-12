# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""G10 operations store (AD08 K2): queryable store for the operations ledger.
Parses operations.md OP/STEP lines into SQLite (AI-Agent/state/operations.sqlite3),
then answers G013-style queries directly — no whole-file load.

Usage:
  g10-operations rebuild          # parse operations.md, upsert into sqlite
  g10-operations query OP-0002    # direct query with token cost
  g10-operations stats            # store summary
"""
from __future__ import annotations

import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vaultlib import VAULT
from g07_tokens import tokens_of

SRC = VAULT / "AI-Agent" / "operations.md"
DB = VAULT / "AI-Agent" / "state" / "operations.sqlite3"

RE_OP = re.compile(r"- \*\*op:\*\* (OP-\d+) · ([^·]+) · ([^·]+) · (open|applied|rolled_back|failed) · base=([0-9a-f]+) · (.*)")
RE_STEP = re.compile(r"- \*\*step:\*\* (OP-\d+) · (\d+) · ([^·]+) · before=([^·]+) · after=(\S+)")

SCHEMA_USER_VERSION = 1      # PRAGMA user_version: 0 = created before versioning, 1 = current (U-50)
SCHEMA = """
CREATE TABLE IF NOT EXISTS operations (
    op_id TEXT PRIMARY KEY, ts TEXT NOT NULL, agent TEXT NOT NULL,
    status TEXT NOT NULL, base TEXT NOT NULL, title TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS steps (
    op_id TEXT NOT NULL, seq INTEGER NOT NULL, path TEXT NOT NULL,
    before TEXT NOT NULL, after TEXT NOT NULL,
    PRIMARY KEY (op_id, seq)
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    uv = conn.execute("PRAGMA user_version").fetchone()[0]
    if uv > SCHEMA_USER_VERSION:
        conn.close()
        raise RuntimeError(f"{DB.name}: user_version {uv} is newer than supported {SCHEMA_USER_VERSION}; upgrade the tools")
    return conn


def rebuild() -> dict:
    text = SRC.read_text(encoding="utf-8", errors="replace")
    ops, steps = {}, []
    for line in text.splitlines():
        if m := RE_OP.match(line):
            oid, ts, agent, status, base, title = m.groups()
            ops[oid] = (ts.strip(), agent.strip(), status, base, title.strip())
        elif m := RE_STEP.match(line):
            oid, seq, path, before, after = m.groups()
            steps.append((oid, int(seq), path.strip(), before.strip(), after.strip()))
    conn = _connect()
    conn.executescript(SCHEMA)
    if conn.execute("PRAGMA user_version").fetchone()[0] == 0:
        conn.execute(f"PRAGMA user_version = {SCHEMA_USER_VERSION}")
    conn.execute("DELETE FROM steps")
    conn.execute("DELETE FROM operations")
    conn.executemany("INSERT OR REPLACE INTO operations VALUES (?,?,?,?,?,?)",
                     [(oid, *vals) for oid, vals in ops.items()])
    conn.executemany("INSERT OR REPLACE INTO steps VALUES (?,?,?,?,?)", steps)
    conn.commit()
    return {"ops": len(ops), "steps": len(steps)}


def query(op_id: str) -> dict:
    t0 = time.perf_counter()
    conn = _connect()
    conn.row_factory = sqlite3.Row
    op = conn.execute("SELECT * FROM operations WHERE op_id=?", (op_id,)).fetchone()
    steps = conn.execute("SELECT seq, path, before, after FROM steps WHERE op_id=? ORDER BY seq", (op_id,)).fetchall()
    ms = round((time.perf_counter() - t0) * 1000, 1)
    if not op:
        return {"op_id": op_id, "found": False, "ms": ms}
    lines = [f"- op {op['op_id']} {op['ts']} {op['agent']} {op['status']} base={op['base']} {op['title']}"]
    lines += [f"  step {s['seq']}: {s['path']} {s['before']} -> {s['after']}" for s in steps]
    body = "\n".join(lines)
    return {"op_id": op_id, "found": True, "ms": ms,
            "tokens": tokens_of(body), "steps": len(steps), "body": body}


def stats() -> dict:
    conn = _connect()
    ops = conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
    steps = conn.execute("SELECT COUNT(*) FROM steps").fetchone()[0]
    status = dict(conn.execute("SELECT status, COUNT(*) FROM operations GROUP BY status").fetchall())
    src_tok = tokens_of(SRC.read_text(encoding="utf-8", errors="replace"))
    return {"ops": ops, "steps": steps, "status": status, "src_tokens": src_tok}


def main(argv: list) -> None:
    if not argv or argv[0] == "rebuild":
        r = rebuild()
        print(f"G10 rebuilt: ops={r['ops']} steps={r['steps']}")
    elif argv[0] == "query" and len(argv) > 1:
        r = query(argv[1])
        if not r["found"]:
            print(f"G10 QUERY miss {r['op_id']} ({r['ms']}ms)")
            return
        print(r["body"])
        print(f"G10 QUERY {r['op_id']} tokens={r['tokens']} steps={r['steps']} ms={r['ms']}")
    elif argv[0] == "stats":
        s = stats()
        print(f"G10 STATS ops={s['ops']} steps={s['steps']} status={s['status']} src_tokens={s['src_tokens']}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
