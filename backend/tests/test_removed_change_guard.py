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
