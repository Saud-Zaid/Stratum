# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""injection_fixture.py — a frozen injection sample (AD06 B3, condition 7 CF2-W1 + condition 11 CF2-W5).

Freezes the injection simulation in the T1 fixture style: a loaded total under the cap returns zero violations, and a payload
that exceeds the permanent-layer cap (1300 tokens) returns a risk at the consumption point. The threshold is in tokens, not
bytes (condition 9). Enforcement source: AI-Agent/schema/decision_ledger.py — one unit that serves insertion
and checking (the norm_v1 pattern, condition 4). It runs in audit.py as the blocking check inj, which fails the commit when enforcement breaks.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

FIXTURE_VERSION = "1.0.0"
CAP_TOKENS = 1300
VAULT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(VAULT / "AI-Agent" / "schema"))
import decision_ledger as dl  # noqa: E402

# a sound loaded total: 1200 + 80 = 1280 <= 1300 — no violations.
UNDER_CAP = ({"kind": "static_childhood", "tokens": 1200},
             {"kind": "decision", "tokens": 80})
# the overflowing payload: the same session + a billed summary of 60 tokens -> 1340 > 1300 (condition 12: the summary is billed too).
OVER_CAP = UNDER_CAP + ({"kind": "summary", "tokens": 60},)


def run_injection():
    under = dl.enforce_injection(UNDER_CAP, CAP_TOKENS)
    over = dl.enforce_injection(OVER_CAP, CAP_TOKENS)
    under_ok = under == []
    over_err = len(over) >= 1 and all(v.get("error") for v in over)
    passed = under_ok and over_err
    blob = json.dumps({"v": FIXTURE_VERSION, "cap": CAP_TOKENS, "u": UNDER_CAP, "o": OVER_CAP},
                      sort_keys=True, ensure_ascii=False).encode("utf-8")
    return {"fixture_version": FIXTURE_VERSION,
            "data_hash": hashlib.sha256(blob).hexdigest()[:16],
            "cap_tokens": CAP_TOKENS,
            "under_cap_violations": len(under),
            "over_cap_violations": len(over),
            "pass": passed}


if __name__ == "__main__":
    r = run_injection()
    print(("PASS" if r["pass"] else "FAIL"), r)
    sys.exit(0 if r["pass"] else 2)
