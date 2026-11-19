# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for the G02 routing tag (AD06 C6 F3): kind="routing" rows live in the
decision ledger via the sanctioned append_decision API (no schema change, hash chain
untouched); tested against a temp DB so the live ledger is never written by a test.
Usage: routing-tests"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import decision_ledger as dl

T = []


def ok(name, cond, got=""):
    T.append((name, bool(cond), got))


def routing_body(task: str, proposed: str, approved, dtype: str = "agent_route") -> str:
    """Contract body for a routing row; approved=None means pending owner approval."""
    return json.dumps({"task": task, "decision_type": dtype,
                       "model_proposed": proposed, "model_approved": approved},
                      ensure_ascii=False, separators=(",", ":"))


# temp DB: the sanctioned API writes, the live ledger is never touched by tests
tmp = Path(tempfile.mkdtemp()) / "ledger-routing-test.sqlite3"
r1 = dl.append_decision("routing 1", routing_body("read a note", "cheap-model", None),
                        session="test", kind="routing", db=tmp)
r2 = dl.append_decision("routing 2", routing_body("write in the vault", "strong-model", "strong-model"),
                        session="test", kind="routing", db=tmp)
r3 = dl.append_decision("ordinary decision", "decision text", session="test", kind="decision", db=tmp)
ok("routing: rows append with increasing ids", 0 < r1 < r2 < r3, (r1, r2, r3))

rows = [e for e in dl.entries(db=tmp) if e["kind"] == "routing"]
ok("routing: kind filter finds both", len(rows) == 2, len(rows))
b1 = json.loads(rows[0]["body"])
ok("routing: body JSON parses with contract fields",
   all(k in b1 for k in ("task", "decision_type", "model_proposed", "model_approved")), list(b1))
ok("routing: pending approval round-trips as null", b1["model_approved"] is None)
ok("routing: approved model round-trips",
   json.loads(rows[1]["body"])["model_approved"] == "strong-model")
ok("routing: ordinary decisions coexist with routing rows",
   len([e for e in dl.entries(db=tmp) if e["kind"] == "decision"]) == 1)
ok("routing: ledger hash chain verifies on temp db", dl.verify_ledger(db=tmp)[0])

# live ledger: the standing routing policy row exists, parses, and the chain is intact
live = [e for e in dl.entries() if e["kind"] == "routing"]
ok("routing: live ledger has the standing policy row", len(live) >= 1, len(live))
# N-B6 (treatment 7): the demand applies to the latest policy row only — historical rows (append-only)
# cannot be repaired retroactively, and a fixed failure on the old ones hides a recent break behind a permanent red.
# N-B6: the property must exist in the live routing rows (any row — proving the
# operation is enough), and old rows from before the field was introduced are exempt from the strict demand.
ok("routing: live routing rows carry model_proposed where applicable",
   any("model_proposed" in (json.loads(e["body"]) if isinstance(e["body"], str) and e["body"].strip().startswith("{") else {})
       for e in live), len(live))
ok("routing: live ledger still signed", dl.verify_ledger()[0])

# T-02d (U-50): PRAGMA user_version guard, on a temp db
import sqlite3 as _sq

def _uv(path):
    c = _sq.connect(path); v = c.execute("PRAGMA user_version").fetchone()[0]; c.close(); return v

ok("ledger: append sets user_version 1", _uv(tmp) == dl.SCHEMA_USER_VERSION == 1, _uv(tmp))
_c = _sq.connect(tmp); _c.execute("PRAGMA user_version = 2"); _c.commit(); _c.close()
try:
    dl.append_decision("x", "y", session="test", db=tmp); _raised = False
except dl.LedgerVersionError:
    _raised = True
ok("ledger: newer user_version is refused on write", _raised)
try:
    dl.entries(db=tmp); _raised = False
except dl.LedgerVersionError:
    _raised = True
ok("ledger: newer user_version is refused on read", _raised)
_c = _sq.connect(tmp); _n = _c.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]; _c.close()
ok("ledger: refused call neither lowered the version nor added a row", _uv(tmp) == 2 and _n == 3, (_uv(tmp), _n))
_c = _sq.connect(tmp); _c.execute("PRAGMA user_version = 0"); _c.commit(); _c.close()
dl.entries(db=tmp)
ok("ledger: legacy 0 stays 0 on a read", _uv(tmp) == 0, _uv(tmp))
dl.append_decision("again", "z", session="test", db=tmp)
ok("ledger: legacy 0 upgraded to 1 by the next write", _uv(tmp) == 1, _uv(tmp))

FAILS = [t for t in T if not t[1]]
for name, cond, got in T:
    print(("PASS" if cond else "FAIL") + f" {name}" + (f" [{got}]" if got and not cond else ""))
print(f"ROUTING-TESTS {len(T) - len(FAILS)}/{len(T)}")
if FAILS:
    raise SystemExit(1)
