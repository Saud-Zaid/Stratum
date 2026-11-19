#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""cli_contract-tests.py — the shared CLI contract of the vault tools (T-02e, U-47/U-48, first slice).

For every tool in CLI_TOOLS: `-h`/`--help` exits 0, prints to stdout only and touches nothing; an unknown flag exits 2
with the message on stderr and nothing on stdout. Also checks that each `stratum-*` console script in pyproject.toml
points at a real function in src/stratum_cli/main.py and a real script, and that find_vault resolves a vault.
T-05 extends this to docs, skills and release_manifest.json against --help for all 33 release tools.
Tools run through sys.executable (never through the bash wrapper) with the caller's environment.
Usage: cli_contract-tests"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
VAULT = HERE.parent.parent

# tools that already satisfy the contract; grows as each tool is converted (T-03/T-05 cover the rest of the 33)
CLI_TOOLS = ["audit", "state", "section", "outline", "tool_gate", "entry_map", "restore_ready", "consumer_suites"]

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


def run(script, *args):
    return subprocess.run([sys.executable, str(HERE / f"{script}.py"), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=dict(os.environ, VAULT=str(VAULT)), cwd=tempfile.gettempdir(), timeout=120)


def snapshot():
    r = subprocess.run(["git", "-C", str(VAULT), "status", "--porcelain", "--", ".", ":(exclude)AI-Agent/state"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout


before = snapshot()
for tool in CLI_TOOLS:
    h = run(tool, "--help")
    ok(f"{tool}: --help exits 0 on stdout only", h.returncode == 0 and h.stdout.strip() and not h.stderr.strip(), (h.returncode, h.stderr[:80]))
    s = run(tool, "-h")
    ok(f"{tool}: -h equals --help", s.returncode == 0 and s.stdout == h.stdout)
    b = run(tool, "--no-such-flag-zz")
    ok(f"{tool}: unknown flag exits 2, stderr only", b.returncode == 2 and b.stderr.strip() and not b.stdout.strip(), (b.returncode, b.stdout[:60]))
ok("help and bad flags changed nothing in the working tree", snapshot() == before)

# console scripts <-> main.py functions <-> script files
proj = tomllib.loads((VAULT / "pyproject.toml").read_text(encoding="utf-8"))
scripts = proj["project"]["scripts"]
ok("pyproject declares 7 stratum-* commands", len(scripts) == 7 and all(k.startswith("stratum-") for k in scripts), list(scripts))
tree = ast.parse((VAULT / "src" / "stratum_cli" / "main.py").read_text(encoding="utf-8"))
funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
for cmd, target in scripts.items():
    mod, _, fn = target.partition(":")
    ok(f"{cmd}: target function exists", mod == "stratum_cli.main" and fn in funcs, target)
    src = ast.get_source_segment((VAULT / "src" / "stratum_cli" / "main.py").read_text(encoding="utf-8"), funcs[fn]) if fn in funcs else ""
    named = [t for t in (n.value for n in ast.walk(funcs[fn]) if isinstance(n, ast.Constant) and isinstance(n.value, str)) if t.endswith(".py")] if fn in funcs else []
    ok(f"{cmd}: runs an existing AI-Agent/scripts file", len(named) == 1 and (HERE / named[0]).is_file(), named)

import importlib.util  # noqa: E402  (loaded by path: src/stratum_cli is not part of the audited import graph, ADR-006)

_spec = importlib.util.spec_from_file_location("stratum_cli_main", VAULT / "src" / "stratum_cli" / "main.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

ok("find_vault honours $VAULT", (lambda: (os.environ.__setitem__("VAULT", "/x/y"), M.find_vault())[1])() == Path("/x/y"))
os.environ.pop("VAULT", None)
ok("find_vault walks up to the vault", M.find_vault(HERE) == VAULT, M.find_vault(HERE))
try:
    M.find_vault(Path(tempfile.gettempdir()))
    raised = False
except SystemExit as e:
    raised = "no vault found" in str(e)
ok("find_vault outside a vault exits with a message", raised)

# --- operational tools generalized in T-02e (jev_client, g03_session): contract + config resolution ---
for _tool in ("archprint", "g04_search", "fx02_session_tax", "fx05_task_key", "vault_diagram", "run_tests", "install_plugins", "upgrade_core", "restore_pre_upgrade", "export_release"):
    _f = [sys.executable, str(HERE / f"{_tool}.py")]
    _h = subprocess.run(_f + ["--help"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    _b = subprocess.run(_f + ["--bogus"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    ok(f"{_tool} --help rc0 / unknown flag rc2", _h.returncode == 0 and "usage" in _h.stdout.lower() and _b.returncode == 2, (_h.returncode, _b.returncode))
for _tool in ("jev_client", "g03_session"):
    _f = [sys.executable, str(HERE / f"{_tool}.py")]
    _h = subprocess.run(_f + ["--help"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    ok(f"{_tool} --help rc0 with usage", _h.returncode == 0 and "usage" in _h.stdout.lower(), (_h.returncode, _h.stderr[-200:]))
_jc = HERE / "jev_client.py"
_cfgdir = Path(tempfile.mkdtemp())
_env = {k: v for k, v in os.environ.items() if k not in ("JEV_MCP_PATH", "JEV_CONFIG", "XDG_CONFIG_HOME", "OPENROUTER_API_KEY")}
_r = subprocess.run([sys.executable, str(_jc), "jev_check", "{}"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                    env={**_env, "XDG_CONFIG_HOME": str(_cfgdir)})
ok("jev_client without server path fails loudly naming the config it looked at",
   _r.returncode != 0 and str(_cfgdir / "goose" / "config.yaml") in _r.stderr, (_r.returncode, _r.stderr[-300:]))
_r = subprocess.run([sys.executable, str(_jc), "jev_check", "{}"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                    env={**_env, "JEV_MCP_PATH": str(_cfgdir / "nope.py")})
ok("jev_client JEV_MCP_PATH to a missing file fails loudly", _r.returncode != 0 and "file missing" in _r.stderr, _r.stderr[-300:])
_srv = _cfgdir / "srv.py"
_srv.write_text("", encoding="utf-8")
_cfg = _cfgdir / "c.yaml"
_cfg.write_text(f"extensions:\n  j:\n    name: Jev\n    args: ['{_srv}']\n", encoding="utf-8")
_code = (f"import sys; sys.path.insert(0, {str(HERE)!r}); import jev_client as J; "
         f"print(J.config_path()); print(J.resolve_server_path())")
_r = subprocess.run([sys.executable, "-c", _code], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, env={**_env, "JEV_CONFIG": str(_cfg)})
ok("jev_client JEV_CONFIG overrides the config location and resolves the server",
   _r.returncode == 0 and _r.stdout.split("\n")[:2] == [str(_cfg), str(_srv)], (_r.returncode, _r.stdout, _r.stderr[-200:]))
_code = f"import sys; sys.path.insert(0, {str(HERE)!r}); import jev_client as J; J.load_api_key()"
_r = subprocess.run([sys.executable, "-c", _code], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                    env={**_env, "JEV_CONFIG": str(_cfgdir / "absent.yaml")})
ok("jev_client load_api_key with no config exits cleanly (no traceback)",
   _r.returncode != 0 and "Traceback" not in _r.stderr and "missing" in _r.stderr, _r.stderr[-300:])

failed = [r for r in R if not r[1]]
for name, passed, got in R:
    print(("PASS " if passed else "FAIL ") + name + ("" if passed else f" -> {got}"))
print(f"CLI-CONTRACT-TESTS {len(R) - len(failed)}/{len(R)}")
sys.exit(1 if failed else 0)
