$ErrorActionPreference = 'Stop'

# Run from the policy-intelligence-backend project root.
$baseUrl = 'http://127.0.0.1:8001'
$earlierId = 'e29f5941-9545-4570-a16d-12550e87fb27'
$laterId   = '661f4cac-38ce-4412-ad97-2436db3fb8a6'
$outDir = '.\sample_requests\pmegp_official'

if (-not (Test-Path $outDir)) { throw "PMEGP output directory not found: $outDir" }

Write-Host "`n========== PMEGP CANDIDATE-RECALL ACCEPTANCE ==========" -ForegroundColor Cyan
try {
    $health = Invoke-RestMethod -Uri "$baseUrl/health" -Method Get -UseBasicParsing -TimeoutSec 15
} catch {
    throw "Backend on port 8001 is not reachable. Start it with: .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001"
}
if ($health.status -ne 'ok') { throw 'Backend health check did not return status=ok.' }
Write-Host "Backend healthy: version $($health.version)" -ForegroundColor Green

$payload = @{ earlier_document_id = $earlierId; later_document_id = $laterId }
$body = $payload | ConvertTo-Json -Depth 10
$started = Invoke-RestMethod -Uri "$baseUrl/api/documents/compare" -Method Post -ContentType 'application/json' -Body $body -UseBasicParsing -TimeoutSec 30
$analysisId = [string]$started.analysis_id
if ([string]::IsNullOrWhiteSpace($analysisId)) { throw 'Comparison API did not return an analysis_id.' }
Write-Host "New analysis ID: $analysisId" -ForegroundColor Green

$finalStatus = $null
$deadline = (Get-Date).AddMinutes(15)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    $finalStatus = Invoke-RestMethod -Uri "$baseUrl/api/analysis/$analysisId" -Method Get -UseBasicParsing -TimeoutSec 30
    Write-Host "Status: $($finalStatus.status)"
    if ($finalStatus.status -eq 'completed' -or $finalStatus.status -eq 'failed') { break }
}
if ($null -eq $finalStatus -or ($finalStatus.status -ne 'completed' -and $finalStatus.status -ne 'failed')) {
    throw "Analysis did not finish within 15 minutes. Preserve analysis ID: $analysisId"
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$resultPath = Join-Path $outDir "PMEGP_Recall_Acceptance_$stamp.json"
$finalStatus | ConvertTo-Json -Depth 100 | Set-Content -Path $resultPath -Encoding UTF8
Write-Host "Saved full response: $resultPath" -ForegroundColor Green

if ($finalStatus.status -eq 'failed') {
    Write-Host "Analysis error: $($finalStatus.error)" -ForegroundColor Red
    throw "PMEGP comparison failed. Analysis ID: $analysisId"
}

$result = $finalStatus.result
if ($null -eq $result) { throw "Completed analysis has no result payload. Inspect $resultPath" }
$changes = @($result.changes)
Write-Host "`nSUMMARY" -ForegroundColor Cyan
Write-Host $result.summary
Write-Host "`nCOUNTS" -ForegroundColor Cyan
$result.counts | ConvertTo-Json -Depth 20 | Write-Host
Write-Host "`nFINDINGS" -ForegroundColor Cyan

$udyamMentioned = $false
$udyamVerified = $false
foreach ($change in $changes) {
    $title = [string]$change.title
    $explanation = [string]$change.explanation
    $oldQuote = [string]$change.old_quote
    $newQuote = [string]$change.new_quote
    $oldText = [string]$change.old_text
    $newText = [string]$change.new_text
    $allText = "$title $explanation $oldQuote $newQuote $oldText $newText"
    if ($allText -match '(?i)udyam') {
        $udyamMentioned = $true
        if (($oldQuote + ' ' + $newQuote + ' ' + $oldText + ' ' + $newText) -match '(?i)udyam' -and $change.evidence_verified -eq $true) {
            $udyamVerified = $true
        }
    }
    [pscustomobject]@{
        title = $title
        change_type = $change.change_type
        explanation = $explanation
        old_page = $change.old_page
        old_quote = $oldQuote
        new_page = $change.new_page
        new_quote = $newQuote
        evidence_verified = $change.evidence_verified
        numerical_consistency_verified = $change.numerical_consistency_verified
        review_required = $change.review_required
        evidence_warning = $change.evidence_warning
        consistency_warnings = $change.consistency_warnings
    } | ConvertTo-Json -Depth 15 | Write-Host
}

Write-Host "`nLIMITATIONS" -ForegroundColor Cyan
@($result.limitations) | ForEach-Object { Write-Host "- $_" }
Write-Host "`nACCEPTANCE METRICS" -ForegroundColor Cyan
Write-Host "Findings returned: $($changes.Count)"
Write-Host "Udyam mentioned anywhere: $udyamMentioned"
Write-Host "Udyam backed by a verified source quote: $udyamVerified"
Write-Host "Overall review required: $($result.overall_review_required)"
Write-Host "Full result: $resultPath"

if (-not $udyamVerified) {
    Write-Host "`nACCEPTANCE FAILED: no Udyam-related finding is supported by a verified source quotation." -ForegroundColor Red
    Write-Host 'Keep the JSON as a regression artifact. Candidate recall is not accepted.'
    exit 2
}
Write-Host "`nPMEGP UDYAM EVIDENCE GATE PASSED." -ForegroundColor Green
Write-Host 'This passes the targeted Udyam recall gate only; it does not certify exhaustive legal review.' -ForegroundColor Yellow
