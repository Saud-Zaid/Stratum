#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""agent_adapters - one table of the AI agents whose session logs the vault can read (AD13 G3, register D58). Standard library only.

Why a table: agent_digest.py first knew two agents through two hard-coded functions and two hard-coded paths. Every new agent meant a copy of
the pipeline; every new operating system meant a hunt for `~`. Here an agent is one ADAPTER: where its logs live on each operating system, how
to read one session of them as a stream of EVENTS in one schema, and what that agent's log can and cannot tell (its CAPABILITIES). The
analysers (agent_digest, and later ctxlife and the hooks) read events only, never an agent's own format.

The event schema (a plain dict per event, key "k"):
  {"k": "ts",         "v": "<ISO time or epoch text>"}                     time of the line; the first and the last give the session span
  {"k": "turn",       "model": "<name or empty>"}                         one model turn, already de-duplicated by the adapter
  {"k": "user",       "n": 1, "interrupts": 0}                            user messages and the interruptions among them
  {"k": "compaction"}                                                       the harness compacted the context
  {"k": "call",       "id": "<id>", "name": "<tool>", "args": <object|None>}   a tool call; its arguments are hashed, never stored
  {"k": "result",     "id": "<call id or None>", "text": "<output>", "err": "<error text>" or None, "orphan": "<label if no call matches>"}
  {"k": "error",      "text": "<text>"}                                    an error that belongs to no tool (the harness or the API)

An adapter pairs calls and results itself when its format needs it (Antigravity lists the calls of a turn and then the results in order).
Capabilities say what an agent cannot give, so a report never reads a missing number as "no problem": tokens "exact" | "none", errors,
calls (tool names and arguments), ids (calls linked to results by an identifier), compactions.

Status of each adapter on a machine: "parsed" (found, read), "none-found" (a parser exists, no logs on this machine), "found-no-parser" (the
agent's logs are on this machine and nobody wrote a reader), "declared" (no parser, nothing found). `coverage()` reports it, and the weekly
report prints it: a harness that is not read is a stated gap, not a quiet one.

Operating systems: Linux, macOS and Windows resolve their roots through `roots(name, platform, env)`, which reads the environment instead of
a hard-coded `~`. The Linux roots are verified on the vault owner's machine; the macOS and Windows roots follow the layouts the vendors document
and are NOT verified on those systems (the tests pin the strings, not the behaviour of a real Mac or Windows machine)."""
from __future__ import annotations

import glob
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Callable, Iterator

# --------------------------------------------------------------------------------------------------------------------- platform roots

def home_dir(env=None) -> str:
    e = os.environ if env is None else env
    return e.get("USERPROFILE") or e.get("HOME") or os.path.expanduser("~")


def platform_name(platform: str | None = None) -> str:
    p = platform or sys.platform
    return "windows" if p.startswith("win") else "macos" if p == "darwin" else "linux"


def roots(name: str, platform: str | None = None, env=None) -> list:
    """Glob patterns (with forward slashes) of the log files of agent `name` on the given platform."""
    e = os.environ if env is None else env
    h = home_dir(e).replace("\\", "/")
    osn = platform_name(platform)
    if name == "claude":
        base = (e.get("CLAUDE_CONFIG_DIR") or h + "/.claude").replace("\\", "/")
        return [base + "/projects/*/*.jsonl", base + "/projects/*/*/subagents/*.jsonl"]
    if name == "antigravity":
        return [f"{h}/.gemini/{b}/brain/*/.system_generated/logs/transcript_full.jsonl" for b in ("antigravity", "antigravity-cli", "antigravity-ide")]
    if name == "cursor":
        if osn == "macos":
            base = h + "/Library/Application Support/Cursor"
        elif osn == "windows":
            base = (e.get("APPDATA") or h + "/AppData/Roaming").replace("\\", "/") + "/Cursor"
        else:
            base = (e.get("XDG_CONFIG_HOME") or h + "/.config").replace("\\", "/") + "/Cursor"
        return [base + "/User/globalStorage/state.vscdb"]
    if name == "codex":
        return [(e.get("CODEX_HOME") or h + "/.codex").replace("\\", "/") + "/sessions/*/*/*/rollout-*.jsonl"]
    if name == "goose":
        if osn == "windows":
            return [(e.get("APPDATA") or h + "/AppData/Roaming").replace("\\", "/") + "/Block/goose/data/sessions/sessions.db"]
        if osn == "macos":
            return [h + "/Library/Application Support/Block/goose/sessions/sessions.db"]
        return [h + "/.local/share/goose/sessions/sessions.db"]
    return []


# --------------------------------------------------------------------------------------------------------------------- the unit

class Unit:
    """One session of one agent: enough to key it in the archive, to see that it changed, and to read it as events."""

    def __init__(self, harness: str, sid: str, project: str, fp: int, mtime: int, subagents: int, read: Callable[[], Iterator[dict]], src: str = ""):
        self.harness, self.sid, self.project, self.fp, self.mtime, self.subagents, self.read, self.src = harness, sid, project, fp, mtime, subagents, read, src

    @property
    def key(self) -> str:
        return f"{self.harness}:{self.sid}"


def _jsonl(path):
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for ln in fh:
            try:
                o = json.loads(ln)
            except ValueError:
                continue
            if isinstance(o, dict):
                yield o


def _within(f: str, cut: float) -> bool:
    try:
        return os.path.getmtime(f) >= cut
    except OSError:
        return False


# --------------------------------------------------------------------------------------------------------------------- Claude Code

def claude_events(path) -> Iterator[dict]:
    seen = set()
    for o in _jsonl(path):
        ts = o.get("timestamp") or ""
        if ts:
            yield {"k": "ts", "v": ts}
        if o.get("type") == "system" and o.get("subtype") == "compact_boundary":
            yield {"k": "compaction"}
            continue
        m = o.get("message") or {}
        c = m.get("content")
        if o.get("type") == "assistant":
            mid = m.get("id")
            if mid not in seen:
                seen.add(mid)
                yield {"k": "turn", "model": m.get("model") if m.get("model") and m.get("model") != "<synthetic>" else ""}
        if isinstance(c, str):
            if o.get("type") == "user":
                yield {"k": "user", "n": 1, "interrupts": c.count("[Request interrupted by user")}
            continue
        if not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "tool_use":
                yield {"k": "call", "id": b.get("id"), "name": b.get("name"), "args": b.get("input"), "label_args": b.get("input") or {}}
            elif t == "tool_result":
                txt = text_of(b.get("content"))
                yield {"k": "result", "id": b.get("tool_use_id"), "text": txt, "err": txt if b.get("is_error") else None, "orphan": "?"}
            elif t == "text" and o.get("type") == "user":
                yield {"k": "user", "n": 1, "interrupts": (b.get("text") or "").count("[Request interrupted by user")}


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(x.get("text", "") for x in content if isinstance(x, dict))
    return ""


def claude_unit(f) -> "Unit":
    p = Path(f)
    st = p.stat()
    if p.parent.name == "subagents":          # <slug>/<session>/subagents/agent-<id>.jsonl: a sub-agent has its own transcript
        return Unit("claude-sub", f"{p.parents[1].name}/{p.stem}", p.parents[2].name, st.st_size, int(st.st_mtime), 0, (lambda q=str(f): claude_events(q)), str(f))
    n_sub = len(glob.glob(str(p.with_suffix("")) + "/subagents/*.jsonl"))
    return Unit("claude", p.stem, p.parent.name, st.st_size, int(st.st_mtime), n_sub, (lambda q=str(f): claude_events(q)), str(f))


def claude_units(days: float, patterns: list | None = None) -> list:
    import time
    cut = time.time() - days * 86400
    return [claude_unit(f) for pat in (patterns or roots("claude")) for f in glob.glob(pat) if _within(f, cut)]


# --------------------------------------------------------------------------------------------------------------------- Antigravity

def antigravity_events(path) -> Iterator[dict]:
    queue = []                           # ids of the tool calls of the last planner response, consumed by the steps that follow
    n = 0
    for o in _jsonl(path):
        ts = o.get("created_at") or ""
        if ts:
            yield {"k": "ts", "v": ts}
        ty = o.get("type")
        if ty == "PLANNER_RESPONSE":
            yield {"k": "turn", "model": o.get("model") or ""}
            queue = []
            for tc in o.get("tool_calls") or []:
                if isinstance(tc, dict):
                    n += 1
                    cid = f"a{n}"
                    queue.append(cid)
                    yield {"k": "call", "id": cid, "name": tc.get("name"), "args": tc.get("args"), "label_args": tc.get("args") or {}}
        elif ty == "USER_INPUT":
            yield {"k": "user", "n": 1, "interrupts": 0}
        elif ty == "CHECKPOINT":
            yield {"k": "compaction"}
        elif ty == "ERROR_MESSAGE":
            yield {"k": "error", "text": o.get("error") or o.get("content") or ""}
        elif ty == "GENERIC":
            cid = queue.pop(0) if queue else None
            txt = o.get("content") or ""
            bad = o.get("status") in ("ERROR", "INVALID") or o.get("error")
            yield {"k": "result", "id": cid, "text": txt, "err": (o.get("error") or txt) if bad else None, "orphan": "unknown"}


def antigravity_unit(f) -> "Unit":
    p = Path(f)
    st = p.stat()
    return Unit("antigravity", p.parts[-4] if len(p.parts) >= 4 else p.stem, "", st.st_size, int(st.st_mtime), 0, (lambda q=str(f): antigravity_events(q)), str(f))


def antigravity_units(days: float, patterns: list | None = None) -> list:
    import time
    cut = time.time() - days * 86400
    return [antigravity_unit(f) for pat in (patterns or roots("antigravity")) for f in glob.glob(pat) if _within(f, cut)]


# --------------------------------------------------------------------------------------------------------------------- Cursor

_CURSOR_BAD = ("error", "failed", "rejected", "cancelled", "canceled", "aborted")
_CURSOR_OK = ("completed", "complete", "success", "succeeded", "done", "ok", "finished")
_CURSOR_RUNNING = ("loading", "pending", "running", "in_progress", "streaming", "")      # a call with no outcome yet; no vendor document lists the words, so any other word is reported


def _kv_rows(db, like: str):
    return list(db.execute("select key, value from cursorDiskKV where key like ?", (like,)))


def _open_ro(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=2)      # as_uri quotes a space, # or ? in the path and writes file:///C:/ on Windows


def cursor_events_from(db, cid: str) -> Iterator[dict]:
    """The events of one Cursor composer: `composerData:<id>` names the model, `bubbleId:<id>:<bubble>` rows are the messages, in time order."""
    row = db.execute("select value from cursorDiskKV where key = ?", ("composerData:" + cid,)).fetchone()
    cd = _loads(row[0]) if row else {}
    model = ((cd.get("modelConfig") or {}).get("modelName") or "") if isinstance(cd, dict) else ""
    if model == "default":
        model = "cursor-default"
    bubbles = []
    for k, v in _kv_rows(db, f"bubbleId:{cid}:%"):
        o = _loads(v)
        if isinstance(o, dict):
            bubbles.append(o)
    bubbles.sort(key=lambda b: str(b.get("createdAt") or ""))
    if isinstance(cd, dict) and cd.get("createdAt"):
        yield {"k": "ts", "v": _iso(cd.get("createdAt"))}
    for b in bubbles:
        if b.get("createdAt"):
            yield {"k": "ts", "v": _iso(b.get("createdAt"))}
        if b.get("type") == 1:
            yield {"k": "user", "n": 1, "interrupts": 0}
            continue
        yield {"k": "turn", "model": model}
        t = b.get("toolFormerData")
        if isinstance(t, dict) and t.get("name"):
            cid_ = str(t.get("toolCallId") or id(t))
            args = _loads(t.get("params")) if isinstance(t.get("params"), str) else t.get("params")
            yield {"k": "call", "id": cid_, "name": t.get("name"), "args": args, "label_args": args if isinstance(args, dict) else {}}
            status = str(t.get("status") or "").lower()
            if status in _CURSOR_RUNNING:
                continue                    # a call still running, or never answered: it is not a result
            code = _exit_code(t.get("result"))
            bad = status in _CURSOR_BAD or (code not in (None, 0))
            if not bad and status not in _CURSOR_OK:
                yield {"k": "note", "v": "cursor-status:" + status[:30]}       # an unrecognised word is counted, never guessed as an error
            msg = (f"Exit code {code}" if code not in (None, 0) and status not in _CURSOR_BAD else str(t.get("error") or t.get("result") or status)) if bad else ""
            yield {"k": "result", "id": cid_, "text": msg, "err": msg if bad else None, "orphan": "?"}


def _exit_code(result):
    """The exit code of a terminal call when the result carries one (a JSON object with exitCode or exit_code), else None."""
    r = _loads(result) if isinstance(result, str) else result
    if isinstance(r, dict):
        for k in ("exitCode", "exit_code"):
            if isinstance(r.get(k), int) and not isinstance(r.get(k), bool):
                return r[k]
    return None


def _loads(v):
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return {}


def _iso(v) -> str:
    if isinstance(v, (int, float)):
        import datetime
        return datetime.datetime.fromtimestamp(v / 1000.0, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return str(v)


def cursor_units(days: float, patterns: list | None = None) -> list:
    import time
    cut = time.time() - days * 86400
    out = []
    for pat in patterns or roots("cursor"):
        for f in glob.glob(pat):
            try:
                db = _open_ro(f)
                heads = list(db.execute("select composerId, createdAt, lastUpdatedAt from composerHeaders"))
            except sqlite3.Error:
                continue
            try:
                for cid, created, upd in heads:
                    if cid == "empty-state-draft":
                        continue
                    last = (upd or created or 0) / 1000.0
                    if last < cut:
                        continue
                    n_b = db.execute("select count(*), coalesce(sum(length(value)),0) from cursorDiskKV where key like ?", (f"bubbleId:{cid}:%",)).fetchone()
                    if not n_b[0]:
                        continue            # a composer with no message is an empty draft: nothing to digest
                    out.append(Unit("cursor", cid, "", int(n_b[1]), int(last), 0, (lambda c=cid, q=f: _cursor_read(q, c)), f))
            except sqlite3.Error:
                pass
            finally:
                db.close()
    return out


def _cursor_read(path, cid):
    try:
        db = _open_ro(path)
    except sqlite3.Error:
        return
    try:
        yield from cursor_events_from(db, cid)
    except sqlite3.Error:
        return
    finally:
        db.close()


# --------------------------------------------------------------------------------------------------------------------- the table

CAPS = {
    "claude": {"tokens": "none", "errors": True, "calls": True, "ids": True, "compactions": True},
    "antigravity": {"tokens": "exact", "errors": True, "calls": True, "ids": False, "compactions": True},
    "cursor": {"tokens": "none", "errors": True, "calls": True, "ids": True, "compactions": False},
}

# name -> (label, units(days, patterns) or None when nobody wrote a reader, note)
ADAPTERS = {
    "claude": ("Claude Code", claude_units, "~/.claude/projects (CLAUDE_CONFIG_DIR); sub-agent transcripts archived as claude-sub; the same layout on all three systems"),
    "antigravity": ("Antigravity", antigravity_units, "~/.gemini/antigravity*/brain/*/.system_generated/logs; the macOS and Windows paths are the Linux layout, unverified there"),
    "cursor": ("Cursor", cursor_units, "state.vscdb of the app (a SQLite file, read-only); fields read follow a real file with no conversation in it, tool statuses other than loading are unverified"),
    "codex": ("Codex CLI", None, "~/.codex/sessions rollout files: a reader needs a real session to be written against; none is installed here"),
    "goose": ("Goose", None, "sessions.db: idle on this machine since 2026-11-04, read by fx01_session_analyzer"),
}


def discover(days: float, only: str = "all", overrides: dict | None = None) -> list:
    """Units of every agent that has a reader, newest logs only. `overrides` maps an adapter name to a list of glob patterns (tests, odd installs)."""
    out = []
    for name, (_label, fn, _note) in ADAPTERS.items():
        if fn is None or only not in ("all", name):
            continue
        out.extend(fn(days, (overrides or {}).get(name)))
    return sorted(out, key=lambda u: (u.harness, u.sid))


def coverage(days: float = 7.0, platform: str | None = None, env=None, overrides: dict | None = None) -> list:
    """One row per agent: status on this machine and what its log can tell. Never raises."""
    rows = []
    for name, (label, fn, note) in ADAPTERS.items():
        pats = (overrides or {}).get(name) or roots(name, platform, env)
        found = sum(len(glob.glob(p)) for p in pats)
        try:
            n_units = len(fn(36500.0, (overrides or {}).get(name))) if fn else 0
        except Exception:        # noqa: BLE001 - a coverage report never fails on one agent
            n_units = 0
        if fn is None:
            status = "found-no-parser" if found else "declared"
        else:
            status = "parsed" if n_units else "none-found"
        rows.append({"agent": name, "label": label, "status": status, "log_files": found, "sessions": n_units,
                     "capabilities": CAPS.get(name, {}), "note": note})
    return rows


def format_coverage(rows: list) -> str:
    out = ["| agent | status | sessions | tokens | note |", "|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['label']} | {r['status']} | {r['sessions']} | {r['capabilities'].get('tokens', 'unknown')} | {r['note']} |")
    return "\n".join(out)


if __name__ == "__main__":
    print(format_coverage(coverage()))
