# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""G03 session memory (AD08 K3): two layers —
1) anti-repayment session library: records files loaded in this session; a second
   load of the same file is served from the record, never re-read (P-05: AD06 file
   loaded 11x per session; reload 19/30 = 83% of tokens).
2) compact warm-start builder: derived state compressed to a block contract —
   per open project: name + one next step, no history logs (retrievable by query).
   G16 target: handoff + compact < 5,000 tokens (baseline 9,069).

Usage:
  g03-session warmstart        # print compact warm-start state + token cost
  g03-session mem mark FILE    # mark file as loaded in this session
  g03-session mem check FILE   # 1 if already loaded this session, else 0
  g03-session mem stats        # session memory summary
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vaultlib import VAULT, force_utf8_stdio
from g07_tokens import tokens_of

STATE = Path(__file__).resolve().parent / "state.py"
HANDOFF = VAULT / "AI-Agent" / "handoff.md"
MEMLOG = VAULT / "AI-Agent" / "state" / "session-memory.jsonl"


def _state_text() -> str:
    r = subprocess.run([sys.executable, str(STATE), "--days", "1"],
                       capture_output=True, text=True, timeout=60)
    return r.stdout


def _section(text: str, title: str) -> list[str]:
    lines = text.splitlines()
    out, grab = [], False
    for l in lines:
        if l.startswith("## "):
            grab = l.strip().startswith(title)   # state.py titles carry suffixes ("(last 7 days)")
            continue
        if grab:
            out.append(l)
    return [l for l in out if l.strip()]


def warmstart() -> dict:
    t0 = time.perf_counter()
    full = _state_text()
    head = _section(full, "## git")
    active = _section(full, "## active work")
    gate = _section(full, "## gate")
    due = _section(full, "## due")
    club = _section(full, "## club")

    # git: head line + uncommitted count only (details queryable via git)
    head_ln = [l for l in head if l.startswith("head")]
    uncommitted = [l for l in head if l.startswith("uncommitted")]
    git_compact = (head_ln + [f"uncommitted {len(uncommitted)} files (queryable: git status)"] if uncommitted else head_ln)

    # active work: per project keep the project line + ONE next step; drop logs
    projects, cur = [], None
    for l in active:
        if l.startswith("- ") and "\t" in l:   # project lines carry a tab ("path\topen N"); next/log are indented
            cur = {"p": l, "next": []}
            projects.append(cur)
        elif cur is not None and l.strip().startswith("next\t"):   # state indents next lines
            if len(cur["next"]) < 1:
                cur["next"].append(l)
        # log lines dropped — history is queryable, not session surface

    out = ["## git"]
    out += git_compact
    if gate:
        out += ["## gate"] + gate
    if due:
        out += ["## due"] + due
    if club:
        out += ["## club"] + club
    out += ["## active work (compact)"]
    for p in projects:
        out.append(p["p"])
        out += p["next"]
    body = "\n".join(out)
    handoff_tok = tokens_of(HANDOFF.read_text(encoding="utf-8", errors="replace")) if HANDOFF.is_file() else 0
    compact_tok = tokens_of(body)
    full_tok = tokens_of(full)
    return {"full_tokens": full_tok, "compact_tokens": compact_tok,
            "handoff_tokens": handoff_tok,
            "warmstart_tokens": handoff_tok + compact_tok,
            "ms": round((time.perf_counter() - t0) * 1000, 1),
            "body": body}


def _memlog_rows(session: str) -> list[dict]:
    """Rows of this session from the memory log; a missing file or a damaged line is skipped, never fatal."""
    if not MEMLOG.is_file():
        return []
    rows = []
    for line in MEMLOG.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("session") == session:
            rows.append(r)
    return rows


def session_loaded(session: str, path: str) -> bool:
    """True when `path` was marked in `session` (state lives in the log, so it survives across CLI calls)."""
    return any(r.get("file") == path for r in _memlog_rows(session))


def mem_stats(session: str) -> dict:
    rows = _memlog_rows(session)
    files = {r.get("file") for r in rows}
    return {"files": len(files), "loads": len(rows), "reloads": len(rows) - len(files)}


class SessionMem:
    """Layer 1 — anti-repayment: mark/check loaded files for this session."""

    def __init__(self, session: str = "adhoc"):
        self.session = session
        self._loads: dict[str, int] = {}

    def mark(self, path: str, tokens: int = 0) -> None:
        n = sum(1 for r in _memlog_rows(self.session) if r.get("file") == path) + 1   # the log is the cross-process count
        self._loads[path] = n
        MEMLOG.parent.mkdir(parents=True, exist_ok=True)
        with open(MEMLOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"session": self.session, "file": path, "n": n,
                                "tokens": tokens}) + "\n")

    def check(self, path: str) -> bool:
        return path in self._loads

    def reload_savings(self) -> int:
        """Tokens avoided: every load after the first would have re-read the file."""
        return self._saved

    _saved = 0

    def serve(self, path: str, text: str) -> tuple[str, int]:
        """Return file text; if already loaded, serve from record (0 re-read cost)."""
        if self.check(path):
            self._saved += tokens_of(text)  # what WOULD have been paid
            return text, 0
        self.mark(path, tokens_of(text))
        return text, 1


def main(argv: list) -> None:
    force_utf8_stdio()
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return
    if argv and argv[0].startswith("-"):
        print(f"g03-session: unknown option {argv[0]}", file=sys.stderr)
        sys.exit(2)
    if not argv or argv[0] == "warmstart":
        r = warmstart()
        print(r["body"])
        print(f"G03 WARMSTART full={r['full_tokens']} compact={r['compact_tokens']} "
              f"handoff={r['handoff_tokens']} warmstart={r['warmstart_tokens']} ms={r['ms']}")
    elif argv[0] == "mem":
        sub = argv[1] if len(argv) > 1 else "stats"
        session = os.environ.get("STRATUM_SESSION_ID", "adhoc")
        if sub == "mark" and len(argv) > 2:
            SessionMem(session).mark(argv[2])
            print(f"G03 MEM marked {argv[2]}")
        elif sub == "check" and len(argv) > 2:
            print(1 if session_loaded(session, argv[2]) else 0)
        elif sub == "stats":
            st = mem_stats(session)
            print(f"G03 MEM session={session} files={st['files']} loads={st['loads']} reloads={st['reloads']}")
        else:
            print(__doc__)
            sys.exit(2)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
