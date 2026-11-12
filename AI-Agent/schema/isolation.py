# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""AI-Agent/schema/isolation.py — periodic isolation check at the container boundary.

Declared residue in AD06-C1-10, STRIDE class "E", option (c): a sandbox escape raises
the sending privilege, and the declared control is a periodic isolation check. This file is its structural control.

The declared container boundaries:
  ISO-P1-TS-net   TypeScript container (execute_typescript) refuses the network (fetch)
  ISO-P2-TS-fs    TypeScript container refuses disk access (Deno.readTextFile)
  ISO-P3-TS-env   TypeScript container refuses the environment and external processes (Deno.env)
  ISO-P4-key      HMAC key outside the agent's write path (outside VAULT, condition 25-3)
  ISO-P5-state    spool and send log at their declared paths under AI-Agent/state

The report is append-only in AI-Agent/state/isolation-report.json; every row is HMAC-signed
with a separate key outside the vault (~/.config/goose/secrets/isolation-hmac.key) — the report
itself is a threatened asset, so the condition-26 argument applies: a broken chain fails the check.

check_isolation returns (rc, detail):
  rc 0 — fresh report (<=7 days) and intact
  rc 1 — stale 7-14 days or report missing (a reminder, no block: a clean new machine)
  rc 2 — stale >14 days, a recorded escape or a broken chain (blocking)

CLI:
  record --json '<probes-json>'   record probes executed live
  verify                          verify the report chain
  check                           the full periodic check
"""
from __future__ import annotations

import argparse
import hmac as _hmac
import hashlib as _hashlib
import json
import os
import secrets
import sqlite3  # noqa: F401  (documents reliance on the declared paths only)
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2]
LEGACY_KEY_PATH = Path.home() / ".config" / "goose" / "secrets" / "isolation-hmac.key"


def _release_mode() -> bool:
    """True when AI-Agent/config/release_profile.yaml says `mode: release` (a missing or unreadable file = vault)."""
    try:
        import yaml
        cfg = yaml.safe_load((VAULT / "AI-Agent" / "config" / "release_profile.yaml").read_text(encoding="utf-8")) or {}
        return cfg.get("mode") == "release"
    except Exception:
        return False


def default_key_path() -> Path:
    """Mother vault keeps its existing key; a release build keeps it in the per-user state dir (U-25),
    outside the vault: $XDG_STATE_HOME/stratum, %LOCALAPPDATA%\\stratum on Windows, ~/.local/state/stratum."""
    if not _release_mode():
        return LEGACY_KEY_PATH
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "stratum" / "isolation-hmac.key"


KEY_PATH = default_key_path()
REPORT_PATH = VAULT / "AI-Agent" / "state" / "isolation-report.json"

GENESIS = "genesis"
FRESH_DAYS = 7
STALE_DAYS = 14


class IsolationViolation(Exception):
    """A short key, or one leaking inside the agent's write path."""


# The declared catalogue: what each probe measures and the expected observation for a "pass" verdict.
PROBES = {
    "ISO-P1-TS-net": {"tool": "execute_typescript", "call": "fetch", "expected": "blocked"},
    "ISO-P2-TS-fs": {"tool": "execute_typescript", "call": "Deno.readTextFile", "expected": "blocked"},
    "ISO-P3-TS-env": {"tool": "execute_typescript", "call": "Deno.env", "expected": "blocked"},
    "ISO-P4-key": {"tool": "script", "call": "key_outside_vault", "expected": "pass"},
    "ISO-P5-state": {"tool": "script", "call": "state_paths_declared", "expected": "pass"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_key(path: Path | None = None) -> bytes:
    path = path or KEY_PATH
    """The same control as in the mediator: a key of >=32 bytes outside the agent's write path."""
    if not path.exists() or path.stat().st_size < 32:
        raise IsolationViolation(f"isolation HMAC key missing or too short: {path}")
    if VAULT.resolve() in path.resolve().parents:
        raise IsolationViolation("isolation key inside the agent's write path — rejected (condition 25-3)")
    raw = path.read_bytes()
    # A legacy key is exactly 32 raw bytes: strip() would eat a leading/trailing whitespace byte and change the key.
    return raw if len(raw) == 32 else raw.strip()


def ensure_key(path: Path | None = None) -> bytes:
    path = path or KEY_PATH
    """Generates the key on first record only; outside the vault with 600 permissions."""
    if path.exists():
        return load_key(path)
    if VAULT.resolve() in path.resolve().parents:
        raise IsolationViolation("isolation key inside the agent's write path — rejected (condition 25-3)")
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32).encode("ascii")   # 64 hex chars: strip()-safe, 256 bits of CSPRNG
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)   # never overwrite, born 0600
    except FileExistsError:
        return load_key(path)                                                  # lost a race: use the winner's key
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    return key


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _mac(key: bytes, ts: str, probes: list, prev: str) -> str:
    return _hmac.new(key, canonical({"ts": ts, "probes": probes, "prev": prev}), _hashlib.sha256).hexdigest()


def record(probes: list[dict], path: Path = REPORT_PATH, key_path: Path | None = None) -> dict:
    """Record a probe report: ids from the catalogue only, the verdict is what was observed live.

    ok for an entry = every observation matches the catalogue's expectation; a fail value is not rejected
    here — it is signed and carried in the report for check_isolation to judge (rc 2).
    """
    key = ensure_key(key_path)
    entries = []
    if path.exists():
        entries = json.loads(path.read_text(encoding="utf-8"))["entries"]
    prev = entries[-1]["mac"] if entries else GENESIS
    clean = []
    for p in probes:
        pid = p["id"]
        if pid not in PROBES:
            raise IsolationViolation(f"probe not declared in the catalogue: {pid}")
        clean.append({"id": pid, "verdict": str(p["verdict"]), "detail": str(p.get("detail", ""))[:200]})
    ok = all(c["verdict"] == PROBES[c["id"]]["expected"] for c in clean)
    ts = _now()
    entry = {"ts": ts, "probes": clean, "ok": ok, "prev": prev, "mac": _mac(key, ts, clean, prev)}
    entries.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"entries": entries}, ensure_ascii=False, indent=2), encoding="utf-8")
    return entry


def verify_chain(path: Path = REPORT_PATH, key: bytes | None = None) -> tuple[bool, str]:
    """An HMAC chain over every row: deletion, modification and foreign insertion all break it."""
    if not path.exists():
        return False, "isolation report missing"
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))["entries"]
    except (json.JSONDecodeError, KeyError):
        return False, "isolation report corrupt (unreadable json or no entries)"
    if key is None:
        key = load_key()
    prev = GENESIS
    for i, e in enumerate(entries):
        try:
            want = _mac(key, e["ts"], e["probes"], e["prev"])
        except KeyError:
            return False, f"row {i}: key missing in the entry"
        if not _hmac.compare_digest(e["mac"], want):
            return False, f"row {i}: signature mismatch (tampering or a different key)"
        if e["prev"] != prev:
            return False, f"row {i}: prev does not match the chain (deletion or insertion)"
        prev = e["mac"]
    return True, f"intact chain of {len(entries)} rows"


def check_isolation(path: Path = REPORT_PATH, now: datetime | None = None) -> tuple[int, str]:
    """The blocking periodic check: rc0 fresh, rc1 stale/missing, rc2 escape, break or long staleness."""
    if not path.exists():
        return 1, "iso: isolation report missing — run the probes and record them (rc1, no block on a clean machine)"
    broken, why = verify_chain(path)
    if not broken:
        return 2, f"iso: {why} — the report is compromised and proves nothing"
    entries = json.loads(path.read_text(encoding="utf-8"))["entries"]
    last = entries[-1]
    ref = now or datetime.now(timezone.utc)
    ts = datetime.fromisoformat(last["ts"])
    age_days = (ref - ts).total_seconds() / 86400
    if not last.get("ok", False):
        return 2, "iso: the latest report records an escape (a probe with an unexpected verdict) — blocking"
    if age_days > STALE_DAYS:
        return 2, f"iso: report stale {age_days:.0f} days (> {STALE_DAYS}) — the periodic check is down"
    if age_days > FRESH_DAYS:
        return 1, f"iso: report stale {age_days:.0f} days (> {FRESH_DAYS}) — re-run the probes soon"
    return 0, f"iso: fresh report ({age_days:.1f} days), {len(last['probes'])} probes intact"


# ---- CLI -------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="periodic isolation check at the container boundary")
    ap.add_argument("cmd", choices=["record", "verify", "check"])
    ap.add_argument("--json", help="probes JSON for the record command")
    args = ap.parse_args()
    if args.cmd == "record":
        if not args.json:
            print("record requires --json")
            return 2
        entry = record(json.loads(args.json))
        print(("OK" if entry["ok"] else "ESCAPE") + f"\t{entry['ts']}\t{entry['mac'][:16]}")
        return 0
    if args.cmd == "verify":
        ok, why = verify_chain()
        print(("OK" if ok else "BROKEN") + f"\t{why}")
        return 0 if ok else 2
    rc, why = check_isolation()
    print(f"RC{rc}\t{why}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
