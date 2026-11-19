# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""upgrade_core.py — upgrade an installed Stratum vault from a newer release without losing local work.

Usage:
  python AI-Agent/scripts/upgrade_core.py --check
  python AI-Agent/scripts/upgrade_core.py --from <release.zip | release-dir | https://...zip --sha256 HEX>
                                           [--dry-run] [--yes] [--ack] [--no-sync] [--skip-verify]

A release carries `release_manifest.json` (format_version 1 or 2): every file with its SHA-256 and a policy.
  replace   core file: updated when the local copy is unmodified; a modified one is kept and the upstream copy is
            parked in .vault-release/conflicts/ (a modified `critical` file stops the upgrade: HIGH conflict-skew)
  merge     text file: three-way merge (base = what the last install/upgrade wrote, local, upstream); overlaps go to
            .vault-release/conflicts/ with markers and the local file is kept
  union     JSON list: local items, then upstream items that are missing
  json-merge JSON object: upstream keys that are missing are added; local values win
  add-only  created when missing, never overwritten        keep    never touched
Nothing is written before the whole plan is known; before the first write the files it will change are saved in
.vault-release/backups/ (restore with restore_pre_upgrade.py). Breaking changes write .vault-release/pending-review.json
and need --ack. Source members are read in memory and never extracted (no Zip Slip). Standard library only.
Exit code: 0 done (or nothing to do), 1 stopped (review needed, HIGH conflict-skew, conflicts left, verification failed),
2 bad arguments or a bad release.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

RELEASE_DIR = ".vault-release"
INSTALLED = f"{RELEASE_DIR}/installed.json"
EXECUTABLE_FILES = frozenset({".githooks/pre-commit", "setup.sh", "AI-Agent/vault-python"})
POLICIES = {"replace", "merge", "union", "json-merge", "add-only", "keep"}
ALLOWED_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")
MAX_ZIP = 256 * 1024 * 1024


class UpgradeError(Exception):
    """A release or an argument that must stop the upgrade before anything is written."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*))?$")


def vtuple(v: str) -> tuple:
    """A version as a sortable tuple, by SemVer 2.0 precedence: 1.0.0-beta.1 < 1.0.0-beta.2 < 1.0.0-rc.1 < 1.0.0. Build metadata is not accepted."""
    m = _SEMVER.match(v) if isinstance(v, str) else None
    if not m:
        raise UpgradeError(f"bad version {v!r}")
    core = tuple(int(x) for x in m.groups()[:3])
    if m.group(4) is None:
        return core + (1,)                                      # a release sorts after every pre-release of the same core
    ids = tuple((0, int(i), "") if i.isdigit() else (1, 0, i) for i in m.group(4).split("."))   # numeric identifiers sort below alphanumeric ones
    return core + (0, ids)


def safe_rel(name: str) -> str:
    """A release-relative path that can never leave the vault: no absolute path, no `..`, no drive, no backslash."""
    p = PurePosixPath(name)
    if not name or name.startswith(("/", "\\")) or "\\" in name or ":" in name.split("/")[0] or ".." in p.parts or p.parts[0] == ".git":
        raise UpgradeError(f"unsafe path in the release: {name!r}")
    return p.as_posix()


# ---------------------------------------------------------------- sources
class Source:
    def __init__(self, reader, label: str):
        self._read, self.label = reader, label
        self.manifest = load_manifest(self.read("release_manifest.json"))

    def read(self, rel: str) -> bytes:
        return self._read(rel)

    @classmethod
    def from_dir(cls, path: Path) -> "Source":
        root = path.resolve()

        def reader(rel):
            f = (root / safe_rel(rel)).resolve()
            if root not in f.parents or not f.is_file():
                raise UpgradeError(f"release member not found: {rel}")
            return f.read_bytes()
        return cls(reader, str(path))

    @classmethod
    def from_zip_bytes(cls, data: bytes, label: str) -> "Source":
        z = zipfile.ZipFile(io.BytesIO(data))
        names = {n for n in z.namelist() if not n.endswith("/")}
        top = {n.split("/", 1)[0] for n in names}
        prefix = ""
        if "release_manifest.json" not in names and len(top) == 1 and f"{next(iter(top))}/release_manifest.json" in names:
            prefix = next(iter(top)) + "/"

        def reader(rel):
            member = prefix + safe_rel(rel)
            if member not in names:
                raise UpgradeError(f"release member not found: {rel}")
            info = z.getinfo(member)
            if info.file_size > MAX_ZIP:
                raise UpgradeError(f"release member too large: {rel}")
            return z.read(member)
        return cls(reader, label)

    @classmethod
    def open(cls, spec: str, expect_sha: str = "") -> "Source":
        if spec.startswith("gh:"):
            raise UpgradeError("gh:<tag> sources need `gh attestation verify`, which this version does not implement; download the archive and use --from <file.zip>")
        if spec.startswith("https://"):
            u = urllib.parse.urlsplit(spec)
            if u.hostname not in ALLOWED_HOSTS or u.username or u.password:
                raise UpgradeError(f"refused URL (an allowed host only): {spec}")
            if not expect_sha:
                raise UpgradeError("an https source needs --sha256 of the archive")
            with urllib.request.urlopen(urllib.request.Request(spec, headers={"User-Agent": "stratum-upgrade"}), timeout=120) as r:
                data = r.read(MAX_ZIP + 1)
            if len(data) > MAX_ZIP:
                raise UpgradeError("archive too large")
            if sha256(data) != expect_sha.lower():
                raise UpgradeError("the downloaded archive does not match --sha256; nothing was used")
            return cls.from_zip_bytes(data, spec)
        p = Path(spec)
        if p.is_dir():
            return cls.from_dir(p)
        if p.is_file() and zipfile.is_zipfile(p):
            data = p.read_bytes()
            if expect_sha and sha256(data) != expect_sha.lower():
                raise UpgradeError("the archive does not match --sha256")
            return cls.from_zip_bytes(data, str(p))
        raise UpgradeError(f"not a release directory or zip archive: {spec}")


def load_manifest(raw: bytes) -> dict:
    try:
        m = json.loads(raw.decode("utf-8"))
        fv = m["format_version"]
        if fv not in (1, 2):
            raise UpgradeError(f"unsupported release_manifest format_version {fv}")
        vtuple(m["version"])
        files = {}
        for rel, e in m["files"].items():
            rel = safe_rel(rel)
            if e.get("policy", "replace") not in POLICIES or len(e["sha256"]) != 64:
                raise UpgradeError(f"bad manifest entry for {rel}")
            files[rel] = {"sha256": e["sha256"], "policy": e.get("policy", "replace")}
        out = {"format_version": fv, "version": m["version"], "files": files,
               "critical": [safe_rel(x) for x in (m.get("critical") or [])] if fv == 2 else [],
               "migrations": m.get("migrations") or [],
               "breaking_changes": (m.get("breaking_changes") or []) if fv == 2 else [],
               "cli_migrations": (m.get("cli_migrations") or []) if fv == 2 else []}
        for mig in out["migrations"]:
            vtuple(mig["from"]), vtuple(mig["to"])
            for st in mig["steps"]:
                if st["op"] not in ("rename", "delete"):
                    raise UpgradeError(f"unsupported migration step {st['op']!r}")
                for k in ("from", "to", "path"):
                    if k in st:
                        safe_rel(st[k])
        return out
    except UpgradeError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise UpgradeError(f"bad release_manifest.json: {e.__class__.__name__}: {e}") from e


# ---------------------------------------------------------------- merge
def _hunks(base: list, other: list) -> list:
    sm = difflib.SequenceMatcher(None, base, other, autojunk=False)
    return [(i1, i2, other[j1:j2]) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]


def _pure_python_diff3(base: str, local: str, upstream: str) -> tuple[str, int]:
    """A three-way merge on lines. Hunks of the two sides that touch or overlap in the base are one conflict unless both made
    the same change. Returns (text, number of conflicts); conflict blocks use the diff3 markers."""
    b, l, u = base.splitlines(True), local.splitlines(True), upstream.splitlines(True)
    hl, hu = _hunks(b, l), _hunks(b, u)
    out, pos, conflicts, i, j = [], 0, 0, 0, 0
    while i < len(hl) or j < len(hu):
        a = hl[i] if i < len(hl) else None
        c = hu[j] if j < len(hu) else None
        if a and (not c or a[1] < c[0]):          # a local hunk strictly before the next upstream one
            out += b[pos:a[0]] + a[2]
            pos, i = a[1], i + 1
        elif c and (not a or c[1] < a[0]):
            out += b[pos:c[0]] + c[2]
            pos, j = c[1], j + 1
        else:                                       # they touch or overlap: grow the region over every hunk that joins it
            start, end = min(a[0], c[0]), max(a[1], c[1])
            ii, jj = i + 1, j + 1
            grown = True
            while grown:
                grown = False
                while ii < len(hl) and hl[ii][0] <= end:
                    end, ii, grown = max(end, hl[ii][1]), ii + 1, True
                while jj < len(hu) and hu[jj][0] <= end:
                    end, jj, grown = max(end, hu[jj][1]), jj + 1, True
            lt = _apply(b, hl[i:ii], start, end)
            ut = _apply(b, hu[j:jj], start, end)
            out += b[pos:start]
            if lt == ut:
                out += lt
            else:
                conflicts += 1
                out += ["<<<<<<< local\n"] + lt + ["||||||| base\n"] + b[start:end] + ["=======\n"] + ut + [">>>>>>> upstream\n"]
            pos, i, j = end, ii, jj
    out += b[pos:]
    return "".join(out), conflicts


def _apply(base: list, hunks: list, start: int, end: int) -> list:
    res, pos = [], start
    for h1, h2, new in hunks:
        res += base[pos:h1] + new
        pos = h2
    return res + base[pos:end]


def merge3(base: str, local: str, upstream: str) -> tuple[str, int, str]:
    """(merged text, conflict count, engine). `git merge-file --diff3` when git is there, else the pure-python merge."""
    if shutil.which("git"):
        with tempfile.TemporaryDirectory(prefix="merge3-") as d:
            paths = []
            for name, text in (("local", local), ("base", base), ("upstream", upstream)):
                p = Path(d) / name
                p.write_bytes(text.encode("utf-8"))
                paths.append(str(p))
            r = subprocess.run(["git", "-c", "core.quotepath=off", "merge-file", "-p", "--diff3", "-L", "local", "-L", "base", "-L", "upstream", *paths],
                               capture_output=True)
            if 0 <= r.returncode < 127:
                return r.stdout.decode("utf-8", "replace"), r.returncode, "git"
    text, n = _pure_python_diff3(base, local, upstream)
    return text, n, "python"


# ---------------------------------------------------------------- files
def write_atomic(dest: Path, data: bytes, retries: int = 5, *, mode: int | None = None, executable: bool = False, sleeper=time.sleep) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".upgrade-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if os.name != "nt":
            if mode is not None:
                os.chmod(tmp, mode)
            elif executable:
                os.chmod(tmp, 0o755)
            elif dest.exists():
                os.chmod(tmp, stat.S_IMODE(dest.stat().st_mode))
            else:
                os.chmod(tmp, 0o644)
        for n in range(retries):
            try:
                os.replace(tmp, dest)
                return
            except PermissionError:                  # Windows: another process holds the file for a moment
                if n == retries - 1:
                    raise
                sleeper(0.2 * (n + 1))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_installed(root: Path) -> dict | None:
    f = root / INSTALLED
    if not f.is_file():
        return _installed_from_manifest(root)
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        vtuple(d["version"])
        return d
    except (ValueError, KeyError, UpgradeError):
        raise UpgradeError(f"{INSTALLED} is unreadable")


def _installed_from_manifest(root: Path) -> dict | None:
    """A `git clone` install has no .vault-release/installed.json but ships release_manifest.json: what the manifest lists
    (minus the keep-policy files) is exactly what was installed. The result carries source=release_manifest so callers can say so."""
    f = root / "release_manifest.json"
    if not f.is_file():
        return None
    try:
        man = json.loads(f.read_text(encoding="utf-8"))
        vtuple(man["version"])
        files = {r: e["sha256"] for r, e in man["files"].items() if e.get("policy", "replace") != "keep"}
    except (ValueError, KeyError, TypeError, AttributeError, UpgradeError):
        return None
    return {"version": man["version"], "files": files, "source": "release_manifest"}


def _json_union(local: bytes, up: bytes) -> bytes:
    a, b = json.loads(local), json.loads(up)
    if not isinstance(a, list) or not isinstance(b, list):
        raise UpgradeError("union policy needs JSON lists")
    return (json.dumps(a + [x for x in b if x not in a], indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _json_deep(local, up):
    if isinstance(local, dict) and isinstance(up, dict):
        out = dict(local)
        for k, v in up.items():
            out[k] = _json_deep(local[k], v) if k in local else v
        return out
    return local


def _json_merge(local: bytes, up: bytes) -> bytes:
    return (json.dumps(_json_deep(json.loads(local), json.loads(up)), indent=2, ensure_ascii=False) + "\n").encode("utf-8")


# ---------------------------------------------------------------- plan
def plan(root: Path, src: Source, installed: dict | None) -> dict:
    """Decide every file; writes nothing. Entries: (kind, rel, bytes|None, info)."""
    man = src.manifest
    base_files = (installed or {}).get("files", {})
    acts, conflicts, critical_hit = [], [], []
    for rel, e in sorted(man["files"].items()):
        new = src.read(rel)
        if sha256(new) != e["sha256"]:
            raise UpgradeError(f"the release is damaged or tampered: {rel} does not match its manifest hash")
        pol, dest = e["policy"], root / rel
        local = dest.read_bytes() if dest.is_file() else None
        if pol == "keep":
            continue
        if local is None:
            acts.append(("add", rel, new, ""))
            continue
        if pol == "add-only" or sha256(local) == e["sha256"]:
            continue
        if pol == "union":
            acts.append(("update", rel, _json_union(local, new), "union"))
        elif pol == "json-merge":
            acts.append(("update", rel, _json_merge(local, new), "json-merge"))
        elif pol == "replace":
            if base_files.get(rel) == sha256(local):
                acts.append(("update", rel, new, ""))
            else:
                conflicts.append((rel, "local-modified", new))
                if rel in man["critical"]:
                    critical_hit.append(rel)
        else:  # merge
            base_f = root / RELEASE_DIR / "base" / rel
            if base_files.get(rel) == sha256(local):
                acts.append(("update", rel, new, ""))
            elif base_f.is_file():
                text, n, engine = merge3(base_f.read_text(encoding="utf-8"), local.decode("utf-8"), new.decode("utf-8"))
                if n == 0:
                    acts.append(("update", rel, text.encode("utf-8"), f"merged ({engine})"))
                else:
                    conflicts.append((rel, f"merge-conflict x{n} ({engine})", text.encode("utf-8")))
                    if rel in man["critical"]:
                        critical_hit.append(rel)
            else:
                conflicts.append((rel, "local-modified-no-base", new))
                if rel in man["critical"]:
                    critical_hit.append(rel)
    for rel, h in sorted(base_files.items()):          # files the new release no longer has
        if rel not in man["files"] and (root / rel).is_file():
            if sha256((root / rel).read_bytes()) == h:
                acts.append(("delete", rel, None, "removed upstream"))
            else:
                conflicts.append((rel, "orphan-kept: removed upstream but modified locally", None))
    return {"acts": acts, "conflicts": conflicts, "critical": critical_hit}


def chain(man: dict, installed_version: str) -> list:
    lo, hi = vtuple(installed_version), vtuple(man["version"])
    return sorted((m for m in man["migrations"] if lo <= vtuple(m["from"]) and vtuple(m["to"]) <= hi), key=lambda m: vtuple(m["from"]))


def review_items(man: dict) -> list:
    return [{"kind": "breaking_change", **b} for b in man["breaking_changes"]] + [{"kind": "cli_migration", **c} for c in man["cli_migrations"]]


# ---------------------------------------------------------------- run
def make_backup(root: Path, paths: list[str], added: list[str], version_before: str) -> Path:
    bdir = root / RELEASE_DIR / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    z = bdir / f"{version_before}-{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}.zip"
    meta = {"format": 1, "version_before": version_before, "files": {}, "added": sorted(added)}
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in sorted(set(paths) | {INSTALLED}):
            f = root / rel
            if f.is_file():
                data = f.read_bytes()
                meta["files"][rel] = sha256(data)
                zf.writestr(f"files/{rel}", data)
        zf.writestr("backup.json", json.dumps(meta, indent=2))
    return z


def run_upgrade(root: Path, src: Source, dry_run=False, ack=False, no_sync=True, skip_verify=True, out=print) -> int:
    man = src.manifest
    installed = read_installed(root)
    if installed and vtuple(man["version"]) <= vtuple(installed["version"]):
        out(f"UPGRADE nothing to do: installed {installed['version']} is not older than {man['version']}")
        return 0
    p = plan(root, src, installed)
    from_v = installed["version"] if installed else "0.0.0"
    out(f"UPGRADE {from_v} -> {man['version']}  source={src.label}")
    for kind, rel, _, info in p["acts"]:
        out(f"  {kind.upper():7} {rel}" + (f"  ({info})" if info else ""))
    for rel, why, _ in p["conflicts"]:
        out(f"  CONFLICT {rel}: {why}")
    items = review_items(man)
    if p["critical"]:
        out(f"UPGRADE stopped: HIGH conflict-skew on critical files {p['critical']}; nothing was written. Resolve them or take the release's copy from {RELEASE_DIR}/conflicts after a dry run.")
        if not dry_run:
            _park(root, p)
        return 1
    if dry_run:
        out("UPGRADE dry run: nothing was written")
        return 0
    if items and not ack:
        write_atomic(root / RELEASE_DIR / "pending-review.json", (json.dumps({"version": man["version"], "items": items}, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        out(f"UPGRADE stopped: {len(items)} breaking change(s) to review in {RELEASE_DIR}/pending-review.json; run again with --ack")
        return 1
    changed = [r for k, r, _, _ in p["acts"] if k in ("update", "delete")]
    added = [r for k, r, _, _ in p["acts"] if k == "add"]
    renames = [st for m in chain(man, from_v) for st in m["steps"]]
    changed += [st["from"] for st in renames if st["op"] == "rename"] + [st["path"] for st in renames if st["op"] == "delete"]
    backup = None
    if installed:                                   # a first install has nothing to go back to
        bases = [f"{RELEASE_DIR}/base/{r}" for r, e in man["files"].items() if e["policy"] == "merge"]   # the next merge's base moves with the files
        backup = make_backup(root, changed + [b for b in bases if (root / b).is_file()],
                             added + [b for b in bases if not (root / b).is_file()] + [st["to"] for st in renames if st["op"] == "rename"], from_v)
        out(f"UPGRADE backup {backup.relative_to(root).as_posix()}")
    for st in renames:                                           # migrations first: the new layout, then the new content
        if st["op"] == "rename" and (root / st["from"]).is_file() and not (root / st["to"]).exists():
            data = (root / st["from"]).read_bytes()
            write_atomic(root / st["to"], data, executable=(st["to"] in EXECUTABLE_FILES))
            (root / st["from"]).unlink()
            out(f"  MIGRATE rename {st['from']} -> {st['to']}")
        elif st["op"] == "delete" and (root / st["path"]).is_file():
            (root / st["path"]).unlink()
            out(f"  MIGRATE delete {st['path']}")
    for kind, rel, data, _ in p["acts"]:
        if kind == "delete":
            (root / rel).unlink()
        else:
            write_atomic(root / rel, data, executable=(rel in EXECUTABLE_FILES))
    _park(root, p)
    new_installed = {"version": man["version"], "files": {r: e["sha256"] for r, e in man["files"].items() if e["policy"] != "keep"}}
    # a file kept locally after a conflict stays on its old base hash, so the next upgrade still sees it as modified
    for rel, _, _ in p["conflicts"]:
        if rel in new_installed["files"] and installed:
            new_installed["files"][rel] = installed["files"].get(rel, new_installed["files"][rel])
    write_atomic(root / INSTALLED, (json.dumps(new_installed, indent=2) + "\n").encode("utf-8"))
    for rel, e in man["files"].items():                           # the base of the next three-way merge
        if e["policy"] == "merge" and (root / rel).is_file() and not any(c[0] == rel for c in p["conflicts"]):
            write_atomic(root / RELEASE_DIR / "base" / rel, src.read(rel))
    pr = root / RELEASE_DIR / "pending-review.json"
    if items and ack and pr.is_file():
        pr.unlink()
    out(f"UPGRADE applied {len(p['acts'])} change(s); {len(p['conflicts'])} left in {RELEASE_DIR}/conflicts")
    rc = 1 if p["conflicts"] else 0
    if not no_sync:
        rc = max(rc, _sync(root, out))
    if not skip_verify:
        rc = max(rc, _verify(root, backup, out))
    return rc


def _park(root: Path, p: dict) -> None:
    for rel, why, data in p["conflicts"]:
        if data is not None:
            suffix = "" if why.startswith("merge-conflict") else ".upstream"
            write_atomic(root / RELEASE_DIR / "conflicts" / (rel + suffix), data)


def _sync(root: Path, out) -> int:
    if not shutil.which("uv"):
        out("UPGRADE sync skipped: uv is not installed")
        return 0
    r = subprocess.run(["uv", "sync", "--locked", "--no-dev", "--no-editable"], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out("UPGRADE sync " + ("ok" if r.returncode == 0 else f"FAILED: {r.stderr.strip()[-200:]}"))
    if r.returncode == 0 and (root / ".venv").is_dir() and (root / "uv.lock").is_file():
        (root / ".venv" / ".stratum-lock-sha256").write_text(sha256((root / "uv.lock").read_bytes()) + "\n", encoding="utf-8")
    return 0 if r.returncode == 0 else 1


def _verify(root: Path, backup: Path | None, out) -> int:
    audit = root / "AI-Agent" / "scripts" / "audit.py"
    if not audit.is_file():
        out("UPGRADE verify skipped: no audit.py")
        return 0
    r = subprocess.run([sys.executable, str(audit), "--ratchet", "--no-cache"], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", env=dict(os.environ, VAULT=str(root)))
    if r.returncode == 0:
        out("UPGRADE verify: GATE CLEAR")
        return 0
    how = f"Restore with: python AI-Agent/scripts/restore_pre_upgrade.py --from {backup.relative_to(root).as_posix()}" if backup else "This was a first install: there is no backup."
    out(f"UPGRADE verify FAILED (audit exit {r.returncode}). {how}")
    return 1


def check(root: Path, out=print) -> int:
    inst = read_installed(root)
    if not inst:
        out(f"UPGRADE check: no {INSTALLED}; this tree was not installed from a release")
        return 1
    bad = 0
    for rel, h in sorted(inst["files"].items()):
        f = root / rel
        st = "OK" if f.is_file() and sha256(f.read_bytes()) == h else ("MISSING" if not f.is_file() else "MODIFIED")
        if st != "OK":
            bad += 1
            out(f"  {st:8} {rel}")
    out(f"UPGRADE check: version {inst['version']}, {len(inst['files']) - bad}/{len(inst['files'])} files as released")
    return 1 if bad else 0


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    text = (__doc__ or "").strip()
    ap = argparse.ArgumentParser(prog="upgrade_core", description=text.splitlines()[0], epilog=text, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="compare the tree with what the last release wrote")
    ap.add_argument("--from", dest="source", default="", help="release archive, directory or https URL")
    ap.add_argument("--sha256", default="", help="SHA-256 of the archive")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    ap.add_argument("--ack", action="store_true", help="acknowledge the breaking changes listed in pending-review.json")
    ap.add_argument("--no-sync", action="store_true", help="do not run uv sync")
    ap.add_argument("--skip-verify", action="store_true", help="do not run the audit gate afterwards")
    args = ap.parse_args(argv)
    root = Path(os.environ.get("VAULT") or Path(__file__).resolve().parents[2])
    try:
        if args.check:
            return check(root)
        if not args.source:
            ap.error("--from is required unless --check is given")
        src = Source.open(args.source, args.sha256)
        if not args.yes and not args.dry_run and sys.stdin.isatty():
            if input(f"Upgrade to {src.manifest['version']}? [y/N] ").strip().lower() != "y":
                print("UPGRADE cancelled")
                return 1
        return run_upgrade(root, src, args.dry_run, args.ack, args.no_sync, args.skip_verify)
    except UpgradeError as e:
        print(f"upgrade_core: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
