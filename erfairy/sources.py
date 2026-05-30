"""受控数据源配置加载。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .crawler import CrawlConfig


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SOURCES_PATH = PROJECT_DIR / "sources.example.json"


@dataclass(slots=True)
class SourceConfig:
    """一个可控抓取源。"""

    name: str
    entry_url: str
    allowed_domains: list[str]
    source_id: str = ""
    category: str = "anime"
    max_pages: int = 10
    max_depth: int = 1
    delay_seconds: float = 1.0
    source_score: float = 0.0
    parse_strategy: str = "default"
    notes: str = ""
    scheduler_interval_minutes: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceConfig":
        return cls(
            name=str(data["name"]),
            entry_url=str(data["entry_url"]),
            source_id=str(data.get("id", "")),
            allowed_domains=[str(domain) for domain in data.get("allowed_domains", [])],
            category=str(data.get("category", "anime")),
            max_pages=int(data.get("max_pages", 10)),
            max_depth=int(data.get("max_depth", 1)),
            delay_seconds=float(data.get("delay_seconds", 1.0)),
            source_score=float(data.get("source_score", 0.0)),
            parse_strategy=str(data.get("parse_strategy", "default")),
            notes=str(data.get("notes", "")),
            scheduler_interval_minutes=int(data.get("scheduler_interval_minutes", 0)),
        )

    def to_crawl_config(self) -> CrawlConfig:
        return CrawlConfig(
            seeds=[self.entry_url],
            max_pages=self.max_pages,
            max_depth=self.max_depth,
            delay_seconds=self.delay_seconds,
            allowed_domains=set(self.allowed_domains),
            category=self.category,
        )


def load_source_configs(path: str | Path = DEFAULT_SOURCES_PATH) -> list[SourceConfig]:
    source_path = Path(path)
    data = json.loads(source_path.read_text(encoding="utf-8"))
    return [SourceConfig.from_dict(item) for item in data]


def find_source_config(name: str, path: str | Path = DEFAULT_SOURCES_PATH) -> SourceConfig | None:
    key = name.strip()
    for source in load_source_configs(path):
        if source.name == key or source.source_id == key:
            return source
    return None
