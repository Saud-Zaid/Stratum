# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""AI-Agent/schema/isolation-tests.py — real behavioural tests for the periodic isolation check.

Every test performs real tampering (deletion / modification / insertion / a key inside the vault / a recorded escape / staleness)
rather than static samples — the same pattern as mediator-tests.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import isolation
from isolation import (
    IsolationViolation,
    PROBES,
    check_isolation,
    ensure_key,
    load_key,
    record,
    verify_chain,
)


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="iso-tests-"))
        self.report = self.tmp / "isolation-report.json"
        self.key = self.tmp / "isolation-hmac.key"
        self.key.write_bytes(b"k" * 48)
        self._orig_keypath = isolation.KEY_PATH
        isolation.KEY_PATH = self.key

    def tearDown(self):
        isolation.KEY_PATH = self._orig_keypath
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _probes_all_expected(self):
        return [{"id": pid, "verdict": spec["expected"], "detail": f"probe {pid} live"}
                for pid, spec in PROBES.items()]

    # 1 — a full record, then verify_chain passes
    def test_record_and_verify_roundtrip(self):
        e1 = record(self._probes_all_expected(), path=self.report)
        self.assertTrue(e1["ok"])
        e2 = record(self._probes_all_expected(), path=self.report)
        self.assertEqual(e2["prev"], e1["mac"])
        ok, why = verify_chain(self.report, key=self.key.read_bytes())
        self.assertTrue(ok, why)

    # 2 — deleting a row breaks the chain
    def test_chain_break_on_delete(self):
        record(self._probes_all_expected(), path=self.report)
        record(self._probes_all_expected(), path=self.report)
        record(self._probes_all_expected(), path=self.report)
        entries = json.loads(self.report.read_text(encoding="utf-8"))["entries"]
        del entries[1]
        tampered = self.tmp / "tampered.json"
        tampered.write_text(json.dumps({"entries": entries}), encoding="utf-8")
        ok, why = verify_chain(tampered, key=self.key.read_bytes())
        self.assertFalse(ok)
        self.assertIn("prev", why)

    # 3 — modifying an observation after signing is caught by the signature
    def test_chain_break_on_tamper(self):
        record(self._probes_all_expected(), path=self.report)
        entries = json.loads(self.report.read_text(encoding="utf-8"))["entries"]
        entries[0]["probes"][0]["verdict"] = "pass" if entries[0]["probes"][0]["verdict"] != "pass" else "blocked"
        tampered = self.tmp / "tampered.json"
        tampered.write_text(json.dumps({"entries": entries}), encoding="utf-8")
        ok, why = verify_chain(tampered, key=self.key.read_bytes())
        self.assertFalse(ok)
        self.assertIn("signature", why)

    # 4 — inserting a foreign (unsigned) row breaks the chain
    def test_chain_break_on_insert(self):
        record(self._probes_all_expected(), path=self.report)
        entries = json.loads(self.report.read_text(encoding="utf-8"))["entries"]
        entries.append({"ts": "2026-01-01T00:00:00+00:00", "probes": [], "ok": True,
                        "prev": "forged", "mac": "0" * 64})
        tampered = self.tmp / "tampered.json"
        tampered.write_text(json.dumps({"entries": entries}), encoding="utf-8")
        ok, why = verify_chain(tampered, key=self.key.read_bytes())
        self.assertFalse(ok)

    # 5 — a key inside the agent's write path is rejected (condition 25-3)
    def test_key_guard(self):
        inside = self.tmp / "inside.key"  # under tmp, not VAULT — simulated by temporarily changing VAULT
        inside.write_bytes(b"k" * 48)
        fake_vault = self.tmp / "vault" / "AI-Agent" / "schema"
        fake_vault.mkdir(parents=True)
        keyfile = fake_vault / "hmac.key"
        keyfile.write_bytes(b"k" * 48)
        orig = isolation.VAULT
        isolation.VAULT = fake_vault
        try:
            with self.assertRaises(IsolationViolation):
                load_key(keyfile)
        finally:
            isolation.VAULT = orig

    # 6 — an escape recorded in the latest report returns rc2 (blocking)
    def test_escape_verdict_fails(self):
        bad = [p for p in self._probes_all_expected() if p["id"] != "ISO-P1-TS-net"]
        bad.append({"id": "ISO-P1-TS-net", "verdict": "allowed", "detail": "fetch succeeded live!"})
        record(bad, path=self.report)
        rc, why = check_isolation(self.report)
        self.assertEqual(rc, 2)
        self.assertIn("escape", why)

    # 7 — staleness: 10 days rc1, 20 days rc2 (a real periodic check)
    def test_stale_detection(self):
        record(self._probes_all_expected(), path=self.report)
        entries = json.loads(self.report.read_text(encoding="utf-8"))["entries"]
        now = datetime.now(timezone.utc)
        for age, want_rc in ((timedelta(days=10), 1), (timedelta(days=20), 2)):
            old = json.loads(json.dumps(entries))
            old_ts = (now - age).isoformat()
            old[0]["ts"] = old_ts
            # re-sign with the test key to measure staleness alone
            import hashlib, hmac as _h
            from isolation import canonical
            key = self.key.read_bytes()
            mac = _h.new(key, canonical({"ts": old_ts, "probes": old[0]["probes"], "prev": old[0]["prev"]}),
                         hashlib.sha256).hexdigest()
            old[0]["mac"] = mac
            stale = self.tmp / f"stale-{want_rc}.json"
            stale.write_text(json.dumps({"entries": old}), encoding="utf-8")
            rc, why = check_isolation(stale, now=now)
            self.assertEqual(rc, want_rc, why)

    # 8 — a missing report is rc1 (no block on a clean machine) and corrupt json is rc2
    def test_missing_and_corrupt(self):
        rc, why = check_isolation(self.tmp / "missing.json")
        self.assertEqual(rc, 1, why)
        corrupt = self.tmp / "corrupt.json"
        corrupt.write_text("not json at all", encoding="utf-8")
        rc, why = check_isolation(corrupt)
        self.assertEqual(rc, 2, why)


class KeyStorageTests(unittest.TestCase):
    """T-02d (U-25): key creation is atomic and 0600, raw 32 B keys survive, and the release key lives in the state dir."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="iso-key-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ensure_key_is_hex_0600_and_stable(self):
        p = self.tmp / "sub" / "k.key"
        k1 = ensure_key(p)
        self.assertEqual(len(k1), 64)
        int(k1.decode("ascii"), 16)
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.assertEqual(ensure_key(p), k1)
        self.assertEqual(load_key(p), k1)

    def test_ensure_key_never_overwrites(self):
        p = self.tmp / "k.key"
        p.write_bytes(b"x" * 40)
        self.assertEqual(ensure_key(p), b"x" * 40)

    def test_lost_race_uses_winner_key(self):
        p = self.tmp / "k.key"
        real_open = isolation.os.open

        def racing_open(path, flags, mode=0o777):
            Path(path).write_bytes(b"w" * 40)
            return real_open(path, flags, mode)   # now O_EXCL fails: FileExistsError

        isolation.os.open = racing_open
        try:
            self.assertEqual(ensure_key(p), b"w" * 40)
        finally:
            isolation.os.open = real_open

    def test_raw_32_byte_key_not_stripped(self):
        p = self.tmp / "raw.key"
        raw = b" " + bytes(range(1, 31)) + b"\n"          # whitespace at both ends, exactly 32 bytes
        self.assertEqual(len(raw), 32)
        p.write_bytes(raw)
        self.assertEqual(load_key(p), raw)

    def test_text_key_is_stripped(self):
        p = self.tmp / "t.key"
        p.write_bytes(b"a" * 48 + b"\n")
        self.assertEqual(load_key(p), b"a" * 48)

    def test_default_key_path_by_mode(self):
        vault = self.tmp / "v"
        (vault / "AI-Agent" / "config").mkdir(parents=True)
        orig_vault = isolation.VAULT
        isolation.VAULT = vault
        env = dict(isolation.os.environ)
        try:
            self.assertEqual(isolation.default_key_path(), isolation.LEGACY_KEY_PATH)          # no profile = vault
            (vault / "AI-Agent" / "config" / "release_profile.yaml").write_text("mode: vault\n", encoding="utf-8")
            self.assertEqual(isolation.default_key_path(), isolation.LEGACY_KEY_PATH)
            (vault / "AI-Agent" / "config" / "release_profile.yaml").write_text("mode: release\n", encoding="utf-8")
            isolation.os.environ["XDG_STATE_HOME"] = str(self.tmp / "xdg")
            self.assertEqual(isolation.default_key_path(), self.tmp / "xdg" / "stratum" / "isolation-hmac.key")
            del isolation.os.environ["XDG_STATE_HOME"]
            self.assertEqual(isolation.default_key_path(), Path.home() / ".local" / "state" / "stratum" / "isolation-hmac.key")
        finally:
            isolation.VAULT = orig_vault
            isolation.os.environ.clear()
            isolation.os.environ.update(env)

    def test_existing_vault_key_is_untouched_by_mode_logic(self):
        if isolation._release_mode():
            self.assertEqual(isolation.KEY_PATH, isolation.default_key_path())   # a release keeps its key in the per-user state dir
        else:
            self.assertEqual(isolation.KEY_PATH, isolation.LEGACY_KEY_PATH)   # the mother vault is in vault mode



if __name__ == "__main__":
    unittest.main()
