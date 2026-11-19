# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Tests for install_plugins.py. No network: the downloader is injected, and every case works in a temporary vault.
Usage: AI-Agent/vault-python AI-Agent/scripts/install_plugins-tests.py"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import install_plugins as IP

R = []
HERE = Path(__file__).resolve().parent


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


MAIN = b"console.log('plugin');\n"
MANI = b'{"id":"demo","version":"1.0.0"}\n'
URL = "https://github.com/o/demo/releases/download/1.0.0/"
lock = {"lock_version": 1, "plugins": {"demo": {"version": "1.0.0", "files": {
    "main.js": {"url": URL + "main.js", "sha256": IP.sha256(MAIN), "normalized_sha256": IP.sha256(IP.normalize_main(MAIN))},
    "manifest.json": {"url": URL + "manifest.json", "sha256": IP.sha256(MANI)}}}}}
ASSETS = {URL + "main.js": MAIN, URL + "manifest.json": MANI}
calls = []


def fetcher(url):
    calls.append(url)
    return ASSETS[url]


tmps = []


def vault():
    d = Path(tempfile.mkdtemp(prefix="instplug-"))
    tmps.append(d)
    return d


try:
    v = vault()
    rows = IP.run(v, lock, fetcher=fetcher)
    ok("T01-installs-every-file-and-writes-exactly-the-bytes", [r[2] for r in rows] == ["INSTALLED", "INSTALLED"] and (v / ".obsidian/plugins/demo/main.js").read_bytes() == MAIN)
    calls.clear()
    rows = IP.run(v, lock, fetcher=fetcher)
    ok("T02-second-run-is-a-no-op-without-network", [r[2] for r in rows] == ["OK", "OK"] and not calls, (rows, calls))

    v2 = vault()
    bad = dict(ASSETS)
    bad[URL + "main.js"] = MAIN + b"evil();"
    rows = IP.run(v2, lock, fetcher=lambda u: bad[u])
    ok("T03-a-tampered-download-is-refused-and-nothing-is-written", rows[0][2].startswith("REFUSED hash mismatch") and not (v2 / ".obsidian/plugins/demo/main.js").exists() and rows[1][2] == "INSTALLED", rows)
    ok("T04-no-temp-file-is-left-behind", not list((v2 / ".obsidian/plugins/demo").glob(".install-*")))

    v3 = vault()
    rows = IP.run(v3, lock, fetcher=lambda u: (_ for _ in ()).throw(OSError("offline")))
    ok("T05-a-download-failure-is-reported-not-raised", all(r[2].startswith("REFUSED download failed") for r in rows), rows)

    v4 = vault()
    IP.run(v4, lock, fetcher=fetcher)
    (v4 / ".obsidian/plugins/demo/manifest.json").write_bytes(b"{}")
    (v4 / ".obsidian/plugins/demo/main.js").unlink()
    ok("T06-check-reports-missing-and-modified-without-network", [r[2] for r in IP.run(v4, lock, check=True, fetcher=lambda u: (_ for _ in ()).throw(AssertionError("network used")))] == ["MISSING", "MODIFIED"])

    v5 = vault()
    IP.run(v5, lock, fetcher=fetcher)
    (v5 / ".obsidian/plugins/demo/main.js").write_bytes(MAIN + b"\n\n/* nosourcemap */")
    ok("T07-obsidians-nosourcemap-suffix-is-tolerated", IP.file_state(v5, "demo", "main.js", lock["plugins"]["demo"]["files"]["main.js"]) == "OK")
    (v5 / ".obsidian/plugins/demo/main.js").write_bytes(MAIN + b"evil();\n/* nosourcemap */")
    ok("T08-but-a-changed-body-with-the-suffix-is-still-modified", IP.file_state(v5, "demo", "main.js", lock["plugins"]["demo"]["files"]["main.js"]) == "MODIFIED")
    sm = b"body();\n//# sourceMappingURL=data:application/json;base64,AAAA"
    ok("T09-an-inline-source-map-is-normalised-away", IP.normalize_main(sm) == b"body();" and IP.normalize_main(b"body();\n\n/* nosourcemap */") == b"body();")
    ok("T10-sourcemap-marker-inside-code-is-not-cut", IP.normalize_main(b"x='//# sourceMappingURL=';\ny();") == b"x='//# sourceMappingURL=';\ny();")

    v6 = vault()
    rows = IP.run(v6, lock, dry_run=True, fetcher=fetcher)
    ok("T11-dry-run-writes-nothing", [r[2] for r in rows] == ["WOULD-INSTALL"] * 2 and not (v6 / ".obsidian").exists())
    ok("T12-only-filters-by-plugin-id", IP.run(v6, lock, only="other", dry_run=True) == [])

    for u in ("http://github.com/a", "https://evil.example.com/a", "https://user:pw@github.com/a", "ftp://github.com/a", "file:///etc/passwd", "https://github.com.evil.example/a"):
        try:
            IP.check_url(u)
            refused = False
        except ValueError:
            refused = True
        ok(f"T13-refuses-{u}", refused)
    ok("T14-allows-the-release-hosts", all(IP.check_url(u) is None for u in ("https://github.com/o/r/releases/download/1/main.js", "https://objects.githubusercontent.com/x")))

    class R404:  # a redirect to a disallowed host is refused by the handler
        pass
    try:
        IP._SafeRedirect().redirect_request(None, None, 302, "Found", {}, "https://evil.example.com/x")
        redirected = True
    except ValueError:
        redirected = False
    ok("T15-a-redirect-to-a-disallowed-host-is-refused", not redirected)

    p = v / "lock.json"
    for name, mutate in (("T16a-lock-with-a-path-traversal-id", lambda l: l["plugins"].__setitem__("../x", l["plugins"]["demo"])),
                         ("T16b-lock-with-an-unknown-file-name", lambda l: l["plugins"]["demo"]["files"].__setitem__("evil.exe", {"url": URL + "e", "sha256": "0" * 64})),
                         ("T16c-lock-with-a-short-hash", lambda l: l["plugins"]["demo"]["files"]["main.js"].__setitem__("sha256", "abc")),
                         ("T16d-lock-with-a-non-github-url", lambda l: l["plugins"]["demo"]["files"]["main.js"].__setitem__("url", "https://evil.example.com/main.js"))):
        broken = json.loads(json.dumps(lock))
        mutate(broken)
        p.write_text(json.dumps(broken), encoding="utf-8")
        try:
            IP.load_lock(p)
            refused = False
        except ValueError:
            refused = True
        ok(name, refused)
    p.write_text(json.dumps(lock), encoding="utf-8")
    ok("T17-a-valid-lock-loads", IP.load_lock(p)["plugins"].keys() == {"demo"})

    _orig_rep, _tries = os.replace, [0]
    def _flaky_rep_ip(a, b):
        _tries[0] += 1
        if _tries[0] < 3:
            raise PermissionError("busy")
        return _orig_rep(a, b)
    _rt = vault()
    try:
        os.replace = _flaky_rep_ip
        IP.write_atomic(_rt / "f.bin", b"abc", retries=4, sleeper=lambda _: None)
    finally:
        os.replace = _orig_rep
    ok("T17b-write-atomic-retries-permission-error",
       _tries[0] == 3 and (_rt / "f.bin").read_bytes() == b"abc" and not list(_rt.glob(".install-*")))

    def cli(*a, root=None):
        return subprocess.run([sys.executable, str(HERE / "install_plugins.py"), *a], capture_output=True, text=True, encoding="utf-8", errors="replace", env=dict(os.environ, VAULT=str(root or v)), timeout=60)
    ok("T18-cli-check-exit-codes", cli("--check", "--lock", str(p), root=v5).returncode == 1 and cli("--check", "--lock", str(p), root=v).returncode == 0, cli("--check", "--lock", str(p), root=v).stdout[-120:])
    ok("T19-cli-help-rc0-unknown-flag-rc2-broken-lock-rc2", cli("--help").returncode == 0 and cli("--bogus").returncode == 2 and cli("--lock", str(v / "nope.json")).returncode == 2)
finally:
    for d in tmps:
        shutil.rmtree(d, ignore_errors=True)

failed = [r for r in R if not r[1]]
for name, passed, got in R:
    print(("PASS " if passed else "FAIL ") + name + ("" if passed else f" -> {got}"))
print(f"INSTALL-PLUGINS-TESTS {len(R) - len(failed)}/{len(R)}")
sys.exit(1 if failed else 0)
