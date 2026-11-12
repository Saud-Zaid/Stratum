# setup.ps1 - install the pinned runtime into .venv from uv.lock, then stamp the lock hash.
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "setup: uv is required (https://docs.astral.sh/uv/getting-started/installation/)"
    exit 1
}

uv sync --locked --no-dev
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# .venv\.stratum-lock-sha256 lets vault-python.ps1 and state.py notice a lock that moved after setup.
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath "uv.lock").Hash.ToLower()
Set-Content -LiteralPath ".venv\.stratum-lock-sha256" -Value $hash -NoNewline -Encoding ascii

# Tokenizer vocabulary: fetched once, hash-checked and time-bounded; offline runs fall back to estimates.
$env:PYTHONPATH = "AI-Agent\scripts"
& ".venv\Scripts\python.exe" -c "from _vaultlib import ensure_o200k_cache; print('tokenizer vocabulary:', 'ready' if ensure_o200k_cache() else 'unavailable (offline?)')"
Remove-Item Env:\PYTHONPATH

if ((Test-Path ".git") -and (Test-Path ".githooks")) { git config core.hooksPath .githooks }
Write-Host "setup: done. Run: AI-Agent\vault-python.ps1 AI-Agent\scripts\state.py"
