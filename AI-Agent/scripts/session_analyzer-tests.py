#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Behavioral tests for session_analyzer.py. Run: AI-Agent/vault-python AI-Agent/scripts/session_analyzer-tests.py"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contextlib
import io
from session_analyzer import analyze_file, main as analyzer_main  # noqa: E402

FAILURES = []
CHECKS = []


def check_test(name, cond):
    CHECKS.append(name)
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}")
        FAILURES.append(name)


FIXTURE = [
    {"task": "G001", "phase": "plan", "thought": "t", "action": "a", "obs": "o", "tokens": 5, "ms": 1.0},
    {"task": "G001", "phase": "execute", "thought": "t", "action": "a", "obs": "o", "tokens": 100, "ms": 2.0},
    {"task": "G001", "phase": "correct", "thought": "t", "action": "a", "obs": "loaded 200 tok", "tokens": 200, "ms": 3.0},
    {"task": "G001", "phase": "done", "thought": "t", "action": "a", "obs": "hit", "tokens": 0, "ms": 0.1},
]


def main():
    print("session_analyzer behavioral tests")
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "fix.jsonl"
        f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in FIXTURE), encoding="utf-8")
        a = analyze_file(f)
        check_test("tokens sum 305", a["tokens"] == 305)
        check_test("steps 4", a["steps"] == 4)
        check_test("phases split correct", a["phases"] == "correct:200,done:0,execute:100,plan:5")
        check_test("reloads 1 (correct with tokens)", a["reloads"] == 1)
        check_test("maxstep 200", a["maxstep"] == 200)
        empty = Path(td) / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        a2 = analyze_file(empty)
        check_test("empty log -> zeros", a2["tokens"] == 0 and a2["steps"] == 0)
        # a real loop log (if the smoke run produced one) must parse cleanly
        real = Path(__file__).resolve().parents[1] / "state" / "ad07" / "agent-loop.jsonl"
        if real.exists():
            a3 = analyze_file(real)
            check_test("real agent-loop log parses with tokens>0", a3["tokens"] > 0 and a3["steps"] > 0)
            check_test("real log has plan phase", "plan:" in a3["phases"])

        # --- AD13-M02: Measurement Pollution Guard & Rolling Telemetry tests ---
        telem_p = Path(td) / "telemetry-latest.json"
        limits_p = Path(td) / "limits.yaml"
        limits_p.write_text("context_window: 200000\n", encoding="utf-8")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            summary = analyzer_main([str(f)], limits_path=limits_p, telemetry_path=telem_p)
        out = buf.getvalue().strip()

        # Token estimate check (< 25 tokens)
        tok_count = max(len(out.split()), len(out) // 4)
        check_test("single line output (no newlines in default mode)", "\n" not in out)
        check_test("compact output < 25 tokens", tok_count < 25)
        check_test("summary contains context occupancy and telemetry logged",
                   "context:" in out and "telemetry logged" in out)

        # Telemetry rolling log file checks
        check_test("telemetry-latest.json created", telem_p.exists())
        telem_data = json.loads(telem_p.read_text(encoding="utf-8"))
        check_test("telemetry tool is session_analyzer", telem_data.get("tool") == "session_analyzer")
        check_test("telemetry context used_tokens matches 305",
                   telem_data.get("context", {}).get("used_tokens") == 305)
        check_test("telemetry totals contains tokens and files count",
                   telem_data.get("totals", {}).get("tokens") == 305 and
                   telem_data.get("totals", {}).get("files_count") == 1)
        check_test("telemetry files contains breakdown matrix",
                   len(telem_data.get("files", [])) == 1 and
                   "correct:200" in telem_data["files"][0]["phases"])

        # Verbose mode output check
        buf_v = io.StringIO()
        with contextlib.redirect_stdout(buf_v):
            analyzer_main([str(f), "--verbose"], limits_path=limits_p, telemetry_path=telem_p)
        out_v = buf_v.getvalue()
        check_test("verbose mode prints per-file FX01 details", "FX01 fix.jsonl tokens=305" in out_v)
    print(f"\n{len(CHECKS) - len(FAILURES)}/{len(CHECKS)} passed")
    if FAILURES:
        sys.exit(1)


if __name__ == "__main__":
    main()
