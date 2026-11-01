from fastapi.testclient import TestClient
import fitz

from app.config import settings
from app.main import app


def make_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_upload_list_document_and_page_preview(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    pdf_bytes = make_pdf(
        "Official Policy Guidelines\nThis page contains a sufficiently long extractable text passage "
        "for testing the document ingestion API and page text preservation."
    )

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200

        uploaded = client.post(
            "/api/documents/upload",
            data={"version": "earlier"},
            files={"file": (r"C:\\fakepath\\policy.pdf", pdf_bytes, "application/pdf")},
        )
        assert uploaded.status_code == 201, uploaded.text
        response = uploaded.json()
        assert response["filename"] == "policy.pdf"
        assert response["version"] == "earlier"
        assert response["page_count"] == 1
        assert response["file_size_bytes"] == len(pdf_bytes)
        assert len(response["sha256"]) == 64

        document_id = response["document_id"]
        listed = client.get("/api/documents")
        assert listed.status_code == 200
        assert any(item["document_id"] == document_id for item in listed.json())

        detail = client.get(f"/api/documents/{document_id}")
        assert detail.status_code == 200
        assert "pages" not in detail.json()  # page text is exposed through the bounded page endpoint

        page = client.get(f"/api/documents/{document_id}/pages/1")
        assert page.status_code == 200
        assert "Official Policy Guidelines" in page.json()["text"]

        bad_page = client.get(f"/api/documents/{document_id}/pages/2")
        assert bad_page.status_code == 404


def test_upload_rejects_non_pdf_and_unknown_document(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    with TestClient(app) as client:
        bad = client.post(
            "/api/documents/upload",
            data={"version": "earlier"},
            files={"file": ("notes.txt", b"plain text", "text/plain")},
        )
        assert bad.status_code == 400
        missing = client.get("/api/documents/not-a-real-id")
        assert missing.status_code == 404
