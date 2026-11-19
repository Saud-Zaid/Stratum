#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""FX02/FX12 — session tax gate (AD09 C5 / AD13 M02). Prints compact session tax, reads caps from file.

AD13 M02: Measurement Pollution Guard & Rolling Telemetry.
- Reduces stdout to a single compact line (< 25 tokens).
- Calculates residual context occupancy with silent warning when saturation > 80%.
- Redirects comprehensive matrices to AI-Agent/state/telemetry-latest.json.

Usage:
  python3 fx02_session_tax.py print [tokens]
  python3 fx02_session_tax.py check <prompts> <calls> [tokens]
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vaultlib import force_utf8_stdio, session_db_path, standard_parser

VAULT = Path(__file__).resolve().parent.parent.parent
LIMITS = VAULT / "AI-Agent" / "config" / "limits.yaml"
F2_SCRIPT = VAULT / "AI-Agent" / "scripts" / "f2_memory_gen2.py"
GOOSE_DB = session_db_path()
TELEMETRY_LOG = VAULT / "AI-Agent" / "state" / "telemetry-latest.json"


def read_limits():
    """Read caps from file. Minimal YAML subset: 'key: value' lines; no library dependency."""
    caps = {"max_prompts": None, "max_calls": None}
    if not LIMITS.exists():
        return caps, "limits-missing"
    for line in LIMITS.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if ":" not in line:
            continue
        k, v = (x.strip() for x in line.split(":", 1))
        if k in caps and v.isdigit():
            caps[k] = int(v)
    return caps, "from-file"


def read_context_window(path=None) -> int:
    """Read context window cap from limits.yaml, defaults to 200,000."""
    p = path or LIMITS
    if p and p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].strip()
            if ":" not in line:
                continue
            k, v = (x.strip() for x in line.split(":", 1))
            if k == "context_window" and v.isdigit():
                return int(v)
    return 200_000


def calculate_occupancy(used_tokens: int, max_tokens: int = None) -> dict:
    """Calculate Residual Context Occupancy and saturation warning (>80%)."""
    if max_tokens is None:
        max_tokens = read_context_window()
    used = max(0, int(used_tokens))
    total = max(1, int(max_tokens))
    pct_used = round((used / total) * 100, 1)
    pct_free = max(0.0, round(100.0 - pct_used, 1))
    saturation_warning = pct_used > 80.0
    return {
        "used_tokens": used,
        "total_tokens": total,
        "percent_used": pct_used,
        "percent_free": pct_free,
        "saturation_warning": saturation_warning,
    }


def format_k(n: int) -> str:
    """Format token count with 'k' suffix if >= 1000."""
    if n >= 1000:
        val = n / 1000.0
        return f"{int(val)}k" if val.is_integer() else f"{val:.1f}k"
    return str(n)


def format_pct(p: float) -> str:
    """Format percentage value cleanly as integer percentage."""
    return f"{int(round(p))}%"


def format_summary_line(occ: dict, tax_verdict: str = "ok") -> str:
    """Format single-line compact summary (< 25 tokens)."""
    used_str = format_k(occ["used_tokens"])
    total_str = format_k(occ["total_tokens"])
    pct_used_str = format_pct(occ["percent_used"])
    pct_free_str = format_pct(occ["percent_free"])
    warn_tag = " [>80%]" if occ.get("saturation_warning") else ""
    return (f"context: {used_str}/{total_str} ({pct_used_str} used, "
            f"{pct_free_str} free){warn_tag} | tax: {tax_verdict} | telemetry logged")


def write_telemetry(payload: dict, path: Path = None) -> None:
    """Write comprehensive measurement telemetry to fixed rolling log."""
    target = path or TELEMETRY_LOG
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def f2_state():
    """Ask the F2 Gen-2 ledger for one-word verdicts (delegates to the script's own logic)."""
    try:
        import subprocess
        out = subprocess.run(
            [sys.executable, str(F2_SCRIPT), "check"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        line = out.stdout.strip()
        if "STALE" in line:
            return "F2:STALE"
        if "VALID" in line:
            return f"F2:VALID({line.count('VALID')} sources)"
        return "F2:no-ledger"
    except Exception:
        return "F2:unavailable"


def print_tax(used_tokens=None, limits_path=None, telemetry_path=None):
    from datetime import datetime, timezone
    small_tax = 0
    if GOOSE_DB.exists():
        try:
            db = sqlite3.connect(Path(GOOSE_DB).resolve().as_uri() + "?mode=ro", uri=True)
            row = db.execute(
                "SELECT COALESCE(AVG(ul.input_tokens),0), COUNT(*) FROM usage_ledger ul "
                "JOIN sessions s ON s.id=ul.session_id "
                "WHERE ul.session_id IN (SELECT session_id FROM usage_ledger GROUP BY session_id "
                "HAVING COUNT(*) <= 15)").fetchone()
            db.close()
            small_tax = int(row[0]) if row and row[0] else 0
        except Exception:
            small_tax = 0

    actual_used = int(used_tokens) if used_tokens is not None else small_tax
    caps, src = read_limits()
    max_context = read_context_window(limits_path)
    occ = calculate_occupancy(actual_used, max_context)

    f2 = f2_state()
    is_over = False
    if caps.get("max_prompts") and actual_used > caps["max_prompts"]:
        is_over = True
    if "STALE" in f2:
        is_over = True
    tax_verdict = "OVER" if is_over else "ok"

    summary = format_summary_line(occ, tax_verdict)

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": "fx02_session_tax",
        "summary": summary,
        "context": occ,
        "tax": {
            "verdict": tax_verdict,
            "caps": caps,
            "caps_source": src,
            "f2_state": f2,
            "measured_small_session_tax": small_tax,
        },
    }
    write_telemetry(payload, telemetry_path)
    print(summary)
    return summary


def check_live(prompts, calls, tokens=None, telemetry_path=None):
    from datetime import datetime, timezone
    caps, src = read_limits()
    verdicts = []
    if caps.get("max_prompts"):
        verdicts.append("PROMPTS:OVER" if prompts > caps["max_prompts"] else "PROMPTS:ok")
    if caps.get("max_calls"):
        verdicts.append("CALLS:OVER" if calls > caps["max_calls"] else "CALLS:ok")
    verdict_str = ' | '.join(verdicts) or 'no-caps-configured'

    used = int(tokens) if tokens is not None else prompts
    max_context = read_context_window()
    occ = calculate_occupancy(used, max_context)

    summary = f"FX12 | caps {src} | {verdict_str} | telemetry logged"

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": "fx12_session_check",
        "summary": summary,
        "context": occ,
        "checks": {
            "prompts": prompts,
            "calls": calls,
            "verdicts": verdicts,
            "caps": caps,
            "caps_source": src,
        },
    }
    write_telemetry(payload, telemetry_path)
    print(summary)
    return summary


def main(argv=None):
    force_utf8_stdio()
    ap = standard_parser(__doc__, "fx02-session-tax")
    sub = ap.add_subparsers(dest="cmd")
    pr = sub.add_parser("print", help="print the session tax")
    pr.add_argument("tokens", nargs="?", type=int)
    ck = sub.add_parser("check", help="check live usage against the limits")
    ck.add_argument("prompts", type=int)
    ck.add_argument("calls", type=int)
    ck.add_argument("tokens", nargs="?", type=int)
    args = ap.parse_args(argv)
    if args.cmd in (None, "print"):
        print_tax(getattr(args, "tokens", None))
    else:
        check_live(args.prompts, args.calls, args.tokens)


if __name__ == "__main__":
    main()
