"""倒排索引、TF-IDF 与垂直排序模块。"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timezone

from .models import (
    DocumentScoreExplanation,
    FieldMatch,
    IndexStats,
    SearchDocument,
    SearchExplanation,
)
from .models import utc_now_iso
from .tokenizer import tokenize


FIELD_WEIGHTS = {
    "title": 3.5,
    "aliases": 3.2,
    "character_name": 3.1,
    "game_title": 2.8,
    "tags": 2.2,
    "entity_type": 2.0,
    "summary": 1.5,
    "content": 1.0,
}

NEWS_INTENT_TERMS = {"最新", "活动", "版本", "公告", "新闻", "资讯", "更新", "前瞻"}


class SearchIndex:
    """搜索索引接口。"""

    def rebuild(self, documents: list[SearchDocument]) -> None:
        raise NotImplementedError

    def search(
        self,
        query: str,
        category: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[tuple[SearchDocument, float]], int]:
        raise NotImplementedError

    def explain(self, query: str, category: str | None = None) -> SearchExplanation:
        raise NotImplementedError

    def stats(self) -> IndexStats:
        raise NotImplementedError


def create_search_index(backend: str = "memory") -> SearchIndex:
    """按名称创建搜索索引后端。"""

    normalized = backend.strip().lower()
    if normalized in {"memory", "inmemory", "tfidf"}:
        return InMemoryTfIdfIndex()
    if normalized in {"redis", "redis-zset", "zset"}:
        return RedisZSetLikeIndex()
    raise ValueError(f"未知索引后端：{backend}")


class InMemoryTfIdfIndex(SearchIndex):
    """内存版 TF-IDF 索引。"""

    backend_name = "memory"

    def __init__(self) -> None:
        self.documents: dict[int, SearchDocument] = {}
        self.document_terms: dict[int, dict[str, float]] = {}
        self.document_field_terms: dict[int, dict[str, dict[str, float]]] = {}
        self.inverted: dict[str, dict[int, float]] = defaultdict(dict)
        self.doc_magnitudes: dict[int, float] = {}
        self.last_rebuilt_at = ""

    def clear(self) -> None:
        self.documents.clear()
        self.document_terms.clear()
        self.document_field_terms.clear()
        self.inverted.clear()
        self.doc_magnitudes.clear()

    def rebuild(self, documents: list[SearchDocument]) -> None:
        self.clear()
        for document in documents:
            self.add(document)
        self.last_rebuilt_at = utc_now_iso()

    def add(self, document: SearchDocument) -> None:
        if document.id is None:
            raise ValueError("Document must have an id before indexing")
        field_terms = self._weighted_field_terms(document)
        terms = self._merge_field_terms(field_terms)
        self.documents[document.id] = document
        self.document_terms[document.id] = terms
        self.document_field_terms[document.id] = field_terms
        for term, weight in terms.items():
            self.inverted[term][document.id] = weight
        self.doc_magnitudes[document.id] = math.sqrt(sum(value * value for value in terms.values()))

    def search(
        self,
        query: str,
        category: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[tuple[SearchDocument, float]], int]:
        explanation = self.explain(query, category=category)
        ranked = [(item.document, item.final_score) for item in explanation.results]
        total = len(ranked)
        return ranked[offset : offset + limit], total

    def explain(self, query: str, category: str | None = None) -> SearchExplanation:
        query_terms = tokenize(query)
        if not query_terms:
            return SearchExplanation(query=query, tokens=[], candidate_count=0, missing_terms=[], results=[])

        query_counts = Counter(query_terms)
        scores: dict[int, float] = defaultdict(float)
        field_matches: dict[int, list[FieldMatch]] = defaultdict(list)
        query_magnitude = 0.0
        total_docs = max(len(self.documents), 1)
        missing_terms: list[str] = []

        for term, count in query_counts.items():
            postings = self._postings(term)
            if not postings:
                missing_terms.append(term)
                continue
            idf = math.log((total_docs + 1) / (len(postings) + 1)) + 1
            query_weight = count * idf
            query_magnitude += query_weight * query_weight
            for doc_id, doc_weight in postings.items():
                document = self.documents[doc_id]
                if category and document.category != category:
                    continue
                scores[doc_id] += query_weight * doc_weight * idf
                field_matches[doc_id].extend(self._field_matches(doc_id, term, query_weight, idf))

        if not scores:
            return SearchExplanation(
                query=query,
                tokens=query_terms,
                candidate_count=0,
                missing_terms=missing_terms,
                results=[],
            )

        query_magnitude = math.sqrt(query_magnitude) or 1.0
        results: list[DocumentScoreExplanation] = []
        for doc_id, score in scores.items():
            denominator = self.doc_magnitudes.get(doc_id, 1.0) * query_magnitude
            tfidf_score = score / denominator if denominator else 0.0
            document = self.documents[doc_id]
            boost_score = self._vertical_boost(document, query)
            source_bonus = min(max(document.source_score, 0.0), 10.0) * 0.02
            freshness_bonus = self._freshness_boost(document, query)
            final_score = tfidf_score + boost_score + source_bonus + freshness_bonus
            results.append(
                DocumentScoreExplanation(
                    document=document,
                    field_matches=field_matches[doc_id],
                    tfidf_score=tfidf_score,
                    boost_score=boost_score + source_bonus + freshness_bonus,
                    final_score=final_score,
                )
            )

        results.sort(key=lambda item: item.final_score, reverse=True)
        return SearchExplanation(
            query=query,
            tokens=query_terms,
            candidate_count=len(results),
            missing_terms=missing_terms,
            results=results,
        )

    def stats(self) -> IndexStats:
        posting_count = sum(len(postings) for postings in self.inverted.values())
        return IndexStats(
            document_count=len(self.documents),
            term_count=len(self.inverted),
            posting_count=posting_count,
            last_rebuilt_at=self.last_rebuilt_at,
            backend=self.backend_name,
        )

    def _weighted_field_terms(self, document: SearchDocument) -> dict[str, dict[str, float]]:
        fields = {
            "title": document.title,
            "aliases": " ".join(document.aliases),
            "character_name": document.character_name,
            "game_title": document.game_title,
            "tags": " ".join(document.tags),
            "entity_type": document.entity_type,
            "summary": document.summary,
            "content": document.content,
        }
        weighted: dict[str, dict[str, float]] = {}
        for field, text in fields.items():
            weighted[field] = {}
            counts = Counter(tokenize(text))
            total = sum(counts.values()) or 1
            for term, count in counts.items():
                weighted[field][term] = (count / total) * FIELD_WEIGHTS[field]
        return weighted

    def _merge_field_terms(self, field_terms: dict[str, dict[str, float]]) -> dict[str, float]:
        merged: dict[str, float] = defaultdict(float)
        for terms in field_terms.values():
            for term, weight in terms.items():
                merged[term] += weight
        return dict(merged)

    def _postings(self, term: str) -> dict[int, float]:
        return self.inverted.get(term, {})

    def _field_matches(self, doc_id: int, term: str, query_weight: float, idf: float) -> list[FieldMatch]:
        matches: list[FieldMatch] = []
        for field, terms in self.document_field_terms.get(doc_id, {}).items():
            tf = terms.get(term, 0.0)
            if tf <= 0:
                continue
            matches.append(
                FieldMatch(
                    field=field,
                    term=term,
                    tf=tf,
                    idf=idf,
                    field_weight=FIELD_WEIGHTS[field],
                    contribution=query_weight * tf * idf,
                )
            )
        return matches

    def _vertical_boost(self, document: SearchDocument, query: str) -> float:
        query = query.strip().lower()
        if not query:
            return 0.0

        title = document.title.lower()
        aliases = [alias.lower() for alias in document.aliases]
        character_name = document.character_name.lower()
        game_title = document.game_title.lower()
        entity_type = document.entity_type.lower()
        tags = [tag.lower() for tag in document.tags]
        summary = document.summary.lower()

        boost = 0.0
        if query == character_name:
            boost += 2.2
        if query == game_title:
            boost += 1.8
        if query == entity_type:
            boost += 1.0
        if document.entity_type == "work" and query in title:
            boost += 0.7
        if document.entity_type == "character" and query in character_name:
            boost += 1.2
        if query == title:
            boost += 1.8
        if title.startswith(query):
            boost += 1.0
        if query in title:
            boost += 0.9
        if query in aliases:
            boost += 2.0
        elif any(query in alias for alias in aliases):
            boost += 1.3
        if query in character_name and character_name:
            boost += 1.5
        if query in game_title and game_title:
            boost += 1.0
        if any(query == tag or query in tag for tag in tags):
            boost += 0.6
        if document.entity_type == "work" and query in game_title:
            boost += 0.6
        if query in summary:
            boost += 0.25
        if document.entity_type == "news" and self._has_news_intent(query):
            boost += 1.4
        return boost

    def _has_news_intent(self, query: str) -> bool:
        query_terms = set(tokenize(query))
        return any(term in query or term in query_terms for term in NEWS_INTENT_TERMS)

    def _freshness_boost(self, document: SearchDocument, query: str) -> float:
        """新闻意图查询下，给近期新闻一个轻量加分。"""

        if not self._has_news_intent(query):
            return 0.0
        if document.entity_type != "news" and document.category != "news":
            return 0.0

        published_at = document.published_at or document.crawled_at
        published = _parse_iso_datetime(published_at)
        if published is None:
            return 0.0

        age_days = max((datetime.now(timezone.utc) - published).days, 0)
        if age_days <= 7:
            return 0.7
        if age_days <= 30:
            return 0.45
        if age_days <= 90:
            return 0.25
        return 0.0


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class RedisZSetLikeIndex(InMemoryTfIdfIndex):
    """Redis ZSet 风格倒排索引。

    这个实现仍运行在本地内存中，但把 postings 额外保存成 Redis ZSet 常见形态：
    term -> [(score, doc_id), ...]。后续接入真实 Redis 时，可以把这里的
    redis_zsets 替换为 ZADD/ZRANGE/ZINTERSTORE 等命令。
    """

    backend_name = "redis-zset-like"

    def __init__(self) -> None:
        super().__init__()
        self.redis_zsets: dict[str, list[tuple[float, int]]] = defaultdict(list)

    def clear(self) -> None:
        super().clear()
        self.redis_zsets.clear()

    def add(self, document: SearchDocument) -> None:
        super().add(document)
        assert document.id is not None
        for term, weight in self.document_terms[document.id].items():
            self.redis_zsets[term].append((weight, document.id))
        for term in self.redis_zsets:
            self.redis_zsets[term].sort(key=lambda item: item[0], reverse=True)

    def _postings(self, term: str) -> dict[int, float]:
        return {doc_id: weight for weight, doc_id in self.redis_zsets.get(term, [])}
