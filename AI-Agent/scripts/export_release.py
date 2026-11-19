# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""export_release.py — build the public release tree from the mother vault by a whitelist.

Usage: python AI-Agent/scripts/export_release.py --plan [--json]
       python AI-Agent/scripts/export_release.py --check [--json]
       python AI-Agent/scripts/export_release.py --write --out DIR        (not built yet: see the T-06 notes)

`--plan` classifies every tracked file of the mother vault by AI-Agent/config/export-manifest.yaml (first match wins; a file
no rule names stops the export) and prints what each action covers. `--check` is `--plan` plus the facts the build depends on:
the tools the manifest keeps exist, the sanitizers it names are implemented, and the overlay does not point outside the
release. Exit code: 0 the plan is complete, 1 a finding stops the export, 2 bad arguments or an unreadable manifest.
Standard library plus PyYAML.
"""
from __future__ import annotations

import collections
import fnmatch
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _vaultlib import arabic_in_python, force_utf8_stdio, scan_secrets, standard_parser  # noqa: E402

MANIFEST = "AI-Agent/config/export-manifest.yaml"
OVERLAY = "AI-Agent/release-overlay"
ACTIONS = ("copy", "sanitize", "overlay", "seed", "derive", "drop")


class ExportError(Exception):
    """A manifest or a tree that the export cannot use."""


def tracked_files(root: Path) -> list[str]:
    r = subprocess.run(["git", "-c", "core.quotepath=off", "-C", str(root), "ls-files", "-z"], capture_output=True)
    if r.returncode != 0:
        raise ExportError(f"not a git repository: {root}")
    return sorted(p.decode("utf-8") for p in r.stdout.split(b"\0") if p)


def overlay_files(root: Path) -> list[str]:
    base = root / OVERLAY
    return sorted(f.relative_to(base).as_posix() for f in base.rglob("*") if f.is_file()) if base.is_dir() else []


def load_manifest(root: Path) -> dict:
    try:
        m = yaml.safe_load((root / MANIFEST).read_text(encoding="utf-8"))
        assert m["version"] == 1 and isinstance(m["rules"], list)
        ids = [r["id"] for r in m["rules"]]
        if len(ids) != len(set(ids)):
            raise ExportError("duplicate rule ids in the export manifest")
        for r in m["rules"]:
            if r["action"] not in ACTIONS:
                raise ExportError(f"rule {r['id']}: unknown action {r['action']!r}")
            if r["action"] in ("sanitize", "derive") and not r.get("via"):
                raise ExportError(f"rule {r['id']}: {r['action']} needs `via`")
        deny = m.get("privacy_denylist")
        if deny is not None and (not isinstance(deny, list) or not all(isinstance(x, str) and x for x in deny)):
            raise ExportError("privacy_denylist must be a list of non-empty strings")
        return m
    except ExportError:
        raise
    except (OSError, KeyError, TypeError, AssertionError, yaml.YAMLError) as e:
        raise ExportError(f"unreadable manifest {MANIFEST}: {e.__class__.__name__}: {e}") from e


def classification_tests(root: Path) -> dict[str, set[str]]:
    c = yaml.safe_load((root / "AI-Agent/config/test-classification.yaml").read_text(encoding="utf-8")) or {}
    return {k: {e["path"] if isinstance(e, dict) else e for e in (c.get(k) or [])} for k in ("stratum_core", "mother_vault_drop", "excluded_duplicates")}


def keep_paths(manifest: dict, group_names: list[str] | None, which: str) -> set[str]:
    keep = manifest["keep"]
    if which == "scripts":
        names = [n for g in (group_names or []) for n in keep["scripts"][g]]
        return {f"AI-Agent/scripts/{n}.py" for n in names}
    return {f"AI-Agent/schema/{n}.py" for n in keep["schema"]}


def rule_matches(rule: dict, path: str, manifest: dict, tests: dict) -> bool:
    if rule.get("path") == path or path in (rule.get("paths") or []):
        return True
    if any(path.startswith(p) for p in ([rule["prefix"]] if "prefix" in rule else []) + (rule.get("prefixes") or [])):
        return True
    if rule.get("glob") and fnmatch.fnmatchcase(path, rule["glob"]):
        return True
    if rule.get("from_keep") is not None:
        which = "scripts" if rule["dir"].endswith("scripts") else "schema"
        return path in keep_paths(manifest, rule["from_keep"], which)
    if rule.get("tests"):
        return path in tests[rule["tests"]]
    return False


def classify(root: Path, manifest: dict | None = None) -> dict:
    """{'files': {path: (action, rule id, via)}, 'unclassified': [...], 'unused_rules': [...], 'overlay_new': [...]}"""
    manifest = manifest or load_manifest(root)
    tests = classification_tests(root)
    overlay = set(overlay_files(root))
    tracked = tracked_files(root)
    files, unclassified, used = {}, [], collections.Counter()
    for path in tracked:
        if path in overlay:
            files[path] = ("overlay", "overlay", "")
            continue
        for rule in manifest["rules"]:
            if rule_matches(rule, path, manifest, tests):
                files[path] = (rule["action"], rule["id"], rule.get("via", ""))
                used[rule["id"]] += 1
                break
        else:
            unclassified.append(path)
    overlay_new = sorted(p for p in overlay if p not in files)
    for p in overlay_new:
        files[p] = ("overlay", "overlay", "")
    unused = [r["id"] for r in manifest["rules"] if not used[r["id"]]]
    return {"files": files, "unclassified": unclassified, "unused_rules": unused, "overlay_new": overlay_new}


def sanitize_script(text: str, name: str = "") -> str:
    """The `scripts-english` sanitizer. The scripts are English at the source (their Arabic lives in _locale_ar.py, which is not
    exported), so the sanitizer verifies that and returns the text unchanged; any Arabic left, even as a \\u escape, stops the export."""
    hits = arabic_in_python(text)
    if hits:
        raise ExportError(f"{name or 'script'}: {len(hits)} Arabic occurrence(s), first at line {hits[0][0]} ({hits[0][1]}): {hits[0][2]!r}")
    return text


# Exact text edits for the few shipped scripts whose data names a tool the release does not carry. The edits live in
# AI-Agent/config/release-patches/script-edits.yaml (a build input, never shipped, so this exporter does not carry the names either).
# Each must match exactly once: a changed source line stops the export instead of silently shipping the name.
def load_release_edits(root: Path) -> dict:
    f = root / "AI-Agent/config/release-patches/script-edits.yaml"
    return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("edits", {}) if f.is_file() else {}


def apply_release_edits(text: str, rel: str, edits: dict | None = None) -> str:
    for e in (edits or {}).get(rel, []):
        old, new = e["old"], e["new"]
        if text.count(old) != 1:
            raise ExportError(f"{rel}: the release edit expects its text exactly once, found {text.count(old)}: {old[:60]!r}")
        text = text.replace(old, new)
    return text


def derive_profile(root: Path) -> str:
    """The release profile: the mother's release_profile.yaml with release_profile.patch.yaml applied, validated, as block YAML."""
    from _vaultlib import PatchError, UNTOUCHABLE_CHECKS, apply_patch, dump_yaml_block, validate_profile
    mother = yaml.safe_load((root / "AI-Agent/config/release_profile.yaml").read_text(encoding="utf-8"))
    patch = yaml.safe_load((root / "AI-Agent/config/release-patches/release_profile.patch.yaml").read_text(encoding="utf-8"))
    try:
        out = apply_patch(mother, patch)
    except PatchError as e:
        raise ExportError(f"release_profile.patch.yaml does not apply: {e}") from e
    problems = validate_profile(out)
    if problems:
        raise ExportError("the release profile is invalid: " + "; ".join(problems))
    if out["mode"] != "release" or set(out["checks"]["disabled"]) & set(UNTOUCHABLE_CHECKS):
        raise ExportError("the release profile must be mode release and must not disable an integrity check")
    return dump_yaml_block(out)


def seed_test_classification(root: Path) -> str:
    """The release's test-classification.yaml: only the stratum_core entries whose file the release ships."""
    from _vaultlib import dump_yaml_block
    data = yaml.safe_load((root / "AI-Agent/config/test-classification.yaml").read_text(encoding="utf-8"))
    core = [e for e in data["stratum_core"] if (root / (e["path"] if isinstance(e, dict) else e)).is_file()]
    return dump_yaml_block({"version": 1, "stratum_core": core})


def build_plan(root: Path) -> dict:
    manifest = load_manifest(root)
    cl = classify(root, manifest)
    counts = collections.Counter(a for a, _, _ in cl["files"].values())
    findings, notes = [], []
    for p in cl["unclassified"]:
        findings.append(("UNCLASSIFIED", p, "no rule in the export manifest names this file"))
    for rid in cl["unused_rules"]:
        notes.append(("STALE-RULE", rid, "matches no tracked file"))
    pend = set(manifest["sanitizers"]["pending"])
    pending_by = collections.Counter(v for a, _, v in cl["files"].values() if a in ("sanitize", "derive") and v in pend)
    impl = set(manifest["sanitizers"]["implemented"])
    for _, (a, rid, via) in cl["files"].items():
        if a in ("sanitize", "derive") and via not in impl | pend:
            findings.append(("UNKNOWN-SANITIZER", rid, f"via {via!r} is neither implemented nor pending"))
    kept = {"scripts": keep_paths(manifest, ["governance", "operations", "release_tools"], "scripts"), "schema": keep_paths(manifest, None, "schema")}
    tools_built = sorted(p for p in kept["scripts"] if (root / p).is_file())
    for p in sorted(kept["scripts"] | kept["schema"]):
        if not (root / p).is_file():
            (notes if p.rsplit("/", 1)[1][:-3] in ("enable_mcp",) else findings).append(("KEEP-MISSING", p, "listed in `keep` but not on disk"))
    for p, (a, rid, via) in sorted(cl["files"].items()):
        if a == "overlay" and p in cl["overlay_new"] and any(p.startswith(x) for x in ("AI-Agent/skills/arch-", "AI-Agent/skills/card-forge")):
            findings.append(("OVERLAY-DROPPED-SKILL", p, "the overlay ships a skill the release drops"))
    for p, (a, rid, via) in sorted(cl["files"].items()):
        if a != "drop" and any(0x0600 <= ord(ch) <= 0x06FF for ch in p):
            findings.append(("ARABIC-PATH", p, "a file that ships must have an English path"))
    for p, (a, rid, via) in sorted(cl["files"].items()):
        if via == "scripts-english" and a == "sanitize" and (root / p).is_file() and p.endswith(".py"):
            try:
                sanitize_script((root / p).read_text(encoding="utf-8"), p)
            except ExportError as e:
                findings.append(("ARABIC-IN-SCRIPT", p, str(e)))
            except SyntaxError as e:
                findings.append(("SYNTAX", p, f"does not parse: {e}"))
    return {"counts": dict(counts), "total": len(cl["files"]), "findings": findings, "notes": notes, "pending_sanitizers": dict(pending_by),
            "tools": {"built": len(tools_built), "declared": manifest["keep"]["release_tool_count"]}, "overlay_new": len(cl["overlay_new"]), "files": cl["files"]}


WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *{f"com{i}" for i in range(1, 10)}, *{f"lpt{i}" for i in range(1, 10)}}
FORBIDDEN_SHIPPED = ("workspace", "diagnostic.log", "vault-index.sqlite3", "obsidian_askpass", "/.trash/", "isolation-report.json", "telemetry-latest", "net-preflight.log",
                     "session-memory.jsonl", "task-key.json", "throttle-state.json", "mcp-tools-istefox/data.json", "update-time-on-edit", "/handoff/", "/AI-Agent/fixtures/", "card-template",
                     "/.DS_Store", "/._", "/Thumbs.db", "/desktop.ini", "/.git_credentials_input")
TEXT_EXT = {".md", ".py", ".json", ".yaml", ".yml", ".base", ".canvas", ".js", ".css", ".html", ".sh", ".ps1", ".cmd", ".toml", ".txt", ".cff", ".mdc", ".lock"}
TEXT_NAMES = ("VERSION", "LICENSE", ".gitignore", ".gitattributes", "vault-python", "pre-commit", ".python-version")
EXECUTABLE_FILES = (".githooks/pre-commit", "setup.sh", "AI-Agent/vault-python")
BASE_ZIP_MAX_BYTES = 1024 * 1024
STATE_RAW_MAX_BYTES = 256 * 1024


def ntfs_problems(paths: list[str]) -> list[str]:
    """Names Windows or macOS cannot hold: reserved device names, forbidden characters, a trailing dot or space, two paths that differ
    only by case, and a path long enough to hit MAX_PATH once a checkout directory is prepended."""
    bad, seen = [], {}
    for p in paths:
        for part in p.split("/"):
            stem = part.split(".", 1)[0].lower()
            if stem in WINDOWS_RESERVED:
                bad.append(f"{p}: reserved Windows name {part!r}")
            if any(c in part for c in '<>:"|?*\\') or any(ord(c) < 32 for c in part):
                bad.append(f"{p}: forbidden character in {part!r}")
            if part.endswith((".", " ")):
                bad.append(f"{p}: trailing dot or space in {part!r}")
        if len(p) > 200:
            bad.append(f"{p}: path of {len(p)} characters")
        low = p.lower()
        if low in seen and seen[low] != p:
            bad.append(f"{p}: differs only by case from {seen[low]}")
        seen[low] = p
    return bad


def skill_problems(out: Path) -> list[tuple[str, str]]:
    """agentskills.io rules for each shipped skill: `name` is 1-64 lowercase letters, digits and single hyphens and equals the folder
    name; `description` is 1-1024 characters; `compatibility`, when present, is at most 500. Extra keys are the vault's own and allowed."""
    import re as _re
    bad = []
    for f in sorted((out / "AI-Agent/skills").glob("*/SKILL.md")):
        rel = f.relative_to(out).as_posix()
        text = f.read_text(encoding="utf-8")
        m = _re.match(r"^---\n(.*?)\n---\n", text, _re.S)
        try:
            fm = yaml.safe_load(m.group(1)) if m else None
        except yaml.YAMLError:
            fm = None
        if not isinstance(fm, dict):
            bad.append((rel, "no readable frontmatter"))
            continue
        name, desc = fm.get("name"), fm.get("description")
        if not (isinstance(name, str) and 1 <= len(name) <= 64 and _re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name)):
            bad.append((rel, f"invalid name {name!r}"))
        elif name != f.parent.name:
            bad.append((rel, f"name {name!r} differs from the folder {f.parent.name!r}"))
        if not (isinstance(desc, str) and 1 <= len(desc) <= 1024):
            bad.append((rel, "description missing or longer than 1024 characters"))
        if "compatibility" in fm and not (isinstance(fm["compatibility"], str) and 1 <= len(fm["compatibility"]) <= 500):
            bad.append((rel, "compatibility must be 1-500 characters"))
    return bad


SPDX_LINES = ("# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0", "# SPDX-FileCopyrightText: 2026 Saud Zaid")


def add_spdx(text: str) -> str:
    """Put the SPDX license and copyright lines at the top of a Python file, under a shebang when there is one. Idempotent."""
    if "SPDX-License-Identifier:" in text.split("\n\n", 1)[0]:
        return text
    lines = text.split("\n")
    at = 1 if lines and lines[0].startswith("#!") else 0
    return "\n".join(lines[:at] + list(SPDX_LINES) + lines[at:])


SECRET_RULE_FILES = {"AI-Agent/schema/secret-shapes.json"}   # gitleaks rules (MIT, provenance inside the file); never scanned as a leak


def check_tree(out: Path, privacy_patterns: tuple[str, ...] | list[str] = ()) -> list[tuple[str, str, str]]:
    """The acceptance gates that can run on a built tree alone: Zero-Arabic (names, texts, and Python by token and AST), secrets
    and Zero-Bidi, privacy denylist, orphan sweep, NTFS compatibility, and files that must never ship. [(gate, path, why)]"""
    findings: list[tuple[str, str, str]] = []
    files = sorted(f.relative_to(out).as_posix() for f in out.rglob("*") if f.is_file() and ".git/" not in f.relative_to(out).as_posix() + "/")
    low_pats = [(pat, pat.lower()) for pat in privacy_patterns if pat]
    for p in files:
        if any(0x0600 <= ord(ch) <= 0x06FF for ch in p):
            findings.append(("zero-arabic", p, "Arabic in the file name"))
        low_path = ("/" + p).lower()
        if any(x.lower() in low_path for x in FORBIDDEN_SHIPPED):
            findings.append(("zero-leak", p, "a file that must never ship"))
        f = out / p
        if f.suffix.lower() not in TEXT_EXT and f.name not in TEXT_NAMES:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(("zero-leak", p, "a text file that is not UTF-8"))
            continue
        if f.suffix == ".py":
            if not text.startswith(("#!", "# SPDX-License-Identifier:")) or "SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0" not in text.split("\n\n", 1)[0]:
                findings.append(("spdx", p, "no SPDX license line at the top"))
            try:
                for ln, kind, what in arabic_in_python(text)[:3]:
                    findings.append(("zero-arabic", p, f"line {ln} ({kind}): {what!r}"))
            except SyntaxError as e:
                findings.append(("syntax", p, str(e)))
        elif any(0x0600 <= ord(ch) <= 0x06FF for ch in text):
            findings.append(("zero-arabic", p, "Arabic in the text"))
        if low_pats and p != "CITATION.cff":
            hits = 0
            for ln, line in enumerate(text.splitlines(), 1):
                if "SPDX-FileCopyrightText" in line or (p == "LICENSE" and ln == 1 and line.startswith("Required Notice:")):
                    continue
                low_line = line.lower()
                for pat, low_pat in low_pats:
                    if low_pat in low_line:
                        findings.append(("privacy", p, f"line {ln}: matched {pat!r}"))
                        hits += 1
                        break
                if hits >= 3:
                    break
        if p in SECRET_RULE_FILES:      # detection rules (regex text that matches other rules' shapes), as audit's secrets check leaves them out
            continue
        for kind, ln, what in scan_secrets(text):
            findings.append(("zero-leak" if kind != "bidi" and kind != "bom" else "zero-arabic", p, f"line {ln}: {kind}: {what}"))
    sweep_script = out / "AI-Agent" / "schema" / "sweep_orphan_writes.py"
    if sweep_script.is_file():
        sw = subprocess.run([sys.executable, str(sweep_script)], cwd=out, capture_output=True, text=True, encoding="utf-8", errors="replace", env=_tree_env())
        if sw.returncode != 0:
            findings.append(("orphan", "AI-Agent", (sw.stdout + sw.stderr).strip()[:200]))
    findings += [("ntfs-compat", "", m) for m in ntfs_problems(files)]
    findings += [("agentskills", p, why) for p, why in skill_problems(out)]
    return findings


SEED_PY = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import decision_ledger as L
date, skill_sha, skill_review, perm_tokens = sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
ts = date + "T00:00:00+00:00"
L.open_ledger()
L.append_decision("static childhood - permanent layer", f"Permanent layer billed at session start; {perm_tokens} tokens measured with tiktoken o200k_base.", "release", kind="static_childhood", tokens_billed=perm_tokens, ts=ts)
rec = {"created": date, "id": "vault-writer", "name": "vault-writer", "path": "AI-Agent/skills/vault-writer/SKILL.md", "review_by": skill_review, "sha256": skill_sha, "status": "active"}
L.append_decision("skill-record: vault-writer", json.dumps(rec, sort_keys=True), "release", kind="skill_record", ts=ts)
L.append_decision("Routing policy: cheap model reads, strong model writes", json.dumps({"task": "declared routing policy", "decision_type": "agent_route_policy", "model_proposed": {"reading": "cheap-model", "writing": "strong-model", "deletion_move": "banned"}, "model_approved": None}, sort_keys=True), "release", kind="routing", ts=ts)
import mediator as M
M.open_writer().close()
L.append_injection_log("release", "static_childhood", perm_tokens, "tiktoken-first-party", ts=ts, note="opening entry")
L.append_injection_log("release", "decision_batch", 0, "tiktoken-first-party", ts=ts, count=3, coverage_pct=100, note="the three opening decisions are billed")
"""


def _tokens(text: str) -> int:
    from g07_tokens import tokens_of
    return tokens_of(text)


def seed_tree(root: Path, out: Path, date: str) -> list[str]:
    """Generate the state files of a fresh install under `out` by running the tree's own writers, so every seed is valid by construction."""
    import datetime as _dt
    import hashlib as _hl
    made = []
    agent = out / "AI-Agent"
    (agent / "state").mkdir(parents=True, exist_ok=True)
    handoff = (agent / "handoff.md").read_bytes()
    ops_seed = (
        f"---\n"
        f"tags:\n"
        f"  - ai-agent\n"
        f"created: {date}\n"
        f"updated_by: AI-Agent\n"
        f"---\n\n"
        f"# Operation log\n\n"
        f"Multi-file changes are recorded as append-only operation and step entries using structured IDs:\n\n"
        f"- Format (`op`): `OP-0001 · YYYY-MM-DDTHH:MM+00:00 · agent · open|applied|rolled_back|failed · base=<commit> · <title>`\n"
        f"- Format (`step`): `OP-0001 · 1 · <path> · before=<12 hex>|new · after=<12 hex>|pending|deleted`\n\n"
        f"Use `g10_operations.py stats` or `g10_operations.py query OP-NNNN` to inspect recorded operations.\n\n"
        f"## Operations\n"
    )
    runs_seed = (
        f"---\n"
        f"tags:\n"
        f"  - ai-agent\n"
        f"created: {date}\n"
        f"updated_by: AI-Agent\n"
        f"---\n\n"
        f"# Last runs\n\n"
        f"Scheduled or recurring maintenance jobs append one append-only status line per completed run:\n\n"
        f"- Format (`last_run`): `<job> · YYYY-MM-DD HH:MM · ok|fail · <note>`\n\n"
        f"`state.py` prints the latest status per recorded job. Append only; never edit historical lines.\n\n"
        f"## Runs\n"
    )
    (agent / "operations.md").write_text(ops_seed, encoding="utf-8")
    (agent / "last-runs.md").write_text(runs_seed, encoding="utf-8")
    env = {**os.environ, "VAULT": str(out), "STRATUM_NET_LOG": os.devnull}
    scripts = str(out / "AI-Agent/schema")
    sys.path.insert(0, str(out / "AI-Agent/scripts"))
    try:
        perm = _tokens((agent / "permanent-layer.md").read_text(encoding="utf-8"))
        sha = _hl.sha256((agent / "skills/vault-writer/SKILL.md").read_bytes()).hexdigest()
        review = (_dt.date.fromisoformat(date) + _dt.timedelta(days=180)).isoformat()
        for args in ([sys.executable, "-c", SEED_PY, scripts, date, sha, review, str(perm)],
                     [sys.executable, str(out / "AI-Agent/scripts/g10_operations.py"), "rebuild"]):
            r = subprocess.run(args, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=out)
            if r.returncode != 0:
                raise ExportError(f"seed step failed ({Path(args[1]).name[:30]}): {(r.stderr or r.stdout)[-300:]}")
        metrics = {"operations_md_tokens": _tokens((agent / "operations.md").read_text(encoding="utf-8")),
                   "rules_md_tokens": _tokens((agent / "rules.md").read_text(encoding="utf-8")),
                   "handoff_md_tokens": _tokens(handoff.decode("utf-8")),
                   "hit_rate_pct": 100, "usage_rate_pct": None, "token_ratio_out_in": None,
                   "permanent_layer": {"file": "AI-Agent/permanent-layer.md", "cap_tokens": 1300, "measured_tokens": perm},
                   "static_childhood_tokens": perm, "session_ceiling_tokens": 1300,
                   "session_ceiling_scope": "live payload of a standard session: dynamic injection plus session context",
                   "s13_max_seconds": 5, "hit_rate_cadence_days": 14, "schedule_established": date, "s16_max_log_lines": 200}
        base = {"created": date, "project": "Stratum", "method": "tiktoken o200k_base first-party measurement", "metrics": metrics,
                "notes": "Release baseline: measured on the shipped files. The detached signature of a vault owner is not part of a release.",
                "version": "1.0.0", "last_measured": date}
        blob = json.dumps(base, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        base["content_hash"] = _hl.sha256(blob).hexdigest()
        (agent / "g06_baseline.json").write_text(json.dumps(base, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (agent / "audit_baseline.json").write_text(json.dumps({"version": 3, "description": "Baseline technical debt and legacy warnings snapshot (Ratchet pattern)", "created": date, "total_baseline_warnings": 0, "findings": []}, indent=2) + "\n", encoding="utf-8")
    finally:
        sys.path.remove(str(out / "AI-Agent/scripts"))
    return ["AI-Agent/operations.md", "AI-Agent/last-runs.md", "AI-Agent/state/decision-ledger.sqlite3", "AI-Agent/state/operations.sqlite3",
            "AI-Agent/state/injection-log.jsonl", "AI-Agent/g06_baseline.json", "AI-Agent/audit_baseline.json"]


def release_date(root: Path) -> str:
    import re as _re
    m = _re.search(r"^## \[\d[^\]]*\] - (\d{4}-\d{2}-\d{2})", (root / OVERLAY / "CHANGELOG.md").read_text(encoding="utf-8"), _re.M)
    if not m:
        raise ExportError("the overlay CHANGELOG.md has no dated release heading")
    return m.group(1)


CRITICAL_FILES = ["AI-Agent/scripts/audit.py", "AI-Agent/scripts/_vaultlib.py", "AI-Agent/scripts/upgrade_core.py", "AI-Agent/schema/frontmatter.yaml", "AI-Agent/schema/decision_ledger.py"]
BASE_PREFIXES = ("AI-Agent/", ".githooks/", ".github/", ".cursor/", ".agents/", "LICENSES/")
BASE_FILES = {"LICENSE", "VERSION", "AGENTS.md", "CLAUDE.md", "THIRD-PARTY-NOTICES.md", "CITATION.cff", "release_manifest.json", ".gitignore"}
ADD_ONLY_FILES = {"AI-Agent/operations.md", "AI-Agent/last-runs.md", "AI-Agent/g06_baseline.json", "AI-Agent/audit_baseline.json", "Dashboard.md", "Active-Work.base"}
MERGE_FILES = {"AI-Agent/handoff.md", "AI-Agent/rules.md", "AI-Agent/permanent-layer.md", "AGENTS.md", "CLAUDE.md", "AI-Agent/config/release_profile.yaml", "AI-Agent/config/limits.yaml",
               "README.md", "GETTING-STARTED.md"}


def policy_of(rel: str) -> str:
    """How an upgrade treats a shipped file (upgrade_core POLICIES): code is replaced, the notes a person edits are merged, state and
    folders that become the person's own are never overwritten."""
    if rel.startswith(".obsidian/"):
        if rel == ".obsidian/community-plugins.json":
            return "union"
        if rel.endswith(".json") and rel != ".obsidian/plugins.lock.json":
            return "json-merge"
        return "replace"
    if rel.startswith(("AI-Agent/state/", "02-Areas/", "00-Inbox/", "01-Projects/", "04-Archive/", "05-Zettelkasten/")) or rel in ADD_ONLY_FILES:
        return "add-only"
    if rel in MERGE_FILES or rel.startswith(("Templates/", ".cursor/", "03-Resources/", "06-MOCs/")):
        return "merge"
    return "replace"


SKIP_DIRS = (".git", ".vault-release", ".venv", "__pycache__", "node_modules")


def _tree_env() -> dict:
    """The environment for a git command that works on the BUILT tree: a commit hook runs with GIT_INDEX_FILE, GIT_DIR and friends set, and a git
    command in another directory that inherits them reads and WRITES the committing repository's index (found 2026-11-19: `git commit --only` through the
    gate failed with an invalid object because `git add -A` in the built tree wrote the release's files into the commit's temporary index)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def tree_files(tree: Path) -> list[str]:
    """The files a release consists of, as sorted posix paths. In a git checkout that is what git tracks or would track (a CI runner adds
    .venv and caches that are none of the release); in a bare tree it is every file outside the skipped folders."""
    if (tree / ".git").exists():
        r = subprocess.run(["git", "-c", "core.quotepath=off", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=tree, capture_output=True, env=_tree_env())
        if r.returncode == 0:
            names = {n.decode("utf-8") for n in r.stdout.split(b"\0") if n}
            return sorted(n for n in names if (tree / n).is_file())
    return sorted(f.relative_to(tree).as_posix() for f in tree.rglob("*")
                  if f.is_file() and not set(f.relative_to(tree).parts[:-1]) & set(SKIP_DIRS))


def build_manifest(out: Path) -> dict:
    version = (out / "VERSION").read_text(encoding="utf-8").strip()
    files = {}
    for rel in tree_files(out):
        f = out / rel
        if rel.split("/")[0] in (".git", ".vault-release") or rel == "release_manifest.json":
            continue
        files[rel] = {"sha256": hashlib.sha256(f.read_bytes()).hexdigest(), "policy": policy_of(rel)}
    return {"format_version": 2, "version": version, "files": files, "critical": [c for c in CRITICAL_FILES if c in files],
            "migrations": [], "breaking_changes": [], "cli_migrations": []}


def write_manifest(out: Path) -> dict:
    man = build_manifest(out)
    (out / "release_manifest.json").write_text(json.dumps(man, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return man


def _zip(tree: Path, names: list[str], dest: Path) -> int:
    """A deterministic archive: sorted members, fixed timestamp, fixed permissions, so one tree always gives one hash."""
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in sorted(names):
            src = tree / rel
            zi = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = (0o755 if src.stat().st_mode & stat.S_IXUSR else 0o644) << 16
            z.writestr(zi, src.read_bytes())
    return dest.stat().st_size


def build_archives(tree: Path, dist: Path) -> dict:
    """base.zip (the core an upgrade reads, at most 1 MB), full.zip (the whole vault) and SHA256SUMS."""
    dist.mkdir(parents=True, exist_ok=True)
    names = [n for n in tree_files(tree) if n.split("/")[0] not in (".git", ".vault-release")]
    base = [n for n in names if n in BASE_FILES or n.startswith(BASE_PREFIXES)]
    dir_bytes = {
        prefix.rstrip("/"): sum((tree / n).stat().st_size for n in base if n.startswith(prefix))
        for prefix in ("AI-Agent/scripts/", "AI-Agent/state/")
    }
    sizes = {"base.zip": _zip(tree, base, dist / "base.zip"), "full.zip": _zip(tree, names, dist / "full.zip")}
    (dist / "SHA256SUMS").write_text("".join(f"{hashlib.sha256((dist / n).read_bytes()).hexdigest()}  {n}\n" for n in sorted(sizes)), encoding="utf-8")
    if sizes["base.zip"] > BASE_ZIP_MAX_BYTES:
        raise ExportError(f"base.zip is {sizes['base.zip']} bytes, over the {BASE_ZIP_MAX_BYTES} B limit")
    if dir_bytes["AI-Agent/state"] > STATE_RAW_MAX_BYTES:
        raise ExportError(f"AI-Agent/state is {dir_bytes['AI-Agent/state']} bytes, over the {STATE_RAW_MAX_BYTES} B limit")
    return {"members": {"base.zip": len(base), "full.zip": len(names)}, "bytes": sizes, "dir_bytes": dir_bytes}


def seed_upgrade_state(out: Path, man: dict) -> list[str]:
    """Seed .vault-release/installed.json and .vault-release/base/<rel> for factory three-way merges."""
    rel_dir = out / ".vault-release"
    rel_dir.mkdir(parents=True, exist_ok=True)
    installed = {
        "version": man["version"],
        "files": {r: e["sha256"] for r, e in sorted(man["files"].items()) if e["policy"] != "keep"},
    }
    (rel_dir / "installed.json").write_text(json.dumps(installed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    made = [".vault-release/installed.json"]
    for rel, e in sorted(man["files"].items()):
        if e["policy"] == "merge" and (out / rel).is_file():
            dest = rel_dir / "base" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((out / rel).read_bytes())
            made.append(f".vault-release/base/{rel}")
    return made


def init_repo(out: Path) -> None:
    """A fresh git repository with the pre-commit hook wired and every file staged; the first commit is the owner's."""
    for args in (["init", "-q"], ["config", "core.hooksPath", ".githooks"], ["add", "-A"]):
        r = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=out, capture_output=True, text=True, encoding="utf-8", errors="replace", env=_tree_env())
        if r.returncode != 0:
            raise ExportError(f"git {args[0]} failed: {r.stderr.strip()[:200]}")
    execs = [rel for rel in EXECUTABLE_FILES if (out / rel).is_file()]
    if execs:
        r = subprocess.run(["git", "-c", "core.quotepath=off", "update-index", "--chmod=+x", *execs], cwd=out, capture_output=True, text=True, encoding="utf-8", errors="replace", env=_tree_env())
        if r.returncode != 0:
            raise ExportError(f"git update-index failed: {r.stderr.strip()[:200]}")


def write_release(root: Path, out: Path, plan: dict | None = None) -> dict:
    """Build the release tree under `out` (which must not exist or be empty). Returns {'written': n, 'skipped_seeds': [...], 'findings': [...]}."""
    from _vaultlib import apply_patch, canonical_sha256, derive_obsidian, dump_yaml_block, release_contract
    manifest_doc = load_manifest(root)
    plan = plan or build_plan(root)
    if plan["findings"]:
        raise ExportError("the plan has findings; nothing was written")
    if out.exists() and any(out.iterdir()):
        raise ExportError(f"{out} is not empty")
    patches = root / "AI-Agent/config/release-patches"
    out.mkdir(parents=True, exist_ok=True)
    written, skipped = 0, []

    def put(rel: str, data: bytes, mode_from: Path | None = None) -> None:
        nonlocal written
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if Path(rel).suffix.lower() in TEXT_EXT | {".cmd", ".bat", ".ps1", ".toml"} or Path(rel).name in TEXT_NAMES:
            data = data.replace(b"\r\n", b"\n")   # the release is LF everywhere: its hashes must not depend on the author's checkout
        if rel.endswith(".py"):
            data = add_spdx(data.decode("utf-8")).encode("utf-8")
        dest.write_bytes(data)
        if mode_from is not None and mode_from.exists() and mode_from.stat().st_mode & stat.S_IXUSR:
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        written += 1

    obsidian_done = False
    release_edits = load_release_edits(root)
    for rel, (action, rid, via) in sorted(plan["files"].items()):
        src = root / rel
        if action == "drop":
            continue
        if action == "overlay":
            f = root / OVERLAY / rel
            put(rel, f.read_bytes(), f)
        elif action == "copy":
            put(rel, src.read_bytes(), src)
        elif action == "sanitize":
            if rel.endswith(".py"):
                put(rel, apply_release_edits(sanitize_script(src.read_text(encoding="utf-8"), rel), rel, release_edits).encode("utf-8"), src)
            else:
                put(rel, src.read_bytes(), src)
        elif action == "seed":
            skipped.append(rel)
        elif action == "derive":
            if via == "obsidian":
                if not obsidian_done:
                    texts, _, unclassified = derive_obsidian(root, patches)
                    if unclassified:
                        raise ExportError(f"unclassified .obsidian files: {unclassified}")
                    for r, text in texts.items():
                        put(r, text.encode("utf-8"))
                    obsidian_done = True
            elif via == "frontmatter-patch":
                doc = yaml.safe_load(src.read_text(encoding="utf-8"))
                put(rel, dump_yaml_block(apply_patch(doc, yaml.safe_load((patches / "frontmatter.patch.yaml").read_text(encoding="utf-8")))).encode("utf-8"))
            elif via == "interface-patch":
                doc = yaml.safe_load(src.read_text(encoding="utf-8"))
                put(rel, dump_yaml_block(apply_patch(doc, yaml.safe_load((patches / "interface.patch.yaml").read_text(encoding="utf-8")))).encode("utf-8"))
            elif via == "contracts":
                name = {"AI-Agent/contracts/decision-log-v1.0.0.json": "contract-decision-log", "AI-Agent/contracts/skill-record-v1.0.0.json": "contract-skill-record"}.get(rel)
                if not name:
                    raise ExportError(f"no contract patch for {rel}")
                doc = json.loads(src.read_text(encoding="utf-8"))
                put(rel, (json.dumps(release_contract(doc, yaml.safe_load((patches / f"{name}.patch.yaml").read_text(encoding="utf-8"))), indent=4, ensure_ascii=False) + "\n").encode("utf-8"))
            elif via == "release-profile":
                put(rel, derive_profile(root).encode("utf-8"))
            elif via == "test-classification":
                put(rel, seed_test_classification(root).encode("utf-8"))
            else:
                raise ExportError(f"unknown derive step {via!r} for {rel}")
    env = {**os.environ, "VAULT": str(out), "STRATUM_NET_LOG": os.devnull}
    r = subprocess.run([sys.executable, str(out / "AI-Agent/scripts/derive_live_arch.py"), "--derive"], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=out)
    if r.returncode != 0:
        raise ExportError(f"the live architecture document could not be derived: {(r.stderr or r.stdout)[-300:]}")
    made = seed_tree(root, out, release_date(root))
    missing = sorted(set(skipped) - set(made))
    if missing:
        raise ExportError(f"seeds the plan lists but nothing generated: {missing}")
    man = write_manifest(out)
    seed_upgrade_state(out, man)
    findings = check_tree(out, privacy_patterns=manifest_doc.get("privacy_denylist") or ())
    if not findings:
        init_repo(out)
    return {"written": written + len(made) + 1, "skipped_seeds": [], "findings": findings}


def main(argv=None) -> int:
    force_utf8_stdio()
    ap = standard_parser(__doc__, "export_release")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--package", action="store_true", help="pack the current tree (a release checkout) into base.zip, full.zip and SHA256SUMS in --dist")
    ap.add_argument("--out", default="")
    ap.add_argument("--dist", default="", help="with --write: also build base.zip, full.zip and SHA256SUMS here")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = Path(os.environ.get("VAULT") or Path(__file__).resolve().parents[2])
    if args.package:
        if not args.dist:
            print("export_release: --package needs --dist DIR", file=sys.stderr)
            return 2
        try:
            stored = json.loads((root / "release_manifest.json").read_text(encoding="utf-8"))
            if stored != build_manifest(root):
                raise ExportError("release_manifest.json does not match the files of this tree; rebuild the release")
            arc = build_archives(root, Path(args.dist))
        except (ExportError, OSError, ValueError) as e:
            print(f"export_release: {e}", file=sys.stderr)
            return 1
        print(f"ARCHIVES base.zip {arc['bytes']['base.zip']} B, full.zip {arc['bytes']['full.zip']} B in {args.dist}")
        return 0
    if args.write:
        if not args.out:
            print("export_release: --write needs --out DIR", file=sys.stderr)
            return 2
        try:
            res = write_release(root, Path(args.out))
        except ExportError as e:
            print(f"export_release: {e}", file=sys.stderr)
            return 1
        print(f"WROTE {res['written']} file(s) to {args.out}")
        if args.dist and not res["findings"]:
            try:
                arc = build_archives(Path(args.out), Path(args.dist))
            except ExportError as e:
                print(f"export_release: {e}", file=sys.stderr)
                return 1
            print(f"ARCHIVES base.zip {arc['bytes']['base.zip']} B ({arc['members']['base.zip']} members), full.zip {arc['bytes']['full.zip']} B ({arc['members']['full.zip']} members) in {args.dist}")
        for g, p, why in res["findings"][:40]:
            print(f"GATE {g}  {p}  {why}")
        print(f"EXPORT-WRITE {'clean' if not res['findings'] else 'findings'} ({len(res['findings'])})")
        return 1 if res["findings"] else 0
    try:
        plan = build_plan(root)
    except ExportError as e:
        print(f"export_release: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({k: v for k, v in plan.items() if k != "files"}, ensure_ascii=False, indent=1))
    else:
        for a in ACTIONS:
            print(f"{a:9} {plan['counts'].get(a, 0):5}")
        print(f"{'total':9} {plan['total']:5}   (overlay-only files: {plan['overlay_new']})")
        print(f"tools     {plan['tools']['built']}/{plan['tools']['declared']} release tools built")
        for k, n in sorted(plan["pending_sanitizers"].items()):
            print(f"pending   sanitizer {k}: {n} file(s) not yet sanitized by the exporter")
        for kind, what, why in plan["notes"]:
            print(f"note      {kind} {what}: {why}")
        for kind, what, why in plan["findings"]:
            print(f"FINDING   {kind} {what}: {why}")
    print(f"EXPORT-PLAN {'complete' if not plan['findings'] else 'blocked'} ({len(plan['findings'])} finding(s))")
    return 1 if plan["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
