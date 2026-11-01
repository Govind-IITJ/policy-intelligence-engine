$ErrorActionPreference = 'Stop'

$root = (Get-Location).Path
$required = @(
    '.\app\services\ai_service.py',
    '.\app\services\diff_service.py'
)
foreach ($file in $required) {
    if (-not (Test-Path $file)) {
        throw "Missing $file. Run this script from the policy-intelligence-backend directory."
    }
}

$python = '.\.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }

$backup = ".\backup-candidate-recall-$(Get-Date -Format yyyyMMdd-HHmmss)"
New-Item -ItemType Directory -Path $backup | Out-Null
Copy-Item '.\app\services\ai_service.py' $backup
Copy-Item '.\app\services\diff_service.py' $backup
if (Test-Path '.\tests') { Copy-Item '.\tests' (Join-Path $backup 'tests') -Recurse }
Write-Host "Backup created: $backup" -ForegroundColor Green

$patch = @'
from pathlib import Path
import re

root = Path.cwd()
ai_path = root / "app/services/ai_service.py"
diff_path = root / "app/services/diff_service.py"
ai = ai_path.read_text(encoding="utf-8-sig")
diff = diff_path.read_text(encoding="utf-8-sig")

# Replace only the ranking/selection helpers. Keep the existing compact model
# schema, evidence assembly, provider integrations, and response validation.
replacement = r'''_CANDIDATE_SIGNAL_WEIGHTS = (
    ("udyam", 90),
    ("mandatory", 34),
    ("compulsory", 32),
    ("voluntary", 28),
    ("physical verification", 24),
    ("margin money adjustment", 22),
    ("beneficiary loan account", 18),
    ("registration", 18),
    ("register", 14),
    ("eligibility", 16),
    ("ineligible", 16),
    ("eligible", 12),
    ("shall", 10),
    ("must", 10),
    ("required", 10),
    ("requirement", 10),
    ("before", 6),
    ("deadline", 16),
    ("last date", 16),
    ("fee", 12),
    ("no fee", 15),
    ("subsidy", 10),
    ("margin money", 10),
    ("project cost", 10),
    ("maximum", 7),
    ("minimum", 7),
    ("ceiling", 7),
    ("disbursement", 8),
    ("verification", 7),
    ("approval", 7),
    ("document", 5),
)


def _candidate_score(candidate: dict[str, Any]) -> int:
    """Score policy significance, not page novelty or formatting differences."""
    old_text = str(candidate.get("old_text") or "").casefold()
    new_text = str(candidate.get("new_text") or "").casefold()
    combined = old_text + " " + new_text
    score = 0

    for term, weight in _CANDIDATE_SIGNAL_WEIGHTS:
        pattern = r"(?<![a-z0-9])" + re.escape(term).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
        if re.search(pattern, combined, flags=re.IGNORECASE):
            score += weight

    # Explicit policy-strengthening transitions receive the strongest boost.
    old_is_voluntary = bool(re.search(r"\b(voluntary|optional|may)\b", old_text))
    new_is_mandatory = bool(re.search(r"\b(mandatory|compulsory|required|must|shall)\b", new_text))
    if old_is_voluntary and new_is_mandatory:
        score += 60

    if "udyam" in combined and "registration" in combined:
        score += 45
    if "udyam" in combined and "physical verification" in combined:
        score += 35
    if "margin money" in combined and re.search(r"\b(before|prior to)\b", new_text):
        score += 18

    if re.search(r"\d", combined):
        score += 4
    if candidate.get("operation") in ("added", "removed"):
        score += 2
    if isinstance(candidate.get("old_page"), int):
        score += 1
    if isinstance(candidate.get("new_page"), int):
        score += 1

    # Very short fragments are often clause-number or PDF line-wrap noise.
    meaningful_chars = len(re.sub(r"[^a-z]", "", combined))
    if meaningful_chars < 24 and not re.search(r"\budyam\b", combined):
        score -= 18

    return score


def _select_candidates(
    candidates: list[dict[str, Any]],
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Select the highest-signal policy deltas with deterministic tie-breaking.

    Earlier versions selected one candidate per new page before filling the
    remaining slots. That let low-value page-layout noise displace a material
    obligation change. This selector ranks semantic signals first and uses
    stable source order only as a tie-breaker.
    """
    if not candidates or limit <= 0:
        return []

    ranked = sorted(
        enumerate(candidates),
        key=lambda item: (-_candidate_score(item[1]), item[0]),
    )

    selected = []
    seen = set()
    for _, candidate in ranked:
        old_text = re.sub(r"\s+", " ", str(candidate.get("old_text") or "").casefold()).strip()
        new_text = re.sub(r"\s+", " ", str(candidate.get("new_text") or "").casefold()).strip()
        fingerprint = (
            candidate.get("operation"),
            candidate.get("old_page"),
            candidate.get("new_page"),
            old_text[:220],
            new_text[:220],
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        selected.append(candidate)
        if len(selected) >= limit:
            break

    return selected
'''

pattern = re.compile(r"(?ms)^def _candidate_score\(.*?(?=^def _build_compact_input\()")
match = pattern.search(ai)
if not match:
    raise SystemExit(
        "Could not locate the compact selector block (expected _candidate_score "
        "followed by _build_compact_input). No source changes were written."
    )
ai = ai[:match.start()] + replacement + "\n\n" + ai[match.end():]

# Expand the compact input from six to twelve candidates. The response remains
# compact; this changes input recall, not the number of findings returned.
ai, call_count = re.subn(
    r"_select_candidates\(all_candidates,\s*limit\s*=\s*6\)",
    "_select_candidates(all_candidates, limit=12)",
    ai,
    count=1,
)
if call_count != 1:
    # Handle positional/default-style variants without broad text replacement.
    ai, call_count = re.subn(
        r"_select_candidates\(all_candidates,\s*6\)",
        "_select_candidates(all_candidates, 12)",
        ai,
        count=1,
    )
if call_count != 1:
    raise SystemExit(
        "Selector helper was replaced, but the expected six-candidate call was "
        "not found. No files were written; inspect _build_compact_input."
    )

# Retain the complete detected pool for large comparisons rather than silently
# stopping at the previous 500-candidate default.
cap_match = re.search(r"(max_candidates\s*:\s*int\s*=\s*)(\d+)", diff)
if not cap_match:
    raise SystemExit(
        "Could not locate build_deterministic_diff max_candidates parameter. "
        "No files were written."
    )
if int(cap_match.group(2)) < 2500:
    diff = (
        diff[:cap_match.start(2)]
        + "2500"
        + diff[cap_match.end(2):]
    )

# Write changes after all structural checks have succeeded.
ai_path.write_text(ai, encoding="utf-8")
diff_path.write_text(diff, encoding="utf-8")
print("Updated AI candidate ranking: high-impact policy terms and obligation transitions now rank first.")
print("Expanded compact model candidate input: 6 -> 12.")
print("Raised deterministic candidate retention cap to at least 2500.")
'@

$patch | & $python -
if ($LASTEXITCODE -ne 0) { throw 'Candidate-recall source patch failed. Original files are preserved in the backup folder.' }

$tests = @'
from app.services.ai_service import _candidate_score, _select_candidates
from app.services.diff_service import build_deterministic_diff


def test_udyam_mandatory_transition_beats_generic_page_noise():
    noise = [
        {
            "operation": "modified",
            "old_page": i + 1,
            "new_page": i + 1,
            "old_text": f"The committee meeting details and administrative note number {i} are listed here.",
            "new_text": f"The committee meeting details and administrative note number {i + 1} are listed here.",
        }
        for i in range(40)
    ]
    udyam = {
        "operation": "modified",
        "old_page": 8,
        "new_page": 8,
        "old_text": "Udyam registration was voluntary for new units before physical verification.",
        "new_text": "All new units must complete mandatory Udyam registration before physical verification and adjustment of Margin Money in the beneficiary loan account.",
    }
    selected = _select_candidates(noise + [udyam], limit=12)
    assert udyam in selected
    assert _candidate_score(udyam) > max(_candidate_score(item) for item in noise)


def test_old_voluntary_to_new_mandatory_transition_gets_priority():
    transition = {
        "operation": "modified",
        "old_page": 3,
        "new_page": 3,
        "old_text": "Registration on the portal is voluntary.",
        "new_text": "Registration on the portal is mandatory and must be completed before verification.",
    }
    generic = {
        "operation": "modified",
        "old_page": 4,
        "new_page": 4,
        "old_text": "The financing bank shall process the claim after receipt.",
        "new_text": "The financing bank shall process the claim after receipt by the branch.",
    }
    assert _candidate_score(transition) > _candidate_score(generic)
    assert _select_candidates([generic, transition], limit=1) == [transition]


def test_duplicate_candidate_is_not_sent_twice():
    candidate = {
        "operation": "added",
        "old_page": None,
        "new_page": 12,
        "old_text": "",
        "new_text": "Udyam registration is mandatory before Margin Money adjustment.",
    }
    duplicate = dict(candidate)
    selected = _select_candidates([candidate, duplicate], limit=12)
    assert selected == [candidate]


def test_default_diff_retains_more_than_previous_500_candidate_limit():
    text = "\n".join(
        f"New administrative provision number {i} specifies a distinct operational condition for implementation"
        for i in range(520)
    )
    diff = build_deterministic_diff(
        [{"page": 1, "text": ""}],
        [{"page": 1, "text": text}],
    )
    assert diff["total_candidate_count"] >= 520
    assert diff["candidate_count"] >= 520
    assert diff["candidates_truncated"] is False
'@

$testPath = '.\tests\test_candidate_recall.py'
if (-not (Test-Path '.\tests')) { New-Item -ItemType Directory '.\tests' | Out-Null }
$tests | Set-Content -Path $testPath -Encoding UTF8

Write-Host "`nRunning compile check and full test suite..." -ForegroundColor Cyan
& $python -m compileall -q app tests
if ($LASTEXITCODE -ne 0) { throw 'Python compile check failed. Review the backup and error output.' }
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Test suite failed. Preserve the output and backup; do not treat this patch as accepted.' }

Write-Host "`nCANDIDATE RECALL PATCH AND TESTS PASSED." -ForegroundColor Green
Write-Host "Backup: $backup" -ForegroundColor DarkGreen
