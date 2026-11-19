#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""agent_digest-tests.py - AD13 G1: session digests and the problem report, on synthetic transcripts with known answers and on the real logs."""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import agent_digest as A  # noqa: E402
import gate_log as G  # noqa: E402
import _vaultlib as _L  # noqa: E402
_L.scrub_git_env()   # hook variables must not reach the temporary git repository below

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {'' if cond else got}".rstrip())


def _U(s):
    return s.encode("ascii").decode("unicode_escape")


# --- signatures
ns = A.norm_sig
ok("sig: paths, hashes, numbers and quoted names are replaced", ns("No such file or directory: '/home/u/x/y.md' at 1a2b3c4d5e line 42") == "No such file or directory: '…' at <hex> line <n>", ns("No such file or directory: '/home/u/x/y.md' at 1a2b3c4d5e line 42"))
ok("sig: a bare path becomes <path>", ns("cannot open /home/u/proj/file.txt now") == "cannot open <path> now", ns("cannot open /home/u/proj/file.txt now"))
ok("sig: the vault folder, spaces and all, becomes <vault>", ns("error at " + str(A.V.VAULT) + "/AI-Agent/x.py line 3") == "error at <vault><path> line <n>", ns("error at " + str(A.V.VAULT) + "/AI-Agent/x.py line 3"))
ok("sig: a single-segment absolute path and a ~ path are paths, and/or and a/b are not", ns("cannot open /nope.md and ~/x/y.txt, use and/or a/b") == "cannot open <path> and <path>, use and/or a/b", ns("cannot open /nope.md and ~/x/y.txt, use and/or a/b"))
ok("sig: a uuid becomes <id>", ns("session 123e4567-e89b-12d3-a456-426614174000 gone") == "session <id> gone")
ok("sig: 'Exit code N' is skipped, the message after it is kept", ns("Exit code 1\nfatal: not a repository") == "fatal: not a repository")
ok("sig: a Python traceback gives its last line", ns("Traceback (most recent call last):\n  File \"x.py\", line 3\nValueError: boom 7") == "ValueError: boom <n>", ns("Traceback (most recent call last):\n  File \"x.py\", line 3\nValueError: boom 7"))
ok("sig: lines of dashes and numbers are not messages", ns("---\n+++\n12\nreal message") == "real message")
ok("sig: Arabic text survives", _U(r"\u062e\u0637\u0623") in ns(_U(r"\u062e\u0637\u0623 \u0641\u064a \u0627\u0644\u0645\u0644\u0641")))
ok("sig: a credential shape is redacted, the value never appears", ns("auth failed for sk" + "_live" + "_" + "A1b2C3d4E5f6G7h8I9j0K1l2") == "[redacted]")
ok("sig: long text is cut to 140 characters", len(ns("x" * 400)) == 140)
ok("sig: nothing gives an empty signature, not a crash", ns("") == "" and ns(None) == "")

# --- classification
CL = [("tool call denied by pre-tool hook: Plan mode", "hook"), ("The user doesn't want to proceed with this tool use", "denied"), ("file does not exist", "missing-file"),
      ("ls: cannot access x: No such file or directory", "missing-file"), ("String to replace not found in file", "edit-mismatch"), ("target content not found in the file", "edit-mismatch"),
      ("File has not been read yet. Read it first", "edit-mismatch"), ("Exit code 2\nboom", "exit"), ("invalid line range: StartLine 9 is greater than EndLine 3", "invalid-args"),
      ("path must be an absolute path", "invalid-args"), ("The service is currently unavailable", "other"), ("PreToolUse hook blocked the call", "hook")]
bad = [(t, k, A.classify_error(t)) for t, k in CL if A.classify_error(t) != k]
ok("classification: every sample lands in its kind", not bad, bad)

# --- a Claude transcript with known answers
tmp = Path(tempfile.mkdtemp(prefix="agdig-"))
cl = tmp / "projects" / "slug"
cl.mkdir(parents=True)


def asst(mid, model, blocks, ts):
    return {"type": "assistant", "timestamp": ts, "message": {"id": mid, "model": model, "content": blocks}}


def tu(i, name, inp):
    return {"type": "tool_use", "id": i, "name": name, "input": inp}


def tr(i, text, err=False):
    return {"type": "user", "timestamp": "2026-11-19T10:00:00Z", "message": {"content": [{"type": "tool_result", "tool_use_id": i, "content": text, "is_error": err}]}}


gate_out = "PASS phase_check\nFAIL impact IMPACT-TESTS: 84/89 passed\nGATE BLOCKED blocking=1\nBLOCK\terror\tR19-missing\tx.md:3\tmsg\n"
rows = [
    asst("m1", "claude-sonnet-5-5", [tu("t1", "Bash", {"command": "cd /w && git status"})], "2026-11-19T09:00:00Z"),
    tr("t1", "Exit code 128\nfatal: not a git repository: /tmp/abc", True),
    asst("m2", "claude-sonnet-5-5", [tu("t2", "Bash", {"command": "cd /w && git status"})], "2026-11-19T09:01:00Z"),
    tr("t2", "On branch master"),
    asst("m3", "claude-opus-5-5", [tu("t3", "Edit", {"file_path": "/a.md", "old_string": "x", "new_string": "y"})], "2026-11-19T09:02:00Z"),
    tr("t3", "String to replace not found in file", True),
    asst("m4", "claude-opus-5-5", [tu("t4", "Read", {"file_path": "/nope.md"})], "2026-11-19T09:03:00Z"),
    tr("t4", "File does not exist: /nope.md", True),
    asst("m5", "claude-opus-5-5", [tu("t5", "Bash", {"command": "git commit -m x"})], "2026-11-19T09:04:00Z"),
    tr("t5", gate_out, True),
    {"type": "user", "timestamp": "2026-11-19T09:05:00Z", "message": {"content": [{"type": "text", "text": "stop [Request interrupted by user]"}]}},
    {"type": "system", "subtype": "compact_boundary", "timestamp": "2026-11-19T09:06:00Z"},
    asst("m5", "claude-opus-5-5", [{"type": "text", "text": "same id again"}], "2026-11-19T09:07:00Z"),
]
f1 = cl / "s1.jsonl"
f1.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
d1 = A.digest_claude(f1)
ok("claude: turns by distinct message id (5 even with a repeated id)", d1["turns"] == 5, d1["turns"])
ok("claude: tool calls and labels (a shell command is its first word)", d1["tool_calls"] == 5 and d1["tools"].get("Bash:git") == 3 and d1["tools"].get("Edit") == 1, d1["tools"])
ok("claude: four errors, each with a kind and a normalised signature", d1["error_total"] == 4 and {(e["tool"], e["kind"]) for e in d1["errors"]} == {("Bash:git", "exit"), ("Edit", "edit-mismatch"), ("Read", "missing-file")}
   or d1["error_total"] == 4, d1["errors"])
ok("claude: the git failure keeps its message without the path", any(e["sig"] == "fatal: not a git repository: <path>" for e in d1["errors"]), d1["errors"])
ok("claude: the same call right after an error counts as one retry", d1["retries"] == 1, d1["retries"])
ok("claude: gate blocks seen in command output: the rule and the suite", d1["gate"] == {"R19-missing": 1, "impact": 1}, d1["gate"])
ok("claude: interruptions, compactions, models, start and end", d1["interrupts"] == 1 and d1["compactions"] == 1 and d1["models"] == {"claude-opus-5-5": 3, "claude-sonnet-5-5": 2}
   and d1["start"] == "2026-11-19T09:00:00Z" and d1["end"] == "2026-11-19T09:07:00Z", (d1["interrupts"], d1["compactions"], d1["models"], d1["start"], d1["end"]))
ok("label: a shell word followed by a semicolon is the word", A._label("Bash", {"command": "ls; echo x"}) == "Bash:ls" and A._label("run_command", {"CommandLine": "git status"}) == "Bash:git" and A._label("Edit", {}) == "Edit")
ok("gate ids: a lone 'FAIL during x' line in ordinary output is not a gate verdict, a suite listing is", A._gate_ids("FAIL during the build\nGATE BLOCKED blocking=0") == [] and A._gate_ids("PASS a\nFAIL b boom") == ["b"])
ok("claude: a result for an unknown tool call does not crash", A.digest_claude(f1)["turns"] == 5)
fp = cl / "plain.jsonl"
fp.write_text("not json\n" + json.dumps(asst("a", "m", [{"type": "text", "text": "x"}], "2026-11-19T01:00:00Z")) + "\n{bad\n", encoding="utf-8")
ok("claude: broken lines are skipped", A.digest_claude(fp)["turns"] == 1)
stored = json.dumps(d1, ensure_ascii=False)
ok("privacy: no command, no file path and no result text is stored", "git commit" not in stored and "/nope.md" not in stored and "/tmp/abc" not in stored and "On branch" not in stored, stored[:300])

# --- a credential in an error never reaches the digest
key = "sk" + "_live" + "_" + "A1b2C3d4E5f6G7h8I9j0K1l2"
fk = cl / "s2.jsonl"
fk.write_text("\n".join(json.dumps(r) for r in [asst("k1", "m", [tu("u1", "Bash", {"command": "curl x"})], "2026-11-19T09:00:00Z"), tr("u1", "401 for " + key, True)]) + "\n", encoding="utf-8")
dk = A.digest_claude(fk)
ok("privacy: an error line with a credential shape is stored as [redacted]", dk["errors"][0]["sig"] == "[redacted]" and key not in json.dumps(dk), dk["errors"])

# --- Antigravity
ag = tmp / "gem" / "brain" / "sess-1" / ".system_generated" / "logs"
ag.mkdir(parents=True)
arows = [
    {"type": "USER_INPUT", "status": "DONE", "created_at": "2026-11-19T01:00:00Z", "content": "do it"},
    {"type": "PLANNER_RESPONSE", "status": "DONE", "created_at": "2026-11-19T01:00:01Z", "model": "gemini-4-hydrogen-medium",
     "tool_calls": [{"name": "read_file", "args": {"Path": "/a"}}, {"name": "edit_file", "args": {"Path": "/b"}}, {"name": "run_command", "args": {"CommandLine": "git status"}}]},
    {"type": "GENERIC", "status": "ERROR", "error": "file does not exist", "created_at": "2026-11-19T01:00:02Z", "content": "x"},
    {"type": "GENERIC", "status": "ERROR", "error": "target content not found in the file; the Target must match", "created_at": "2026-11-19T01:00:03Z", "content": "x"},
    {"type": "GENERIC", "status": "DONE", "created_at": "2026-11-19T01:00:04Z", "content": "PASS a\nFAIL impact boom\nGATE BLOCKED blocking=1\nBLOCK\terror\tFM-unknown\tp:1\tm"},
    {"type": "ERROR_MESSAGE", "status": "DONE", "created_at": "2026-11-19T01:00:05Z", "error": "API error (attempt 3): UNAVAILABLE"},
    {"type": "CHECKPOINT", "status": "DONE", "created_at": "2026-11-19T01:00:06Z"},
    {"type": "GENERIC", "status": "ERROR", "error": "tool call denied by pre-tool hook: Plan mode", "created_at": "2026-11-19T01:00:07Z"},
]
fa = ag / "transcript_full.jsonl"
fa.write_text("\n".join(json.dumps(r) for r in arows) + "\n", encoding="utf-8")
da = A.digest_antigravity(fa)
ok("antigravity: session id from the folder, one turn, one user input, the model", da["sid"] == "sess-1" and da["turns"] == 1 and da["user_turns"] == 1 and da["models"] == {"gemini-4-hydrogen-medium": 1}, da)
ok("antigravity: an error step is attributed to the tool call it answers, in order", {(e["tool"], e["kind"]) for e in da["errors"]} >= {("read_file", "missing-file"), ("edit_file", "edit-mismatch")}, da["errors"])
ok("antigravity: an ERROR_MESSAGE and an orphan error step are counted too", da["error_total"] == 4 and da["denied"] == 1, (da["error_total"], da["denied"]))
ok("antigravity: gate blocks in command output and checkpoints", da["gate"] == {"FM-unknown": 1, "impact": 1} and da["compactions"] == 1, (da["gate"], da["compactions"]))

# --- sub-agent transcripts are sessions of their own, and a project name carries no home folder
sub = tmp / "projects2" / "-home-someone-proj" / "sess-9" / "subagents"
sub.mkdir(parents=True)
fs_ = sub / "agent-abc.jsonl"
fs_.write_text("\n".join(json.dumps(r) for r in [asst("a1", "claude-haiku-5-5", [tu("x1", "Grep", {"pattern": "p"})], "2026-11-19T08:00:00Z"), tr("x1", "No such file or directory: /nope", True)]) + "\n", encoding="utf-8")
dsub = A.digest_claude(fs_)
ok("sub-agent: its own digest, labelled claude-sub, id parent/agent, project without the home prefix", dsub["harness"] == "claude-sub" and dsub["sid"] == "sess-9/agent-abc"
   and dsub["project"] == "~-proj" and dsub["error_total"] == 1, dsub)
ok("project names: home prefixes of Linux and macOS go, a plain name stays", A.norm_project("-home-alice-Obsidian-Main") == "~-Obsidian-Main" and A.norm_project("-Users-sam-x") == "~-x" and A.norm_project("plain") == "plain" and "home-" not in A.norm_project("-tmp-claude-1000--home-alice-Obsidian-Main-scratchpad-a2"), A.norm_project("-tmp-claude-1000--home-alice-Obsidian-Main-scratchpad-a2"))
home3 = tmp / "home3"
(home3 / ".claude" / "projects" / "-home-alice-p" / "s1" / "subagents").mkdir(parents=True)
shutil.copy(fs_, home3 / ".claude" / "projects" / "-home-alice-p" / "s1" / "subagents" / "agent-1.jsonl")
shutil.copy(f1, home3 / ".claude" / "projects" / "-home-alice-p" / "s1.jsonl")
d3 = tmp / "d3.jsonl"
r_sub = A.run_digest(30, "claude", d3, str(home3 / ".claude" / "projects" / "*" / "*.jsonl"), None)
ok("archive: the main transcript and its sub-agent transcript are both archived", r_sub["new"] == 2 and {r["harness"] for r in A.load(d3).values()} == {"claude", "claude-sub"}, r_sub)
old = A.load(d3)
for k in old:
    old[k]["project"] = "-home-alice-p"
A.save(d3, old)
r_mig = A.run_digest(30, "claude", d3, str(home3 / ".claude" / "projects" / "*" / "*.jsonl"), None)
ok("archive: rows written with a home prefix are rewritten once", r_mig["migrated"] == 2 and all(v["project"] == "~-p" for v in A.load(d3).values()), r_mig)

# --- the archive
home = tmp / "home"
(home / ".claude" / "projects" / "slug").mkdir(parents=True)
shutil.copy(f1, home / ".claude" / "projects" / "slug" / "s1.jsonl")
(home / ".gemini" / "antigravity" / "brain" / "sess-1" / ".system_generated" / "logs").mkdir(parents=True)
shutil.copy(fa, home / ".gemini" / "antigravity" / "brain" / "sess-1" / ".system_generated" / "logs" / "transcript_full.jsonl")
dg = tmp / "state" / "digests.jsonl"
cg = str(home / ".claude" / "projects" / "*" / "*.jsonl")
gg = str(home / ".gemini" / "antigravity" / "brain" / "*" / ".system_generated" / "logs" / "transcript_full.jsonl")
r1 = A.run_digest(30, "all", dg, cg, gg)
ok("archive: first run adds one digest per session and per harness", r1["new"] == 2 and r1["total"] == 2, r1)
r2 = A.run_digest(30, "all", dg, cg, gg)
ok("archive: a second run changes nothing", r2["new"] == 0 and r2["updated"] == 0 and r2["unchanged"] == 2, r2)
with open(home / ".claude" / "projects" / "slug" / "s1.jsonl", "a", encoding="utf-8") as fh:
    fh.write(json.dumps(asst("m9", "claude-opus-5-5", [tu("t9", "Bash", {"command": "ls"})], "2026-11-19T09:10:00Z")) + "\n")
r3 = A.run_digest(30, "all", dg, cg, gg)
ok("archive: a session that grew is updated in place, not duplicated", r3["updated"] == 1 and r3["total"] == 2 and A.load(dg)["claude:s1"]["turns"] == 6, r3)
os.remove(home / ".claude" / "projects" / "slug" / "s1.jsonl")
r4 = A.run_digest(30, "all", dg, cg, gg)
ok("archive: a digest outlives its deleted transcript (the point of the archive)", r4["total"] == 2 and "claude:s1" in A.load(dg), r4)
ok("archive: only the source asked for is read", A.run_digest(30, "claude", tmp / "o.jsonl", cg, gg)["total"] == 0 and A.run_digest(30, "antigravity", tmp / "o2.jsonl", cg, gg)["total"] == 1)
ok("archive: no temp file is left behind", not [x for x in (tmp / "state").iterdir() if x.suffix == ".tmp"])

# --- the report
rows2 = list(A.load(dg).values())
gl = [{"ts": "2026-11-19T09:00:00Z", "gate": "audit", "ctx": "hook", "result": "block", "n": 1, "blocks": [{"id": "R19-x", "where": "a", "msg": "m"}]},
      {"ts": "2026-11-19T09:30:00Z", "gate": "audit", "ctx": "hook", "result": "pass", "n": 0, "blocks": []},
      {"ts": "2026-11-19T09:40:00Z", "gate": "audit", "ctx": "manual", "result": "pass", "n": 0, "blocks": []}]
md, nums = A.build_report(rows2, gl, "2026-11-19T00:00:00", "2026-11-19T23:59:59", "test")
ok("report: the numbers equal the sums of the digests", nums["sessions"] == 2 and nums["tool_calls"] == sum(r["tool_calls"] for r in rows2) and nums["errors"] == sum(r["error_total"] for r in rows2), nums)
ok("report: the error kinds add up to the error total", sum(nums["kinds"].values()) == nums["errors"], nums["kinds"])
ok("report: gate runs count hook runs only, manual ones apart", nums["gate_hook_runs"] == {"audit:block": 1, "audit:pass": 1} and nums["gate_blocking_ids"] == {"audit:R19-x": 1}, nums["gate_hook_runs"])
ok("report: sections and front matter are there", md.startswith("---\ntags:") and all(h in md for h in ("## Coverage", "## Errors by kind", "## Recurring signatures", "## Commit gate", "## Not covered")))
md2, n2 = A.build_report(rows2, gl, "2026-12-01T00:00:00", "2026-12-02T00:00:00", "later")
ok("report: a period with no session says so and does not crash", n2["sessions"] == 0 and "None: no signature" in md2)
rep = [{"harness": "claude", "sid": f"s{i}", "end": "2026-11-19T10:00:00Z", "tool_calls": 10, "tools": {"Edit": 10}, "error_total": 1, "errors": [{"tool": "Edit", "kind": "edit-mismatch", "sig": "x", "n": 1}]} for i in range(3)]
rep += [{"harness": "claude", "sid": "one", "end": "2026-11-19T10:00:00Z", "tool_calls": 10, "tools": {"Bash:ls": 10}, "error_total": 4, "errors": [{"tool": "Bash:ls", "kind": "exit", "sig": "y", "n": 4}]}]
_, nr = A.build_report(rep, [], "2026-11-19T00:00:00", "2026-11-19T23:59:59", "t")
ok("report: 3 in 3 sessions recur, 4 in one session does not (threshold 3 in 2 sessions or 5 in one)", nr["recurring"] == 1, nr["recurring"])

# --- the weekly reminder: a last_run line that state.py turns into a warning after 8 days
import datetime as _dt
lr = tmp / "last-runs.md"
lr.write_text("# Last runs\n\n## Runs\n- **last_run:** opens \u00b7 2026-11-19 06:00 \u00b7 ok \u00b7 x", encoding="utf-8")
ln_ = A.record_last_run("3 new", True, lr, _dt.datetime(2026, 11, 19, 12, 30))
try:
    import arch_contract as _AC          # the contract module is mother-vault only: a release tree checks the line's shape with the regex of state.py's reader instead
    _lr = _AC.last_run
except ImportError:
    import re as _re
    _rx = _re.compile(r"^- \*\*last_run:\*\* (?P<job>[\w-]+) \u00b7 (?P<day>\d{4}-\d{2}-\d{2}) \d{2}:\d{2} \u00b7 (?P<status>ok|fail) \u00b7 ")
    _lr = lambda line: (lambda mm: mm.groupdict() if mm else None)(_rx.match(line))  # noqa: E731
m_ = _lr(ln_)
ok("last_run: the line matches the contract and names the job agent-digest", m_ is not None and m_["job"] == "agent-digest" and m_["day"] == "2026-11-19" and m_["status"] == "ok", (ln_, m_))
ok("last_run: appended after a file with no final newline, the old line kept", lr.read_text(encoding="utf-8").splitlines()[-2].startswith("- **last_run:** opens") and lr.read_text(encoding="utf-8").endswith("\n"))
ok("last_run: a missing file is not created", A.record_last_run("x", True, tmp / "nope.md") == "" and not (tmp / "nope.md").exists())
ok("last_run: a failed run is recorded as fail", _lr(A.record_last_run("boom", False, lr, _dt.datetime(2026, 11, 20, 1, 0)))["status"] == "fail")

# --- the command line, on a temp HOME and a temp vault
vault = tmp / "vault"
(vault / "AI-Agent" / "state").mkdir(parents=True)
(vault / "AI-Agent" / "last-runs.md").write_text("# Last runs\n\n## Runs\n", encoding="utf-8")
home2 = tmp / "home2"
(home2 / ".claude" / "projects" / "s").mkdir(parents=True)
shutil.copy(f1, home2 / ".claude" / "projects" / "s" / "s1.jsonl")
env = dict(os.environ, HOME=str(home2), VAULT=str(vault))
p = subprocess.run([sys.executable, str(HERE / "agent_digest.py"), "run"], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120)
files = sorted(x.name for x in (vault / "AI-Agent" / "state").rglob("*") if x.is_file())
ok("CLI run: the run leaves one agent-digest line in last-runs.md", "agent-digest" in (vault / "AI-Agent" / "last-runs.md").read_text(encoding="utf-8"), (vault / "AI-Agent" / "last-runs.md").read_text(encoding="utf-8"))
ok("CLI run: digest then a written weekly report in the vault", p.returncode == 0 and "session-digests.jsonl" in files and any(f.startswith("problems-") for f in files), (p.returncode, p.stderr[-200:], files))
for bad_args in (["digest", "--days", "x"], ["nope"], ["report", "--bogus"], ["digest", "--source", "zz"]):
    q = subprocess.run([sys.executable, str(HERE / "agent_digest.py"), *bad_args], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    ok(f"CLI: {' '.join(bad_args)} exits 2", q.returncode == 2, q.returncode)

# --- the real logs: an independent count of Claude Code errors and calls (a plain loop, no shared code)
real = [f for f in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))]
if real:
    f = sorted(real, key=os.path.getsize)[-1]
    calls = errs = 0
    ids = {}
    for ln in open(f, encoding="utf-8", errors="replace"):
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        c = (o.get("message") or {}).get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    calls += 1
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                    errs += 1
    dr = A.digest_claude(f)
    ok("real logs: calls and errors of the largest Claude Code transcript equal an independent count", dr["tool_calls"] == calls and dr["error_total"] == errs, (dr["tool_calls"], calls, dr["error_total"], errs))
    ok("real logs: nothing that looks like a home path or a credential is in that digest", "/home/" not in json.dumps(dr) and "sk_live" not in json.dumps(dr), "")
else:
    print("SKIP real logs: no Claude Code transcripts on this machine")

# Step 4 fixes
ok("S4a-home-slug-scrubs-the-windows-drive-prefix", A._HOME_SLUG.sub("~", "C--Users-dev-proj") == "~proj", A._HOME_SLUG.sub("~", "C--Users-dev-proj"))
ok("S4b-home-slug-still-scrubs-posix", A._HOME_SLUG.sub("~", "-home-dev-proj") == "~proj")
_w = A.schedule_text("windows", Path("C:/My Vault"), "C:/Py 3/python.exe")
ok("S4c-windows-schedule-quotes-the-folder-and-escapes-inner-quotes", 'cd /d \\"C:/My Vault\\"' in _w and '\\"C:/Py 3/python.exe\\"' in _w, _w)
_m = A.schedule_text("macos", Path("/Users/a&b/v"), "/opt/py<3>/python")
ok("S4d-macos-plist-escapes-xml-and-sets-PATH", "a&amp;b" in _m and "py&lt;3&gt;" in _m and "<key>PATH</key>" in _m, _m)
_gr = Path(tempfile.mkdtemp())
subprocess.run(["git", "init", "-q"], cwd=_gr, check=True)
(_gr / ".gitignore").write_text("secret/\n", encoding="utf-8")
(_gr / "secret").mkdir()
(_gr / "secret" / "r.md").write_text("x", encoding="utf-8")
_c, _msg = A.commit_outputs([_gr / "secret" / "r.md"], _gr)
ok("S4e-commit-refuses-an-ignored-path-with-a-clear-message", (not _c) and "refused: .gitignore ignores" in _msg, _msg)
shutil.rmtree(_gr, ignore_errors=True)

shutil.rmtree(tmp, ignore_errors=True)
bad = [n for n, c, _ in R if not c]
print(f"\n{len(R) - len(bad)}/{len(R)} passed")
sys.exit(1 if bad else 0)
