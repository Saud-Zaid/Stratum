# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""contract-tests.py — a behavioural conformance gate for contracts B/D (N2, CR3-W2).
Behavioural tests on the live contracts, not the hash alone:
- contract B: its fields match the live SQLite ledger schema (consumer-driven — N3).
- contract D: build a skill record from a live skill (vault-writer) and check its fields.
- the contract's canonical signature is correct.
Usage: AI-Agent/vault-python AI-Agent/schema/contract-tests.py"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2]
CONTRACTS = VAULT / "AI-Agent" / "contracts"
LEDGER = VAULT / "AI-Agent" / "state" / "decision-ledger.sqlite3"
SKILLS = VAULT / "AI-Agent" / "skills"


def sha256_canonical(obj: dict) -> str:
    body = {k: v for k, v in obj.items() if k != "content_hash"}
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def test_contract_b_matches_live_ledger_schema():
    data = json.loads((CONTRACTS / "decision-log-v1.0.0.json").read_text(encoding="utf-8"))
    conn = sqlite3.connect(LEDGER)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(decisions)").fetchall()]
    conn.close()
    assert cols == data["fields"], f"contract B drifts from the live schema: {cols} != {data['fields']}"


def test_contract_d_builds_from_live_skill():
    data = json.loads((CONTRACTS / "skill-record-v1.0.0.json").read_text(encoding="utf-8"))
    skill_md = SKILLS / "vault-writer" / "SKILL.md"
    assert skill_md.exists(), "the vault-writer skill is absent — the contract has no live source"
    h = hashlib.sha256(skill_md.read_bytes()).hexdigest()
    record = {"id": "vault-writer", "name": "vault-writer", "path": str(skill_md),
              "sha256": h, "status": "active", "created": "2026-09-18", "review_by": "2026-11-18"}
    for f in data["fields"]:
        assert f in record, f"contract D lacks the field {f} in the live record"


def test_contracts_signed_canonical():
    for name in ("decision-log-v1.0.0.json", "skill-record-v1.0.0.json"):
        data = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
        assert data.get("content_hash") == sha256_canonical(data), f"{name} hash mismatch"


def test_contract_b_rows_hash_conform():
    """Extended B conformance (C3-b): every live row in the ledger has its hash recomputed with the declared contract
    (sha256/canonical_json_no_hash_field) and compared with the stored one — a behavioural gate on live data."""
    data = json.loads((CONTRACTS / "decision-log-v1.0.0.json").read_text(encoding="utf-8"))
    sys.path.insert(0, str(VAULT / "AI-Agent" / "schema"))
    import decision_ledger as dl
    ok, msg = dl.verify_ledger()
    assert ok, f"ledger chain verify failed: {msg}"
    rows = dl.entries()
    assert rows, "ledger is empty - contract B has no live rows to verify"
    for r in rows:
        recomputed = dl._row_hash(r["ts"], r["session"], r["kind"], r["title"], r["body"],
                                  r["tokens_billed"], r["status"])
        assert recomputed == r["content_hash"], \
            f"row {r['id']} ({r['kind']}) hash mismatch vs contract {data['hash_algo']}/{data['hash_mode']}"


def test_contract_d_consumer_from_ledger():
    """Contract D consumer (C3-b): skill-record evidence lives in the ledger with kind="skill_record",
    and the live record is built from a live skill and matches the contract's fields — the consumer reads the ledger, not the mediator."""
    data = json.loads((CONTRACTS / "skill-record-v1.0.0.json").read_text(encoding="utf-8"))
    sys.path.insert(0, str(VAULT / "AI-Agent" / "schema"))
    import decision_ledger as dl
    sr = [r for r in dl.entries() if r["kind"] == "skill_record"]
    assert sr, "no skill_record rows in ledger - contract D has no consumer evidence"
    for r in sr:
        rec = json.loads(r["body"])
        for f in data["fields"]:
            assert f in rec, f"skill_record row {r['id']} lacks contract-D field {f}"
    skill_md = SKILLS / "vault-writer" / "SKILL.md"
    assert skill_md.exists(), "the vault-writer skill is absent — the contract has no live source"
    h = hashlib.sha256(skill_md.read_bytes()).hexdigest()
    record = {"id": "vault-writer", "name": "vault-writer", "path": str(skill_md),
              "sha256": h, "status": "active", "created": "2026-09-18", "review_by": "2026-11-18"}
    for f in data["fields"]:
        assert f in record, f"contract D lacks the field {f} in the live record"


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
    print(f"contract-tests: {len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
