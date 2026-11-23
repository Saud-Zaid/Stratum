#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Tests of jev_client's server launch: the key reaches the server's environment, the server runs with the locked
interpreter when it has mcp and httpx, and the server is found in the documented order. No network, no mcp needed.
Run: AI-Agent/vault-python AI-Agent/scripts/jev_client-tests.py"""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import jev_client as J  # noqa: E402

results = []


def ok(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f" :: {detail}"))


saved = {k: os.environ.get(k) for k in ("OPENROUTER_API_KEY", "JEV_MODEL", "JEV_TIMEOUT", "JEV_MCP_PATH", "JEV_CONFIG")}
try:
    for k in saved:
        os.environ.pop(k, None)
    base = {"PATH": "/usr/bin", "HOME": "/home/x"}

    os.environ["OPENROUTER_API_KEY"] = "test-key-not-real"
    env = J.server_env(base)
    ok("C01-the-exported-key-reaches-the-server-environment", env.get("OPENROUTER_API_KEY") == "test-key-not-real", env)
    ok("C02-the-safe-default-environment-is-kept", env["PATH"] == "/usr/bin" and env["HOME"] == "/home/x", env)
    ok("C03-the-base-mapping-is-not-mutated", "OPENROUTER_API_KEY" not in base, base)

    os.environ["JEV_MODEL"] = "typesafe/jev-test"
    ok("C04-JEV_MODEL-is-passed-when-set", J.server_env(base).get("JEV_MODEL") == "typesafe/jev-test")
    os.environ.pop("JEV_MODEL")
    ok("C05-an-unset-variable-is-not-passed", "JEV_MODEL" not in J.server_env(base))
    os.environ.pop("OPENROUTER_API_KEY")
    ok("C06-no-key-set-means-no-key-passed", "OPENROUTER_API_KEY" not in J.server_env(base))

    server = HERE / "jev_mcp.py"
    real_find = importlib.util.find_spec
    try:
        importlib.util.find_spec = lambda name, *a, **kw: object()
        cmd, args = J.server_command(server)
        ok("C07-with-mcp-and-httpx-the-server-runs-on-this-interpreter", cmd == sys.executable and args == [str(server)], (cmd, args))
        importlib.util.find_spec = lambda name, *a, **kw: None if name == "httpx" else object()
        cmd, args = J.server_command(server)
        ok("C08-without-httpx-the-server-runs-through-uv", cmd == "uv" and args[-1] == str(server) and "mcp<2" in args, (cmd, args))
    finally:
        importlib.util.find_spec = real_find

    ok("C09-the-shipped-server-sits-next-to-the-client", server.is_file())
    ok("C10-without-JEV_MCP_PATH-the-sibling-server-is-used", J.resolve_server_path() == server, J.resolve_server_path())
    with tempfile.TemporaryDirectory() as d:
        cfg_server = Path(d) / "cfg_server.py"
        cfg_server.write_text("# stand-in\n", encoding="utf-8")
        cfg = Path(d) / "c.yaml"
        cfg.write_text(f"extensions:\n  jev:\n    name: Jev\n    args: [run, {cfg_server}]\n", encoding="utf-8")
        os.environ["JEV_CONFIG"] = str(cfg)
        ok("C13-an-explicit-JEV_CONFIG-wins-over-the-sibling", J.resolve_server_path() == cfg_server, J.resolve_server_path())
        os.environ.pop("JEV_CONFIG")
        other = Path(d) / "other_server.py"
        other.write_text("# stand-in\n", encoding="utf-8")
        os.environ["JEV_MCP_PATH"] = str(other)
        ok("C11-JEV_MCP_PATH-wins-over-the-sibling", J.resolve_server_path() == other, J.resolve_server_path())
        os.environ["JEV_MCP_PATH"] = str(Path(d) / "missing.py")
        try:
            J.resolve_server_path()
            ok("C12-a-JEV_MCP_PATH-to-a-missing-file-fails-loudly", False, "no exit")
        except SystemExit as e:
            ok("C12-a-JEV_MCP_PATH-to-a-missing-file-fails-loudly", "file missing" in str(e.code), e.code)
finally:
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

print(f"JEV-CLIENT-TESTS {sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
