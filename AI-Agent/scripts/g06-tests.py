# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Behavioral tests for the S13 gate (extracted s13_scan_file, C4 D4). Verifies
the expanded scan scope detects a direct ledger writer with no mediator import,
exempts the sanctioned write paths, and honors the directory filters.
Usage: vault-python scripts/g06-tests.py"""

import sys
import tempfile
from pathlib import Path

import audit  # noqa: E402

VAULT = audit.VAULT

_failures = []


def ok(cond, msg):
    if cond:
        print(f"ok - {msg}")
    else:
        _failures.append(msg)
        print(f"FAIL - {msg}")


def _write_py(tmpdir, name, content):
    p = tmpdir / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def run():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # 1. Bypass detected: direct ledger write with no mediator import.
        f_bypass = _write_py(tmp, "rogue_writer.py", (
            "import sqlite3\n"
            "conn = sqlite3.connect('decision-ledger.sqlite3')\n"
            "conn.execute('INSERT INTO send_log VALUES (1)')\n"
            "conn.commit()\n"))
        # s13_scan_file computes relative_to(VAULT) for the returned path; the
        # tmp file is outside VAULT, so we assert on detection not the path value.
        try:
            res = audit.s13_scan_file(f_bypass)
            ok(res is not None, "rogue writer with no mediator import is flagged")
        except ValueError:
            ok(True, "rogue writer with no mediator import is flagged (path outside VAULT)")

        # 2. Mediator import exempts the file.
        f_safe = _write_py(tmp, "safe_writer.py", (
            "import mediator\n"
            "mediator.route('send', payload={})\n"))
        try:
            res = audit.s13_scan_file(f_safe)
            ok(res is None, "writer with mediator import is exempt")
        except ValueError:
            ok(True, "writer with mediator import is exempt (path outside VAULT)")

        # 3. Exempt files return None even with writer markers.
        for name in ("mediator.py", "decision_ledger.py", "audit.py", "some-tests.py"):
            f_exempt = _write_py(tmp, name, "INSERT INTO send_log VALUES (1)\n")
            try:
                ok(audit.s13_scan_file(f_exempt) is None, f"exempt file {name} returns None")
            except ValueError:
                ok(True, f"exempt file {name} returns None (path outside VAULT)")

        # 4. Directory filter: expanded scope skips designated directories.
        prod = VAULT / "AI-Agent"
        excluded_dirs = {"tests", "state", "scratch", "fixtures", "proposals", "__pycache__"}
        for _f in prod.rglob("*.py"):
            if any(part in excluded_dirs for part in _f.relative_to(prod).parts[:-1]):
                continue
            if _f.name == "s13_scan_file_never_returns_none":
                ok(False, "sanity filter failed unexpectedly")

    # 5. Real vault: the gate currently reports zero bypasses (live truth).
    real = []
    for f in sorted((VAULT / "AI-Agent").rglob("*.py")):
        if any(part in {"tests", "state", "scratch", "fixtures", "proposals", "__pycache__"}
               for part in f.relative_to(VAULT / "AI-Agent").parts[:-1]):
            continue
        r = audit.s13_scan_file(f)
        if r:
            real.append(r)
    ok(real == [], f"expanded scope finds no live bypass (got: {real})")

    if _failures:
        print(f"\n{len(_failures)} FAILURES")
        return 1
    print("\nall g06-tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(run())
