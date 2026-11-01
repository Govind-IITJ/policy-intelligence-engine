$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host 'POLICY INTELLIGENCE — FRONTEND STARTUP' -ForegroundColor Cyan

$node = Get-Command node.exe -ErrorAction SilentlyContinue
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $node) { throw 'Node.js is not installed or not on PATH. Install Node.js 20.19+ or 22.12+.' }
if (-not $npm) { throw 'npm.cmd was not found. Reinstall Node.js with npm and reopen PowerShell.' }

Write-Host "Node: $(& node.exe --version)"
Write-Host "npm:  $(& npm.cmd --version)"

if (-not (Test-Path '.\.env.local')) {
    @'
VITE_API_BASE_URL=http://127.0.0.1:8001
VITE_MAX_UPLOAD_MB=20
'@ | Set-Content -Path '.\.env.local' -Encoding UTF8
    Write-Host 'Created .env.local with the local backend URL.' -ForegroundColor Green
}

$backendReady = $false
try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8001/health' -UseBasicParsing -TimeoutSec 3
    if ($health.status -eq 'ok') {
        $backendReady = $true
        Write-Host "Backend connected: $($health.service) v$($health.version)" -ForegroundColor Green
    }
} catch {}
if (-not $backendReady) {
    Write-Warning 'Backend on port 8001 is not responding. The frontend will start, but upload/analysis will not work until the backend is running.'
}

if (-not (Test-Path '.\node_modules\.bin\vite.cmd')) {
    Write-Host 'Installing frontend dependencies from package-lock.json...' -ForegroundColor Cyan
    & npm.cmd ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed. Check internet connectivity and package registry access, then rerun this script.' }
}

Write-Host ''
Write-Host 'Starting frontend at http://localhost:5173' -ForegroundColor Green
Write-Host 'Keep this PowerShell window open while using the app.' -ForegroundColor Yellow
& npm.cmd run dev -- --host localhost --port 5173 --strictPort
if ($LASTEXITCODE -ne 0) { throw "Vite exited with code $LASTEXITCODE." }
