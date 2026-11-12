# vault-python.ps1 - Windows twin of vault-python: resolves VAULT, the interpreter and the tokenizer cache, then runs the script.
# Usage: AI-Agent\vault-python.ps1 AI-Agent\scripts\state.py [args]    |    AI-Agent\vault-python.ps1 --env
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $PSCommandPath
if (-not $env:VAULT) { $env:VAULT = (Resolve-Path (Join-Path $here "..")).Path }

if (-not $env:TIKTOKEN_CACHE_DIR) {
    $base = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME ".cache" }
    $env:TIKTOKEN_CACHE_DIR = Join-Path $base "tiktoken"
}

$venvPy = Join-Path $env:VAULT ".venv\Scripts\python.exe"
if ($env:VAULT_PYTHON) { $py = $env:VAULT_PYTHON }
elseif (Test-Path -LiteralPath $venvPy) { $py = $venvPy }
elseif (Get-Command py -ErrorAction SilentlyContinue) { $py = "py" ; $pyArgs = @("-3.13") }
else { $py = "python" }

# Lock stamp: only when the vault's own .venv is the interpreter; a stale stamp warns once and never blocks.
$stamp = Join-Path $env:VAULT ".venv\.stratum-lock-sha256"
$lock = Join-Path $env:VAULT "uv.lock"
if (($py -eq $venvPy) -and (Test-Path -LiteralPath $stamp) -and (Test-Path -LiteralPath $lock)) {
    $want = (Get-FileHash -Algorithm SHA256 -LiteralPath $lock).Hash.ToLower()
    $have = (Get-Content -LiteralPath $stamp -Raw).Trim()
    if ($want -ne $have) { [Console]::Error.WriteLine("vault-python: .venv is older than uv.lock - run setup.cmd to refresh it.") }
}

if ($args.Count -gt 0 -and $args[0] -eq "--env") {
    Write-Output "python=$py"
    Write-Output "VAULT=$env:VAULT"
    Write-Output "TIKTOKEN_CACHE_DIR=$env:TIKTOKEN_CACHE_DIR"
    exit 0
}

& $py @pyArgs @args
exit $LASTEXITCODE
