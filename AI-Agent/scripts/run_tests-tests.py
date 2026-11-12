# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Tests for run_tests.py: the plan comes from test-classification.yaml, lanes run in order, every outcome is reported,
and the exit code is 0 only when every selected test passed. All work happens in a temporary vault.
Usage: AI-Agent/vault-python AI-Agent/scripts/run_tests-tests.py"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import run_tests as RT

R = []
HERE = Path(__file__).resolve().parent


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


def vault(entries_core, entries_mother=(), files=None):
    root = Path(tempfile.mkdtemp(prefix="runtests-"))
    (root / "AI-Agent" / "config").mkdir(parents=True)
    lines = ["version: 1", "stratum_core:"]
    for p, runner, lane in entries_core:
        lines += [f"  - path: {p}", f"    runner: {runner}", f"    lane: {lane}"]
    lines.append("mother_vault_drop:")
    for p, runner, lane in entries_mother:
        lines += [f"  - path: {p}", f"    runner: {runner}", f"    lane: {lane}"]
    (root / RT.CLASSIFICATION).write_text("\n".join(lines) + "\n", encoding="utf-8")
    for rel, body in (files or {}).items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")
    return root


_PASS, _FAIL = "print('ok')\n", "import sys\nprint('boom')\nsys.exit(3)\n"
_SLOW = "import time\ntime.sleep(30)\n"
_ORDER = "import os,sys\nopen(os.environ['VAULT'] + '/order.log', 'a').write(sys.argv[0].split('/')[-1] + '\\n')\n"
tmp = []
try:
    r1 = vault([("t/a-tests.py", "direct", "parallel"), ("t/b-tests.py", "direct", "serial"), ("t/c-tests.py", "direct", "parallel")],
               files={"t/a-tests.py": _PASS, "t/b-tests.py": _FAIL, "t/c-tests.py": _PASS}); tmp.append(r1)
    plan = RT.load_plan(r1)
    ok("T01-plan-keeps-file-order-and-lanes", [(e["path"], e["lane"]) for e in plan] == [("t/a-tests.py", "parallel"), ("t/b-tests.py", "serial"), ("t/c-tests.py", "parallel")], plan)
    res = RT.run_plan(r1, plan, jobs=2, timeout=20)
    ok("T02-results-in-plan-order-with-statuses", [(r["path"], r["status"]) for r in res] == [("t/a-tests.py", "PASS"), ("t/b-tests.py", "FAIL"), ("t/c-tests.py", "PASS")], [(r["path"], r["status"]) for r in res])
    ok("T03-failure-tail-carries-the-output", "boom" in res[1]["tail"])
    ok("T04-summary-counts", RT.summarize(res) == (2, 3, 0), RT.summarize(res))
    ok("T05-lane-filter", [e["path"] for e in RT.load_plan(r1, lane="serial")] == ["t/b-tests.py"] and [e["path"] for e in RT.load_plan(r1, only="a-tests")] == ["t/a-tests.py"])

    r2 = vault([("t/slow-tests.py", "direct", "serial"), ("t/gone-tests.py", "direct", "serial"), ("t/probe.py", "probe_cli", "serial")],
               [("t/mother-tests.py", "direct", "parallel")], files={"t/slow-tests.py": _SLOW, "t/probe.py": _PASS}); tmp.append(r2)
    res2 = RT.run_plan(r2, RT.load_plan(r2), timeout=1)
    st = {r["path"]: r["status"] for r in res2}
    ok("T06-timeout-is-reported-and-not-a-pass", st["t/slow-tests.py"] == "TIMEOUT", st)
    ok("T07-a-missing-core-file-fails", st["t/gone-tests.py"] == "MISSING", st)
    ok("T08-a-probe-is-skipped-not-counted", st["t/probe.py"] == "SKIP" and RT.summarize(res2) == (0, 2, 1), (st, RT.summarize(res2)))
    ok("T09-the-mother-set-is-not-selected-by-default", all(e["set"] == "stratum_core" for e in RT.load_plan(r2)) and any(e["set"] == "mother_vault_drop" for e in RT.load_plan(r2, "all")))
    ok("T10-a-missing-mother-only-file-is-a-skip-in-a-release-tree", {r["path"]: r["status"] for r in RT.run_plan(r2, RT.load_plan(r2, "all"), timeout=1)}["t/mother-tests.py"] == "SKIP")

    r3 = vault([("t/p1-tests.py", "direct", "parallel"), ("t/s1-tests.py", "direct", "serial"), ("t/p2-tests.py", "direct", "parallel")],
               files={"t/p1-tests.py": _ORDER, "t/s1-tests.py": _ORDER, "t/p2-tests.py": _ORDER}); tmp.append(r3)
    RT.run_plan(r3, RT.load_plan(r3), jobs=2, timeout=20)
    order = (r3 / "order.log").read_text(encoding="utf-8").split()
    ok("T11-the-serial-lane-runs-after-the-parallel-lane", order[-1] == "s1-tests.py" and sorted(order[:2]) == ["p1-tests.py", "p2-tests.py"], order)

    r4 = vault([("t/skip-tests.py", "direct", "parallel"), ("t/ok-tests.py", "direct", "parallel")], files={"t/skip-tests.py": "import sys\nprint('inputs absent')\nsys.exit(77)\n", "t/ok-tests.py": _PASS}); tmp.append(r4)
    res4 = RT.run_plan(r4, RT.load_plan(r4), timeout=20)
    ok("T15-exit-77-is-a-skip-with-its-message-and-is-not-counted", [r["status"] for r in res4] == ["SKIP", "PASS"] and RT.summarize(res4) == (1, 1, 1) and "inputs absent" in res4[0]["tail"], res4)

    r5 = vault([("t/env-tests.py", "direct", "parallel")], files={"t/env-tests.py": "import os,sys\nsys.exit(0 if os.environ.get('STRATUM_NET_LOG','').endswith('stratum-tests-net-preflight.log') and os.environ.get('VAULT') else 4)\n"}); tmp.append(r5)
    ok("T16-children-get-a-temp-net-log-so-a-test-run-does-not-write-into-the-tree", RT.run_plan(r5, RT.load_plan(r5), timeout=20)[0]["status"] == "PASS")

    def cli(root, *a):
        return subprocess.run([sys.executable, str(HERE / "run_tests.py"), *a], capture_output=True, text=True, env=dict(os.environ, VAULT=str(root)), timeout=60)
    good = vault([("t/a-tests.py", "direct", "parallel")], files={"t/a-tests.py": _PASS}); tmp.append(good)
    c1, c2, c3 = cli(good), cli(r1), cli(good, "--list")
    ok("T12-cli-exit-0-when-all-pass-and-1-when-one-fails", c1.returncode == 0 and "RUN-TESTS 1/1 passed" in c1.stdout and c2.returncode == 1 and "RUN-TESTS 2/3" in c2.stdout, (c1.stdout[-80:], c2.stdout[-80:]))
    ok("T13-list-prints-the-plan-without-running", c3.returncode == 0 and "RUN-TESTS plan 1" in c3.stdout)
    ok("T14-help-rc0-unknown-flag-rc2", cli(good, "--help").returncode == 0 and cli(good, "--bogus").returncode == 2)
finally:
    for t in tmp:
        shutil.rmtree(t, ignore_errors=True)

failed = [r for r in R if not r[1]]
for name, passed, got in R:
    print(("PASS " if passed else "FAIL ") + name + ("" if passed else f" -> {got}"))
print(f"RUN-TESTS-TESTS {len(R) - len(failed)}/{len(R)}")
sys.exit(1 if failed else 0)
