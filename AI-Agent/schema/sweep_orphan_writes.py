# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""sweep_orphan_writes.py — orphan sweep (M4′, AD06 B5).
Flags AI-Agent files outside the sources declared in interface.yaml and the known directories.
rc: 0 clean, 1 warning (an orphan was found), 2 fault."""
from __future__ import annotations
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2]
KNOWN_DIRS = ("schema", "scripts", "tests", "traps", "handoff", "skills", "due", "proposals", "radar-state", "scratch", "state", "gate", "contracts", "fixtures", "config", "protocols", "templates", "release-overlay", "keys")
KNOWN_FILES = ("interface.yaml", "g06_baseline.json", "permanent-layer.md", "requirements.txt", "audit_baseline.json", "handoff.md", "last-runs.md", "operations.md", "reservations.md", "rules.md", "vault-python", "vault-python.ps1", ".gitignore", "c7-golden-set.json", "capabilities.yaml", "g06_baseline.json.sig", "gate_baseline.json")


def find_orphans(vault: Path | None = None) -> list[str]:
    """Return sorted AI-Agent/ relative posix paths outside declared sources."""
    root = (vault or VAULT) / "AI-Agent"
    if not root.is_dir():
        return []
    orphans = []
    for f in sorted(root.rglob("*")):
        if not f.is_file() or "__pycache__" in f.parts or f.name.endswith(".pyc"):
            continue
        rel = f.relative_to(root)
        if rel.parts and rel.parts[0] in KNOWN_DIRS:
            continue
        if rel.as_posix() in KNOWN_FILES:
            continue
        orphans.append(rel.as_posix())
    return orphans


def sweep(vault: Path | None = None) -> int:
    orphans = find_orphans(vault)
    if orphans:
        print("rc=1  sweep: " + str(len(orphans)) + " orphan file(s) outside the declared sources: " + str(orphans))
        return 1
    print("rc=0  sweep: zero orphans — every AI-Agent file belongs to a declared source")
    return 0


if __name__ == "__main__":
    sys.exit(sweep())
