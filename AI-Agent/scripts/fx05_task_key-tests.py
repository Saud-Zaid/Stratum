# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for fx05_task_key (2026-10-23, AD10 C15 stage 4): the task-key state
machine (open/close/status/check). KEYS and LIMITS paths are redirected to temp
files before any call -- the real task-key.json is never touched by tests.
Usage: fx05_task_key-tests"""
import sys
import tempfile
from pathlib import Path

import fx05_task_key as F

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


TMP = Path(tempfile.mkdtemp())
KEYS = TMP / "task-key.json"
LIMITS = TMP / "limits.yaml"

F.KEYS = KEYS
F.LIMITS = LIMITS

# Redirect GOOSE_DB too: session_stats reads the real goose sessions.db read-only,
# which is fine, but cmd_close writes to KEYS. Point stats at a tiny temp sqlite
# so tests are hermetic and deterministic.
import sqlite3

DB = TMP / "sessions.db"
con = sqlite3.connect(DB)
con.execute("CREATE TABLE usage_ledger (session_id TEXT, total_tokens INT, input_tokens INT, cache_read_tokens INT)")
con.executemany("INSERT INTO usage_ledger VALUES (?,?,?,?)", [
    ("sess-a", 1000, 700, 200),   # 3 rows => 3 calls, 1000 tokens, uncached 500
    ("sess-a", 500, 400, 100),
    ("sess-a", 300, 100, 50),
    ("sess-b", 100, 90, 10),
])
con.commit()
con.close()
F.GOOSE_DB = DB

LIMITS.write_text("max_calls: 2\nmax_uncached_tokens: 10000\n", encoding="utf-8")


def capture(fn, *a):
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*a)
    return buf.getvalue()


# T1: read_limits parses top-level int caps only
caps = F.read_limits()
ok("T1-read-limits", caps == {"max_calls": 2, "max_uncached_tokens": 10000}, str(caps))

# T2: read_limits skips comments and "session" lines, but strips indentation first
# (the startswith filter runs AFTER strip(), so indented keys are included) -- actual behavior
LIMITS.write_text("# comment\nmax_calls: 5  # inline\n  indented: 9\n", encoding="utf-8")
caps = F.read_limits()
ok("T2-limits-comment", caps == {"max_calls": 5, "indented": 9}, str(caps))
LIMITS.write_text("max_calls: 2\nmax_uncached_tokens: 10000\n", encoding="utf-8")  # restore for T7+

# T3: empty keys file -> find_open returns None
d = F.load_keys()
ok("T3-no-open", F.find_open(d) is None, str(d))

# T4: cmd_open creates a key
out = capture(F.cmd_open, ["--session", "sess-a", "--task", "test task"])
ok("T4-open", "KEY OPEN" in out and "sess-a" in out, out)

# T5: open key persists in file
k = F.find_open(F.load_keys())
ok("T5-persist", k is not None and k["session_id"] == "sess-a" and k["task"] == "test task" and k["status"] == "open", str(k))

# T6: second open is BLOCKED while one is open
out = capture(F.cmd_open, ["--session", "sess-b", "--task", "other"])
ok("T6-double-open-blocked", "BLOCKED" in out and "sess-a" in out, out)

# T7: cmd_close closes the key with session stats
out = capture(F.cmd_close)
ok("T7-close", "KEY CLOSED" in out and "verdict=OVER" in out, out)  # sess-a has 3 calls > cap 2

# T8: closed key retains measured stats
k = F.find_open(F.load_keys())
ok("T8-no-open-after-close", k is None, str(F.load_keys()))
d = F.load_keys()
closed = [x for x in d["keys"] if x["status"] == "closed"][0]
ok("T8b-closed-stats", closed["calls"] == 3 and closed["uncached"] == 850 and closed["verdict"] == "OVER", str(closed))

# T9: cmd_status with no open key
out = capture(F.cmd_status)
ok("T9-status-none", "no open key" in out, out)

# T10: open again, status shows live stats and verdict
capture(F.cmd_open, ["--session", "sess-b", "--task", "small"])
out = capture(F.cmd_status)
ok("T10-status", "F5 status" in out and "sess-b" in out and "verdict=ok" in out, out)

# T11: cmd_check flags only when calls exceed cap
out = capture(F.cmd_check)
ok("T11-check-ok", "F5 check | ok" in out, out)

# T12: usage_ledger aggregation correctness
stats = F.session_stats("sess-a")
ok("T12-aggregation", stats == {"calls": 3, "total_tokens": 1800, "uncached": 850}, str(stats))

# T13: session with no rows -> zeros (no crash)
stats = F.session_stats("sess-zzz")
ok("T13-no-rows", stats == {"calls": 0, "total_tokens": 0, "uncached": 0}, str(stats))

# T14: cmd_open without args -> usage message
out = capture(F.cmd_open, [])
ok("T14-open-usage", "usage:" in out, out)

# T15: monkeypatched KEYS path is inside the temp dir (isolation invariant)
ok("T15-isolated", KEYS.exists() and str(KEYS).startswith(str(TMP)), f"KEYS={KEYS}")

F2, P2 = sum(1 for _, c, _ in R if not c), sum(1 for _, c, _ in R if c)
print(f"FX05-TESTS {P2}/{len(R)}")
for name, c, got in R:
    if not c:
        print(f"FAIL {name} :: {got}")
sys.exit(1 if F2 else 0)
