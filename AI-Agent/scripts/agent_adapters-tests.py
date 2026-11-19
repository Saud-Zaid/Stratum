#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""agent_adapters-tests.py - AD13 G3: the agent table, its three operating-system layouts, the Cursor reader on a synthetic database,
the coverage statement, and the weekly run's new switches (--if-stale, --commit, schedule print)."""
from __future__ import annotations

import datetime
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _vaultlib as _V  # noqa: E402
import agent_adapters as AD  # noqa: E402
import agent_digest as A  # noqa: E402

_V.scrub_git_env()          # a git hook sets GIT_INDEX_FILE and friends; this file makes temporary repositories and must not write into the real one (found 2026-11-19: it overwrote the hook's index)

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {'' if cond else got}".rstrip())


tmp = Path(tempfile.mkdtemp(prefix="agad-"))

# --- roots: the three systems, from the environment and not from a hard-coded home
lin = {"HOME": "/home/u"}
mac = {"HOME": "/Users/u"}
win = {"USERPROFILE": "C:\\Users\\u", "APPDATA": "C:\\Users\\u\\AppData\\Roaming"}
ok("roots: Claude Code under HOME/.claude on Linux", AD.roots("claude", "linux", lin)[0] == "/home/u/.claude/projects/*/*.jsonl", AD.roots("claude", "linux", lin))
ok("roots: CLAUDE_CONFIG_DIR wins", AD.roots("claude", "linux", {"HOME": "/h", "CLAUDE_CONFIG_DIR": "/cfg"})[0] == "/cfg/projects/*/*.jsonl")
ok("roots: a Windows profile is read from USERPROFILE and its backslashes become slashes", AD.roots("claude", "win32", win)[0] == "C:/Users/u/.claude/projects/*/*.jsonl", AD.roots("claude", "win32", win))
ok("roots: Cursor on Linux, macOS and Windows", [AD.roots("cursor", p, e)[0] for p, e in (("linux", lin), ("darwin", mac), ("win32", win))] ==
   ["/home/u/.config/Cursor/User/globalStorage/state.vscdb", "/Users/u/Library/Application Support/Cursor/User/globalStorage/state.vscdb",
    "C:/Users/u/AppData/Roaming/Cursor/User/globalStorage/state.vscdb"], [AD.roots("cursor", p, e)[0] for p, e in (("linux", lin), ("darwin", mac), ("win32", win))])
ok("roots: XDG_CONFIG_HOME moves Cursor on Linux", AD.roots("cursor", "linux", {"HOME": "/h", "XDG_CONFIG_HOME": "/x"})[0] == "/x/Cursor/User/globalStorage/state.vscdb")
ok("roots: Antigravity on Windows has slashes only", all("\\" not in r and r.startswith("C:/Users/u/.gemini/") for r in AD.roots("antigravity", "win32", win)), AD.roots("antigravity", "win32", win))
ok("roots: Antigravity has its three product folders", len(AD.roots("antigravity", "linux", lin)) == 3 and all(".gemini/" in r for r in AD.roots("antigravity", "linux", lin)))
ok("roots: Codex honours CODEX_HOME, Goose differs per system", AD.roots("codex", "linux", {"HOME": "/h", "CODEX_HOME": "/cx"})[0].startswith("/cx/sessions/") and
   len({AD.roots("goose", p, e)[0] for p, e in (("linux", lin), ("darwin", mac), ("win32", win))}) == 3)
ok("roots: an unknown agent has none, platform names are three", AD.roots("nobody") == [] and {AD.platform_name(p) for p in ("linux", "darwin", "win32", "cygwin")} == {"linux", "macos", "windows"})

# --- the Cursor reader on a synthetic state.vscdb (field names follow a real file; there was no conversation in the real one)
dbp = tmp / "Cursor" / "User" / "globalStorage" / "state.vscdb"
dbp.parent.mkdir(parents=True)
db = sqlite3.connect(dbp)
db.execute("create table composerHeaders (composerId text, workspaceId text, createdAt integer, lastUpdatedAt integer, isArchived integer, isSubagent integer, recency integer, checkpointAt integer, subagentTypeName text, value text)")
db.execute("create table cursorDiskKV (key text primary key, value blob)")
now_ms = int(datetime.datetime.now().timestamp() * 1000)
old_ms = now_ms - 90 * 86400 * 1000
SECRET = "sk" + "_live" + "_" + "A1b2C3d4E5f6G7h8I9j0K1l2"
SENT = "SENTINEL-FILE-TEXT-DO-NOT-STORE"
for cid, created in (("c-real", now_ms - 3600_000), ("c-old", old_ms), ("c-empty", now_ms - 1000), ("empty-state-draft", now_ms)):
    db.execute("insert into composerHeaders values (?,?,?,?,0,0,0,0,'','')", (cid, "w", created, created))
    db.execute("insert into cursorDiskKV values (?,?)", ("composerData:" + cid, json.dumps({"modelConfig": {"modelName": "gpt-x"}, "createdAt": created})))


def bubble(cid, bid, ts, ty, tool=None, status="completed", err=None, params=None):
    o = {"bubbleId": bid, "type": ty, "createdAt": ts, "text": SENT, "tokenCount": {"inputTokens": 0, "outputTokens": 0}}
    if tool:
        o["toolFormerData"] = {"name": tool, "status": status, "toolCallId": "call-" + bid, "params": json.dumps(params or {"path": "/x/" + SENT}), "tool": 1}
        if err:
            o["toolFormerData"]["error"] = err
    db.execute("insert into cursorDiskKV values (?,?)", (f"bubbleId:{cid}:{bid}", json.dumps(o)))


bubble("c-real", "b1", "2026-11-19T10:00:00.000Z", 1)
bubble("c-real", "b2", "2026-11-19T10:00:05.000Z", 2, "read_file")
bubble("c-real", "b3", "2026-11-19T10:00:09.000Z", 2, "edit_file", status="error", err="file does not exist: /x/y.md and key " + SECRET)
bubble("c-real", "b4", "2026-11-19T10:00:12.000Z", 2, "run_terminal_cmd", status="loading")
bubble("c-real", "b5", "2026-11-19T10:00:15.000Z", 2)
bubble("c-old", "b1", "2026-08-01T10:00:00.000Z", 1)
bubble("empty-state-draft", "b1", "2026-11-19T10:00:00.000Z", 1)           # the placeholder draft even with a message in it is not a session
db.commit()
db.close()
before = (dbp.stat().st_mtime_ns, dbp.stat().st_size)
units = AD.cursor_units(30, [str(dbp)])
ok("cursor: only the composer with messages inside the window is a unit (an empty draft, an old one and the placeholder are not)", [u.sid for u in units] == ["c-real"], [u.sid for u in units])
u = units[0]
ev = list(u.read())
ok("cursor: events carry the model, 4 assistant turns, 1 user message and ordered time", [e["k"] for e in ev].count("turn") == 4 and [e["k"] for e in ev].count("user") == 1 and
   all(e.get("model") == "gpt-x" for e in ev if e["k"] == "turn"), [e["k"] for e in ev])
ok("cursor: a loading tool is a call without a result, an error status is a result with an error", [e["k"] for e in ev].count("call") == 3 and [e["k"] for e in ev].count("result") == 2 and
   sum(1 for e in ev if e["k"] == "result" and e["err"]) == 1)
row = A.digest_unit(u)
js = json.dumps(row)
ok("cursor: the digest row has the shared shape, harness cursor and the errors classified", row["harness"] == "cursor" and row["turns"] == 4 and row["user_turns"] == 1 and row["error_total"] == 1 and row["models"] == {"gpt-x": 4}, row)
ok("cursor: the error is a missing-file signature with the key redacted and the path gone", row["errors"][0]["kind"] == "missing-file" and SECRET not in js and "/x/y.md" not in js, row.get("errors"))
ok("cursor: neither the message text nor the tool arguments reach the row (only a hash of the arguments)", SENT not in js)
ok("cursor: the database is opened read-only and is not touched", (dbp.stat().st_mtime_ns, dbp.stat().st_size) == before)
ro = AD._open_ro(dbp)
try:
    ro.execute("create table zz (a)")
    wrote = True
except sqlite3.Error:
    wrote = False
ro.close()
ok("cursor: the connection refuses a write", not wrote)
ok("roots: a Windows profile without APPDATA falls back to AppData/Roaming under the profile, with slashes", AD.roots("cursor", "win32", {"USERPROFILE": "C:\\Users\\u"})[0] == "C:/Users/u/AppData/Roaming/Cursor/User/globalStorage/state.vscdb", AD.roots("cursor", "win32", {"USERPROFILE": "C:\\Users\\u"}))
odd = tmp / "odd dir (x)#1%2" / "state.vscdb"
odd.parent.mkdir()
shutil_copy = __import__("shutil").copy
shutil_copy(dbp, odd)
ok("cursor: a path with spaces, brackets, # and % opens (the URI is quoted)", [x.sid for x in AD.cursor_units(30, [str(odd)])] == ["c-real"], [x.sid for x in AD.cursor_units(30, [str(odd)])])
junk = tmp / "junk" / "state.vscdb"
junk.parent.mkdir()
junk.write_bytes(b"not a database at all")
ok("cursor: a corrupt database gives no units and no crash", AD.cursor_units(30, [str(junk)]) == [])
none_t = tmp / "nt.vscdb"
sqlite3.connect(none_t).close()
ok("cursor: a database without the composer tables gives no units", AD.cursor_units(30, [str(none_t)]) == [])
ok("cursor: a missing file gives no units", AD.cursor_units(30, [str(tmp / "nope" / "state.vscdb")]) == [])

# --- discovery and the archive key
ov = {"cursor": [str(dbp)], "claude": [str(tmp / "none" / "*.jsonl")], "antigravity": [str(tmp / "none" / "*.jsonl")]}
ok("discover: all agents with a reader, keyed harness:sid", [x.key for x in AD.discover(30, "all", ov)] == ["cursor:c-real"])
ok("discover: one agent only", AD.discover(30, "claude", ov) == [] and len(AD.discover(30, "cursor", ov)) == 1)
ok("discover: agents without a reader are skipped without error", AD.discover(30, "codex", ov) == [])
arch = tmp / "arch.jsonl"
r1 = A.run_digest(30, "cursor", arch, overrides=ov)
r2 = A.run_digest(30, "cursor", arch, overrides=ov)
ok("archive: a Cursor session is archived once and is unchanged on the second run", r1["new"] == 1 and r2["new"] == 0 and r2["unchanged"] == 1 and r2["total"] == 1, (r1, r2))

# --- coverage: a stated gap
home = tmp / "home"
(home / ".codex" / "sessions" / "2026" / "11" / "19").mkdir(parents=True)
(home / ".codex" / "sessions" / "2026" / "11" / "19" / "rollout-1.jsonl").write_text("{}\n", encoding="utf-8")
cov = {c["agent"]: c for c in AD.coverage(30, "linux", {"HOME": str(home)}, {"cursor": [str(dbp)], "claude": [str(tmp / "n1" / "*")], "antigravity": [str(tmp / "n2" / "*")]})}
ok("coverage: parsed, none-found, found-no-parser and declared are told apart", cov["cursor"]["status"] == "parsed" and cov["claude"]["status"] == "none-found" and cov["codex"]["status"] == "found-no-parser" and cov["goose"]["status"] == "declared", {k: v["status"] for k, v in cov.items()})
ok("coverage: every row says what the log can tell (tokens exact only for Antigravity)", cov["antigravity"]["capabilities"]["tokens"] == "exact" and cov["cursor"]["capabilities"]["tokens"] == "none")
ok("coverage: the table has one line per agent", len(AD.format_coverage(list(cov.values())).splitlines()) == 2 + len(cov))

# --- the CLI
env = dict(os.environ, HOME=str(home), VAULT=str(tmp / "vault"))
(tmp / "vault" / "AI-Agent").mkdir(parents=True)
cli = lambda *a: subprocess.run([sys.executable, str(HERE / "agent_digest.py"), *a], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120)  # noqa: E731
p = cli("coverage")
ok("CLI coverage prints the table", p.returncode == 0 and "| Cursor |" in p.stdout and "Codex CLI" in p.stdout, p.stdout + p.stderr)
ok("CLI --source takes any agent with a reader and refuses others", cli("digest", "--source", "cursor").returncode == 0 and cli("digest", "--source", "codex").returncode == 2 and cli("digest", "--source", "zz").returncode == 2)
bad = {t: cli("schedule", "print", "--os", t) for t in A.SCHEDULE_TARGETS}
ok("CLI schedule print: five targets print a template that names the weekly command", all(r.returncode == 0 and "--if-stale" in r.stdout and "agent_digest.py" in r.stdout for r in bad.values()), {t: r.stderr[:80] for t, r in bad.items() if r.returncode})
ok("CLI schedule print: each target has its own mechanism", "systemctl --user" in bad["linux"].stdout and "launchctl" in bad["macos"].stdout and "schtasks" in bad["windows"].stdout and "SessionStart" in bad["claude-hook"].stdout)
ok("CLI schedule print: a template for another system warns that the paths are this machine's", AD.platform_name() in ("linux", "macos", "windows") and any("NOTE: printed on" in bad[t].stdout for t in ("linux", "macos", "windows") if t != AD.platform_name()))
ok("CLI schedule print: a bad target, a bad verb and nothing installed", cli("schedule", "print", "--os", "bsd").returncode == 2 and cli("schedule").returncode == 2 and cli("schedule", "install").returncode == 2)
ok("CLI --if-stale with a word is exit 2", cli("run", "--if-stale", "x").returncode == 2)

# --- --if-stale
lr = tmp / "last-runs.md"
fixed = datetime.datetime(2026, 11, 19, 12, 0)
lr.write_text("- **last_run:** agent-digest \u00b7 2026-11-17 12:00 \u00b7 ok \u00b7 x\n- **last_run:** other \u00b7 2026-11-01 12:00 \u00b7 ok \u00b7 y\n", encoding="utf-8")
ok("if-stale: the age comes from the last agent-digest line, not another job's", abs(A.days_since_last_run(lr, fixed) - 2.0) < 1e-6, A.days_since_last_run(lr, fixed))
lr.write_text("- **last_run:** other \u00b7 2026-11-01 12:00 \u00b7 ok \u00b7 y\n", encoding="utf-8")
ok("if-stale: no file or no line is None (so the run goes ahead)", A.days_since_last_run(tmp / "nope.md", fixed) is None and A.days_since_last_run(lr, fixed) is None)
(tmp / "vault" / "AI-Agent" / "last-runs.md").write_text("- **last_run:** agent-digest \u00b7 " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M") + " \u00b7 ok \u00b7 now\n", encoding="utf-8")
p = cli("run", "--if-stale", "6")
ok("if-stale: a fresh run is skipped, saying so, and writes no report", p.returncode == 0 and "fresh" in p.stdout and not (tmp / "vault" / "AI-Agent" / "state" / "problems").exists(), p.stdout + p.stderr)
(tmp / "vault" / "AI-Agent" / "last-runs.md").write_text("- **last_run:** agent-digest \u00b7 2020-01-01 00:00 \u00b7 ok \u00b7 old\n", encoding="utf-8")
p = cli("run", "--if-stale", "6")
ok("if-stale: a stale run goes ahead, writes the report with the Coverage table", p.returncode == 0 and "report written" in p.stdout and "## Agents read" in next((tmp / "vault" / "AI-Agent" / "state" / "problems").glob("*.md")).read_text(encoding="utf-8"), p.stdout + p.stderr)

# --- --commit: exactly the listed paths, through the gate, never a push
repo = tmp / "repo"
repo.mkdir()
g = lambda *a: subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace")  # noqa: E731
g("init", "-q")
g("config", "user.email", "t@example.com")
g("config", "user.name", "t")
(repo / "other.txt").write_text("mine\n", encoding="utf-8")
(repo / "a.jsonl").write_text("1\n", encoding="utf-8")
(repo / "r.md").write_text("r\n", encoding="utf-8")
g("add", "-A")
g("commit", "-q", "-m", "base")
(repo / "other.txt").write_text("mine edited\n", encoding="utf-8")
g("add", "other.txt")                                   # staged by someone else: must stay staged and uncommitted
(repo / "a.jsonl").write_text("2\n", encoding="utf-8")
(repo / "r.md").write_text("r2\n", encoding="utf-8")
okc, msg = A.commit_outputs([repo / "a.jsonl", repo / "r.md"], repo)
files = g("show", "--name-only", "--format=", "HEAD").stdout.split()
ok("commit: it commits the archive and the report and nothing else", okc and sorted(files) == ["a.jsonl", "r.md"], (okc, msg, files))
ok("commit: another file staged before stays staged and uncommitted", g("diff", "--cached", "--name-only").stdout.split() == ["other.txt"], g("status", "--short").stdout)
ok("commit: nothing changed is not a commit and not an error", A.commit_outputs([repo / "a.jsonl", repo / "r.md"], repo) == (False, "nothing to commit"))
(repo / "a.jsonl").write_text("3\n", encoding="utf-8")
hook = repo / ".git" / "hooks" / "pre-commit"
hook.write_text("#!/bin/sh\necho gate says no\nexit 1\n", encoding="utf-8", newline="\n")
hook.chmod(0o755)
okc, msg = A.commit_outputs([repo / "a.jsonl"], repo)
ok("commit: a gate that refuses is reported, the commit is not forced", (not okc) and "gate" in msg, (okc, msg))
ok("env: the test scrubbed every GIT_ variable before it made a repository", not [k for k in os.environ if k.startswith("GIT_")])
ok("commit: the tool never pushes and never skips the hook", "push" not in Path(A.__file__).read_text(encoding="utf-8").split("def commit_outputs")[1].split("def schedule_text")[0].replace("never a push", "") and
   "--no-verify" not in Path(A.__file__).read_text(encoding="utf-8").split("def commit_outputs")[1].split("def schedule_text")[0].replace("never --no-verify", ""))

# --- loops: the same call with the same arguments three or more times in a row, for any agent (events are the common schema)
def _calls(seq):
    ev = []
    for i, (name, args) in enumerate(seq):
        ev.append({"k": "call", "id": f"i{i}", "name": name, "args": args, "label_args": args})
    return AD.Unit("cursor", "loops", "", 0, 0, 0, lambda: iter(ev))


rd = ("read_file", {"p": "a"})
rd2 = ("read_file", {"p": "b"})
ed = ("edit_file", {"p": "a"})
ok("loops: two identical calls are not a loop, three are one", A.digest_unit(_calls([rd, rd]))["loops"] == 0 and A.digest_unit(_calls([rd, rd, rd]))["loops"] == 1)
ok("loops: a run of six is one loop, not four", A.digest_unit(_calls([rd] * 6))["loops"] == 1)
ok("loops: other arguments or another tool in between break the run", A.digest_unit(_calls([rd, rd, rd2, rd, rd]))["loops"] == 0 and A.digest_unit(_calls([rd, rd, ed, rd]))["loops"] == 0)
ok("loops: two separate runs are two loops, counted by tool", (lambda r: r["loops"] == 2 and r["loop_tools"] == {"read_file": 1, "edit_file": 1})(A.digest_unit(_calls([rd] * 3 + [rd2] + [ed] * 3))))
ok("loops: the digest schema is 4 and the loop fields exist on every row", A.SCHEMA == 4 and "loop_tools" in A.digest_unit(_calls([rd])))
rows_ = [dict(A.digest_unit(_calls([rd] * 3)), end="2026-11-19T10:00:00Z"), dict(A.digest_unit(_calls([rd])), end="2026-11-19T11:00:00Z", sid="b"),
         {"harness": "claude", "sid": "old", "end": "2026-11-19T12:00:00Z", "v": 1, "tool_calls": 5}]
md_, nums_ = A.build_report(rows_, [], "2026-11-19T00:00:00", "2026-11-19T23:59:59", "t")
ok("loops: the report counts loops, the sessions that had one, and says how many older digests have no count", nums_["loops"] == 1 and nums_["loop_sessions"] == 1 and "1 older digests have no loop count" in md_ and "`read_file` 1" in md_, md_[-900:])

# --- weeks: a session that crosses a week boundary is one row per ISO week, not whole in the week it ended
def _sess(evs, sid="wk"):
    return AD.Unit("antigravity", sid, "", 111, 5, 0, lambda: iter(evs))


W46 = "2026-11-15T23:59:00Z"        # a Sunday
W47 = "2026-11-16T00:01:00Z"        # the Monday after
evs = [{"k": "ts", "v": W46}, {"k": "turn", "model": "m"}, {"k": "call", "id": "c1", "name": "read_file", "args": {"p": 1}, "label_args": {"p": 1}},
       {"k": "result", "id": "c1", "text": "", "err": "file does not exist", "orphan": "?"},
       {"k": "call", "id": "c2", "name": "edit_file", "args": {"p": 2}, "label_args": {"p": 2}},
       {"k": "ts", "v": W47}, {"k": "result", "id": "c2", "text": "", "err": "target content not found", "orphan": "?"}, {"k": "turn", "model": "m"},
       {"k": "call", "id": "c3", "name": "read_file", "args": {"p": 3}, "label_args": {"p": 3}}]
sl = A.digest_slices(_sess(evs))
ok("weeks: a session across a Sunday and a Monday is two rows, the last one under the session's own key", [r["sid"] for r in sl] == ["wk@2026-W46", "wk"] and sl[0]["slice_of"] == "antigravity:wk" and "slice_of" not in sl[1], [(r["sid"], r.get("slice_of")) for r in sl])
ok("weeks: calls, turns and spans are split by the week they happened in and add up", [r["tool_calls"] for r in sl] == [2, 1] and [r["turns"] for r in sl] == [1, 1] and sl[0]["end"] == W46 and sl[1]["start"] == W47, [(r["tool_calls"], r["turns"]) for r in sl])
ok("weeks: a result is counted in the week it arrived in, under the label of the call made the week before", [r["error_total"] for r in sl] == [1, 1] and sl[1]["errors"][0]["tool"] == "edit_file" and sl[1]["errors"][0]["kind"] == "edit-mismatch", [r["errors"] for r in sl])
ok("weeks: an event before any time stamp belongs to the first week, and no stamp at all is one row with the plain key", [r["tool_calls"] for r in A.digest_slices(_sess([{"k": "call", "id": "x", "name": "t", "args": None, "label_args": {}}, {"k": "ts", "v": W47}]))] == [1] and
   [r["sid"] for r in A.digest_slices(_sess([{"k": "turn", "model": ""}]))] == ["wk"])
ok("weeks: digest_unit gives the last week's row", A.digest_unit(_sess(evs)) == sl[1])
arch2 = tmp / "weeks.jsonl"
state = {"evs": evs, "fp": 111}


def _units(days, source, claude_glob=None, agy_glob=None, overrides=None):
    return [AD.Unit("antigravity", "wk", "", state["fp"], 5, 0, lambda: iter(state["evs"]))]


_orig = A._discover
A._discover = _units
try:
    a1 = A.run_digest(30, "all", arch2)
    a2 = A.run_digest(30, "all", arch2)
    state["evs"] = evs + [{"k": "ts", "v": "2026-11-23T10:00:00Z"}, {"k": "turn", "model": "m"}]       # grows into a third week
    state["fp"] = 222
    a3 = A.run_digest(30, "all", arch2)
finally:
    A._discover = _orig
keys = sorted(A.load(arch2))
ok("weeks: the archive holds one row per week, a second run changes nothing, growth rebuilds the slices without duplicates", a1["new"] == 1 and a2["unchanged"] == 1 and a3["updated"] == 1 and
   keys == ["antigravity:wk", "antigravity:wk@2026-W46", "antigravity:wk@2026-W47"], (a1, a2, a3, keys))
orph = A.load(arch2)
orph["antigravity:wk@2020-W01"] = {"harness": "antigravity", "sid": "wk@2020-W01", "slice_of": "antigravity:wk", "v": 3, "start": "2020-01-01", "end": "2020-01-02"}
orph["antigravity:other@2020-W01"] = {"harness": "antigravity", "sid": "other@2020-W01", "slice_of": "antigravity:other", "v": 3, "start": "2020-01-01", "end": "2020-01-02"}
A.save(arch2, orph)
state["fp"] = 333
A._discover = _units
try:
    A.run_digest(30, "all", arch2)
finally:
    A._discover = _orig
ok("weeks: a slice the session no longer produces is removed on a rebuild, another session's slice is left alone", "antigravity:wk@2020-W01" not in A.load(arch2) and "antigravity:other@2020-W01" in A.load(arch2), sorted(A.load(arch2)))
rr = [dict(r, end=r["end"] or "2026-11-19T00:00:00Z") for r in sl]
for r in rr:
    r["errors"] = [{"tool": "read_file", "kind": "missing-file", "sig": "x", "n": 2}]
md2, n2 = A.build_report(rr, [], "2026-11-01T00:00:00", "2026-11-30T00:00:00", "t")
ok("weeks: two slices of one session do not make a signature recur across sessions", n2["recurring"] == 0, n2)

# --- line endings: the archive, the report and the log are LF on every system, and a last-runs.md keeps its own style
import ast as _ast
_bad_w = []
for _f in ("agent_digest.py", "gate_log.py"):
    for _n in _ast.walk(_ast.parse((HERE / _f).read_text(encoding="utf-8"))):
        if isinstance(_n, _ast.Call):
            _fn = _n.func.attr if isinstance(_n.func, _ast.Attribute) else getattr(_n.func, "id", "")
            _mode = next((a.value for a in _n.args[1:2] if isinstance(a, _ast.Constant)), "")
            _write = _fn == "write_text" or (_fn in ("open", "fdopen") and isinstance(_mode, str) and ("w" in _mode or "a" in _mode) and "b" not in _mode)
            if _write and not any(k.arg == "newline" and isinstance(k.value, _ast.Constant) and k.value.value == "\n" for k in _n.keywords):
                _bad_w.append((_f, _n.lineno))
ok("line endings: every text writer of the digest and the gate log asks for LF", not _bad_w, _bad_w)
lf_ = tmp / "lf.md"
lf_.write_bytes(b"# t\r\n- **last_run:** opens \xc2\xb7 2026-11-19 06:00 \xc2\xb7 ok \xc2\xb7 x\r\n")
A.record_last_run("s", True, lf_, datetime.datetime(2026, 11, 19, 12, 30))
ok("line endings: a CRLF last-runs.md gets a CRLF line and its old bytes are untouched", lf_.read_bytes().startswith(b"# t\r\n- **last_run:** opens") and lf_.read_bytes().endswith(b"\r\n") and lf_.read_bytes().count(b"\n") == lf_.read_bytes().count(b"\r\n") == 3, lf_.read_bytes())
lf2_ = tmp / "lf2.md"
lf2_.write_bytes(b"a\nb")
A.record_last_run("s", True, lf2_, datetime.datetime(2026, 11, 19, 12, 30))
ok("line endings: an LF file without a final newline gets one before the new line, no CR", b"\r" not in lf2_.read_bytes() and lf2_.read_bytes().startswith(b"a\nb\n- **last_run:**"), lf2_.read_bytes())

# --- service errors, unrecognised Cursor words, exit codes, distinct sessions
CLS = [("API error (attempt 2): UNAVAILABLE (code 503): The service is overloaded", "service"), ("Error: The stream was interrupted. Please continue", "service"),
       ("API error (attempt 1): request failed: stream idle timeout", "service"), ("model output error: model output must contain either output", "service"),
       ("Exit code 1\nboom", "exit"), ("file does not exist", "missing-file"), ("The service is currently unavailable", "other")]
ok("kinds: model-service failures are their own kind, a command failure and the rest keep theirs", all(A.classify_error(t) == k for t, k in CLS) and "service" in A.KINDS and "service" in A.HOMES,
   [(t[:30], A.classify_error(t)) for t, k in CLS if A.classify_error(t) != k])

mem = sqlite3.connect(":memory:")
mem.execute("create table cursorDiskKV (key text primary key, value blob)")
mem.execute("insert into cursorDiskKV values ('composerData:m1', ?)", (json.dumps({"modelConfig": {"modelName": "m"}}),))
for i, (st, res) in enumerate([("completed", None), ("success", None), ("weird-new-word", None), ("completed", json.dumps({"exitCode": 2})), ("running", None), ("completed", json.dumps({"exitCode": 0})), ("cancelled", None)]):
    mem.execute("insert into cursorDiskKV values (?, ?)", (f"bubbleId:m1:b{i}", json.dumps({"type": 2, "createdAt": f"2026-11-19T10:00:0{i}.000Z", "toolFormerData": {"name": "run_terminal_cmd", "status": st, "toolCallId": f"t{i}", "params": "{}", "result": res}})))
evm = list(AD.cursor_events_from(mem, "m1"))
errs_ = [e for e in evm if e["k"] == "result" and e["err"] is not None]
ok("cursor: known success words are not errors, running has no result, a cancelled call and a non-zero exit code are errors", len([e for e in evm if e["k"] == "result"]) == 6 and len(errs_) == 2 and
   any(e["err"] == "Exit code 2" for e in errs_), [(e["k"], e.get("err")) for e in evm if e["k"] == "result"])
ok("cursor: an unrecognised status is a note, never an error", [e["v"] for e in evm if e["k"] == "note"] == ["cursor-status:weird-new-word"])
rown = A.digest_unit(AD.Unit("cursor", "m1", "", 1, 1, 0, lambda: iter(evm)))
ok("cursor: the digest keeps the unrecognised word and the exit-code error is kind exit", rown["notes"] == {"cursor-status:weird-new-word": 1} and any(e["kind"] == "exit" for e in rown["errors"]), rown.get("notes"))
mdn, numn = A.build_report([dict(rown, end="2026-11-19T12:00:00Z")], [], "2026-11-19T00:00:00", "2026-11-19T23:59:59", "t")
ok("report: unrecognised words are listed so the first real session shows them", "cursor-status:weird-new-word" in mdn)
two = [dict(r, end=r["end"] or "2026-11-19T10:00:00Z") for r in sl]
mdt, numt = A.build_report(two, [], "2026-11-01T00:00:00", "2026-11-30T00:00:00", "t")
ok("report: the two weekly rows of one session are one session", numt["sessions"] == 1 and numt["by_harness"] == {"antigravity": 1}, numt["by_harness"])

bad = [n for n, c, _ in R if not c]
print(f"\n{len(R) - len(bad)}/{len(R)} passed")
sys.exit(1 if bad else 0)
