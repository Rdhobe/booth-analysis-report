# Starts the UPBI API (FastAPI) on http://127.0.0.1:<Port>. First run creates a Python environment and installs the packages.
#   powershell -ExecutionPolicy Bypass -File .\run_api.ps1            (default port 8000)
#   powershell -ExecutionPolicy Bypass -File .\run_api.ps1 -Port 8001
param([int]$Port = 8000)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venvPython = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Error "Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this again."
    }
    Write-Host "First run: creating the Python environment (about a minute)..."
    python -m venv (Join-Path $root ".venv")
}
& $venvPython -m pip install --quiet --disable-pip-version-check -r (Join-Path $root "server\requirements.txt")

Set-Location (Join-Path $root "server")
Write-Host ""
Write-Host "API starting. Check it at: http://127.0.0.1:$Port/api/insights/meta"
Write-Host "Leave this window open. Press Ctrl+C to stop."
& $venvPython -m uvicorn app:app --host 127.0.0.1 --port $Port
