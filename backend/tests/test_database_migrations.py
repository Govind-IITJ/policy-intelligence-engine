import sqlite3

from app import database
from app.config import settings


def test_original_starter_database_migrates_with_phase1_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    db_path = settings.database_path
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE documents (
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
        CREATE TABLE analyses (
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
    conn.commit()
    conn.close()

    database.init_db()

    with database.get_connection() as migrated:
        columns = {row["name"] for row in migrated.execute("PRAGMA table_info(documents)").fetchall()}
    assert {"sha256", "file_size_bytes", "nonempty_pages", "empty_pages_json", "pdf_metadata_json", "warnings_json"}.issubset(columns)
