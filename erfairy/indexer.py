"""倒排索引、TF-IDF 与垂直排序模块。"""

from __future__ import annotations

import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import requests

try:
    import redis
except ImportError:  # pragma: no cover - covered when the optional backend is selected.
    redis = None

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

    def upsert_many(self, documents: list[SearchDocument]) -> None:
        raise NotImplementedError

    def delete_many(self, document_ids: list[int]) -> None:
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
    if normalized in {"redis-zset", "zset", "redis-zset-like", "zset-like"}:
        return RedisZSetLikeIndex()
    if normalized in {"redis", "redis-real", "redis-server"}:
        return RedisSearchIndex(
            redis_url=os.getenv("ERFAIRY_REDIS_URL", "redis://localhost:6379/0"),
            key_prefix=os.getenv("ERFAIRY_REDIS_PREFIX", "erfairy"),
        )
    if normalized in {"meili", "meilisearch"}:
        return MeiliSearchIndex(
            meili_url=os.getenv("ERFAIRY_MEILI_URL", "http://localhost:7700"),
            api_key=os.getenv("ERFAIRY_MEILI_MASTER_KEY", ""),
            index_uid=os.getenv("ERFAIRY_MEILI_INDEX", "erfairy_documents"),
        )
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

    def upsert_many(self, documents: list[SearchDocument]) -> None:
        if not documents:
            return
        for document in documents:
            self.add(document)
        self.last_rebuilt_at = utc_now_iso()

    def delete_many(self, document_ids: list[int]) -> None:
        if not document_ids:
            return
        for document_id in document_ids:
            self.remove(document_id)
        self.last_rebuilt_at = utc_now_iso()

    def add(self, document: SearchDocument) -> None:
        if document.id is None:
            raise ValueError("Document must have an id before indexing")
        if document.id in self.documents:
            self.remove(document.id)
        field_terms = self._weighted_field_terms(document)
        terms = self._merge_field_terms(field_terms)
        self.documents[document.id] = document
        self.document_terms[document.id] = terms
        self.document_field_terms[document.id] = field_terms
        for term, weight in terms.items():
            self.inverted[term][document.id] = weight
        self.doc_magnitudes[document.id] = math.sqrt(sum(value * value for value in terms.values()))

    def remove(self, document_id: int) -> None:
        old_terms = self.document_terms.pop(document_id, {})
        for term in old_terms:
            postings = self.inverted.get(term)
            if postings is None:
                continue
            postings.pop(document_id, None)
            if not postings:
                self.inverted.pop(term, None)
        self.documents.pop(document_id, None)
        self.document_field_terms.pop(document_id, None)
        self.doc_magnitudes.pop(document_id, None)

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


def _redis_from_url(redis_url: str):
    if redis is None:
        raise RuntimeError(
            "Redis backend requires the 'redis' package. "
            "Run 'pip install -r requirements.txt' first."
        )
    return redis.from_url(redis_url, decode_responses=True)


class RedisSearchIndex(InMemoryTfIdfIndex):
    """Real Redis ZSet postings backend.

    Redis stores term -> doc_id weighted postings. The process still keeps
    documents and field-level explanation data in memory for this teaching MVP.
    """

    backend_name = "redis"

    def __init__(self, redis_url: str = "redis://localhost:6379/0", key_prefix: str = "erfairy") -> None:
        super().__init__()
        self.redis_url = redis_url
        self.key_prefix = key_prefix.strip() or "erfairy"
        self.redis_client = _redis_from_url(redis_url)
        try:
            self.redis_client.ping()
        except Exception as exc:  # pragma: no cover - exact redis exception type is client-version dependent.
            raise RuntimeError(
                f"Cannot connect to Redis at {redis_url}. "
                "Start Redis or switch ERFAIRY_INDEX_BACKEND back to memory."
            ) from exc

    def clear(self) -> None:
        super().clear()
        self._clear_redis()

    def rebuild(self, documents: list[SearchDocument]) -> None:
        self.clear()
        for document in documents:
            InMemoryTfIdfIndex.add(self, document)
        self.last_rebuilt_at = utc_now_iso()
        self._write_redis_index()

    def upsert_many(self, documents: list[SearchDocument]) -> None:
        if not documents:
            return
        for document in documents:
            self.add(document)
        self.last_rebuilt_at = utc_now_iso()
        self._write_redis_meta()

    def delete_many(self, document_ids: list[int]) -> None:
        if not document_ids:
            return
        for document_id in document_ids:
            self.remove(document_id)
        self.last_rebuilt_at = utc_now_iso()
        self._write_redis_meta()

    def add(self, document: SearchDocument) -> None:
        super().add(document)
        assert document.id is not None
        self._write_document_to_redis(document.id)
        self._write_redis_meta()

    def remove(self, document_id: int) -> None:
        old_terms = list(self.document_terms.get(document_id, {}))
        super().remove(document_id)
        if not old_terms:
            return
        pipeline = self.redis_client.pipeline()
        for term in old_terms:
            pipeline.zrem(self._postings_key(term), str(document_id))
        pipeline.execute()
        self._cleanup_empty_terms(old_terms)

    def stats(self) -> IndexStats:
        terms_key = self._terms_key()
        term_count = int(self.redis_client.scard(terms_key))
        posting_count = 0
        for term in self.redis_client.scan_iter(match=self._postings_key("*")):
            posting_count += int(self.redis_client.zcard(term))
        redis_last_rebuilt = self.redis_client.hget(self._meta_key(), "last_rebuilt_at")
        return IndexStats(
            document_count=len(self.documents),
            term_count=term_count,
            posting_count=posting_count,
            last_rebuilt_at=redis_last_rebuilt or self.last_rebuilt_at,
            backend=self.backend_name,
        )

    def debug_snapshot(self, term: str = "", term_limit: int = 24, postings_limit: int = 12) -> dict:
        terms = sorted(str(item) for item in self.redis_client.smembers(self._terms_key()))
        selected_term = term.strip()
        if not selected_term and terms:
            selected_term = terms[0]

        rows = []
        if selected_term:
            for member, score in self.redis_client.zrevrange(
                self._postings_key(selected_term),
                0,
                max(postings_limit - 1, 0),
                withscores=True,
            ):
                doc_id = int(member)
                document = self.documents.get(doc_id)
                rows.append(
                    {
                        "doc_id": doc_id,
                        "score": float(score),
                        "title": document.title if document else "",
                        "url": document.url if document else "",
                        "category": document.category if document else "",
                    }
                )

        keys = sorted(str(key) for key in self.redis_client.scan_iter(match=f"{self.key_prefix}:*"))
        return {
            "available": True,
            "backend": self.backend_name,
            "redis_url": _mask_redis_url(self.redis_url),
            "key_prefix": self.key_prefix,
            "keys": keys[:100],
            "key_count": len(keys),
            "terms_key": self._terms_key(),
            "postings_key_pattern": self._postings_key("*"),
            "meta_key": self._meta_key(),
            "meta": self.redis_client.hgetall(self._meta_key()),
            "term_count": len(terms),
            "sample_terms": terms[:term_limit],
            "selected_term": selected_term,
            "selected_postings_key": self._postings_key(selected_term) if selected_term else "",
            "postings": rows,
            "posting_count_for_selected_term": int(self.redis_client.zcard(self._postings_key(selected_term)))
            if selected_term
            else 0,
        }

    def _postings(self, term: str) -> dict[int, float]:
        rows = self.redis_client.zrevrange(self._postings_key(term), 0, -1, withscores=True)
        postings: dict[int, float] = {}
        for member, score in rows:
            postings[int(member)] = float(score)
        return postings

    def _write_redis_index(self) -> None:
        pipeline = self.redis_client.pipeline()
        for term, postings in self.inverted.items():
            pipeline.sadd(self._terms_key(), term)
            pipeline.zadd(self._postings_key(term), {str(doc_id): weight for doc_id, weight in postings.items()})
        pipeline.execute()
        self._write_redis_meta()

    def _write_document_to_redis(self, document_id: int) -> None:
        pipeline = self.redis_client.pipeline()
        for term, weight in self.document_terms[document_id].items():
            pipeline.sadd(self._terms_key(), term)
            pipeline.zadd(self._postings_key(term), {str(document_id): weight})
        pipeline.execute()

    def _write_redis_meta(self) -> None:
        self.redis_client.hset(
            self._meta_key(),
            mapping={
                "backend": self.backend_name,
                "last_rebuilt_at": self.last_rebuilt_at,
                "document_count": str(len(self.documents)),
            },
        )

    def _cleanup_empty_terms(self, terms: list[str]) -> None:
        pipeline = self.redis_client.pipeline()
        for term in terms:
            if int(self.redis_client.zcard(self._postings_key(term))) == 0:
                pipeline.delete(self._postings_key(term))
                pipeline.srem(self._terms_key(), term)
        pipeline.execute()

    def _clear_redis(self) -> None:
        keys = list(self.redis_client.scan_iter(match=f"{self.key_prefix}:*"))
        if keys:
            self.redis_client.delete(*keys)

    def _terms_key(self) -> str:
        return f"{self.key_prefix}:terms"

    def _postings_key(self, term: str) -> str:
        return f"{self.key_prefix}:postings:{term}"

    def _meta_key(self) -> str:
        return f"{self.key_prefix}:meta"


def _mask_redis_url(redis_url: str) -> str:
    parsed = urlsplit(redis_url)
    if not parsed.password:
        return redis_url
    username = parsed.username or ""
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    userinfo = f"{username}:***@" if username else "***@"
    return urlunsplit((parsed.scheme, f"{userinfo}{hostname}{port}", parsed.path, parsed.query, parsed.fragment))


def _requests_session():
    return requests.Session()


class MeiliSearchIndex(InMemoryTfIdfIndex):
    """Meilisearch-backed ranking adapter.

    Meilisearch owns candidate retrieval. The Python process keeps SearchDocument
    objects and re-ranks Meilisearch candidates with the local vertical scoring
    rules so domain-specific boosts still apply.
    """

    backend_name = "meilisearch"

    def __init__(
        self,
        meili_url: str = "http://localhost:7700",
        api_key: str = "",
        index_uid: str = "erfairy_documents",
    ) -> None:
        super().__init__()
        self.meili_url = meili_url.rstrip("/")
        self.api_key = api_key
        self.index_uid = index_uid
        self.session = _requests_session()
        try:
            self._request("GET", "/health")
        except Exception as exc:  # pragma: no cover - exact requests exception type is environment-dependent.
            raise RuntimeError(
                f"Cannot connect to Meilisearch at {self.meili_url}. "
                "Start Meilisearch or switch ERFAIRY_INDEX_BACKEND back to memory."
            ) from exc
        self._ensure_index()

    def rebuild(self, documents: list[SearchDocument]) -> None:
        self.clear()
        for document in documents:
            InMemoryTfIdfIndex.add(self, document)
        self.last_rebuilt_at = utc_now_iso()
        self._delete_all_documents()
        self._add_documents_to_meili(list(self.documents.values()))

    def upsert_many(self, documents: list[SearchDocument]) -> None:
        if not documents:
            return
        for document in documents:
            InMemoryTfIdfIndex.add(self, document)
        self.last_rebuilt_at = utc_now_iso()
        self._add_documents_to_meili(documents)

    def delete_many(self, document_ids: list[int]) -> None:
        if not document_ids:
            return
        for document_id in document_ids:
            InMemoryTfIdfIndex.remove(self, document_id)
            self._wait_for_task(self._request("DELETE", f"/indexes/{self.index_uid}/documents/{document_id}"))
        self.last_rebuilt_at = utc_now_iso()

    def search(
        self,
        query: str,
        category: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[tuple[SearchDocument, float]], int]:
        explanation = self.explain(query, category=category, limit=limit, offset=offset)
        return [(item.document, item.final_score) for item in explanation.results], explanation.candidate_count

    def explain(
        self,
        query: str,
        category: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> SearchExplanation:
        query_terms = tokenize(query)
        if not query_terms:
            return SearchExplanation(query=query, tokens=[], candidate_count=0, missing_terms=[], results=[])

        fetch_limit = min(max(offset + limit, 50), 200)
        body = {
            "q": query,
            "limit": fetch_limit,
            "offset": 0,
            "attributesToRetrieve": ["id"],
            "showRankingScore": True,
        }
        if category:
            body["filter"] = f"category = {self._quote_filter_value(category)}"
        payload = self._request("POST", f"/indexes/{self.index_uid}/search", json=body)
        hits = payload.get("hits", [])
        meili_rank: dict[int, float] = {}
        for rank, hit in enumerate(hits):
            doc_id = int(hit["id"])
            meili_rank[doc_id] = float(hit.get("_rankingScore") or (1.0 / (rank + 1)))

        local_explanation = InMemoryTfIdfIndex.explain(self, query, category=category)
        reranked: list[DocumentScoreExplanation] = []
        for item in local_explanation.results:
            doc_id = item.document.id
            if doc_id not in meili_rank:
                continue
            meili_tiebreaker = meili_rank[doc_id] * 0.001
            reranked.append(
                DocumentScoreExplanation(
                    document=item.document,
                    field_matches=item.field_matches,
                    tfidf_score=item.tfidf_score,
                    boost_score=item.boost_score + meili_tiebreaker,
                    final_score=item.final_score + meili_tiebreaker,
                )
            )
        reranked.sort(key=lambda item: item.final_score, reverse=True)
        page_results = reranked[offset : offset + limit]
        return SearchExplanation(
            query=query,
            tokens=query_terms,
            candidate_count=len(reranked),
            missing_terms=local_explanation.missing_terms,
            results=page_results,
        )

    def stats(self) -> IndexStats:
        stats = super().stats()
        return IndexStats(
            document_count=stats.document_count,
            term_count=stats.term_count,
            posting_count=stats.posting_count,
            last_rebuilt_at=stats.last_rebuilt_at,
            backend=self.backend_name,
        )

    def _ensure_index(self) -> None:
        response = self.session.request(
            "GET",
            f"{self.meili_url}/indexes/{self.index_uid}",
            headers=self._headers(),
            timeout=10,
        )
        if response.status_code == 404:
            task = self._request("POST", "/indexes", json={"uid": self.index_uid, "primaryKey": "id"})
            self._wait_for_task(task)
        else:
            response.raise_for_status()
        filter_task = self._request(
            "PUT",
            f"/indexes/{self.index_uid}/settings/filterable-attributes",
            json=["category"],
        )
        self._wait_for_task(filter_task)

    def _delete_all_documents(self) -> None:
        task = self._request("DELETE", f"/indexes/{self.index_uid}/documents")
        self._wait_for_task(task)

    def _add_documents_to_meili(self, documents: list[SearchDocument]) -> None:
        if not documents:
            return
        payload = [self._document_payload(document) for document in documents]
        task = self._request("POST", f"/indexes/{self.index_uid}/documents", json=payload)
        self._wait_for_task(task)

    def _document_payload(self, document: SearchDocument) -> dict:
        data = document.as_dict()
        data["id"] = document.id
        data["tags_text"] = " ".join(document.tags)
        data["aliases_text"] = " ".join(document.aliases)
        return data

    def _request(self, method: str, path: str, **kwargs) -> dict:
        headers = self._headers(kwargs.pop("headers", {}))
        response = self.session.request(method, f"{self.meili_url}{path}", headers=headers, timeout=10, **kwargs)
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()

    def _headers(self, extra: dict | None = None) -> dict:
        headers = dict(extra or {})
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _wait_for_task(self, payload: dict) -> None:
        task_uid = payload.get("taskUid") or payload.get("uid")
        if task_uid is None:
            return
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            task = self._request("GET", f"/tasks/{task_uid}")
            status = task.get("status")
            if status in {"succeeded", "canceled"}:
                return
            if status == "failed":
                raise RuntimeError(f"Meilisearch task failed: {task}")
            time.sleep(0.05)
        raise TimeoutError(f"Timed out waiting for Meilisearch task {task_uid}")

    def _quote_filter_value(self, value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'


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

    def remove(self, document_id: int) -> None:
        old_terms = list(self.document_terms.get(document_id, {}))
        super().remove(document_id)
        for term in old_terms:
            self.redis_zsets[term] = [(weight, doc_id) for weight, doc_id in self.redis_zsets[term] if doc_id != document_id]
            if not self.redis_zsets[term]:
                self.redis_zsets.pop(term, None)

    def _postings(self, term: str) -> dict[int, float]:
        return {doc_id: weight for weight, doc_id in self.redis_zsets.get(term, [])}
