#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Tests of the Jev decision server (jev_mcp.py) with stand-ins for mcp and httpx, so they run without either library
and without network: the key comes from the environment, the request carries the pinned model and the Bearer key, an
incomplete gate is refused, and the gate fingerprint is stable.
Run: AI-Agent/vault-python AI-Agent/scripts/jev_mcp-tests.py"""
import importlib
import os
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

calls = []


class _FastMCP:
    def __init__(self, name):
        self.name = name

    def tool(self):
        return lambda fn: fn

    def run(self):
        pass


class _Response:
    status_code = 200
    text = ""

    def json(self):
        return {"model": "typesafe/jev-1.14-test", "answers": {"q": {"type": "choice", "choice": "a"}},
                "usage": {"cost": 0.00001, "input_tokens": 10, "output_tokens": 2}}


def _post(url, headers=None, json=None, timeout=None):
    calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
    return _Response()


fastmcp = types.ModuleType("mcp.server.fastmcp")
fastmcp.FastMCP = _FastMCP
sys.modules.update({"mcp": types.ModuleType("mcp"), "mcp.server": types.ModuleType("mcp.server"),
                    "mcp.server.fastmcp": fastmcp, "httpx": types.SimpleNamespace(post=_post)})

results = []


def ok(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f" :: {detail}"))


saved = {k: os.environ.get(k) for k in ("OPENROUTER_API_KEY", "JEV_MODEL", "HOME")}
home = tempfile.mkdtemp(prefix="jevhome-")
try:
    os.environ.pop("JEV_MODEL", None)
    os.environ["HOME"] = home                       # no agent config here: the key can only come from the environment
    os.environ["OPENROUTER_API_KEY"] = "test-key-not-real"
    S = importlib.import_module("jev_mcp")

    ok("S01-the-key-is-read-from-the-environment", S._load_key() == "test-key-not-real")
    ok("S02-the-pinned-model-is-typesafe-jev-1-14", S.MODEL == "typesafe/jev-1.14", S.MODEL)

    ev = {"cycle_note": "c", "recorded_state": "r", "paths_or_numbers": ["a", "b", "c"]}
    out = S.jev_gate("DR-1", "gate-x", "Pick one?", {"a": "when a", "b": "when b"}, ev)
    req = calls[-1]
    ok("S03-the-request-goes-to-the-decisions-endpoint", req["url"] == "https://openrouter.ai/api/alpha/decisions", req["url"])
    ok("S04-the-request-carries-the-bearer-key", req["headers"]["Authorization"] == "Bearer test-key-not-real")
    ok("S05-the-request-carries-the-pinned-model", req["json"]["model"] == "typesafe/jev-1.14", req["json"]["model"])
    ok("S06-the-state-is-sent-as-a-structured-dict", isinstance(req["json"]["state"], dict) and req["json"]["state"]["gate"] == "gate-x")
    h = out["state_hash"]
    ok("S07-the-gate-fingerprint-is-16-hex", len(h) == 16 and all(c in "0123456789abcdef" for c in h), h)
    again = S.jev_gate("DR-1", "gate-x", "Another wording?", {"a": "x"}, dict(reversed(list(ev.items()))))
    ok("S08-the-fingerprint-depends-on-the-evidence-not-the-wording-or-key-order", again["state_hash"] == h, again["state_hash"])

    for missing in ("cycle_note", "recorded_state", "paths_or_numbers"):
        bad = {k: v for k, v in ev.items() if k != missing}
        try:
            S.jev_gate("DR-1", "gate-x", "Q?", {"a": "x"}, bad)
            ok(f"S09-a-gate-without-{missing}-is-refused", False, "accepted")
        except ValueError:
            ok(f"S09-a-gate-without-{missing}-is-refused", True)

    os.environ.pop("OPENROUTER_API_KEY")
    try:
        S.jev_check("x is 3", "Is x above 2?", "yes", "no")
        ok("S10-no-key-anywhere-fails-loudly", False, "no error")
    except RuntimeError as e:
        ok("S10-no-key-anywhere-fails-loudly", "OPENROUTER_API_KEY" in str(e), e)
finally:
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

print(f"JEV-MCP-TESTS {sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
