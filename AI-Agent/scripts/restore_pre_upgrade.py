# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""restore_pre_upgrade.py — put back what upgrade_core.py changed, from the backup it made first.

Usage: python AI-Agent/scripts/restore_pre_upgrade.py [--list] [--from BACKUP.zip] [--yes]

Without --from the newest backup in .vault-release/backups/ is used. Every file in the backup is checked against the hash the
backup recorded before it is written back; files the upgrade added are removed; `installed.json` goes back too, so the tree
is again exactly the release it was. Exit code: 0 restored, 1 refused (damaged backup or nothing to restore), 2 bad arguments.
Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from upgrade_core import RELEASE_DIR, UpgradeError, safe_rel, write_atomic  # noqa: E402


def backups(root: Path) -> list[Path]:
    d = root / RELEASE_DIR / "backups"
    return sorted(d.glob("*.zip"), key=lambda p: (p.stat().st_mtime, p.name)) if d.is_dir() else []


def restore(root: Path, zpath: Path, out=print) -> int:
    try:
        zf = zipfile.ZipFile(zpath)
        meta = json.loads(zf.read("backup.json").decode("utf-8"))
        assert meta["format"] == 1
        payload = {}
        for rel, h in meta["files"].items():
            data = zf.read(f"files/{safe_rel(rel)}")
            if hashlib.sha256(data).hexdigest() != h:
                out(f"RESTORE refused: {rel} in the backup does not match its recorded hash; nothing was changed")
                return 1
            payload[rel] = data
        added = [safe_rel(a) for a in meta["added"]]
    except (OSError, KeyError, ValueError, AssertionError, zipfile.BadZipFile, UpgradeError) as e:
        out(f"RESTORE refused: unreadable backup {zpath.name}: {e.__class__.__name__}: {e}")
        return 1
    for rel, data in payload.items():
        write_atomic(root / rel, data)
        out(f"  RESTORED {rel}")
    for rel in added:
        f = root / rel
        if f.is_file():
            f.unlink()
            out(f"  REMOVED  {rel}  (added by the upgrade)")
    out(f"RESTORE done: back to {meta['version_before']} from {zpath.name}")
    return 0


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    text = (__doc__ or "").strip()
    ap = argparse.ArgumentParser(prog="restore_pre_upgrade", description=text.splitlines()[0], epilog=text, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--from", dest="source", default="")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args(argv)
    root = Path(os.environ.get("VAULT") or Path(__file__).resolve().parents[2])
    found = backups(root)
    if args.list:
        for b in found:
            print(b.relative_to(root).as_posix())
        print(f"RESTORE {len(found)} backup(s)")
        return 0
    target = Path(args.source) if args.source else (found[-1] if found else None)
    if not target or not target.is_file():
        print("restore_pre_upgrade: no backup to restore", file=sys.stderr)
        return 1
    if not args.yes and sys.stdin.isatty() and input(f"Restore {target.name}? [y/N] ").strip().lower() != "y":
        print("RESTORE cancelled")
        return 1
    return restore(root, target)


if __name__ == "__main__":
    sys.exit(main())
