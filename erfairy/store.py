"""SQLite 文档存储模块。

负责把 SearchDocument 持久化到本地 SQLite，并保存爬取运行与错误记录。
"""

from __future__ import annotations

import json
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

from .models import CrawlError, SearchDocument


TITLE_SIMILARITY_THRESHOLD = 0.92


class SQLiteDocumentStore:
    """轻量文档仓库。"""

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
                    aliases TEXT NOT NULL DEFAULT '[]',
                    entity_type TEXT NOT NULL DEFAULT '',
                    game_title TEXT NOT NULL DEFAULT '',
                    character_name TEXT NOT NULL DEFAULT '',
                    source_score REAL NOT NULL DEFAULT 0.0,
                    content_hash TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT 'anime',
                    source TEXT NOT NULL DEFAULT '',
                    published_at TEXT NOT NULL DEFAULT '',
                    crawled_at TEXT NOT NULL,
                    image_url TEXT NOT NULL DEFAULT ''
                )
                """
            )
            self._ensure_document_columns(conn)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS crawl_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL DEFAULT '',
                    source_count INTEGER NOT NULL DEFAULT 0,
                    saved_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    category TEXT NOT NULL DEFAULT 'anime',
                    status TEXT NOT NULL DEFAULT 'running'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS crawl_errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    crawl_run_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    message TEXT NOT NULL,
                    depth INTEGER NOT NULL DEFAULT 0,
                    category TEXT NOT NULL DEFAULT 'anime',
                    crawled_at TEXT NOT NULL,
                    FOREIGN KEY (crawl_run_id) REFERENCES crawl_runs(id)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_crawl_errors_run_id ON crawl_errors(crawl_run_id)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL UNIQUE,
                    source_type TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    reason TEXT NOT NULL DEFAULT '',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    discovered_at TEXT NOT NULL,
                    approved_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            self._ensure_source_candidate_columns(conn)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_source_candidates_status ON source_candidates(status)")

    def _ensure_document_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(documents)").fetchall()}
        column_defs = {
            "aliases": "TEXT NOT NULL DEFAULT '[]'",
            "entity_type": "TEXT NOT NULL DEFAULT ''",
            "game_title": "TEXT NOT NULL DEFAULT ''",
            "character_name": "TEXT NOT NULL DEFAULT ''",
            "source_score": "REAL NOT NULL DEFAULT 0.0",
            "content_hash": "TEXT NOT NULL DEFAULT ''",
        }
        for name, ddl in column_defs.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {name} {ddl}")

    def _ensure_source_candidate_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(source_candidates)").fetchall()}
        if "config_json" not in columns:
            conn.execute("ALTER TABLE source_candidates ADD COLUMN config_json TEXT NOT NULL DEFAULT '{}'")

    def upsert(self, document: SearchDocument) -> SearchDocument:
        tags_json = json.dumps(document.tags, ensure_ascii=False)
        aliases_json = json.dumps(document.aliases, ensure_ascii=False)
        with self.connect() as conn:
            existing = self._find_existing_document(conn, document)
            upsert_url = existing["url"] if existing else document.url
            conn.execute(
                """
                INSERT INTO documents (
                    url, title, content, summary, tags, aliases, entity_type,
                    game_title, character_name, source_score, content_hash, category, source,
                    published_at, crawled_at, image_url
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    title=excluded.title,
                    content=excluded.content,
                    summary=excluded.summary,
                    tags=excluded.tags,
                    aliases=excluded.aliases,
                    entity_type=excluded.entity_type,
                    game_title=excluded.game_title,
                    character_name=excluded.character_name,
                    source_score=excluded.source_score,
                    content_hash=excluded.content_hash,
                    category=excluded.category,
                    source=excluded.source,
                    published_at=excluded.published_at,
                    crawled_at=excluded.crawled_at,
                    image_url=excluded.image_url
                """,
                (
                    upsert_url,
                    document.title,
                    document.content,
                    document.summary,
                    tags_json,
                    aliases_json,
                    document.entity_type,
                    document.game_title,
                    document.character_name,
                    document.source_score,
                    document.content_hash,
                    document.category,
                    document.source,
                    document.published_at,
                    document.crawled_at,
                    document.image_url,
                ),
            )
            row = conn.execute("SELECT id, url FROM documents WHERE url = ?", (upsert_url,)).fetchone()
        document.id = int(row["id"])
        document.url = row["url"]
        return document

    def _find_existing_document(self, conn: sqlite3.Connection, document: SearchDocument) -> sqlite3.Row | None:
        if document.content_hash:
            existing = conn.execute(
                "SELECT id, url, title FROM documents WHERE content_hash = ? ORDER BY id LIMIT 1",
                (document.content_hash,),
            ).fetchone()
            if existing:
                return existing

        normalized_title = self._normalize_title(document.title)
        if len(normalized_title) < 6:
            return None

        rows = conn.execute(
            """
            SELECT id, url, title
            FROM documents
            WHERE category = ?
              AND (? = '' OR source = ? OR source = '')
            ORDER BY id
            """,
            (document.category, document.source, document.source),
        ).fetchall()
        for row in rows:
            candidate = self._normalize_title(row["title"])
            if not candidate:
                continue
            if SequenceMatcher(None, normalized_title, candidate).ratio() >= TITLE_SIMILARITY_THRESHOLD:
                return row
        return None

    def _normalize_title(self, title: str) -> str:
        return "".join(ch.lower() for ch in title if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")

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

    def delete(self, doc_id: int) -> bool:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        return cursor.rowcount > 0

    def clear(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM documents")

    def start_crawl_run(self, category: str = "anime") -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO crawl_runs (started_at, category, status)
                VALUES (?, ?, 'running')
                """,
                (self._utc_now_iso(), category),
            )
        return int(cursor.lastrowid)

    def finish_crawl_run(
        self,
        crawl_run_id: int,
        source_count: int,
        saved_count: int,
        error_count: int,
        category: str = "anime",
        status: str = "completed",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE crawl_runs
                SET finished_at = ?, source_count = ?, saved_count = ?, error_count = ?, category = ?, status = ?
                WHERE id = ?
                """,
                (
                    self._utc_now_iso(),
                    source_count,
                    saved_count,
                    error_count,
                    category,
                    status,
                    crawl_run_id,
                ),
            )

    def save_crawl_errors(self, crawl_run_id: int, errors: Iterable[CrawlError]) -> list[CrawlError]:
        error_list = list(errors)
        if not error_list:
            return []
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO crawl_errors (
                    crawl_run_id, url, stage, message, depth, category, crawled_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        crawl_run_id,
                        error.url,
                        error.stage,
                        error.message,
                        error.depth,
                        error.category,
                        error.crawled_at,
                    )
                    for error in error_list
                ],
            )
        return error_list

    def crawl_errors_for_run(self, crawl_run_id: int) -> list[CrawlError]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT url, stage, message, depth, category, crawled_at
                FROM crawl_errors
                WHERE crawl_run_id = ?
                ORDER BY id
                """,
                (crawl_run_id,),
            ).fetchall()
        return [
            CrawlError(
                url=row["url"],
                stage=row["stage"],
                message=row["message"],
                depth=int(row["depth"]),
                category=row["category"],
                crawled_at=row["crawled_at"],
            )
            for row in rows
        ]

    def recent_crawl_runs(self, limit: int = 20) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, started_at, finished_at, source_count, saved_count,
                       error_count, category, status
                FROM crawl_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        runs = []
        for row in rows:
            errors = [error.as_dict() for error in self.crawl_errors_for_run(int(row["id"]))]
            runs.append(
                {
                    "id": int(row["id"]),
                    "started_at": row["started_at"],
                    "finished_at": row["finished_at"],
                    "source_count": int(row["source_count"]),
                    "saved_count": int(row["saved_count"]),
                    "error_count": int(row["error_count"]),
                    "category": row["category"],
                    "status": row["status"],
                    "errors": errors,
                }
            )
        return runs

    def upsert_source_candidate(
        self,
        url: str,
        source_type: str,
        title: str = "",
        reason: str = "",
        status: str = "pending",
        config: dict | None = None,
    ) -> dict:
        config_json = json.dumps(config or {}, ensure_ascii=False)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO source_candidates (
                    url, source_type, title, status, reason, config_json, discovered_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    source_type=excluded.source_type,
                    title=excluded.title,
                    reason=excluded.reason,
                    config_json=excluded.config_json
                """,
                (url, source_type, title, status, reason, config_json, self._utc_now_iso()),
            )
            row = conn.execute("SELECT * FROM source_candidates WHERE url = ?", (url,)).fetchone()
        return self._row_to_source_candidate(row)

    def source_candidates(self, status: str | None = None, limit: int = 100) -> list[dict]:
        with self.connect() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT * FROM source_candidates
                    WHERE status = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM source_candidates ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_to_source_candidate(row) for row in rows]

    def get_source_candidate(self, candidate_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM source_candidates WHERE id = ?", (candidate_id,)).fetchone()
        return self._row_to_source_candidate(row) if row else None

    def approve_source_candidate(self, candidate_id: int) -> dict | None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE source_candidates
                SET status = 'approved', approved_at = ?
                WHERE id = ?
                """,
                (self._utc_now_iso(), candidate_id),
            )
            row = conn.execute("SELECT * FROM source_candidates WHERE id = ?", (candidate_id,)).fetchone()
        return self._row_to_source_candidate(row) if row else None

    def reject_source_candidate(self, candidate_id: int) -> dict | None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE source_candidates
                SET status = 'rejected'
                WHERE id = ?
                """,
                (candidate_id,),
            )
            row = conn.execute("SELECT * FROM source_candidates WHERE id = ?", (candidate_id,)).fetchone()
        return self._row_to_source_candidate(row) if row else None

    def _row_to_source_candidate(self, row: sqlite3.Row) -> dict:
        try:
            config = json.loads(row["config_json"] or "{}")
        except json.JSONDecodeError:
            config = {}
        return {
            "id": int(row["id"]),
            "url": row["url"],
            "source_type": row["source_type"],
            "title": row["title"],
            "status": row["status"],
            "reason": row["reason"],
            "config_json": row["config_json"],
            "config": config,
            "discovered_at": row["discovered_at"],
            "approved_at": row["approved_at"],
        }

    def _row_to_document(self, row: sqlite3.Row) -> SearchDocument:
        return SearchDocument(
            id=int(row["id"]),
            url=row["url"],
            title=row["title"],
            content=row["content"],
            summary=row["summary"],
            tags=json.loads(row["tags"] or "[]"),
            aliases=json.loads(row["aliases"] or "[]"),
            entity_type=row["entity_type"],
            game_title=row["game_title"],
            character_name=row["character_name"],
            source_score=float(row["source_score"] or 0.0),
            content_hash=row["content_hash"],
            category=row["category"],
            source=row["source"],
            published_at=row["published_at"],
            crawled_at=row["crawled_at"],
            image_url=row["image_url"],
        )

    def _utc_now_iso(self) -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat(timespec="seconds")
