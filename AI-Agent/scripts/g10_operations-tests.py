# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for g10_operations (2026-10-23, AD10 C15 stage 4): the operations
SQLite store. SRC and DB are redirected to temp files before any call -- the real
operations.sqlite3 is never touched by tests (isolation is asserted below).
Usage: g10_operations-tests"""
import sys
import tempfile
from pathlib import Path

import g10_operations as G

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


TMP = Path(tempfile.mkdtemp())
SRC = TMP / "operations.md"
DB = TMP / "operations.sqlite3"

G.SRC = SRC
G.DB = DB

OPS = """- **op:** OP-0001 · 2026-10-20T10:00:00+03:00 · agent-a · applied · base=abc1234 · did the thing
- **step:** OP-0001 · 1 · file-a.md · before=old · after=new
- **step:** OP-0001 · 2 · file-b.md · before=x · after=y
- **op:** OP-0002 · 2026-10-21T10:00:00+03:00 · agent-b · rolled_back · base=def5678 · reverted thing
- **step:** OP-0002 · 1 · file-c.md · before=z · after=w
- **op:** OP-0003 · 2026-10-22T10:00:00+03:00 · agent-a · failed · base=fff0001 · broken op
some prose line that matches nothing
"""
SRC.write_text(OPS, encoding="utf-8")

# T1: rebuild parses OP and STEP lines
r = G.rebuild()
ok("T1-rebuild-counts", r == {"ops": 3, "steps": 3}, str(r))

# T2: rebuild skips prose lines (only OP-0001/2/3)
ok("T2-prose-skipped", r["ops"] == 3 and "OP-0003" in OPS, str(r))

# T3: query returns op with steps in order
q = G.query("OP-0001")
ok("T3-query-found", q["found"] is True and q["steps"] == 2, str({k: q[k] for k in ("op_id", "found", "steps")}))

# T4: query body has op line + step lines in seq order
ok("T4-body-order", "step 1: file-a.md" in q["body"] and "step 2: file-b.md" in q["body"] and q["body"].index("step 1") < q["body"].index("step 2"), q["body"])

# T5: query includes status and base
ok("T5-op-fields", "applied" in q["body"] and "base=abc1234" in q["body"], q["body"])

# T6: query token cost is a positive int
ok("T6-tokens", isinstance(q["tokens"], int) and q["tokens"] > 0, str(q["tokens"]))

# T7: query ms is a float (timing measured)
ok("T7-ms", isinstance(q["ms"], float), str(q["ms"]))

# T8: query miss -> found=False, no crash
q2 = G.query("OP-9999")
ok("T8-miss", q2["found"] is False and "body" not in q2, str(q2))

# T9: stats aggregates correctly
s = G.stats()
ok("T9-stats", s["ops"] == 3 and s["steps"] == 3 and s["status"] == {"applied": 1, "rolled_back": 1, "failed": 1}, str(s))

# T10: stats src_tokens counts the whole source file
ok("T10-src-tokens", s["src_tokens"] > 0, str(s["src_tokens"]))

# T11: rebuild is idempotent (re-run -> same counts)
r2 = G.rebuild()
ok("T11-idempotent", r2 == r, f"{r2} vs {r}")

# T12: empty source -> zero ops, no crash
SRC.write_text("prose only, no ops\n", encoding="utf-8")
r3 = G.rebuild()
ok("T12-empty", r3 == {"ops": 0, "steps": 0}, str(r3))

# T13: isolation invariant -- DB path is inside temp dir
ok("T13-isolated", str(G.DB).startswith(str(TMP)) and not str(G.DB).endswith("state/operations.sqlite3"), f"DB={G.DB}")

# T14: status dict maps each status correctly (rebuild again after emptying)
SRC.write_text(OPS, encoding="utf-8")
G.rebuild()
s2 = G.stats()
ok("T14-status-again", s2["status"] == {"applied": 1, "rolled_back": 1, "failed": 1}, str(s2))

# --- T-02d (U-50): PRAGMA user_version guard ---
import sqlite3

def _uv():
    c = sqlite3.connect(DB); v = c.execute("PRAGMA user_version").fetchone()[0]; c.close(); return v

ok("T15-rebuild-sets-user-version-1", _uv() == 1, str(_uv()))
G.rebuild()
ok("T16-rebuild-keeps-user-version-1", _uv() == 1)
_c = sqlite3.connect(DB); _c.execute("PRAGMA user_version = 2"); _c.commit(); _c.close()
for _name, _fn in (("rebuild", G.rebuild), ("query", lambda: G.query("OP-0001")), ("stats", G.stats)):
    try:
        _fn(); _raised = False
    except RuntimeError as e:
        _raised = "newer than supported" in str(e)
    ok(f"T17-{_name}-refuses-newer-schema", _raised)
ok("T18-newer-version-not-lowered", _uv() == 2, str(_uv()))
_c = sqlite3.connect(DB); _c.execute("PRAGMA user_version = 0"); _c.commit(); _c.close()
G.query("OP-0001")
ok("T19-read-does-not-write-version", _uv() == 0, str(_uv()))
G.rebuild()
ok("T20-legacy-zero-upgraded-by-write", _uv() == 1)

F, P = sum(1 for _, c, _ in R if not c), sum(1 for _, c, _ in R if c)
print(f"G10-TESTS {P}/{len(R)}")
for name, c, got in R:
    if not c:
        print(f"FAIL {name} :: {got}")
sys.exit(1 if F else 0)
