$ErrorActionPreference = "Stop"
Set-Location "C:\Users\Govind\Downloads\Policy_Intelligence_Phase1_Backend\policy-intelligence-backend"

$python = Join-Path $PWD ".venv\Scripts\python.exe"
$servicePath = ".\app\services\analysis_service.py"
$runner = ".\Run_PMEGP_Recall_Acceptance_v2.ps1"
if (-not (Test-Path $python)) { throw "Virtualenv Python not found." }
if (-not (Test-Path $servicePath)) { throw "Missing analysis_service.py." }
if (-not (Test-Path $runner)) { throw "Missing PMEGP acceptance runner." }

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = ".\backup-persistence-review-gate-$stamp"
New-Item -ItemType Directory -Path $backup | Out-Null
Copy-Item $servicePath $backup
Write-Host "Backup created: $backup" -ForegroundColor Green

$patch = @'
import ast
from pathlib import Path

path = Path("app/services/analysis_service.py")
source = path.read_text(encoding="utf-8-sig")

if "def _enforce_persisted_review_invariants(" in source:
    raise SystemExit("Persistence review guard already exists. No duplicate patch applied.")

tree = ast.parse(source)
calls = [
    node for node in ast.walk(tree)
    if isinstance(node, ast.Call)
    and isinstance(node.func, ast.Attribute)
    and node.func.attr == "update_analysis_completed"
]
if not calls:
    raise SystemExit("No update_analysis_completed() call found in analysis_service.py. No changes written.")

encoded = source.encode("utf-8")
byte_offsets = [0]
for line in source.splitlines(True):
    byte_offsets.append(byte_offsets[-1] + len(line.encode("utf-8")))

replacements = []
preferred_names = {"result", "result_json", "result_data", "payload", "analysis_result", "comparison"}
for call in calls:
    candidate = None
    for kw in call.keywords:
        if kw.arg in preferred_names:
            candidate = kw.value
            break
    if candidate is None and call.args:
        candidate = call.args[-1]
    if candidate is None:
        raise SystemExit("Completion call has no identifiable payload argument.")
    segment = ast.get_source_segment(source, candidate)
    if not segment:
        raise SystemExit("Could not recover persistence payload expression.")
    start = byte_offsets[candidate.lineno - 1] + candidate.col_offset
    end = byte_offsets[candidate.end_lineno - 1] + candidate.end_col_offset
    wrapped = ("_enforce_persisted_review_invariants(" + segment + ")").encode("utf-8")
    replacements.append((start, end, wrapped))
    print("Wrapping persisted payload:", segment[:160].replace("\n", " "))

for start, end, replacement in sorted(replacements, reverse=True):
    encoded = encoded[:start] + replacement + encoded[end:]
source = encoded.decode("utf-8")

helper = r"""
def _enforce_persisted_review_invariants(payload):
    import json

    was_json_text = isinstance(payload, str)
    if was_json_text:
        try:
            data = json.loads(payload)
        except Exception:
            return payload
    elif hasattr(payload, "model_dump"):
        data = payload.model_dump()
    else:
        data = payload

    if not isinstance(data, (dict, list)):
        return payload

    containers = []
    seen = set()

    def visit(value):
        marker = id(value)
        if marker in seen:
            return
        if isinstance(value, dict):
            seen.add(marker)
            changes = value.get("changes")
            if isinstance(changes, list) and any(isinstance(item, dict) for item in changes):
                containers.append(value)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(value, list):
            seen.add(marker)
            for child in value:
                if isinstance(child, (dict, list)):
                    visit(child)

    visit(data)
    if not containers:
        return payload

    for container in containers:
        changes = container.get("changes") or []
        for change in changes:
            if not isinstance(change, dict):
                continue
            if str(change.get("change_type", "")).casefold() == "removed":
                change["review_required"] = True
                note = (
                    "Automated removal is not proof of repeal. A human reviewer must "
                    "compare the complete later policy, including renumbered clauses, "
                    "annexes and related provisions, before treating this as removed."
                )
                existing = str(change.get("evidence_warning") or "").strip()
                if note not in existing:
                    change["evidence_warning"] = (existing + " " if existing else "") + note
                change["removal_verification"] = {
                    "status": "human_review_required",
                    "confirmed_repeal": False,
                }

        required = sum(
            1 for item in changes
            if isinstance(item, dict) and bool(item.get("review_required"))
        )
        counts = container.get("counts")
        if not isinstance(counts, dict):
            counts = {}
            container["counts"] = counts
        counts["needs_review"] = required
        if required or any(
            isinstance(item, dict) and item.get("change_type") == "removed"
            for item in changes
        ):
            container["overall_review_required"] = True

    if was_json_text:
        return json.dumps(data, ensure_ascii=False)
    return data
"""
source = source.rstrip() + "\n\n" + helper.lstrip() + "\n"
ast.parse(source)
path.write_text(source, encoding="utf-8")
print(f"Patched {len(replacements)} completion payload call(s).")
'@

$patch | & $python -
if ($LASTEXITCODE -ne 0) { throw "Persistence-boundary patch failed. Backup: $backup" }

$test = @'
from app.services.analysis_service import _enforce_persisted_review_invariants


def test_persisted_payload_forces_all_removals_to_review():
    payload = {
        "changes": [
            {"change_type": "removed", "review_required": False},
            {"change_type": "added", "review_required": False},
            {"change_type": "removed", "review_required": False},
        ],
        "counts": {"total": 3, "needs_review": 0},
        "overall_review_required": False,
    }
    result = _enforce_persisted_review_invariants(payload)
    assert result["changes"][0]["review_required"] is True
    assert result["changes"][1]["review_required"] is False
    assert result["changes"][2]["review_required"] is True
    assert result["counts"]["needs_review"] == 2
    assert result["overall_review_required"] is True
    assert result["changes"][0]["removal_verification"]["confirmed_repeal"] is False


def test_persisted_payload_guard_handles_json_text():
    import json
    payload = {
        "result": {
            "changes": [{"change_type": "removed", "review_required": False}],
            "counts": {"needs_review": 0},
            "overall_review_required": False,
        }
    }
    result = _enforce_persisted_review_invariants(json.dumps(payload))
    decoded = json.loads(result)
    inner = decoded["result"]
    assert inner["changes"][0]["review_required"] is True
    assert inner["counts"]["needs_review"] == 1
    assert inner["overall_review_required"] is True
'@
Set-Content -Path ".\tests\test_persisted_review_invariants.py" -Value $test -Encoding UTF8

Write-Host "`nRunning compile check and full tests..." -ForegroundColor Cyan
& $python -m compileall -q app tests
if ($LASTEXITCODE -ne 0) { throw "Compilation failed. Backup: $backup" }
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed. Backend was not restarted. Backup: $backup" }

Write-Host "`nPERSISTENCE-BOUNDARY PATCH AND TESTS PASSED." -ForegroundColor Green

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
        $h = Invoke-RestMethod "http://127.0.0.1:8001/health" -UseBasicParsing -TimeoutSec 3
        if ($h.status -eq "ok") { $healthy = $true }
    } catch {}
}
if (-not $healthy) {
    Get-Content ".\uvicorn-8001-error.log" -Tail 60 -ErrorAction SilentlyContinue
    throw "Backend failed to become healthy on port 8001."
}
Write-Host "Backend healthy on port 8001." -ForegroundColor Green

Write-Host "`nRunning real PMEGP acceptance..." -ForegroundColor Cyan
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runner
if ($LASTEXITCODE -ne 0) { throw "PMEGP Udyam gate failed." }

$outDir = ".\sample_requests\pmegp_official"
$latest = Get-ChildItem $outDir -Filter "PMEGP_Recall_Acceptance_*.json" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $latest) { throw "No PMEGP result JSON found." }
$full = Get-Content $latest.FullName -Raw | ConvertFrom-Json
$result = $full.result
if ($null -eq $result) { throw "Latest result JSON missing result payload." }

$changes = @($result.changes)
$removals = @($changes | Where-Object { $_.change_type -eq "removed" })
$unreviewed = @($removals | Where-Object { $_.review_required -ne $true })
$reviewCount = @($changes | Where-Object { $_.review_required -eq $true }).Count
$reported = [int]$result.counts.needs_review

Write-Host "`n========== PERSISTED RESULT ACCEPTANCE ==========" -ForegroundColor Cyan
Write-Host "Findings: $($changes.Count)"
Write-Host "Removal findings: $($removals.Count)"
Write-Host "Unreviewed removals: $($unreviewed.Count)"
Write-Host "Review flags: $reviewCount"
Write-Host "Reported needs_review: $reported"
Write-Host "Overall review required: $($result.overall_review_required)"
Write-Host "JSON: $($latest.FullName)"

if ($unreviewed.Count -gt 0) { throw "FAIL: a persisted removal is not review-required." }
if ($reported -ne $reviewCount) { throw "FAIL: needs_review count mismatch." }
if ($reviewCount -gt 0 -and $result.overall_review_required -ne $true) {
    throw "FAIL: overall review flag did not propagate."
}
Write-Host "`nPERSISTED REVIEW-SAFETY ACCEPTANCE PASSED." -ForegroundColor Green
Write-Host "Note: this flags removal claims for human review; it does not prove legal repeal." -ForegroundColor Yellow
