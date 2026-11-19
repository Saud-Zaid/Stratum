#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""tokmeter (AD13 A1): where the tokens go, from the agent harnesses' own logs.

Reads three sources, read-only: Goose sessions.db, Claude Code transcripts
(~/.claude/projects/*/*.jsonl) and Antigravity transcripts
(~/.gemini/antigravity{,-cli,-ide}/brain/*/.system_generated/logs/transcript_full.jsonl; AD13 D4). Per tool and per shell command it reports calls,
result size and the share of all tool-result bytes; per source it reports the exact
usage the API returned (input, cache read, output). Sizes are characters by default
and o200k tokens with --tokens (an approximation of Claude's tokenizer, which is
not public); the usage totals are exact because they come from the provider.

Usage:
  tokmeter [--source goose|claude|antigravity|all] [--days N] [--tokens] [--top N] [--json PATH]
`all` is Goose plus Claude Code, the baseline of the earlier measurements; Antigravity is asked for by name so its
much larger text does not move those shares. Prints a compact summary; the full breakdown goes to --json (default
AI-Agent/state/tokmeter-latest.json). Exit 0; 2 on a bad argument.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vaultlib import VAULT, force_utf8_stdio, session_db_path, sqlite_ro_uri

READ_CAP = 8000      # chars: a read result past this is a candidate for a window plus an outline
REPEAT_MIN = 200     # chars: smaller identical results are not worth counting
READ_CMDS = {"cat", "sed", "head", "tail", "awk", "less", "more", "nl", "bat"}
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*$")


def classify_command(cmd: str) -> str:
    """Short class of a shell command: its first real word, with wrappers resolved.
    `cd X && cat f` -> cat; `FOO=1 python3 x.py` -> python3; `vault-python .../state.py` -> state.py."""
    if not isinstance(cmd, str):
        return "?"
    s = cmd.strip()
    while True:
        m = re.match(r"^cd\s+(\"[^\"]*\"|'[^']*'|\S+)\s*(&&|;)\s*", s)
        if not m:
            break
        s = s[m.end():]
    words = s.split()
    while words and _ASSIGN.match(words[0]):
        words = words[1:]
    if not words:
        return "?"
    w = os.path.basename(words[0])
    if w in ("vault-python", "python", "python3") and len(words) > 1:
        rest = [x for x in words[1:] if not x.startswith("-")]
        if rest and rest[0].endswith(".py"):
            return os.path.basename(rest[0])
        if w != "vault-python":
            return "python-inline"
    return w


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    out = []
    if isinstance(content, list):
        for p in content:
            if isinstance(p, dict):
                out.append(p.get("text") or "" if p.get("type", "text") == "text" else "")
            elif isinstance(p, str):
                out.append(p)
    return "".join(out)


def iter_goose(db_path: Path, since: float = 0.0):
    """Yield (usage_or_None, tool_event_or_None) per session/tool call from Goose."""
    if not Path(db_path).exists():
        return
    db = sqlite3.connect(sqlite_ro_uri(db_path), uri=True)
    try:
        sess = {}
        for sid, i, o, cr, cw in db.execute(
                "select id, accumulated_input_tokens, accumulated_output_tokens, accumulated_cache_read_tokens,"
                " accumulated_cache_write_tokens from sessions where cast(strftime('%s', created_at) as integer) >= ?",
                (int(since),)):
            sess[sid] = (i or 0, o or 0, cr or 0, cw or 0)
        for sid, (i, o, cr, cw) in sess.items():
            yield {"source": "goose", "session": sid, "input": i, "cache_read": cr, "cache_write": cw,
                   "output": o, "calls": 0}, None
        pending = {}
        for sid, cj in db.execute("select session_id, content_json from messages order by id"):
            if sid not in sess:
                continue
            try:
                parts = json.loads(cj)
            except ValueError:
                continue
            for p in parts if isinstance(parts, list) else []:
                t = p.get("type")
                if t == "toolRequest":
                    v = (p.get("toolCall") or {}).get("value") or {}
                    args = v.get("arguments") or {}
                    name = v.get("name") or "?"
                    pending[p.get("id")] = (name, args.get("command") if isinstance(args, dict) else None,
                                            name + "|" + json.dumps(args, sort_keys=True, ensure_ascii=False))
                elif t == "toolResponse":
                    name, cmd, fp = pending.pop(p.get("id"), ("?", None, None))
                    tr = p.get("toolResult") or {}
                    val = tr.get("value") or {}
                    text = _text_of(val.get("content")) if isinstance(val, dict) else ""
                    err = tr.get("status") == "error" or (isinstance(val, dict) and bool(val.get("isError")))
                    yield None, {"source": "goose", "session": sid, "tool": name, "cmd": cmd, "text": text,
                                 "fp": fp, "err": err}
    finally:
        db.close()


def iter_claude(root: Path, since: float = 0.0):
    """Yield usage and tool events from Claude Code transcripts."""
    root = Path(root)
    files = [(f, Path(f).stem, Path(f).stem) for f in glob.glob(str(root / "*" / "*.jsonl"))]
    # a subagent writes its own transcript, <project>/<session>/subagents/agent-*.jsonl; its usage is in no other file
    for f in glob.glob(str(root / "*" / "*" / "**" / "*.jsonl"), recursive=True):
        parent = Path(f).relative_to(root).parts[1]
        files.append((f, parent, parent + "/" + Path(f).stem))
    for f, usage_sid, sid in sorted(files):
        if os.path.getmtime(f) < since:
            continue
        usage = {"source": "claude", "session": usage_sid, "input": 0, "cache_read": 0, "cache_write": 0,
                 "output": 0, "calls": 0}
        pending = {}
        events = []
        seen_msg = set()
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                m = o.get("message") if isinstance(o.get("message"), dict) else {}
                if o.get("type") == "assistant":
                    u = m.get("usage") or {}
                    mid = m.get("id") or o.get("uuid")
                    if u and mid not in seen_msg:
                        seen_msg.add(mid)
                        usage["input"] += u.get("input_tokens") or 0
                        usage["cache_read"] += u.get("cache_read_input_tokens") or 0
                        usage["cache_write"] += u.get("cache_creation_input_tokens") or 0
                        usage["output"] += u.get("output_tokens") or 0
                        usage["calls"] += 1
                    for p in m.get("content") or []:
                        if isinstance(p, dict) and p.get("type") == "tool_use":
                            inp = p.get("input") or {}
                            pending[p.get("id")] = (p.get("name") or "?", inp.get("command") if isinstance(inp, dict) else None,
                                                    (p.get("name") or "?") + "|" + json.dumps(inp, sort_keys=True, ensure_ascii=False))
                elif o.get("type") == "user" and isinstance(m.get("content"), list):
                    for p in m["content"]:
                        if isinstance(p, dict) and p.get("type") == "tool_result":
                            name, cmd, fp = pending.pop(p.get("tool_use_id"), ("?", None, None))
                            events.append({"source": "claude", "session": sid, "tool": name, "cmd": cmd,
                                           "text": _text_of(p.get("content")), "fp": fp,
                                           "err": bool(p.get("is_error"))})
        yield usage, None
        for e in events:
            yield None, e


SHELL_TOOLS = ("shell", "Bash", "run_command")      # Goose, Claude Code, Antigravity
READ_TOOLS = ("Read", "read_file", "view_file")


def iter_antigravity(root: Path, since: float = 0.0):
    """Yield usage and tool events from Antigravity conversation transcripts.

    A PLANNER_RESPONSE row carries the usage and its tool_calls; the GENERIC rows after it are the results, in call
    order, until the next PLANNER_RESPONSE. A result row with no pending call (a plain step) is not a tool result."""
    for f in sorted(glob.glob(str(Path(root) / "*" / ".system_generated" / "logs" / "transcript_full.jsonl"))):
        if os.path.getmtime(f) < since:
            continue
        sid = Path(f).relative_to(root).parts[0]
        usage = {"source": "antigravity", "session": sid, "input": 0, "cache_read": 0, "cache_write": 0,
                 "output": 0, "calls": 0}
        pending, events = [], []
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                kind = o.get("type")
                if kind == "PLANNER_RESPONSE":
                    usage["input"] += o.get("input_tokens") or 0
                    usage["cache_read"] += o.get("cache_read_tokens") or 0
                    usage["output"] += o.get("output_tokens") or 0
                    usage["calls"] += 1
                    pending = []
                    for c in o.get("tool_calls") or []:
                        args = c.get("args") if isinstance(c.get("args"), dict) else {}
                        name = c.get("name") or "?"
                        pending.append((name, args.get("CommandLine") if name == "run_command" else None,
                                        name + "|" + json.dumps(args, sort_keys=True, ensure_ascii=False)))
                elif kind in ("GENERIC", "ERROR_MESSAGE") and pending:
                    name, cmd, fp = pending.pop(0)
                    events.append({"source": "antigravity", "session": sid, "tool": name, "cmd": cmd,
                                   "text": o.get("content") or "", "fp": fp,
                                   "err": bool(o.get("error")) or kind == "ERROR_MESSAGE"})
        yield usage, None
        for e in events:
            yield None, e


LOOP_MIN = 3     # identical consecutive calls that count as a loop run (AD13 C8 trigger)


def loop_stats(seqs: dict, total: int) -> dict:
    """Per source: runs of LOOP_MIN or more identical consecutive tool calls (same tool and same arguments), how many
    of them failed every time, the calls beyond the first of each run, and their result size as a share of all text.
    This is the stage-0 trigger for the loop guard: a guard is worth building where this is not zero."""
    out = {}
    for (src, _sid), seq in seqs.items():
        o = out.setdefault(src, {"calls": 0, "runs": 0, "failing_runs": 0, "repeat_calls": 0, "repeat_size": 0})
        o["calls"] += len(seq)
        i = 0
        while i < len(seq):
            j = i
            while j + 1 < len(seq) and seq[j + 1][0] == seq[i][0]:
                j += 1
            if j - i + 1 >= LOOP_MIN:
                o["runs"] += 1
                o["failing_runs"] += all(x[1] for x in seq[i:j + 1])
                o["repeat_calls"] += j - i
                o["repeat_size"] += sum(x[2] for x in seq[i + 1:j + 1])
            i = j + 1
    for o in out.values():
        o["repeat_share"] = round(o["repeat_size"] / total, 4) if total else 0
    return out


def measure(events, use_tokens: bool = False) -> dict:
    """Aggregate usage and tool events into totals, by tool and by shell command class."""
    enc = None
    if use_tokens:
        from g07_tokens import enc as _enc
        enc = _enc()

    def size(text):
        return len(enc.encode(text, disallowed_special=())) if enc else len(text)

    usage = defaultdict(lambda: defaultdict(int))
    tools = defaultdict(lambda: [0, 0])
    cmds = defaultdict(lambda: [0, 0])
    sessions = set()
    seen = set()
    repeat = defaultdict(int)
    read_sizes = []
    seqs = defaultdict(list)    # (source, session) -> [(fingerprint, failed, size)] in call order
    for u, e in events:
        if u:
            sessions.add((u["source"], u["session"]))
            for k in ("input", "cache_read", "cache_write", "output", "calls"):
                usage[u["source"]][k] += u[k]
        if e:
            n = size(e["text"])
            if e.get("fp") is not None:
                seqs[(e["source"], e["session"])].append((e["fp"], bool(e.get("err")), n))
            tools[e["tool"]][0] += 1
            tools[e["tool"]][1] += n
            key = (e["source"], e["session"], hash(e["text"]))
            if len(e["text"]) > REPEAT_MIN and key in seen:
                repeat[e["tool"]] += n
            seen.add(key)
            if e["tool"] in SHELL_TOOLS and e["cmd"]:
                c = classify_command(e["cmd"])
                cmds[c][0] += 1
                cmds[c][1] += n
                if c in READ_CMDS:
                    read_sizes.append(n)
            elif e["tool"] in READ_TOOLS:
                read_sizes.append(n)
    total = sum(v[1] for v in tools.values()) or 1
    shell_total = sum(v[1] for k, v in tools.items() if k in SHELL_TOOLS) or 1
    loops = loop_stats(seqs, total)
    reads = sum(read_sizes)
    excess = sum(x - READ_CAP for x in read_sizes if x > READ_CAP)
    repeats = sum(repeat.values())
    return {
        "unit": "o200k_tokens" if use_tokens else "chars",
        "sessions": len(sessions),
        "usage": {s: dict(v) for s, v in usage.items()},
        "result_total": total if tools else 0,
        "tools": {k: {"calls": v[0], "size": v[1], "share": round(v[1] / total, 4)}
                  for k, v in sorted(tools.items(), key=lambda kv: -kv[1][1])},
        "shell_commands": {k: {"calls": v[0], "size": v[1], "share_of_shell": round(v[1] / shell_total, 4)}
                           for k, v in sorted(cmds.items(), key=lambda kv: -kv[1][1])},
        "reads_share_of_all": round(reads / total, 4) if tools else 0,
        "read_excess_over_cap": {"cap": READ_CAP, "share_of_all": round(excess / total, 4) if tools else 0},
        "loops": loops,
        "exact_repeats": {"min_size": REPEAT_MIN, "share_of_all": round(repeats / total, 4) if tools else 0,
                          "by_tool": dict(sorted(repeat.items(), key=lambda kv: -kv[1]))},
    }


def summarize(r: dict, top: int = 8) -> str:
    lines = [f"tokmeter unit={r['unit']} sessions={r['sessions']}"]
    for s, u in r["usage"].items():
        denom = (u["input"] + u["cache_read"] + u["cache_write"]) or 1
        lines.append(f"usage {s}: calls={u['calls']} input={u['input']} cache_read={u['cache_read']} "
                     f"cache_write={u['cache_write']} output={u['output']} cache_share={u['cache_read'] / denom:.1%}")
    for k, v in list(r["tools"].items())[:top]:
        lines.append(f"tool {k}: calls={v['calls']} size={v['size']} share={v['share']:.1%}")
    for k, v in list(r["shell_commands"].items())[:top]:
        lines.append(f"cmd {k}: calls={v['calls']} size={v['size']} share_of_shell={v['share_of_shell']:.1%}")
    for src, o in r.get("loops", {}).items():
        lines.append(f"loops {src}: calls={o['calls']} runs>={LOOP_MIN}={o['runs']} failing_runs={o['failing_runs']} "
                     f"repeat_calls={o['repeat_calls']} repeat_share={o['repeat_share']:.2%}")
    lines.append(f"reads_share_of_all={r['reads_share_of_all']:.1%} "
                 f"read_excess_over_{r['read_excess_over_cap']['cap']}={r['read_excess_over_cap']['share_of_all']:.1%} "
                 f"exact_repeats={r['exact_repeats']['share_of_all']:.1%}")
    return "\n".join(lines)


def main(argv=None) -> int:
    force_utf8_stdio()
    a = list(sys.argv[1:] if argv is None else argv)
    opts = {"source": "all", "days": 0, "tokens": False, "top": 8,
            "json": str(VAULT / "AI-Agent" / "state" / "tokmeter-latest.json")}
    i = 0
    while i < len(a):
        k = a[i]
        if k == "--tokens":
            opts["tokens"] = True
        elif k in ("--source", "--days", "--top", "--json") and i + 1 < len(a):
            i += 1
            opts[k[2:]] = a[i]
        else:
            print(f"bad argument: {k}", file=sys.stderr)
            return 2
        i += 1
    if opts["source"] not in ("goose", "claude", "antigravity", "all"):
        print(f"bad --source: {opts['source']}", file=sys.stderr)
        return 2
    try:
        days, top = int(opts["days"]), int(opts["top"])
    except ValueError:
        print("bad number", file=sys.stderr)
        return 2
    since = time.time() - days * 86400 if days else 0.0
    root = Path(os.environ.get("STRATUM_CLAUDE_PROJECTS") or Path.home() / ".claude" / "projects")

    env_brain = os.environ.get("STRATUM_ANTIGRAVITY_BRAIN")
    # the three Antigravity front ends keep separate folders (Antigravity 2.0, CLI, IDE); a later one is skipped when absent
    brains = [Path(env_brain)] if env_brain else [Path.home() / ".gemini" / d / "brain"
                                                  for d in ("antigravity", "antigravity-cli", "antigravity-ide")]

    def events():
        if opts["source"] in ("goose", "all"):
            yield from iter_goose(session_db_path(), since)
        if opts["source"] in ("claude", "all"):
            yield from iter_claude(root, since)
        if opts["source"] == "antigravity":
            for brain in brains:
                yield from iter_antigravity(brain, since)

    r = measure(events(), opts["tokens"])
    try:
        Path(opts["json"]).parent.mkdir(parents=True, exist_ok=True)
        Path(opts["json"]).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        print(f"json not written: {e}", file=sys.stderr)
    print(summarize(r, top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
