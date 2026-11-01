"""PDF ingestion and page-preserving text extraction."""

from __future__ import annotations

from hashlib import sha256
from pathlib import PurePosixPath
import re
from typing import Any

import fitz
from fastapi import HTTPException, UploadFile

from app.config import settings


def safe_display_filename(filename: str | None) -> str:
    """Return a display-only basename; uploaded bytes are stored under UUID names."""
    raw = (filename or "document.pdf").replace("\\", "/")
    name = PurePosixPath(raw).name
    name = "".join(ch for ch in name if ch.isprintable() and ch not in "\x00")
    return name[:180] or "document.pdf"


def _clean_page_text(text: str) -> str:
    text = text.replace("\x00", " ").replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    # Preserve paragraph boundaries while removing empty runs at page edges.
    cleaned = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", cleaned)


def _pdf_title(metadata: dict[str, Any], pages: list[dict[str, Any]], filename: str) -> str:
    title = str(metadata.get("title") or "").strip()
    if title:
        return title[:240]
    first_page = next((p["text"] for p in pages if p["text"]), "")
    first_line = next((line.strip() for line in first_page.splitlines() if line.strip()), "")
    return (first_line or PurePosixPath(safe_display_filename(filename)).stem or "Untitled PDF")[:240]


def extract_pdf_bytes(data: bytes, filename: str) -> dict[str, Any]:
    """Validate a PDF and extract text while preserving 1-based PDF page numbers."""
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    # Some otherwise valid PDFs contain a small preamble before the header.
    if b"%PDF-" not in data[:1024]:
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid PDF.")

    try:
        pdf = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Could not open this PDF. It may be damaged, unsupported or password-protected.",
        ) from exc

    try:
        if pdf.needs_pass:
            raise HTTPException(
                status_code=422,
                detail="This PDF is password-protected. Upload an unlocked official copy.",
            )

        page_count = pdf.page_count
        if page_count == 0:
            raise HTTPException(status_code=400, detail="The PDF contains no pages.")
        if page_count > settings.max_pdf_pages:
            raise HTTPException(
                status_code=413,
                detail=f"PDF has {page_count} pages; the limit is {settings.max_pdf_pages} pages.",
            )

        pages: list[dict[str, Any]] = []
        total_chars = 0
        nonempty_pages = 0
        empty_pages: list[int] = []

        for index, page in enumerate(pdf):
            text = _clean_page_text(page.get_text("text", sort=True))
            char_count = len(text)
            total_chars += char_count
            if text:
                nonempty_pages += 1
            else:
                empty_pages.append(index + 1)
            rect = page.rect
            pages.append(
                {
                    "page": index + 1,
                    "text": text,
                    "character_count": char_count,
                    "has_text": bool(text),
                    "width_points": round(float(rect.width), 2),
                    "height_points": round(float(rect.height), 2),
                }
            )

        if total_chars < 40 or nonempty_pages == 0:
            raise HTTPException(
                status_code=422,
                detail=(
                    "This PDF appears to be scanned or image-only, or contains too little extractable text. "
                    "OCR is not enabled in this MVP; use a text-based PDF."
                ),
            )

        raw_metadata = pdf.metadata or {}
        metadata = {
            key: (str(raw_metadata.get(key) or "").strip()[:500])
            for key in ("author", "subject", "creator", "producer", "creationDate", "modDate", "keywords")
        }
        title = _pdf_title(raw_metadata, pages, filename)
        warnings: list[str] = []
        if empty_pages:
            warnings.append(
                "No selectable text was extracted from PDF page(s): "
                + ", ".join(str(page) for page in empty_pages)
                + ". These may be scanned pages, image-only pages or intentionally blank pages."
            )

        return {
            "title": title,
            "page_count": page_count,
            "extracted_characters": total_chars,
            "nonempty_pages": nonempty_pages,
            "empty_pages": empty_pages,
            "pages": pages,
            "pdf_metadata": metadata,
            "warnings": warnings,
            "sha256": sha256(data).hexdigest(),
            "file_size_bytes": len(data),
        }
    finally:
        pdf.close()


async def read_and_extract_upload(file: UploadFile) -> tuple[bytes, dict[str, Any]]:
    filename = safe_display_filename(file.filename)
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files are accepted.")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {settings.max_upload_mb} MB upload limit.",
        )
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    extracted = extract_pdf_bytes(data, filename)
    return data, extracted
