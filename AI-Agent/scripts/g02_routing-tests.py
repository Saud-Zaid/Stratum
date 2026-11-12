# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for g02_routing (2026-10-23, AD10 C15 stage 4): routing-row rendering
from the decision ledger. dl.entries is monkeypatched to return controlled rows --
the real decision-ledger.sqlite3 is never touched by tests.
Usage: g02_routing-tests"""
import io
import contextlib
import sys

import g02_routing as G

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


FAKE = [
    {"id": 1, "ts": "2026-10-01T10:00:00+03:00", "kind": "routing",
     "body": '{"task": "build feature", "decision_type": "model_select", "model_proposed": "gpt-4o", "model_approved": "gpt-4o"}'},
    {"id": 2, "ts": "2026-10-02T10:00:00+03:00", "kind": "routing",
     "body": '{"task": "review plan", "decision_type": "model_select", "model_proposed": "claude", "model_approved": null}'},
    {"id": 3, "ts": "2026-10-03T10:00:00+03:00", "kind": "other",
     "body": '{"task": "not routing"}'},
    {"id": 4, "ts": "2026-10-04T10:00:00+03:00", "kind": "routing",
     "body": '{"task": "t4", "decision_type": "model_select", "model_proposed": "m1", "model_approved": "m1"}'},
]


def run(entries, argv=None):
    G.dl.entries = lambda: entries
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        G.main(argv or [])
    return buf.getvalue()


# T1: only routing rows are rendered (id 3 with kind=other excluded)
out = run(FAKE, ["--all"])
ok("T1-kind-filter", "RT1" in out and "RT2" in out and "RT4" in out, out)
ok("T1b-no-other", "RT3" not in out, out)

# T2: approved model printed; null approved -> pending
ok("T2-approved", "approved=gpt-4o" in out and "approved=pending" in out, out)

# T3: ts date prefix printed (first 10 chars)
ok("T3-date", "2026-10-01" in out and "2026-10-02" in out, out)

# T4: summary line with correct count
ok("T4-count", "G02ROUTING 3 routing rows" in out, out)

# T5: without --all only the last 10 routing rows are shown (3 <= 10, all shown)
out2 = run(FAKE, [])
ok("T5-default-10", "G02ROUTING 3 routing rows" in out2, out2)

# T6: >10 routing rows without --all -> only last 10 shown
many = FAKE[:2] + [{"id": i, "ts": f"2026-09-{i:02d}T10:00:00+03:00", "kind": "routing",
                    "body": '{"task": "t", "decision_type": "d", "model_proposed": "m", "model_approved": null}'}
                   for i in range(10, 30)]
out3 = run(many, [])
# routing rows total = 2 + 20 = 22; without --all only last 10 shown
ok("T6-last-10", "G02ROUTING 10 routing rows" in out3 and "RT1" not in out3, out3)

# T7: empty ledger -> 0 rows, no crash
out4 = run([], [])
ok("T7-empty", "G02ROUTING 0 routing rows" in out4, out4)

# T8: missing decision_type falls back to '?'
fake_missing = [{"id": 9, "ts": "2026-10-05T10:00:00+03:00", "kind": "routing",
                 "body": '{"task": "t", "model_proposed": "m"}'}]
out5 = run(fake_missing, ["--all"])
ok("T8-fallback", "?" in out5, out5)

# T9: body line shape (TSV-ish with :: separator)
ok("T9-shape", " :: " in out and "proposed=" in out, out)

F, P = sum(1 for _, c, _ in R if not c), sum(1 for _, c, _ in R if c)
print(f"G02ROUTING-TESTS {P}/{len(R)}")
for name, c, got in R:
    if not c:
        print(f"FAIL {name} :: {got}")
sys.exit(1 if F else 0)
