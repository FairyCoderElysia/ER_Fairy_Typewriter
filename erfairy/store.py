from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .models import SearchDocument


class SQLiteDocumentStore:
    def __init__(self, db_path: str | Path = "data/erfairy.sqlite3") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '[]',
                    category TEXT NOT NULL DEFAULT 'anime',
                    source TEXT NOT NULL DEFAULT '',
                    published_at TEXT NOT NULL DEFAULT '',
                    crawled_at TEXT NOT NULL,
                    image_url TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category)")

    def upsert(self, document: SearchDocument) -> SearchDocument:
        tags_json = json.dumps(document.tags, ensure_ascii=False)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO documents (
                    url, title, content, summary, tags, category, source,
                    published_at, crawled_at, image_url
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    title=excluded.title,
                    content=excluded.content,
                    summary=excluded.summary,
                    tags=excluded.tags,
                    category=excluded.category,
                    source=excluded.source,
                    published_at=excluded.published_at,
                    crawled_at=excluded.crawled_at,
                    image_url=excluded.image_url
                """,
                (
                    document.url,
                    document.title,
                    document.content,
                    document.summary,
                    tags_json,
                    document.category,
                    document.source,
                    document.published_at,
                    document.crawled_at,
                    document.image_url,
                ),
            )
            row = conn.execute("SELECT id FROM documents WHERE url = ?", (document.url,)).fetchone()
        document.id = int(row["id"])
        return document

    def bulk_upsert(self, documents: Iterable[SearchDocument]) -> list[SearchDocument]:
        return [self.upsert(document) for document in documents]

    def all(self) -> list[SearchDocument]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM documents ORDER BY id").fetchall()
        return [self._row_to_document(row) for row in rows]

    def count(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS total FROM documents").fetchone()
        return int(row["total"])

    def get(self, doc_id: int) -> SearchDocument | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return self._row_to_document(row) if row else None

    def clear(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM documents")

    def _row_to_document(self, row: sqlite3.Row) -> SearchDocument:
        return SearchDocument(
            id=int(row["id"]),
            url=row["url"],
            title=row["title"],
            content=row["content"],
            summary=row["summary"],
            tags=json.loads(row["tags"] or "[]"),
            category=row["category"],
            source=row["source"],
            published_at=row["published_at"],
            crawled_at=row["crawled_at"],
            image_url=row["image_url"],
        )
