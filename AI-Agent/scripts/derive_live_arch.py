# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Live architecture document derivation and drift check (AD10 C10/R1).
--check: light drift check — verifies key structural figures in the live doc
         (03-Resources/Live-Agent-Architecture.md) against the authoritative
         Measured: header in tool-matrix-C4.md (single source of truth).
--derive: full regeneration of the derived figures from the matrix header.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import ast

from _vaultlib import VAULT, load_profile, locale_value, read

LIVE_DOC = VAULT / (load_profile(VAULT)["paths"]["live_doc"] or "03-Resources/Live-Agent-Architecture.md")   # profile paths.live_doc
TOOL_MATRIX = VAULT / "AI-Agent" / "state" / "ad10" / "tool-matrix-C4.md"

_SCRIPT_WORD = "(" + (re.escape(locale_value("SCRIPT_WORD")) + "|" if locale_value("SCRIPT_WORD") else "") + r"scripts?\b)"   # the unit word: English, plus the Arabic one where the locale has it
MEASURED_RE = re.compile(r"scripts=(\d+) · ✅=(\d+) ⚠️=(\d+) ❌=(\d+)")


def ast_measured() -> tuple[int, int, int, int]:
    """(scripts, ok, warn, bad) counted live from AI-Agent/scripts/*.py (tests excluded): ok = parses, bad = syntax
    error, warn = 0. The release has no tool matrix, so the live script tree is the only source (U-37)."""
    files = sorted(p for p in (VAULT / "AI-Agent" / "scripts").glob("*.py") if not p.name.endswith("-tests.py"))
    bad = 0
    for p in files:
        try:
            ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, ValueError):
            bad += 1
    return len(files), len(files) - bad, 0, bad


def measured() -> tuple[int, int, int, int]:
    """(scripts, ok, warn, bad) from the C4 matrix Measured: header line; without a matrix file, counted live (ast_measured)."""
    if not TOOL_MATRIX.exists():
        return ast_measured()
    text = read(TOOL_MATRIX)
    m = MEASURED_RE.search(text)
    if not m:
        raise SystemExit(f"BLOCKED livedoc matrix Measured: header missing in {TOOL_MATRIX}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))


def doc_figures(text: str) -> dict:
    """Extract key structural figures declared in the live doc."""
    out = {}
    m = re.search(r"(\d+)\s*" + _SCRIPT_WORD, text)
    if m:
        out["scripts"] = int(m.group(1))
    m = re.search(r"(\d+)\s*✅", text)
    if m:
        out["ok"] = int(m.group(1))
    m = re.search(r"(\d+)\s*⚠️", text)
    if m:
        out["warn"] = int(m.group(1))
    m = re.search(r"(\d+)\s*❌", text)
    if m:
        out["bad"] = int(m.group(1))
    return out


def check() -> int:
    """Return 0 if the live doc matches the authoritative measured baseline."""
    if not LIVE_DOC.exists():
        print(f"BLOCKED livedoc missing {rel(LIVE_DOC)}")
        return 1
    text = read(LIVE_DOC)
    doc = doc_figures(text)
    scripts, ok, warn, bad = measured()
    reality = {"scripts": scripts, "ok": ok, "warn": warn, "bad": bad}
    issues = []
    for key, real in reality.items():
        if key in doc and doc[key] != real:
            issues.append(f"{key}: doc={doc[key]} reality={real}")
    if issues:
        for i in issues:
            print(f"BLOCKED livedoc drift {i}")
        return 1
    print("GATE CLEAR livedoc")
    return 0


def derive() -> None:
    """Regenerate the derived figures block in the live doc."""
    scripts, ok, warn, bad = measured()
    text = read(LIVE_DOC)
    text = re.sub(r"\d+(\s*)" + _SCRIPT_WORD, lambda m: f"{scripts}{m.group(1)}{m.group(2)}", text, count=1)
    text = re.sub(r"\d+\s*✅", f"{ok} ✅", text, count=1)
    text = re.sub(r"\d+\s*⚠️", f"{warn} ⚠️", text, count=1)
    text = re.sub(r"\d+\s*❌", f"{bad} ❌", text, count=1)
    LIVE_DOC.write_text(text, encoding="utf-8")
    print(f"DERIVED livedoc scripts={scripts} ok={ok} warn={warn} bad={bad}")


def rel(path: Path) -> str:
    return str(path.relative_to(VAULT))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    if mode == "--derive":
        derive()
    else:
        sys.exit(check())
