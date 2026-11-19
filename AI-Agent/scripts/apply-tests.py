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


def _U(s):
    """ASCII-escaped test data: the shipped sources hold no Arabic literal (the release gate reads decoded strings too)."""
    return s.encode("ascii").decode("unicode_escape")


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
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)


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
    keep = _mkfile(_rel("t5-keep.md"), "keep-original")
    # a plain file where the second operation needs a folder: its write fails on every system and for every user (no permission bits)
    ro_dir = _mkfile(_rel("t5-ro-dir"), "a file, not a folder")
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
    _rm(ro_dir)
    _rm(keep)


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

# ---------------------------------------------------------------------------------------------------------------
# AD13 D1: block edits, receipts, atomic writes. These run in a temporary vault (ap.VAULT is swapped for the run).
# ---------------------------------------------------------------------------------------------------------------
import hashlib
import random
import shutil

REAL_VAULT = ap.VAULT
TV = tempfile.mkdtemp(prefix="apply-d1-")


def chk(name, cond, detail=""):
    ok(name) if cond else fail(name, detail)


def tv(name):
    return os.path.join(TV, name)


def put(name, text, mode="w"):
    full = tv(name)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, mode, encoding=None if "b" in mode else "utf-8", newline=None if "b" in mode else "") as f:
        f.write(text)
    return full


def get(name):
    with open(tv(name), "rb") as f:
        return f.read()


def run(ops, dry=False):
    """Run the real entry point (a subprocess) against the temporary vault; returns (rc, json, stdout+stderr)."""
    pf = os.path.join(TV, "_plan.json")
    with open(pf, "w", encoding="utf-8") as f:
        json.dump({"operations": ops}, f, ensure_ascii=False)
    r = subprocess.run([sys.executable, SCRIPT, "--plan", pf] + (["--dry-run"] if dry else []),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, env={**os.environ, "VAULT": TV})
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        out = {}
    return r.returncode, out, r.stdout + r.stderr


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def tmp_files():
    return [n for _d, _s, fs in os.walk(TV) for n in fs if n.endswith(".tmp")]


try:
    ap.VAULT = TV
    # edits: unique replace, multi-edit sequence, receipts
    put("n.md", "alpha\nbeta\ngamma\n")
    rc, out, _ = run([{"path": "n.md", "edits": [{"old": "beta", "new": "BETA"}, {"old": "BETA\ngamma", "new": "BETA\nGAMMA"}]}])
    chk("t11_edits_apply_in_sequence", rc == 0 and get("n.md") == b"alpha\nBETA\nGAMMA\n" and out["receipts"][0]["edits_applied"] == 2, (rc, out))
    rc_ = out["receipts"][0]
    chk("t12_receipt_matches_disk", rc_["after_sha"] == sha256(get("n.md")) and rc_["before_sha"] == sha256(b"alpha\nbeta\ngamma\n")
        and rc_["lines_changed"] == 4 and rc_["bytes_after"] == len(get("n.md")), rc_)
    # ambiguity / not found: whole batch aborts, nothing written (also the other file of the batch)
    put("a.md", "x\nx\n")
    put("b.md", "keep\n")
    rc, out, _ = run([{"path": "b.md", "edits": [{"old": "keep", "new": "CHANGED"}]}, {"path": "a.md", "edits": [{"old": "x", "new": "y"}]}])
    chk("t13_ambiguous_old_aborts_whole_batch", rc == 1 and out["status"] == "aborted" and get("b.md") == b"keep\n" and get("a.md") == b"x\nx\n"
        and "ambiguous" in out["errors"][0], (rc, out))
    rc, out, _ = run([{"path": "a.md", "edits": [{"old": "nope", "new": "y"}]}])
    chk("t14_missing_old_aborts", rc == 1 and "not found" in out["errors"][0] and get("a.md") == b"x\nx\n", out)
    # idempotence
    put("i.md", "one two three\n")
    plan = [{"path": "i.md", "edits": [{"old": "two", "new": "2"}]}]
    run(plan)
    rc, out, _ = run(plan)
    chk("t15_rerun_is_already_applied_and_byte_identical", rc == 0 and out["receipts"][0]["edits_already_applied"] == 1
        and out["receipts"][0]["unchanged"] and get("i.md") == b"one 2 three\n", out)
    put("g.md", "a\n")
    plan = [{"path": "g.md", "edits": [{"old": "a", "new": "a b"}]}]
    run(plan)
    rc, out, _ = run(plan)
    chk("t16_new_contains_old_is_not_called_already_applied", get("g.md") == b"a b b\n" and out["receipts"][0]["edits_already_applied"] == 0
        and out["receipts"][0]["edits_applied"] == 1, (get("g.md"), out))
    sha0 = sha256(get("g.md"))
    rc, out, _ = run([{"path": "g.md", "ifMatch": sha256(b"a\n"), "edits": [{"old": "a", "new": "a b"}]}])
    chk("t17_ifmatch_protects_the_non_idempotent_case", rc == 1 and "ifMatch" in out["errors"][0] and sha256(get("g.md")) == sha0, out)
    # ifMatch chain: the before_sha of a receipt guards the next plan
    put("c.md", "v1\n")
    rc, out1, _ = run([{"path": "c.md", "ifMatch": sha256(b"v1\n"), "edits": [{"old": "v1", "new": "v2"}]}])
    rc2, out2, _ = run([{"path": "c.md", "ifMatch": out1["receipts"][0]["before_sha"], "edits": [{"old": "v2", "new": "v3"}]}])
    chk("t18_stale_ifmatch_after_a_concurrent_change_aborts", rc == 0 and rc2 == 1 and get("c.md") == b"v2\n", (out1, out2))
    # CRLF
    put("w.md", "a\r\nb\r\nc\r\n", "wb") if False else put("w.md", "a\r\nb\r\nc\r\n")
    rc, out, _ = run([{"path": "w.md", "edits": [{"old": "b\r\n", "new": "B\r\n"}]}])
    chk("t19_crlf_kept_byte_exact", rc == 0 and get("w.md") == b"a\r\nB\r\nc\r\n", get("w.md"))
    rc_exact, _, _ = run([{"path": "w.md", "expectedContent": "a\r\nB\r\nc\r\n", "newContent": "z"}], dry=True)
    rc_lf, _, _ = run([{"path": "w.md", "expectedContent": "a\nB\nc\n", "newContent": "z"}], dry=True)
    chk("t20_expectedcontent_is_byte_exact_for_crlf", rc_exact == 0 and rc_lf == 1)
    # same path twice: folded, written once; rollback restores the ORIGINAL
    put("s.md", "ORIG")
    rc, out, _ = run([{"path": "s.md", "newContent": "ONE"}, {"path": "s.md", "edits": [{"old": "ONE", "new": "TWO"}]}])
    chk("t21_same_path_ops_are_folded", rc == 0 and get("s.md") == b"TWO" and len(out["receipts"]) == 1, (rc, out))
    put("s.md", "ORIG")
    put("p2.md", "P2")
    real_replace = os.replace
    calls = {"n": 0}

    def boom_second(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("injected")
        return real_replace(src, dst)

    os.replace = boom_second
    try:
        errs, files_, _r = ap.preflight([{"path": "s.md", "newContent": "ONE"}, {"path": "p2.md", "newContent": "NEW2"}])
        errs2, status = ap.commit(files_)
    finally:
        os.replace = real_replace
    chk("t22_failure_after_first_write_restores_original_bytes", status == "rolled_back" and get("s.md") == b"ORIG" and get("p2.md") == b"P2"
        and not tmp_files(), (status, get("s.md"), errs2))
    # crash injection at every write step of a four-file batch
    names = ["k%d.md" % i for i in range(4)]
    for k in range(1, 5):
        for n in names:
            put(n, "orig-" + n)
        calls["n"] = 0

        def boom_k(src, dst, k=k):
            calls["n"] += 1
            if calls["n"] == k:
                raise OSError("injected at %d" % k)
            return real_replace(src, dst)

        os.replace = boom_k
        try:
            e, fl, _r = ap.preflight([{"path": n, "newContent": "new-" + n} for n in names])
            e2, st = ap.commit(fl)
        finally:
            os.replace = real_replace
        same = all(get(n) == ("orig-" + n).encode() for n in names)
        chk("t23_crash_at_write_%d_leaves_every_file_original" % k, st == "rolled_back" and same and not tmp_files(), (st, e2))
    # crash in the middle of a write: the original is intact, no temp file survives
    put("m.md", "ORIGINAL-CONTENT")
    real_fsync = os.fsync

    def bad_fsync(fd):
        raise OSError("disk full")

    os.fsync = bad_fsync
    try:
        e, fl, _r = ap.preflight([{"path": "m.md", "newContent": "NEW-CONTENT-LONG"}])
        e2, st = ap.commit(fl)
    finally:
        os.fsync = real_fsync
    chk("t24_mid_write_failure_keeps_original_and_no_tmp", st == "rolled_back" and get("m.md") == b"ORIGINAL-CONTENT" and not tmp_files(), (st, get("m.md")))
    # created file is removed on rollback
    put("r1.md", "R1")
    calls["n"] = 0

    def boom_2(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("x")
        return real_replace(src, dst)

    os.replace = boom_2
    try:
        e, fl, _r = ap.preflight([{"path": "newdir/created.md", "newContent": "C"}, {"path": "r1.md", "newContent": "R1X"}])
        e2, st = ap.commit(fl)
    finally:
        os.replace = real_replace
    chk("t25_created_file_removed_on_rollback", st == "rolled_back" and not os.path.exists(tv("newdir/created.md")) and get("r1.md") == b"R1")
    # sections
    doc = "---\ntitle: t\n---\n# Top\n\nintro\n\n## Alpha\n\nalpha body\n\n### Child\n\nchild body\n\n## Beta\n\nbeta body\n\n## " + _U(r"\u0642\u0633\u0645 \u0639\u0631\u0628\u064a") + "\n\n" + _U(r"\u0646\u0635 \u0642\u062f\u064a\u0645") + "\n"
    put("d.md", doc)
    rc, out, _ = run([{"path": "d.md", "section": "Beta", "newBody": "\nnew beta\n\n"}])
    got = get("d.md").decode()
    chk("t26_section_replaced_neighbours_byte_identical", rc == 0 and got == doc.replace("## Beta\n\nbeta body\n\n", "## Beta\n\nnew beta\n\n", 1), got)
    rc, out, _ = run([{"path": "d.md", "section": _U(r"\u0642\u0633\u0645 \u0639\u0631\u0628\u064a"), "newBody": "\n" + _U(r"\u0646\u0635 \u062c\u062f\u064a\u062f") + "\n"}])
    chk("t27_arabic_heading_section", rc == 0 and get("d.md").decode().endswith("## " + _U(r"\u0642\u0633\u0645 \u0639\u0631\u0628\u064a") + "\n\n" + _U(r"\u0646\u0635 \u062c\u062f\u064a\u062f") + "\n"), get("d.md").decode()[-60:])
    rc, out, _ = run([{"path": "d.md", "section": "Missing", "newBody": "x"}])
    chk("t28_missing_heading_aborts", rc == 1 and "not found" in out["errors"][0])
    put("dup.md", "## Same\n\na\n\n## Same\n\nb\n")
    rc, out, _ = run([{"path": "dup.md", "section": "Same", "newBody": "x"}])
    chk("t29_ambiguous_heading_aborts", rc == 1 and "ambiguous" in out["errors"][0] and get("dup.md") == b"## Same\n\na\n\n## Same\n\nb\n")
    put("crlf.md", "## A\r\n\r\nold\r\n\r\n## B\r\n\r\nkeep\r\n")
    rc, out, _ = run([{"path": "crlf.md", "section": "A", "newBody": "\nnew\n\n"}])
    chk("t30_section_edit_keeps_crlf", rc == 0 and get("crlf.md") == b"## A\r\n\r\nnew\r\n\r\n## B\r\n\r\nkeep\r\n", get("crlf.md"))
    # dry run
    put("dr.md", "before\n")
    rc, out, _ = run([{"path": "dr.md", "edits": [{"old": "before", "new": "after"}]}], dry=True)
    rc2, out2, _ = run([{"path": "dr.md", "edits": [{"old": "before", "new": "after"}]}])
    chk("t31_dry_run_writes_nothing_and_predicts_receipt", rc == 0 and out["status"] == "dry_run" and out["receipts"][0]["after_sha"] == out2["receipts"][0]["after_sha"]
        == sha256(get("dr.md")), (out, out2))
    # invalid plans: exit 2, one JSON line, no traceback
    for label, op in (("both-forms", {"path": "n.md", "newContent": "x", "edits": [{"old": "a", "new": "b"}]}),
                      ("no-form", {"path": "n.md"}),
                      ("empty-edits", {"path": "n.md", "edits": []}),
                      ("empty-old", {"path": "n.md", "edits": [{"old": "", "new": "b"}]}),
                      ("bad-ifmatch", {"path": "n.md", "ifMatch": "abc", "newContent": "x"}),
                      ("section-without-body", {"path": "n.md", "section": "A"}),
                      ("non-string-new", {"path": "n.md", "edits": [{"old": "a", "new": 3}]})):
        rc, out, text = run([op])
        chk("t32_invalid_plan_%s_exit_2" % label, rc == 2 and out.get("status") == "invalid" and "Traceback" not in text, (rc, text[:150]))
    # plan from stdin
    put("st.md", "from stdin\n")
    r = subprocess.run([sys.executable, SCRIPT, "--plan", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, env={**os.environ, "VAULT": TV},
                       input=json.dumps({"operations": [{"path": "st.md", "edits": [{"old": "stdin", "new": "STDIN"}]}]}))
    chk("t38_plan_from_stdin", r.returncode == 0 and get("st.md") == b"from STDIN\n", (r.stdout, r.stderr))
    r = subprocess.run([sys.executable, SCRIPT, "--plan", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, env={**os.environ, "VAULT": TV}, input="{bad")
    chk("t39_bad_stdin_plan_exit_2", r.returncode == 2 and "Traceback" not in r.stdout + r.stderr, (r.returncode, r.stdout))
    # non-UTF-8 file, sandbox escape, symlink out
    with open(tv("bin.md"), "wb") as f:
        f.write(b"\xff\xfe\x00bad")
    rc, out, text = run([{"path": "bin.md", "edits": [{"old": "a", "new": "b"}]}])
    chk("t33_non_utf8_file_aborts_cleanly", rc == 1 and "Traceback" not in text and get("bin.md") == b"\xff\xfe\x00bad", (rc, text[:150]))
    rc, out, _ = run([{"path": "../escape.md", "edits": [{"old": "a", "new": "b"}]}])
    chk("t34_edit_sandbox_escape_rejected", rc == 1 and "escapes" in out["errors"][0])
    outside = tempfile.mkdtemp(prefix="apply-out-")
    with open(os.path.join(outside, "o.md"), "w", encoding="utf-8") as f:
        f.write("secret\n")
    try:
        os.symlink(os.path.join(outside, "o.md"), tv("link.md"))
    except OSError as exc:   # Windows without the symlink privilege (WinError 1314): say so, do not fail
        print("SKIP t35_symlink_leaving_the_vault_rejected: cannot create a symlink here (%s)" % exc)
    else:
        rc, out, _ = run([{"path": "link.md", "edits": [{"old": "secret", "new": "x"}]}])
        chk("t35_symlink_leaving_the_vault_rejected", rc == 1 and open(os.path.join(outside, "o.md"), encoding="utf-8").read() == "secret\n", out)
    shutil.rmtree(outside, ignore_errors=True)
    # property test against an oracle: random texts, random unique-substring edits, random line endings
    rnd = random.Random(20261115)
    ALPHA = ["a", "b", "c", "$", "\\", "(", "[", _U(r"\u0639"), _U(r"\u0628"), _U(r"\u0643"), " ", "\n", "\r\n", "#", "|"]
    mism = amb_leak = 0
    for trial in range(300):
        text = "".join(rnd.choice(ALPHA) for _ in range(rnd.randint(5, 80)))
        put("prop.md", text)
        before = get("prop.md")
        i = rnd.randrange(len(text))
        j = min(len(text), i + rnd.randint(1, 6))
        old = text[i:j]
        new = "".join(rnd.choice(ALPHA) for _ in range(rnd.randint(0, 5)))
        rc, out, _ = run([{"path": "prop.md", "edits": [{"old": old, "new": new}]}])
        n = text.count(old)
        if n == 1:
            if rc != 0 or get("prop.md") != text.replace(old, new, 1).encode("utf-8"):
                mism += 1
        elif n > 1:
            if rc != 1 or get("prop.md") != before:
                amb_leak += 1
    chk("t36_property_300_random_edits_match_the_oracle", mism == 0 and amb_leak == 0, (mism, amb_leak))
    # negative control: the oracle comparison must be able to fail
    put("nc.md", "hello world\n")
    run([{"path": "nc.md", "edits": [{"old": "hello", "new": "bye"}]}])
    chk("t37_negative_control_wrong_oracle_differs", get("nc.md") != "hello world\n".replace("hello", "BYE", 1).encode())
    # AD13 D1 prior-art retrofit: a failed match says why (Aider's "did you mean"), an ambiguous one says where, the rename is made durable
    body = "".join("line %02d of the note, with some words in it\n" % n for n in range(1, 41))
    body = body.replace("line 07 of the note", "    indented block starts here\n    second indented line\nline 07 of the note", 1)
    put("hint.md", body)

    def msg(old, name="hint.md", extra=None):
        rc, out, _ = run([{"path": name, "edits": [{"old": old, "new": "X"}]}] + (extra or []))
        return rc, (out.get("errors") or [""])[0]
    rc, m = msg("  indented block starts here\n  second indented line\n")
    chk("t38_indentation_difference_is_named_with_its_lines", rc == 1 and "not found" in m and "differs only in leading or trailing whitespace" in m and "lines 7-8" in m, m)
    rc, m = msg("line 21 of the note, with some wrds in it\n")
    chk("t39_a_typo_gets_the_closest_text_with_line_and_similarity", rc == 1 and "closest text is at lines 23-23" in m and "similarity 0.9" in m and "line 21 of the note, with some words in it" in m, m)
    rc, m = msg("completely different text about nothing\nthat resembles no line here\n")
    chk("t40_nothing_close_means_no_hint", rc == 1 and m.rstrip().endswith("not found in hint.md") and "closest" not in m and "differs" not in m, m)
    put("crlf.md", b"alpha line\r\nbeta line\r\ngamma line\r\n", mode="wb")
    rc, m = msg("alpha line\nbeta line\n", name="crlf.md")
    chk("t41_line_ending_mismatch_is_named", rc == 1 and "CRLF" in m, m)
    put("amb.md", "".join("row %d\nsame text here\n" % n for n in range(1, 8)))
    rc, m = msg("same text here\n", name="amb.md")
    chk("t42_ambiguous_match_lists_where_it_starts", rc == 1 and "ambiguous (7 matches)" in m and "starts at lines 2, 4, 6, 8, 10, ..." in m, m)
    before = get("hint.md")
    rc, m = msg("line 21 of the note, with some wrds in it\n", extra=[{"path": "never.md", "newContent": "x"}])
    chk("t43_a_failed_match_still_aborts_the_whole_batch_untouched", rc == 1 and get("hint.md") == before and not os.path.exists(os.path.join(TV, "never.md")))
    big = "".join("generated line number %05d with some padding words\n" % n for n in range(30000))
    put("big.md", big)
    import time as _t
    t0 = _t.time()
    rc, m = msg("generated line number 15000 with some padding wrds\n", name="big.md")
    chk("t44_hint_on_a_30000_line_file_is_fast_and_right", rc == 1 and "lines 15001-15001" in m and _t.time() - t0 < 5, (m, _t.time() - t0))
    long_line = "word " * 200 + "\n"
    put("long.md", long_line)
    rc, m = msg("word " * 199 + "wrd\n", name="long.md")
    chk("t45_excerpt_is_capped", rc == 1 and len(m) < 700, len(m))
    # durability: the directory is fsynced after the rename, and a failure there never fails the write
    calls = []
    real_fsync, real_replace = os.fsync, os.replace
    try:
        os.replace = lambda a, b: (calls.append("replace"), real_replace(a, b))[1]
        os.fsync = lambda fd: (calls.append("dir-fsync" if os.path.isdir("/proc/self/fd/%d" % fd) else "file-fsync"), real_fsync(fd))[1]
        ap._write_atomic(os.path.join(TV, "dur.md"), "durable\n")
        order_ok = calls[-2:] == ["replace", "dir-fsync"]
        def boom(fd):
            raise OSError("no directory fsync here")
        os.fsync = lambda fd: boom(fd) if os.path.isdir("/proc/self/fd/%d" % fd) else real_fsync(fd)
        ap._write_atomic(os.path.join(TV, "dur2.md"), "still written\n")
        survived = open(os.path.join(TV, "dur2.md"), encoding="utf-8").read() == "still written\n"
    finally:
        os.fsync, os.replace = real_fsync, real_replace
    chk("t46_directory_fsync_follows_the_rename_and_cannot_fail_the_write", order_ok and survived, calls)
finally:
    ap.VAULT = REAL_VAULT
    shutil.rmtree(TV, ignore_errors=True)

print("SUITE %d/%d" % (passed, passed + failed))
sys.exit(1 if failed else 0)
