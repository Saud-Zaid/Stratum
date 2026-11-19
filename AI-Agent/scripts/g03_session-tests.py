# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for g03_session (2026-10-23, AD10 C15 stage 5): the anti-repayment
session memory (mark/check/serve/reload_savings), the warm-start section splitter,
and the compact builder. MEMLOG, HANDOFF and _state_text are redirected to temp
files -- the real session-memory.jsonl is never touched by tests.
Usage: g03_session-tests"""
import sys
import tempfile
from pathlib import Path

import g03_session as G

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


TMP = Path(tempfile.mkdtemp())
G.MEMLOG = TMP / "session-memory.jsonl"

# --- SessionMem (layer 1) ---
# T1: fresh session -> nothing marked
m = G.SessionMem("s1")
ok("T1-fresh", m.check("file-a.md") is False, str(m._loads))

# T2: mark registers the file, check confirms
m.mark("file-a.md", tokens=100)
ok("T2-mark-check", m.check("file-a.md") is True, str(m._loads))

# T3: reload_savings counts what a second serve would have re-read
text = "some content to serve"
t = G.tokens_of(text)
G.SessionMem._saved = 0
m2 = G.SessionMem("s2")
m2.serve("x.md", text)          # first serve: real read
m2.serve("x.md", text)          # second serve: from record, saves t tokens
ok("T3-savings", m2.reload_savings() == t, f"saved={m2.reload_savings()} expected={t}")

# T4: serve returns the text and a read flag (1 first, 0 repeat)
G.SessionMem._saved = 0
m3 = G.SessionMem("s3")
body, n = m3.serve("y.md", "content")
ok("T4-first-serve", body == "content" and n == 1, f"n={n}")
body, n = m3.serve("y.md", "content")
ok("T4b-second-serve", body == "content" and n == 0, f"n={n}")

# T5: memlog file written in the temp dir (isolation)
ok("T5-memlog-isolated", G.MEMLOG.exists() and str(G.MEMLOG).startswith(str(TMP)), str(G.MEMLOG))

# T6: memlog lines are JSON with session/file/n/tokens
import json
lines = [json.loads(l) for l in G.MEMLOG.read_text(encoding="utf-8").splitlines()]
ok("T6-memlog-shape", all(set(("session", "file", "n", "tokens")) <= set(l) for l in lines), str(lines[:2]))

# --- _section splitter ---
STATE_TEXT = """## git
head abc1234 msg
uncommitted 3 files
## gate
GATE CLEAR blocking=0
## active work
- proj1.md\topen 2
    next\tstep one
    log\t2026-10-20 did a
- proj2.md\topen 1
    next\tstep two
## due
due\t2026-10-25\tnote.md
"""

# T7: extracts lines under the matching heading only
got = G._section(STATE_TEXT, "## git")
ok("T7-git", got == ["head abc1234 msg", "uncommitted 3 files"], str(got))

# T8: another section
got = G._section(STATE_TEXT, "## gate")
ok("T8-gate", got == ["GATE CLEAR blocking=0"], str(got))

# T9: missing heading -> empty
ok("T9-missing", G._section(STATE_TEXT, "## club") == [], "expected empty")

# --- warmstart compact builder ---
G._state_text = lambda: STATE_TEXT
(HANDOFF := TMP / "handoff.md").write_text("# handoff content\n", encoding="utf-8")
G.HANDOFF = HANDOFF

w = G.warmstart()
body = w["body"]

# T10: compact keeps exactly ONE next step per project (log lines dropped)
ok("T10-one-next", body.count("step one") == 1 and body.count("step two") == 1, body)

# T11: logs are dropped from the compact body
ok("T11-logs-dropped", "did a" not in body, body)

# T12: project lines preserved
ok("T12-projects", "proj1.md" in body and "proj2.md" in body, body)

# T13: git section compacted (head line kept, uncommitted as count)
ok("T13-git-compact", "head abc1234 msg" in body and "uncommitted 1 files" in body, body)

# T14: token accounting is consistent
ok("T14-tokens", w["warmstart_tokens"] == w["handoff_tokens"] + w["compact_tokens"], str(w))

# T15: full state tokens > compact tokens (compression happened)
ok("T15-compression", w["full_tokens"] > w["compact_tokens"], f"full={w['full_tokens']} compact={w['compact_tokens']}")

# T16: ms is a non-negative float
ok("T16-ms", isinstance(w["ms"], float) and w["ms"] >= 0, str(w["ms"]))

# --- cross-process mem log (T17-T22): state lives in MEMLOG, CLI mark/check/stats read it back ---
import os
import subprocess

G.MEMLOG = TMP / "cli-memory.jsonl"
G.SessionMem("c1").mark("x.md", tokens=5)
G.SessionMem("c1").mark("x.md", tokens=5)      # a second process: the count continues from the log
ok("T17-count-continues-across-instances", [r["n"] for r in G._memlog_rows("c1")] == [1, 2], G._memlog_rows("c1"))
ok("T18-session-loaded", G.session_loaded("c1", "x.md") and not G.session_loaded("c1", "y.md") and not G.session_loaded("c2", "x.md"))
ok("T19-stats", G.mem_stats("c1") == {"files": 1, "loads": 2, "reloads": 1}, G.mem_stats("c1"))
with open(G.MEMLOG, "a", encoding="utf-8") as f:
    f.write("not json\n")
ok("T20-damaged-line-skipped", G.mem_stats("c1")["loads"] == 2)
G.MEMLOG = TMP / "absent.jsonl"
ok("T21-missing-log-is-empty", G.mem_stats("c1") == {"files": 0, "loads": 0, "reloads": 0})


def _cli(*a, **env):
    e = dict(os.environ, **env)
    return subprocess.run([sys.executable, str(Path(G.__file__).resolve()), *a], capture_output=True, text=True, encoding="utf-8", errors="replace", env=e, timeout=60)


ok("T22-help-rc0", _cli("--help").returncode == 0 and _cli("-h").returncode == 0)
ok("T23-unknown-flag-rc2", _cli("--bogus").returncode == 2)
ok("T24-mem-bad-subcommand-rc2", _cli("mem", "nonsense").returncode == 2)
ok("T25-mem-check-without-file-rc2", _cli("mem", "check").returncode == 2)

F, P = sum(1 for _, c, _ in R if not c), sum(1 for _, c, _ in R if c)
print(f"G03-TESTS {P}/{len(R)}")
for name, c, got in R:
    if not c:
        print(f"FAIL {name} :: {got}")
sys.exit(1 if F else 0)
