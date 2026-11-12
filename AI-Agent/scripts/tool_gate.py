#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""tool_gate.py — Tool Admission Controller & Surgical Read Guard (AD13 M06, W2.1).

Enforces:
1. 200-Line Surgical Read Cap: Blocks full file reads for files > 200 lines to protect
   the agent context window. Automatically supplies an actionable outline breakdown
   and pre-formatted section.py commands.
2. Tool Admission Gate: Validates tool invocation safety, prevents path traversal outside
   the vault, and verifies tool registry status.
3. System Override: Allows internal architectural gates and ratchet audits to bypass the
   cap using `--system-override` without causing agent lockouts.

Usage:
  tool_gate check-read <file_path> [--system-override] [--json]
  tool_gate admit <tool_name> [tool_args...] [--json]
  tool_gate stats [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from _vaultlib import VAULT, load_profile, normalize_ar, read, sections, standard_parser

READ_CAP_LINES = 200


def read_cap_bytes() -> int:
    """Byte ceiling from the profile (limits.read_cap_bytes); 0 = no byte ceiling (mother vault)."""
    try:
        return int(load_profile()["limits"]["read_cap_bytes"])
    except ValueError:
        return 0


def _structured_sections(suffix: str, content: str) -> list[dict]:
    """Top-level keys of a .json/.yaml/.yml file, so a rejected read still gets an outline."""
    try:
        if suffix == ".json":
            data = json.loads(content)
        elif suffix in (".yaml", ".yml"):
            import yaml
            data = yaml.safe_load(content)
        else:
            return []
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    return [{"level": "key", "title": str(k), "start_line": 0, "line_count": 0} for k in list(data)[:15]]


def resolve_vault_path(raw_path: str) -> Path:
    p = Path(raw_path)
    if p.is_absolute():
        try:
            rel = p.relative_to(VAULT)
            return VAULT / rel
        except ValueError:
            return p
    return VAULT / raw_path


def check_read_admission(file_path_str: str, system_override: bool = False) -> dict:
    # 1. Path Traversal & Boundary Check First
    try:
        raw = Path(file_path_str)
        if raw.is_absolute():
            target = raw.resolve()
        else:
            target = (VAULT / raw).resolve()
        rel = target.relative_to(VAULT.resolve())
        rel_str = str(rel)
    except (ValueError, Exception):
        return {
            "verdict": "REJECT",
            "admitted": False,
            "path": str(file_path_str),
            "reason": "Security Boundary Violation: File path is outside the vault root.",
            "lines": 0,
            "bytes": 0,
            "cap": READ_CAP_LINES,
            "system_override": system_override,
            "sections": [],
            "suggested_actions": [],
        }

    # 2. Existence check
    if not target.exists() or not target.is_file():
        return {
            "verdict": "ERROR",
            "admitted": False,
            "path": rel_str,
            "reason": f"File not found: {file_path_str}",
            "lines": 0,
            "bytes": 0,
            "cap": READ_CAP_LINES,
            "system_override": system_override,
            "sections": [],
            "suggested_actions": [],
        }

    # 3. Read & Line Count Measurement
    try:
        content = read(target)
    except Exception as e:
        return {
            "verdict": "ERROR",
            "admitted": False,
            "path": rel_str,
            "reason": f"Failed to read file: {e}",
            "lines": 0,
            "bytes": 0,
            "cap": READ_CAP_LINES,
            "system_override": system_override,
            "sections": [],
            "suggested_actions": [],
        }

    lines = content.splitlines()
    line_count = len(lines)
    byte_count = len(content.encode("utf-8"))

    # 4. Check Cap vs System Override
    byte_cap = read_cap_bytes()
    over_bytes = bool(byte_cap) and byte_count > byte_cap
    if (line_count <= READ_CAP_LINES and not over_bytes) or system_override:
        return {
            "verdict": "ADMIT",
            "admitted": True,
            "path": rel_str,
            "reason": "Admitted: within 200-line limit" if line_count <= READ_CAP_LINES else "Admitted: system override active",
            "lines": line_count,
            "bytes": byte_count,
            "cap": READ_CAP_LINES,
            "system_override": system_override,
            "sections": [],
            "suggested_actions": [],
        }

    # 5. Surgical Read Rejection + Outline Extraction
    raw_sections = sections(content) if target.suffix == ".md" else []
    structured = _structured_sections(target.suffix, content)
    sec_breakdown = []
    suggested_cmds = []

    for level, title, line, count in raw_sections:
        clean_title = title.strip()
        sec_breakdown.append({
            "level": f"H{level}",
            "title": clean_title,
            "start_line": line,
            "line_count": count,
        })
        if count <= READ_CAP_LINES:
            suggested_cmds.append(f'AI-Agent/vault-python AI-Agent/scripts/section.py "{rel_str}" "{clean_title}"')

    suggested_cmds.append(f'AI-Agent/vault-python AI-Agent/scripts/outline.py "{rel_str}" --all')

    if line_count > READ_CAP_LINES:
        why = f"File has {line_count} lines (> {READ_CAP_LINES} cap)."
    else:
        why = f"File has {byte_count} bytes (> {byte_cap} byte cap) in {line_count} lines."
    return {
        "verdict": "REJECT",
        "admitted": False,
        "path": rel_str,
        "reason": f"200-Line Surgical Read Ban (AD13 W2.1): {why} Full read forbidden to prevent context bloat.",
        "lines": line_count,
        "bytes": byte_count,
        "cap": READ_CAP_LINES,
        "cap_bytes": byte_cap,
        "system_override": False,
        "sections": (sec_breakdown or structured)[:15],
        "total_sections": len(raw_sections) or len(structured),
        "suggested_actions": suggested_cmds[:5],
    }


def check_tool_admission(tool_name: str, args: list[str]) -> dict:
    stem = Path(tool_name).stem
    # Check if tool is located under AI-Agent/scripts/ or known built-in
    script_path = SCRIPTS_DIR / f"{stem}.py"
    exists = script_path.is_file()

    # Traversal detection in args
    has_traversal = any(".." in a or a.startswith("/etc") or a.startswith("/root") for a in args)

    if has_traversal:
        return {
            "verdict": "REJECT",
            "admitted": False,
            "tool": stem,
            "reason": "Security Boundary Violation: Path traversal or unauthorized system path in tool arguments.",
            "args": args,
        }

    if not exists and not tool_name.startswith(("git", "rg", "python")):
        return {
            "verdict": "WARN_UNKNOWN",
            "admitted": True,
            "tool": stem,
            "reason": f"Tool '{stem}' is not in AI-Agent/scripts/, but execution permitted.",
            "args": args,
        }

    return {
        "verdict": "ADMIT",
        "admitted": True,
        "tool": stem,
        "reason": f"Tool '{stem}' verified and admitted.",
        "args": args,
    }


def get_vault_read_stats() -> dict:
    """Scan vault markdown files and report line count distribution."""
    total_md = 0
    safe_md = 0
    oversized_md = 0
    max_lines = 0
    largest_file = ""

    for p in VAULT.rglob("*.md"):
        if ".git" in p.parts or ".smart-env" in p.parts or ".trash" in p.parts:
            continue
        try:
            cnt = len(read(p).splitlines())
            total_md += 1
            if cnt <= READ_CAP_LINES:
                safe_md += 1
            else:
                oversized_md += 1
                if cnt > max_lines:
                    max_lines = cnt
                    largest_file = str(p.relative_to(VAULT))
        except Exception:
            continue

    return {
        "total_markdown_files": total_md,
        "safe_direct_read_files": safe_md,
        "safe_percentage": round((safe_md / max(total_md, 1)) * 100, 1),
        "oversized_files_requiring_surgical_read": oversized_md,
        "oversized_percentage": round((oversized_md / max(total_md, 1)) * 100, 1),
        "read_cap_lines": READ_CAP_LINES,
        "largest_file": largest_file,
        "largest_file_lines": max_lines,
    }


COMMANDS = ("check-read", "admit", "stats")


def _parsers():
    """argparse contract (U-47): -h exits 0, unknown flags exit 2. `admit` passes everything after the tool name through."""
    ap = standard_parser(__doc__, "tool_gate")
    sub = ap.add_subparsers(dest="command", metavar="{check-read,admit,stats}")
    cr = sub.add_parser("check-read", help="admit or refuse a full read of a file")
    cr.add_argument("path")
    cr.add_argument("--system-override", action="store_true")
    cr.add_argument("--json", action="store_true")
    ad = sub.add_parser("admit", help="check a tool invocation")
    ad.add_argument("tool_name")
    ad.add_argument("tool_args", nargs=argparse.REMAINDER)
    ad.add_argument("--json", action="store_true")
    st = sub.add_parser("stats", help="read-discipline statistics of the vault")
    st.add_argument("--json", action="store_true")
    legacy = standard_parser("tool_gate <path>: shorthand for check-read", "tool_gate")
    legacy.add_argument("path")
    legacy.add_argument("--system-override", action="store_true")
    legacy.add_argument("--json", action="store_true")
    return ap, legacy


def main(argv: list[str]) -> None:
    if not argv:
        print(__doc__)
        sys.exit(0)

    ap, legacy = _parsers()
    is_json = "--json" in argv                      # position-independent, as before (`admit <tool> <args> --json`)
    argv = [a for a in argv if a != "--json"]
    if not argv:
        argv = ["--help"] if not is_json else ["stats"]
    if argv[0].startswith("-") or argv[0] in COMMANDS:
        ns = ap.parse_args(argv)
        command = ns.command
    else:
        ns, command = legacy.parse_args(argv), None     # `tool_gate <path>`: the pre-subcommand form
    if command is None and not hasattr(ns, "path"):
        sys.exit(ap.format_usage())

    if command == "check-read":
        target_path = ns.path
        override = ns.system_override
        res = check_read_admission(target_path, system_override=override)

        if is_json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            if res["admitted"]:
                print(f"[ADMIT] {res['path']} ({res['lines']} lines, {res['bytes']}B) — {res['reason']}")
            else:
                print(f"[{res['verdict']}] {res['reason']}")
                print(f"File: {res['path']} | Total Lines: {res['lines']} | Cap: {res['cap']}")
                if res["sections"]:
                    print("\nRecommended Surgical Sections:")
                    for s in res["sections"][:8]:
                        print(f"  - {s['level']} L{s['start_line']} ({s['line_count']} lines): {s['title']}")
                if res["suggested_actions"]:
                    print("\nRun one of the following surgical commands instead:")
                    for cmd in res["suggested_actions"]:
                        print(f"  $ {cmd}")
        sys.exit(0 if res["admitted"] else 1)

    elif command == "admit":
        tool_name = ns.tool_name
        tool_args = ns.tool_args
        res = check_tool_admission(tool_name, tool_args)
        if is_json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print(f"[{res['verdict']}] {res['reason']}")
        sys.exit(0 if res["admitted"] else 1)

    elif command == "stats":
        stats = get_vault_read_stats()
        if is_json:
            print(json.dumps(stats, indent=2))
        else:
            print("=== VAULT READ SURGICAL DISCIPLINE STATS ===")
            print(f"Total Markdown Files:     {stats['total_markdown_files']}")
            print(f"Safe Direct Read (<=200L): {stats['safe_direct_read_files']} ({stats['safe_percentage']}%)")
            print(f"Oversized (>200L Ban):    {stats['oversized_files_requiring_surgical_read']} ({stats['oversized_percentage']}%)")
            print(f"Largest Vault Document:   {stats['largest_file']} ({stats['largest_file_lines']} lines)")
        sys.exit(0)

    else:
        # Default behavior: assume file path for check-read if file exists
        command = ns.path
        if Path(command).exists() or (VAULT / command).exists():
            override = ns.system_override
            res = check_read_admission(command, system_override=override)
            if is_json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                if res["admitted"]:
                    print(f"[ADMIT] {res['path']} ({res['lines']} lines) — within {res['cap']} line cap")
                else:
                    print(f"[{res['verdict']}] {res['reason']}")
            sys.exit(0 if res["admitted"] else 1)
        else:
            sys.exit(f"unknown command or path: {command}. Use check-read, admit, or stats.")


if __name__ == "__main__":
    main(sys.argv[1:])
