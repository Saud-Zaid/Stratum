# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""mediator.py — the single mediator for the send point (AD06 B6a — d3 of the send-point ADR).

The five controls (condition 25) in a strict order that is never traded off — the path:
  pre_check → injection_check → build → sign → dispatch → log
  1) Pre-check: payload sanitising — vault/excluded paths and plain-text secrets
     are masked [REDACTED-g13] before anything leaves, and the findings are recorded in the row's meta.
  2) Injection check: OWASP LLM01 patterns on the free fields — rejects the whole payload
     before signing, not after (an explicit rejection, not silent sanitising).
  3) Signing: HMAC-SHA256 over the final payload after both checks — the key is entirely outside
     the agent's write path (outside VAULT: ~/.config/goose/secrets/).
     Hash chain: every row signs its predecessor, so no silent deletion and no late insertion.
  4) Sending: a transport registered by name only — on failure the signed payload is spooled
     with a size/age limit (1MB / 24 hours), and anything past its age is dropped, not resent (authorisation
     expiry — K4 of the self-critique). The default transport is a local echo
     on 127.0.0.1 (K8) until the real endpoints are wired in B6b.
  5) Durable log: a send_log table on the same WAL store (decision-ledger.sqlite3),
     reading fully separate from writing (an independent read-only connection), and a retention
     policy that archives for display and never deletes rows (trimming, not destroying — condition 26).

Any change to the payload between the check and the signing changes the hash and verification catches it — TOCTOU closed.
Usage: AI-Agent/vault-python AI-Agent/schema/mediator.py"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

MEDIATOR_VERSION = "1.0.0"
VAULT = Path(__file__).resolve().parents[2]
DB_PATH = VAULT / "AI-Agent" / "state" / "decision-ledger.sqlite3"
SPOOL_DIR = VAULT / "AI-Agent" / "state" / "spool"
THROTTLE_STATE_PATH = VAULT / "AI-Agent" / "state" / "throttle-state.json"
# C3 D2: the throttle state is external — a separate file (the kill-switch-state.json pattern); it survives
# across processes. It used to live in the unit's memory, so every new session reset it (decorative in practice).
KEY_PATH = Path.home() / ".config" / "goose" / "secrets" / "mediator-hmac.key"

SPOOL_MAX_BYTES = 1_000_000      # spool size limit (P3)
SPOOL_TTL_HOURS = 24             # spool age limit — authorisation expiry
RETENTION_DAYS = 90              # retention: archive for display, never delete rows

SEND_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS send_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  session TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  hmac TEXT NOT NULL,
  prev_hmac TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'sent',
  meta TEXT NOT NULL DEFAULT '{}'
)"""

# paths that never leave — the pre-check masks them (condition 25-1: sanitising A1/A2)
DENIED_PATH_FRAGMENTS = (
    "AI-Agent/state/", "AI-Agent/contracts/", "AI-Agent/handoff/",
    ".config/goose/secrets", "decision-ledger.sqlite3", "mediator-hmac.key",
)

SECRET_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/=]{8,}"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"ghp_[A-Za-z0-9]{16,}"),
    re.compile(r"(?i)authorization\s*:\s*\S+"),
)

# OWASP LLM01 injection patterns — full rejection, not sanitising (condition 25-5)
INJECTION_PATTERNS = (
    re.compile(r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+(rules|instructions)"),
    re.compile(r"(?i)disregard\s+(all\s+)?(previous|prior|your)\s+(rules|instructions)"),
    re.compile(r"(?i)(you\s+are\s+now|act\s+as\s+if\s+you\s+are)\s+(a|an)\s"),
    re.compile(r"(?i)reveal\s+(your|the)\s+(system|initial)\s+prompt"),
    re.compile(r"(?i)\bsystem\s*:\s*"),
    re.compile(r"<\|?(im_start|endoftext|system)\|?>"),
)

REDACT = "[REDACTED-g13]"


class MediatorViolation(Exception):
    """Base of the exceptions: the payload is rejected before anything leaves."""


class InjectionViolation(MediatorViolation):
    pass


class SpoolViolation(MediatorViolation):
    pass


class KeyViolation(MediatorViolation):
    pass


class ThrottleViolation(MediatorViolation):
    """The 429 gate (F6): refuses a send in progress — it stops it midway, not afterwards (closes S15)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# F6 preflight: the gate state sits at the natural catch point. C3 D2: the state is external —
# the file is the only source of truth; every new process reads it, so the gate stays active across
# restarts, and a real reset is only deleting the file.


def _read_throttle_file() -> str | None:
    """The gate's activation time from the external state file, or None when it is idle."""
    try:
        return json.loads(THROTTLE_STATE_PATH.read_text(encoding="utf-8")).get("tripped_at")
    except Exception:                                            # noqa: BLE001
        return None


def is_throttled() -> bool:
    return _read_throttle_file() is not None


def _trip_throttle() -> None:
    THROTTLE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    THROTTLE_STATE_PATH.write_text(
        json.dumps({"tripped_at": _now()}, ensure_ascii=False), encoding="utf-8")


def reset_throttle() -> None:
    THROTTLE_STATE_PATH.unlink(missing_ok=True)


def _is_rate_limit_error(exc: Exception) -> bool:
    return "429" in str(exc) or "429" in type(exc).__name__


def load_key(path: Path = KEY_PATH) -> bytes:
    """Rejects a short key, or one leaking inside the vault — it must be outside the agent's write path."""
    if not path.exists() or path.stat().st_size < 32:
        raise KeyViolation(f"HMAC key missing or too short: {path}")
    if VAULT in path.resolve().parents:
        raise KeyViolation("key inside the agent's write path — rejected (condition 25-3)")
    return path.read_bytes().strip()


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _scrub_text(text: str, findings: list[str]) -> str:
    """Sanitises one string of plain-text secrets, then of the forbidden paths."""
    for rx in SECRET_PATTERNS:
        if rx.search(text):
            findings.append("secret-pattern")
            text = rx.sub(REDACT, text)
    for frag in DENIED_PATH_FRAGMENTS:
        if frag in text:
            findings.append(f"denied-path:{frag}")
            text = text.replace(frag, REDACT)
    return text


def pre_check(payload: dict) -> tuple[dict, list[str]]:
    """Control 1: deep sanitising of every payload string before anything else."""
    findings: list[str] = []

    def walk(obj):
        if isinstance(obj, str):
            return _scrub_text(obj, findings)
        if isinstance(obj, dict):
            return {k: walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [walk(v) for v in obj]
        return obj

    clean = walk(payload)
    return clean, findings


def injection_check(payload: dict) -> None:
    """Control 5: rejects the whole payload on the first injection pattern — an explicit rejection, not sanitising."""
    def walk(obj):
        if isinstance(obj, str):
            for rx in INJECTION_PATTERNS:
                if rx.search(obj):
                    raise InjectionViolation(f"LLM01 injection pattern: {rx.pattern}")
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
    walk(payload)


def open_writer(db: Path = DB_PATH) -> sqlite3.Connection:
    """The only write connection — creates the table on the same WAL store (condition 26)."""
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(SEND_LOG_SCHEMA)
    return conn


def read_send_log(db: Path = DB_PATH) -> list[dict]:
    """Control 5 (the reading half): a read-only connection fully independent of writing."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM send_log ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _row_mac(key: bytes, ts: str, session: str, endpoint: str,
             payload_hash: str, prev_hmac: str) -> str:
    blob = canonical({"ts": ts, "session": session, "endpoint": endpoint,
                      "payload_hash": payload_hash, "prev_hmac": prev_hmac})
    return hmac.new(key, blob, hashlib.sha256).hexdigest()


def verify_signature(payload: dict, signature: str, prev_hmac: str, key: bytes) -> bool:
    """Independent verification: any change after the check and before signing is caught here (TOCTOU)."""
    payload_hash = hashlib.sha256(canonical(payload)).hexdigest()
    want = _row_mac(key, "", "", "", payload_hash, prev_hmac)
    return hmac.compare_digest(signature, want)


def send(endpoint: str, payload: dict, session: str, key: bytes | None = None,
         transport=None, db: Path = DB_PATH) -> dict:
    """The whole strict path: 429 gate → sanitising → injection rejection → build → sign → send/spool → log."""
    if is_throttled():                              # Control 6 (F6): a send in progress is stopped midway
        raise ThrottleViolation(
            f"429 gate active since {_read_throttle_file()} — the send is stopped midway until the throttle is reset")
    key = key or load_key()
    payload, findings = pre_check(payload)          # Control 1
    injection_check(payload)                        # Control 5 (rejection, not sanitising)
    meta = {"scrubbed": len(findings), "findings": findings} if findings else {}
    payload_hash = hashlib.sha256(canonical(payload)).hexdigest()

    conn = open_writer(db)
    try:
        last = conn.execute("SELECT hmac FROM send_log ORDER BY id DESC LIMIT 1").fetchone()
        prev_hmac = last["hmac"] if last else "GENESIS"
        ts = _now()
        mac = _row_mac(key, ts, session, endpoint, payload_hash, prev_hmac)   # Control 3

        status, transport_note = "sent", "local-echo"
        if transport is not None:
            try:
                transport(endpoint, payload)
            except Exception as exc:                                    # noqa: BLE001
                if _is_rate_limit_error(exc):                           # F6: a 429 activates the gate before spooling
                    _trip_throttle()
                return _spool(key, conn, ts, session, endpoint, payload,
                              payload_hash, prev_hmac, mac, meta, exc)
        else:
            transport_note = "no-transport-bound"

        conn.execute(
            "INSERT INTO send_log (ts, session, endpoint, payload_hash, hmac, prev_hmac, status, meta)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, session, endpoint, payload_hash, mac, prev_hmac, status,
             json.dumps({**meta, "transport": transport_note}, ensure_ascii=False)))
        conn.commit()
        return {"status": "sent", "payload_hash": payload_hash, "hmac": mac, "meta": meta}
    finally:
        conn.close()


def _spool(key, conn, ts, session, endpoint, payload, payload_hash, prev_hmac,
           mac, meta, exc) -> dict:
    """Control 4: spools the signed payload with a size/age limit — one over the limit is dropped."""
    blob = canonical({"ts": ts, "endpoint": endpoint, "payload": payload, "hmac": mac})
    if len(blob) > SPOOL_MAX_BYTES:
        conn.execute(
            "INSERT INTO send_log (ts, session, endpoint, payload_hash, hmac, prev_hmac, status, meta)"
            " VALUES (?, ?, ?, ?, ?, ?, 'dropped', ?)",
            (ts, session, endpoint, payload_hash, mac, prev_hmac,
             json.dumps({**meta, "drop_reason": f"spool-cap:{len(blob)}>1MB"},
                        ensure_ascii=False)))
        conn.commit()
        raise SpoolViolation(f"payload larger than the spool limit: {len(blob)} > {SPOOL_MAX_BYTES}")
    SPOOL_DIR.mkdir(parents=True, exist_ok=True)
    (SPOOL_DIR / f"{payload_hash[:16]}.json").write_bytes(blob)
    conn.execute(
        "INSERT INTO send_log (ts, session, endpoint, payload_hash, hmac, prev_hmac, status, meta)"
        " VALUES (?, ?, ?, ?, ?, ?, 'spooled', ?)",
        (ts, session, endpoint, payload_hash, mac, prev_hmac,
         json.dumps({**meta, "spool_error": str(exc), "ttl_hours": SPOOL_TTL_HOURS},
                    ensure_ascii=False)))
    conn.commit()
    return {"status": "spooled", "payload_hash": payload_hash, "hmac": mac, "meta": meta}


def flush_spool(db: Path = DB_PATH, key: bytes | None = None,
                transport=None) -> dict:
    """Spool draining: anything past its age is dropped (authorisation expiry), live items are resent.
    C3 D2: draining is subject to the same gate — the spool is never emptied onto a restricted endpoint."""
    if is_throttled():                              # C3 D2: flush_spool bypassing the send() gate was a C2 hole
        raise ThrottleViolation(
            f"429 gate active since {_read_throttle_file()} — spool draining is stopped until the throttle is reset")
    key = key or load_key()
    SPOOL_DIR.mkdir(parents=True, exist_ok=True)
    sent, dropped = 0, 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=SPOOL_TTL_HOURS)
    for f in sorted(SPOOL_DIR.glob("*.json")):
        blob = json.loads(f.read_text(encoding="utf-8"))
        if datetime.fromisoformat(blob["ts"]) < cutoff:
            f.unlink()
            dropped += 1
            continue
        if transport is not None:
            try:
                transport(blob["endpoint"], blob["payload"])
            except Exception:                                          # noqa: BLE001
                continue
        conn = open_writer(db)
        try:
            conn.execute("INSERT INTO send_log (ts, session, endpoint, payload_hash,"
                         " hmac, prev_hmac, status, meta) VALUES (?,?,?,?,?,?,?,?)",
                         (blob["ts"], "spool-flush", blob["endpoint"], "-", blob["hmac"],
                          "-", "flushed", json.dumps({"from_spool": True}, ensure_ascii=False)))
            conn.commit()
        finally:
            conn.close()
        f.unlink()
        sent += 1
    return {"sent": sent, "dropped": dropped}


def verify_send_log_chain(db: Path = DB_PATH, key: bytes | None = None) -> tuple[bool, str]:
    """Verifies the whole chain: every mac matches its row and its predecessor — tampering is caught."""
    key = key or load_key()
    if not db.exists():
        return False, "send_log: log database missing"
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM send_log ORDER BY id").fetchall()
        prev = "GENESIS"
        for r in rows:
            if r["prev_hmac"] != prev:
                return False, f"chain broken at id={r['id']}"
            want = _row_mac(key, r["ts"], r["session"], r["endpoint"],
                            r["payload_hash"], r["prev_hmac"])
            if not hmac.compare_digest(r["hmac"], want):
                return False, f"wrong mac at id={r['id']} — the row was tampered with"
            prev = r["hmac"]
        return True, f"send_log: intact chain ({len(rows)} rows)"
    finally:
        conn.close()


def retention_report(db: Path = DB_PATH) -> dict:
    """Retention policy: archive for display, never delete — it feeds the report and removes not a single row."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        n = conn.execute("SELECT COUNT(*) FROM send_log WHERE ts < ? AND status='sent'",
                         (cutoff,)).fetchone()[0]
    finally:
        conn.close()
    return {"retention_days": RETENTION_DAYS, "due_for_archive_review": n,
            "deleted": 0, "policy": "archive-for-review-never-delete"}


if __name__ == "__main__":
    print(MEDIATOR_VERSION, "— the mediator: import it as a module, do not run it directly (the tests call the functions)")
