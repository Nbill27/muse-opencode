# muse-local launcher — cookie/session based, loopback only, no API key.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$env:PYTHONPATH = Join-Path $PSScriptRoot "src"
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "venv missing. creating..."
    python -m venv .venv
    & $py -m pip install -q --upgrade pip
    & $py -m pip install -q fastapi "uvicorn[standard]" pydantic pydantic-settings "httpx[socks]" websockets
}

if (-not (Test-Path (Join-Path $PSScriptRoot "session.json"))) {
    Write-Warning "session.json not found — /v1/chat/completions will return 503 until it exists."
}

# free the port from a stale run
Get-NetTCPConnection -LocalPort 20233 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }

Write-Host "muse-local -> http://127.0.0.1:20233/v1  (model: muse-chat)"
& $py -m museai
