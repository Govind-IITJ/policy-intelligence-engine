from app import database
from app.config import settings
from app.models import ComparisonDraft, ChangeDraft, ActionDraft
from app.services import analysis_service


def make_doc(document_id, version, text, sha):
    return {
        "document_id": document_id,
        "filename": f"{version}.pdf",
        "stored_path": f"{document_id}.pdf",
        "version": version,
        "title": "Test Policy",
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


def test_analysis_marks_valid_evidence_and_counts_types(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    database.init_db()
    old_text = "Applicants must have annual family income below INR 200000."
    new_text = "Applicants must have annual family income below INR 300000."
    old = make_doc("old-id", "earlier", old_text, "old-hash")
    new = make_doc("new-id", "later", new_text, "new-hash")
    database.insert_document(old)
    database.insert_document(new)

    draft = ComparisonDraft(
        document_title="Test Policy",
        executive_summary="The income threshold was increased.",
        key_findings=["Income threshold increased."],
        changes=[
            ChangeDraft(
                title="Income threshold increased",
                change_type="eligibility",
                old_text=old_text,
                new_text=new_text,
                explanation="The stated annual income threshold increased from INR 200000 to INR 300000.",
                affected_stakeholders=["Applicants"],
                practical_action="Review the latest eligibility requirements.",
                old_page=1,
                old_quote=old_text,
                new_page=1,
                new_quote=new_text,
                confidence="high",
                review_required=False,
            )
        ],
        action_checklist=[
            ActionDraft(action="Review the latest eligibility criteria", reason="The threshold changed.",
                        source_document="later", source_page=1, review_required=False)
        ],
        limitations=[],
        overall_review_required=False,
    )
    monkeypatch.setattr(analysis_service, "analyse_documents", lambda *args: draft)

    analysis_id = "analysis-test"
    database.insert_analysis(analysis_id, "old-id", "new-id")
    analysis_service.run_analysis_job(analysis_id, "old-id", "new-id")

    saved = database.get_analysis(analysis_id)
    assert saved["status"] == "completed"
    change = saved["result"]["changes"][0]
    assert change["evidence_verified"] is True
    assert change["evidence_status"] == "both_source_quotes_matched"
    assert change["source_quote_verified"] is True
    assert change["both_sides_verified"] is True
    assert saved["result"]["counts"]["source_quotes_verified"] == 1
    assert saved["result"]["counts"]["both_sides_verified"] == 1
    assert saved["result"]["counts"]["interpretation_verified"] == 0
    assert saved["result"]["counts"]["by_type"]["eligibility"] == 1
    assert saved["result"]["comparison_metadata"]["candidate_count"] >= 1


def test_analysis_flags_missing_required_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    database.init_db()
    old_text = "Applicants must submit the form before 30 June 2025."
    new_text = "Applicants must submit the form before 31 July 2025."
    database.insert_document(make_doc("old-id", "earlier", old_text, "old-hash"))
    database.insert_document(make_doc("new-id", "later", new_text, "new-hash"))

    draft = ComparisonDraft(
        document_title="Test Policy", executive_summary="A date may have changed.", key_findings=[],
        changes=[ChangeDraft(
            title="Deadline changed", change_type="deadline", old_text=old_text, new_text=new_text,
            explanation="The deadline changed.", affected_stakeholders=["Applicants"], practical_action="Check the date.",
            old_page=1, old_quote="", new_page=1, new_quote=new_text, confidence="low", review_required=False,
        )],
        action_checklist=[], limitations=[], overall_review_required=False,
    )
    monkeypatch.setattr(analysis_service, "analyse_documents", lambda *args: draft)
    database.insert_analysis("analysis-test-2", "old-id", "new-id")
    analysis_service.run_analysis_job("analysis-test-2", "old-id", "new-id")

    saved = database.get_analysis("analysis-test-2")
    change = saved["result"]["changes"][0]
    assert change["evidence_verified"] is False
    assert change["review_required"] is True
    assert saved["result"]["overall_review_required"] is True


def test_identical_file_hash_skips_ai_and_completes_with_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    database.init_db()
    text = "This is the same exact policy text in both uploaded document versions."
    database.insert_document(make_doc("old-id", "earlier", text, "same-hash"))
    database.insert_document(make_doc("new-id", "later", text, "same-hash"))
    monkeypatch.setattr(analysis_service, "analyse_documents", lambda *args: (_ for _ in ()).throw(AssertionError("AI should not run")))
    database.insert_analysis("analysis-identical", "old-id", "new-id")
    analysis_service.run_analysis_job("analysis-identical", "old-id", "new-id")
    saved = database.get_analysis("analysis-identical")
    assert saved["status"] == "completed"
    assert saved["result"]["counts"]["total"] == 0
    assert saved["result"]["overall_review_required"] is True


def test_ai_action_without_a_retained_finding_is_discarded(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    database.init_db()
    old_text = "The authority published the earlier procedure for applicants."
    new_text = "The authority published the revised procedure for applicants."
    database.insert_document(make_doc("old-id", "earlier", old_text, "old-hash"))
    database.insert_document(make_doc("new-id", "later", new_text, "new-hash"))

    draft = ComparisonDraft(
        document_title="Test Policy", executive_summary="A procedure changed.", key_findings=[], changes=[],
        action_checklist=[ActionDraft(
            action="Review the revised procedure", reason="The process changed.",
            source_document="later", source_page=9, review_required=False,
        )],
        limitations=[], overall_review_required=False,
    )
    monkeypatch.setattr(analysis_service, "analyse_documents", lambda *args: draft)
    database.insert_analysis("analysis-invalid-action", "old-id", "new-id")
    analysis_service.run_analysis_job("analysis-invalid-action", "old-id", "new-id")

    saved = database.get_analysis("analysis-invalid-action")
    # The AI checklist is no longer trusted as an independent action source.
    # Actions must be rebuilt from retained findings and carry a change_id.
    assert saved["result"]["action_checklist"] == []
