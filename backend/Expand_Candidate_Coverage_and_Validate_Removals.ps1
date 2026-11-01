$ErrorActionPreference = "Stop"
Set-Location "C:\Users\Govind\Downloads\Policy_Intelligence_Phase1_Backend\policy-intelligence-backend"

$python = Join-Path $PWD ".venv\Scripts\python.exe"
$aiPath = ".\app\services\ai_service.py"
$analysisPath = ".\app\services\analysis_service.py"
$runner = ".\Run_PMEGP_Recall_Acceptance_v2.ps1"
foreach ($f in @($python, $aiPath, $analysisPath, $runner)) {
    if (-not (Test-Path $f)) { throw "Required project file missing: $f" }
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = ".\backup-expanded-coverage-full-policy-$stamp"
New-Item -ItemType Directory -Path $backup | Out-Null
Copy-Item $aiPath $backup
Copy-Item $analysisPath $backup
if (Test-Path ".\tests") { Copy-Item ".\tests" (Join-Path $backup "tests") -Recurse }
Write-Host "Backup created: $backup" -ForegroundColor Green

$patch = @'
import ast
import re
from pathlib import Path

ai_path = Path("app/services/ai_service.py")
analysis_path = Path("app/services/analysis_service.py")
ai = ai_path.read_text(encoding="utf-8-sig")
analysis = analysis_path.read_text(encoding="utf-8-sig")

if "_select_candidates(all_candidates, limit=16)" in ai:
    raise SystemExit("Candidate window is already 16; refusing duplicate patch.")
ai, count = re.subn(
    r"_select_candidates\(\s*all_candidates\s*,\s*limit\s*=\s*12\s*\)",
    "_select_candidates(all_candidates, limit=16)",
    ai,
    count=1,
)
if count != 1:
    ai, count = re.subn(
        r"_select_candidates\(\s*all_candidates\s*,\s*12\s*\)",
        "_select_candidates(all_candidates, 16)",
        ai,
        count=1,
    )
if count != 1:
    raise SystemExit("Could not find current 12-candidate selector call. No files written.")

if "def _validate_removal_against_complete_later_document(" in analysis:
    raise SystemExit("Full-policy removal validator already exists; refusing duplicate patch.")

helper = r'''

def _validate_removal_against_complete_later_document(
    change: dict[str, Any],
    later_pages: list[dict[str, Any]],
) -> dict[str, Any]:
    if str(change.get("change_type", "")).casefold() != "removed":
        return change

    change["review_required"] = True
    old_material = " ".join(
        str(change.get(key) or "")
        for key in ("title", "old_text", "old_quote", "explanation")
    ).casefold()

    anchors = [
        ("physical verification", re.compile(r"\bphysical\s+verification\b", re.I)),
        ("EDP training", re.compile(r"\bEDP\s+training\b", re.I)),
        ("Udyam", re.compile(r"\bUdyam\b", re.I)),
        ("Margin Money", re.compile(r"\bMargin\s+Money\b", re.I)),
        ("project cost", re.compile(r"\bproject\s+cost\b", re.I)),
        ("registration", re.compile(r"\bregistration\b", re.I)),
        ("eligibility", re.compile(r"\beligib(?:ility|le)\b", re.I)),
        ("training", re.compile(r"\btraining\b", re.I)),
        ("verification", re.compile(r"\bverification\b", re.I)),
    ]
    selected = next(
        ((label, pattern) for label, pattern in anchors if pattern.search(old_material)),
        None,
    )
    related = None

    if selected:
        label, pattern = selected
        # Search every extracted page of the later document, not model candidates.
        for page in later_pages or []:
            page_text = str(page.get("text") or "")
            match = pattern.search(page_text)
            if not match:
                continue
            start = max(0, match.start() - 150)
            end = min(len(page_text), match.end() + 260)
            quote = page_text[start:end].strip()
            if len(quote) > 520:
                quote = quote[:520]
            if quote:
                related = {"page": page.get("page"), "quote": quote, "anchor": label}
                break

    if related:
        change["change_type"] = "modified"
        change["new_page"] = related["page"]
        change["new_quote"] = related["quote"]
        change["title"] = f"Changed provision concerning {related['anchor']}"
        old_explanation = str(change.get("explanation") or "").strip()
        note = (
            f"The complete extracted later document contains related text about "
            f"{related['anchor']} on page {related['page']}. This is a provisional "
            "modification, not a confirmed repeal. Compare complete clauses, conditions, "
            "exceptions and cross-references manually."
        )
        change["explanation"] = (old_explanation + " " if old_explanation else "") + note
        change["removal_verification"] = {
            "status": "related_later_provision_found",
            "subject": related["anchor"],
            "later_page": related["page"],
            "later_quote": related["quote"],
            "confirmed_repeal": False,
            "human_review_required": True,
            "search_scope": "all_extracted_later_document_pages",
        }
        change["evidence_warning"] = (
            "Related subject matter exists in the later version. This provisional "
            "modification requires full clause-level human review."
        )
    else:
        change["removal_verification"] = {
            "status": "no_related_passage_located",
            "confirmed_repeal": False,
            "human_review_required": True,
            "search_scope": "all_extracted_later_document_pages",
        }
        change["evidence_warning"] = (
            "No related passage was located by automated subject search. This does not "
            "establish repeal. Review the complete later policy, amendments, annexes, "
            "renumbered clauses and incorporated documents manually."
        )
    return change
'''

anchor = "\ndef run_analysis_job("
if anchor not in analysis:
    raise SystemExit("Could not find run_analysis_job insertion point. No files written.")
analysis = analysis.replace(anchor, helper + anchor, 1)

loop = 'for change in _deduplicate_changes(result.get("changes", [])):'
if analysis.count(loop) != 1:
    raise SystemExit("Expected exactly one canonical change-enrichment loop. No files written.")
pos = analysis.index(loop) + len(loop)
analysis = analysis[:pos] + '\n            change = _validate_removal_against_complete_later_document(change, later["pages"])' + analysis[pos:]

ast.parse(ai)
ast.parse(analysis)
ai_path.write_text(ai, encoding="utf-8")
analysis_path.write_text(analysis, encoding="utf-8")
print("Expanded ranked candidate selection from 12 to 16.")
print("Installed full later-document removal validation across all extracted pages.")
'@

$patch | & $python -
if ($LASTEXITCODE -ne 0) { throw "Source patch failed. Backup: $backup" }

$tests = @'
from app.services.ai_service import _select_candidates
from app.services.analysis_service import _validate_removal_against_complete_later_document


def test_candidate_window_can_select_sixteen_ranked_candidates():
    candidates = []
    for index in range(22):
        candidates.append({
            "operation": "modified",
            "old_page": index + 1,
            "new_page": index + 1,
            "old_text": f"Existing provision number {index} requires the applicant to submit a distinct form.",
            "new_text": f"Revised provision number {index} requires the applicant to submit an updated distinct form.",
        })
    selected = _select_candidates(candidates, limit=16)
    assert len(selected) == 16


def test_physical_verification_is_checked_across_all_later_pages():
    change = {
        "title": "Removal of Mandatory 100% Physical Verification",
        "change_type": "removed",
        "old_text": "100% physical verification is mandatory for every unit setup.",
        "old_quote": "100% physical verification is mandatory for every unit setup.",
        "explanation": "The requirement appears absent.",
        "review_required": False,
    }
    later_pages = [
        {"page": 1, "text": "Introductory scheme overview."},
        {"page": 17, "text": "The actual establishment and working status of each unit will be checked through 100% physical verification with geo-tagging."},
    ]
    result = _validate_removal_against_complete_later_document(change, later_pages)
    assert result["change_type"] == "modified"
    assert result["new_page"] == 17
    assert "physical verification" in result["new_quote"].casefold()
    assert result["review_required"] is True
    assert result["removal_verification"]["search_scope"] == "all_extracted_later_document_pages"


def test_edp_training_retained_with_changed_conditions_is_provisional_modification():
    change = {
        "title": "Removal of Mandatory EDP Training",
        "change_type": "removed",
        "old_quote": "EDP training is mandatory for beneficiary eligibility.",
        "old_text": "EDP training is mandatory.",
        "review_required": False,
    }
    later_pages = [
        {"page": 8, "text": "Projects up to Rs. 2 lakh are exempt from EDP training. EDP training is mandatory for beneficiaries claiming Margin Money subsidy."}
    ]
    result = _validate_removal_against_complete_later_document(change, later_pages)
    assert result["change_type"] == "modified"
    assert result["new_page"] == 8
    assert result["review_required"] is True
    assert result["removal_verification"]["confirmed_repeal"] is False


def test_unmatched_removal_is_never_treated_as_confirmed_repeal():
    change = {
        "title": "Removal of quarterly report",
        "change_type": "removed",
        "old_quote": "Quarterly district employment reports shall be filed.",
        "review_required": False,
    }
    later_pages = [{"page": 1, "text": "The scheme will be implemented by designated agencies."}]
    result = _validate_removal_against_complete_later_document(change, later_pages)
    assert result["change_type"] == "removed"
    assert result["review_required"] is True
    assert result["removal_verification"]["confirmed_repeal"] is False
    assert "does not establish repeal" in result["evidence_warning"]
'@
Set-Content -Path ".\tests\test_coverage_and_full_policy_removal.py" -Value $tests -Encoding UTF8

Write-Host "`nRunning compile check and full test suite..." -ForegroundColor Cyan
& $python -m compileall -q app tests
if ($LASTEXITCODE -ne 0) { throw "Compile check failed. Backup: $backup" }
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed. Backend restart and live comparison skipped. Backup: $backup" }

Write-Host "`nCANDIDATE COVERAGE AND FULL-POLICY VALIDATION TESTS PASSED." -ForegroundColor Green

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

Start-Process -FilePath $python `
    -ArgumentList @("-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8001") `
    -WorkingDirectory $PWD -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $PWD "uvicorn-8001.log") `
    -RedirectStandardError (Join-Path $PWD "uvicorn-8001-error.log") | Out-Null

$healthy = $false
$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $deadline -and -not $healthy) {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod "http://127.0.0.1:8001/health" -UseBasicParsing -TimeoutSec 3
        if ($health.status -eq "ok") { $healthy = $true }
    } catch {}
}
if (-not $healthy) {
    Get-Content ".\uvicorn-8001-error.log" -Tail 60 -ErrorAction SilentlyContinue
    throw "Backend failed to become healthy on port 8001."
}
Write-Host "Backend healthy on port 8001." -ForegroundColor Green

Write-Host "`nRunning real PMEGP comparison..." -ForegroundColor Cyan
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runner
if ($LASTEXITCODE -ne 0) { throw "PMEGP Udyam evidence gate failed." }

$outDir = ".\sample_requests\pmegp_official"
$latest = Get-ChildItem $outDir -Filter "PMEGP_Recall_Acceptance_*.json" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $latest) { throw "No saved PMEGP result JSON found." }
$full = Get-Content $latest.FullName -Raw | ConvertFrom-Json
$result = $full.result
if ($null -eq $result) { throw "Result payload missing in $($latest.FullName)" }

$changes = @($result.changes)
$removals = @($changes | Where-Object { $_.change_type -eq "removed" })
$unreviewed = @($changes | Where-Object { $_.review_required -ne $true })
$reviewCount = @($changes | Where-Object { $_.review_required -eq $true }).Count
$reportedReviewCount = [int]$result.counts.needs_review
$relatedModifications = @($changes | Where-Object {
    $_.change_type -eq "modified" -and $_.removal_verification.status -eq "related_later_provision_found"
})

Write-Host "`n========== COVERAGE + FULL-POLICY ACCEPTANCE ==========" -ForegroundColor Cyan
Write-Host "Findings returned: $($changes.Count)"
Write-Host "Candidate input target: 16 (previously 12)"
Write-Host "Findings with later-policy related passage: $($relatedModifications.Count)"
Write-Host "Remaining removal claims: $($removals.Count)"
Write-Host "Unreviewed findings: $($unreviewed.Count)"
Write-Host "needs_review count: $reportedReviewCount"
Write-Host "Review flags: $reviewCount"
Write-Host "Overall review required: $($result.overall_review_required)"
Write-Host "Result: $($latest.FullName)"

if ($unreviewed.Count -gt 0) { throw "FAIL: an item escaped human review." }
if ($reportedReviewCount -ne $reviewCount) { throw "FAIL: needs_review count differs from review flags." }
if ($reviewCount -gt 0 -and $result.overall_review_required -ne $true) {
    throw "FAIL: overall review status did not propagate."
}

Write-Host "`nCOVERAGE + REVIEW-SAFETY ACCEPTANCE PASSED." -ForegroundColor Green
Write-Host "Related later passages are provisional modifications, not confirmed legal conclusions." -ForegroundColor Yellow
Write-Host "Candidate review remains focused on 16 candidates, not exhaustive review." -ForegroundColor Yellow
