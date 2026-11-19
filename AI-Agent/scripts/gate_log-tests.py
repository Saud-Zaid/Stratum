#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""gate_log-tests.py - AD13 G1: the commit-gate run log, on its own and wired into audit and consumer_suites."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REAL = HERE.parent.parent
sys.path.insert(0, str(HERE))
import gate_log as G  # noqa: E402
import consumer_suites as CS  # noqa: E402

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {'' if cond else got}".rstrip())


d = Path(tempfile.mkdtemp(prefix="gatelog-"))
p = d / "state" / "gate-runs.jsonl"
os.environ.pop("GIT_INDEX_FILE", None)
os.environ.pop("GATE_LOG", None)      # the gate runs this suite with GATE_LOG=off; the tests below need the log on
ok("a pass is one line with no blocks", G.record("audit", [], path=p) and G.read(p)[-1]["result"] == "pass" and G.read(p)[-1]["blocks"] == [], G.read(p))
ok("a block carries its ids, places and messages", G.record("audit", [("R19-x", "a.md:3", "m" * 400), {"id": "SECRET-leak-2", "where": "b.md:1", "msg": "leak"}], path=p)
   and G.read(p)[-1]["result"] == "block" and G.read(p)[-1]["n"] == 2 and len(G.read(p)[-1]["blocks"][0]["msg"]) == 160 and G.read(p)[-1]["blocks"][1]["id"] == "SECRET-leak-2", G.read(p)[-1])
ok("outside a git hook the run is manual", G.read(p)[-1]["ctx"] == "manual")
os.environ["GIT_INDEX_FILE"] = "/x/index"
G.record("suites", [("vault_mv-tests", "FAIL", "boom")], path=p)
ok("inside a git hook (GIT_INDEX_FILE set) the run is a hook run", G.read(p)[-1]["ctx"] == "hook" and G.read(p)[-1]["gate"] == "suites")
os.environ.pop("GIT_INDEX_FILE", None)
G.record("audit", [("R19-x", "a.md:3", "m")], ctx="hook", path=p)
G.record("audit", [], ctx="hook", path=p)
s = G.summarize(G.read(p))
ok("summary counts hook runs only and ranks blocking ids", s["hook_runs"] == {"audit:block": 1, "audit:pass": 1, "suites:block": 1} and s["manual_runs"] == 2
   and list(s["blocking_ids"])[0] in ("audit:R19-x", "suites:vault_mv-tests"), s)
ok("summary honours a since bound", G.summarize(G.read(p), since="9999")["hook_runs"] == {})
barrier = d / "barrier"
barrier.write_text("a file where a folder is needed", encoding="utf-8")   # unwritable on every system and for every user, root included
okw = G.record("audit", [], path=barrier / "sub" / "x.jsonl")
ok("a path that cannot be written is swallowed and reported as False", okw is False, okw)
big = d / "big.jsonl"
big.write_text("".join(json.dumps({"ts": f"2026-01-01T00:00:{i % 60:02d}Z", "gate": "audit", "ctx": "hook", "result": "pass", "n": 0, "blocks": [], "pad": "x" * (150 + i % 53)}) + "\n" for i in range(30000)), encoding="utf-8")      # uneven lines: the middle of the file falls inside one
_raw = big.read_bytes()
big.write_bytes(b" " * 7 + _raw)      # seven spaces ahead of the first line: the lines move by 7 bytes and the middle of the file by 3 or 4, so it falls inside a line
before = big.stat().st_size
G.record("audit", [], path=big)
ok("a log over 5 MB is cut to whole lines, newest kept", before > G.MAX_BYTES and big.stat().st_size < before * 0.6 and all(json.loads(l) for l in big.read_text(encoding="utf-8").splitlines())
   and G.read(big)[-1]["n"] == 0, (before, big.stat().st_size))
(d / "bad.jsonl").write_text('not json\n{"a": 1}\n', encoding="utf-8")
ok("unreadable lines are skipped", G.read(d / "bad.jsonl") == [{"a": 1}])

# GATE_LOG=off: nothing is written, and run_plan hands it to the suites it runs
os.environ["GATE_LOG"] = "off"
ok("GATE_LOG=off writes nothing", G.record("audit", [("x", "y", "z")], path=d / "off.jsonl") is False and not (d / "off.jsonl").exists())
os.environ.pop("GATE_LOG", None)
fake = Path(tempfile.mkdtemp(prefix="gatelog-fake-"))
(fake / "AI-Agent" / "scripts").mkdir(parents=True)
(fake / "AI-Agent" / "scripts" / "zz-tests.py").write_text("import os, sys\nsys.exit(0 if os.environ.get('GATE_LOG') == 'off' else 1)\n", encoding="utf-8")
(fake / "AI-Agent" / "scripts" / "zz.py").write_text("x = 1\n", encoding="utf-8")
rc_f, lines_f = CS.run_plan(["AI-Agent/scripts/zz.py"], {"stem_prefix": "AI-Agent/scripts/", "prefixes": [], "fallback": [], "time_cap_seconds": 60}, root=str(fake))
ok("run_plan gives the suites it runs GATE_LOG=off", rc_f == 0 and any(x.startswith("PASS zz-tests") for x in lines_f), (rc_f, lines_f))
shutil.rmtree(fake, ignore_errors=True)

# consumer_suites main, staged and run: the run is logged as a suites run (planner and runner replaced, the log goes to a temp vault)
sv = Path(tempfile.mkdtemp(prefix="gatelog-suites-"))
_old = (CS.staged_paths, CS.load_config, CS.run_plan, os.environ.get("VAULT"))
CS.staged_paths, CS.load_config, CS.run_plan = (lambda root=None: ["AI-Agent/scripts/x.py"]), (lambda path=None: {"time_cap_seconds": 1}), (lambda paths, cfg, root=None, python=None: (1, ["FAIL x-tests boom"]))
os.environ["VAULT"] = str(sv)
try:
    rc = CS.main(["--staged", "--run"])
    CS.run_plan = lambda paths, cfg, root=None, python=None: (0, ["PASS x-tests "])
    rc2 = CS.main(["--staged", "--run"])
    sl = G.read(sv / "AI-Agent" / "state" / "gate-runs.jsonl")
    ok("consumer_suites --staged --run logs a failing run with the suite name, then a passing run", rc == 1 and rc2 == 0 and [x["result"] for x in sl] == ["block", "pass"]
       and sl[0]["gate"] == "suites" and sl[0]["blocks"][0]["id"] == "x-tests", sl)
finally:
    CS.staged_paths, CS.load_config, CS.run_plan = _old[:3]
    if _old[3] is None:
        os.environ.pop("VAULT", None)
    else:
        os.environ["VAULT"] = _old[3]
    shutil.rmtree(sv, ignore_errors=True)

# consumer_suites: the failing lines of a run become ids
lines = ["PASS a-tests ", "FAIL vault_mv-tests ValueError: boom", "COMPILE FAIL AI-Agent/scripts/x.py: invalid syntax", "MISSING zed (the map names a suite with no file)", "TIMEOUT slow (time_cap_seconds=300 exhausted)", "SKIP q (no suite file)"]
f = CS.failed_suites(lines)
ok("failed_suites reads FAIL, COMPILE FAIL, MISSING and TIMEOUT and ignores PASS and SKIP", [x[0] for x in f] == ["vault_mv-tests", "compile", "zed", "slow"] and f[0][2].startswith("ValueError"), f)


def tmp_vault(notes):
    root = Path(tempfile.mkdtemp(prefix="gatelog-vault-"))
    (root / "AI-Agent" / "schema").mkdir(parents=True)
    (root / "AI-Agent" / "config").mkdir()
    shutil.copy(REAL / "AI-Agent" / "gate_baseline.json", root / "AI-Agent" / "gate_baseline.json")
    shutil.copy(REAL / "AI-Agent" / "schema" / "frontmatter.yaml", root / "AI-Agent" / "schema" / "frontmatter.yaml")
    for n, b in notes.items():
        f = root / n
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(b, encoding="utf-8")
    return root


def audit(root, env_extra=None, *flags):
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_INDEX_FILE", "GATE_LOG")}
    env.update(VAULT=str(root), **(env_extra or {}))
    r = subprocess.run([sys.executable, str(HERE / "audit.py"), "--no-cache", "--ratchet", "--check", "secrets", *flags], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=180)
    return r


hd = "---\ntags: [x]\ncreated: 2026-11-01\narea: '[[n]]'\n---\n# T\n\n"
key = "sk" + "_live" + "_" + "A1b2C3d4E5f6G7h8I9j0K1l2"
clean = tmp_vault({"03-Resources/a.md": hd + "nothing\n"})
leak = tmp_vault({"03-Resources/a.md": hd + "key " + key + "\n"})
r1 = audit(clean)
l1 = G.read(clean / "AI-Agent" / "state" / "gate-runs.jsonl")
ok("audit --ratchet on a clean tree logs one passing manual run", r1.returncode == 0 and len(l1) == 1 and l1[0]["gate"] == "audit" and l1[0]["result"] == "pass" and l1[0]["ctx"] == "manual", (r1.returncode, l1))
r2 = audit(leak)
l2 = G.read(leak / "AI-Agent" / "state" / "gate-runs.jsonl")
ok("audit --ratchet on a leak logs the blocking rule and path, and still exits 1", r2.returncode == 1 and len(l2) == 1 and l2[0]["result"] == "block" and l2[0]["blocks"][0]["id"].startswith("SECRET-leak")
   and "a.md" in l2[0]["blocks"][0]["where"], (r2.returncode, l2))
r3 = audit(leak, {"GIT_INDEX_FILE": "/x"})
ok("inside a hook the audit run is logged as a hook run", G.read(leak / "AI-Agent" / "state" / "gate-runs.jsonl")[-1]["ctx"] == "hook", r3.returncode)
state = leak / "AI-Agent" / "state"
shutil.rmtree(state)
state.write_text("a file where the folder should be", encoding="utf-8")        # the log cannot be created
r4 = audit(leak)
ok("a log that cannot be written never changes the verdict (exit 1 stays 1, GATE BLOCKED still printed)", r4.returncode == 1 and "GATE BLOCKED" in r4.stdout, (r4.returncode, r4.stdout[-200:]))
r5 = audit(clean, None, "--path", "03-Resources/a.md")
ok("the audit still passes on a clean tree after the change (exit 0, GATE CLEAR)", r5.returncode == 0 and "GATE CLEAR" in r5.stdout, (r5.returncode, r5.stdout[-200:]))
ok("the real vault ignores the log file in git", subprocess.run(["git", "-C", str(REAL), "check-ignore", "-q", "AI-Agent/state/gate-runs.jsonl"]).returncode == 0)

for x in (d, clean, leak):
    shutil.rmtree(x, ignore_errors=True)
bad = [n for n, c, _ in R if not c]
print(f"\n{len(R) - len(bad)}/{len(R)} passed")
sys.exit(1 if bad else 0)
