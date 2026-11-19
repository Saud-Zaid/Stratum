# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Tests for export_release.py (--plan / --check): rule matching, fail-closed coverage, and the real manifest against the real
vault. Fixtures are temporary git repositories. Usage: AI-Agent/vault-python AI-Agent/scripts/export_release-tests.py"""
from __future__ import annotations

import json
import time
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

import export_release as E
from _vaultlib import scrub_git_env
scrub_git_env()   # hook variables must not reach the temporary repositories below

R = []
HERE = Path(__file__).resolve().parent
REAL = HERE.parent.parent


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


tmps = []


def fixture(rules, files, overlay=(), keep=None, sanitizers=None, classification=None):
    d = Path(tempfile.mkdtemp(prefix="export-"))
    tmps.append(d)
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    man = {"version": 1, "keep": keep or {"scripts": {"governance": [], "operations": [], "release_tools": []}, "schema": [], "release_tool_count": 0},
           "sanitizers": sanitizers or {"implemented": ["obsidian"], "pending": ["scripts-english"]},
           "rules": rules + [{"id": "fixture-config", "action": "drop", "prefix": "AI-Agent/config/"}]}   # the two config files every fixture carries
    (d / "AI-Agent/config").mkdir(parents=True)
    (d / E.MANIFEST).write_text(yaml.safe_dump(man, allow_unicode=True), encoding="utf-8")
    (d / "AI-Agent/config/test-classification.yaml").write_text(yaml.safe_dump(classification or {"stratum_core": [], "mother_vault_drop": [], "excluded_duplicates": []}), encoding="utf-8")
    for rel in files:
        f = d / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x\n", encoding="utf-8")
    for rel in overlay:
        f = d / E.OVERLAY / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("o\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=d, check=True)
    return d


try:
    rules = [{"id": "keep-readme", "action": "copy", "path": "README.md"}, {"id": "drop-work", "action": "drop", "prefixes": ["01-Projects/", "02-Areas/"]},
             {"id": "scripts", "action": "sanitize", "via": "scripts-english", "glob": "AI-Agent/scripts/*.py"}, {"id": "never", "action": "drop", "path": "no/such/file"}]
    d = fixture(rules, ["README.md", "01-Projects/a.md", "02-Areas/b.md", "AI-Agent/scripts/x.py", "mystery.txt"])
    cl = E.classify(d)
    ok("E01-first-matching-rule-wins-and-actions-are-recorded", cl["files"]["README.md"] == ("copy", "keep-readme", "") and cl["files"]["01-Projects/a.md"][0] == "drop" and cl["files"]["AI-Agent/scripts/x.py"] == ("sanitize", "scripts", "scripts-english"), cl["files"])
    ok("E02-a-file-no-rule-names-is-unclassified", cl["unclassified"] == ["mystery.txt"], cl["unclassified"])
    ok("E03-a-rule-that-matches-nothing-is-reported-as-stale", cl["unused_rules"] == ["never"], cl["unused_rules"])
    plan = E.build_plan(d)
    ok("E04-unclassified-is-a-finding-that-stops-the-export", [f[0] for f in plan["findings"]] == ["UNCLASSIFIED"] and plan["pending_sanitizers"] == {"scripts-english": 1}, plan["findings"])

    d2 = fixture(rules[:2] + [{"id": "everything", "action": "drop", "prefix": ""}], ["README.md", "x/y.md"], overlay=["README.md", "NEW.md"])
    cl2 = E.classify(d2)
    ok("E05-an-overlay-path-wins-before-any-rule-is-read", cl2["files"]["README.md"] == ("overlay", "overlay", "") and cl2["overlay_new"] == ["NEW.md"] and cl2["files"]["NEW.md"][0] == "overlay", cl2)
    ok("E06-overlay-only-files-are-counted-and-the-total-is-the-union", E.build_plan(d2)["total"] == 7 and E.build_plan(d2)["overlay_new"] == 1, E.build_plan(d2)["total"])

    d3 = fixture([{"id": "r", "action": "sanitize", "via": "mystery-fixer", "path": "a.py"}, {"id": "d", "action": "drop", "prefix": ""}], ["a.py"])
    ok("E07-an-unknown-sanitizer-is-a-finding", [f[0] for f in E.build_plan(d3)["findings"]] == ["UNKNOWN-SANITIZER"], E.build_plan(d3)["findings"])

    keep = {"scripts": {"governance": ["audit", "gone"], "operations": [], "release_tools": ["enable_mcp"]}, "schema": [], "release_tool_count": 3}
    d4 = fixture([{"id": "s", "action": "copy", "dir": "AI-Agent/scripts", "from_keep": ["governance", "operations", "release_tools"], "ext": ".py"}, {"id": "d", "action": "drop", "prefix": ""}],
                 ["AI-Agent/scripts/audit.py", "AI-Agent/scripts/other.py"], keep=keep)
    p4 = E.build_plan(d4)
    ok("E08-a-kept-tool-missing-from-disk-is-a-finding-except-the-deferred-enable_mcp", [(f[0], f[1]) for f in p4["findings"]] == [("KEEP-MISSING", "AI-Agent/scripts/gone.py")] and any(n[1].endswith("enable_mcp.py") for n in p4["notes"]) and p4["tools"] == {"built": 1, "declared": 3}, (p4["findings"], p4["notes"], p4["tools"]))
    ok("E09-from_keep-selects-only-the-named-tools", E.classify(d4)["files"]["AI-Agent/scripts/audit.py"][0] == "copy" and E.classify(d4)["files"]["AI-Agent/scripts/other.py"][0] == "drop")

    cls = {"stratum_core": [{"path": "AI-Agent/scripts/a-tests.py"}], "mother_vault_drop": [{"path": "AI-Agent/scripts/m-tests.py"}], "excluded_duplicates": ["p/dup-tests.py"]}
    d5 = fixture([{"id": "tc", "action": "copy", "tests": "stratum_core"}, {"id": "tm", "action": "drop", "tests": "mother_vault_drop"}, {"id": "td", "action": "drop", "tests": "excluded_duplicates"}],
                 ["AI-Agent/scripts/a-tests.py", "AI-Agent/scripts/m-tests.py", "p/dup-tests.py"], classification=cls)
    ok("E10-tests-follow-the-test-classification", {p: a for p, (a, _, _) in E.classify(d5)["files"].items() if p.endswith("tests.py")} == {"AI-Agent/scripts/a-tests.py": "copy", "AI-Agent/scripts/m-tests.py": "drop", "p/dup-tests.py": "drop"})

    d6 = fixture([{"id": "c", "action": "copy", "prefix": ""}], ["f" + chr(0x645) + ".md", "ok.md"])
    ok("E11-a-shipped-file-with-an-arabic-path-is-a-finding", [f[0] for f in E.build_plan(d6)["findings"]] == ["ARABIC-PATH"], E.build_plan(d6)["findings"])
    d7 = fixture([{"id": "c", "action": "drop", "prefix": ""}], ["f" + chr(0x645) + ".md"])
    ok("E12-the-same-file-dropped-is-fine", E.build_plan(d7)["findings"] == [])

    for name, body in (("E13-duplicate-ids", [{"id": "a", "action": "drop", "prefix": ""}, {"id": "a", "action": "drop", "path": "x"}]),
                       ("E13b-unknown-action", [{"id": "a", "action": "shred", "prefix": ""}]), ("E13c-sanitize-without-via", [{"id": "a", "action": "sanitize", "prefix": ""}])):
        try:
            E.load_manifest(fixture(body, ["f"]))
            raised = False
        except E.ExportError:
            raised = True
        ok(name + "-are-rejected", raised)
    try:
        E.load_manifest(Path(tempfile.mkdtemp()))
        raised = False
    except E.ExportError:
        raised = True
    ok("E14-a-missing-manifest-is-rejected", raised)
    d8 = Path(tempfile.mkdtemp())
    tmps.append(d8)
    try:
        E.tracked_files(d8)
        raised = False
    except E.ExportError:
        raised = True
    ok("E15-not-a-git-repository-is-rejected", raised)

    def cli(root, *a):
        return subprocess.run([sys.executable, str(HERE / "export_release.py"), *a], capture_output=True, text=True, encoding="utf-8", errors="replace", env=dict(os.environ, VAULT=str(root)), timeout=120)
    c1, c2, c3 = cli(d, "--plan"), cli(d2, "--plan"), cli(d, "--plan", "--json")
    ok("E16-cli-exit-1-when-blocked-and-0-when-complete", c1.returncode == 1 and "EXPORT-PLAN blocked" in c1.stdout and c2.returncode == 0 and "EXPORT-PLAN complete" in c2.stdout, (c1.returncode, c2.returncode))
    ok("E17-json-output-is-valid-and-has-the-counts", json.loads(c3.stdout.split("EXPORT-PLAN")[0])["counts"]["drop"] == 4, c3.stdout[:200])
    ok("E18-write-without-out-is-rc2", cli(d2, "--write").returncode == 2)
    o18 = Path(tempfile.mkdtemp(prefix="export-out-"))
    tmps.append(o18)
    (o18 / "stale.txt").write_text("x\n", encoding="utf-8")
    ok("E18b-write-refuses-a-non-empty-target", cli(d2, "--write", "--out", str(o18)).returncode == 1 and (o18 / "stale.txt").is_file())
    ok("E18c-ntfs-flags-reserved-names-case-twins-and-trailing-dots", len(E.ntfs_problems(["a/CON.md", "b/ok.md", "b/OK.md", "c/x.", "d/a:b.md"])) == 4, E.ntfs_problems(["a/CON.md", "b/ok.md", "b/OK.md", "c/x.", "d/a:b.md"]))
    t18 = Path(tempfile.mkdtemp(prefix="export-tree-"))
    tmps.append(t18)
    (t18 / "a.md").write_text("plain\n", encoding="utf-8")
    ok("E18d-check-tree-passes-a-clean-tree", E.check_tree(t18) == [], E.check_tree(t18))
    (t18 / "b.md").write_text("x" + chr(0x645) + "\n", encoding="utf-8")
    (t18 / "c.py").write_text("s = '" + chr(0x645) + "'\n", encoding="utf-8")
    (t18 / "d.md").write_text("zero\u200bwidth\u202eflip\n", encoding="utf-8")
    g18 = {(g, p) for g, p, _ in E.check_tree(t18)}
    ok("E18e-check-tree-finds-arabic-text-arabic-python-and-bidi", {("zero-arabic", "b.md"), ("zero-arabic", "c.py")} <= g18 and any(p == "d.md" for _, p in g18), sorted(g18))
    s27 = Path(tempfile.mkdtemp(prefix="export-skill-"))
    tmps.append(s27)
    for d_, fm_ in (("good-one", "name: good-one\ndescription: fine"), ("Bad_Name", "name: Bad_Name\ndescription: x"), ("other", "name: mismatch\ndescription: x"), ("nodesc", "name: nodesc")):
        (s27 / "AI-Agent/skills" / d_).mkdir(parents=True)
        (s27 / "AI-Agent/skills" / d_ / "SKILL.md").write_text(f"---\n{fm_}\n---\nbody\n", encoding="utf-8")
    ok("E18f-agentskills-flags-bad-name-mismatch-and-missing-description", sorted(Path(p).parent.name for p, _ in E.skill_problems(s27)) == ["Bad_Name", "nodesc", "other"], E.skill_problems(s27))
    ok("E27-spdx-goes-under-a-shebang-and-is-idempotent", E.add_spdx("#!/usr/bin/env python3\n\"\"\"d\"\"\"\n").split("\n")[:3] == ["#!/usr/bin/env python3", *E.SPDX_LINES]
       and E.add_spdx("x = 1\n").startswith(E.SPDX_LINES[0]) and E.add_spdx(E.add_spdx("x = 1\n")) == E.add_spdx("x = 1\n"))
    t27 = Path(tempfile.mkdtemp(prefix="export-spdx-"))
    tmps.append(t27)
    (t27 / "a.py").write_text("x = 1\n", encoding="utf-8")
    ok("E28-check-tree-flags-a-python-file-without-spdx", ("spdx", "a.py") in {(g, p) for g, p, _ in E.check_tree(t27)})

    t29 = Path(tempfile.mkdtemp(prefix="export-priv-"))
    tmps.append(t29)
    (t29 / "AI-Agent/scripts").mkdir(parents=True)
    (t29 / "AI-Agent/scripts/a.py").write_text("# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0\n# SPDX-FileCopyrightText: 2026 PRIVATE_CORP_99\nx = 1\n", encoding="utf-8")
    (t29 / "AI-Agent/scripts/b.py").write_text("# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0\nx = 'PRIVATE_CORP_99'\n", encoding="utf-8")
    (t29 / "notes.txt").write_text("leak PRIVATE_CORP_99\n", encoding="utf-8")
    (t29 / "CITATION.cff").write_text("authors:\n  - family-names: PRIVATE_CORP_99\n", encoding="utf-8")
    (t29 / "LICENSE").write_text("Required Notice: PRIVATE_CORP_99\n\nBody text\n", encoding="utf-8")
    _f29 = {(g, p) for g, p, _ in E.check_tree(t29, privacy_patterns=["PRIVATE_CORP_99"])}
    ok("E29-check-tree-flags-privacy-denylist-exempting-spdx-and-citation",
       ("privacy", "AI-Agent/scripts/b.py") in _f29 and ("privacy", "notes.txt") in _f29
       and ("privacy", "AI-Agent/scripts/a.py") not in _f29 and ("privacy", "CITATION.cff") not in _f29 and ("privacy", "LICENSE") not in _f29,
       _f29)

    t30 = Path(tempfile.mkdtemp(prefix="export-junk-"))
    tmps.append(t30)
    (t30 / "AI-Agent/schema").mkdir(parents=True)
    shutil.copy(REAL / "AI-Agent/schema/sweep_orphan_writes.py", t30 / "AI-Agent/schema/sweep_orphan_writes.py")
    for jf in (".DS_Store", "sub/._a.md", "Thumbs.db", "desktop.ini", ".git_credentials_input", "AI-Agent/mystery-orphan.txt"):
        jp = t30 / jf
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text("x\n", encoding="utf-8")
    _f30 = {(g, p) for g, p, _ in E.check_tree(t30)}
    ok("E30-check-tree-flags-forbidden-os-junk-and-orphans",
       {("zero-leak", j) for j in (".DS_Store", "sub/._a.md", "Thumbs.db", "desktop.ini", ".git_credentials_input")} <= _f30
       and ("orphan", "AI-Agent") in _f30,
       _f30)

    t31 = Path(tempfile.mkdtemp(prefix="export-exec-"))
    tmps.append(t31)
    for rel in E.EXECUTABLE_FILES:
        ep = t31 / rel
        ep.parent.mkdir(parents=True, exist_ok=True)
        ep.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    E.init_repo(t31)
    _st31 = subprocess.run(["git", "ls-files", "--stage"], cwd=t31, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.splitlines()
    _modes31 = {ln.split("\t", 1)[1]: ln.split(" ", 1)[0] for ln in _st31 if "\t" in ln}
    ok("E31-init-repo-marks-executable-files-100755", all(_modes31.get(r) == "100755" for r in E.EXECUTABLE_FILES), _modes31)

    ok("E19-help-rc0-unknown-flag-rc2-and-no-mode-rc2", cli(d2, "--help").returncode == 0 and cli(d2, "--bogus").returncode == 2 and cli(d2).returncode == 2)

    # ---- packaging: policy, manifest, deterministic archives, package mode
    ok("E20-policy-code-is-replaced-notes-merged-state-kept", (E.policy_of("AI-Agent/scripts/audit.py"), E.policy_of("AI-Agent/handoff.md"), E.policy_of("AI-Agent/state/operations.sqlite3"),
       E.policy_of(".obsidian/community-plugins.json"), E.policy_of(".obsidian/app.json"), E.policy_of("Templates/Area.md"), E.policy_of("02-Areas/Mine.md"))
       == ("replace", "merge", "add-only", "union", "json-merge", "merge", "add-only"))
    p20 = Path(tempfile.mkdtemp(prefix="export-pkg-"))
    tmps.append(p20)
    for rel, body in {"VERSION": "1.2.3\n", "AI-Agent/scripts/audit.py": "x = 1\n", "AI-Agent/handoff.md": "# h\n", "notes/mine.md": "# n\n"}.items():
        (p20 / rel).parent.mkdir(parents=True, exist_ok=True)
        (p20 / rel).write_text(body, encoding="utf-8")
    man = E.write_manifest(p20)
    ok("E21-manifest-lists-every-file-with-hash-and-policy-but-not-itself", man["format_version"] == 2 and man["version"] == "1.2.3" and "release_manifest.json" not in man["files"]
       and set(man["files"]) == {"VERSION", "AI-Agent/scripts/audit.py", "AI-Agent/handoff.md", "notes/mine.md"} and man["critical"] == ["AI-Agent/scripts/audit.py"], sorted(man["files"]))
    a1, a2 = Path(tempfile.mkdtemp(prefix="export-dist-")), Path(tempfile.mkdtemp(prefix="export-dist-"))
    tmps += [a1, a2]
    E.build_archives(p20, a1)
    time.sleep(1.1)   # a later clock must not change a byte
    E.build_archives(p20, a2)
    ok("E22-archives-are-deterministic", (a1 / "SHA256SUMS").read_text() == (a2 / "SHA256SUMS").read_text() and (a1 / "base.zip").read_bytes() == (a2 / "base.zip").read_bytes())
    import zipfile as _zf
    with _zf.ZipFile(a1 / "base.zip") as z:
        base_names = z.namelist()
        stamps = {i.date_time for i in z.infolist()}
    ok("E23-base-holds-the-core-and-full-holds-everything", "notes/mine.md" not in base_names and "AI-Agent/handoff.md" in base_names and "release_manifest.json" in base_names and stamps == {(1980, 1, 1, 0, 0, 0)}, base_names)
    c23 = cli(p20, "--package", "--dist", str(a1 / "again"))
    ok("E24-package-mode-packs-a-matching-tree", c23.returncode == 0 and (a1 / "again" / "base.zip").is_file(), c23.stderr[-200:])
    (p20 / "AI-Agent/handoff.md").write_text("# edited\n", encoding="utf-8")
    v29 = Path(tempfile.mkdtemp(prefix="export-venv-"))
    tmps.append(v29)
    (v29 / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    (v29 / "a.md").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=v29, check=True)
    (v29 / ".gitignore").write_text(".venv/\n__pycache__/\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=v29, check=True)
    m29 = E.write_manifest(v29)
    (v29 / ".venv/lib").mkdir(parents=True)
    (v29 / ".venv/lib/x.py").write_text("x\n", encoding="utf-8")
    (v29 / "__pycache__").mkdir()
    (v29 / "__pycache__/c.pyc").write_bytes(b"\0")
    ok("E24b-a-runners-venv-and-caches-are-not-part-of-the-release", E.build_manifest(v29) == m29 and ".venv/lib/x.py" not in E.tree_files(v29), E.tree_files(v29))
    ok("E25-package-mode-refuses-a-tree-that-drifted-from-its-manifest", cli(p20, "--package", "--dist", str(a1 / "drift")).returncode == 1)
    ok("E26-package-needs-dist-rc2", cli(p20, "--package").returncode == 2)

    # ---- the real manifest against the real vault
    if not (REAL / E.MANIFEST).is_file():
        print("EXPORT-RELEASE-TESTS SKIP: no export manifest here (this is not the mother vault)")
        sys.exit(77)
    real = E.build_plan(REAL)
    ok("R01-every-tracked-file-of-the-vault-is-classified", real["findings"] == [] and not [f for f in real["findings"] if f[0] == "UNCLASSIFIED"], real["findings"][:3])
    ok("R02-the-counts-add-up-to-the-total", sum(real["counts"].values()) == real["total"] and set(real["counts"]) <= set(E.ACTIONS))
    ok("R03-nothing-private-ships-by-copy", not [p for p, (a, rid, _) in real["files"].items() if a == "copy" and (p.startswith(("01-Projects/", "02-Areas/", "04-Archive/", "AI-Agent/handoff/", "AI-Agent/state/")) or 0x600 <= ord(max(p)) <= 0x6FF)])
    ok("R04-no-stale-rule-remains", E.classify(REAL)["unused_rules"] == [], E.classify(REAL)["unused_rules"])
    copied = {p for p, (a, _, _) in real["files"].items() if a == "copy"}
    ok("R05-the-packaging-files-are-copied", {"pyproject.toml", "uv.lock", "setup.sh", "src/stratum_cli/main.py"} <= copied)
    sanitized = {p for p, (a, _, _) in real["files"].items() if a in ("sanitize", "derive")}
    import re as _r6
    _ov = int(_r6.search(r"^\s*tools:\s+(\d+)", (REAL / "AI-Agent" / "release-overlay" / "AI-Agent" / "schema" / "consumer-map.yaml").read_text(encoding="utf-8"), _r6.M).group(1))
    ok("R06-the-release-tool-scripts-are-all-present-except-the-deferred-one", real["tools"]["built"] == real["tools"]["declared"] == _ov >= 32, (real["tools"], _ov))
    kept = {p for p, (a, rid, _) in real["files"].items() if rid in ("scripts-keep", "schema-keep")}
    ok("R07-no-mother-only-tool-is-kept", not [p for p in kept if p.rsplit("/", 1)[1][:-3] in ("arch_rules", "club_rules", "impact", "radar_state", "cost", "norm_v1", "claim_gate", "system_architect_engine")])
    ok("R08-the-dropped-skills-are-dropped", all(real["files"][p][0] == "drop" for p in real["files"] if p.startswith(("AI-Agent/skills/arch-", "AI-Agent/skills/card-forge", "AI-Agent/skills/club-radar", "AI-Agent/skills/contest-sprint")) and not p.startswith(E.OVERLAY)))
    ok("R09-the-sixteen-skills-ship-from-the-overlay", sum(1 for p, (a, _, _) in real["files"].items() if a == "overlay" and p.startswith("AI-Agent/skills/") and p.endswith("SKILL.md")) == 16)
    ok("R10-secrets-and-local-state-never-ship", not [p for p, (a, _, _) in real["files"].items() if a != "drop" and any(x in p for x in ("workspace", "diagnostic.log", "mcp-tools-istefox/data.json", "vault-index.sqlite3", "askpass", ".trash"))
                                                      and a not in ("derive",)])
    # ---- the whole build, end to end (mother vault only)
    e2e = Path(tempfile.mkdtemp(prefix="export-e2e-"))
    tmps.append(e2e)
    shutil.rmtree(e2e)
    res = E.write_release(REAL, e2e / "tree")
    ok("R11-a-full-build-passes-every-tree-gate", res["findings"] == [], res["findings"][:3])
    man = json.loads((e2e / "tree/release_manifest.json").read_text(encoding="utf-8"))
    ok("R12-the-manifest-hashes-match-the-built-files", all(hashlib.sha256((e2e / "tree" / r).read_bytes()).hexdigest() == m["sha256"] for r, m in man["files"].items()), len(man["files"]))
    ok("R13-the-tree-is-a-git-repo-with-the-hook-wired-and-nothing-committed", subprocess.run(["git", "config", "core.hooksPath"], cwd=e2e / "tree", capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip() == ".githooks"
       and subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=e2e / "tree", capture_output=True).returncode != 0)
    crlf = [f.relative_to(e2e / "tree").as_posix() for f in (e2e / "tree").rglob("*") if f.is_file() and ".git" not in f.relative_to(e2e / "tree").parts
            and (f.suffix.lower() in (E.TEXT_EXT | {".cmd", ".bat", ".ps1", ".toml"}) or f.name in E.TEXT_NAMES) and b"\r\n" in f.read_bytes()]
    ok("R15-the-release-is-LF-everywhere", crlf == [], crlf[:5])
    gate = subprocess.run([str(e2e / "tree/AI-Agent/vault-python"), str(e2e / "tree/AI-Agent/scripts/audit.py"), "--ratchet"], cwd=e2e / "tree", capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={k: v for k, v in os.environ.items() if k != "VAULT"})
    ok("R14-the-built-tree-passes-its-own-commit-gate", gate.returncode == 0 and "GATE CLEAR blocking=0" in gate.stdout, "\n".join(l for l in (gate.stdout + gate.stderr).splitlines() if l.startswith(("error", "GATE")))[-400:])

    _arc17 = E.build_archives(e2e / "tree", e2e / "dist")
    _pkg17 = cli(e2e / "tree", "--package", "--dist", str(e2e / "dist2"))
    ok("R17-package-succeeds-under-1mb-cap-with-budget-breakdown",
       _arc17["bytes"]["base.zip"] <= 1024 * 1024 and _arc17["dir_bytes"]["AI-Agent/state"] <= 256 * 1024
       and "AI-Agent/scripts" in _arc17["dir_bytes"] and _pkg17.returncode == 0,
       (_arc17, _pkg17.returncode, _pkg17.stderr[-200:]))

    import upgrade_core as _UC
    _inst18 = _UC.read_installed(e2e / "tree")
    _ops18 = (e2e / "tree/AI-Agent/operations.md").read_text(encoding="utf-8")
    _runs18 = (e2e / "tree/AI-Agent/last-runs.md").read_text(encoding="utf-8")
    shutil.copytree(e2e / "tree", e2e / "v1")
    shutil.copytree(e2e / "tree", e2e / "v2")
    _hf1 = e2e / "v1/AI-Agent/handoff.md"
    _hf1.write_text(_hf1.read_text(encoding="utf-8") + "\nLocal owner note line\n", encoding="utf-8")
    _hf2 = e2e / "v2/AI-Agent/handoff.md"
    _hf2.write_text(_hf2.read_text(encoding="utf-8").replace("\n# ", "\nUpstream Banner Line\n\n# ", 1), encoding="utf-8")
    (e2e / "v2/VERSION").write_text("9.9.9\n", encoding="utf-8")
    E.write_manifest(e2e / "v2")
    _p18 = _UC.plan(e2e / "v1", _UC.Source.from_dir(e2e / "v2"), _UC.read_installed(e2e / "v1"))
    ok("R18-upgrade-state-and-clean-seeds-enable-three-way-merge",
       _inst18 is not None and _inst18["version"] == man["version"]
       and (e2e / "tree/.vault-release/base/AI-Agent/handoff.md").is_file()
       and _ops18.count("`") % 2 == 0 and "## Operations" in _ops18 and "## Runs" in _runs18
       and not _p18["conflicts"]
       and any(k == "update" and r == "AI-Agent/handoff.md" and "merged" in info for k, r, _, info in _p18["acts"]),
       (_inst18 and _inst18["version"], _p18["conflicts"], [x[:2] + (x[3],) for x in _p18["acts"] if x[1] == "AI-Agent/handoff.md"]))

    _st19 = subprocess.run(["git", "ls-files", "--stage"], cwd=e2e / "tree", capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.splitlines()
    _m19 = {ln.split("\t", 1)[1]: ln.split(" ", 1)[0] for ln in _st19 if "\t" in ln}
    ok("R19-git-index-has-100755-for-executables", all(_m19.get(r) == "100755" for r in E.EXECUTABLE_FILES), {r: _m19.get(r) for r in E.EXECUTABLE_FILES})

    _deny20 = E.load_manifest(REAL).get("privacy_denylist") or []
    _p20d = Path(tempfile.mkdtemp(prefix="export-deny-"))
    tmps.append(_p20d)
    (_p20d / "leak.txt").write_text(f"leaked {_deny20[0]}\n", encoding="utf-8")
    _f20 = E.check_tree(_p20d, privacy_patterns=_deny20)
    ok("R20-manifest-privacy-denylist-catches-planted-leak", bool(_deny20) and any(g == "privacy" for g, _, _ in _f20), (_deny20[:3], _f20))

finally:
    for t in tmps:
        shutil.rmtree(t, ignore_errors=True)

# the git commands on a built tree must not inherit a hook's GIT_INDEX_FILE (a hook sets it; the tree's own `git add -A` wrote into the commit's index)
_it = Path(tempfile.mkdtemp(prefix="exp-env-"))
try:
    (_it / "out").mkdir()
    (_it / "out" / "a.txt").write_text("x\n", encoding="utf-8")
    _idx = _it / "hook-index"
    os.environ["GIT_INDEX_FILE"] = str(_idx)
    try:
        E.init_repo(_it / "out")
        _names = E.tree_files(_it / "out")
    finally:
        del os.environ["GIT_INDEX_FILE"]
    _staged = subprocess.run(["git", "ls-files"], cwd=_it / "out", capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.split()
    ok("R16-init_repo-and-tree_files-ignore-an-inherited-GIT_INDEX_FILE", not _idx.exists() and _staged == ["a.txt"] and _names == ["a.txt"], (_idx.exists(), _staged, _names))
finally:
    shutil.rmtree(_it, ignore_errors=True)

failed = [r for r in R if not r[1]]
for name, passed, got in R:
    print(("PASS " if passed else "FAIL ") + name + ("" if passed else f" -> {got}"))
print(f"EXPORT-RELEASE-TESTS {len(R) - len(failed)}/{len(R)}")
sys.exit(1 if failed else 0)
