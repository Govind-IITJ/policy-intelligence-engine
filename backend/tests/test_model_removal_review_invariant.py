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
        confidence="high",
        review_required=False,
    )


def test_removed_change_cannot_be_marked_review_complete():
    change = _removed_change()
    assert change.review_required is True


def test_comparison_inherits_review_from_removed_change():
    change = _removed_change()
    draft = ComparisonDraft(
        document_title="PMEGP comparison",
        executive_summary="Test comparison",
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
        confidence="high",
        review_required=False,
    )
    assert change.review_required is False


