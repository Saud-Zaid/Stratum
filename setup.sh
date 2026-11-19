#!/usr/bin/env sh
# setup.sh - install the pinned runtime into .venv from uv.lock, then stamp the lock hash.
set -eu
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  for d in "$HOME/.local/bin" "$HOME/.cargo/bin" /opt/homebrew/bin /usr/local/bin; do
    if [ -x "$d/uv" ]; then PATH="$d:$PATH"; export PATH; break; fi
  done
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "setup: uv is required (https://docs.astral.sh/uv/getting-started/installation/)" >&2
  exit 1
fi

uv sync --locked --no-dev --no-editable

# .venv/.stratum-lock-sha256 lets vault-python and state.py notice a lock that moved after setup (U-49).
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum uv.lock | cut -d' ' -f1 > .venv/.stratum-lock-sha256
else
  shasum -a 256 uv.lock | cut -d' ' -f1 > .venv/.stratum-lock-sha256
fi

# Fetch the tokenizer vocabulary once, hash-checked and time-bounded; offline runs fall back to estimates.
PYTHONPATH="AI-Agent/scripts" .venv/bin/python -c "from _vaultlib import ensure_o200k_cache; print('tokenizer vocabulary:', 'ready' if ensure_o200k_cache() else 'unavailable (offline?)')" || true

# Smoke test: the installed package imports and the entry point runs.
PYTHONUTF8=1 .venv/bin/python -c "import stratum_cli.main" || { echo "setup: stratum_cli failed to import" >&2; exit 1; }
PYTHONUTF8=1 .venv/bin/stratum-state --help >/dev/null 2>&1 || echo "setup: warning: stratum-state --help did not run" >&2

# -e (not -d): .git is a file in a worktree or submodule.
if [ -e .git ] && [ -d .githooks ]; then
  git config core.hooksPath .githooks
fi
echo "setup: done. Run: AI-Agent/vault-python AI-Agent/scripts/state.py"
