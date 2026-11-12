#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Consumer suites runner — maps changed paths to the consumer test suites they require.

C19-b stage C (AD10): the registry lives in consumer-map.yaml (single source of truth),
never in code. Standard (research 20261024a_c19b-standards, Q1): map-based registry with
mandatory broad-set fallback — a path the registry does not cover triggers the fallback
suites, so silent drift has nowhere to hide (C19 D3/D6 lesson).

Usage: consumer_suites --check <path> [<path>...]
       consumer_suites --plan <path> [<path>...]
       consumer_suites --staged [--run]      the paths in the git index; --run syntax-checks them and runs the planned suites
Exit:  0 normally (and all suites green with --run); 1 a suite or compile failed; 2 an unknown option or the map is missing/broken (the caller must not proceed blindly).
"""
import os
import subprocess
import sys
import time

MAP_REL = os.path.join("schema", "consumer-map.yaml")


def map_path():
    """consumer-map.yaml relative to this script's vault root (AI-Agent/)."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), MAP_REL)


def load_config(path=None):
    """Parse the suites block of consumer-map.yaml into a config dict.

    Flat format (mini-parser, no yaml lib): keys under `suites:`, list entries as
    `- "prefix|suite1,suite2"`. Raises ValueError on a missing/broken block.
    """
    path = path or map_path()
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    # strip frontmatter: everything before the second '---'
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                lines = lines[i + 1:]
                break
    # find the suites block
    start = None
    for i, ln in enumerate(lines):
        if ln.rstrip() == "suites:":
            start = i + 1
            break
    if start is None:
        raise ValueError("consumer-map.yaml has no 'suites:' block")
    cfg = {"prefixes": [], "fallback": [], "stem_prefix": "", "time_cap_seconds": 300}
    section = None
    for ln in lines[start:]:
        if ln.strip() and not ln[0].isspace():
            break  # next top-level key: suites block ended
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if section == "prefixes" and s.startswith('- "'):
            prefix, _, suites = s[3:-1].partition("|")
            cfg["prefixes"].append((prefix, [x.strip() for x in suites.split(",") if x.strip()]))
            continue
        key, _, val = s.partition(":")
        key, val = key.strip(), val.strip()
        if key == "stem_prefix":
            cfg["stem_prefix"] = val.strip('"')
            section = None
        elif key == "prefixes":
            section = "prefixes"
        elif key == "fallback":
            cfg["fallback"] = [x.strip() for x in val.split(",") if x.strip()]
            section = None
        elif key == "time_cap_seconds":
            cfg["time_cap_seconds"] = int(val)
            section = None
    if not cfg["fallback"]:
        raise ValueError("consumer-map.yaml suites.fallback is empty — mandatory broad-set fallback (Q1)")
    return cfg


def plan(paths, cfg):
    """Map changed paths to suites. Returns (suites_list, unknown_paths).

    Standard Q1: any path the registry does not cover forces ALL fallback suites —
    the broad set runs, never nothing.
    """
    ordered, unknown = [], []
    for p in paths:
        p = p.replace("\\", "/")
        matched = False
        stem_pre = cfg["stem_prefix"]
        if stem_pre and p.startswith(stem_pre) and p.endswith(".py") and "-tests" not in os.path.basename(p):
            stem = os.path.basename(p)[:-3]
            cand = stem + "-tests"
            if cand not in ordered:
                ordered.append(cand)
            matched = True
        for prefix, suites in cfg["prefixes"]:
            if p.startswith(prefix):
                for s in suites:
                    if s not in ordered:
                        ordered.append(s)
                matched = True
        if not matched:
            unknown.append(p)
    if unknown:
        for s in cfg["fallback"]:
            if s not in ordered:
                ordered.append(s)
    return ordered, unknown


def vault_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def staged_paths(root=None):
    """Added/copied/modified/renamed paths in the index, relative to the repo root (git's own spelling, / separators)."""
    root = root or vault_root()
    r = subprocess.run(["git", "-C", root, "-c", "core.quotepath=off", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise OSError("git diff --cached failed: " + (r.stderr.strip().splitlines() or ["?"])[0])
    return [x for x in r.stdout.splitlines() if x]


def suite_file(name, root=None):
    """AI-Agent/{scripts,schema}/<name>(-tests).py for a suite name from the map; None when no such file exists."""
    root = root or vault_root()
    base = name if name.endswith("-tests") else name + "-tests"
    for d in ("scripts", "schema"):
        f = os.path.join(root, "AI-Agent", d, base + ".py")
        if os.path.isfile(f):
            return f
    return None


def run_plan(paths, cfg, root=None, python=None):
    """py_compile every .py path, then run the planned suites. Returns (rc, lines): 0 all green, 1 a failure.
    A mapped suite with no file is a failure (the map is lying); a stem-derived `<stem>-tests` with no file is skipped."""
    root = root or vault_root()
    python = python or sys.executable
    lines, bad, seen = [], False, set()
    for p in paths:
        if p.endswith(".py") and os.path.isfile(os.path.join(root, p)):
            try:
                with open(os.path.join(root, p), "rb") as fh:
                    compile(fh.read(), p, "exec")          # a syntax check that writes no .pyc
            except (SyntaxError, ValueError) as e:
                bad = True
                lines.append("COMPILE FAIL %s: %s" % (p, str(e).strip().splitlines()[-1][:160]))
    suites, unknown = plan(paths, cfg)
    deadline = time.monotonic() + cfg["time_cap_seconds"]
    for name in suites:
        f = suite_file(name, root)
        if f is None:
            if name.endswith("-tests"):
                lines.append("SKIP %s (no suite file)" % name)
            else:
                bad = True
                lines.append("MISSING %s (the map names a suite with no file)" % name)
            continue
        if f in seen:
            continue                                   # the stem rule and the map can name one file twice
        seen.add(f)
        left = deadline - time.monotonic()
        if left <= 0:
            bad = True
            lines.append("TIMEOUT %s (time_cap_seconds=%s exhausted)" % (name, cfg["time_cap_seconds"]))
            continue
        try:
            r = subprocess.run([python, f], cwd=root, capture_output=True, text=True, timeout=left)
            if r.returncode == 77:   # the suite declares itself not applicable in this tree
                lines.append("SKIP %s (exit 77: not applicable here)" % name)
                continue
            ok = r.returncode == 0
            tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
        except subprocess.TimeoutExpired:
            ok, tail = False, ["timed out"]
        bad = bad or not ok
        lines.append("%s %s %s" % ("PASS" if ok else "FAIL", name, "" if ok else tail[0][:160]))
    return (1 if bad else 0), lines


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    known = {"--check", "--plan", "--staged", "--run"}
    unknown_flags = [a for a in argv if a.startswith("-") and a not in known]
    if unknown_flags:
        print("consumer_suites: unknown option %s" % unknown_flags[0], file=sys.stderr)
        return 2
    staged, run = "--staged" in argv, "--run" in argv
    if not staged and "--check" not in argv and "--plan" not in argv:
        print(__doc__)
        return 0
    paths = []
    for mode in ("--check", "--plan"):
        if mode in argv:
            paths += [a for a in argv[argv.index(mode) + 1:] if not a.startswith("-")]
            break
    try:
        if staged:
            paths += staged_paths()
        cfg = load_config()
    except (ValueError, OSError) as e:
        print("BLOCK consumer-suites: %s" % e, file=sys.stderr)
        return 2
    if not paths:
        if not staged:
            print("no paths given", file=sys.stderr)
            return 1
        return 0                                   # nothing staged: nothing to run
    if run:
        rc, lines = run_plan(paths, cfg)
        for ln in lines:
            print(ln)
        return rc
    suites, unknown = plan(paths, cfg)
    for s in suites:
        print(s)
    if unknown:
        print("# fallback triggered for:", ", ".join(unknown), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
