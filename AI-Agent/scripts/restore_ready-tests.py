#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for restore_ready (FX00). Covers: all three checks pass on the real
vault; negative cases via a broken temp repo (no remote / no hook / no commits);
check functions return (bool, str) shape. Usage: restore_ready-tests"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import restore_ready as RR  # noqa: E402
from _vaultlib import scrub_git_env  # noqa: E402
scrub_git_env()   # hook variables must not reach the temporary repositories below

passed = failed = 0


def skip(name, why):
    """Not counted either way: the check is about an installed working checkout and this tree is not one."""
    print(f"SKIP {name} {why}")


def _rm(d):
    """rmtree that also removes git's read-only object files (Windows refuses to delete them otherwise)."""
    def onerror(func, path, _exc):
        os.chmod(path, 0o700)
        func(path)
    shutil.rmtree(d, onerror=onerror)


def _installed_checkout():
    """True when this checkout has the pre-commit hook installed, a remote and at least one commit: only then are the two real-checkout
    checks meaningful (the very first commit of a fresh repository runs the hook before any commit exists)."""
    return RR.git("remote").stdout.strip() != "" and os.path.isfile(RR.hook_path()) and RR.git("rev-parse", "--verify", "HEAD").returncode == 0


def ok(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
    print(f"{'PASS' if cond else 'FAIL'} {name} {extra if not cond else ''}")


def _mkrepo(no_hook=False, no_remote=False, no_commit=False):
    d = tempfile.mkdtemp(prefix="rr-test-")
    g = lambda *a: subprocess.run(["git", "-C", d, "-c", "user.email=t@t", "-c", "user.name=t", *a],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace")
    g("init", "-q")
    if not no_commit:
        g("commit", "-q", "--allow-empty", "-m", "init")
    if not no_hook:
        h = os.path.join(d, ".git", "hooks", "pre-commit")
        with open(h, "w", newline="\n") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(h, 0o755)
    if not no_remote:
        # an empty bare repo reachable locally proves ls-remote path
        bare = tempfile.mkdtemp(prefix="rr-bare-")
        subprocess.run(["git", "init", "-q", "--bare", bare])
        g("remote", "add", "origin", bare)
    return d


def t1_check_shapes():
    for name, fn in RR.CHECKS:
        res = fn()
        if not (isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], bool) and isinstance(res[1], str)):
            ok("t1_check_shapes", False, f"{name} bad shape {res}")
            return
    ok("t1_check_shapes", True)


def t2_full_repo_passes():
    d = _mkrepo()
    old_vault, old_hook = RR.VAULT, RR.HOOK
    RR.VAULT, RR.HOOK = d, os.path.join(d, ".git", "hooks", "pre-commit")
    try:
        all_ok, results = RR.run()
        names = [n for n, _, _ in results]
        ok("t2_full_repo_passes", all_ok and names == ["commits", "hook", "remote"],
           f"all_ok={all_ok} results={results}")
    finally:
        RR.VAULT, RR.HOOK = old_vault, old_hook
        _rm(d)


def t3_no_remote_fails():
    d = _mkrepo(no_remote=True)
    old_vault, old_hook = RR.VAULT, RR.HOOK
    RR.VAULT, RR.HOOK = d, os.path.join(d, ".git", "hooks", "pre-commit")
    try:
        all_ok, results = RR.run()
        remote = [r for r in results if r[0] == "remote"][0]
        ok("t3_no_remote_fails", (not all_ok) and remote[1] is False,
           f"results={results}")
    finally:
        RR.VAULT, RR.HOOK = old_vault, old_hook
        _rm(d)


def t4_no_hook_fails():
    d = _mkrepo(no_hook=True)
    old_vault, old_hook = RR.VAULT, RR.HOOK
    RR.VAULT, RR.HOOK = d, os.path.join(d, ".git", "hooks", "pre-commit")
    try:
        all_ok, results = RR.run()
        hook = [r for r in results if r[0] == "hook"][0]
        ok("t4_no_hook_fails", (not all_ok) and hook[1] is False, f"results={results}")
    finally:
        RR.VAULT, RR.HOOK = old_vault, old_hook
        _rm(d)


def t5_no_commits_fails():
    d = _mkrepo(no_commit=True)
    old_vault, old_hook = RR.VAULT, RR.HOOK
    RR.VAULT, RR.HOOK = d, os.path.join(d, ".git", "hooks", "pre-commit")
    try:
        all_ok, results = RR.run()
        commits = [r for r in results if r[0] == "commits"][0]
        ok("t5_no_commits_fails", (not all_ok) and commits[1] is False, f"results={results}")
    finally:
        RR.VAULT, RR.HOOK = old_vault, old_hook
        _rm(d)


def t6_real_vault_resteady():
    if not _installed_checkout():
        return skip("t6_real_vault_resteady", "this checkout has no hook or no remote (a fresh clone): the check is for an installed vault")
    all_ok, results = RR.run()
    ok("t6_real_vault_resteady", all_ok, f"results={results}")


def t7_cli_exit_codes():
    if not _installed_checkout():
        return skip("t7_cli_exit_codes", "this checkout has no hook or no remote (a fresh clone): the check is for an installed vault")
    r = subprocess.run([sys.executable, os.path.join(HERE, "restore_ready.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    ok("t7_cli_exit_codes", r.returncode == 0 and "RESTORE-READY yes" in r.stdout,
       f"rc={r.returncode} out={r.stdout[:200]}")


def _pin(d):
    old = (RR.VAULT, RR.HOOK)
    RR.VAULT, RR.HOOK = d, None
    return old


def t8_hooks_path_resolved_through_git():
    d = _mkrepo(no_hook=True)
    old = _pin(d)
    try:
        os.makedirs(os.path.join(d, ".githooks"))
        h = os.path.join(d, ".githooks", "pre-commit")
        with open(h, "w", newline="\n") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(h, 0o755)
        subprocess.run(["git", "-C", d, "config", "core.hooksPath", ".githooks"], check=True)
        res = RR.check_hook()
        ok("t8_hooks_path_resolved_through_git", res[0] is True and RR.hook_path() == h, res)
    finally:
        RR.VAULT, RR.HOOK = old
        _rm(d)


def t9_tracked_hook_must_be_100755():
    d = _mkrepo(no_hook=True)
    old = _pin(d)
    try:
        os.makedirs(os.path.join(d, ".githooks"))
        h = os.path.join(d, ".githooks", "pre-commit")
        with open(h, "w", newline="\n") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(h, 0o755)
        subprocess.run(["git", "-C", d, "config", "core.hooksPath", ".githooks"], check=True)
        subprocess.run(["git", "-C", d, "add", ".githooks/pre-commit"], check=True)
        subprocess.run(["git", "-C", d, "update-index", "--chmod=-x", ".githooks/pre-commit"], check=True)
        bad = RR.check_hook()
        subprocess.run(["git", "-C", d, "update-index", "--chmod=+x", ".githooks/pre-commit"], check=True)
        good = RR.check_hook()
        ok("t9_tracked_hook_must_be_100755", bad[0] is False and "100644" in bad[1] and good[0] is True and "tracked 100755" in good[1], (bad, good))
    finally:
        RR.VAULT, RR.HOOK = old
        _rm(d)


def t10_local_flag_skips_only_remote():
    d = _mkrepo(no_remote=True)
    old = _pin(d)
    try:
        strict, _ = RR.run()
        local, results = RR.run(require_remote=False)
        remote = [r for r in results if r[0] == "remote"][0]
        ok("t10_local_flag_skips_only_remote", strict is False and local is True and "skipped" in remote[2], results)
        d2 = _mkrepo(no_remote=True, no_hook=True)
        RR.VAULT = d2
        broken, _ = RR.run(require_remote=False)
        ok("t10b_local_flag_still_requires_hook", broken is False)
        _rm(d2)
    finally:
        RR.VAULT, RR.HOOK = old
        _rm(d)


def t11_cli_local_and_unknown_flag():
    r = subprocess.run([sys.executable, os.path.join(HERE, "restore_ready.py"), "--bogus"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    h = subprocess.run([sys.executable, os.path.join(HERE, "restore_ready.py"), "--help"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    d = _mkrepo(no_remote=True)   # restore_ready.py finds its repository from where it lives, so run a copy that lives in a repository the test builds
    try:
        os.makedirs(os.path.join(d, "AI-Agent", "scripts"))
        shutil.copy(os.path.join(HERE, "restore_ready.py"), os.path.join(d, "AI-Agent", "scripts", "restore_ready.py"))
        loc = subprocess.run([sys.executable, os.path.join(d, "AI-Agent", "scripts", "restore_ready.py"), "--local"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    finally:
        _rm(d)
    ok("t11_cli_local_and_unknown_flag", r.returncode == 2 and "--bogus" in r.stderr and h.returncode == 0 and "--local" in h.stdout
       and loc.returncode == 0 and "skipped" in loc.stdout, (r.returncode, h.returncode, loc.returncode, loc.stdout[-120:]))


for fn in (t1_check_shapes, t2_full_repo_passes, t3_no_remote_fails, t4_no_hook_fails,
           t5_no_commits_fails, t6_real_vault_resteady, t7_cli_exit_codes,
           t8_hooks_path_resolved_through_git, t9_tracked_hook_must_be_100755,
           t10_local_flag_skips_only_remote, t11_cli_local_and_unknown_flag):
    fn()

print(f"SUITE {passed}/{passed + failed}")   # a SKIP line above is not counted
sys.exit(1 if failed else 0)
