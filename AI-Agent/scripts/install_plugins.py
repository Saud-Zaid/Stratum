# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""install_plugins.py — install the Obsidian community plugins named in .obsidian/plugins.lock.json.

Usage: python AI-Agent/scripts/install_plugins.py [--check] [--only PLUGIN_ID] [--lock PATH] [--dry-run]

Plugin code is never stored in the repository. Each file is downloaded over HTTPS from the URL in the lock, from an allowed
host only (every redirect is checked too), is hashed in memory and written only when its SHA-256 equals the lock's; a file
that does not match is refused and nothing is written. `--check` needs no network: it verifies the installed files against the
lock. Obsidian rewrites an installed main.js (it appends a nosourcemap comment and strips an inline source map), so a main.js
is compared in that normalised form (`normalized_sha256` in the lock). Standard library only.
Exit code: 0 all good, 1 a file is missing, modified or refused, 2 a broken lock or arguments.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ALLOWED_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com", "raw.githubusercontent.com")
MAX_BYTES = 64 * 1024 * 1024
TIMEOUT = 60
LOCK_REL = ".obsidian/plugins.lock.json"
_SOURCEMAP = b"//# sourceMappingURL="
_NOSOURCEMAP = b"/* nosourcemap */"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_main(data: bytes) -> bytes:
    """main.js as Obsidian leaves it and as the release publishes it, brought to one form: no trailing nosourcemap comment,
    no inline source-map line, no trailing whitespace."""
    cut = data.rfind(_SOURCEMAP)
    if cut != -1 and b"\n" not in data[cut:].rstrip(b"\n"):
        data = data[:cut]
    data = data.rstrip()
    if data.endswith(_NOSOURCEMAP):
        data = data[: -len(_NOSOURCEMAP)].rstrip()
    return data


def check_url(url: str) -> None:
    """HTTPS to an allowed host, nothing else (no credentials in the URL, no other scheme)."""
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS or u.username or u.password:
        raise ValueError(f"refused URL (https and an allowed host only): {url}")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str) -> bytes:
    check_url(url)
    opener = urllib.request.build_opener(_SafeRedirect)
    with opener.open(urllib.request.Request(url, headers={"User-Agent": "stratum-install-plugins"}), timeout=TIMEOUT) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError(f"refused: {url} is larger than {MAX_BYTES} bytes")
    return data


def load_lock(path: Path) -> dict:
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
        assert lock["lock_version"] == 1 and isinstance(lock["plugins"], dict) and lock["plugins"]
        for pid, p in lock["plugins"].items():
            assert "/" not in pid and ".." not in pid and p["files"]
            for fn, f in p["files"].items():
                assert fn in ("main.js", "manifest.json", "styles.css") and len(f["sha256"]) == 64
                check_url(f["url"])
        return lock
    except (OSError, ValueError, KeyError, AssertionError, TypeError) as e:
        raise ValueError(f"broken lock {path}: {e.__class__.__name__}: {e}") from e


def file_state(root: Path, pid: str, fn: str, entry: dict) -> str:
    """OK, MISSING or MODIFIED for one installed file."""
    f = root / ".obsidian" / "plugins" / pid / fn
    if not f.is_file():
        return "MISSING"
    data = f.read_bytes()
    if sha256(data) == entry["sha256"]:
        return "OK"
    if fn == "main.js" and entry.get("normalized_sha256") and sha256(normalize_main(data)) == entry["normalized_sha256"]:
        return "OK"
    return "MODIFIED"


def write_atomic(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".install-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, dest)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def run(root: Path, lock: dict, only: str = "", check: bool = False, dry_run: bool = False, fetcher=fetch) -> list[tuple[str, str, str]]:
    """[(plugin, file, status)]: OK, MISSING, MODIFIED (check only), INSTALLED, WOULD-INSTALL, REFUSED (hash or URL)."""
    rows = []
    for pid, p in lock["plugins"].items():
        if only and pid != only:
            continue
        for fn, entry in p["files"].items():
            state = file_state(root, pid, fn, entry)
            if check or state == "OK":
                rows.append((pid, fn, state))
                continue
            if dry_run:
                rows.append((pid, fn, "WOULD-INSTALL"))
                continue
            try:
                data = fetcher(entry["url"])
            except (OSError, ValueError, urllib.error.URLError) as e:
                rows.append((pid, fn, f"REFUSED download failed: {e}"))
                continue
            if sha256(data) != entry["sha256"]:
                rows.append((pid, fn, "REFUSED hash mismatch: the file does not match the lock and was not written"))
                continue
            write_atomic(root / ".obsidian" / "plugins" / pid / fn, data)
            rows.append((pid, fn, "INSTALLED"))
    return rows


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    text = (__doc__ or "").strip()
    ap = argparse.ArgumentParser(prog="install_plugins", description=text.splitlines()[0], epilog=text,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="verify installed files against the lock; no network")
    ap.add_argument("--only", default="", help="one plugin id")
    ap.add_argument("--lock", default="", help=f"lock file (default {LOCK_REL})")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    root = Path(os.environ.get("VAULT") or Path(__file__).resolve().parents[2])
    try:
        lock = load_lock(Path(args.lock) if args.lock else root / LOCK_REL)
    except ValueError as e:
        print(f"install_plugins: {e}", file=sys.stderr)
        return 2
    if args.only and args.only not in lock["plugins"]:
        print(f"install_plugins: unknown plugin {args.only}", file=sys.stderr)
        return 2
    rows = run(root, lock, args.only, args.check, args.dry_run)
    for pid, fn, st in rows:
        print(f"{st.split()[0]:13} {pid}/{fn}" + (f"  {st.split(' ', 1)[1]}" if " " in st else ""))
    bad = [r for r in rows if r[2] not in ("OK", "INSTALLED", "WOULD-INSTALL")]
    print(f"INSTALL-PLUGINS {len(rows) - len(bad)}/{len(rows)} ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
