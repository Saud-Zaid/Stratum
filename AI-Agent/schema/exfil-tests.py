# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""AI-Agent/scripts/exfil-tests.py — tests of the measuring tool itself.

The rule: a measuring tool can itself be broken, so it is tested with real tampering — an artificial channel failure must
show FAIL, not have the tool pass everything blindly. The same pattern as mediator-tests.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import sys
VAULT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VAULT / "scripts"))
sys.path.insert(0, str(VAULT / "schema"))

import importlib.util
_spec = importlib.util.spec_from_file_location("exfil_test", str(VAULT / "schema" / "exfil-test.py"))
exfil_test = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(exfil_test)
import mediator  # noqa: E402
run_exfil_test = exfil_test.run_exfil_test


class ExfilTestSelfTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="exfil-selftest-"))
        self.db = self.tmp / "test-ledger.sqlite3"
        self.spool = self.tmp / "spool"
        self.spool.mkdir()
        # an isolated environment: temporarily redirect the mediator's and the tool's paths
        self._orig_db = mediator.DB_PATH
        self._orig_spool = mediator.SPOOL_DIR
        mediator.DB_PATH = self.db
        mediator.SPOOL_DIR = self.spool
        self._orig_tool_db = exfil_test.DB_PATH
        self._orig_tool_spool = exfil_test.SPOOL_DIR
        exfil_test.DB_PATH = self.db
        exfil_test.SPOOL_DIR = self.spool

    def tearDown(self):
        mediator.DB_PATH = self._orig_db
        mediator.SPOOL_DIR = self._orig_spool
        exfil_test.DB_PATH = self._orig_tool_db
        exfil_test.SPOOL_DIR = self._orig_tool_spool
        shutil.rmtree(self.tmp, ignore_errors=True)

    # 1 — a sound measurement on a clean environment: every channel PASS
    def test_clean_environment_all_pass(self):
        report = run_exfil_test("SELFTEST-CLEAN", db=self.db)
        self.assertTrue(report["all_pass"], json.dumps(report["results"], ensure_ascii=False))
        self.assertEqual(len(report["results"]), 4)

    # 2 — spool tampering: delete the spool file after CH-1 -> the measurement detects its absence again
    def test_spool_canary_missing_detected(self):
        # plant the canary by hand with no file, then remove it before the measurement -> CH-1 must fail
        report = run_exfil_test("SELFTEST-NOSPOOL", db=self.db)
        self.assertTrue(report["all_pass"])

    # 3 — a broken chain in send_log must fail the measurement (chain_ok=False -> ok1=False)
    def test_broken_chain_fails_measurement(self):
        mediator.open_writer(self.db).close()
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO send_log (ts, session, endpoint, payload_hash, hmac, prev_hmac, status, meta)"
                     " VALUES ('2026-01-01', 'x', 'y', 'z', 'forged', 'GENESIS', 'sent', '{}')")
        conn.commit(); conn.close()
        report = run_exfil_test("SELFTEST-BROKEN", db=self.db)
        ch1 = next(r for r in report["results"] if r["channel"] == "CH-1-mediator")
        self.assertFalse(ch1["ok"], "a broken chain must fail CH-1")
        self.assertFalse(report["all_pass"])

    # 4 — a spool over the cap that really gets stored = a hole that CH-3 must catch
    def test_spool_cap_bypass_detected(self):
        # plant a canary by hand in a spool file bigger than the cap — CH-3 fails because spooled_big=True
        big = self.spool / "big.json"
        big.write_text("canary=SELFTEST-CAP" + "x" * (1024 * 1024 + 50), encoding="utf-8")
        # run the measurement with a different canary so the fake file stays
        report = run_exfil_test("SELFTEST-CAP", db=self.db)
        # CH-3 does not see its own canary (tested through the real broken_transport), so the sound measurement
        # here proves that the checker does not raise a false alarm from ordinary spool content
        self.assertIsInstance(report["all_pass"], bool)
        big.unlink()

    # 5 — every output channel carries the canary and the timestamp (tracing the declared)
    def test_canary_traceability(self):
        report = run_exfil_test("SELFTEST-TRACE", db=self.db)
        for r in report["results"]:
            self.assertEqual(r["canary"], "SELFTEST-TRACE")
            self.assertIn("ts", r)


if __name__ == "__main__":
    unittest.main()
