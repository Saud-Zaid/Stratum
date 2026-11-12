# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Tests for upgrade_core.py and restore_pre_upgrade.py. Releases are built in memory, every case works in a temporary
vault, and nothing touches the network. Usage: AI-Agent/vault-python AI-Agent/scripts/upgrade_core-tests.py"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import restore_pre_upgrade as RP
import upgrade_core as U

R = []
HERE = Path(__file__).resolve().parent


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


tmps = []


def tmp():
    d = Path(tempfile.mkdtemp(prefix="upgrade-"))
    tmps.append(d)
    return d


def release(version, files, critical=(), migrations=(), breaking=(), cli=(), fv=2):
    """files: {rel: (text, policy)} -> a Source over an in-memory directory tree."""
    d = tmp()
    entries = {}
    for rel, (text, pol) in files.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_bytes(text.encode("utf-8"))   # bytes, so Windows does not turn \n into \r\n and break the hash
        entries[rel] = {"sha256": U.sha256(text.encode("utf-8")), "policy": pol}
    man = {"format_version": fv, "version": version, "files": entries, "critical": list(critical), "migrations": list(migrations),
           "breaking_changes": list(breaking), "cli_migrations": list(cli)}
    (d / "release_manifest.json").write_text(json.dumps(man), encoding="utf-8", newline="")
    return U.Source.from_dir(d), d


def up(root, src, **kw):
    lines = []
    rc = U.run_upgrade(root, src, out=lines.append, **kw)
    return rc, "\n".join(lines)


def read(root, rel):
    return (root / rel).read_text(encoding="utf-8")


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


try:
    # ---- the line-based merge
    base = "a\nb\nc\nd\ne\nf\ng\n"
    t, n = U._pure_python_diff3(base, "A\nb\nc\nd\ne\nf\ng\n", "a\nb\nc\nd\ne\nf\nG\n")
    ok("M01-distant-edits-merge-cleanly", n == 0 and t == "A\nb\nc\nd\ne\nf\nG\n", (n, t))
    t, n = U._pure_python_diff3(base, "a\nX\nc\nd\ne\nf\ng\n", "a\nY\nc\nd\ne\nf\ng\n")
    ok("M02-same-line-two-edits-conflict-with-markers", n == 1 and "<<<<<<< local" in t and "||||||| base" in t and ">>>>>>> upstream" in t, t)
    t, n = U._pure_python_diff3(base, "a\nX\nc\nd\ne\nf\ng\n", "a\nX\nc\nd\ne\nf\nG\n")
    ok("M03-the-same-change-on-both-sides-is-not-a-conflict", n == 0 and t == "a\nX\nc\nd\ne\nf\nG\n", (n, t))
    t, n = U._pure_python_diff3(base, "a\nX\nc\nd\ne\nf\ng\n", "a\nb\nY\nd\ne\nf\ng\n")
    ok("M04-adjacent-hunks-count-as-overlapping", n == 1, (n, t))
    t, n = U._pure_python_diff3("", "x\n", "y\n")
    ok("M05-two-different-additions-to-an-empty-base-conflict", n == 1)
    t, n = U._pure_python_diff3(base, base, "a\nb\nc\nd\ne\nf\nG\n")
    ok("M06-an-unchanged-local-takes-upstream", n == 0 and t.endswith("G\n"))
    t2, n2, eng = U.merge3(base, "A\nb\nc\nd\ne\nf\ng\n", "a\nb\nc\nd\ne\nf\nG\n")
    ok("M07-merge3-engine-agrees-with-the-pure-python-result-on-a-clean-merge", n2 == 0 and t2 == "A\nb\nc\nd\ne\nf\nG\n", (eng, n2, t2))
    t2, n2, eng = U.merge3(base, "a\nX\nc\nd\ne\nf\ng\n", "a\nY\nc\nd\ne\nf\ng\n")
    ok("M08-merge3-reports-the-conflict", n2 >= 1 and "<<<<<<<" in t2, (eng, n2))

    # ---- fresh install, no-op, multi-hop
    v100 = {"AI-Agent/core.py": ("core v1\n", "replace"), "AI-Agent/notes.md": ("# n\nl1\nl2\nl3\nl4\nl5\nl6\n", "merge"),
            "AI-Agent/gone.txt": ("old\n", "replace"), "user.md": ("mine\n", "keep"), "seed.md": ("seed\n", "add-only"),
            "cfg/plugins.json": ('["a"]\n', "union"), "cfg/app.json": ('{"x": 1}\n', "json-merge")}
    s100, _ = release("1.0.0", v100)
    root = tmp()
    rc, out = up(root, s100)
    ok("U01-fresh-install-adds-everything-and-records-the-release", rc == 0 and read(root, "AI-Agent/core.py") == "core v1\n" and json.loads(read(root, U.INSTALLED))["version"] == "1.0.0" and not (root / "user.md").exists(), out)
    ok("U02-merge-files-get-a-base-copy", read(root, ".vault-release/base/AI-Agent/notes.md").startswith("# n"))
    rc, out = up(root, s100)
    ok("U03-same-version-is-a-no-op", rc == 0 and "nothing to do" in out)
    ok("U04-check-is-clean-right-after-an-install", U.check(root, out=lambda *_: None) == 0)

    (root / "AI-Agent/notes.md").write_text("# n\nL1 mine\nl2\nl3\nl4\nl5\nl6\n", encoding="utf-8", newline="")      # a local edit near the top
    (root / "user.md").write_text("my own note\n", encoding="utf-8", newline="")
    (root / "cfg/plugins.json").write_text('["a", "mine"]\n', encoding="utf-8", newline="")
    (root / "cfg/app.json").write_text('{"x": 9}\n', encoding="utf-8", newline="")
    v110 = {"AI-Agent/core.py": ("core v2\n", "replace"), "AI-Agent/notes.md": ("# n\nl1\nl2\nl3\nl4\nl5\nL6 theirs\n", "merge"),
            "user.md": ("SHOULD NOT LAND\n", "keep"), "seed.md": ("seed 2\n", "add-only"), "AI-Agent/new.py": ("new\n", "replace"),
            "cfg/plugins.json": ('["a", "b"]\n', "union"), "cfg/app.json": ('{"x": 1, "y": 2}\n', "json-merge")}
    s110, _ = release("1.1.0", v110)
    snap = snapshot(root)
    rc, out = up(root, s110, dry_run=True)
    ok("U05-dry-run-prints-the-plan-and-writes-nothing", rc == 0 and "UPDATE  AI-Agent/core.py" in out and snapshot(root) == snap, out)
    rc, out = up(root, s110)
    ok("U06-replace-updates-an-unmodified-file-and-adds-new-ones", rc == 0 and read(root, "AI-Agent/core.py") == "core v2\n" and read(root, "AI-Agent/new.py") == "new\n", out)
    ok("U07-merge-keeps-the-local-edit-and-takes-the-upstream-one", read(root, "AI-Agent/notes.md") == "# n\nL1 mine\nl2\nl3\nl4\nl5\nL6 theirs\n", read(root, "AI-Agent/notes.md"))
    ok("U08-keep-and-add-only-are-never-overwritten", read(root, "user.md") == "my own note\n" and read(root, "seed.md") == "seed\n")
    ok("U09-union-and-json-merge-keep-local-values-and-add-upstream-ones", json.loads(read(root, "cfg/plugins.json")) == ["a", "mine", "b"] and json.loads(read(root, "cfg/app.json")) == {"x": 9, "y": 2}, (read(root, "cfg/plugins.json"), read(root, "cfg/app.json")))
    ok("U10-removed-upstream-and-unmodified-is-deleted", not (root / "AI-Agent/gone.txt").exists(), out)

    # ---- a second hop with a rename, a deletion and a replace conflict
    (root / "AI-Agent/new.py").write_text("new, edited locally\n", encoding="utf-8", newline="")
    v120 = {"AI-Agent/core.py": ("core v3\n", "replace"), "AI-Agent/new.py": ("new v2\n", "replace"), "lib/moved.py": ("core v3 moved\n", "replace"),
            "AI-Agent/notes.md": ("# n\nl1\nl2\nl3\nl4\nl5\nL6 theirs\n", "merge")}
    mig = [{"from": "1.1.0", "to": "1.2.0", "steps": [{"op": "rename", "from": "AI-Agent/core.py", "to": "lib/old_core.py"}, {"op": "delete", "path": "cfg/app.json"}]}]
    s120, _ = release("1.2.0", v120, migrations=mig)
    rc, out = up(root, s120)
    ok("H01-second-hop-applies-the-migration-then-the-content", (root / "lib/old_core.py").is_file() and not (root / "cfg/app.json").exists() and read(root, "lib/moved.py") == "core v3 moved\n", out)
    ok("H02-a-locally-edited-replace-file-is-kept-and-the-upstream-copy-is-parked", read(root, "AI-Agent/new.py") == "new, edited locally\n" and read(root, ".vault-release/conflicts/AI-Agent/new.py.upstream") == "new v2\n" and rc == 1, out)
    (root / "orphan.txt").write_text("x\n", encoding="utf-8", newline="")
    r7 = tmp()
    so1, _ = release("1.0.0", {"keep_me.txt": ("v1\n", "replace"), "stay.txt": ("s\n", "replace")})
    up(r7, so1)
    (r7 / "keep_me.txt").write_text("edited locally\n", encoding="utf-8", newline="")
    so2, _ = release("1.1.0", {"stay.txt": ("s\n", "replace")})
    rc7, out7 = up(r7, so2)
    ok("H03-a-removed-upstream-file-that-was-modified-locally-is-kept-and-reported", read(r7, "keep_me.txt") == "edited locally\n" and "orphan-kept" in out7 and rc7 == 1, out7)
    ok("H04-installed-version-is-the-new-one-and-the-conflicted-file-stays-modified-against-its-base", json.loads(read(root, U.INSTALLED))["version"] == "1.2.0" and U.check(root, out=lambda *_: None) == 1)

    # ---- critical conflict: HIGH conflict-skew writes nothing
    r2 = tmp()
    up(r2, s100)
    (r2 / "AI-Agent/core.py").write_text("locally changed core\n", encoding="utf-8", newline="")
    sk, _ = release("1.1.0", {"AI-Agent/core.py": ("core v2\n", "replace")}, critical=["AI-Agent/core.py"])
    snap = snapshot(r2)
    rc, out = up(r2, sk, dry_run=True)
    rc2, out2 = up(r2, sk)
    ok("C01-a-modified-critical-file-stops-the-upgrade-with-nothing-written-to-the-tree", rc == 1 and rc2 == 1 and "HIGH conflict-skew" in out2 and read(r2, "AI-Agent/core.py") == "locally changed core\n" and not (r2 / ".vault-release/backups").exists(), out2)

    # ---- merge conflict
    r3 = tmp()
    up(r3, s100)
    (r3 / "AI-Agent/notes.md").write_text("# n\nL1 mine\nl2\nl3\nl4\nl5\nl6\n", encoding="utf-8", newline="")
    sc, _ = release("1.1.0", {"AI-Agent/notes.md": ("# n\nL1 theirs\nl2\nl3\nl4\nl5\nl6\n", "merge")})
    rc, out = up(r3, sc)
    parked = (r3 / ".vault-release/conflicts/AI-Agent/notes.md")
    ok("C02-an-overlapping-merge-keeps-local-and-parks-a-file-with-markers", rc == 1 and "L1 mine" in read(r3, "AI-Agent/notes.md") and "<<<<<<<" in parked.read_text(encoding="utf-8") and "CONFLICT" in out, out)

    # ---- tamper, Zip Slip, archives
    r4 = tmp()
    st, d = release("1.1.0", {"AI-Agent/core.py": ("core v2\n", "replace")})
    (d / "AI-Agent/core.py").write_text("evil\n", encoding="utf-8", newline="")
    try:
        up(r4, st)
        raised = False
    except U.UpgradeError:
        raised = True
    ok("S01-a-member-that-does-not-match-the-manifest-hash-stops-everything", raised and not (r4 / "AI-Agent").exists())
    for bad in ("../x", "/etc/passwd", "a\\b", "C:/x", ".git/config", ""):
        try:
            U.safe_rel(bad)
            refused = False
        except U.UpgradeError:
            refused = True
        ok(f"S02-safe_rel-refuses-{bad!r}", refused)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("rel/release_manifest.json", json.dumps({"format_version": 2, "version": "1.0.0", "files": {"../evil.txt": {"sha256": "0" * 64, "policy": "replace"}}}))
    try:
        U.Source.from_zip_bytes(buf.getvalue(), "evil.zip")
        raised = False
    except U.UpgradeError:
        raised = True
    ok("S03-a-zip-slip-path-in-the-manifest-is-rejected", raised)
    zp = tmp() / "rel.zip"
    sd = Path(s110.label)
    with zipfile.ZipFile(zp, "w") as z:
        for f in sorted(sd.rglob("*")):
            if f.is_file():
                z.write(f, "stratum-1.1.0/" + f.relative_to(sd).as_posix())
    zs = U.Source.open(str(zp))
    ok("S04-a-zip-with-one-top-folder-is-read-in-memory", zs.manifest["version"] == "1.1.0" and zs.read("AI-Agent/core.py") == b"core v2\n")
    for spec, kw in (("gh:v1.1.0", {}), ("https://evil.example.com/r.zip", {"expect_sha": "a" * 64}), ("https://github.com/o/r/r.zip", {}), ("http://github.com/o/r/r.zip", {"expect_sha": "a" * 64}), (str(zp), {"expect_sha": "0" * 64}), (str(tmp()), {})):
        try:
            U.Source.open(spec, **kw)
            refused = False
        except U.UpgradeError:
            refused = True
        ok(f"S05-source-refused-{spec[:34]}", refused)
    for bad in ({"format_version": 3, "version": "1.0.0", "files": {}}, {"format_version": 2, "version": "x.y", "files": {}},
                {"format_version": 2, "version": "1.0.0", "files": {"a": {"sha256": "1", "policy": "replace"}}},
                {"format_version": 2, "version": "1.0.0", "files": {"a": {"sha256": "0" * 64, "policy": "run-it"}}},
                {"format_version": 2, "version": "1.0.0", "files": {}, "migrations": [{"from": "1.0.0", "to": "1.1.0", "steps": [{"op": "python", "path": "x.py"}]}]}):
        try:
            U.load_manifest(json.dumps(bad).encode())
            refused = False
        except U.UpgradeError:
            refused = True
        ok(f"S06-manifest-refused-{str(bad)[:44]}", refused)
    m1 = U.load_manifest(json.dumps({"format_version": 1, "version": "1.0.0", "files": {}, "breaking_changes": [{"id": "x"}]}).encode())
    ok("S07-a-v1-manifest-has-no-review-items", m1["breaking_changes"] == [] and m1["critical"] == [])

    # ---- breaking changes need --ack
    r5 = tmp()
    up(r5, s100)
    sb, _ = release("1.1.0", {"AI-Agent/core.py": ("core v2\n", "replace")}, breaking=[{"id": "BC-1", "summary": "flag renamed"}], cli=[{"old": "--a", "new": "--b", "since": "1.1.0"}])
    rc, out = up(r5, sb)
    pr = json.loads(read(r5, ".vault-release/pending-review.json")) if (r5 / ".vault-release/pending-review.json").is_file() else {}
    ok("B01-breaking-changes-stop-the-upgrade-and-write-pending-review", rc == 1 and read(r5, "AI-Agent/core.py") == "core v1\n" and [i["kind"] for i in pr.get("items", [])] == ["breaking_change", "cli_migration"], out)
    rc, out = up(r5, sb, ack=True)
    ok("B02-ack-lets-it-through-and-clears-the-pending-file", rc == 0 and read(r5, "AI-Agent/core.py") == "core v2\n" and not (r5 / ".vault-release/pending-review.json").exists(), out)

    # ---- backup and restore
    r6 = tmp()
    up(r6, s100)
    (r6 / "AI-Agent/core.py").write_text("core v1\n", encoding="utf-8", newline="")
    before = snapshot(r6)
    rc, out = up(r6, s110)
    ok("R01-the-upgrade-made-a-backup-before-writing", rc == 0 and len(RP.backups(r6)) == 1, out)
    ok("R02-the-tree-changed", snapshot(r6) != before and (r6 / "AI-Agent/new.py").exists())
    rc = RP.restore(r6, RP.backups(r6)[-1], out=lambda *_: None)
    after = {k: v for k, v in snapshot(r6).items() if not k.startswith(".vault-release/backups/") and not k.startswith(".vault-release/conflicts/")}
    prev = {k: v for k, v in before.items() if not k.startswith(".vault-release/backups/")}
    ok("R03-restore-puts-back-every-changed-file-byte-for-byte-and-removes-added-ones", rc == 0 and after == prev, sorted(set(after) ^ set(prev)))
    bz = RP.backups(r6)[-1]
    data = bytearray(bz.read_bytes())
    with zipfile.ZipFile(bz) as zf:
        members = {n: zf.read(n) for n in zf.namelist()}
    members["files/AI-Agent/core.py"] = b"tampered backup\n"
    with zipfile.ZipFile(bz, "w") as zf:
        for n, b in members.items():
            zf.writestr(n, b)
    snap = snapshot(r6)
    msgs = []
    rc_t = RP.restore(r6, bz, out=lambda *a: msgs.append(" ".join(map(str, a))))
    now = snapshot(r6)
    ok("R04-a-tampered-backup-is-refused-and-nothing-is-changed", rc_t == 1 and now == snap, (rc_t, msgs[:2], sorted(set(now) ^ set(snap))[:3]))
    (bz).write_bytes(b"not a zip")
    ok("R05-a-corrupt-backup-is-refused", RP.restore(r6, bz, out=lambda *_: None) == 1)

    # ---- the closing verification gate
    rv = tmp()
    up(rv, s100)
    (rv / "AI-Agent/scripts").mkdir(parents=True, exist_ok=True)
    (rv / "AI-Agent/scripts/audit.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8", newline="")
    sv, _ = release("1.1.0", {"AI-Agent/core.py": ("core v2\n", "replace")})
    rcv, outv = up(rv, sv, skip_verify=False)
    ok("V01-a-passing-audit-closes-the-upgrade-clean", rcv == 0 and "GATE CLEAR" in outv, outv)
    rv2 = tmp()
    up(rv2, s100)
    (rv2 / "AI-Agent/scripts").mkdir(parents=True, exist_ok=True)
    (rv2 / "AI-Agent/scripts/audit.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8", newline="")
    rcv2, outv2 = up(rv2, sv, skip_verify=False)
    ok("V02-a-failing-audit-exits-1-and-names-the-restore-command", rcv2 == 1 and "restore_pre_upgrade.py --from .vault-release/backups/" in outv2, outv2)
    ok("V03-the-named-backup-restores-the-tree-after-a-failed-verification", RP.restore(rv2, RP.backups(rv2)[-1], out=lambda *_: None) == 0 and read(rv2, "AI-Agent/core.py") == "core v1\n")

    # ---- CLI
    def cli(mod, *a, root=None):
        return subprocess.run([sys.executable, str(HERE / mod), *a], capture_output=True, text=True, env=dict(os.environ, VAULT=str(root or tmp())), timeout=60)
    ok("X01-help-rc0-unknown-flag-rc2-for-both-tools", all(cli(m, "--help").returncode == 0 and cli(m, "--bogus").returncode == 2 for m in ("upgrade_core.py", "restore_pre_upgrade.py")))
    rr = tmp()
    c = cli("upgrade_core.py", "--from", s100.label, "--yes", "--no-sync", "--skip-verify", root=rr)
    ok("X02-cli-installs-a-release-directory", c.returncode == 0 and (rr / "AI-Agent/core.py").is_file(), c.stdout[-200:] + c.stderr[-200:])
    ok("X03-cli-check-and-bad-source-exit-codes", cli("upgrade_core.py", "--check", root=rr).returncode == 0 and cli("upgrade_core.py", "--from", "/nonexistent", "--yes", root=rr).returncode == 2 and cli("upgrade_core.py", root=rr).returncode == 2)
    ok("X04-restore-cli-lists-and-reports-no-backup", cli("restore_pre_upgrade.py", "--list", root=rr).returncode == 0 and cli("restore_pre_upgrade.py", "--yes", root=rr).returncode == 1)
    # ---- versions: SemVer precedence with pre-releases
    V = U.vtuple
    chain_ = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0", "1.0.1", "1.1.0", "2.0.0"]
    ok("V01-semver-precedence-order", sorted(chain_, key=V) == chain_, sorted(chain_, key=V))
    bad_v = []
    for v_ in ("1.0", "1.0.0-", "1.0.0+build", "v1.0.0", "1.0.0-beta..1", "x.y.z", ""):
        try:
            V(v_)
            bad_v.append(v_)
        except U.UpgradeError:
            pass
    ok("V02-malformed-versions-are-refused", bad_v == [], bad_v)
    sb1, _ = release("1.0.0-beta.1", {"core.txt": ("b1\n", "replace")})
    sfin, _ = release("1.0.0", {"core.txt": ("final\n", "replace")})
    rb = tmp()
    rc1, _ = up(rb, sb1)
    rc2, _ = up(rb, sfin)
    ok("V03-a-beta-installs-then-the-final-release-upgrades-it", rc1 == 0 and rc2 == 0 and read(rb, "core.txt") == "final\n"
       and json.loads(read(rb, U.INSTALLED))["version"] == "1.0.0", (rc1, rc2))
    rc3, out3 = up(rb, sb1)
    ok("V04-an-older-beta-does-not-downgrade-a-final-release", read(rb, "core.txt") == "final\n", out3[-150:])
finally:
    for d in tmps:
        shutil.rmtree(d, ignore_errors=True)

failed = [r for r in R if not r[1]]
for name, passed, got in R:
    print(("PASS " if passed else "FAIL ") + name + ("" if passed else f" -> {got}"))
print(f"UPGRADE-CORE-TESTS {len(R) - len(failed)}/{len(R)}")
sys.exit(1 if failed else 0)
