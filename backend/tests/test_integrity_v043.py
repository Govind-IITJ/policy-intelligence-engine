from app.services.analysis_service import (
    _build_final_action_checklist,
    _neutralize_unsupported_explanation,
    _page_has_text,
    _possible_excerpt_context_warnings,
)


def _doc(role, page_text="Source clause text."):
    return {
        "version": role,
        "page_count": 1,
        "pages": [{"page": 1, "text": page_text}],
    }


def test_unsupported_frequency_claim_is_neutralized():
    change = {
        "title": "Introduction of trimester-based payment cycles for UTs",
        "change_type": "added",
        "old_quote": "",
        "new_quote": "UT Government in a particular 4-month period / trimester, shall be entitled to receive",
        "explanation": "The change shifts annual disbursement to quarterly payments, four times per year.",
        "confidence": "high",
        "review_required": False,
    }
    warnings = ["The explanation states a reporting frequency not supported by the source wording: 4 times per year."]

    _neutralize_unsupported_explanation(change, warnings)

    assert "quarterly" not in change["explanation"].casefold()
    assert "four times" not in change["explanation"].casefold()
    assert change["title"] == "UT payment-period provision (interpretation unverified)"
    assert change["explanation_validation"]["status"] == "unsupported_claims_neutralized"
    assert change["review_required"] is True
    assert change["confidence"] == "low"


def test_unsupported_date_claim_is_neutralized_for_one_sided_eligibility_candidate():
    change = {
        "title": "Eligibility cut-off date and reassessment procedure clarified",
        "change_type": "added",
        "old_quote": "",
        "new_quote": "eligibility of the family under PM-KISAN - If the family is no longer eligible,",
        "explanation": "The excerpt establishes the cut-off date 01.02.2019.",
        "confidence": "medium",
        "review_required": False,
    }
    warnings = ["Numerical claims not found in the cited source text: 1.02, 2019"]

    _neutralize_unsupported_explanation(change, warnings)

    assert "01.02.2019" not in change["explanation"]
    assert change["title"] == "Family eligibility provision (date interpretation unverified)"
    assert change["explanation_validation"]["human_review_required"] is True


def test_short_non_terminated_quote_is_flagged_as_possible_fragment():
    change = {
        "old_quote": "",
        "new_quote": "01.12.2018 till 01.02.2019 shall be eligible for the benefits from the date of entry of land",
    }
    warnings = _possible_excerpt_context_warnings(change)
    assert len(warnings) == 1
    assert "new quotation" in warnings[0]


def test_final_actions_are_rebuilt_only_from_retained_findings_and_linked():
    earlier = _doc("earlier")
    later = _doc("later")
    findings = [
        {
            "change_id": "CHG-001",
            "title": "Potential addition",
            "change_type": "added",
            "new_page": 1,
            "new_evidence_verified": True,
            "pairing_verified": False,
            "practical_action": "Review the corresponding earlier section before acting.",
            "review_required": True,
        },
        {
            "change_id": "CHG-002",
            "title": "Possible modification",
            "change_type": "modified",
            "new_page": 1,
            "new_evidence_verified": True,
            "pairing_verified": True,
            "practical_action": "Compare the complete corresponding provisions.",
            "review_required": True,
        },
    ]

    actions = _build_final_action_checklist(findings, earlier, later)

    assert len(actions) == 2
    assert [item["change_id"] for item in actions] == ["CHG-001", "CHG-002"]
    assert all(item["review_required"] is True for item in actions)
    assert all(item["source_verified"] is True for item in actions)
    assert "complete earlier and later provisions" in actions[0]["action"].casefold()
    assert all("filename" not in item["source_document"] for item in actions)


def test_action_source_is_not_verified_when_quote_is_not_verified():
    actions = _build_final_action_checklist(
        [{
            "change_id": "CHG-009",
            "title": "Unverified",
            "change_type": "added",
            "new_page": 1,
            "new_evidence_verified": False,
            "pairing_verified": False,
            "review_required": True,
        }],
        _doc("earlier"),
        _doc("later"),
    )
    assert actions[0]["source_verified"] is False
    assert "verify the quoted source" in actions[0]["action"].casefold()


def test_page_has_text_rejects_invalid_or_empty_pages():
    assert _page_has_text(_doc("later"), 1) is True
    assert _page_has_text(_doc("later", "   "), 1) is False
    assert _page_has_text(_doc("later"), 0) is False
    assert _page_has_text(_doc("later"), True) is False


def test_analysis_rebuilds_actions_after_suppression_and_neutralizes_unsupported_date(tmp_path, monkeypatch):
    from app import database
    from app.config import settings
    from app.models import ActionDraft, ChangeDraft, ComparisonDraft
    from app.services import analysis_service

    def make_document(document_id, version, text, sha):
        return {
            "document_id": document_id,
            "filename": f"{version}.pdf",
            "stored_path": f"{document_id}.pdf",
            "version": version,
            "title": "Test policy",
            "page_count": 1,
            "extracted_characters": len(text),
            "pages": [{"page": 1, "text": text, "character_count": len(text), "has_text": True}],
            "created_at": database.utc_now(),
            "sha256": sha,
            "file_size_bytes": 100,
            "nonempty_pages": 1,
            "empty_pages": [],
            "pdf_metadata": {},
            "warnings": [],
        }

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    database.init_db()
    old_text = "The benefit is payable in three equal installments every four months. Earlier procedural details are listed here."
    new_text = "The benefit is payable in three equal installments every four months. The family is eligible if it meets the prescribed criteria."
    database.insert_document(make_document("old-integrity", "earlier", old_text, "old-integrity-hash"))
    database.insert_document(make_document("new-integrity", "later", new_text, "new-integrity-hash"))

    draft = ComparisonDraft(
        document_title="Test policy",
        executive_summary="The policy changed.",
        key_findings=["Raw AI finding before reconciliation."],
        changes=[
            ChangeDraft(
                title="Installment frequency changed",
                change_type="process",
                old_text="three equal installments every four months",
                new_text="three equal installments every four months",
                explanation="The payment frequency changed.",
                affected_stakeholders=["Beneficiaries"],
                practical_action="Review installment provisions.",
                old_page=1,
                old_quote="three equal installments every four months",
                new_page=1,
                new_quote="three equal installments every four months",
                confidence="medium",
                review_required=True,
            ),
            ChangeDraft(
                title="Eligibility cut-off date introduced",
                change_type="added",
                old_text="",
                new_text="The family is eligible if it meets the prescribed criteria.",
                explanation="The new provision establishes a cutoff date of 01.02.2019.",
                affected_stakeholders=["Families"],
                practical_action="Review the corresponding section in the earlier policy.",
                old_page=None,
                old_quote="",
                new_page=1,
                new_quote="The family is eligible if it meets the prescribed criteria.",
                confidence="high",
                review_required=False,
            ),
        ],
        action_checklist=[
            ActionDraft(
                action="Implement the changed installment schedule.",
                reason="Installment frequency changed.",
                source_document="later",
                source_page=1,
                review_required=False,
            ),
            ActionDraft(
                action="Apply the new cutoff date.",
                reason="Eligibility cutoff introduced.",
                source_document="later",
                source_page=1,
                review_required=False,
            ),
        ],
        limitations=[],
        overall_review_required=False,
    )
    monkeypatch.setattr(analysis_service, "analyse_documents", lambda *args: draft)
    database.insert_analysis("analysis-v043-integrity", "old-integrity", "new-integrity")
    analysis_service.run_analysis_job("analysis-v043-integrity", "old-integrity", "new-integrity")

    saved = database.get_analysis("analysis-v043-integrity")
    assert saved["status"] == "completed"
    result = saved["result"]
    assert len(result["changes"]) == 1
    retained = result["changes"][0]
    assert retained["title"] == "Family eligibility provision (date interpretation unverified)"
    assert retained["explanation_validation"]["status"] == "unsupported_claims_neutralized"
    assert "01.02.2019" not in retained["explanation"]
    assert len(result["suppressed_findings"]) == 1
    assert len(result["action_checklist"]) == 1
    assert result["action_checklist"][0]["change_id"] == retained["change_id"]
    assert "apply the new cutoff" not in result["action_checklist"][0]["action"].casefold()
