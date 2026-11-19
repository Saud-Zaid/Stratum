#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Skill args retrieval (2026-10-23, AD10 C12/R3, owner approval): the retrieval
consumer of the MCP-style skill argument contracts. Prints a skill's args block
(input/output/consumer) without loading the SKILL.md body -- agents route by
contract, not by reading whole skill files.

Usage:
  vault-python AI-Agent/scripts/skill_args.py <skill-name>      one skill
  vault-python AI-Agent/scripts/skill_args.py --all             every skill, one line each

Consumer: agents (retrieval path). Contract lives in each SKILL.md frontmatter;
this tool never invents values, it only reads them.
"""
import sys
import json
from pathlib import Path

import yaml

VAULT = Path(__file__).resolve().parent.parent.parent
SKILLS = VAULT / "AI-Agent" / "skills"


def load_args(name: str) -> dict | None:
    p = SKILLS / name / "SKILL.md"
    if not p.is_file():
        return None
    text = p.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    try:
        fm = yaml.safe_load(text[3:end])
    except Exception:
        return None
    return (fm or {}).get("args")


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv and argv[0].startswith("--") and argv[0] != "--all":
        print(f"skill_args.py: unknown option {argv[0]}", file=sys.stderr)
        return 2
    if argv and argv[0] == "--all":
        for d in sorted(SKILLS.iterdir()):
            if not d.is_dir():
                continue
            a = load_args(d.name)
            if a is None:
                print(f"{d.name}\t<no args>")
                continue
            print(f"{d.name}\tinput={a.get('input', '')}\toutput={a.get('output', '')}\tconsumer={a.get('consumer', '')}")
        return 0
    if not argv:
        print("usage: skill_args.py <skill-name> | --all", file=sys.stderr)
        return 2
    a = load_args(argv[0])
    if a is None:
        print(json.dumps({"error": f"skill '{argv[0]}' not found or has no args"}))
        return 1
    print(json.dumps(a, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
