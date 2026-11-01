"""SQLite persistence for uploaded policy documents and analyses."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from app.config import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_connection():
    conn = sqlite3.connect(settings.database_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate_documents_table(conn: sqlite3.Connection) -> None:
    """Add Phase 1 fields when opening a database created by the original starter."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(documents)").fetchall()}
    migrations = {
        "sha256": "ALTER TABLE documents ADD COLUMN sha256 TEXT",
        "file_size_bytes": "ALTER TABLE documents ADD COLUMN file_size_bytes INTEGER NOT NULL DEFAULT 0",
        "nonempty_pages": "ALTER TABLE documents ADD COLUMN nonempty_pages INTEGER NOT NULL DEFAULT 0",
        "empty_pages_json": "ALTER TABLE documents ADD COLUMN empty_pages_json TEXT NOT NULL DEFAULT '[]'",
        "pdf_metadata_json": "ALTER TABLE documents ADD COLUMN pdf_metadata_json TEXT NOT NULL DEFAULT '{}'",
        "warnings_json": "ALTER TABLE documents ADD COLUMN warnings_json TEXT NOT NULL DEFAULT '[]'",
    }
    for column, statement in migrations.items():
        if column not in existing:
            conn.execute(statement)


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                version TEXT NOT NULL CHECK(version IN ('earlier','later')),
                title TEXT NOT NULL,
                page_count INTEGER NOT NULL,
                extracted_characters INTEGER NOT NULL,
                pages_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS analyses (
                analysis_id TEXT PRIMARY KEY,
                earlier_document_id TEXT NOT NULL,
                later_document_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('processing','completed','failed')),
                result_json TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(earlier_document_id) REFERENCES documents(document_id),
                FOREIGN KEY(later_document_id) REFERENCES documents(document_id)
            );
            """
        )
        _migrate_documents_table(conn)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analyses_created_at ON analyses(created_at DESC)")


def insert_document(record: dict[str, Any]) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO documents
            (document_id, filename, stored_path, version, title, page_count,
             extracted_characters, pages_json, created_at, sha256, file_size_bytes,
             nonempty_pages, empty_pages_json, pdf_metadata_json, warnings_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record["document_id"], record["filename"], record["stored_path"],
                record["version"], record["title"], record["page_count"],
                record["extracted_characters"], json.dumps(record["pages"], ensure_ascii=False),
                record["created_at"], record.get("sha256"), record.get("file_size_bytes", 0),
                record.get("nonempty_pages", 0), json.dumps(record.get("empty_pages", [])),
                json.dumps(record.get("pdf_metadata", {}), ensure_ascii=False),
                json.dumps(record.get("warnings", []), ensure_ascii=False),
            ),
        )


def _document_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["pages"] = json.loads(result.pop("pages_json"))
    result["empty_pages"] = json.loads(result.pop("empty_pages_json", "[]") or "[]")
    result["pdf_metadata"] = json.loads(result.pop("pdf_metadata_json", "{}") or "{}")
    result["warnings"] = json.loads(result.pop("warnings_json", "[]") or "[]")
    return result


def get_document(document_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM documents WHERE document_id = ?", (document_id,)).fetchone()
    return _document_row_to_dict(row) if row is not None else None


def list_documents(limit: int = 50) -> list[dict[str, Any]]:
    bounded_limit = max(1, min(int(limit), 100))
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM documents ORDER BY created_at DESC LIMIT ?", (bounded_limit,)
        ).fetchall()
    return [_document_row_to_dict(row) for row in rows]


def insert_analysis(analysis_id: str, earlier_id: str, later_id: str) -> None:
    now = utc_now()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO analyses
            (analysis_id, earlier_document_id, later_document_id, status, created_at, updated_at)
            VALUES (?, ?, ?, 'processing', ?, ?)""",
            (analysis_id, earlier_id, later_id, now, now),
        )


def update_analysis_completed(analysis_id: str, result: dict[str, Any]) -> None:
    now = utc_now()
    with get_connection() as conn:
        conn.execute(
            "UPDATE analyses SET status='completed', result_json=?, error_message=NULL, updated_at=? WHERE analysis_id=?",
            (json.dumps(result, ensure_ascii=False), now, analysis_id),
        )


def update_analysis_failed(analysis_id: str, message: str) -> None:
    now = utc_now()
    with get_connection() as conn:
        conn.execute(
            "UPDATE analyses SET status='failed', error_message=?, updated_at=? WHERE analysis_id=?",
            (message[:1000], now, analysis_id),
        )


def get_analysis(analysis_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM analyses WHERE analysis_id = ?", (analysis_id,)).fetchone()
    if row is None:
        return None
    result = dict(row)
    if result.get("result_json"):
        result["result"] = json.loads(result.pop("result_json"))
    else:
        result["result"] = None
        result.pop("result_json", None)
    return result
