from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4
import logging
import os

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Query, Request
from fastapi.responses import JSONResponse
import secrets
from fastapi.middleware.cors import CORSMiddleware

from app import database
from app.config import settings
from app.models import (
    DocumentVersion,
    UploadResponse,
    DocumentListItem,
    DocumentPageResponse,
    CompareRequest,
    CompareResponse,
)
from app.services.pdf_service import read_and_extract_upload, safe_display_filename
from app.services.analysis_service import run_analysis_job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("policy-intelligence")


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.init_db()
    logger.info("Policy Intelligence API started. Data directory: %s", settings.root_data_dir)
    yield


app = FastAPI(
    title="Policy Intelligence Engine API",
    version="0.4.3",
    description=(
        "Document ingestion and evidence-grounded policy comparison of two versions "
        "of an official policy document."
    ),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_backend_token(request: Request, call_next):
    # All API traffic must arrive through the authenticated Vercel proxy.
    if request.url.path.startswith("/api/"):
        expected = settings.api_shared_secret
        supplied = request.headers.get("x-backend-token", "")
        if not expected or not secrets.compare_digest(supplied, expected):
            return JSONResponse(status_code=401, content={"detail": "Unauthorized backend request."})
    return await call_next(request)


@app.get("/api/ai/status")
def ai_status() -> dict:
    model = settings.ollama_model if settings.ai_provider.strip().lower() == "ollama" else settings.openai_model
    return {"provider": settings.ai_provider, "model": model, "status": "configured"}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "policy-intelligence-api", "version": app.version}


@app.post("/api/documents/upload", response_model=UploadResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    version: DocumentVersion = Form(...),
):
    data, extracted = await read_and_extract_upload(file)
    document_id = str(uuid4())
    display_name = safe_display_filename(file.filename)
    stored_path = settings.root_data_dir / "uploads" / f"{document_id}.pdf"
    temporary_path = stored_path.with_suffix(".uploading")

    record = {
        "document_id": document_id,
        "filename": display_name,
        "stored_path": str(stored_path),
        "version": version.value,
        "title": extracted["title"],
        "page_count": extracted["page_count"],
        "extracted_characters": extracted["extracted_characters"],
        "pages": extracted["pages"],
        "created_at": database.utc_now(),
        "sha256": extracted["sha256"],
        "file_size_bytes": extracted["file_size_bytes"],
        "nonempty_pages": extracted["nonempty_pages"],
        "empty_pages": extracted["empty_pages"],
        "pdf_metadata": extracted["pdf_metadata"],
        "warnings": extracted["warnings"],
    }

    try:
        # Write to a temporary file and atomically rename only after all bytes are written.
        with temporary_path.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(stored_path)
        database.insert_document(record)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        stored_path.unlink(missing_ok=True)
        logger.exception("Could not persist uploaded document %s", document_id)
        raise HTTPException(status_code=500, detail="Could not store the uploaded document.")
    finally:
        await file.close()

    return UploadResponse(
        document_id=document_id,
        filename=record["filename"],
        version=version,
        title=record["title"],
        page_count=record["page_count"],
        extracted_characters=record["extracted_characters"],
        created_at=record["created_at"],
        file_size_bytes=record["file_size_bytes"],
        sha256=record["sha256"],
        nonempty_pages=record["nonempty_pages"],
        empty_pages=record["empty_pages"],
        pdf_metadata=record["pdf_metadata"],
        warnings=record["warnings"],
    )


@app.get("/api/documents", response_model=list[DocumentListItem])
def list_uploaded_documents(limit: int = Query(default=50, ge=1, le=100)):
    docs = database.list_documents(limit=limit)
    return [
        DocumentListItem(
            document_id=doc["document_id"],
            filename=doc["filename"],
            version=doc["version"],
            title=doc["title"],
            page_count=doc["page_count"],
            extracted_characters=doc["extracted_characters"],
            created_at=doc["created_at"],
            file_size_bytes=doc.get("file_size_bytes", 0),
            sha256=doc.get("sha256") or "",
            nonempty_pages=doc.get("nonempty_pages", 0),
            empty_pages=doc.get("empty_pages", []),
            warnings=doc.get("warnings", []),
        )
        for doc in docs
    ]


@app.get("/api/documents/{document_id}")
def get_uploaded_document(document_id: str):
    doc = database.get_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    # Keep the complete extracted text server-side; expose metadata here.
    return {
        "document_id": doc["document_id"],
        "filename": doc["filename"],
        "version": doc["version"],
        "title": doc["title"],
        "page_count": doc["page_count"],
        "extracted_characters": doc["extracted_characters"],
        "created_at": doc["created_at"],
        "file_size_bytes": doc.get("file_size_bytes", 0),
        "sha256": doc.get("sha256") or "",
        "nonempty_pages": doc.get("nonempty_pages", 0),
        "empty_pages": doc.get("empty_pages", []),
        "pdf_metadata": doc.get("pdf_metadata", {}),
        "warnings": doc.get("warnings", []),
    }


@app.get("/api/documents/{document_id}/pages/{page_number}", response_model=DocumentPageResponse)
def get_document_page(document_id: str, page_number: int):
    doc = database.get_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if page_number < 1 or page_number > doc["page_count"]:
        raise HTTPException(status_code=404, detail="PDF page not found. Page numbers are 1-based.")
    page = doc["pages"][page_number - 1]
    return DocumentPageResponse(
        document_id=document_id,
        page=page["page"],
        character_count=page.get("character_count", len(page.get("text", ""))),
        has_text=page.get("has_text", bool(page.get("text", ""))),
        text=page.get("text", ""),
    )


@app.post("/api/documents/compare", response_model=CompareResponse, status_code=202)
def compare_documents(payload: CompareRequest, background_tasks: BackgroundTasks):
    earlier = database.get_document(payload.earlier_document_id)
    later = database.get_document(payload.later_document_id)
    if earlier is None or later is None:
        raise HTTPException(status_code=404, detail="One or both document IDs were not found. Upload both PDFs first.")
    if earlier["version"] != "earlier":
        raise HTTPException(status_code=400, detail="The first document must have been uploaded with version='earlier'.")
    if later["version"] != "later":
        raise HTTPException(status_code=400, detail="The second document must have been uploaded with version='later'.")
    if payload.earlier_document_id == payload.later_document_id:
        raise HTTPException(status_code=400, detail="Choose two different documents for comparison.")

    analysis_id = str(uuid4())
    database.insert_analysis(analysis_id, payload.earlier_document_id, payload.later_document_id)
    background_tasks.add_task(run_analysis_job, analysis_id, payload.earlier_document_id, payload.later_document_id)
    return CompareResponse(
        analysis_id=analysis_id,
        status="processing",
        message="Comparison started. Poll GET /api/analysis/{analysis_id} for the result.",
    )


@app.get("/api/analysis/{analysis_id}")
def get_analysis_status(analysis_id: str):
    analysis = database.get_analysis(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    response = {
        "analysis_id": analysis["analysis_id"],
        "status": analysis["status"],
        "created_at": analysis["created_at"],
        "updated_at": analysis["updated_at"],
    }
    if analysis["status"] == "completed":
        response["result"] = analysis["result"]
    elif analysis["status"] == "failed":
        response["error"] = analysis["error_message"] or "Analysis failed."
    return response


@app.get("/api/analysis/{analysis_id}/changes")
def get_analysis_changes(analysis_id: str):
    analysis = database.get_analysis(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    if analysis["status"] == "processing":
        return {"analysis_id": analysis_id, "status": "processing", "changes": []}
    if analysis["status"] == "failed":
        raise HTTPException(status_code=409, detail=analysis["error_message"] or "Analysis failed.")
    result = analysis["result"] or {}
    return {
        "analysis_id": analysis_id,
        "status": "completed",
        "counts": result.get("counts", {}),
        "changes": result.get("changes", []),
    }
