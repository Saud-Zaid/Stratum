# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Tests for enable_mcp.py against a throwaway vault: nothing touches the real one."""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import enable_mcp as M

HERE = Path(__file__).resolve().parent
R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


tmps = []


def vault(installed=True, data=None, enabled=("dataview",)):
    d = Path(tempfile.mkdtemp(prefix="mcp-"))
    tmps.append(d)
    (d / ".obsidian/plugins" / M.PLUGIN_ID).mkdir(parents=True)
    if installed:
        (d / M.MANIFEST_REL).write_text("{}", encoding="utf-8")
    if data is not None:
        (d / M.DATA_REL).write_text(json.dumps(data), encoding="utf-8")
    (d / M.ENABLED_REL).write_text(json.dumps(list(enabled)), encoding="utf-8")
    return d


def cli(root, *a):
    return subprocess.run([sys.executable, str(HERE / "enable_mcp.py"), *a], capture_output=True, text=True, env=dict(os.environ, VAULT=str(root)), timeout=60)


try:
    v = vault()
    out = []
    ok("M01-enable-returns-0", M.enable(v, out=out.append) == 0, out)
    data = json.loads((v / M.DATA_REL).read_text(encoding="utf-8"))
    tok = data["mcpTransport"]["bearerToken"]
    ok("M02-token-is-43-url-safe-chars-from-32-bytes", len(tok) == 43 and all(c.isalnum() or c in "-_" for c in tok), len(tok))
    ok("M03-token-listed-with-id-label-and-time", data["mcpTransport"]["tokens"][0]["token"] == tok and len(data["mcpTransport"]["tokens"][0]["id"]) == 7 and isinstance(data["mcpTransport"]["tokens"][0]["createdAt"], int))
    ok("M04-plugin-never-writes-the-claude-desktop-config", data["mcpClientConfig"]["autoWriteClaudeDesktopConfig"] is False)
    mcp = json.loads((v / M.MCP_REL).read_text(encoding="utf-8"))
    srv = mcp["mcpServers"]["obsidian"]
    ok("M05-mcp-json-is-streamable-http-on-localhost-with-the-bearer", srv["type"] == "streamable-http" and srv["url"] == "http://127.0.0.1:27200/mcp" and srv["headers"]["Authorization"] == f"Bearer {tok}", srv["url"])
    if os.name != "nt":
        ok("M06-secret-files-are-0600", stat.S_IMODE((v / M.MCP_REL).stat().st_mode) == 0o600 and stat.S_IMODE((v / M.DATA_REL).stat().st_mode) == 0o600)
    ok("M07-plugin-enabled-once-and-others-kept", json.loads((v / M.ENABLED_REL).read_text(encoding="utf-8")) == ["dataview", M.PLUGIN_ID])
    ok("M08-mcp-json-is-gitignored", ".mcp.json" in (v / ".gitignore").read_text(encoding="utf-8").splitlines())
    ok("M09-the-token-is-never-printed", tok not in " ".join(out), out)
    before = (v / M.MCP_REL).read_bytes()
    out2 = []
    ok("M10-second-run-changes-nothing", M.enable(v, out=out2.append) == 0 and (v / M.MCP_REL).read_bytes() == before and "already enabled" in out2[0], out2)
    out3 = []
    M.enable(v, rotate=True, out=out3.append)
    d3 = json.loads((v / M.DATA_REL).read_text(encoding="utf-8"))
    ok("M11-rotate-replaces-the-token-everywhere", d3["mcpTransport"]["bearerToken"] != tok and len(d3["mcpTransport"]["tokens"]) == 1
       and d3["mcpTransport"]["bearerToken"] in (v / M.MCP_REL).read_text(encoding="utf-8") and tok not in (v / M.MCP_REL).read_text(encoding="utf-8"))
    n = vault(data={"toolLoading": {"profile": "adaptive"}, "mcpTransport": {"livePort": 27202, "tokens": [{"id": "old0000", "label": "x", "token": "T" * 43, "createdAt": 1}], "bearerToken": "T" * 43}})
    M.enable(n, out=lambda s: None)
    dn = json.loads((n / M.DATA_REL).read_text(encoding="utf-8"))
    ok("M12-existing-settings-and-tokens-are-kept-and-livePort-is-used", dn["toolLoading"] == {"profile": "adaptive"} and dn["mcpTransport"]["bearerToken"] == "T" * 43
       and len(dn["mcpTransport"]["tokens"]) == 1 and json.loads((n / M.MCP_REL).read_text(encoding="utf-8"))["mcpServers"]["obsidian"]["url"].endswith(":27202/mcp"))
    p = vault()
    M.enable(p, port=27300, out=lambda s: None)
    ok("M13-port-flag-wins", json.loads((p / M.MCP_REL).read_text(encoding="utf-8"))["mcpServers"]["obsidian"]["url"].endswith(":27300/mcp"))
    u = vault(installed=False)
    r = cli(u)
    ok("M14-not-installed-rc1-and-nothing-written", r.returncode == 1 and "install_plugins" in r.stderr and not (u / M.MCP_REL).exists() and not (u / ".gitignore").exists(), r.stderr)
    b = vault()
    (b / M.DATA_REL).write_text("{not json", encoding="utf-8")
    ok("M15-unreadable-settings-rc1-and-no-token-file", cli(b).returncode == 1 and not (b / M.MCP_REL).exists())
    dr = vault()
    cli(dr, "--dry-run")
    ok("M16-dry-run-writes-nothing", not (dr / M.MCP_REL).exists() and json.loads((dr / M.ENABLED_REL).read_text(encoding="utf-8")) == ["dataview"])
    out4 = []
    M.disable(v, out=out4.append)
    ok("M17-disable-removes-the-server-and-the-plugin-but-keeps-settings", not (v / M.MCP_REL).exists() and M.PLUGIN_ID not in json.loads((v / M.ENABLED_REL).read_text(encoding="utf-8"))
       and (v / M.DATA_REL).is_file(), out4)
    out5 = []
    M.disable(v, out=out5.append)
    ok("M18-disable-twice-is-fine", out5 == ["already disabled"])
    e = vault()
    (e / M.MCP_REL).write_text(json.dumps({"mcpServers": {"other": {"url": "x"}}}), encoding="utf-8")
    M.enable(e, out=lambda s: None)
    M.disable(e, out=lambda s: None)
    ok("M19-other-servers-in-mcp-json-survive-enable-and-disable", json.loads((e / M.MCP_REL).read_text(encoding="utf-8"))["mcpServers"] == {"other": {"url": "x"}})
    ok("M20-help-rc0-unknown-flag-rc2-bad-port-rc2", cli(v, "--help").returncode == 0 and cli(v, "--bogus").returncode == 2 and cli(v, "--port", "80").returncode == 2)
    ok("M21-status-reports-without-secrets", (lambda r: r.returncode == 0 and "enabled" in r.stdout and tok not in r.stdout)(cli(e, "--status")))
finally:
    for t in tmps:
        shutil.rmtree(t, ignore_errors=True)

failed = [r for r in R if not r[1]]
for name, passed, got in R:
    print(("PASS " if passed else "FAIL ") + name + ("" if passed else f" -> {got}"))
print(f"ENABLE-MCP-TESTS {len(R) - len(failed)}/{len(R)}")
sys.exit(1 if failed else 0)
