"""SQLite 文档存储模块。

项目简介：
    搜索引擎不能只靠内存索引；原始文档和结构化字段需要持久化保存，进程重启后才能恢复。

开发目的：
    用 SQLite 做轻量文档库，保存 SearchDocument，再在启动时从 SQLite 重建内存索引。

技术栈：
    sqlite3、SQL DDL/DML、UPSERT、JSON 序列化、pathlib。

学习目标：
    1. 理解“文档存储”和“搜索索引”是两层不同职责。
    2. 理解 SQLite 表结构如何映射 Python dataclass。
    3. 理解 UPSERT 如何用 url 做去重更新。

知识点与免费文档：
    - sqlite3: https://docs.python.org/3/library/sqlite3.html
    - SQLite UPSERT: https://www.sqlite.org/lang_upsert.html
    - json: https://docs.python.org/3/library/json.html
    - pathlib: https://docs.python.org/3/library/pathlib.html
"""

from __future__ import annotations  # 让 Path | str 这类类型注解保持兼容。

import json  # SQLite 没有原生 list 类型，这里用 JSON 字符串保存 tags。
import sqlite3  # Python 标准库 SQLite 驱动，适合轻量本地项目。
from pathlib import Path  # 比字符串路径更安全、可读。
from typing import Iterable  # Iterable 表示可遍历的一批文档。

from .models import SearchDocument  # 文档模型。


class SQLiteDocumentStore:
    """SQLite 文档仓库。

    入参：
        db_path: SQLite 数据库文件路径，默认 data/erfairy.sqlite3。

    使用场景：
        web.py 启动时写入样例数据；/crawl 抓取后写入新文档；/reindex 从这里读取所有文档。

    设计思路：
        SQLite 零部署、单文件、适合学习；缺点是并发写入能力不如 PostgreSQL/MySQL。
    """

    def __init__(self, db_path: str | Path = "data/erfairy.sqlite3") -> None:
        self.db_path = Path(db_path)  # 统一转成 Path，后续可使用 parent/mkdir 等方法。
        self.db_path.parent.mkdir(parents=True, exist_ok=True)  # 确保 data/ 目录存在。
        self._init_schema()  # 初始化表结构，保证第一次运行也能直接使用。

    def connect(self) -> sqlite3.Connection:
        """创建一个 SQLite 连接。

        出参：
            sqlite3.Connection，row_factory 已设为 sqlite3.Row。

        设计思路：
            每个方法短连接 + with 自动提交/关闭，MVP 更简单；高并发服务可改为连接池。
        """

        conn = sqlite3.connect(self.db_path)  # 连接到数据库文件，不存在时 SQLite 会创建。
        conn.row_factory = sqlite3.Row  # 让查询结果可用 row["title"] 访问，比 tuple 下标更清晰。
        return conn  # 返回连接给调用方用 with 管理生命周期。

    def _init_schema(self) -> None:
        """创建 documents 表和分类索引。

        设计思路：
            表结构对应 SearchDocument 字段；url 设置 UNIQUE，支持后续 upsert 去重。
        """

        with self.connect() as conn:  # with 结束时自动提交事务并关闭连接。
            conn.execute(  # 执行建表 SQL。
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category)")  # 分类过滤常用，单独建索引。

    def upsert(self, document: SearchDocument) -> SearchDocument:
        """插入或更新一篇文档。

        入参：
            document: 待保存文档。

        出参：
            SearchDocument，同一个对象会被回填 id。

        设计思路：
            url 是天然去重键；重复抓取同一 URL 时更新内容，不制造重复文档。
        """

        tags_json = json.dumps(document.tags, ensure_ascii=False)  # list[str] 转 JSON 字符串；ensure_ascii=False 保留中文可读性。
        with self.connect() as conn:  # 打开一次数据库连接。
            conn.execute(  # 使用参数化 SQL，避免字符串拼接造成 SQL 注入风险。
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
                (  # ? 占位符对应的参数元组。
                    document.url,  # 唯一 URL。
                    document.title,  # 标题。
                    document.content,  # 正文。
                    document.summary,  # 摘要。
                    tags_json,  # 标签 JSON。
                    document.category,  # 分类。
                    document.source,  # 来源。
                    document.published_at,  # 发布时间。
                    document.crawled_at,  # 抓取时间。
                    document.image_url,  # 图片地址。
                ),
            )
            row = conn.execute("SELECT id FROM documents WHERE url = ?", (document.url,)).fetchone()  # 查询最终 id。
        document.id = int(row["id"])  # 回填 id，后续 indexer 必须依赖它。
        return document  # 返回带 id 的文档。

    def bulk_upsert(self, documents: Iterable[SearchDocument]) -> list[SearchDocument]:
        """批量插入或更新文档。

        入参：
            documents: 任意可遍历文档集合。

        出参：
            list[SearchDocument]，每篇文档都已回填 id。
        """

        return [self.upsert(document) for document in documents]  # MVP 逐条写入，逻辑直观；大规模可优化为批量事务。

    def all(self) -> list[SearchDocument]:
        """读取全部文档。

        使用场景：
            应用启动或 /reindex 时，用所有文档重建内存索引。
        """

        with self.connect() as conn:  # 打开数据库连接。
            rows = conn.execute("SELECT * FROM documents ORDER BY id").fetchall()  # 按 id 保持稳定顺序。
        return [self._row_to_document(row) for row in rows]  # 把数据库行转成 SearchDocument 对象。

    def count(self) -> int:
        """返回文档总数。"""

        with self.connect() as conn:  # 打开连接。
            row = conn.execute("SELECT COUNT(*) AS total FROM documents").fetchone()  # 聚合统计。
        return int(row["total"])  # SQLite 返回数字，转 int 明确类型。

    def get(self, doc_id: int) -> SearchDocument | None:
        """按 id 查询单篇文档。

        入参：
            doc_id: SQLite 主键。

        出参：
            SearchDocument 或 None。
        """

        with self.connect() as conn:  # 打开连接。
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()  # 参数化查询单行。
        return self._row_to_document(row) if row else None  # 查到则转换，查不到返回 None。

    def clear(self) -> None:
        """清空文档表。

        使用场景：
            测试或开发时重置数据；生产环境要谨慎使用。
        """

        with self.connect() as conn:  # 打开连接。
            conn.execute("DELETE FROM documents")  # 删除所有文档。

    def _row_to_document(self, row: sqlite3.Row) -> SearchDocument:
        """把 SQLite 行对象转换为 SearchDocument。

        入参：
            row: sqlite3.Row。

        出参：
            SearchDocument。
        """

        return SearchDocument(  # 字段一一映射，避免数据库层泄露到业务层。
            id=int(row["id"]),  # 主键转 int。
            url=row["url"],  # URL。
            title=row["title"],  # 标题。
            content=row["content"],  # 正文。
            summary=row["summary"],  # 摘要。
            tags=json.loads(row["tags"] or "[]"),  # JSON 字符串还原成 list[str]。
            category=row["category"],  # 分类。
            source=row["source"],  # 来源。
            published_at=row["published_at"],  # 发布时间。
            crawled_at=row["crawled_at"],  # 抓取时间。
            image_url=row["image_url"],  # 图片地址。
        )
