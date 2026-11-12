# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""decision_ledger.py — the billed decision ledger + the session injection log (AD06 B3, conditions 7 and 11 CF2).

One v1.0.0 unit serves insertion and checking together (the norm_v1 pattern — condition 4):
- SQLite ledger in AI-Agent/state/decision-ledger.sqlite3: a table of billed decisions and an opening entry
  static_childhood (condition 11: it appears in the ledger, the injection log and g06).
- A JSONL session injection log in AI-Agent/state/injection-log.jsonl wired to the g06 check in pre-commit (condition 7).
- enforce_injection(): enforcement at the consumption point — a threshold in tokens, not bytes (condition 9), with the cap on
  the total loaded in the session (condition 17). The frozen simulation: tests/fixtures/injection_fixture.py.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

LEDGER_VERSION = "1.0.0"
VAULT = Path(__file__).resolve().parents[2]
LEDGER_PATH = VAULT / "AI-Agent" / "state" / "decision-ledger.sqlite3"
INJECTION_LOG = VAULT / "AI-Agent" / "state" / "injection-log.jsonl"
STATIC_CHILDHOOD_KIND = "static_childhood"
DEFAULT_CAP = 1300
SCHEMA_USER_VERSION = 1      # PRAGMA user_version: 0 = created before versioning, 1 = current (U-50)


class LedgerVersionError(RuntimeError):
    """The database was written by a newer schema than this code understands."""

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS decisions ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " ts TEXT NOT NULL,"
    " session TEXT NOT NULL,"
    " kind TEXT NOT NULL,"
    " title TEXT NOT NULL,"
    " body TEXT NOT NULL,"
    " tokens_billed INTEGER NOT NULL,"
    " status TEXT NOT NULL DEFAULT 'active',"
    " content_hash TEXT NOT NULL)"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def tokens_of(text: str) -> int:
    """First-party measurement in tokens, not bytes (condition 9): tiktoken o200k_base, estimated at 4 characters/token when it is absent."""
    try:
        import tiktoken
        return len(tiktoken.get_encoding("o200k_base").encode(text))
    except Exception:
        return max(1, len(text) // 4)


def _row_hash(ts: str, session: str, kind: str, title: str, body: str, tokens: int, status: str) -> str:
    blob = json.dumps([ts, session, kind, title, body, tokens, status],
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _connect(db: Path = LEDGER_PATH) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    uv = conn.execute("PRAGMA user_version").fetchone()[0]
    if uv > SCHEMA_USER_VERSION:
        conn.close()
        raise LedgerVersionError(f"{db.name}: user_version {uv} is newer than supported {SCHEMA_USER_VERSION}; upgrade the tools")
    return conn


def open_ledger(db: Path = LEDGER_PATH) -> None:
    """Builds the schema and records the ledger version in meta — no path names repeated outside the unit."""
    conn = _connect(db)
    conn.execute(_SCHEMA)
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('ledger_version', ?)", (LEDGER_VERSION,))
    if conn.execute("PRAGMA user_version").fetchone()[0] == 0:
        conn.execute(f"PRAGMA user_version = {SCHEMA_USER_VERSION}")     # 0 -> 1 on first open; never lowered
    conn.commit()
    conn.close()


def append_decision(title: str, body: str, session: str, kind: str = "decision",
                    tokens_billed: int | None = None, status: str = "active",
                    ts: str | None = None, db: Path = LEDGER_PATH) -> int:
    """Adds a billed decision and returns the ledger id; the per-row hash and the total hash are updated together."""
    open_ledger(db)
    ts = ts or _now()
    tokens = int(tokens_billed) if tokens_billed is not None else tokens_of(f"{title} {body}")
    rowh = _row_hash(ts, session, kind, title, body, tokens, status)
    conn = _connect(db)
    cur = conn.execute(
        "INSERT INTO decisions (ts, session, kind, title, body, tokens_billed, status, content_hash)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ts, session, kind, title, body, tokens, status, rowh))
    _refresh_ledger_hash(conn)
    conn.commit()
    did = cur.lastrowid
    conn.close()
    return did


def _refresh_ledger_hash(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT content_hash FROM decisions ORDER BY id").fetchall()
    blob = json.dumps([r["content_hash"] for r in rows], separators=(",", ":")).encode("utf-8")
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('ledger_hash', ?)",
                 (hashlib.sha256(blob).hexdigest(),))


def tombstone(target_id: int, reason: str, session: str, db: Path = LEDGER_PATH) -> int:
    """Q-B17 (a tombstone is mandatory — declared decision 2026-11-02): real deletion from the ledger is forbidden.
    Writes a tombstone row (kind='tombstone') pointing at the original id with the reason and the session —
    the original row stays as it is (fully append-only) and the hash chain is kept through append_decision.
    Returns the tombstone row id. The only allowed way to take a decision out of circulation."""
    body = json.dumps({"tombstoned_id": int(target_id), "reason": reason},
                      ensure_ascii=False, separators=(",", ":"))
    return append_decision(f"tombstone: row {target_id} marked as a tombstone", body,
                           session=session, kind="tombstone", status="active", db=db)


def active_entries(db: Path = LEDGER_PATH) -> list[dict]:
    """Q-B17: the active rows — excludes any row that a tombstone now points at.
    The default reader for reports; entries() stays complete for historical review."""
    all_rows = entries(db)
    dead_ids = set()
    for r in all_rows:
        if r.get("kind") == "tombstone":
            try:
                b = json.loads(r["body"])
                if isinstance(b, dict) and "tombstoned_id" in b:
                    dead_ids.add(int(b["tombstoned_id"]))
            except Exception:
                continue
    return [r for r in all_rows if r["id"] not in dead_ids]


def entries(db: Path = LEDGER_PATH) -> list[dict]:
    if not db.exists():
        return []
    conn = _connect(db)
    rows = conn.execute("SELECT * FROM decisions ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_decisions(kinds: tuple[str, ...] = ("decision",), db: Path = LEDGER_PATH) -> int:
    """A recorded batch that can be counted (B3 acceptance): the number of standard decisions, not the opening rows."""
    if not db.exists():
        return 0
    conn = _connect(db)
    q = ",".join("?" for _ in kinds)
    n = conn.execute(f"SELECT COUNT(*) AS n FROM decisions WHERE kind IN ({q})", kinds).fetchone()["n"]
    conn.close()
    return int(n)


def verify_ledger(db: Path = LEDGER_PATH) -> tuple[bool, str]:
    """Returns (intact, message): the total hash in meta matches a recomputation from the rows."""
    if not db.exists():
        return False, "ledger: ledger database missing"
    conn = _connect(db)
    try:
        meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta").fetchall()}
        rows = conn.execute("SELECT content_hash FROM decisions ORDER BY id").fetchall()
        blob = json.dumps([r["content_hash"] for r in rows], separators=(",", ":")).encode("utf-8")
        want = hashlib.sha256(blob).hexdigest()
        if meta.get("ledger_version") != LEDGER_VERSION:
            return False, f"ledger: [LEDGER-ERR-002] ledger version {meta.get('ledger_version')!r} does not match the unit {LEDGER_VERSION}"
        if meta.get("ledger_hash") != want:
            return False, ("ledger: [LEDGER-ERR-001] hash mismatch — a direct sqlite3 insert or any non-mediated write "
                           "broke the signature chain; recomputing through append_decision() is mandatory")
        return True, f"ledger: signed and intact v{LEDGER_VERSION} ({len(rows)} rows)"
    finally:
        conn.close()


def append_injection_log(session: str, kind: str, tokens: int, method: str,
                         ts: str | None = None, **extra) -> Path:
    """One JSONL line per injection: the injection log is wired to the g06 check in pre-commit (condition 7).
    C3 D3 (approved C4 critique): method declares where the value came from — "tiktoken-first-party"
    (measured first-hand) or "declared". The cap is only as trustworthy as its writer.
    C4 D2 (C3 closing critique): method is mandatory with no default — the declared-only era
    must not return through a caller forgetting; every caller states the value's source explicitly.
    C4 D3: automatic rotation when the line cap declared in the baseline is reached."""
    entry = {"ts": ts or _now(), "session": session, "kind": kind, "tokens": int(tokens),
             "method": method}
    entry.update(extra)
    INJECTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    rotate_injection_log()
    with INJECTION_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return INJECTION_LOG


def read_injection_log(path: Path = INJECTION_LOG) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def rotate_injection_log(path: Path = INJECTION_LOG, cap: int | None = None) -> Path | None:
    """C4 D3 (deferred decision #19, C4 critique): injection-log rotation — when the log reaches the line cap
    declared in the baseline (metrics.s16_max_log_lines), it moves to a dated archive
    (injection-log.YYYY-MM-DD.jsonl) and a new log starts. No magic: the cap is declared in the
    baseline, the move never touches the lines, and the archive keeps the full history."""
    if cap is None:
        try:
            _b = json.loads((VAULT / "AI-Agent" / "g06_baseline.json").read_text(encoding="utf-8"))
            cap = int(_b.get("metrics", {}).get("s16_max_log_lines") or 200)
        except Exception:
            cap = 200
    if not path.exists():
        return None
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(lines) < cap:
        return None
    archive = path.with_name(f"injection-log.{_now()[:10]}.jsonl")
    path.rename(archive)
    return archive


def enforce_injection(entries_in: list[dict], cap_tokens: int = DEFAULT_CAP) -> list[dict]:
    """Enforcement at the consumption point (conditions 7 and 17): any item above the cap is a risk, and a loaded total above it is a risk.
    entries_in: dicts carrying tokens or tokens_billed. Returns [] when everything matches."""
    violations: list[dict] = []
    total = 0
    for i, e in enumerate(entries_in):
        t = int(e.get("tokens", e.get("tokens_billed", 0)))
        total += t
        if t > cap_tokens:
            violations.append({"error": True, "entry_index": i, "kind": e.get("kind"),
                               "tokens": t, "rule": "single-entry-over-cap", "cap": cap_tokens})
    if total > cap_tokens:
        violations.append({"error": True, "entry_index": len(entries_in), "kind": "_session_total",
                           "tokens": total, "rule": "loaded-total-over-cap", "cap": cap_tokens})
    return violations


def self_check() -> bool:
    """The static_childhood opening entry exists in the ledger + the ledger is signed + the first injection-log line is static_childhood."""
    es = entries()
    if not es or es[0]["kind"] != STATIC_CHILDHOOD_KIND:
        return False
    ok, _ = verify_ledger()
    log = read_injection_log()
    return ok and bool(log) and log[0].get("kind") == STATIC_CHILDHOOD_KIND
