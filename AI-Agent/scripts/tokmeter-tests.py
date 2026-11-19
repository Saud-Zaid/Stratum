# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for tokmeter (AD13 A1): command classification, Goose and Claude Code
parsing against synthetic stores with known answers, usage totals, shares, bad
arguments, an unreadable store, and a negative control (a mutated fixture must change
the answer). Usage: tokmeter-tests"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tokmeter as T

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


# T1-T7: classification of shell commands
C = T.classify_command
ok("T1-plain", C("cat a.md") == "cat", C("cat a.md"))
ok("T2-cd-wrapper", C('cd "/x y" && sed -n 1,5p f') == "sed", C('cd "/x y" && sed -n 1,5p f'))
ok("T3-env-assign", C("FOO=1 BAR=2 grep x f") == "grep", C("FOO=1 BAR=2 grep x f"))
ok("T4-vault-python", C("AI-Agent/vault-python AI-Agent/scripts/state.py") == "state.py")
ok("T5-python-inline", C("python3 - <<'EOF'\nprint(1)\nEOF") == "python-inline", C("python3 - <<'EOF'"))
ok("T6-empty-and-nonstr", C("") == "?" and C(None) == "?")
ok("T7-chained-cd", C("cd a && cd b && head f") == "head", C("cd a && cd b && head f"))

tmp = Path(tempfile.mkdtemp(prefix="tokmeter-"))

# Goose fixture with known sizes
gdb = tmp / "sessions.db"
con = sqlite3.connect(gdb)
con.execute("create table sessions (id text, created_at text, accumulated_input_tokens int,"
            " accumulated_output_tokens int, accumulated_cache_read_tokens int, accumulated_cache_write_tokens int)")
con.execute("create table messages (id integer primary key autoincrement, session_id text, content_json text)")
con.execute("insert into sessions values ('s1', datetime('now'), 1000, 50, 400, 0)")
con.execute("insert into sessions values ('old', '2001-01-01 00:00:00', 9, 9, 9, 9)")


def req(i, name, cmd):
    return json.dumps([{"type": "toolRequest", "id": i, "toolCall": {"status": "success",
                        "value": {"name": name, "arguments": {"command": cmd}}}}])


def resp(i, text):
    return json.dumps([{"type": "toolResponse", "id": i, "toolResult": {"status": "success",
                        "value": {"content": [{"type": "text", "text": text}]}}}])


for i, name, cmd, text in [("a", "shell", "cat f", "x" * 300), ("b", "shell", "grep q f", "y" * 100),
                           ("c", "tree", None, "z" * 100)]:
    con.execute("insert into messages (session_id, content_json) values ('s1', ?)", (req(i, name, cmd),))
    con.execute("insert into messages (session_id, content_json) values ('s1', ?)", (resp(i, text),))
con.commit()
con.close()

m = T.measure(T.iter_goose(gdb, time.time() - 86400))
ok("T8-goose-usage", m["usage"]["goose"]["input"] == 1000 and m["usage"]["goose"]["cache_read"] == 400, m["usage"])
ok("T9-goose-old-excluded", m["usage"]["goose"]["output"] == 50, m["usage"])
ok("T10-tool-sizes", m["tools"]["shell"]["size"] == 400 and m["tools"]["tree"]["size"] == 100, m["tools"])
ok("T11-share", abs(m["tools"]["shell"]["share"] - 0.8) < 1e-9, m["tools"]["shell"])
ok("T12-cmd-share", abs(m["shell_commands"]["cat"]["share_of_shell"] - 0.75) < 1e-9, m["shell_commands"])
ok("T13-read-share", abs(m["reads_share_of_all"] - 0.6) < 1e-9, m["reads_share_of_all"])
m_all = T.measure(T.iter_goose(gdb, 0))
ok("T14-since-zero-includes-old", m_all["usage"]["goose"]["output"] == 59, m_all["usage"])

# Claude Code fixture
proj = tmp / "projects" / "p1"
proj.mkdir(parents=True)
lines = [
    {"type": "assistant", "uuid": "u1", "message": {"id": "m1", "usage": {"input_tokens": 2, "cache_read_input_tokens": 100,
     "cache_creation_input_tokens": 10, "output_tokens": 5}, "content": [
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "cd x && cat y"}}]}},
    {"type": "assistant", "uuid": "u2", "message": {"id": "m1", "usage": {"input_tokens": 2, "cache_read_input_tokens": 100,
     "cache_creation_input_tokens": 10, "output_tokens": 5}, "content": []}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "a" * 50}]}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "b" * 7}]}]}},
]
(proj / "s.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n", encoding="utf-8")
mc = T.measure(T.iter_claude(tmp / "projects"))
ok("T15-claude-usage-dedup", mc["usage"]["claude"]["calls"] == 1 and mc["usage"]["claude"]["cache_read"] == 100, mc["usage"])
ok("T16-claude-tool-and-cmd", mc["tools"]["Bash"]["size"] == 50 and mc["shell_commands"]["cat"]["calls"] == 1, mc)
ok("T17-list-content-parsed-as-unknown-tool", mc["tools"].get("?", {}).get("size") == 7, mc["tools"])
ok("T18-bad-line-skipped", mc["sessions"] == 1 and mc["usage"]["claude"]["calls"] == 1, mc["usage"])
ok("T19-missing-root-empty", T.measure(T.iter_claude(tmp / "nope"))["sessions"] == 0)
ok("T20-missing-db-empty", T.measure(T.iter_goose(tmp / "none.db"))["sessions"] == 0)

# Negative control: change the fixture, the answer must change
con = sqlite3.connect(gdb)
con.execute("update messages set content_json = ? where id = 2", (resp("a", "x" * 301),))
con.commit()
con.close()
m2 = T.measure(T.iter_goose(gdb, time.time() - 86400))
ok("T21-negative-control", m2["tools"]["shell"]["size"] == 401 and m2["tools"]["shell"]["size"] != m["tools"]["shell"]["size"],
   m2["tools"]["shell"])

# KPIs: exact repeats and read excess over the cap
rg = tmp / "rep.db"
con = sqlite3.connect(rg)
con.execute("create table sessions (id text, created_at text, accumulated_input_tokens int,"
            " accumulated_output_tokens int, accumulated_cache_read_tokens int, accumulated_cache_write_tokens int)")
con.execute("create table messages (id integer primary key autoincrement, session_id text, content_json text)")
con.execute("insert into sessions values ('r1', datetime('now'), 0, 0, 0, 0)")
for i, text in [("a", "q" * 1000), ("b", "q" * 1000), ("c", "w" * 9000), ("d", "e" * 50), ("e", "e" * 50)]:
    con.execute("insert into messages (session_id, content_json) values ('r1', ?)", (req(i, "shell", "cat f%s" % i),))
    con.execute("insert into messages (session_id, content_json) values ('r1', ?)", (resp(i, text),))
con.commit()
con.close()
mr = T.measure(T.iter_goose(rg, 0))
ok("T29-repeat-counts-second-copy-only", mr["exact_repeats"]["by_tool"] == {"shell": 1000}, mr["exact_repeats"])
ok("T30-small-repeats-ignored", mr["exact_repeats"]["share_of_all"] == round(1000 / 11100, 4), mr["exact_repeats"])
ok("T31-read-excess", mr["read_excess_over_cap"]["share_of_all"] == round((9000 - T.READ_CAP) / 11100, 4), mr["read_excess_over_cap"])

# CLI: exit codes, bad args, output file
env = {**os.environ, "STRATUM_SESSION_DB": str(gdb), "STRATUM_CLAUDE_PROJECTS": str(tmp / "projects")}


def cli(*a):
    return subprocess.run([sys.executable, str(Path(__file__).parent / "tokmeter.py"), *a],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


out_json = tmp / "out.json"
r = cli("--json", str(out_json), "--top", "2")
ok("T22-cli-ok", r.returncode == 0 and r.stdout.startswith("tokmeter unit=chars"), (r.returncode, r.stdout[:80], r.stderr[:80]))
ok("T23-json-written", json.loads(out_json.read_text(encoding="utf-8"))["unit"] == "chars")
ok("T24-top-limits-rows", r.stdout.count("\ntool ") <= 2, r.stdout)
r = cli("--bogus")
ok("T25-bad-flag-exit2", r.returncode == 2 and "bad argument" in r.stderr, (r.returncode, r.stderr))
r = cli("--source", "nope")
ok("T26-bad-source-exit2", r.returncode == 2, r.returncode)
r = cli("--days", "x")
ok("T27-bad-number-exit2", r.returncode == 2, r.returncode)
r = cli("--source", "goose", "--json", str(tmp / "no" / "dir" / "o.json"))
ok("T28-json-parent-created", r.returncode == 0 and (tmp / "no" / "dir" / "o.json").exists(), r.stderr)

# loop trigger (AD13 C8): runs of 3+ identical consecutive calls, failing runs, repeat size; near-misses must not count
def _call(i, cmd, res, err=False):
    return [{"type": "assistant", "uuid": f"a{i}", "message": {"id": f"mm{i}", "content": [
        {"type": "tool_use", "id": f"c{i}", "name": "Bash", "input": {"command": cmd}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"c{i}", "content": res, "is_error": err}]}}]


lp = tmp / "projects" / "loop"
lp.mkdir(parents=True)
seq = []
for i in range(3):
    seq += _call(i, "make test", "FAIL " * 10, True)        # a failing run of 3
seq += _call(3, "ls", "ok")
seq += _call(4, "git status", "a") + _call(5, "git status", "a")      # only 2: not a run
seq += _call(6, "ls", "ok") + _call(7, "git status", "a") + _call(8, "ls", "ok") + _call(9, "git status", "a")   # alternating: not consecutive
for i in range(10, 14):
    seq += _call(i, "echo hi", "hi")                        # a succeeding run of 4
seq += _call(14, "echo hi ", "hi") + _call(15, "echo  hi", "hi")   # different arguments: no run
(lp / "l.jsonl").write_text("\n".join(json.dumps(x) for x in seq), encoding="utf-8")
ml = T.measure(T.iter_claude(tmp / "projects" / ".." / "projects"))["loops"]["claude"]
ok("T30-loops-two-runs-found", ml["runs"] == 2 and ml["failing_runs"] == 1, ml)
ok("T31-loop-repeat-calls-counted", ml["repeat_calls"] == 2 + 3, ml)
ok("T32-loop-repeat-size-is-result-size", ml["repeat_size"] == 2 * len("FAIL " * 10) + 3 * 2, ml)
ok("T33-negative-control-near-misses-not-counted", ml["runs"] != 5, ml)
ok("T34-loop-summary-line", "loops claude:" in T.summarize(T.measure(T.iter_claude(tmp / "projects"))))

# Fable review: a subagent's transcript lives in <project>/<session>/subagents/agent-*.jsonl and carries its own usage;
# the */*.jsonl glob never read it, so every delegated token was missing from the "exact" totals
sub_root = tmp / "projects2"
(sub_root / "p1" / "S1" / "subagents").mkdir(parents=True)
(sub_root / "p1" / "S1.jsonl").write_text("\n".join(json.dumps(x) for x in lines[:3]), encoding="utf-8")
ms0 = T.measure(T.iter_claude(sub_root))
agent = [
    {"type": "assistant", "uuid": "a1", "isSidechain": True, "message": {"id": "m9", "usage": {"input_tokens": 3, "cache_read_input_tokens": 40,
     "cache_creation_input_tokens": 1, "output_tokens": 7}, "content": [{"type": "tool_use", "id": "r1", "name": "Read", "input": {"file_path": "f"}}]}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "r1", "content": "c" * 20}]}},
]
(sub_root / "p1" / "S1" / "subagents" / "agent-x.jsonl").write_text("\n".join(json.dumps(x) for x in agent), encoding="utf-8")
ms = T.measure(T.iter_claude(sub_root))
ok("T35-control-parent-only-totals", ms0["usage"]["claude"]["output"] == 5 and ms0["sessions"] == 1, ms0["usage"])
ok("T36-subagent-usage-is-counted", ms["usage"]["claude"] == {"input": 5, "cache_read": 140, "cache_write": 11, "output": 12, "calls": 2}, ms["usage"])
ok("T37-subagent-tool-results-are-counted", ms["tools"].get("Read", {}).get("size") == 20 and ms["tools"]["Bash"]["size"] == 50, ms["tools"])
ok("T38-subagent-belongs-to-its-parent-session", ms["sessions"] == 1, ms["sessions"])

# AD13 D4: Antigravity transcripts. A PLANNER_RESPONSE carries usage and tool_calls; the GENERIC rows after it are the
# results in call order; a GENERIC row with no pending call is a plain step, not a tool result.
brain = tmp / "brain"
logs = brain / "SESS1" / ".system_generated" / "logs"
logs.mkdir(parents=True)
big = "x" * 9000


def _planner(i, inp, cr, out, calls):
    return {"step_index": i, "type": "PLANNER_RESPONSE", "input_tokens": inp, "cache_read_tokens": cr, "output_tokens": out,
            "tool_calls": calls}


ag_rows = [
    {"step_index": 0, "type": "USER_INPUT", "content": "task"},
    _planner(1, 100, 0, 10, [{"name": "run_command", "args": {"CommandLine": "cat a.md"}},
                             {"name": "read_file", "args": {"Path": "/v/n.md"}},
                             {"name": "grep_search", "args": {"Query": "x"}}]),
    {"step_index": 2, "type": "GENERIC", "content": "r" * 40},
    {"step_index": 3, "type": "GENERIC", "content": big},
    {"step_index": 4, "type": "GENERIC", "content": "g" * 5, "error": "boom"},
    {"step_index": 5, "type": "GENERIC", "content": "plain step, no pending call"},
    _planner(6, 50, 100, 7, [{"name": "run_command", "args": {"CommandLine": "cat a.md"}}]),
    {"step_index": 7, "type": "ERROR_MESSAGE", "content": "denied"},
]
(logs / "transcript_full.jsonl").write_text("\n".join(json.dumps(x) for x in ag_rows) + "\nnot json\n", encoding="utf-8")
ma = T.measure(T.iter_antigravity(brain))
ok("T39-antigravity-usage-totals", ma["usage"]["antigravity"] == {"input": 150, "cache_read": 100, "cache_write": 0, "output": 17, "calls": 2}, ma["usage"])
ok("T40-antigravity-results-pair-in-call-order",
   ma["tools"]["run_command"]["calls"] == 2 and ma["tools"]["run_command"]["size"] == 40 + len("denied")
   and ma["tools"]["read_file"]["size"] == 9000 and ma["tools"]["grep_search"]["size"] == 5, ma["tools"])
ok("T41-antigravity-plain-step-is-not-a-result", ma["result_total"] == 40 + 9000 + 5 + len("denied"), ma["result_total"])
ok("T42-antigravity-shell-class-and-reads",
   ma["shell_commands"]["cat"]["calls"] == 2 and ma["read_excess_over_cap"]["share_of_all"] == round((9000 - T.READ_CAP) / ma["result_total"], 4),
   (ma["shell_commands"], ma["read_excess_over_cap"]))
ok("T43-antigravity-session-and-malformed-line", ma["sessions"] == 1)
ok("T44-antigravity-loop-sequence-counts-calls", ma["loops"]["antigravity"]["calls"] == 4, ma["loops"])
ok("T45-antigravity-since-filter", T.measure(T.iter_antigravity(brain, since=time.time() + 3600))["sessions"] == 0)
ok("T46-antigravity-missing-root-is-empty", T.measure(T.iter_antigravity(tmp / "nothing"))["sessions"] == 0)
ag_rows[2]["content"] = "r" * 41          # negative control: one more character changes the answer
(logs / "transcript_full.jsonl").write_text("\n".join(json.dumps(x) for x in ag_rows), encoding="utf-8")
ok("T47-antigravity-negative-control", T.measure(T.iter_antigravity(brain))["tools"]["run_command"]["size"] == 41 + len("denied"))
env["STRATUM_ANTIGRAVITY_BRAIN"] = str(brain)
r = cli("--source", "antigravity", "--json", str(tmp / "ag.json"))
ok("T48-cli-antigravity", r.returncode == 0 and "usage antigravity: calls=2" in r.stdout, (r.returncode, r.stdout[:120], r.stderr[:80]))
r = cli("--source", "all", "--json", str(tmp / "all.json"))
ok("T49-all-excludes-antigravity-so-old-baselines-hold", "usage antigravity" not in r.stdout, r.stdout[:200])

F, P = sum(1 for _, c, _ in R if not c), sum(1 for _, c, _ in R if c)
print(f"TOKMETER-TESTS {P}/{len(R)}")
for name, c, got in R:
    if not c:
        print(f"FAIL {name} :: {got}")
sys.exit(1 if F else 0)
