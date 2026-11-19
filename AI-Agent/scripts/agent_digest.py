#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""agent_digest - what went wrong in the agents' sessions, kept after the harness deletes its logs (AD13 G1, register D56).

usage:
  agent_digest.py digest [--days N] [--source <agent>|all] [--json]   archive one compact digest per session
  agent_digest.py report [--days N] [--write] [--json]                           the problem report of the last N days (default 7)
  agent_digest.py run [--if-stale N] [--commit]                                  digest, then report --write (the weekly command);
                                                                                 --if-stale N skips it when the last run is under N days old,
                                                                                 --commit commits only the archive and the report, through the gate
  agent_digest.py coverage [--json]                                              which agents are read on this machine and what their logs can tell
  agent_digest.py schedule print [--os linux|macos|windows|claude-hook|antigravity-hook]   a template for the weekly run; printed, never installed

Why: Claude Code keeps its transcripts for about a week; nothing kept what they said about failures. The digest is the durable part: per
session the harness, the models named, the turns, the tool calls, every tool ERROR classified and normalised into a signature, the
retries, the denials, the interruptions and the commit-gate blocks seen in command output. It never stores a command, a file's text or
a model answer: only tool names (a shell command becomes its first word), error kinds and a normalised first line of the error
(paths, numbers, hashes and quoted names replaced), and any line that matches a credential shape is replaced by "[redacted]".

Files: AI-Agent/state/session-digests.jsonl (one JSON object per line, upserted by `harness:session`; tracked in git, it is the archive)
and AI-Agent/state/problems/problems-YYYY-Www.md (the report). The commit gate's own run log is gate_log.py (git-ignored).
Agents are ADAPTERS (agent_adapters.py): Claude Code, Antigravity and Cursor are read; Codex and Goose are declared (no reader: no session of
theirs to write one against, or idle). The report ends with a Coverage table, so a gap is stated. Claude Desktop chats are not on this machine."""
from __future__ import annotations

import datetime
import glob
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _vaultlib as V  # noqa: E402
from tokmeter import classify_command  # noqa: E402
import agent_adapters as AD  # noqa: E402

SCHEMA = 4                       # 2: + loops (3 or more identical calls in a row); 3: one row per ISO week of a session; 4: the service error kind and the notes field; an older row is kept as it was when its log is gone
LOOP_RUN = 3
DIGEST_REL = Path("AI-Agent") / "state" / "session-digests.jsonl"
PROBLEMS_REL = Path("AI-Agent") / "state" / "problems"
SIG_CHARS = 140
_HOME_SLUG = re.compile(r"(?:[A-Za-z]-)?-(?:home|Users)-[^-]+-")      # anywhere: a sub-agent scratch folder carries the home folder in the middle of its name
TOP_TOOLS = 12
KINDS = ("exit", "edit-mismatch", "missing-file", "invalid-args", "denied", "hook", "service", "other")
HOMES = {
    "exit": "a command failed: read the first word of the tool label; the fix is usually a wrapper, a flag the tool lacks or a missing check before the call",
    "edit-mismatch": "an edit missed its target or the file was not read first: the edit path (`apply.py`, the read-before-write rule) or its message should teach the fix",
    "missing-file": "a path that does not exist: a convention or a link the agent guessed (R19 to R21, the handoff map)",
    "invalid-args": "the call itself was malformed (a wrong argument shape, a relative path, a bad line range): the tool schema or its description should prevent it",
    "denied": "a permission or user denial: a rule that is too narrow, or an action that should not have been tried",
    "hook": "a hook refused the call: the hook message must say what to do instead",
    "service": "the model service or the stream failed (unavailable, interrupted, idle timeout): not a defect of a tool or a rule; count it, do not fix it here",
    "other": "unclassified: read the signature",
}

_PATH = re.compile(r"(?<![\w<])(?:~/?|/)[\w.@%+~-]+(?:/[\w.@%+~-]*)*")      # an absolute path of one segment or more; "and/or" and "a/b" are not paths
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_HEX = re.compile(r"\b[0-9a-f]{7,}\b")
_NUM = re.compile(r"\d+")
_SQ = re.compile(r"'[^']{1,80}'")
_DQ = re.compile(r'"[^"]{1,80}"')
_BLOCK_LINE = re.compile(r"^BLOCK\t\w+\t([\w.-]+)\t", re.M)
_FAIL_LINE = re.compile(r"^(?:FAIL|MISSING|TIMEOUT) ([\w.-]+)", re.M)


def norm_sig(text) -> str:
    """The first meaningful line of an error with what varies from one occurrence to the next replaced."""
    t = text if isinstance(text, str) else str(text or "")
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    while lines and re.match(r"^(exit code \d+|error:?|<tool_use_error>)$", lines[0], re.I):
        lines = lines[1:]
    lines = [ln for ln in lines if re.search(r"[A-Za-z\u0600-\u06ff]", ln)]       # a line of dashes or numbers is not a message
    first = lines[0] if lines else ""
    if first.startswith("Traceback") and len(lines) > 1:
        first = lines[-1]                       # a Python traceback: the last line names the exception
    try:
        if V.scan_secrets(first, entropy=False, hidden=False):
            return "[redacted]"
    except Exception:          # noqa: BLE001 - a scanner fault must not drop the error, but must not leak either
        return "[redacted]"
    for real, token in ((str(V.VAULT), "<vault>"), (os.path.expanduser("~"), "~")):      # this machine's own folders first: a name with spaces would not survive the path rule
        if len(real) > 3:
            first = first.replace(real, token)
    first = _UUID.sub("<id>", first)
    first = _PATH.sub("<path>", first)
    first = _HEX.sub("<hex>", first)
    first = _SQ.sub("'…'", first)
    first = _DQ.sub('"…"', first)
    first = _NUM.sub("<n>", first)
    return re.sub(r"\s+", " ", first).strip()[:SIG_CHARS]


def classify_error(text) -> str:
    t = text if isinstance(text, str) else str(text or "")
    low = t.lower()
    head = low[:300]
    if "hook" in head and ("denied" in head or "blocked" in head or "refus" in head or "pretooluse" in head or "pre-tool" in head):
        return "hook"
    if "doesn't want to proceed" in head or "user rejected" in head or "permission denied" in head or "was rejected" in head or "denied by" in head or "tool use was rejected" in head:
        return "denied"
    if ("api error" in head or "unavailable (code" in head or "stream was interrupted" in head or "stream idle timeout" in head
            or "model output error" in head or "overloaded" in head or "rate limit" in head or "read tcp" in head):
        return "service"
    if ("invalid_args" in head or "invalid tool call" in head or "must be an absolute path" in head or "invalid line range" in head or "failed to parse" in head
            or "invalid argument" in head or "required parameter" in head or "inputvalidationerror" in head):
        return "invalid-args"
    if ("not found in the file" in low or "target content not found" in low or "string to replace not found" in low or "has not been read" in low
            or "must read" in head or "old_string" in head or "did not match" in head):
        return "edit-mismatch"
    if "no such file or directory" in low or "does not exist" in head or "not a directory" in head or "cannot find the path" in head:
        return "missing-file"
    if re.match(r"^\s*exit code \d+", low) or "command failed" in head or "returned non-zero" in head:
        return "exit"
    return "other"


def _text_of(content) -> str:
    if isinstance(content, list):
        return "".join(x.get("text", "") for x in content if isinstance(x, dict))
    return content if isinstance(content, str) else ""


def _gate_ids(text: str) -> list:
    if "GATE BLOCKED" not in text and "\nFAIL " not in "\n" + text:
        return []
    ids = _BLOCK_LINE.findall(text)
    if re.search(r"^(?:PASS|SKIP) [\w.-]+", text, re.M):      # the suite listing of consumer_suites: only there is "FAIL <suite>" a gate verdict
        ids += _FAIL_LINE.findall(text)
    return ids


def _label(name: str, args) -> str:
    if name in ("Bash", "run_command") and isinstance(args, dict):
        return "Bash:" + classify_command(args.get("command") or args.get("CommandLine") or "").rstrip(";&|")
    return name or "?"


def _ihash(args) -> str:
    try:
        return hashlib.sha1(json.dumps(args, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
    except Exception:          # noqa: BLE001
        return ""


class _Acc:
    def __init__(self):
        self.tools = Counter()
        self.errors = Counter()          # (label, kind, sig) -> n
        self.gate = Counter()
        self.retries = 0
        self.denied = 0
        self.last_err = None             # (label, input hash) of the last errored call
        self.run = None                  # (label, input hash) of the call before, and how many times in a row it was made
        self.run_n = 0
        self.loops = Counter()           # label -> runs of LOOP_RUN or more identical calls: the call itself did not change, only the model's hope

    def call(self, label, ih):
        self.tools[label] += 1
        if self.run == (label, ih):
            self.run_n += 1
            if self.run_n == LOOP_RUN:
                self.loops[label] += 1
        else:
            self.run, self.run_n = (label, ih), 1
        if self.last_err and self.last_err == (label, ih):
            self.retries += 1
        self.last_err = None

    def error(self, label, ih, text):
        kind = classify_error(text)
        self.errors[(label, kind, norm_sig(text))] += 1
        if kind in ("denied", "hook"):
            self.denied += 1
        self.last_err = (label, ih)

    def pack(self) -> dict:
        errs = [{"tool": k[0], "kind": k[1], "sig": k[2], "n": n} for k, n in sorted(self.errors.items(), key=lambda x: (-x[1], x[0]))]
        return {"tool_calls": sum(self.tools.values()), "tools": dict(self.tools.most_common(TOP_TOOLS)), "errors": errs,
                "error_total": sum(e["n"] for e in errs), "retries": self.retries, "denied": self.denied,
                "gate": dict(self.gate.most_common()), "loops": sum(self.loops.values()), "loop_tools": dict(self.loops.most_common(5))}


def norm_project(slug: str) -> str:
    """A Claude Code project folder name is the path of the working directory with dashes: its home prefix names the user and the machine."""
    return _HOME_SLUG.sub("~-", slug or "")


def _week_of(ts) -> str | None:
    try:
        y, w, _ = datetime.date.fromisoformat(str(ts)[:10]).isocalendar()
    except ValueError:
        return None
    return f"{y}-W{w:02d}"


class _Slice:
    def __init__(self):
        self.turns = self.user_turns = self.interrupts = self.compactions = 0
        self.models, self.acc = Counter(), _Acc()
        self.first = self.last = ""
        self.notes = Counter()           # words an adapter could not interpret (an unknown status): counted so the first real session shows them


def digest_slices(u) -> list:
    """The archive rows of one session, one per ISO week it ran in (UTC), so a session that crosses a week boundary is not counted whole in the
    week it ended: measured 11.8% of tool calls and 7.3% of errors were in an earlier week than the session's end. The row of the LAST week keeps the
    session's own key; an earlier week is `<sid>@<week>` with `slice_of` naming the session. A session inside one week is one row, as before."""
    first_week = None
    try:
        for e in u.read():                 # pass 1 stops at the first time stamp: events before any stamp belong to that week
            if e.get("k") == "ts" and _week_of(e["v"]):
                first_week = _week_of(e["v"])
                break
    except OSError:
        return []
    cur = first_week
    sl: dict = {}
    pend = {}
    try:
        for e in u.read():
            k = e.get("k")
            if k == "ts":
                cur = _week_of(e["v"]) or cur
            x = sl.setdefault(cur, _Slice())
            if k == "ts":
                x.first, x.last = x.first or e["v"], e["v"]
            elif k == "turn":
                x.turns += 1
                if e.get("model"):
                    x.models[e["model"]] += 1
            elif k == "user":
                x.user_turns += e.get("n", 1)
                x.interrupts += e.get("interrupts", 0)
            elif k == "compaction":
                x.compactions += 1
            elif k == "call":
                lab, ih = _label(e.get("name"), e.get("label_args") or {}), _ihash(e.get("args"))
                pend[e.get("id")] = (lab, ih)
                x.acc.call(lab, ih)
            elif k == "result":
                lab, ih = pend.pop(e.get("id"), (e.get("orphan") or "?", ""))
                if lab.startswith("Bash"):
                    for gid in _gate_ids(e.get("text") or ""):
                        x.acc.gate[gid] += 1
                if e.get("err") is not None:
                    x.acc.error(lab, ih, e["err"])
            elif k == "error":
                x.acc.error("agent", "", e.get("text") or "")
            elif k == "note":
                x.notes[str(e.get("v"))[:40]] += 1
    except OSError:
        return []
    if not sl:
        sl[cur] = _Slice()
    weeks = sorted(sl, key=lambda w: (w is None, w or ""))
    rows = []
    for w in weeks:
        x = sl[w]
        last_week = w == weeks[-1]
        row = {"v": SCHEMA, "harness": u.harness, "sid": u.sid if last_week else f"{u.sid}@{w}", "project": norm_project(u.project), "start": x.first, "end": x.last,
               "turns": x.turns, "user_turns": x.user_turns, "models": dict(x.models.most_common()), "interrupts": x.interrupts, "compactions": x.compactions,
               "subagents": u.subagents, "src_size": u.fp, "src_mtime": u.mtime}
        if not last_week:
            row["slice_of"] = u.key
        row.update(x.acc.pack())
        if x.notes:
            row["notes"] = dict(x.notes.most_common(5))
        rows.append(row)
    return rows


def digest_unit(u) -> dict | None:
    """The row of the session's last week (the whole session when it ran inside one week): see digest_slices."""
    rows = digest_slices(u)
    return rows[-1] if rows else None


def digest_claude(path) -> dict | None:
    return digest_unit(AD.claude_unit(path)) if os.path.isfile(path) else None


def digest_antigravity(path) -> dict | None:
    return digest_unit(AD.antigravity_unit(path)) if os.path.isfile(path) else None


def sources(days: float, source: str = "all", claude_glob: str | None = None, agy_glob: str | None = None):
    """(harness, path) pairs of the file-based agents: kept for callers that only list files; the digest itself uses AD.discover."""
    return sorted((u.harness, u.src) for u in _discover(days, source, claude_glob, agy_glob) if u.src)


def _discover(days, source, claude_glob=None, agy_glob=None, overrides=None):
    ov = dict(overrides or {})
    if claude_glob:
        ov["claude"] = [claude_glob, os.path.join(os.path.dirname(os.path.dirname(claude_glob)), "*", "*", "subagents", "*.jsonl")]
    if agy_glob:
        ov["antigravity"] = [agy_glob]
    return AD.discover(days, source, ov)


def load(path: Path) -> dict:
    rows = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                rows[f"{r.get('harness')}:{r.get('sid')}"] = r
    except OSError:
        pass
    return rows


def save(path: Path, rows: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            for k in sorted(rows, key=lambda k: (rows[k].get("start") or "", k)):
                fh.write(json.dumps(rows[k], ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def run_digest(days=7.0, source="all", digest_path: Path | None = None, claude_glob=None, agy_glob=None, overrides: dict | None = None) -> dict:
    dp = Path(digest_path) if digest_path else V.VAULT / DIGEST_REL
    rows = load(dp)
    migrated = 0
    for rr in rows.values():              # rows archived before the home prefix was removed from the project name
        np_ = norm_project(rr.get("project", ""))
        if np_ != rr.get("project"):
            rr["project"] = np_
            migrated += 1
    new = upd = same = skipped = 0
    for u in _discover(days, source, claude_glob, agy_glob, overrides):
        old = rows.get(u.key)
        if old and old.get("src_size") == u.fp and old.get("v") == SCHEMA:
            same += 1
            continue
        ds = digest_slices(u)
        if not ds:
            skipped += 1
            continue
        for k_ in [k_ for k_, r_ in rows.items() if r_.get("slice_of") == u.key]:
            del rows[k_]                   # the earlier-week rows of this session are rebuilt below
        for d in ds:
            rows[f"{d['harness']}:{d['sid']}"] = d
        if old:
            upd += 1
        else:
            new += 1
    if new or upd or migrated or not dp.exists():
        save(dp, rows)
    return {"new": new, "updated": upd, "unchanged": same, "skipped": skipped, "total": len(rows), "path": str(dp), "migrated": migrated}


def _week(ts: datetime.date) -> str:
    y, w, _ = ts.isocalendar()
    return f"{y}-W{w:02d}"


def build_report(rows: list, gate_rows: list, since: str, until: str, label: str) -> tuple[str, dict]:
    """(markdown, numbers) of the sessions whose end falls in [since, until]; gate_rows are gate_log lines."""
    sel = [r for r in rows if since <= (r.get("end") or "") <= until + "~"]
    ids = {(r.get("slice_of") or f"{r['harness']}:{r['sid']}"): r["harness"] for r in sel}      # a session that crossed a week is one session
    by_h = Counter(ids.values())
    calls = sum(r.get("tool_calls", 0) for r in sel)
    errs = sum(r.get("error_total", 0) for r in sel)
    kinds, tools_err, tools_calls = Counter(), Counter(), Counter()
    sig = defaultdict(lambda: {"n": 0, "sessions": set(), "harness": set()})
    for r in sel:
        for t, n in (r.get("tools") or {}).items():
            tools_calls[t] += n
        for e in r.get("errors", []):
            kinds[e["kind"]] += e["n"]
            tools_err[e["tool"]] += e["n"]
            s = sig[(e["tool"], e["kind"], e["sig"])]
            s["n"] += e["n"]
            s["sessions"].add(r.get("slice_of") or f"{r['harness']}:{r['sid']}")
            s["harness"].add(r["harness"])
    retries = sum(r.get("retries", 0) for r in sel)
    loops, loop_tools, loop_sessions, unscored = 0, Counter(), 0, 0
    for r in sel:
        if "loops" not in r:            # a schema 1 row from before the loop count: not counted as zero
            unscored += 1
            continue
        loops += r["loops"]
        loop_sessions += 1 if r["loops"] else 0
        loop_tools.update(r.get("loop_tools") or {})
    notes = Counter()
    for r in sel:
        notes.update(r.get("notes") or {})
    denied = sum(r.get("denied", 0) for r in sel)
    interrupts = sum(r.get("interrupts", 0) for r in sel)
    gate_agent = Counter()
    for r in sel:
        gate_agent.update(r.get("gate") or {})
    recurring = sorted(((k, v) for k, v in sig.items() if (v["n"] >= 3 and len(v["sessions"]) >= 2) or v["n"] >= 5),
                       key=lambda kv: (-kv[1]["n"], kv[0]))[:15]
    try:
        import gate_log as GL
        gs = GL.summarize([g for g in gate_rows if since <= g.get("ts", "") <= until + "~"])
    except ImportError:
        gs = {"hook_runs": {}, "blocking_ids": {}, "manual_runs": 0}
    nums = {"sessions": len(ids), "by_harness": dict(by_h), "tool_calls": calls, "errors": errs,
            "error_rate_pct": round(100 * errs / calls, 1) if calls else 0.0, "kinds": dict(kinds.most_common()), "retries": retries, "loops": loops, "loop_sessions": loop_sessions,
            "denied": denied, "interrupts": interrupts, "recurring": len(recurring), "gate_hook_runs": gs["hook_runs"],
            "gate_blocking_ids": gs["blocking_ids"], "gate_seen_in_sessions": dict(gate_agent.most_common())}
    L = ["---", "tags:", "  - ai-agent", "  - report", f"created: {datetime.date.today().isoformat()}", "---", "",
         f"# Agent problem report {label}", "",
         f"Period {since[:10]} to {until[:10]}. Made by `agent_digest.py` from the session digests and the commit-gate run log; no model wrote it. "
         "Read the recurring signatures first: a tool that fails the same way in two sessions is a defect of the tool, the skill or the rule, not of the model.", "",
         "## Coverage", "",
         f"{len(ids)} sessions ({', '.join(f'{h} {n}' for h, n in sorted(by_h.items())) or 'none'}), {calls} tool calls, {errs} errors ({nums['error_rate_pct']}%).", ""]
    L += ["## Errors by kind", "", "| Kind | Count | Where to look |", "|---|---|---|"]
    for k in KINDS:
        if kinds.get(k):
            L.append(f"| {k} | {kinds[k]} | {HOMES[k]} |")
    if not kinds:
        L.append("| none | 0 | |")
    L += ["", "## Tools that fail most", "", "| Tool | Errors | Calls | Rate |", "|---|---|---|---|"]
    for t, n in tools_err.most_common(8):
        c = tools_calls.get(t, 0)
        L.append(f"| `{t}` | {n} | {c if c else 'n/a'} | {str(round(100 * n / c, 1)) + '%' if c else 'n/a'} |")
    if not tools_err:
        L.append("| none | 0 | 0 | 0% |")
    L += ["", "## Recurring signatures", ""]
    if recurring:
        L += ["| Tool | Kind | Signature | Count | Sessions |", "|---|---|---|---|---|"]
        for (t, k, s), v in recurring:
            L.append(f"| `{t}` | {k} | {s.replace('|', '/')} | {v['n']} | {len(v['sessions'])} |")
    else:
        L.append("None: no signature reached 3 occurrences in 2 sessions (or 5 in one).")
    L += ["", "## Friction", "", f"- Retries of the same call right after an error: {retries}.", f"- Denials and hook refusals: {denied}.",
          f"- Interruptions by the user: {interrupts}.",
          f"- Loops (the same call with the same arguments {LOOP_RUN} times or more in a row): {loops} in {loop_sessions} sessions"
          + (", by tool: " + ", ".join(f"`{t}` {n}" for t, n in loop_tools.most_common(5)) if loop_tools else "")
          + (f"; {unscored} older digests have no loop count" if unscored else "")
          + ". A status poll (a task waited on by asking again) repeats on purpose but still costs a model turn each time: read the tool before the count."
          + ((" Unrecognised words in agent logs (an adapter could not interpret them): " + ", ".join(f"`{k}` {n}" for k, n in notes.most_common(5)) + ".") if notes else ""), "", "## Commit gate", ""]
    runs = gs["hook_runs"]
    if runs:
        L.append("Commit attempts logged by the gate in this period: " + ", ".join(f"{k} {n}" for k, n in runs.items()) + f" ({gs['manual_runs']} manual runs not counted).")
        if gs["blocking_ids"]:
            L += ["", "| Gate and check | Blocks |", "|---|---|"] + [f"| `{k}` | {n} |" for k, n in list(gs["blocking_ids"].items())[:10]]
    else:
        L.append("No hook runs of the gate are logged in this period (the log starts with the first commit after `gate_log.py` was added).")
    if gate_agent:
        L += ["", "Blocks the agents saw in command output (older sessions, before the log existed): " + ", ".join(f"`{k}` {n}" for k, n in list(gate_agent.items())[:10]) + "."]
    L += ["", "## Not covered", "", "Agents without a reader are named in the table of agents read, at the end. Also not read: Claude Desktop chats, model answers, "
          "thinking text (Claude Code does not store it) and the outcome of a session (whether the work was kept): errors are what the tools reported, "
          "not what the user judged. Antigravity results are matched to calls by their order (its log has no call id), so a share of its errors carries the tool "
          "label `unknown`.", ""]
    return "\n".join(L), nums


def run_report(days=7.0, write=False, digest_path: Path | None = None, out_dir: Path | None = None, gate_path: Path | None = None, coverage=None) -> tuple[str, dict, str]:
    rows = list(load(Path(digest_path) if digest_path else V.VAULT / DIGEST_REL).values())
    try:
        import gate_log as GL
        grows = GL.read(Path(gate_path) if gate_path else None)
    except ImportError:
        grows = []
    now = datetime.datetime.now(datetime.timezone.utc)
    since = (now - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    until = now.strftime("%Y-%m-%dT%H:%M:%S")
    label = f"{_week(now.date())}" if abs(days - 7) < 0.5 else f"last {int(days)} days"
    md, nums = build_report(rows, grows, since, until, label)
    if coverage is not None:            # which agents were read: a harness nobody reads is a stated gap, not a quiet one
        md = md.rstrip("\n") + "\n\n## Agents read\n\n" + AD.format_coverage(coverage) + "\n"
        nums["coverage"] = {r["agent"]: r["status"] for r in coverage}
    path = ""
    if write:
        d = Path(out_dir) if out_dir else V.VAULT / PROBLEMS_REL
        d.mkdir(parents=True, exist_ok=True)
        path = str(d / f"problems-{_week(now.date())}.md")
        Path(path).write_text(md, encoding="utf-8", newline="\n")
    return md, nums, path


def record_last_run(summary: str, ok_flag: bool = True, path: Path | None = None, now: datetime.datetime | None = None) -> str:
    """Append the contract 1.2 line to AI-Agent/last-runs.md (arch_contract.LAST_RUN) so that state.py, which every session starts with, warns when the
    weekly run is more than 8 days old: this is the reminder, no timer exists. Returns the line, or "" when the file is not there."""
    p = Path(path) if path else V.VAULT / "AI-Agent" / "last-runs.md"
    if not p.is_file():
        return ""
    stamp = (now or datetime.datetime.now()).strftime("%Y-%m-%d %H:%M")
    line = f"- **last_run:** agent-digest · {stamp} · {'ok' if ok_flag else 'fail'} · {summary}"
    data = p.read_bytes()
    eol = "\r\n" if b"\r\n" in data else "\n"          # the file's own line ending is kept: a Windows checkout may be CRLF
    with open(p, "ab") as fh:
        fh.write((("" if data.endswith(b"\n") or not data else eol) + line + eol).encode("utf-8"))
    return line


_LAST_RUN = re.compile(r"last_run:\*\* agent-digest \u00b7 (\d{4}-\d{2}-\d{2} \d{2}:\d{2})")


def days_since_last_run(path: Path | None = None, now: datetime.datetime | None = None) -> float | None:
    """Days since the last `agent-digest` line of last-runs.md, or None when there is none."""
    p = Path(path) if path else V.VAULT / "AI-Agent" / "last-runs.md"
    try:
        found = _LAST_RUN.findall(p.read_text(encoding="utf-8"))
    except OSError:
        return None
    if not found:
        return None
    t = datetime.datetime.strptime(found[-1], "%Y-%m-%d %H:%M")
    return ((now or datetime.datetime.now()) - t).total_seconds() / 86400


def commit_outputs(paths: list, root: Path | None = None) -> tuple[bool, str]:
    """Commit exactly `paths` (the archive and the report) through the commit gate: never `git add` of a folder, never --no-verify, never a push.
    Returns (committed, message). Nothing to commit is (False, 'nothing to commit')."""
    import subprocess
    root = Path(root) if root else V.VAULT
    rel = [Path(p).resolve().relative_to(root.resolve()).as_posix() for p in paths if p and Path(p).exists()]
    if not rel:
        return False, "nothing to commit"
    ig = subprocess.run(["git", "check-ignore", "--"] + rel, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if ig.returncode == 0 and ig.stdout.strip():   # 0 = at least one path is ignored: say which, instead of a cryptic `git add` failure
        return False, "refused: .gitignore ignores " + ", ".join(ig.stdout.split()) + " (the digest archive cannot be committed here)"
    st = subprocess.run(["git", "status", "--porcelain", "--"] + rel, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if st.returncode != 0:
        return False, "git status failed: " + (st.stderr or "").strip()[:160]
    if not st.stdout.strip():
        return False, "nothing to commit"
    ad = subprocess.run(["git", "add", "--"] + rel, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if ad.returncode != 0:
        return False, "git add failed: " + (ad.stderr or "").strip()[:160]
    cm = subprocess.run(["git", "commit", "--only", "-m", "chore(agent-digest): weekly session digests and problem report", "--"] + rel,
                        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if cm.returncode != 0:
        return False, "the commit gate or git refused: " + ((cm.stdout or "") + (cm.stderr or "")).strip()[-300:]
    return True, "committed " + ", ".join(rel)


def schedule_text(os_name: str, vault: Path | None = None, python: str | None = None) -> str:
    """A ready-to-install template that runs the weekly command; this tool prints it and never installs it (a timer is persistent configuration)."""
    v = str(Path(vault) if vault else V.VAULT)
    py = python or sys.executable or "python3"
    script = os.path.join(v, "AI-Agent", "scripts", "agent_digest.py")
    cmd = f'"{py}" "{script}" run --if-stale 6 --commit'
    from xml.sax.saxutils import escape as _x
    if os_name == "linux":
        return ("# ~/.config/systemd/user/agent-digest.service\n[Unit]\nDescription=Weekly agent session digest\n[Service]\nType=oneshot\n"
                f"WorkingDirectory={v}\nExecStart={cmd}\n\n# ~/.config/systemd/user/agent-digest.timer\n[Unit]\nDescription=Weekly agent session digest\n"
                "[Timer]\nOnCalendar=weekly\nPersistent=true\n[Install]\nWantedBy=timers.target\n\n# install: systemctl --user enable --now agent-digest.timer\n")
    if os_name == "macos":
        return ("<!-- ~/Library/LaunchAgents/app.stratum.agent-digest.plist ; install: launchctl load ~/Library/LaunchAgents/app.stratum.agent-digest.plist -->\n"
                '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>\n<key>Label</key><string>app.stratum.agent-digest</string>\n'
                f"<key>ProgramArguments</key><array><string>{_x(py)}</string><string>{_x(script)}</string><string>run</string><string>--if-stale</string><string>6</string><string>--commit</string></array>\n"
                "<key>EnvironmentVariables</key><dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>\n"
                f"<key>WorkingDirectory</key><string>{_x(v)}</string>\n<key>StartCalendarInterval</key><dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>9</integer></dict>\n</dict></plist>\n")
    if os_name == "windows":
        return f'REM run once in a Command Prompt; remove with: schtasks /Delete /TN AgentDigest\nschtasks /Create /SC WEEKLY /D MON /ST 09:00 /TN AgentDigest /TR "cmd /c cd /d \\"{v}\\" && {cmd.replace(chr(34), chr(92) + chr(34))}"\n'
    if os_name == "claude-hook":
        return ('# merge into .claude/settings.json (project or user): a SessionStart hook that runs the weekly command only when it is stale\n'
                '{"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": ' + json.dumps(f"{cmd}") + "}]}]}}\n")
    if os_name == "antigravity-hook":
        return ('# merge into .agents/hooks.json (see the Antigravity hooks documentation for the event name of a session start)\n'
                + json.dumps({"command": cmd}) + "\n")
    raise ValueError(os_name)


SCHEDULE_TARGETS = ("linux", "macos", "windows", "claude-hook", "antigravity-hook")


def main(argv=None) -> int:
    V.force_utf8_stdio()
    a = list(sys.argv[1:] if argv is None else argv)
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if a else 2
    cmd, rest = a[0], a[1:]
    as_json = "--json" in rest
    write = "--write" in rest
    commit = "--commit" in rest
    rest = [x for x in rest if x not in ("--json", "--write", "--commit")]

    def opt(name, default):
        if name in rest:
            i = rest.index(name)
            v = rest[i + 1] if i + 1 < len(rest) else None
            del rest[i:i + 2]
            return v
        return default
    try:
        days = float(opt("--days", "7"))
    except ValueError:
        print("ERROR: --days needs a number", file=sys.stderr)
        return 2
    source = opt("--source", "all")
    stale = opt("--if-stale", None)
    target = opt("--os", None)
    readable = [n for n, v in AD.ADAPTERS.items() if v[1] is not None]
    if source not in readable + ["all"]:
        print("ERROR: --source is " + ", ".join(readable) + " or all", file=sys.stderr)
        return 2
    try:
        stale_days = float(stale) if stale is not None else None
    except ValueError:
        print("ERROR: --if-stale needs a number of days", file=sys.stderr)
        return 2
    if rest and not (cmd == "schedule" and rest == ["print"]):
        print(f"ERROR: unknown argument {rest[0]!r}", file=sys.stderr)
        return 2
    if cmd == "schedule":
        if not rest or rest[0] != "print":
            print("ERROR: usage: schedule print [--os " + "|".join(SCHEDULE_TARGETS) + "]", file=sys.stderr)
            return 2
        t = target or AD.platform_name()
        if t not in SCHEDULE_TARGETS:
            print("ERROR: --os is " + ", ".join(SCHEDULE_TARGETS), file=sys.stderr)
            return 2
        if t in ("linux", "macos", "windows") and t != AD.platform_name():
            print(f"# NOTE: printed on {AD.platform_name()}; the paths below are this machine's. Print it again on the {t} machine before installing.")
        print(schedule_text(t), end="")
        return 0
    if cmd == "coverage":
        cov = AD.coverage(days)
        print(json.dumps(cov, ensure_ascii=False) if as_json else AD.format_coverage(cov))
        return 0
    if cmd == "digest":
        r = run_digest(days, source)
        print(json.dumps(r) if as_json else f"digests: {r['new']} new, {r['updated']} updated, {r['unchanged']} unchanged, {r['total']} in the archive")
        return 0
    if cmd in ("report", "run"):
        if cmd == "run" and stale_days is not None:
            age = days_since_last_run()
            if age is not None and age < stale_days:
                print(f"fresh: the last run was {age:.1f} days ago (limit {stale_days:g}), nothing to do")
                return 0
        if cmd == "run":
            r = run_digest(max(days, 8), source)
            print(f"digests: {r['new']} new, {r['updated']} updated, {r['total']} in the archive")
            write = True
        md, nums, path = run_report(days, write, coverage=AD.coverage(days))
        if cmd == "run":
            record_last_run(f"{r['new']} new and {r['updated']} updated digests, {r['total']} in the archive, {nums['errors']} errors in {nums['sessions']} sessions this week")
        if as_json:
            print(json.dumps({"numbers": nums, "path": path}, ensure_ascii=False))
        else:
            print(md if not write else f"report written: {path}\n" + json.dumps(nums, ensure_ascii=False))
        if commit and cmd == "run":
            ok_, msg = commit_outputs([V.VAULT / DIGEST_REL, path])
            print(msg)
            return 0 if ok_ or msg == "nothing to commit" else 1
        return 0
    print(f"ERROR: unknown command {cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
