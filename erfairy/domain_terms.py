"""领域词典加载与文档补全。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from dataclasses import replace
from pathlib import Path
from typing import Any

from .models import SearchDocument


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ALIASES_PATH = PROJECT_DIR / "aliases.example.json"


@dataclass(slots=True)
class DomainEntity:
    """一个二次元领域实体及其别名。"""

    canonical: str
    entity_type: str = ""
    game_title: str = ""
    aliases: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DomainEntity":
        return cls(
            canonical=str(data.get("canonical", "")),
            entity_type=str(data.get("entity_type", "")),
            game_title=str(data.get("game_title", "")),
            aliases=[str(alias) for alias in data.get("aliases", [])],
        )

    @property
    def lookup_terms(self) -> list[str]:
        return [self.canonical, *self.aliases]


@dataclass(slots=True)
class DomainTerms:
    """可加载的领域词典。"""

    entities: list[DomainEntity] = field(default_factory=list)
    news_intent_terms: set[str] = field(default_factory=set)


def load_domain_terms(path: str | Path = DEFAULT_ALIASES_PATH) -> DomainTerms:
    """从 aliases.example.json 加载别名和新闻意图词。"""

    aliases_path = Path(path)
    if not aliases_path.exists():
        return DomainTerms()

    data = json.loads(aliases_path.read_text(encoding="utf-8"))
    return DomainTerms(
        entities=[DomainEntity.from_dict(item) for item in data.get("entities", [])],
        news_intent_terms={str(term) for term in data.get("news_intent_terms", [])},
    )


def enrich_document(document: SearchDocument, terms: DomainTerms) -> SearchDocument:
    """根据领域词典补全文档字段，不覆盖爬虫已经明确解析出的字段。"""

    enriched = replace(document, tags=list(document.tags), aliases=list(document.aliases))
    searchable_fields = [enriched.title, enriched.summary, enriched.content, *enriched.tags, *enriched.aliases]
    haystack = " ".join(searchable_fields).lower()
    exact_terms = {value.lower() for value in [*enriched.tags, *enriched.aliases] if value}
    for entity in terms.entities:
        if not _matches_entity(haystack, entity, exact_terms):
            continue

        enriched.aliases = _merge_unique([*enriched.aliases, entity.canonical, *entity.aliases])
        if not enriched.entity_type:
            enriched.entity_type = entity.entity_type
        if not enriched.game_title:
            enriched.game_title = entity.game_title
        if not enriched.character_name and entity.entity_type == "character":
            enriched.character_name = entity.canonical
    return enriched


def enrich_documents(documents: list[SearchDocument], terms: DomainTerms) -> list[SearchDocument]:
    """批量补全文档字段。"""

    return [enrich_document(document, terms) for document in documents]


def _matches_entity(haystack: str, entity: DomainEntity, exact_terms: set[str] | None = None) -> bool:
    exact_terms = exact_terms or set()
    for term in entity.lookup_terms:
        normalized = term.strip().lower()
        if not normalized:
            continue
        if len(normalized) <= 1:
            if normalized in exact_terms:
                return True
            continue
        if normalized in haystack:
            return True
    return False


def _merge_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(normalized)
    return merged
