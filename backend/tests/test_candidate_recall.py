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
