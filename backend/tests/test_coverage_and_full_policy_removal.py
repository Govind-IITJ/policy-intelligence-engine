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
