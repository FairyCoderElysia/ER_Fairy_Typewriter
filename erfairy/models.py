from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class SearchDocument:
    url: str
    title: str
    content: str
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    category: str = "anime"
    source: str = ""
    published_at: str = ""
    crawled_at: str = field(default_factory=utc_now_iso)
    image_url: str = ""
    id: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "summary": self.summary,
            "tags": self.tags,
            "category": self.category,
            "source": self.source,
            "published_at": self.published_at,
            "crawled_at": self.crawled_at,
            "image_url": self.image_url,
        }


@dataclass(slots=True)
class SearchResult:
    document: SearchDocument
    score: float
    snippet: str

    def as_dict(self) -> dict[str, Any]:
        data = self.document.as_dict()
        data["score"] = round(self.score, 6)
        data["snippet"] = self.snippet
        return data
