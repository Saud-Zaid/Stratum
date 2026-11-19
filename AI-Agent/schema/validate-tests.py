# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Tests for validate.py (K5: a checker without tests is a third document with no bytes). AD06 B1."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate  # noqa: E402


def _tmpdir():
    return tempfile.TemporaryDirectory()


def test_baseline_signed_ok():
    rc, _ = validate.check_baseline(validate.BASELINE)
    assert rc == 0, rc


def test_baseline_tamper_detected():
    with _tmpdir() as d:
        p = Path(d) / "g06_baseline.json"
        data = {"version": "1.0.0", "metrics": {"x": 1}, "content_hash": "0" * 64}
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        rc, msg = validate.check_baseline(p)
        assert rc == 2 and "hash mismatch" in msg, (rc, msg)


def test_baseline_unsigned_detected():
    with _tmpdir() as d:
        p = Path(d) / "g06_baseline.json"
        p.write_text(json.dumps({"version": "1.0.0", "metrics": {}}), encoding="utf-8")
        rc, msg = validate.check_baseline(p)
        assert rc == 2 and "content_hash" in msg, (rc, msg)


def test_fmea_present_ok():
    if not validate.FMEA.exists() and validate.release_mode():
        return   # the FMEA record belongs to the mother vault
    rc, _ = validate.check_fmea(validate.FMEA)
    assert rc == 0, rc


def test_fmea_partial_mode_detected():
    with _tmpdir() as d:
        p = Path(d) / "fmea.md"
        p.write_text("FM-G06-1 only, without the second mode", encoding="utf-8")
        rc, msg = validate.check_fmea(p)
        assert rc == 2 and "FM-G13-1" in msg, (rc, msg)


def test_switch_absent_info():
    rc, _ = validate.check_switch(Path("/nonexistent/switch.json"))
    assert rc == 0, rc


def test_switch_halt_blocks():
    with _tmpdir() as d:
        p = Path(d) / "switch.json"
        p.write_text(json.dumps({"status": "HALT"}), encoding="utf-8")
        rc, msg = validate.check_switch(p)
        assert rc == 2 and "HALT" in msg, (rc, msg)


def test_switch_run_ok():
    with _tmpdir() as d:
        p = Path(d) / "switch.json"
        p.write_text(json.dumps({"status": "RUN"}), encoding="utf-8")
        rc, _ = validate.check_switch(p)
        assert rc == 0, rc


def test_contracts_absent_n3_gate():
    rc, _ = validate.check_contracts(Path("/nonexistent/contracts"))
    assert rc == 0, rc


def test_contracts_tampered_detected():
    with _tmpdir() as d:
        (Path(d)).mkdir(exist_ok=True)
        f = Path(d) / "decision-log-v1.0.0.json"
        f.write_text(json.dumps({"id": "decision-log", "version": "1.0.0", "content_hash": "dead"}), encoding="utf-8")
        rc, msg = validate.check_contracts(Path(d))
        assert rc == 2 and "hash mismatch" in msg, (rc, msg)


def test_norm_passes():
    rc, _ = validate.check_norm()
    assert rc == 0, rc


def test_norm_detects_unit_missing():
    if validate.t1_disabled():
        return   # a release has no T1 recall check, so nothing to detect
    unit = validate.VAULT / "AI-Agent" / "schema" / "norm_v1.py"
    backup = unit.with_suffix(".py.bak")
    unit.rename(backup)
    try:
        rc, msg = validate.check_norm()
        assert rc == 2 and "norm_v1" in msg, (rc, msg)
    finally:
        backup.rename(unit)


def test_norm_detects_fixture_missing():
    if validate.t1_disabled():
        return   # a release has no T1 recall check, so nothing to detect
    fx = validate.VAULT / "AI-Agent" / "tests" / "fixtures" / "t1_fixture.py"
    backup = fx.with_suffix(".py.bak")
    fx.rename(backup)
    try:
        rc, msg = validate.check_norm()
        assert rc == 2 and "fixture" in msg, (rc, msg)
    finally:
        backup.rename(fx)


def test_ledger_passes():
    rc, msg = validate.check_ledger()
    assert rc == 0, (rc, msg)


def test_ledger_detects_db_missing():
    db = validate.VAULT / "AI-Agent" / "state" / "decision-ledger.sqlite3"
    log = validate.VAULT / "AI-Agent" / "state" / "injection-log.jsonl"
    bk_db, bk_log = db.with_suffix(".sqlite3.bak"), log.with_suffix(".jsonl.bak")
    db.rename(bk_db)
    log.rename(bk_log)
    try:
        rc, msg = validate.check_ledger()
        assert rc == 2 and "ledger database missing" in msg, (rc, msg)
    finally:
        bk_db.rename(db)
        bk_log.rename(log)


def test_ledger_detects_log_missing():
    log = validate.VAULT / "AI-Agent" / "state" / "injection-log.jsonl"
    bk_log = log.with_suffix(".jsonl.bak")
    log.rename(bk_log)
    try:
        rc, msg = validate.check_ledger()
        assert rc == 2 and "injection log missing" in msg, (rc, msg)
    finally:
        bk_log.rename(log)


def test_ledger_detects_baseline_mismatch():
    orig_bytes = validate.BASELINE.read_bytes()
    data = json.loads(orig_bytes.decode("utf-8"))
    try:
        data["metrics"]["static_childhood_tokens"] = 999
        validate.BASELINE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rc, msg = validate.check_ledger()
        assert rc == 2 and "baseline" in msg, (rc, msg)
    finally:
        validate.BASELINE.write_bytes(orig_bytes)


def test_pl_passes():
    rc, msg = validate.check_pl()
    assert rc == 0, (rc, msg)


def test_pl_detects_file_missing():
    path = validate.VAULT / "AI-Agent" / "permanent-layer.md"
    backup = path.with_suffix(".md.bak")
    path.rename(backup)
    try:
        rc, msg = validate.check_pl()
        assert rc == 2 and "permanent layer is not built" in msg, (rc, msg)
    finally:
        backup.rename(path)


def test_injection_fixture_passes():
    sys.path.insert(0, str(validate.VAULT / "AI-Agent" / "tests" / "fixtures"))
    import injection_fixture as fx
    res = fx.run_injection()
    assert res["pass"], res



def test_sidedoor_token_detected():
    with _tmpdir() as d:
        p = Path(d) / "config.yaml"
        p.write_text("  github:\n    enabled: true\n    headers:\n      Authorization: Bearer gh" + "p_ABCDEFGHIJKLMNOPQRSTUVWX\n", encoding="utf-8")
        rc, msg = validate.check_sidedoor(p)
        assert rc == 2 and "plain-text token" in msg, (rc, msg)


def test_sidedoor_disabled_ok():
    with _tmpdir() as d:
        p = Path(d) / "config.yaml"
        p.write_text("  github:\n    enabled: false\n", encoding="utf-8")
        rc, _ = validate.check_sidedoor(p)
        assert rc == 0, rc


def test_sidedoor_missing_config_warns():
    rc, msg = validate.check_sidedoor(Path("/nonexistent/config.yaml"))
    assert rc == 1 and "not found" in msg, (rc, msg)

def test_goose_config_prefers_appdata_when_it_exists():
    import os
    with _tmpdir() as d:
        cfg = Path(d) / "Block" / "goose" / "config" / "config.yaml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("x: 1\n", encoding="utf-8")
        old = os.environ.get("APPDATA")
        os.environ["APPDATA"] = d
        try:
            assert validate._goose_config() == cfg
        finally:
            if old is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = old


def test_injection_log_rotation_keeps_static_childhood_first():
    import decision_ledger as DL
    with _tmpdir() as d:
        log = Path(d) / "injection-log.jsonl"
        rows = [{"kind": DL.STATIC_CHILDHOOD_KIND, "tokens": 5}] + [{"kind": "decision", "tokens": i} for i in range(4)]
        log.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        archive = DL.rotate_injection_log(log, cap=3)
        assert archive is not None and archive.is_file()
        assert len([l for l in archive.read_text(encoding="utf-8").splitlines() if l.strip()]) == 5, "archive keeps the full history"
        new = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(new) == 1 and new[0]["kind"] == DL.STATIC_CHILDHOOD_KIND, new


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"validate-tests: {len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
