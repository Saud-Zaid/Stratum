# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""AD11 C1-04 D2/D3/D6 -- entry map generator (final, validated v3 logic).

Generates a tree map of the vault by walking the filesystem (not git state):
untracked files appear, gitignored paths are excluded -- they are either
rebuildable indexes or secret-bearing (probe evidence: .gitignore hides
data.json which holds connector tokens). Dot-directories are hard-excluded.

Caps (D6): depth 3, max 200 lines, max 8 KB output; directories above 15
files collapse into one line. Output to stdout only -- never written to
disk (Z9: no shared state, no partial writes, no locking needed).

Usage: python entry_map.py [root] [max_depth]
Fallback path (D5): run directly on the vault root when state.py fails.
"""
from __future__ import annotations

import fnmatch
import sys
import time
from pathlib import Path

MAX_DEPTH = 3
MAX_LINES = 200
MAX_BYTES = 8192
COLLAPSE = 15
HARD_EXCLUDE = {".git", ".smart-env", ".obsidian", "node_modules", "__pycache__",
                ".trash", ".stfolder", "pylib"}
ANCHORS = ["01-Projects", "02-Areas", "03-Resources", "04-Archive", "AI-Agent"]


def gitignore_patterns(root: Path) -> list[str]:
    patterns = []
    gi = root / ".gitignore"
    if gi.exists():
        for line in gi.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
    return patterns


def is_ignored(path: Path, root: Path, patterns: list[str]) -> bool:
    rel = path.relative_to(root).as_posix()
    for part in rel.split("/"):
        if part in HARD_EXCLUDE:
            return True
        if part.startswith(".") and part != ".gitignore":
            return True
    for p in patterns:
        if p.endswith("/"):
            if rel.startswith(p) or f"/{p}" in f"/{rel}":
                return True
        elif "*" in p:
            if fnmatch.fnmatch(path.name, p) or fnmatch.fnmatch(rel, p):
                return True
        else:
            if rel == p or rel.startswith(p + "/") or path.name == p:
                return True
    return False


def dir_file_count(d: Path) -> int:
    return sum(1 for x in d.rglob("*") if x.is_file())


def walk(d: Path, root: Path, patterns: list[str], depth: int, out: list[str]) -> None:
    if depth > MAX_DEPTH:
        return
    try:
        entries = sorted(d.iterdir(), key=lambda e: e.name.lower())
    except PermissionError:
        return
    subdirs, files = [], []
    for e in entries:
        if is_ignored(e, root, patterns):
            continue
        (subdirs if e.is_dir() else files).append(e)
    subdirs.sort(key=lambda s: (0 if s.name in ANCHORS else 1))
    indent = "  " * depth
    for f in files:
        out.append(f"{indent}{f.name}")
    for sd in subdirs:
        n = dir_file_count(sd)
        if depth + 1 >= MAX_DEPTH and n > COLLAPSE:
            out.append(f"{indent}{sd.name}/ ({n} files)")
        else:
            out.append(f"{indent}{sd.name}/")
            walk(sd, root, patterns, depth + 1, out)


def main() -> None:
    # D6: caps are architectural decisions (depth 3, 200 lines, 8 KB) -- no CLI
    # override; deepening them requires owner approval recorded in AD11 C1-04.
    import argparse   # stdlib only: this tool is the fallback when state.py or _vaultlib fail, so it imports nothing from the vault
    ap = argparse.ArgumentParser(prog="entry_map", description=__doc__.strip().splitlines()[0],
                                 epilog=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", default=".", help="directory to map (default: current)")
    ap.add_argument("max_depth", nargs="?", help="accepted for compatibility and ignored: the caps are fixed by D6")
    root = Path(ap.parse_args().root).resolve()
    patterns = gitignore_patterns(root)
    out: list[str] = []
    walk(root, root, patterns, 0, out)
    total = sum(1 for x in root.rglob("*") if x.is_file() and not is_ignored(x, root, patterns))
    out.insert(0, f"# Entry Map -- {total} files -- read-only -- {time.strftime('%Y-%m-%d %H:%M')}")
    if len(out) > MAX_LINES - 1:
        out = out[:MAX_LINES - 2] + [f"... truncated at {MAX_LINES} lines (D6 cap)"]
    footer = f"---\nlines={len(out)} files={total} caps: depth={MAX_DEPTH} lines<={MAX_LINES}"
    body = "\n".join(out)
    # byte cap: preserve footer, trim body from the end (D6 fix: 8215 > 8192)
    while len((body + "\n" + footer).encode("utf-8")) > MAX_BYTES and len(body.splitlines()) > 10:
        body = "\n".join(body.splitlines()[:-1])
    sys.stdout.write(body + "\n" + footer + "\n")


if __name__ == "__main__":
    main()
