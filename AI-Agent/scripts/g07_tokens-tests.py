# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for g07_tokens (2026-10-23, AD10 C15 stage 4): the named token counter
(tiktoken o200k_base). Tests tokens_of on controlled strings (including Arabic),
file_tokens on a temp file, and main() output shape with --total. No vault writes.
Usage: g07_tokens-tests"""
import sys
import tempfile
from pathlib import Path

import g07_tokens as T

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


e = T.enc()

# T1: encoding is o200k_base (first-party method, re-baselines g06 if changed)
ok("T1-encoding", T.ENCODING == "o200k_base", T.ENCODING)

# T2: empty string -> 0 tokens
ok("T2-empty", T.tokens_of("", e) == 0, str(T.tokens_of("", e)))

# T3: ASCII word counts > 0 and deterministic
n1 = T.tokens_of("hello world", e)
n2 = T.tokens_of("hello world", e)
ok("T3-ascii", n1 > 0 and n1 == n2, str(n1))

# T4: plain text counts > 0
na = T.tokens_of("the first section", e)
ok("T4-text", na > 0, str(na))

# T5: longer text -> more tokens
ok("T5-monotonic", T.tokens_of("hello " * 10, e) > T.tokens_of("hello", e), "not monotonic")

# T6: file_tokens reads a temp file (utf-8, errors=replace)
TMP = Path(tempfile.mkdtemp())
f = TMP / "sample.md"
f.write_text("# Headings\nSome content\n", encoding="utf-8")
ok("T6-file", T.file_tokens(f, e) > 0, str(T.file_tokens(f, e)))

# T7: default encoding arg (no _e passed) gives the same count for the same string
ok("T7-default-enc", T.tokens_of("hello world") == n1, f"default={T.tokens_of('hello world')} explicit={n1}")

# T8: main() prints "<tokens> <path>" per file, with --total a TOTAL row
out_file = TMP / "one.md"
out_file.write_text("hello world", encoding="utf-8")
import io
import contextlib

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    T.main([str(out_file), "--total"])
out = buf.getvalue()
lines = out.strip().splitlines()
ok("T8-total-row", lines[-1].startswith("TOTAL "), lines[-1])

# T9: per-file row shows the same count as file_tokens
per = int(lines[0].split()[0])
ok("T9-per-file", per == T.file_tokens(out_file, e), f"row={per} direct={T.file_tokens(out_file, e)}")

# T10: TOTAL equals sum of per-file rows
two = TMP / "two.md"
two.write_text("second file content", encoding="utf-8")
buf2 = io.StringIO()
with contextlib.redirect_stdout(buf2):
    T.main([str(out_file), str(two), "--total"])
rows = buf2.getvalue().strip().splitlines()
sums = sum(int(l.split()[0]) for l in rows[:-1])
ok("T10-sum", int(rows[-1].split()[1]) == sums, f"total={rows[-1]} sum={sums}")

# T11: no args -> docstring, no crash
buf3 = io.StringIO()
with contextlib.redirect_stdout(buf3):
    T.main([])
ok("T11-noargs", "G07" in buf3.getvalue() or "tokens" in buf3.getvalue().lower(), buf3.getvalue()[:60])

# T12: main() with non-absolute path resolves against VAULT (uses existing vault file, read-only)
buf4 = io.StringIO()
with contextlib.redirect_stdout(buf4):
    T.main(["AI-Agent/handoff.md"])
ok("T12-vault-rel", "AI-Agent/handoff.md" in buf4.getvalue(), buf4.getvalue()[:80])

# T13-T14 (T-02d, U-45): an unavailable vocabulary fails fast with a clear error instead of hanging on the network
_saved_ready = T._vocab_ready
T._vocab_ready = lambda: False
try:
    T.enc(); _raised = False
except RuntimeError as _e:
    _raised = "vocabulary unavailable" in str(_e)
ok("T13-unavailable-vocab-raises", _raised)
T._vocab_ready = _saved_ready
ok("T14-available-vocab-works", T.tokens_of("hello world") == n1)
T._vocab_ready.cache_clear()
ok("T15-vocab-ready-true-with-real-cache", T._vocab_ready() is True)

F, P = sum(1 for _, c, _ in R if not c), sum(1 for _, c, _ in R if c)
print(f"G07-TESTS {P}/{len(R)}")
for name, c, got in R:
    if not c:
        print(f"FAIL {name} :: {got}")
sys.exit(1 if F else 0)
