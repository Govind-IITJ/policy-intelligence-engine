from io import BytesIO

import fitz
import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app.config import settings
from app.services.pdf_service import extract_pdf_bytes, read_and_extract_upload, safe_display_filename


def make_pdf(*texts: str, metadata: dict | None = None, encryption: bool = False) -> bytes:
    doc = fitz.open()
    for text in texts:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    if metadata:
        doc.set_metadata(metadata)
    if encryption:
        data = doc.tobytes(
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner-password",
            user_pw="user-password",
        )
    else:
        data = doc.tobytes()
    doc.close()
    return data


def test_extracts_text_and_one_based_page_numbers():
    result = extract_pdf_bytes(
        make_pdf(
            "Government Policy\nEligibility requirements apply to applicants under the scholarship scheme.",
            "Revised procedure\nApplications must include the required supporting documents.",
        ),
        "policy.pdf",
    )
    assert result["page_count"] == 2
    assert result["nonempty_pages"] == 2
    assert result["pages"][0]["page"] == 1
    assert result["pages"][1]["page"] == 2
    assert "Eligibility requirements" in result["pages"][0]["text"]
    assert "Revised procedure" in result["pages"][1]["text"]
    assert result["extracted_characters"] == sum(p["character_count"] for p in result["pages"])
    assert len(result["sha256"]) == 64
    assert result["file_size_bytes"] > 0


def test_uses_pdf_title_metadata_and_captures_metadata():
    result = extract_pdf_bytes(
        make_pdf(
            "A sufficiently long policy text with enough characters to pass extraction validation.",
            metadata={"title": "Official Scheme Guidelines", "author": "Department of Example"},
        ),
        "source.pdf",
    )
    assert result["title"] == "Official Scheme Guidelines"
    assert result["pdf_metadata"]["author"] == "Department of Example"


def test_falls_back_to_first_page_heading_when_title_missing():
    result = extract_pdf_bytes(
        make_pdf("Revised Scholarship Guidelines\nThis document explains eligibility, deadlines and application process."),
        "source.pdf",
    )
    assert result["title"] == "Revised Scholarship Guidelines"


def test_rejects_non_pdf():
    with pytest.raises(HTTPException) as exc:
        extract_pdf_bytes(b"not a pdf", "bad.pdf")
    assert exc.value.status_code == 400


def test_rejects_empty_pdf_bytes():
    with pytest.raises(HTTPException) as exc:
        extract_pdf_bytes(b"", "empty.pdf")
    assert exc.value.status_code == 400


def test_rejects_password_protected_pdf():
    with pytest.raises(HTTPException) as exc:
        extract_pdf_bytes(make_pdf("This is a sufficiently long text body for this PDF.", encryption=True), "locked.pdf")
    assert exc.value.status_code == 422


def test_rejects_image_only_empty_text_pdf():
    with pytest.raises(HTTPException) as exc:
        extract_pdf_bytes(make_pdf(""), "scan.pdf")
    assert exc.value.status_code == 422


def test_records_empty_pages_as_warning_when_other_pages_have_text():
    result = extract_pdf_bytes(
        make_pdf(
            "This first page contains enough meaningful extracted text for this test to pass.",
            "",
            "This third page contains further text and should retain its original PDF page number.",
        ),
        "mixed.pdf",
    )
    assert result["page_count"] == 3
    assert result["empty_pages"] == [2]
    assert result["pages"][2]["page"] == 3
    assert result["warnings"]


def test_rejects_page_count_above_configured_limit(monkeypatch):
    monkeypatch.setattr(settings, "max_pdf_pages", 1)
    with pytest.raises(HTTPException) as exc:
        extract_pdf_bytes(make_pdf("Page one has enough text to make this PDF readable.", "Page two also has enough text."), "large.pdf")
    assert exc.value.status_code == 413


def test_sanitizes_windows_and_unix_path_filenames():
    assert safe_display_filename(r"C:\\fakepath\\policy.pdf") == "policy.pdf"
    assert safe_display_filename("../../policy.pdf") == "policy.pdf"


@pytest.mark.asyncio
async def test_upload_reader_rejects_wrong_extension():
    upload = UploadFile(filename="policy.docx", file=BytesIO(b"not a pdf"))
    with pytest.raises(HTTPException) as exc:
        await read_and_extract_upload(upload)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_upload_reader_enforces_upload_size(monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    upload = UploadFile(filename="large.pdf", file=BytesIO(b"%PDF-" + b"x" * (1024 * 1024)))
    with pytest.raises(HTTPException) as exc:
        await read_and_extract_upload(upload)
    assert exc.value.status_code == 413
