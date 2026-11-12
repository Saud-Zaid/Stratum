#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for session_budget (FX02/FX12, execution cycle 1). Usage: session_budget-tests"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import session_budget as SB

passed = failed = 0


def ok(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {extra}")


GOOD = """---
status: active
tags: [FX02]
created: 2026-10-24
---

# Task budget ceilings (FX02/FX12)

- "call_cost_note|Every call costs the full context"
- "small|12"
- "medium|25"
- "delegation|30"
"""


def write_map(text):
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# T1: happy path parses all three types + note
caps, note = SB.load_budget(write_map(GOOD))
ok("t1_parses", caps == {"small": 12, "medium": 25, "delegation": 30}, repr(caps))
ok("t1_note", "call" in note)

# T2: negative — missing block raises ValueError (never proceeds blindly)
try:
    SB.load_budget(write_map("---\nstatus: active\ntags: [t]\ncreated: 2026-01-01\n---\n\n# other section\n\n- \"x|1\"\n"))
    ok("t2_no_block", False, "no ValueError")
except ValueError:
    ok("t2_no_block", True)

# T3: negative — non-numeric ceiling raises ValueError
try:
    SB.load_budget(write_map(GOOD.replace("- \"small|12\"", "- \"small|twelve\"")))
    ok("t3_nonnum", False, "no ValueError")
except ValueError:
    ok("t3_nonnum", True)

# T4: negative — duplicate type raises ValueError
try:
    SB.load_budget(write_map(GOOD.replace("- \"medium|25\"", "- \"small|25\"")))
    ok("t4_dup", False, "no ValueError")
except ValueError:
    ok("t4_dup", True)

# T5: negative — missing note raises ValueError
try:
    SB.load_budget(write_map(GOOD.replace("- \"call_cost_note|Every call costs the full context\"\n", "")))
    ok("t5_no_note", False, "no ValueError")
except ValueError:
    ok("t5_no_note", True)

# T6: unknown task type raises ValueError (never a silent default)
try:
    SB.ceiling_for("huge", caps)
    ok("t6_unknown", False, "no ValueError")
except ValueError:
    ok("t6_unknown", True)

# T7: start line carries ceiling and note from the file
line = SB.start_line("medium", caps, note)
ok("t7_start", "ceiling=25" in line and "task=medium" in line, line)

# T8: close OK under ceiling
line, status = SB.close_line("small", 12, caps)
ok("t8_ok", status == "OK" and "actual=12" in line, line)

# T9: close OVER beyond ceiling
line, status = SB.close_line("small", 13, caps)
ok("t9_over", status == "OVER" and "ceiling=12" in line, line)

# T10: real CLI — --start on the real map exits 0 and prints the line
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'session_budget.py')
r = os.system(f"python3 '{SCRIPT}' --start medium > /dev/null")
ok("t10_cli_start", r == 0)

# T11: real CLI — --close over the ceiling exits non-zero (the gate fires)
r = os.system(f"python3 '{SCRIPT}' --close small 99 > /dev/null")
ok("t11_cli_over", r != 0)

print(f"PASSED {passed} FAILED {failed}")
sys.exit(0 if failed == 0 else 1)
