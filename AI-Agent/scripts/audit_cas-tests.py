#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""audit_cas-tests.py — Comprehensive Unit & Integration Tests for L3 Incremental CAS Audit Cache.

AD13 M04 Verification:
- Tests early index bootstrap in AI-Agent/state/vault-index.sqlite3.
- Tests WAL mode and schema invariants.
- Benchmarks warm execution time against a stated threshold (the test name carries the threshold).
- Tests 100% accuracy equivalence between cached and uncached audits.
- Verifies transient link drift detection on in-memory heading index.
- Verifies graceful fallback if SQLite cache is bypassed or disabled.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
VAULT_DIR = SCRIPTS_DIR.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from _vaultlib import INDEX_DB_PATH, get_vault_index_db, VAULT, read, file_sha1, invalidate_audit_cache_if_stale
from _vaultlib import scrub_git_env
scrub_git_env()   # hook variables must not reach the temporary clones below

R = []


def ok(name: str, condition: bool, details: str = "") -> None:
    R.append((name, condition, details))
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name} {details}".strip())


def test_db_structure():
    conn = get_vault_index_db()
    cur = conn.cursor()
    
    # T01: DB exists
    ok("T01-db-initialized", INDEX_DB_PATH.exists(), f"path={INDEX_DB_PATH}")
    
    # T02: WAL mode
    cur.execute("PRAGMA journal_mode;")
    mode = cur.fetchone()[0].lower()
    ok("T02-wal-mode", mode == "wal", f"journal_mode={mode}")
    
    # T03: Tables exist
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {r[0] for r in cur.fetchall()}
    has_tables = "audit_cas_cache" in tables and "vault_files" in tables
    ok("T03-required-tables", has_tables, f"tables={tables}")


def test_cache_population_and_data_integrity():
    conn = get_vault_index_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM audit_cas_cache;")
    count = cur.fetchone()[0]
    ok("T04-cache-populated", count >= 50, f"entries={count}")
    
    # Verify sample record
    cur.execute("SELECT path, blob_sha1, leaf_max, findings_json, doc_meta_json FROM audit_cas_cache LIMIT 10;")
    rows = cur.fetchall()
    valid_records = True
    for r in rows:
        path, sha, leaf_max, f_json, m_json = r
        if len(sha) != 40 or f_json != "[]":   # findings are never cached (M04): the column stays empty
            valid_records = False
            break
        meta = json.loads(m_json)
        if not {"headings", "fm_raw", "has_fm", "wikilinks", "inline"} <= set(meta) or "fm" in meta:   # front matter values are never stored (YAML types do not survive JSON)
            valid_records = False
            break
    ok("T05-data-integrity", valid_records and len(rows) == 10, "text hash and parse-product JSON structures valid; no findings stored")


def test_warm_audit_speed():
    python_bin = sys.executable   # the interpreter running the tests: no wrapper dependency
    audit_script = SCRIPTS_DIR / "audit.py"
    
    durations = []
    for _ in range(3):   # the best of three: one slow run on a busy machine says nothing about the cache
        t0 = time.time()
        res = subprocess.run([str(python_bin), str(audit_script), "--ratchet"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        durations.append(time.time() - t0)
    duration = min(durations)
    
    ok("T06-ratchet-success", res.returncode == 0, f"code={res.returncode}")
    ok("T07-warm-under-5s-workstation-15s-ci", duration < (15.0 if os.environ.get("CI") else 5.0),   # a shared CI runner is several times slower than a workstation
        f"duration={duration:.3f}s (Warm Ratchet Audit)")


def test_accuracy_match():
    python_bin = sys.executable   # the interpreter running the tests: no wrapper dependency
    audit_script = SCRIPTS_DIR / "audit.py"
    
    # 1. Warm cached run
    res_cached = subprocess.run([str(python_bin), str(audit_script), "--check", "headings,size,frontmatter"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    summary_cached = [l for l in res_cached.stdout.splitlines() if l.startswith("SUMMARY") or l.startswith("SNAPSHOT")]
    
    # 2. Uncached run (--no-cache)
    res_uncached = subprocess.run([str(python_bin), str(audit_script), "--check", "headings,size,frontmatter", "--no-cache"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    summary_uncached = [l for l in res_uncached.stdout.splitlines() if l.startswith("SUMMARY") or l.startswith("SNAPSHOT")]
    
    match = summary_cached == summary_uncached and len(summary_cached) >= 2
    ok("T08-accuracy-match", match, f"cached={summary_cached[0] if summary_cached else 'none'}")


def test_transient_cross_file_detection():
    # Verify that in-memory cross-file check detects broken link without full rescan
    import audit
    
    texts = {"file_a.md": "Links to [[file_b#NonExistentHeading]]\n", "file_b.md": "## RealHeading\nSome content\n"}
    docs = {r: audit.parse(t) for r, t in texts.items()}
    ctx = audit.Ctx(texts, docs)
    
    found = audit.findings_for("file_a.md", texts["file_a.md"], {"links"}, 4000, ctx)
    has_r12 = any(f[1] == "R12-missing" for f in found)
    ok("T09-transient-r12-detected", has_r12, "In-memory heading resolution catches broken link")


def test_graceful_fallback():
    python_bin = sys.executable   # the interpreter running the tests: no wrapper dependency
    audit_script = SCRIPTS_DIR / "audit.py"
    
    # Force --no-cache explicitly
    res = subprocess.run([str(python_bin), str(audit_script), "--no-cache", "--check", "consumer_drift"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok("T10-graceful-fallback", res.returncode == 0 and "SUMMARY" in res.stdout, "Runs cleanly with cache disabled")


def test_fingerprint_invalidation():
    """T-02d: the cache is dropped when the profile or the schema changes, kept when they do not."""
    with tempfile.TemporaryDirectory() as td:
        conn = get_vault_index_db(Path(td) / "idx.sqlite3")
        row = ("a.md", "sha", 4000, "[]", "{}", 0.0)
        ins = "INSERT INTO audit_cas_cache (path, blob_sha1, leaf_max, findings_json, doc_meta_json, updated_at) VALUES (?,?,?,?,?,?)"
        n = lambda: conn.execute("SELECT COUNT(*) FROM audit_cas_cache").fetchone()[0]
        conn.execute(ins, row); conn.commit()
        ok("T11-first-run-untrusted", invalidate_audit_cache_if_stale(conn, profile_sha1="p1", schema_sha1="s1") and n() == 0)
        conn.execute(ins, row); conn.commit()
        ok("T12-same-fingerprints-keep-cache", not invalidate_audit_cache_if_stale(conn, profile_sha1="p1", schema_sha1="s1") and n() == 1)
        ok("T13-profile-change-drops-cache", invalidate_audit_cache_if_stale(conn, profile_sha1="p2", schema_sha1="s1") and n() == 0)
        conn.execute(ins, row); conn.commit()
        ok("T14-schema-change-drops-cache", invalidate_audit_cache_if_stale(conn, profile_sha1="p2", schema_sha1="s2") and n() == 0)
        f = Path(td) / "x.yaml"
        ok("T15-file_sha1-missing-is-empty", file_sha1(f) == "")
        f.write_text("a", encoding="utf-8"); h1 = file_sha1(f); f.write_text("b", encoding="utf-8")
        ok("T16-file_sha1-tracks-content", h1 != file_sha1(f) and len(h1) == 40)
        conn.close()


def test_profile_change_end_to_end():
    """A changed release_profile.yaml makes the next audit recompute: the stored profile_sha1 follows it."""
    conn = get_vault_index_db()
    prof = VAULT / "AI-Agent" / "config" / "release_profile.yaml"
    original = prof.read_bytes()
    try:
        subprocess.run([sys.executable, str(SCRIPTS_DIR / "audit.py"), "--check", "headings"], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(VAULT))
        before = dict(conn.execute("SELECT key, value FROM cache_meta").fetchall())
        prof.write_bytes(original + b"\n# fingerprint probe\n")
        subprocess.run([sys.executable, str(SCRIPTS_DIR / "audit.py"), "--check", "headings"], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(VAULT))
        after = dict(conn.execute("SELECT key, value FROM cache_meta").fetchall())
        ok("T17-profile-edit-refreshes-fingerprint", before.get("profile_sha1") != after.get("profile_sha1") and after.get("profile_sha1") == file_sha1(prof),
           f"{before.get('profile_sha1')} -> {after.get('profile_sha1')}")
    finally:
        prof.write_bytes(original)
        subprocess.run([sys.executable, str(SCRIPTS_DIR / "audit.py"), "--check", "headings"], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(VAULT))
        conn.close()


# ---- M04 equivalence, correctness and degradation tests (written first, 2026-11-13) -------------------------------

AUDIT = SCRIPTS_DIR / "audit.py"
FINDING_LEVELS = ("info", "warn", "error")


def _audit(args, cwd, env=None, timeout=900):
    e = dict(os.environ)
    e["VAULT"] = str(cwd)   # the vault-python wrapper exports VAULT; a clone must audit itself, not the checkout that started the tests
    if env:
        e.update(env)
    return subprocess.run([sys.executable, str(cwd / "AI-Agent" / "scripts" / "audit.py"), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(cwd), env=e, timeout=timeout)


def _finding_lines(stdout: str) -> list[str]:
    """The comparable output of an audit run: every finding line plus the SUMMARY line, sorted.
    AUDIT, SNAPSHOT, PRIORITY and CACHE lines carry run-specific data and are excluded."""
    out = []
    for line in stdout.splitlines():
        f = line.split("\t")
        if (len(f) >= 3 and f[0] in FINDING_LEVELS) or line.startswith("SUMMARY"):
            out.append(line)
    return sorted(out)


def _cache_line(stdout: str) -> str:
    return next((l for l in stdout.splitlines() if l.startswith("CACHE ")), "")


def _equal(label, cwd, extra=()):
    """cached run versus --no-cache run on the same tree: the finding sets must be identical."""
    base = ["--min", "info", "--limit", "100000", *extra]
    cached = _audit(base, cwd)
    uncached = _audit([*base, "--no-cache"], cwd)
    a, b = _finding_lines(cached.stdout), _finding_lines(uncached.stdout)
    only_a, only_b = sorted(set(a) - set(b)), sorted(set(b) - set(a))
    _min = 100 if sum(1 for _ in Path(cwd).rglob("*.md")) > 500 else 3      # the mother vault has hundreds of findings; a clean release tree only a few (5 measured)
    ok(label, a == b and len(a) > _min,
       f"cached={len(a)} uncached={len(b)} only-cached={len(only_a)} only-uncached={len(only_b)}"
       + (f" e.g. {(only_b or only_a)[0][:90]}" if (only_a or only_b) else ""))
    return cached, uncached


def test_equivalence_live_tree():
    """T20: the cached audit equals the no-cache audit on the real tree, every rule (the old T08 compared three checks)."""
    _audit(["--ratchet", "--rebuild-cache"], VAULT_DIR)
    _equal("T20-cached-equals-uncached-live-tree", VAULT_DIR)


def _clone(td: str) -> Path:
    dest = Path(td) / "vault"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(VAULT_DIR), str(dest)], check=True, capture_output=True)
    import shutil   # the clone carries the committed scripts; the tests must run the working-tree ones
    shutil.copytree(SCRIPTS_DIR, dest / "AI-Agent" / "scripts", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    return dest


def test_equivalence_after_mutations():
    """T21-T24: equality after real edits: a duplicate heading, a cross-file change (a heading renamed in a note that an
    UNCHANGED note links to), and a change of the audit code."""
    with tempfile.TemporaryDirectory() as td:
        v = _clone(td)
        target = v / "03-Resources" / "Core-Vault-Architecture.md"
        text = target.read_text(encoding="utf-8")
        h2 = next(l for l in text.splitlines() if l.startswith("## "))[3:].strip()
        probe = v / "03-Resources" / "Mutation-Probe-Link.md"
        probe.write_text(f"# Mutation Probe Link\n\nSee [[Core-Vault-Architecture#{h2}]].\n", encoding="utf-8")
        _audit(["--ratchet", "--rebuild-cache"], v)                      # populate the cache with the probe note unchanged from here on
        base = _audit(["--min", "info", "--limit", "100000", "--no-cache"], v)
        ok("T21a-heading-link-resolves-before-mutation",
           not any("R12-missing" in l and "Mutation-Probe-Link" in l for l in _finding_lines(base.stdout)))
        notes = sorted((v / "01-Projects").rglob("*.md")) or sorted(v.rglob("*.md"))
        notes = [n for n in notes if not any(part.startswith(".") for part in n.relative_to(v).parts)]   # .vault-release/base is a copy the audit skips
        dup = next((n for n in notes if n.stat().st_size > 500), None)
        if dup is None:      # a release tree is nearly empty: no note large enough to take the probe
            print("SKIP T21-T24: no note over 500 bytes in this tree")
            return
        dup.write_text(dup.read_text(encoding="utf-8") + "\n## Mutation Probe\n\n## Mutation Probe\n", encoding="utf-8")
        c, u = _equal("T21-equal-after-dup-heading", v)
        ok("T21b-dup-heading-is-visible", len(_finding_lines(u.stdout)) > len(_finding_lines(base.stdout)),
           f"{len(_finding_lines(base.stdout))} -> {len(_finding_lines(u.stdout))}")
        target.write_text(text.replace("## " + h2, "## " + h2 + " renamed", 1), encoding="utf-8")
        c2, u2 = _equal("T22-equal-after-heading-renamed-in-linked-note", v)
        seen = lambda out: any("R12-missing" in l and "Mutation-Probe-Link" in l for l in _finding_lines(out))
        ok("T22b-unchanged-note-gets-the-new-cross-file-finding", seen(c2.stdout) and seen(u2.stdout),
           "the probe note is a cache hit, yet its heading link now fails")
        line = _cache_line(c2.stdout)
        ok("T23-status-line-after-edit", line.startswith("CACHE ") and "parse_hits=" in line and "parse_misses=" in line
           and "parse_misses=0" not in line, line)
        code = v / "AI-Agent" / "scripts" / "audit.py"
        code.write_text(code.read_text(encoding="utf-8") + "\n# code-version probe\n", encoding="utf-8")
        c3 = _audit(["--min", "info", "--limit", "100000"], v)
        line3 = _cache_line(c3.stdout)
        ok("T24-code-change-invalidates-cache", "invalidated=" in line3 and "code" in line3 and "parse_hits=0" in line3, line3)
        ok("T24b-results-still-equal-after-code-change", _finding_lines(c3.stdout) == _finding_lines(u2.stdout))


def test_status_line_and_warm_hits():
    """T25: one status line per run; a second run on an unchanged tree hits every note and invalidates nothing."""
    _audit(["--ratchet", "--rebuild-cache"], VAULT_DIR)
    r = _audit(["--ratchet"], VAULT_DIR)
    line = _cache_line(r.stdout)
    ok("T25-warm-run-hits-everything", "parse_misses=0" in line and "invalidated=none" in line, line)


def test_corrupt_db_rebuilds_loudly():
    """T26-T27: a corrupt store is replaced (never read), with a warning; a version mismatch also rebuilds."""
    from _vaultlib import INDEX_SCHEMA_VERSION
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "idx.sqlite3"
        db.write_bytes(b"this is not a sqlite database" * 200)
        r = subprocess.run([sys.executable, "-c",
                            "import sys; sys.path.insert(0, %r); from _vaultlib import get_vault_index_db; from pathlib import Path; "
                            "c = get_vault_index_db(Path(%r)); print(c.execute('PRAGMA user_version').fetchone()[0])" % (str(SCRIPTS_DIR), str(db))],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        ok("T26-corrupt-db-rebuilt-with-warning", r.returncode == 0 and r.stdout.strip() == str(INDEX_SCHEMA_VERSION) and "rebuilt" in r.stderr.lower(),
           f"rc={r.returncode} out={r.stdout.strip()} err={r.stderr.strip()[:90]}")
        old = Path(td) / "old.sqlite3"
        con = sqlite3.connect(str(old)); con.execute("CREATE TABLE audit_cas_cache (x)"); con.execute("PRAGMA user_version = 1"); con.commit(); con.close()
        r2 = subprocess.run([sys.executable, "-c",
                             "import sys; sys.path.insert(0, %r); from _vaultlib import get_vault_index_db; from pathlib import Path; "
                             "c = get_vault_index_db(Path(%r)); print(c.execute('PRAGMA user_version').fetchone()[0], "
                             "[r[1] for r in c.execute('PRAGMA table_info(audit_cas_cache)')])" % (str(SCRIPTS_DIR), str(old))],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
        ok("T27-old-schema-version-rebuilds", r2.returncode == 0 and r2.stdout.startswith(str(INDEX_SCHEMA_VERSION)) and "path" in r2.stdout,
           r2.stdout.strip()[:120])


def test_forced_cache_failure_is_loud():
    """T28: when the store cannot be opened the audit still runs uncached, says so on stdout and stderr, and equals a no-cache run."""
    bad = {"VAULT_INDEX_DB": "/proc/nonexistent-dir/idx.sqlite3"}
    r = _audit(["--min", "info", "--limit", "100000"], VAULT_DIR, env=bad)
    ref = _audit(["--min", "info", "--limit", "100000", "--no-cache"], VAULT_DIR)
    ok("T28-cache-failure-is-loud-and-results-equal",
       "CACHE disabled" in _cache_line(r.stdout) and "cache" in r.stderr.lower() and _finding_lines(r.stdout) == _finding_lines(ref.stdout),
       f"{_cache_line(r.stdout)[:80]} | stderr={r.stderr.strip()[:60]}")


def test_concurrent_runs_share_one_store():
    """T29: two audits started together on an empty store both succeed, neither disables the cache, and the store stays intact."""
    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ, VAULT_INDEX_DB=str(Path(td) / "idx.sqlite3"))
        cmd = [sys.executable, str(AUDIT), "--min", "info", "--limit", "100000", "--check", "headings,size,frontmatter,katex"]
        procs = [subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", cwd=str(VAULT_DIR), env=env) for _ in range(2)]
        outs = [p.communicate(timeout=600) for p in procs]
        con = sqlite3.connect(str(Path(td) / "idx.sqlite3"))
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        rows = con.execute("SELECT COUNT(*) FROM audit_cas_cache").fetchone()[0]
        con.close()
        ok("T29-concurrent-runs-safe",
           all(p.returncode in (0, 1) for p in procs) and all("CACHE disabled" not in o[0] for o in outs) and integrity == "ok" and rows > (1000 if sum(1 for _ in VAULT_DIR.rglob("*.md")) > 500 else 10),
           f"rc={[p.returncode for p in procs]} integrity={integrity} rows={rows}")


def test_code_fingerprint_follows_dynamic_imports():
    """T30: a module imported by name (optional_module("x")) is part of the code fingerprint without being listed anywhere."""
    from _vaultlib import code_fingerprint
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "entry.py").write_text("import helper\nx = optional_module('zz')\n", encoding="utf-8")
        (d / "helper.py").write_text("A = 1\n", encoding="utf-8")
        (d / "zz.py").write_text("B = 1\n", encoding="utf-8")
        (d / "unrelated.py").write_text("C = 1\n", encoding="utf-8")
        f1 = code_fingerprint(d / "entry.py")
        (d / "unrelated.py").write_text("C = 2\n", encoding="utf-8")
        f2 = code_fingerprint(d / "entry.py")
        (d / "zz.py").write_text("B = 2\n", encoding="utf-8")
        f3 = code_fingerprint(d / "entry.py")
        (d / "helper.py").write_text("A = 2\n", encoding="utf-8")
        f4 = code_fingerprint(d / "entry.py")
        ok("T30-fingerprint-follows-dynamic-and-static-imports-only", f1 == f2 and f3 != f2 and f4 != f3, "an unrelated file does not change it; zz (dynamic) and helper (static) do")


def test_red_team_regressions():
    """T31 to T34: the four breaks a red-team agent confirmed in M04 stay fixed (AD13, 2026-11-13): a datetime `due`, a date used
    as a front matter key, a note that is not valid UTF-8, and a dangling `.md` symlink. None may crash the audit, cached
    and uncached runs must agree, and the two file-integrity problems must be reported, not skipped."""
    with tempfile.TemporaryDirectory() as td:
        v = _clone(td)
        (v / "rt-due.md").write_text("---\ntags:\n  - ai-agent\ncreated: 2026-11-13\nstatus: active\ndue: 2020-01-01 10:00:00\n---\n# T\n", encoding="utf-8")
        (v / "rt-key.md").write_text("---\ntags:\n  - ai-agent\ncreated: 2026-11-13\n2026-01-01: b\n---\n# T\n", encoding="utf-8")
        (v / "rt-bad.md").write_bytes(b"---\ntags:\n  - ai-agent\n---\n# T\n\xff\xfe\n")
        try:
            os.symlink("/nonexistent/target", v / "rt-broken.md")
        except OSError:   # Windows without the symlink privilege: the other three inputs still run
            pass
        base = ["--min", "info", "--limit", "100000"]
        cold = _audit(base, v)
        warm = _audit(base, v)
        unc = _audit([*base, "--no-cache"], v)
        ok("T31-none-of-the-four-inputs-crashes-the-audit",
           all("Traceback" not in r.stderr and any(l.startswith("SUMMARY") for l in r.stdout.splitlines()) for r in (cold, warm, unc)),
           f"{[r.stderr.strip()[-60:] for r in (cold, warm, unc) if 'Traceback' in r.stderr][:1]}")
        ok("T32-cached-equals-uncached-on-those-inputs", _finding_lines(warm.stdout) == _finding_lines(unc.stdout) == _finding_lines(cold.stdout),
           f"warm={len(_finding_lines(warm.stdout))} uncached={len(_finding_lines(unc.stdout))}")
        lines = _finding_lines(warm.stdout)
        ok("T33-invalid-utf8-and-broken-symlink-are-reported",
           any("FM-file-invalid-utf8" in l and "rt-bad.md" in l for l in lines) and any("FM-file-broken-symlink" in l and "rt-broken.md" in l for l in lines),
           "both findings present")
        ok("T34-a-datetime-due-still-yields-the-overdue-finding-on-a-cache-hit", any("DUE-now" in l and "rt-due.md" in l for l in lines), "DUE-now for rt-due.md")


def main():
    test_fingerprint_invalidation()
    test_profile_change_end_to_end()
    test_db_structure()
    test_cache_population_and_data_integrity()
    test_warm_audit_speed()
    test_accuracy_match()
    test_transient_cross_file_detection()
    test_graceful_fallback()
    test_equivalence_live_tree()
    test_equivalence_after_mutations()
    test_status_line_and_warm_hits()
    test_corrupt_db_rebuilds_loudly()
    test_forced_cache_failure_is_loud()
    test_concurrent_runs_share_one_store()
    test_code_fingerprint_follows_dynamic_imports()
    test_red_team_regressions()
    
    passed = sum(1 for _, c, _ in R if c)
    total = len(R)
    print(f"\nAUDIT-CAS-TESTS: {passed}/{total} passed")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
