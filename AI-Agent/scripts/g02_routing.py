# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""G02 routing tag (AD06 C6 F3): per-task model routing lives as kind="routing" rows in
the decision ledger (body JSON: task, decision_type, model_proposed, model_approved;
approved=null = pending owner). Read-only: prints, never writes — writes go through the
sanctioned ledger API only (append_decision kind="routing").

Usage:
  g02-routing [--all]
Output: - RT<id> <date> <decision_type> proposed=<p> approved=<a|pending> :: <task>
        final: G02ROUTING <n> routing rows
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "schema"))
import decision_ledger as dl


def main(argv: list) -> None:
    rows = [e for e in dl.entries() if e["kind"] == "routing"]
    if "--all" not in argv:
        rows = rows[-10:]
    for r in rows:
        b = json.loads(r["body"])
        approved = b.get("model_approved") or "pending"
        print(f"- RT{r['id']} {r['ts'][:10]} {b.get('decision_type', '?')} "
              f"proposed={b.get('model_proposed')} approved={approved} :: {b.get('task')}")
    print(f"G02ROUTING {len(rows)} routing rows")


if __name__ == "__main__":
    main(sys.argv[1:])
