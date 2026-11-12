# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""stratum-* commands: find the vault, then run the matching AI-Agent/scripts tool exactly as `python <script>` would."""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def find_vault(start: Path | None = None) -> Path:
    """$VAULT when set, else the nearest parent of the working directory that holds AI-Agent/scripts."""
    if os.environ.get("VAULT"):
        return Path(os.environ["VAULT"])
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / "AI-Agent" / "scripts").is_dir():
            return d
    raise SystemExit("stratum: no vault found (run inside a vault, or set VAULT)")


def run_tool(script: str, argv: list[str] | None = None) -> None:
    vault = find_vault()
    path = vault / "AI-Agent" / "scripts" / script
    if not path.is_file():
        raise SystemExit(f"stratum: {path} not found")
    os.environ.setdefault("VAULT", str(vault))
    sys.path.insert(0, str(path.parent))
    sys.argv = [str(path), *(sys.argv[1:] if argv is None else argv)]
    runpy.run_path(str(path), run_name="__main__")


def state() -> None: run_tool("state.py")
def audit() -> None: run_tool("audit.py")
def section() -> None: run_tool("section.py")
def outline() -> None: run_tool("outline.py")
def tool_gate() -> None: run_tool("tool_gate.py")
def restore_ready() -> None: run_tool("restore_ready.py")
def entry_map() -> None: run_tool("entry_map.py")
