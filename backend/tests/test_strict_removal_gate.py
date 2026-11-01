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
