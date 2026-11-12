# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""session_analyzer.py — AD07 F1 (FX01) / AD13 M02: the session analyser and a measured contamination guard.

Reads one or more JSONL logs and computes context-window occupancy and the sources of consumption.
Writes the full analytic detail to the rotating log AI-Agent/state/telemetry-latest.json
and prints a single, very clean summary line (< 25 tokens).

Usage:
  session-analyzer <file.jsonl> [<file2 ...>] [--verbose]
Output:
  context: 42k/200k (21% used, 79% free) | tax: ok | telemetry logged
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from _vaultlib import VAULT

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from fx02_session_tax import (
    TELEMETRY_LOG,
    calculate_occupancy,
    format_summary_line,
    read_context_window,
    write_telemetry,
)


def analyze_file(p: Path) -> dict:
    """Collects the sources of consumption from one JSONL log — never writes."""
    phases: dict[str, int] = {}
    steps, tokens, maxstep, reloads = 0, 0, 0, 0
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        ph = r.get("phase", "?")
        t = int(r.get("tokens", 0))
        phases[ph] = phases.get(ph, 0) + t
        steps += 1
        tokens += t
        maxstep = max(maxstep, t)
        if ph == "correct" and t > 0:
            reloads += 1
    phs = ",".join(f"{k}:{v}" for k, v in sorted(phases.items()))
    return {"name": p.name, "tokens": tokens, "steps": steps, "phases": phs,
            "reloads": reloads, "maxstep": maxstep}


def main(argv: list, limits_path: Path = None, telemetry_path: Path = None) -> str:
    verbose = "--verbose" in argv or "--raw" in argv
    files = [Path(a) for a in argv if not a.startswith("--")]
    if not files:
        print(__doc__)
        return ""

    analyzed = []
    total_tokens = 0
    total_steps = 0
    total_reloads = 0
    max_step = 0

    for p in files:
        pp = p if p.is_absolute() else VAULT / p
        if not pp.exists():
            if verbose:
                print(f"FX01 {p} MISSING")
            continue
        a = analyze_file(pp)
        analyzed.append(a)
        total_tokens += a["tokens"]
        total_steps += a["steps"]
        total_reloads += a["reloads"]
        max_step = max(max_step, a["maxstep"])
        if verbose:
            print(f"FX01 {a['name']} tokens={a['tokens']} steps={a['steps']} "
                  f"phases={a['phases']} reloads={a['reloads']} maxstep={a['maxstep']}")

    ctx_cap = read_context_window(limits_path)
    occ = calculate_occupancy(total_tokens, ctx_cap)
    tax_verdict = "OVER" if total_tokens > 1_000_000 else "ok"
    summary = format_summary_line(occ, tax_verdict)

    telemetry_file = telemetry_path or TELEMETRY_LOG
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": "session_analyzer",
        "summary": summary,
        "context": occ,
        "tax": {
            "verdict": tax_verdict,
        },
        "totals": {
            "tokens": total_tokens,
            "steps": total_steps,
            "reloads": total_reloads,
            "maxstep": max_step,
            "files_count": len(analyzed),
        },
        "files": analyzed,
    }
    write_telemetry(payload, telemetry_file)

    print(summary)
    if verbose:
        print(f"final: SESSIONANALYZER files={len(files)}")
    return summary


if __name__ == "__main__":
    main(sys.argv[1:])
