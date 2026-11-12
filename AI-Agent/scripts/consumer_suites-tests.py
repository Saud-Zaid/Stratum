#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for consumer_suites (C19-b stage C, AD10). Usage: consumer_suites-tests"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import consumer_suites as CS

passed = failed = 0


def ok(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name} {extra}")


MAP = """---
status: active
tags: [AD10]
created: 2026-10-24
---

# map

counters:
  skills: 24

suites:
  stem_prefix:    "scripts/"
  time_cap_seconds: 300
  prefixes:
    - "skills/|skill_args"
    - "schema/|skill_args,derive_live_arch"
  fallback: audit, skill_args
"""


def tmp_map(text):
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


p = tmp_map(MAP)

# T1: load parses frontmatter, prefixes, fallback, cap
cfg = CS.load_config(p)
ok("T1 load parses", cfg["prefixes"][0] == ("skills/", ["skill_args"])
   and cfg["fallback"] == ["audit", "skill_args"] and cfg["stem_prefix"] == "scripts/"
   and cfg["time_cap_seconds"] == 300, cfg)

# T2: stem rule maps a tool to its own suite
suites, unknown = CS.plan(["scripts/radar_reconcile.py"], cfg)
ok("T2 stem maps tool->suite", "radar_reconcile-tests" in suites and not unknown, suites)

# T3: prefix maps a skill dir change to its consumer
suites, unknown = CS.plan(["skills/new-thing/SKILL.md"], cfg)
ok("T3 prefix skill->skill_args", suites == ["skill_args"] and not unknown, suites)

# T4: multiple prefixes merge in order, no dupes
suites, unknown = CS.plan(["skills/a/x.md", "schema/y.yaml"], cfg)
ok("T4 merge order", suites == ["skill_args", "derive_live_arch"] and not unknown, suites)

# T5: unknown path triggers fallback (Q1 mandatory broad set) — the anti-silent-drift core
suites, unknown = CS.plan(["01-Projects/note.md"], cfg)
ok("T5 unknown -> fallback", unknown == ["01-Projects/note.md"] and "audit" in suites and "skill_args" in suites, suites)

# T6: fallback is mandatory — empty fallback must raise
bad = tmp_map(MAP.replace("  fallback: audit, skill_args", "  fallback:"))
try:
    CS.load_config(bad)
    ok("T6 empty fallback raises", False, "no error raised")
except ValueError:
    ok("T6 empty fallback raises", True)
os.remove(bad)

# T7: missing suites block raises (gate blocks, never proceeds blindly)
try:
    CS.load_config(tmp_map("---\nstatus: active\n---\n\n# no suites\n"))
    ok("T7 missing suites raises", False)
except ValueError:
    ok("T7 missing suites raises", True)

# T8: stem rule never matches test files themselves (no self-loop)
suites, unknown = CS.plan(["scripts/skill_args-tests.py"], cfg)
ok("T8 no self-loop", "skill_args-tests-tests" not in suites, suites)

# T9: the real vault map loads and has a non-empty fallback
cfg2 = CS.load_config()
ok("T9 real map loads", bool(cfg2["fallback"]) and len(cfg2["prefixes"]) >= 3, cfg2["fallback"])

# T10: help exits 0 (archmap convention, C17)
import subprocess
r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "consumer_suites.py"), "-h"],
                   capture_output=True, text=True)
ok("T10 help exit=0", r.returncode == 0, r.returncode)

# T11-T20 (T-02e, U-42): --staged / --run in a throwaway repo (never the real index)
import io
import contextlib
import shutil

def _git(root, *a):
    subprocess.run(["git", "-C", root, "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True)

def _repo():
    root = tempfile.mkdtemp(prefix="cs-run-")
    _git(root, "init", "-q")
    os.makedirs(os.path.join(root, "AI-Agent", "scripts"))
    return root

def _w(root, rel, text):
    f = os.path.join(root, rel)
    os.makedirs(os.path.dirname(f), exist_ok=True)
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(text)

CFG = {"prefixes": [("AI-Agent/scripts/audit.py", ["audit"])], "fallback": ["audit"], "stem_prefix": "AI-Agent/scripts/", "time_cap_seconds": 60}
R1 = _repo()
try:
    _w(R1, "AI-Agent/scripts/foo.py", "x = 1\n")
    _w(R1, "AI-Agent/scripts/foo-tests.py", "print('ok')\n")
    _w(R1, "AI-Agent/scripts/old.py", "y = 1\n")
    _git(R1, "add", "-A"); _git(R1, "commit", "-q", "-m", "base")
    _w(R1, "AI-Agent/scripts/foo.py", "x = 2\n")
    _w(R1, "AI-Agent/scripts/new.py", "z = 1\n")
    os.remove(os.path.join(R1, "AI-Agent/scripts/old.py"))
    _git(R1, "add", "-A")
    ok("T11 staged_paths = added/modified, not deleted", sorted(CS.staged_paths(R1)) == ["AI-Agent/scripts/foo.py", "AI-Agent/scripts/new.py"], CS.staged_paths(R1))
    rc, lines = CS.run_plan(["AI-Agent/scripts/foo.py"], CFG, root=R1)
    ok("T12 green suite -> rc 0 and PASS line", rc == 0 and lines == ["PASS foo-tests "], (rc, lines))
    _w(R1, "AI-Agent/scripts/foo-tests.py", "import sys\nprint('boom')\nsys.exit(1)\n")
    rc, lines = CS.run_plan(["AI-Agent/scripts/foo.py"], CFG, root=R1)
    ok("T13 failing suite -> rc 1 and FAIL line with its output", rc == 1 and lines[-1].startswith("FAIL foo-tests boom"), (rc, lines))
    _w(R1, "AI-Agent/scripts/foo-tests.py", "print('ok')\n")
    _w(R1, "AI-Agent/scripts/broken.py", "def (:\n")
    rc, lines = CS.run_plan(["AI-Agent/scripts/broken.py"], CFG, root=R1)
    ok("T14 syntax error -> rc 1 COMPILE FAIL", rc == 1 and lines[0].startswith("COMPILE FAIL AI-Agent/scripts/broken.py"), (rc, lines))
    rc, lines = CS.run_plan(["AI-Agent/scripts/audit.py"], CFG, root=R1)
    ok("T15 mapped suite without a file -> rc 1 MISSING", rc == 1 and lines[-1].startswith("MISSING audit"), (rc, lines))
    rc, lines = CS.run_plan(["AI-Agent/scripts/nostem.py"], CFG, root=R1)
    ok("T16 stem-derived suite without a file -> SKIP, rc 0", rc == 0 and lines == ["SKIP nostem-tests (no suite file)"], (rc, lines))
    _w(R1, "AI-Agent/scripts/foo-tests.py", "import sys\nprint('not here')\nsys.exit(77)\n")
    rc, lines = CS.run_plan(["AI-Agent/scripts/foo.py"], CFG, root=R1)
    ok("T16b suite exiting 77 -> SKIP, rc 0 (not applicable in this tree)", rc == 0 and lines == ["SKIP foo-tests (exit 77: not applicable here)"], (rc, lines))
    _w(R1, "AI-Agent/scripts/foo-tests.py", "print('ok')\n")
    rc, lines = CS.run_plan(["AI-Agent/scripts/foo.py"], dict(CFG, time_cap_seconds=0), root=R1)
    ok("T17 exhausted time cap -> TIMEOUT rc 1", rc == 1 and lines[-1].startswith("TIMEOUT foo-tests"), (rc, lines))
    _w(R1, "AI-Agent/scripts/audit.py", "a = 1\n")
    _w(R1, "AI-Agent/scripts/audit-tests.py", "print('once')\n")
    rc, lines = CS.run_plan(["AI-Agent/scripts/audit.py"], CFG, root=R1)
    ok("T17b one file named by the stem rule and the map runs once", rc == 0 and lines == ["PASS audit-tests "], (rc, lines))
finally:
    shutil.rmtree(R1, ignore_errors=True)

_err, _out = io.StringIO(), io.StringIO()
with contextlib.redirect_stderr(_err), contextlib.redirect_stdout(_out):
    rc_bogus = CS.main(["--bogus"])
ok("T18 unknown option -> exit 2 on stderr", rc_bogus == 2 and "--bogus" in _err.getvalue() and _out.getvalue() == "", (rc_bogus, _err.getvalue()))
_out = io.StringIO()
_orig_staged = CS.staged_paths
CS.staged_paths = lambda root=None: []
try:
    with contextlib.redirect_stdout(_out):
        rc_empty = CS.main(["--staged", "--run"])
finally:
    CS.staged_paths = _orig_staged
ok("T19 nothing staged -> rc 0 and silent (no docstring dump)", rc_empty == 0 and _out.getvalue() == "", _out.getvalue()[:60])
_ran = []
_orig_run = CS.run_plan
CS.run_plan = lambda paths, cfg, root=None, python=None: (_ran.append(paths) or (0, []))
CS.staged_paths = lambda root=None: ["AI-Agent/scripts/state.py"]
try:
    with contextlib.redirect_stdout(io.StringIO()):
        rc_run = CS.main(["--staged", "--run"])
finally:
    CS.run_plan, CS.staged_paths = _orig_run, _orig_staged
ok("T20 --staged --run really calls run_plan with the staged paths", rc_run == 0 and _ran == [["AI-Agent/scripts/state.py"]], _ran)

os.remove(p)
print(f"consumer_suites-tests: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
