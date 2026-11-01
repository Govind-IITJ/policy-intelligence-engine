$ErrorActionPreference = 'Stop'

$root = (Get-Location).Path
$target = '.\app\services\analysis_service.py'
if (-not (Test-Path $target)) {
    throw "Missing $target. Run this script from the policy-intelligence-backend directory."
}
$python = '.\.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }

$backup = ".\backup-removal-guard-$(Get-Date -Format yyyyMMdd-HHmmss)"
New-Item -ItemType Directory -Path $backup | Out-Null
Copy-Item $target $backup
if (Test-Path '.\tests') { Copy-Item '.\tests' (Join-Path $backup 'tests') -Recurse }
Write-Host "Backup created: $backup" -ForegroundColor Green

$patch = @'
from pathlib import Path
import re

path = Path("app/services/analysis_service.py")
source = path.read_text(encoding="utf-8-sig")

if "def _guard_removed_change(" in source:
    raise SystemExit("Removal-verification guard already exists; refusing to apply it twice.")

helper = r'''
_REMOVAL_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "these", "those",
    "was", "were", "are", "is", "be", "been", "being", "to", "of", "in",
    "on", "at", "by", "as", "an", "a", "or", "it", "its", "all", "each",
    "any", "such", "will", "would", "should", "may", "can", "could", "shall",
    "must", "not", "under", "before", "after", "during", "within", "into",
    "their", "them", "they", "he", "she", "his", "her", "who", "which",
    "what", "when", "where", "how", "than", "then", "also", "only", "other",
    "other", "new", "old", "version", "document", "policy", "guideline",
    "guidelines", "clause", "section", "unit", "units", "setup", "set", "up",
    "undergo", "undergone", "beneficiary", "beneficiaries", "applicant", "applicants",
}


def _removal_tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", str(value or "").casefold())
        if len(token) >= 3 and token not in _REMOVAL_STOPWORDS
    }


def _find_related_later_provision(change: dict[str, Any], later_pages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find a later-version passage on the same subject as a claimed removal.

    This is a conservative recall guard, not a legal-equivalence classifier. A
    match forces manual review and converts a one-sided removal into a two-sided
    provisional modification so both versions' evidence can be inspected.
    """
    old_quote = str(change.get("old_quote") or "")
    title = str(change.get("title") or "")
    source_tokens = _removal_tokens(old_quote)
    if len(source_tokens) < 2:
        source_tokens = _removal_tokens(title + " " + old_quote)
    if len(source_tokens) < 2:
        return None

    # Require a meaningful subject anchor for common multi-word policy subjects.
    subject_anchors = []
    source_text = (title + " " + old_quote).casefold()
    for phrase in (
        ("physical", "verification"),
        ("edp", "training"),
        ("udyam", "registration"),
        ("margin", "money"),
        ("project", "cost"),
        ("bank", "loan"),
        ("beneficiary", "contribution"),
    ):
        if all(term in source_text for term in phrase):
            subject_anchors.append(set(phrase))

    best: dict[str, Any] | None = None
    for page in later_pages:
        page_text = str(page.get("text") or "")
        if not page_text.strip():
            continue
        # Keep sentence boundaries where possible and evaluate adjacent pairs to
        # tolerate PDF line wraps and split sentences.
        segments = [part.strip() for part in re.split(r"(?<=[;:!?])\s+|(?<=\.)\s+(?=[A-Z])|\n+", page_text) if part.strip()]
        windows = list(segments)
        windows.extend(
            segments[index] + " " + segments[index + 1]
            for index in range(len(segments) - 1)
        )
        for snippet in windows:
            candidate_tokens = _removal_tokens(snippet)
            overlap = source_tokens & candidate_tokens
            if len(overlap) < 2:
                continue
            anchor_match = any(anchor.issubset(candidate_tokens) for anchor in subject_anchors)
            jaccard = len(overlap) / max(1, len(source_tokens | candidate_tokens))
            source_recall = len(overlap) / max(1, len(source_tokens))
            # A named subject anchor is strong evidence of possible continuation;
            # otherwise require broader token overlap to avoid generic-word hits.
            if not anchor_match and (len(overlap) < 3 or jaccard < 0.16):
                continue
            score = (0.65 if anchor_match else 0.0) + (0.25 * jaccard) + (0.10 * source_recall)
            if re.search(r"\b(no|not|optional|exempt)\b.{0,35}\b(mandatory|required|compulsory)\b", snippet, re.IGNORECASE):
                score -= 0.18
            elif re.search(r"\b(mandatory|required|compulsory)\b", snippet, re.IGNORECASE):
                score += 0.08
            quote = snippet.strip()
            if len(quote) > 520:
                quote = quote[:517].rsplit(" ", 1)[0] + "..."
            if best is None or score > best["score"]:
                best = {
                    "page": page.get("page"),
                    "quote": quote,
                    "score": round(score, 4),
                    "overlap_terms": sorted(overlap),
                    "anchor_match": anchor_match,
                }
    return best


def _guard_removed_change(change: dict[str, Any], later_pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Prevent absence of an aligned excerpt from being presented as proven repeal."""
    if str(change.get("change_type", "")).casefold() != "removed":
        return change

    related = _find_related_later_provision(change, later_pages)
    change["review_required"] = True
    if related and isinstance(related.get("page"), int) and related.get("quote"):
        original_explanation = str(change.get("explanation") or "").strip()
        change["change_type"] = "modified"
        change["new_page"] = related["page"]
        change["new_quote"] = related["quote"]
        change["explanation"] = (
            (original_explanation + " ") if original_explanation else ""
        ) + (
            "A related provision was found in the later version on page "
            f"{related['page']}. The earlier wording therefore cannot be treated as a "
            "confirmed repeal; this is provisionally classified as a possible modification "
            "and requires human review."
        )
        change["removal_verification"] = {
            "status": "related_later_provision_found",
            "related_page": related["page"],
            "related_quote": related["quote"],
            "match_score": related["score"],
            "overlap_terms": related["overlap_terms"],
            "anchor_match": related["anchor_match"],
            "interpretation": "possible_modification_not_proven_repeal",
        }
        change["evidence_warning"] = (
            "Related text exists in the later version. Do not report this as a repeal without "
            "reviewing both provisions and their full surrounding sections."
        )
    else:
        change["removal_verification"] = {
            "status": "not_established",
            "interpretation": "absence_of_match_is_not_proof_of_repeal",
        }
        change["evidence_warning"] = (
            "No related later passage was detected by the automated recall guard. This does "
            "not prove repeal: verify the complete corresponding section, annexes and any "
            "renumbered provisions manually before treating this as removed."
        )
    return change
'''

# Insert helpers before the deduplication helper, which is a stable point in the service.
anchor = "def _deduplicate_changes("
if anchor not in source:
    raise SystemExit("Could not find def _deduplicate_changes; no source changes were written.")
source = source.replace(anchor, helper + "\n\n" + anchor, 1)

# Insert guard at the start of the existing per-change validation loop, before
# evidence requirements are calculated so a possible continuation requires both quotes.
loop_anchor = "for change in _deduplicate_changes(result.get(\"changes\", [])):\n            requires_old, requires_new = _required_evidence(change)"
loop_replacement = (
    "for change in _deduplicate_changes(result.get(\"changes\", [])):\n"
    "            change = _guard_removed_change(change, later[\"pages\"])\n"
    "            requires_old, requires_new = _required_evidence(change)"
)
if loop_anchor not in source:
    raise SystemExit(
        "Could not find the expected change-evidence loop. The helper was not written; "
        "inspect analysis_service.py before applying a manual patch."
    )
source = source.replace(loop_anchor, loop_replacement, 1)

path.write_text(source, encoding="utf-8")
print("Added a removed-change verification guard.")
print("Related later provisions now become two-sided provisional modifications and require review.")
print("Unmatched removals also require review; absence alone is never marked as proof of repeal.")
'@

$patch | & $python -
if ($LASTEXITCODE -ne 0) { throw 'Removal-verification patch failed. Restore from the backup if any source changes were made.' }

$tests = @'
from app.services.analysis_service import _guard_removed_change


def test_physical_verification_is_not_misreported_as_removed():
    change = {
        "change_type": "removed",
        "title": "Removal of mandatory physical verification",
        "old_page": 41,
        "old_quote": "100% physical verification with geo-tagging of the actual establishment and working status of each of the units setup under PMEGP will be done by KVIC.",
        "explanation": "The earlier physical-verification provision appears to be removed.",
        "review_required": False,
    }
    later_pages = [{
        "page": 14,
        "text": "100% physical verification with geo-tagging of the actual establishment and working status of each of the units, set up under PMEGP, including those assisted by other IAs, will be done by KVIC.",
    }]
    guarded = _guard_removed_change(change, later_pages)
    assert guarded["change_type"] == "modified"
    assert guarded["new_page"] == 14
    assert "100% physical verification" in guarded["new_quote"]
    assert guarded["review_required"] is True
    assert guarded["removal_verification"]["status"] == "related_later_provision_found"


def test_edp_training_continuation_becomes_provisional_modification():
    change = {
        "change_type": "removed",
        "title": "Removal of mandatory EDP training",
        "old_page": 33,
        "old_quote": "EDP training is a mandatory training to be undergone by beneficiary to be eligible for sanction and release of loan to the beneficiary.",
    }
    later_pages = [{
        "page": 13,
        "text": "EDP training is mandatory for claiming the Margin Money (subsidy). No EDP training will be mandatory for projects up to Rs. 2 Lakh.",
    }]
    guarded = _guard_removed_change(change, later_pages)
    assert guarded["change_type"] == "modified"
    assert guarded["new_page"] == 13
    assert guarded["new_quote"].startswith("EDP training is mandatory for claiming")
    assert guarded["review_required"] is True
    assert guarded["removal_verification"]["status"] == "related_later_provision_found"


def test_no_related_provision_still_requires_manual_repeal_review():
    change = {
        "change_type": "removed",
        "title": "Removal of a specific reporting obligation",
        "old_quote": "Quarterly district employment reconciliation statement shall be filed with the regional office.",
        "review_required": False,
    }
    later_pages = [{"page": 2, "text": "This scheme shall be implemented by the Ministry through the designated agencies."}]
    guarded = _guard_removed_change(change, later_pages)
    assert guarded["change_type"] == "removed"
    assert guarded["review_required"] is True
    assert guarded["removal_verification"]["status"] == "not_established"
    assert "does not prove repeal" in guarded["evidence_warning"]


def test_non_removed_change_is_unchanged():
    change = {"change_type": "added", "title": "New reporting rule", "review_required": False}
    guarded = _guard_removed_change(change, [{"page": 1, "text": "New reporting rule."}])
    assert guarded == change
'@

$tests | & $python -
if ($LASTEXITCODE -ne 0) { throw 'Could not create removal-guard tests.' }

$testPath = '.\tests\test_removed_change_guard.py'
Set-Content -Path $testPath -Value $tests -Encoding UTF8

Write-Host "`nRunning compile check and full test suite..." -ForegroundColor Cyan
& $python -m compileall -q app tests
if ($LASTEXITCODE -ne 0) { throw 'Python compilation failed.' }
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed. Backup: $backup" }

Write-Host "`nREMOVAL VERIFICATION GUARD AND TESTS PASSED." -ForegroundColor Green
Write-Host "Backup: $backup"

# Restart only the known Policy Intelligence Uvicorn listener on port 8001,
# then wait for the patched service to report healthy.
$listener = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    $ownerIds = $listener | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($ownerId in $ownerIds) {
        $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerId" -ErrorAction SilentlyContinue
        $commandLine = [string]$processInfo.CommandLine
        if ($commandLine -notmatch '(?i)uvicorn.*app\.main:app' -or $commandLine -notmatch '(?i)--port\s+8001') {
            throw "Port 8001 is owned by PID $ownerId, but it is not the expected Policy Intelligence Uvicorn command. No process was terminated."
        }
        Stop-Process -Id $ownerId -Force
    }
    Start-Sleep -Seconds 2
}

$stdout = Join-Path (Get-Location).Path 'uvicorn-8001.log'
$stderr = Join-Path (Get-Location).Path 'uvicorn-8001-error.log'
Start-Process -FilePath (Resolve-Path $python).Path `
    -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8001') `
    -WorkingDirectory (Get-Location).Path `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr | Out-Null

$healthy = $false
$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $deadline -and -not $healthy) {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8001/health' -Method Get -TimeoutSec 3
        if ($health.status -eq 'ok') { $healthy = $true }
    } catch {}
}
if (-not $healthy) {
    if (Test-Path $stderr) { Get-Content $stderr -Tail 60 }
    throw 'The removal guard passed tests, but the patched backend did not become healthy on port 8001.'
}
Write-Host "Patched backend restarted and healthy at http://127.0.0.1:8001" -ForegroundColor Green
