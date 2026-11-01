from fastapi.testclient import TestClient
import fitz

from app.config import settings
from app.main import app
from app.models import ActionDraft, ChangeDraft, ComparisonDraft
from app.services import analysis_service


def make_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_compare_endpoint_returns_analysis_and_verified_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    old_text = "Applicants must have annual family income below INR 200000."
    new_text = "Applicants must have annual family income below INR 300000."

    draft = ComparisonDraft(
        document_title="Scholarship Guidelines",
        executive_summary="The stated income threshold changed.",
        key_findings=["The income threshold increased from INR 200000 to INR 300000."],
        changes=[ChangeDraft(
            title="Income threshold modified", change_type="eligibility",
            old_text=old_text, new_text=new_text,
            explanation="The annual income threshold increased.",
            affected_stakeholders=["Scholarship applicants"],
            practical_action="Review the latest eligibility requirements.",
            old_page=1, old_quote=old_text, new_page=1, new_quote=new_text,
            confidence="high", review_required=False,
        )],
        action_checklist=[ActionDraft(
            action="Review the latest eligibility requirements.",
            reason="The income threshold changed.", source_document="later",
            source_page=1, review_required=False,
        )],
        limitations=[], overall_review_required=False,
    )
    monkeypatch.setattr(analysis_service, "analyse_documents", lambda *args: draft)

    with TestClient(app) as client:
        old_upload = client.post(
            "/api/documents/upload",
            data={"version": "earlier"},
            files={"file": ("earlier.pdf", make_pdf(old_text), "application/pdf")},
        )
        new_upload = client.post(
            "/api/documents/upload",
            data={"version": "later"},
            files={"file": ("later.pdf", make_pdf(new_text), "application/pdf")},
        )
        assert old_upload.status_code == 201
        assert new_upload.status_code == 201

        started = client.post("/api/documents/compare", json={
            "earlier_document_id": old_upload.json()["document_id"],
            "later_document_id": new_upload.json()["document_id"],
        })
        assert started.status_code == 202
        analysis_id = started.json()["analysis_id"]

        status = client.get(f"/api/analysis/{analysis_id}")
        assert status.status_code == 200
        assert status.json()["status"] == "completed"
        change = status.json()["result"]["changes"][0]
        assert change["change_id"] == "CHG-001"
        assert change["evidence_verified"] is True
        assert change["old_page"] == 1
        assert change["new_page"] == 1

        changes = client.get(f"/api/analysis/{analysis_id}/changes")
        assert changes.status_code == 200
        assert changes.json()["counts"]["total"] == 1
