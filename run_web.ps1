# Starts the UPBI website (Next.js) on http://localhost:<Port>. First run installs the packages and builds the site (about 2 minutes).
#   powershell -ExecutionPolicy Bypass -File .\run_web.ps1                      (website 3000, API 8000)
#   powershell -ExecutionPolicy Bypass -File .\run_web.ps1 -Port 3001 -ApiPort 8001
param([int]$Port = 3000, [int]$ApiPort = 8000)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Error "Node.js was not found. Install the LTS version (20 or newer) from https://nodejs.org/, open a NEW PowerShell window, then run this again."
}
Set-Location (Join-Path $root "web")
if (-not (Test-Path "node_modules")) { npm ci --no-audit --no-fund; if ($LASTEXITCODE -ne 0) { throw "npm ci failed" } }
if (-not (Test-Path ".next")) { npm run build; if ($LASTEXITCODE -ne 0) { throw "npm run build failed" } }

$env:UPBI_API_BASE = "http://127.0.0.1:$ApiPort"
$env:NEXT_TELEMETRY_DISABLED = "1"
Write-Host ""
Write-Host "Website starting. Open: http://localhost:$Port   (the API must be running on port $ApiPort)"
Write-Host "Leave this window open. Press Ctrl+C to stop."
npx next start -H 127.0.0.1 -p $Port
