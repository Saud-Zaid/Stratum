#!/usr/bin/env sh
# setup.sh - install the pinned runtime into .venv from uv.lock, then stamp the lock hash.
set -eu
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "setup: uv is required (https://docs.astral.sh/uv/getting-started/installation/)" >&2
  exit 1
fi

uv sync --locked --no-dev

# .venv/.stratum-lock-sha256 lets vault-python and state.py notice a lock that moved after setup (U-49).
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum uv.lock | cut -d' ' -f1 > .venv/.stratum-lock-sha256
else
  shasum -a 256 uv.lock | cut -d' ' -f1 > .venv/.stratum-lock-sha256
fi

# Fetch the tokenizer vocabulary once, hash-checked and time-bounded; offline runs fall back to estimates.
PYTHONPATH="AI-Agent/scripts" .venv/bin/python -c "from _vaultlib import ensure_o200k_cache; print('tokenizer vocabulary:', 'ready' if ensure_o200k_cache() else 'unavailable (offline?)')" || true

if [ -d .git ] && [ -d .githooks ]; then
  git config core.hooksPath .githooks
fi
echo "setup: done. Run: AI-Agent/vault-python AI-Agent/scripts/state.py"
