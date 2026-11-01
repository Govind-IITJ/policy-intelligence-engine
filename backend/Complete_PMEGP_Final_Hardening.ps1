$ErrorActionPreference = "Stop"
Set-Location "C:\Users\Govind\Downloads\Policy_Intelligence_Phase1_Backend\policy-intelligence-backend"

$python = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Virtualenv Python not found: $python" }
$service = ".\app\services\analysis_service.py"
if (-not (Test-Path $service)) { throw "Run this script from the backend project root; missing $service" }
$runner = ".\Run_PMEGP_Recall_Acceptance_v2.ps1"
if (-not (Test-Path $runner)) { throw "Missing PMEGP acceptance runner: $runner" }

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = ".\backup-final-acceptance-$stamp"
New-Item -ItemType Directory -Path $backup | Out-Null
Copy-Item $service $backup
if (Test-Path ".\tests") { Copy-Item ".\tests" (Join-Path $backup "tests") -Recurse }
Write-Host "Backup created: $backup" -ForegroundColor Green

$patch = @'
from pathlib import Path
import re

path = Path("app/services/analysis_service.py")
source = path.read_text(encoding="utf-8-sig")

if "def _strict_removed_change_gate(" in source:
    raise SystemExit("Final removal gate already exists. Refusing to apply twice; inspect the current source.")

helper = r"""
def _strict_later_subject_passage(change, later_pages):
    # Find a later-version passage on the same named policy subject.
    # This is a conservative recall guard, not a legal-equivalence test.
    source_text = (str(change.get("title") or "") + " " + str(change.get("old_quote") or "")).casefold()
    source_tokens = set(re.findall(r"[a-z0-9]+", source_text))

    anchors = [
        (("physical", "verification"), ("physical", "verification")),
        (("edp", "training"), ("edp", "training")),
        (("udyam",), ("udyam",)),
        (("margin", "money"), ("margin", "money")),
        (("project", "cost"), ("project", "cost")),
        (("eligibility",), ("eligibility",)),
        (("registration",), ("registration",)),
        (("subsidy",), ("subsidy",)),
    ]
    selected_anchor = None
    for source_anchor, required in anchors:
        if all(term in source_tokens for term in source_anchor):
            selected_anchor = required
            break

    stop = {
        "the", "and", "for", "with", "from", "that", "this", "these", "those",
        "was", "were", "are", "is", "be", "been", "being", "to", "of", "in",
        "on", "at", "by", "as", "an", "a", "or", "it", "its", "all", "each",
        "any", "such", "will", "would", "should", "may", "can", "could", "shall",
        "must", "not", "under", "before", "after", "during", "within", "into",
        "their", "them", "they", "who", "which", "what", "when", "where", "how",
        "than", "then", "also", "only", "other", "new", "old", "version",
        "document", "policy", "guideline", "guidelines", "clause", "section",
        "unit", "units", "setup", "set", "up", "beneficiary", "beneficiaries",
        "applicant", "applicants",
    }

    best = None
    for page in later_pages or []:
        page_text = str(page.get("text") or "")
        if not page_text.strip():
            continue
        tokens_page = set(re.findall(r"[a-z0-9]+", page_text.casefold()))
        if selected_anchor and not all(term in tokens_page for term in selected_anchor):
            continue

        # Sentence-like segments plus adjacent pairs preserve exact page excerpts
        # while tolerating line wraps and PDF extraction fragmentation.
        segments = [
            item.strip() for item in re.split(r"(?<=[.!?;:])\s+|\r?\n+", page_text)
            if item.strip()
        ]
        windows = list(segments)
        windows.extend(segments[i] + " " + segments[i + 1] for i in range(len(segments) - 1))
        if not windows:
            windows = [page_text.strip()]

        for snippet in windows:
            candidate_tokens = set(re.findall(r"[a-z0-9]+", snippet.casefold()))
            if selected_anchor and not all(term in candidate_tokens for term in selected_anchor):
                continue
            overlap = {
                term for term in (source_tokens - stop)
                if len(term) >= 3 and term in candidate_tokens
            }
            if selected_anchor:
                score = 10.0 + len(overlap)
            else:
                if len(overlap) < 3:
                    continue
                score = float(len(overlap))
            if re.search(r"\b(no|not|optional|exempt|waived)\b.{0,50}\b(mandatory|required|compulsory)\b", snippet, re.I):
                score += 0.25  # Still related; the changed condition needs human interpretation.
            if best is None or score > best["score"]:
                quote = snippet.strip()
                if len(quote) > 520:
                    quote = quote[:517].rsplit(" ", 1)[0] + "..."
                best = {
                    "page": page.get("page"),
                    "quote": quote,
                    "score": score,
                    "anchor": " ".join(selected_anchor) if selected_anchor else None,
                }
    return best


def _strict_removed_change_gate(change, later_pages):
    # Never allow an AI-generated removal to pass as a confirmed repeal.
    if str(change.get("change_type", "")).casefold() != "removed":
        return change

    # A removed provision always remains human-reviewable, even when the quoted
    # old text is perfectly verified.
    change["review_required"] = True
    related = _strict_later_subject_passage(change, later_pages)
    if related and isinstance(related.get("page"), int) and related.get("quote"):
        change["change_type"] = "modified"
        change["new_page"] = related["page"]
        change["new_quote"] = related["quote"]
        explanation = str(change.get("explanation") or "").strip()
        note = (
            "Related subject matter was found in the later version on page "
            f"{related['page']}. This is a provisional modification, not a confirmed repeal; "
            "a human must compare the complete provisions and conditions."
        )
        change["explanation"] = (explanation + " " if explanation else "") + note
        change["removal_verification"] = {
            "status": "related_later_provision_found",
            "related_page": related["page"],
            "related_quote": related["quote"],
            "subject_anchor": related["anchor"],
            "interpretation": "provisional_modification_requires_human_review",
        }
        change["evidence_warning"] = (
            "Related text exists in the later version. Review both full provisions; do not "
            "treat the earlier requirement as repealed based on this automated comparison."
        )
    else:
        change["removal_verification"] = {
            "status": "not_established",
            "interpretation": "absence_of_match_is_not_proof_of_repeal",
        }
        change["evidence_warning"] = (
            "The automated check did not locate a corresponding later passage. This does not "
            "prove repeal. Review the complete policy, annexes and any renumbered provisions."
        )
    return change
"""

anchor = "def _deduplicate_changes("
if anchor not in source:
    raise SystemExit("Cannot find _deduplicate_changes() insertion point. No source changes written.")
source = source.replace(anchor, helper + "\n\n" + anchor, 1)

loop = 'for change in _deduplicate_changes(result.get("changes", [])):'
if source.count(loop) != 1:
    raise SystemExit(f"Expected exactly one analysis change loop; found {source.count(loop)}. No source changes written.")

# Replace the previous narrow guard if present; otherwise insert the strict gate
# as the first operation inside the canonical validation loop.
source = source.replace(
    'change = _guard_removed_change(change, later["pages"])',
    'change = _strict_removed_change_gate(change, later["pages"])'
)
source = source.replace(
    'change = _guard_removed_change(change, later[\"pages\"])',
    'change = _strict_removed_change_gate(change, later[\"pages\"])'
)

loop_pos = source.index(loop) + len(loop)
tail = source[loop_pos:loop_pos + 260]
if "_strict_removed_change_gate(change, later[\"pages\"])" not in tail and "_strict_removed_change_gate(change, later['pages'])" not in tail:
    source = source[:loop_pos] + '\n            change = _strict_removed_change_gate(change, later["pages"])' + source[loop_pos:]

# Keep overall review status consistent with per-finding review flags.
changes_assignment = 'result["changes"] = enriched_changes'
if changes_assignment not in source:
    changes_assignment = 'result["changes"] = enriched_changes'
if changes_assignment not in source:
    raise SystemExit("Cannot find final enriched-changes assignment. No source changes written.")
replacement = changes_assignment + '\n        if any(bool(item.get("review_required")) for item in enriched_changes):\n            result["overall_review_required"] = True'
source = source.replace(changes_assignment, replacement, 1)

path.write_text(source, encoding="utf-8")
print("Installed strict subject-based removal gate.")
print("Physical-verification / EDP-training continuations are detected across the later document.")
print("Every remaining removal requires human review; overall review status now propagates.")
'@

$patch | & $python -
if ($LASTEXITCODE -ne 0) { throw "Backend patch failed. Source backup: $backup" }

$testCode = @'
from app.services.analysis_service import _strict_removed_change_gate


def test_physical_verification_continuation_is_not_reported_as_repeal():
    change = {
        "change_type": "removed",
        "title": "Removal of mandatory 100% physical verification",
        "old_page": 41,
        "old_quote": "As per the scheme guidelines, 100% physical verification is mandatory for all the units setup.",
        "explanation": "The requirement was removed.",
        "review_required": False,
    }
    later_pages = [{
        "page": 14,
        "text": "100% physical verification with geo-tagging of the actual establishment and working status of each of the units set up under PMEGP will be done by KVIC.",
    }]
    result = _strict_removed_change_gate(change, later_pages)
    assert result["change_type"] == "modified"
    assert result["new_page"] == 14
    assert "physical verification" in result["new_quote"].casefold()
    assert result["review_required"] is True
    assert result["removal_verification"]["status"] == "related_later_provision_found"


def test_edp_training_continuation_becomes_reviewable_modification():
    change = {
        "change_type": "removed",
        "title": "Removal of mandatory EDP training",
        "old_page": 33,
        "old_quote": "EDP training is a mandatory training to be undergone by beneficiary to be eligible for sanction.",
    }
    later_pages = [{
        "page": 13,
        "text": "EDP training is mandatory for claiming the Margin Money subsidy. No EDP training will be mandatory for projects up to Rs. 2 lakh.",
    }]
    result = _strict_removed_change_gate(change, later_pages)
    assert result["change_type"] == "modified"
    assert result["new_page"] == 13
    assert "edp training" in result["new_quote"].casefold()
    assert result["review_required"] is True


def test_unmatched_removal_is_never_accepted_without_review():
    change = {
        "change_type": "removed",
        "title": "Removal of a quarterly reporting requirement",
        "old_quote": "Quarterly district employment reconciliation statement shall be filed with the regional office.",
        "review_required": False,
    }
    later_pages = [{"page": 2, "text": "The scheme shall be implemented by the designated agencies."}]
    result = _strict_removed_change_gate(change, later_pages)
    assert result["change_type"] == "removed"
    assert result["review_required"] is True
    assert result["removal_verification"]["status"] == "not_established"
    assert "does not prove repeal" in result["evidence_warning"]


def test_non_removed_finding_is_not_changed():
    change = {"change_type": "added", "title": "New reporting rule", "review_required": False}
    result = _strict_removed_change_gate(change, [{"page": 1, "text": "New reporting rule."}])
    assert result == change
'@

$testCode | & $python -
if ($LASTEXITCODE -ne 0) { throw "Regression-test source generation failed." }
Set-Content -Path ".\tests\test_strict_removal_gate.py" -Value $testCode -Encoding UTF8

Write-Host "`nRunning compile check and full test suite..." -ForegroundColor Cyan
& $python -m compileall -q app tests
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed. Backup: $backup" }
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Test suite failed. Do not run the live acceptance test. Backup: $backup" }

Write-Host "`nPATCH AND REGRESSION TESTS PASSED." -ForegroundColor Green

# Restart only the known Policy Intelligence Uvicorn process on port 8001.
$listener = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    $ownerIds = $listener | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($ownerId in $ownerIds) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerId" -ErrorAction SilentlyContinue
        $commandLine = [string]$proc.CommandLine
        if ($commandLine -notmatch '(?i)uvicorn.*app\.main:app' -or $commandLine -notmatch '(?i)--port\s+8001') {
            throw "Port 8001 is occupied by PID $ownerId, not the expected backend. No process was terminated."
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
$end = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $end -and -not $healthy) {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8001/health" -UseBasicParsing -TimeoutSec 3
        if ($health.status -eq "ok") { $healthy = $true }
    } catch {}
}
if (-not $healthy) {
    if (Test-Path $stderr) { Get-Content $stderr -Tail 60 }
    throw "Patched backend did not become healthy on port 8001."
}
Write-Host "Patched backend healthy on port 8001." -ForegroundColor Green

Write-Host "`nRunning real PMEGP comparison..." -ForegroundColor Cyan
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runner
if ($LASTEXITCODE -ne 0) { throw "PMEGP Udyam evidence gate failed. Preserve the latest JSON result." }

# Inspect the newest saved result and enforce removal/review acceptance as well.
$outDir = ".\sample_requests\pmegp_official"
$latest = Get-ChildItem $outDir -Filter "PMEGP_Recall_Acceptance_*.json" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $latest) { throw "No saved PMEGP acceptance JSON found." }
$full = Get-Content $latest.FullName -Raw | ConvertFrom-Json
$result = $full.result
if ($null -eq $result) { throw "Saved acceptance JSON has no result payload: $($latest.FullName)" }

$changes = @($result.changes)
$unreviewedRemovals = @($changes | Where-Object { $_.change_type -eq "removed" -and $_.review_required -ne $true })
$physicalStillRemoved = @($changes | Where-Object {
    $_.change_type -eq "removed" -and (("$($_.title) $($_.old_quote)") -match '(?i)physical\s+verification')
})
$reviewCount = @($changes | Where-Object { $_.review_required -eq $true }).Count
$reportedReviewCount = 0
if ($null -ne $result.counts -and $null -ne $result.counts.needs_review) {
    $reportedReviewCount = [int]$result.counts.needs_review
}

Write-Host "`n========== FINAL ACCEPTANCE GATES ==========" -ForegroundColor Cyan
Write-Host "Findings: $($changes.Count)"
Write-Host "Per-finding review flags: $reviewCount"
Write-Host "Reported needs_review count: $reportedReviewCount"
Write-Host "Unreviewed removals: $($unreviewedRemovals.Count)"
Write-Host "Physical-verification findings still classified as removed: $($physicalStillRemoved.Count)"
Write-Host "Overall review required: $($result.overall_review_required)"
Write-Host "Result JSON: $($latest.FullName)"

if ($unreviewedRemovals.Count -gt 0) {
    throw "FAIL: one or more removal findings are not flagged for human review."
}
if ($physicalStillRemoved.Count -gt 0) {
    throw "FAIL: physical-verification finding still appears as a removal despite a related later provision."
}
if ($reportedReviewCount -ne $reviewCount) {
    throw "FAIL: needs_review count does not match per-finding review flags."
}
if ($reviewCount -gt 0 -and $result.overall_review_required -ne $true) {
    throw "FAIL: overall_review_required did not propagate review flags."
}

Write-Host "`nREMOVAL AND REVIEW ACCEPTANCE GATES PASSED." -ForegroundColor Green
Write-Host "Udyam recall, removal safety and review-count consistency passed for this PMEGP test pair."
Write-Host "This is a focused acceptance result, not exhaustive legal certification." -ForegroundColor Yellow
