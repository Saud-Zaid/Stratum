#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""restore_ready.py — the restore-readiness gate (FX00).

Checks the three things the project's precondition requires:
  1. commits exist (HEAD is available, the repository is not empty)
  2. the pre-commit hook is installed and executable
  3. a remote (origin) is defined and reachable

Fails loudly (exit 1) when any item is missing. Usage: python AI-Agent/scripts/restore_ready.py [--local]
  --local   a local-only repository with no remote: only the remote item is skipped (U-43)
The hook is resolved through `git rev-parse --git-path hooks/pre-commit`, so core.hooksPath is respected, and a tracked hook must be 100755.
Exit codes: 0 = restore-ready; 1 = an item is missing; 2 = unknown flag."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
HOOK = None   # tests may pin a path; otherwise it is resolved through git, which honours core.hooksPath (.githooks/)


def git(*args):
    try:
        return subprocess.run(["git", "-C", VAULT, "-c", "core.quotepath=off", *args],
                              capture_output=True, text=True, timeout=30)
    except Exception:
        return None


def check_head():
    r = git("rev-parse", "--verify", "HEAD")
    if r is None or r.returncode != 0:
        return False, "HEAD unavailable (no commits)"
    count = git("rev-list", "--count", "HEAD")
    if count is None or count.returncode != 0 or int(count.stdout.strip() or 0) < 1:
        return False, "no commits on HEAD"
    return True, "HEAD=%s commits=%s" % (r.stdout.strip()[:7], count.stdout.strip())


def hook_path():
    """The pre-commit hook git will actually run: `git rev-parse --git-path hooks/pre-commit` (core.hooksPath aware)."""
    if HOOK:
        return HOOK
    r = git("rev-parse", "--git-path", "hooks/pre-commit")
    rel = r.stdout.strip() if r is not None and r.returncode == 0 else ".git/hooks/pre-commit"
    return rel if os.path.isabs(rel) else os.path.join(VAULT, rel)


def tracked_mode(path):
    """The git index mode of a tracked file (e.g. '100755'), None when untracked or outside the repo."""
    try:
        rel = os.path.relpath(path, VAULT).replace(os.sep, "/")
    except ValueError:
        return None
    if rel.startswith(".."):
        return None
    r = git("ls-files", "-s", "--", rel)
    if r is None or r.returncode != 0 or not r.stdout.strip():
        return None
    return r.stdout.split()[0]


def check_hook():
    hook = hook_path()
    if not os.path.isfile(hook):
        return False, "pre-commit hook file missing"
    mode = tracked_mode(hook)
    if mode is not None and mode != "100755":
        return False, "tracked pre-commit hook has mode %s, not 100755 (git update-index --chmod=+x)" % mode
    # Windows has no exec bit on disk: the index mode above is the proof there; elsewhere check the file too.
    if os.name != "nt" and not os.access(hook, os.X_OK):
        return False, "pre-commit hook not executable"
    with open(hook, encoding="utf-8", errors="replace") as f:
        first = f.readline()
    if not first.startswith("#!"):
        return False, "pre-commit hook has no shebang"
    return True, "hook executable with shebang" + (" (tracked 100755)" if mode == "100755" else "")


def check_remote():
    r = git("remote")
    if r is None or r.returncode != 0 or not r.stdout.strip():
        return False, "no git remote configured"
    name = r.stdout.strip().splitlines()[0]
    url = git("remote", "get-url", name)
    remote_url = url.stdout.strip() if url and url.returncode == 0 else "?"
    # ls-remote proves the remote is actually reachable (not just configured)
    ls = git("ls-remote", "--heads", name)
    if ls is None or ls.returncode != 0:
        return False, "remote %s (%s) unreachable: %s" % (
            name, remote_url, (ls.stderr.strip().splitlines() or ["?"])[0][:120] if ls else "?")
    return True, "remote %s (%s) reachable, %d heads" % (
        name, remote_url, len(ls.stdout.strip().splitlines()))


CHECKS = [("commits", check_head), ("hook", check_hook), ("remote", check_remote)]


def run(require_remote=True):
    results = []
    all_ok = True
    for name, fn in CHECKS:
        if name == "remote" and not require_remote:
            results.append((name, True, "skipped (--local: a local-only repository)"))
            continue
        ok, detail = fn()
        results.append((name, ok, detail))
        if not ok:
            all_ok = False
    for name, ok, detail in results:
        print("RESTORE %s %s %s" % (name, "PASS" if ok else "FAIL", detail))
    print("RESTORE-READY %s" % ("yes" if all_ok else "no"))
    return all_ok, results


if __name__ == "__main__":
    if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        print(__doc__)
        sys.exit(0)
    unknown = [a for a in sys.argv[1:] if a != "--local"]
    if unknown:
        print("restore_ready: unknown option %s" % unknown[0], file=sys.stderr)
        sys.exit(2)
    ok, _ = run(require_remote="--local" not in sys.argv[1:])
    sys.exit(0 if ok else 1)
