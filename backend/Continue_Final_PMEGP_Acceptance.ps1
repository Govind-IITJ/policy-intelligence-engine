$ErrorActionPreference = "Stop"
Set-Location "C:\Users\Govind\Downloads\Policy_Intelligence_Phase1_Backend\policy-intelligence-backend"

$python = Join-Path $PWD ".venv\Scripts\python.exe"
$testFile = ".\tests\test_model_removal_review_invariant.py"
$runner = ".\Run_PMEGP_Recall_Acceptance_v2.ps1"
if (-not (Test-Path $python)) { throw "Virtualenv Python not found." }
if (-not (Test-Path $testFile)) { throw "Missing new regression test file: $testFile" }
if (-not (Test-Path $runner)) { throw "Missing PMEGP acceptance runner: $runner" }

# Correct the test fixtures to use the actual ConfidenceLevel enum values.
$content = Get-Content $testFile -Raw
$content = $content.Replace("confidence=0.9,", 'confidence="high",')
$content = $content.Replace("confidence=0.95,", 'confidence="high",')
Set-Content -Path $testFile -Value $content -Encoding UTF8
Write-Host "Corrected confidence fixtures to the model's high/medium/low enum." -ForegroundColor Green

Write-Host "`nRunning compile check and complete test suite..." -ForegroundColor Cyan
& $python -m compileall -q app tests
if ($LASTEXITCODE -ne 0) { throw "Compilation failed." }
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed. Backend restart and live test were skipped." }

Write-Host "`nMODEL-LEVEL REVIEW INVARIANT TESTS PASSED." -ForegroundColor Green

# Restart only the expected Policy Intelligence Uvicorn process on port 8001.
$listener = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    foreach ($ownerId in ($listener | Select-Object -ExpandProperty OwningProcess -Unique)) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerId" -ErrorAction SilentlyContinue
        $cmd = [string]$proc.CommandLine
        if ($cmd -notmatch '(?i)uvicorn.*app\.main:app' -or $cmd -notmatch '(?i)--port\s+8001') {
            throw "Port 8001 belongs to unexpected PID $ownerId. No process was terminated."
        }
        Stop-Process -Id $ownerId -Force
    }
    Start-Sleep -Seconds 2
}

$stdout = Join-Path $PWD "uvicorn-8001.log"
$stderr = Join-Path $PWD "uvicorn-8001-error.log"
Start-Process -FilePath $python `
    -ArgumentList @("-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8001") `
    -WorkingDirectory $PWD -WindowStyle Hidden `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr | Out-Null

$healthy = $false
$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $deadline -and -not $healthy) {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8001/health" -UseBasicParsing -TimeoutSec 3
        if ($health.status -eq "ok") { $healthy = $true }
    } catch {}
}
if (-not $healthy) {
    if (Test-Path $stderr) { Get-Content $stderr -Tail 60 }
    throw "Backend did not become healthy on port 8001."
}
Write-Host "Backend healthy on port 8001." -ForegroundColor Green

Write-Host "`nRunning the real PMEGP comparison..." -ForegroundColor Cyan
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runner
if ($LASTEXITCODE -ne 0) { throw "PMEGP runner failed. Preserve the analysis JSON and logs." }

$outDir = ".\sample_requests\pmegp_official"
$latest = Get-ChildItem $outDir -Filter "PMEGP_Recall_Acceptance_*.json" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $latest) { throw "No saved PMEGP acceptance JSON found." }
$full = Get-Content $latest.FullName -Raw | ConvertFrom-Json
$result = $full.result
if ($null -eq $result) { throw "Saved JSON has no result payload: $($latest.FullName)" }

$changes = @($result.changes)
$removed = @($changes | Where-Object { $_.change_type -eq "removed" })
$unreviewedRemoved = @($removed | Where-Object { $_.review_required -ne $true })
$reviewCount = @($changes | Where-Object { $_.review_required -eq $true }).Count
$reportedReviewCount = [int]$result.counts.needs_review

Write-Host "`n========== FINAL REVIEW-INVARIANT ACCEPTANCE ==========" -ForegroundColor Cyan
Write-Host "Findings: $($changes.Count)"
Write-Host "Removed findings: $($removed.Count)"
Write-Host "Review-required findings: $reviewCount"
Write-Host "Reported needs_review: $reportedReviewCount"
Write-Host "Overall review required: $($result.overall_review_required)"
Write-Host "Result JSON: $($latest.FullName)"

if ($unreviewedRemoved.Count -gt 0) { throw "FAIL: at least one removed finding is not flagged for review." }
if ($reportedReviewCount -ne $reviewCount) { throw "FAIL: needs_review count differs from finding-level review flags." }
if ($reviewCount -gt 0 -and $result.overall_review_required -ne $true) {
    throw "FAIL: overall_review_required did not propagate."
}

Write-Host "`nREVIEW-INVARIANT ACCEPTANCE PASSED." -ForegroundColor Green
Write-Host "No removal can pass without human review in this result." -ForegroundColor Green
Write-Host "This does not prove whether the removal itself is legally correct." -ForegroundColor Yellow
