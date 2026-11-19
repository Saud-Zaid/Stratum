#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""FX05 task key (AD09 C9): session=task coupling.

Doctrine (inherited, not invented):
  - FX05 spec (the architecture-consumption fix note): a task key opens and closes;
    a session whose task ended without a closed key is detected and its cost written.
  - Thresholds read from AI-Agent/config/limits.yaml (C5): never from code.
  - p90 calls cap (34) inherited from C5's derived limits.
  - Read-only against sessions.db; state lives in a small JSON key file.

Commands:
  open --session <id> --task "<name>"    record a task key open for this session
  close                                  close the open key, writing the session's
                                         measured cost (from usage_ledger)
  status                                 current key + live session stats + verdict
  check                                  accept/flag: session over p90 call cap with
                                         an open key = "ended its task, key not closed"
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vaultlib import force_utf8_stdio, session_db_path, standard_parser
from datetime import datetime, timezone

VAULT = Path(__file__).resolve().parents[2]
KEYS = VAULT / "AI-Agent" / "state" / "task-key.json"
LIMITS = VAULT / "AI-Agent" / "config" / "limits.yaml"
GOOSE_DB = session_db_path()


def read_limits():
    """Minimal YAML-subset parser (C5 pattern, standalone by design)."""
    caps = {}
    for line in LIMITS.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" in line and not line.startswith(("session", "  ")):
            k, v = line.split(":", 1)
            try:
                caps[k.strip()] = int(v.strip())
            except ValueError:
                pass
    return caps


def session_stats(sid):
    con = sqlite3.connect(Path(GOOSE_DB).resolve().as_uri() + "?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute(
        "SELECT COUNT(*), SUM(total_tokens), SUM(input_tokens - cache_read_tokens) "
        "FROM usage_ledger WHERE session_id=?", (sid,))
    n, tot, unc = cur.fetchone()
    return {"calls": n or 0, "total_tokens": tot or 0, "uncached": unc or 0}


def load_keys():
    return json.loads(KEYS.read_text(encoding="utf-8")) if KEYS.exists() else {"keys": []}


def save_keys(d):
    KEYS.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def find_open(d):
    for k in d["keys"]:
        if k.get("status") == "open":
            return k
    return None


def cmd_open(args):
    sid, task = None, None
    i = 0
    while i < len(args):
        if args[i] == "--session":
            sid = args[i + 1]
        if args[i] == "--task":
            task = args[i + 1]
        i += 2
    if not sid or not task:
        print("usage: open --session <id> --task \"<name>\"")
        return
    d = load_keys()
    o = find_open(d)
    if o:
        print(f"BLOCKED: key already open for {o['session_id']} ({o['task']}) — close it first")
        return
    k = {"session_id": sid, "task": task, "opened_at": datetime.now(timezone.utc).isoformat(),
         "status": "open"}
    d["keys"].append(k)
    save_keys(d)
    print(f"KEY OPEN | session={sid} | task={task}")


def cmd_close():
    d = load_keys()
    k = find_open(d)
    if not k:
        print("nothing to close: no open key")
        return
    stats = session_stats(k["session_id"])
    caps = read_limits()
    over = stats["calls"] > caps.get("max_calls", 34)
    k.update(status="closed", closed_at=datetime.now(timezone.utc).isoformat(),
             calls=stats["calls"], total_tokens=stats["total_tokens"],
             uncached=stats["uncached"],
             verdict="OVER" if over else "ok")
    save_keys(d)
    print(f"KEY CLOSED | session={k['session_id']} | task={k['task']} | "
          f"calls={stats['calls']} (cap={caps.get('max_calls')}) | "
          f"total_tokens={stats['total_tokens']:,} | verdict={k['verdict']}")


def cmd_status():
    d = load_keys()
    k = find_open(d)
    if not k:
        print("F5 status | no open key")
        return
    stats = session_stats(k["session_id"])
    caps = read_limits()
    over = stats["calls"] > caps.get("max_calls", 34)
    print(f"F5 status | session={k['session_id']} | task={k['task']} | "
          f"calls={stats['calls']}/{caps.get('max_calls')} | "
          f"total_tokens={stats['total_tokens']:,} | "
          f"verdict={'OVER-key-not-closed' if over else 'ok'}")


def cmd_check():
    caps = read_limits()
    d = load_keys()
    k = find_open(d)
    if not k:
        print("F5 check | no open key | ok")
        return
    stats = session_stats(k["session_id"])
    if stats["calls"] > caps.get("max_calls", 34):
        print(f"F5 check | OVER | session={k['session_id']} reached "
              f"{stats['calls']} calls (p90 cap={caps.get('max_calls')}) with task "
              f"'{k['task']}' still open -> close the key or declare the task long")
    else:
        print(f"F5 check | ok | session={k['session_id']} | "
              f"calls={stats['calls']}/{caps.get('max_calls')} | task open")


def main(argv=None):
    force_utf8_stdio()
    ap = standard_parser(__doc__, "fx05-task-key")
    sub = ap.add_subparsers(dest="cmd")
    op = sub.add_parser("open", help="open a task key")
    op.add_argument("--session", required=True)
    op.add_argument("--task", required=True)
    for name in ("close", "status", "check"):
        sub.add_parser(name)
    args = ap.parse_args(argv)
    if args.cmd == "open":
        cmd_open(["--session", args.session, "--task", args.task])
    else:
        {"close": cmd_close, "status": cmd_status, "check": cmd_check, None: cmd_status}[args.cmd]()


if __name__ == "__main__":
    main()
