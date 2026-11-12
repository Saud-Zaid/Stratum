#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""apply-tests.py — checks for apply.py (FX04/T-09).

Coverage:
- Positive: 5-file plan applied in one call (T-09 acceptance).
- Conditional: expectedContent mismatch aborts with NO writes; missing file with
  expectedContent aborts; sandbox escape rejected.
- Rollback: mid-batch write failure restores already-written files.
- Invalid: broken JSON, empty operations, missing keys.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import apply as ap  # noqa: E402

SCRIPT = os.path.join(HERE, "apply.py")
VAULT = ap.VAULT

# Test area MUST live inside the vault sandbox (apply.py rejects paths outside it).
tmp = os.path.join(VAULT, "AI-Agent", "scratch", "apply-tests-tmp")
os.makedirs(tmp, exist_ok=True)
passed = failed = 0


def ok(name):
    global passed
    passed += 1
    print("PASS %s" % name)


def fail(name, detail):
    global failed
    failed += 1
    print("FAIL %s %s" % (name, detail))


def _rel(name):
    """Path relative to vault root inside the tmp dir (sandbox-safe test area)."""
    return os.path.join(os.path.relpath(tmp, VAULT), name)


def _plan(ops):
    p = os.path.join(tmp, "plan-%d.json" % len(os.listdir(tmp)))
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"operations": ops}, f, ensure_ascii=False)
    return p


def _run_cli(plan_path):
    return subprocess.run([sys.executable, SCRIPT, "--plan", plan_path],
                          capture_output=True, text=True, timeout=60)


def _mkfile(rel, content):
    full = os.path.join(VAULT, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return full


def _rm(full):
    if os.path.isfile(full):
        os.remove(full)


def t1_five_files_one_call():
    """T-09 acceptance: a plan with five files executes in one call."""
    ops = [{"path": _rel("t1-f%d.md" % i), "newContent": "content-%d" % i} for i in range(5)]
    r = _run_cli(_plan(ops))
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        fail("t1_five_files_one_call", "no json: %r" % r.stdout[:200])
        return
    if r.returncode != 0 or out.get("status") != "applied" or out.get("applied") != 5:
        fail("t1_five_files_one_call", "rc=%d out=%s" % (r.returncode, out))
        return
    for i in range(5):
        full = os.path.join(VAULT, _rel("t1-f%d.md" % i))
        if not os.path.isfile(full) or open(full, encoding="utf-8").read() != "content-%d" % i:
            fail("t1_five_files_one_call", "file %d wrong" % i)
            return
        _rm(full)
    ok("t1_five_files_one_call")


def t2_conditional_mismatch_aborts():
    """expectedContent mismatch aborts the whole batch with NO writes."""
    target = _mkfile(_rel("t2-target.md"), "original")
    fresh = os.path.join(VAULT, _rel("t2-fresh.md"))
    ops = [
        {"path": _rel("t2-fresh.md"), "newContent": "new"},
        {"path": _rel("t2-target.md"), "expectedContent": "stale-expected", "newContent": "new"},
    ]
    r = _run_cli(_plan(ops))
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        fail("t2_conditional_mismatch_aborts", "no json")
        return
    if r.returncode != 1 or out.get("status") != "aborted":
        fail("t2_conditional_mismatch_aborts", "rc=%d out=%s" % (r.returncode, out))
    elif os.path.isfile(fresh):
        fail("t2_conditional_mismatch_aborts", "fresh file was written despite abort")
    else:
        ok("t2_conditional_mismatch_aborts")
    _rm(target)


def t3_missing_file_with_expected():
    """File missing but expectedContent given -> abort (cannot verify)."""
    ops = [{"path": _rel("t3-ghost.md"), "expectedContent": "x", "newContent": "y"}]
    r = _run_cli(_plan(ops))
    if r.returncode != 1 or "aborted" not in r.stdout:
        fail("t3_missing_file_with_expected", "rc=%d out=%r" % (r.returncode, r.stdout[:150]))
    else:
        ok("t3_missing_file_with_expected")


def t4_sandbox_escape():
    """Path escaping the vault is rejected in pre-flight."""
    ops = [{"path": "../../etc/passwd", "newContent": "evil"}]
    r = _run_cli(_plan(ops))
    if r.returncode not in (1, 2) or "aborted" not in r.stdout and "invalid" not in r.stdout:
        fail("t4_sandbox_escape", "rc=%d out=%r" % (r.returncode, r.stdout[:150]))
    else:
        ok("t4_sandbox_escape")


def t5_rollback_mid_batch():
    """Mid-batch write failure triggers soft rollback of already-written files."""
    if os.name == "nt":   # Windows ignores the read-only directory bit this scenario relies on
        print("SKIP t5_rollback_mid_batch: no POSIX directory permissions on Windows")
        return
    keep = _mkfile(_rel("t5-keep.md"), "keep-original")
    blocker = _mkfile(_rel("t5-blocker"), "blocker")
    os.chmod(blocker, 0o444)  # read-only -> write fails
    os.makedirs(os.path.join(VAULT, _rel("t5-ro-dir")), exist_ok=True)
    ro_dir = os.path.join(VAULT, _rel("t5-ro-dir"))
    os.chmod(ro_dir, 0o555)  # unwritable dir -> makedirs/write fails
    ops = [
        {"path": _rel("t5-keep.md"), "newContent": "keep-changed"},
        {"path": _rel("t5-ro-dir" + "/t5-inside.md"), "newContent": "x"},
    ]
    r = _run_cli(_plan(ops))
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        out = {"status": "?", "stdout": r.stdout[:150]}
    status_ok = out.get("status") in ("rolled_back", "aborted")
    content_ok = open(keep, encoding="utf-8").read() == "keep-original"
    if r.returncode == 0:
        fail("t5_rollback_mid_batch", "rc=0 out=%s" % out)
    elif not content_ok:
        fail("t5_rollback_mid_batch", "keep file not restored: %r" % open(keep, encoding="utf-8").read()[:60])
    elif not status_ok:
        fail("t5_rollback_mid_batch", "status=%s" % out.get("status"))
    else:
        ok("t5_rollback_mid_batch")
    os.chmod(ro_dir, 0o755)
    os.rmdir(ro_dir)
    os.chmod(blocker, 0o644)
    _rm(keep)
    _rm(blocker)


def t6_broken_json():
    p = os.path.join(tmp, "broken.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write("{not json")
    r = _run_cli(p)
    if r.returncode != 2:
        fail("t6_broken_json", "rc=%d" % r.returncode)
    else:
        ok("t6_broken_json")


def t7_empty_operations():
    r = _run_cli(_plan([]))
    if r.returncode != 2:
        fail("t7_empty_operations", "rc=%d" % r.returncode)
    else:
        ok("t7_empty_operations")


def t8_missing_keys():
    r = _run_cli(_plan([{"path": _rel("t8.md")}]))  # no newContent
    if r.returncode != 2:
        fail("t8_missing_keys", "rc=%d" % r.returncode)
    else:
        ok("t8_missing_keys")


def t9_missing_plan_file():
    r = _run_cli(os.path.join(tmp, "no-such-plan.json"))
    if r.returncode != 2:
        fail("t9_missing_plan_file", "rc=%d" % r.returncode)
    else:
        ok("t9_missing_plan_file")


def t10_conditional_match_applies():
    """Matching expectedContent allows the write (conditional success path)."""
    target = _mkfile(_rel("t10-target.md"), "exact-current")
    ops = [{"path": _rel("t10-target.md"), "expectedContent": "exact-current", "newContent": "replaced"}]
    r = _run_cli(_plan(ops))
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        fail("t10_conditional_match_applies", "no json")
        return
    if r.returncode != 0 or out.get("status") != "applied":
        fail("t10_conditional_match_applies", "rc=%d out=%s" % (r.returncode, out))
    elif open(target, encoding="utf-8").read() != "replaced":
        fail("t10_conditional_match_applies", "content not replaced")
    else:
        ok("t10_conditional_match_applies")
    _rm(target)


for fn in (t1_five_files_one_call, t2_conditional_mismatch_aborts, t3_missing_file_with_expected,
           t4_sandbox_escape, t5_rollback_mid_batch, t6_broken_json, t7_empty_operations,
           t8_missing_keys, t9_missing_plan_file, t10_conditional_match_applies):
    fn()

print("SUITE %d/%d" % (passed, passed + failed))
sys.exit(1 if failed else 0)
