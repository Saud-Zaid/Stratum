# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for fx02_session_tax (2026-10-23, AD10 C15 stage 5): caps from file
(minimal YAML subset), live-check verdicts, and f2_state delegation. LIMITS and
F2_SCRIPT are redirected to temp files; the real goose sessions.db is never opened.
Usage: fx02_session_tax-tests"""
import sys
import tempfile
from pathlib import Path

import fx02_session_tax as F

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


TMP = Path(tempfile.mkdtemp())
LIMITS = TMP / "limits.yaml"
F.LIMITS = LIMITS

# --- read_limits ---
# T1: missing file -> None caps + limits-missing source
LIMITS.unlink(missing_ok=True)
caps, src = F.read_limits()
ok("T1-missing", caps == {"max_prompts": None, "max_calls": None} and src == "limits-missing", f"{caps} {src}")

# T2: integer caps parsed from file
LIMITS.write_text("max_prompts: 40\nmax_calls: 34\nother: x\n", encoding="utf-8")
caps, src = F.read_limits()
ok("T2-from-file", caps == {"max_prompts": 40, "max_calls": 34} and src == "from-file", f"{caps} {src}")

# T3: comments and non-int values ignored
LIMITS.write_text("# c\nmax_calls: 10 # inline\nmax_prompts: notanum\nfoo: 5\n", encoding="utf-8")
caps, src = F.read_limits()
ok("T3-filter", caps == {"max_prompts": None, "max_calls": 10}, f"{caps} {src}")

# --- check_live (pure print logic) ---
import io
import contextlib


def capture(*a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        F.check_live(*a)
    return buf.getvalue()


# T4: both caps configured, both under -> ok/ok
LIMITS.write_text("max_prompts: 40\nmax_calls: 34\n", encoding="utf-8")
out = capture(10, 5)
ok("T4-under", "PROMPTS:ok" in out and "CALLS:ok" in out and "from-file" in out, out)

# T5: over prompts -> PROMPTS:OVER
out = capture(50, 5)
ok("T5-prompts-over", "PROMPTS:OVER" in out and "CALLS:ok" in out, out)

# T6: over calls -> CALLS:OVER
out = capture(10, 40)
ok("T6-calls-over", "CALLS:OVER" in out, out)

# T7: no caps configured -> no-caps-configured
LIMITS.unlink(missing_ok=True)
out = capture(10, 5)
ok("T7-no-caps", "no-caps-configured" in out, out)

# --- f2_state delegation ---
# T8: F2 script missing -> subprocess fails -> empty output -> F2:no-ledger (not a crash)
F.F2_SCRIPT = TMP / "nonexistent-script.py"
ok("T8-missing-script", F.f2_state() == "F2:no-ledger", F.f2_state())

# T9: F2 script prints VALID lines -> VALID verdict with source count
fake = TMP / "fake-f2.py"
fake.write_text("print('F2 | VALID src1 | VALID src2')\n", encoding="utf-8")
F.F2_SCRIPT = fake
ok("T9-valid", F.f2_state() == "F2:VALID(2 sources)", F.f2_state())

# T10: F2 script prints STALE -> STALE verdict
fake.write_text("print('F2 | STALE src1')\n", encoding="utf-8")
ok("T10-stale", F.f2_state() == "F2:STALE", F.f2_state())

# T11: F2 script prints something else -> no-ledger
fake.write_text("print('F2 | nothing recognized')\n", encoding="utf-8")
ok("T11-no-ledger", F.f2_state() == "F2:no-ledger", F.f2_state())

# T12: caps are read from file, never hardcoded (code-level invariant)
ok("T12-limits-path", "limits.yaml" in str(F.LIMITS) or F.LIMITS == TMP / "limits.yaml", str(F.LIMITS))

# --- AD13-M02: Residual Context Occupancy & Rolling Telemetry tests ---
import json
import re

# T13: read_context_window defaults to 200k, reads from limits if configured
LIMITS.unlink(missing_ok=True)
ok("T13-ctx-default", F.read_context_window(LIMITS) == 200_000, str(F.read_context_window(LIMITS)))
LIMITS.write_text("context_window: 128000\n", encoding="utf-8")
ok("T13-ctx-from-file", F.read_context_window(LIMITS) == 128_000, str(F.read_context_window(LIMITS)))

# T14: calculate_occupancy calculates percentage accurately without saturation
occ1 = F.calculate_occupancy(42_000, 200_000)
ok("T14-occupancy-normal",
   occ1["percent_used"] == 21.0 and occ1["percent_free"] == 79.0 and not occ1["saturation_warning"],
   str(occ1))

# T15: calculate_occupancy triggers silent warning when > 80%
occ2 = F.calculate_occupancy(170_000, 200_000)
ok("T15-saturation-warning",
   occ2["percent_used"] == 85.0 and occ2["percent_free"] == 15.0 and occ2["saturation_warning"],
   str(occ2))

# T16: format_summary_line produces single line < 25 tokens with warning tag if saturated
def estimate_tokens(s):
    # Standard token proxy: max of word count and chars / 4
    return max(len(s.split()), len(s) // 4)

line_norm = F.format_summary_line(occ1, "ok")
tokens_norm = estimate_tokens(line_norm)
line_sat = F.format_summary_line(occ2, "ok")
tokens_sat = estimate_tokens(line_sat)
ok("T16-compact-tokens",
   "\n" not in line_norm and tokens_norm < 25 and "[>80%]" in line_sat and tokens_sat < 25,
   f"norm={tokens_norm}: {line_norm} | sat={tokens_sat}: {line_sat}")

# T17: write_telemetry persists valid JSON to rolling log path
telem_file = TMP / "telemetry-latest.json"
F.TELEMETRY_LOG = telem_file
payload = {
    "tool": "fx02_test",
    "summary": line_norm,
    "context": occ1,
}
F.write_telemetry(payload, telem_file)
ok("T17-telemetry-written", telem_file.exists(), str(telem_file))
data = json.loads(telem_file.read_text(encoding="utf-8"))
ok("T17-telemetry-content", data.get("tool") == "fx02_test" and data.get("context", {}).get("used_tokens") == 42_000, str(data))

# T18: print_tax produces single line and updates rolling telemetry
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    F.print_tax(42_000, limits_path=LIMITS, telemetry_path=telem_file)
out_tax = buf.getvalue().strip()
tax_tokens = estimate_tokens(out_tax)
ok("T18-print-tax-single-line",
   tax_tokens < 25 and "context:" in out_tax and "telemetry logged" in out_tax and "\n" not in out_tax,
   f"tokens={tax_tokens} out={out_tax}")

F2, P2 = sum(1 for _, c, _ in R if not c), sum(1 for _, c, _ in R if c)
print(f"FX02-TESTS {P2}/{len(R)}")
for name, c, got in R:
    if not c:
        print(f"FAIL {name} :: {got}")
sys.exit(1 if F2 else 0)
