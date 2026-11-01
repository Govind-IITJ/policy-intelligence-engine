$ErrorActionPreference = "Stop"
Set-Location "C:\Users\Govind\Downloads\Policy_Intelligence_Phase1_Backend\policy-intelligence-backend"

$python = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Virtualenv Python not found." }
if (-not (Test-Path ".\app\models.py")) { throw "Missing app\models.py. Run from project root." }
if (-not (Test-Path ".\Run_PMEGP_Recall_Acceptance_v2.ps1")) { throw "Missing PMEGP acceptance runner." }

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = ".\backup-model-review-invariant-$stamp"
New-Item -ItemType Directory -Path $backup | Out-Null
Copy-Item ".\app\models.py" $backup
if (Test-Path ".\tests") { Copy-Item ".\tests" (Join-Path $backup "tests") -Recurse }
Write-Host "Backup created: $backup" -ForegroundColor Green

$patch = @'
import ast
from pathlib import Path

path = Path("app/models.py")
source = path.read_text(encoding="utf-8-sig")
tree = ast.parse(source)

if "def _force_review_for_removed_change" in source:
    raise SystemExit("Model-level removal invariant already exists; refusing duplicate patch.")

classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
if "ChangeDraft" not in classes:
    raise SystemExit("Could not find top-level ChangeDraft class. No changes written.")
if "ComparisonDraft" not in classes:
    raise SystemExit("Could not find top-level ComparisonDraft class. No changes written.")

if "model_validator" not in source:
    future_lines = [
        node.end_lineno for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
    ]
    insert_at = max(future_lines, default=0)
    lines = source.splitlines(True)
    lines.insert(insert_at, "from pydantic import model_validator\n")
    source = "".join(lines)
    tree = ast.parse(source)
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}

change_method = r'''
    @model_validator(mode="after")
    def _force_review_for_removed_change(self):
        change_type = getattr(self.change_type, "value", self.change_type)
        if str(change_type).casefold() == "removed":
            object.__setattr__(self, "review_required", True)
        return self
'''

comparison_method = r'''
    @model_validator(mode="after")
    def _propagate_review_to_comparison(self):
        changes = getattr(self, "changes", []) or []
        requires_review = any(
            bool(getattr(item, "review_required", False))
            or str(getattr(getattr(item, "change_type", ""), "value",
                           getattr(item, "change_type", ""))).casefold() == "removed"
            for item in changes
        )
        if requires_review:
            object.__setattr__(self, "overall_review_required", True)
        return self
'''

insertions = [
    (classes["ChangeDraft"].end_lineno, change_method),
    (classes["ComparisonDraft"].end_lineno, comparison_method),
]
lines = source.splitlines(True)
for end_line, method in sorted(insertions, reverse=True):
    lines.insert(end_line, "\n" + method.strip("\n") + "\n")
source = "".join(lines)
ast.parse(source)
path.write_text(source, encoding="utf-8")
print("Added Pydantic invariant: every removed change requires human review.")
print("Added comparison invariant: review requirement propagates to overall_review_required.")
'@

$patch | & $python -
if ($LASTEXITCODE -ne 0) { throw "Could not patch models.py. Backup: $backup" }

$test = @'
from app.models import ChangeDraft, ComparisonDraft


def _removed_change():
    return ChangeDraft(
        title="Removal of 100% physical verification",
        change_type="removed",
        old_text="100% physical verification is mandatory for all unit setups.",
        new_text="",
        explanation="The requirement appears absent in the later text.",
        affected_stakeholders=["PMEGP beneficiaries"],
        practical_action="Seek clarification before relying on this interpretation.",
        old_page=41,
        old_quote="100% physical verification is mandatory for all unit setups.",
        new_page=None,
        new_quote="",
        confidence=0.9,
        review_required=False,
    )


def test_removed_change_cannot_be_marked_review_complete():
    change = _removed_change()
    assert change.review_required is True


def test_comparison_inherits_review_from_removed_change():
    change = _removed_change()
    draft = ComparisonDraft(
        title="PMEGP comparison",
        summary="Test comparison",
        key_findings=[],
        changes=[change],
        action_checklist=[],
        limitations=[],
        overall_review_required=False,
    )
    assert draft.overall_review_required is True


def test_non_removed_finding_preserves_review_flag():
    change = ChangeDraft(
        title="New Udyam requirement",
        change_type="added",
        old_text="",
        new_text="All new PMEGP units must register under Udyam.",
        explanation="A new mandatory requirement.",
        affected_stakeholders=["New PMEGP units"],
        practical_action="Complete Udyam registration.",
        old_page=None,
        old_quote="",
        new_page=1,
        new_quote="All new PMEGP units must register under Udyam.",
        confidence=0.95,
        review_required=False,
    )
    assert change.review_required is False
'@
Set-Content -Path ".\tests\test_model_removal_review_invariant.py" -Value $test -Encoding UTF8

Write-Host "`nRunning compile and full tests..." -ForegroundColor Cyan
& $python -m compileall -q app tests
if ($LASTEXITCODE -ne 0) { throw "Compile failed. Backup: $backup" }
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed. Backup: $backup" }

Write-Host "`nMODEL REVIEW INVARIANT AND TESTS PASSED." -ForegroundColor Green

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
$until = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $until -and -not $healthy) {
    Start-Sleep -Seconds 2
    try {
        $h = Invoke-RestMethod -Uri "http://127.0.0.1:8001/health" -UseBasicParsing -TimeoutSec 3
        if ($h.status -eq "ok") { $healthy = $true }
    } catch {}
}
if (-not $healthy) {
    if (Test-Path $stderr) { Get-Content $stderr -Tail 60 }
    throw "Patched backend is not healthy on port 8001."
}
Write-Host "Backend healthy on port 8001." -ForegroundColor Green

Write-Host "`nRunning new PMEGP comparison..." -ForegroundColor Cyan
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\Run_PMEGP_Recall_Acceptance_v2.ps1"
if ($LASTEXITCODE -ne 0) { throw "Udyam evidence gate failed. Preserve the latest JSON result." }

$outDir = ".\sample_requests\pmegp_official"
$latest = Get-ChildItem $outDir -Filter "PMEGP_Recall_Acceptance_*.json" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $latest) { throw "No PMEGP result JSON found." }
$full = Get-Content $latest.FullName -Raw | ConvertFrom-Json
$result = $full.result
if ($null -eq $result) { throw "Missing result property in $($latest.FullName)" }

$changes = @($result.changes)
$unreviewed = @($changes | Where-Object { $_.change_type -eq "removed" -and $_.review_required -ne $true })
$removedCount = @($changes | Where-Object { $_.change_type -eq "removed" }).Count
$reviewCount = @($changes | Where-Object { $_.review_required -eq $true }).Count
$reported = [int]$result.counts.needs_review

Write-Host "`n========== FINAL MODEL-INVARIANT CHECK ==========" -ForegroundColor Cyan
Write-Host "Findings: $($changes.Count)"
Write-Host "Removed findings: $removedCount"
Write-Host "Review-required findings: $reviewCount"
Write-Host "Reported needs_review: $reported"
Write-Host "Overall review required: $($result.overall_review_required)"
Write-Host "Result: $($latest.FullName)"

if ($unreviewed.Count -gt 0) { throw "FAIL: a removed finding was not flagged for review." }
if ($reported -ne $reviewCount) { throw "FAIL: persisted needs_review count does not equal the finding flags." }
if ($reviewCount -gt 0 -and $result.overall_review_required -ne $true) {
    throw "FAIL: overall_review_required did not inherit review flags."
}

Write-Host "`nSAFETY ACCEPTANCE PASSED: no unreviewed removals." -ForegroundColor Green
Write-Host "IMPORTANT: a removal may still be a false positive; it is now explicitly review-required, not legally confirmed." -ForegroundColor Yellow
Write-Host "This is a safe triage gate, not exhaustive legal validation." -ForegroundColor Yellow
