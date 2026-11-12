# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""enable_mcp.py — switch on the MCP connector (mcp-tools-istefox) for this vault, only when you ask for it.

Usage: python AI-Agent/scripts/enable_mcp.py [--status] [--rotate] [--disable] [--dry-run] [--port N]

The connector ships disabled. Enabling it does three things, each written atomically:
  1. adds a random 32-byte token (CSPRNG, URL-safe) to the plugin's settings, `.obsidian/plugins/mcp-tools-istefox/data.json`
     (`mcpTransport.tokens` and `bearerToken`), and sets `mcpClientConfig.autoWriteClaudeDesktopConfig` to false so the plugin never
     edits `claude_desktop_config.json` behind your back;
  2. writes `.mcp.json` next to the vault (a streamable-http server at 127.0.0.1:<port>/mcp with that token; mode 0600; git-ignored);
  3. lists the plugin in `.obsidian/community-plugins.json`.
The port is the one the plugin last bound (`mcpTransport.livePort`), else its default 27200; `--port` overrides both. A token is never
printed, only its short id. Running again changes nothing unless `--rotate` is given (a new token replaces the old ones).
`--disable` removes the plugin from the enabled list and the token from `.mcp.json`; the plugin's own settings are kept.
The plugin must be installed first (`install_plugins.py`). Standard library only.
Exit code: 0 done or already in that state, 1 the plugin is not installed or a file is unreadable, 2 bad arguments.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path

PLUGIN_ID = "mcp-tools-istefox"
DEFAULT_PORT = 27200
HOST = "127.0.0.1"
SERVER_NAME = "obsidian"
DATA_REL = f".obsidian/plugins/{PLUGIN_ID}/data.json"
MANIFEST_REL = f".obsidian/plugins/{PLUGIN_ID}/manifest.json"
ENABLED_REL = ".obsidian/community-plugins.json"
MCP_REL = ".mcp.json"
IGNORE_LINE = MCP_REL


class McpError(Exception):
    """Something that stops the change before any file is written."""


def write_atomic(dest: Path, text: str, mode: int | None = None) -> None:
    """Write through a temp file in the same folder and rename it over the target, so a crash leaves the old file whole."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=dest.name + ".", dir=dest.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        if mode is not None and os.name != "nt":
            os.chmod(tmp, mode)
        os.replace(tmp, dest)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_json(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise McpError(f"{path.name} is not readable JSON: {e.__class__.__name__}") from e


def dump(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def new_token() -> dict:
    value = secrets.token_urlsafe(32)
    return {"id": secrets.token_hex(4)[:7], "label": "stratum", "token": value, "createdAt": int(time.time() * 1000)}


def current_token(data: dict) -> dict | None:
    mt = data.get("mcpTransport") or {}
    bearer = mt.get("bearerToken")
    for t in mt.get("tokens") or []:
        if isinstance(t, dict) and t.get("token") == bearer and bearer:
            return t
    return None


def plan(root: Path, rotate: bool, port: int | None) -> dict:
    """Everything that would be written, computed first so a failure writes nothing."""
    if not (root / MANIFEST_REL).is_file():
        raise McpError(f"the plugin is not installed ({MANIFEST_REL} is missing): run install_plugins.py first")
    data = read_json(root / DATA_REL, {})
    if not isinstance(data, dict):
        raise McpError("the plugin settings are not a JSON object")
    enabled = read_json(root / ENABLED_REL, [])
    if not isinstance(enabled, list):
        raise McpError("community-plugins.json is not a list")
    tok = current_token(data)
    mcp = read_json(root / MCP_REL, {})
    has_cfg = isinstance(mcp, dict) and SERVER_NAME in (mcp.get("mcpServers") or {})
    live = (data.get("mcpTransport") or {}).get("livePort")
    use_port = port or (live if isinstance(live, int) and not isinstance(live, bool) and 1024 <= live <= 65535 else DEFAULT_PORT)
    fresh = rotate or tok is None
    if fresh:
        tok = new_token()
        mt = data.setdefault("mcpTransport", {})
        mt["tokens"] = [tok] if rotate else [*[t for t in (mt.get("tokens") or []) if isinstance(t, dict)], tok]
        mt["bearerToken"] = tok["token"]
    data.setdefault("mcpClientConfig", {})["autoWriteClaudeDesktopConfig"] = False
    if not isinstance(mcp, dict):
        mcp = {}
    servers = mcp.setdefault("mcpServers", {})
    servers[SERVER_NAME] = {"type": "streamable-http", "url": f"http://{HOST}:{use_port}/mcp", "headers": {"Authorization": f"Bearer {tok['token']}"}}
    new_enabled = enabled if PLUGIN_ID in enabled else [*enabled, PLUGIN_ID]
    return {"data": data, "mcp": mcp, "enabled": new_enabled, "token_id": tok["id"], "port": use_port, "fresh": fresh,
            "changed": fresh or not has_cfg or new_enabled != enabled or (read_json(root / MCP_REL, {}).get("mcpServers", {}).get(SERVER_NAME) != servers[SERVER_NAME])}


def ensure_ignored(root: Path) -> bool:
    gi = root / ".gitignore"
    text = gi.read_text(encoding="utf-8") if gi.is_file() else ""
    if IGNORE_LINE in (ln.strip() for ln in text.splitlines()):
        return False
    write_atomic(gi, text + ("" if not text or text.endswith("\n") else "\n") + IGNORE_LINE + "\n")
    return True


def enable(root: Path, rotate=False, port=None, dry_run=False, out=print) -> int:
    p = plan(root, rotate, port)
    if not p["changed"]:
        out(f"already enabled: token {p['token_id']}, http://{HOST}:{p['port']}/mcp (use --rotate for a new token)")
        return 0
    if dry_run:
        out(f"would enable: {'a new' if p['fresh'] else 'the existing'} token {p['token_id']}, http://{HOST}:{p['port']}/mcp; nothing written")
        return 0
    ensure_ignored(root)                                   # first, so a token never sits in the file before git ignores it
    write_atomic(root / MCP_REL, dump(p["mcp"]), 0o600)
    write_atomic(root / DATA_REL, dump(p["data"]), 0o600)
    write_atomic(root / ENABLED_REL, dump(p["enabled"]))
    out(f"enabled: token {p['token_id']}, http://{HOST}:{p['port']}/mcp; .mcp.json written (mode 0600, git-ignored). Reload Obsidian to start the server.")
    return 0


def disable(root: Path, dry_run=False, out=print) -> int:
    enabled = read_json(root / ENABLED_REL, [])
    mcp = read_json(root / MCP_REL, {})
    if not isinstance(enabled, list) or not isinstance(mcp, dict):
        raise McpError("community-plugins.json or .mcp.json has an unexpected shape")
    servers = mcp.get("mcpServers") or {}
    if PLUGIN_ID not in enabled and SERVER_NAME not in servers:
        out("already disabled")
        return 0
    if dry_run:
        out("would disable: plugin removed from the enabled list, server removed from .mcp.json; nothing written")
        return 0
    servers.pop(SERVER_NAME, None)
    if servers:
        mcp["mcpServers"] = servers
        write_atomic(root / MCP_REL, dump(mcp), 0o600)
    elif (root / MCP_REL).exists():
        (root / MCP_REL).unlink()
    write_atomic(root / ENABLED_REL, dump([x for x in enabled if x != PLUGIN_ID]))
    out("disabled: the plugin settings (and its tokens) are kept; reload Obsidian.")
    return 0


def status(root: Path, out=print) -> int:
    enabled = read_json(root / ENABLED_REL, [])
    data = read_json(root / DATA_REL, {})
    mcp = read_json(root / MCP_REL, {})
    tok = current_token(data) if isinstance(data, dict) else None
    out(f"installed: {(root / MANIFEST_REL).is_file()}  enabled: {PLUGIN_ID in enabled}  token: {tok['id'] if tok else 'none'}  "
        f".mcp.json: {SERVER_NAME in ((mcp or {}).get('mcpServers') or {})}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="enable_mcp", description=__doc__.strip().splitlines()[0], epilog=__doc__.strip(), formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--status", action="store_true")
    g.add_argument("--disable", action="store_true")
    ap.add_argument("--rotate", action="store_true", help="replace the token with a new one")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args(argv)
    if args.port is not None and not 1024 <= args.port <= 65535:
        print("enable_mcp: --port must be 1024-65535", file=sys.stderr)
        return 2
    root = Path(os.environ.get("VAULT") or Path(__file__).resolve().parents[2])
    try:
        if args.status:
            return status(root)
        if args.disable:
            return disable(root, args.dry_run)
        return enable(root, args.rotate, args.port, args.dry_run)
    except (McpError, OSError) as e:
        print(f"enable_mcp: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
