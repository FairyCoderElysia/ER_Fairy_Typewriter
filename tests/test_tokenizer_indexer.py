"""分词、索引、存储与搜索的测试。"""

from __future__ import annotations

from erfairy import indexer as indexer_module
from erfairy.indexer import (
    InMemoryTfIdfIndex,
    MeiliSearchIndex,
    RedisSearchIndex,
    RedisZSetLikeIndex,
    SearchIndex,
    create_search_index,
)
from erfairy.models import CrawlError, SearchDocument
from erfairy.search import SearchService
from erfairy.store import SQLiteDocumentStore
from erfairy.tokenizer import tokenize


class FakeRedis:
    def __init__(self) -> None:
        self.sets: dict[str, set[str]] = {}
        self.zsets: dict[str, dict[str, float]] = {}
        self.hashes: dict[str, dict[str, str]] = {}

    def ping(self) -> bool:
        return True

    def pipeline(self):
        return self

    def execute(self) -> list[object]:
        return []

    def sadd(self, key: str, value: str):
        self.sets.setdefault(key, set()).add(value)
        return 1

    def srem(self, key: str, value: str):
        removed = value in self.sets.get(key, set())
        self.sets.get(key, set()).discard(value)
        return int(removed)

    def zadd(self, key: str, mapping: dict[str, float]):
        self.zsets.setdefault(key, {}).update(mapping)
        return len(mapping)

    def zrem(self, key: str, member: str):
        removed = member in self.zsets.get(key, {})
        self.zsets.get(key, {}).pop(member, None)
        return int(removed)

    def hset(self, key: str, mapping: dict[str, str]):
        self.hashes.setdefault(key, {}).update(mapping)
        return len(mapping)

    def hget(self, key: str, field: str):
        return self.hashes.get(key, {}).get(field)

    def hgetall(self, key: str):
        return dict(self.hashes.get(key, {}))

    def scard(self, key: str) -> int:
        return len(self.sets.get(key, set()))

    def smembers(self, key: str):
        return set(self.sets.get(key, set()))

    def zcard(self, key: str) -> int:
        return len(self.zsets.get(key, {}))

    def zrevrange(self, key: str, start: int, end: int, withscores: bool = False):
        rows = sorted(self.zsets.get(key, {}).items(), key=lambda item: item[1], reverse=True)
        if end == -1:
            sliced = rows[start:]
        else:
            sliced = rows[start : end + 1]
        if withscores:
            return sliced
        return [member for member, _score in sliced]

    def scan_iter(self, match: str):
        prefix = match.removesuffix("*")
        keys = set(self.sets) | set(self.zsets) | set(self.hashes)
        return (key for key in keys if key.startswith(prefix))

    def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            removed += int(self.sets.pop(key, None) is not None)
            removed += int(self.zsets.pop(key, None) is not None)
            removed += int(self.hashes.pop(key, None) is not None)
        return removed


class FakeResponse:
    def __init__(self, payload: dict | list | None = None, status_code: int = 200) -> None:
        self.payload = payload
        self.content = b"{}" if payload is not None else b""
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")
        return None

    def json(self):
        return self.payload


class FakeMeiliSession:
    def __init__(self) -> None:
        self.documents: dict[int, dict] = {}
        self.requests: list[tuple[str, str]] = []
        self.next_task_uid = 1
        self.match_all_queries = False

    def request(self, method: str, url: str, headers=None, timeout=10, **kwargs):
        self.requests.append((method, url))
        path = url.split("http://example.test", 1)[-1]
        if path == "/health":
            return FakeResponse({"status": "available"})
        if path.startswith("/tasks/"):
            return FakeResponse({"status": "succeeded"})
        if method == "GET" and path == "/indexes/test":
            return FakeResponse({"message": "not found"}, status_code=404)
        if method == "POST" and path == "/indexes":
            return self._task()
        if method == "PUT" and path == "/indexes/test/settings/filterable-attributes":
            return self._task()
        if method == "DELETE" and path == "/indexes/test/documents":
            self.documents.clear()
            return self._task()
        if method == "POST" and path == "/indexes/test/documents":
            for document in kwargs["json"]:
                self.documents[int(document["id"])] = document
            return self._task()
        if method == "DELETE" and path.startswith("/indexes/test/documents/"):
            doc_id = int(path.rsplit("/", 1)[-1])
            self.documents.pop(doc_id, None)
            return self._task()
        if method == "POST" and path == "/indexes/test/search":
            body = kwargs["json"]
            query = body["q"].lower()
            hits = []
            for document in self.documents.values():
                haystack = " ".join(
                    [
                        document.get("title", ""),
                        document.get("content", ""),
                        document.get("summary", ""),
                        document.get("tags_text", ""),
                        document.get("aliases_text", ""),
                    ]
                ).lower()
                if query and query not in haystack and not self.match_all_queries:
                    continue
                if body.get("filter") == 'category = "news"' and document.get("category") != "news":
                    continue
                hits.append({"id": document["id"], "_rankingScore": 1.0 / (len(hits) + 1)})
            offset = body.get("offset", 0)
            limit = body.get("limit", 20)
            return FakeResponse({"hits": hits[offset : offset + limit], "estimatedTotalHits": len(hits)})
        raise AssertionError(f"Unexpected Meilisearch request: {method} {path}")

    def _task(self):
        task_uid = self.next_task_uid
        self.next_task_uid += 1
        return FakeResponse({"taskUid": task_uid})


def test_tokenize_supports_chinese_and_english():
    tokens = tokenize("爱莉希雅 Elysia 是粉色妖精小姐")
    assert "elysia" in tokens
    assert any(token in tokens for token in ["爱莉希雅", "爱莉"])
    assert "是" not in tokens


def test_index_ranks_title_and_tags_higher():
    docs = [
        SearchDocument(
            id=1,
            url="local://1",
            title="爱莉希雅 角色资料",
            content="粉色妖精小姐",
            tags=["崩坏3"],
            aliases=["爱莉希雅", "Elysia"],
            entity_type="character",
        ),
        SearchDocument(
            id=2,
            url="local://2",
            title="普通游戏资讯",
            content="这篇文章提到了爱莉希雅",
            tags=[],
            entity_type="news",
        ),
    ]
    index = InMemoryTfIdfIndex()
    index.rebuild(docs)
    results, total = index.search("爱莉希雅")
    assert total == 2
    assert results[0][0].id == 1


def test_alias_lookup_prefers_character_document():
    docs = [
        SearchDocument(
            id=1,
            url="local://1",
            title="崩坏3 角色资料",
            content="爱莉希雅",
            tags=["崩坏3"],
            aliases=["爱莉希雅", "Elysia"],
            entity_type="character",
            game_title="崩坏3",
            character_name="爱莉希雅",
        ),
        SearchDocument(
            id=2,
            url="local://2",
            title="崩坏3 版本新闻",
            content="爱莉希雅同样出现于活动资讯",
            tags=["崩坏3"],
            entity_type="news",
            game_title="崩坏3",
        ),
    ]
    index = InMemoryTfIdfIndex()
    index.rebuild(docs)
    results, _ = index.search("Elysia")
    assert results[0][0].id == 1


def test_stage4_alias_lookup_recalls_official_character_name():
    docs = [
        SearchDocument(
            id=1,
            url="local://raiden",
            title="雷电将军 原神角色资料",
            content="雷电影与永恒、稻妻和梦想一心相关。",
            tags=["原神", "雷电将军"],
            aliases=["雷电将军", "雷神", "影", "Raiden Shogun"],
            entity_type="character",
            game_title="原神",
            character_name="雷电将军",
        ),
        SearchDocument(
            id=2,
            url="local://genshin",
            title="原神 提瓦特开放世界",
            content="原神里有雷神、岩神、草神等角色。",
            tags=["原神"],
            entity_type="work",
            game_title="原神",
        ),
    ]
    index = InMemoryTfIdfIndex()
    index.rebuild(docs)
    results, _ = index.search("雷神")
    assert results[0][0].character_name == "雷电将军"


def test_exact_title_match_gets_boost():
    docs = [
        SearchDocument(
            id=1,
            url="local://1",
            title="原神 提瓦特开放世界",
            content="开放世界",
            tags=["原神"],
            aliases=["Genshin"],
            entity_type="work",
            game_title="原神",
        ),
        SearchDocument(
            id=2,
            url="local://2",
            title="原神 角色资料",
            content="纳西妲",
            tags=["原神"],
            aliases=["Genshin Impact"],
            entity_type="character",
            game_title="原神",
        ),
    ]
    index = InMemoryTfIdfIndex()
    index.rebuild(docs)
    results, _ = index.search("原神")
    assert results[0][0].id == 1


def test_stage4_game_name_prefers_work_over_character():
    docs = [
        SearchDocument(
            id=1,
            url="local://genshin",
            title="原神 提瓦特开放世界",
            content="开放世界游戏总览。",
            tags=["原神"],
            aliases=["Genshin"],
            entity_type="work",
            game_title="原神",
        ),
        SearchDocument(
            id=2,
            url="local://raiden",
            title="雷电将军 原神角色资料",
            content="原神角色资料。",
            tags=["原神", "雷电将军"],
            entity_type="character",
            game_title="原神",
            character_name="雷电将军",
        ),
    ]
    index = InMemoryTfIdfIndex()
    index.rebuild(docs)
    results, _ = index.search("原神")
    assert results[0][0].entity_type == "work"


def test_stage4_character_exact_match_beats_title_tag_and_content_mentions():
    docs = [
        SearchDocument(
            id=1,
            url="local://character",
            title="稻妻角色资料",
            content="雷电将军是原神角色。",
            tags=["原神"],
            aliases=["雷神", "影"],
            entity_type="character",
            game_title="原神",
            character_name="雷电将军",
        ),
        SearchDocument(
            id=2,
            url="local://title",
            title="雷电将军 活动新闻",
            content="活动资讯。",
            tags=["原神"],
            entity_type="news",
            game_title="原神",
        ),
        SearchDocument(
            id=3,
            url="local://tag",
            title="稻妻攻略",
            content="角色培养素材。",
            tags=["雷电将军"],
            entity_type="news",
            game_title="原神",
        ),
        SearchDocument(
            id=4,
            url="local://content",
            title="原神杂谈",
            content="这一段正文提到了雷电将军。",
            tags=["原神"],
            entity_type="news",
            game_title="原神",
        ),
    ]
    index = InMemoryTfIdfIndex()
    index.rebuild(docs)
    results, _ = index.search("雷电将军")
    assert [document.id for document, _score in results] == [1, 2, 3, 4]


def test_stage4_news_intent_prefers_news_document():
    docs = [
        SearchDocument(
            id=1,
            url="local://genshin",
            title="原神 提瓦特开放世界",
            content="原神包含角色、版本和活动。",
            tags=["原神", "游戏"],
            entity_type="work",
            game_title="原神",
            source_score=1.0,
        ),
        SearchDocument(
            id=2,
            url="local://news",
            title="原神 最新版本活动资讯",
            content="最新活动、版本更新和公告汇总。",
            tags=["原神", "资讯", "最新活动"],
            entity_type="news",
            game_title="原神",
            source_score=0.6,
        ),
    ]
    index = InMemoryTfIdfIndex()
    index.rebuild(docs)
    results, _ = index.search("原神 最新活动")
    assert results[0][0].entity_type == "news"


def test_stage4_source_score_is_only_a_light_bonus():
    docs = [
        SearchDocument(
            id=1,
            url="local://exact",
            title="阿米娅 明日方舟角色资料",
            content="阿米娅是罗德岛的公开领袖。",
            tags=["明日方舟"],
            aliases=["Amiya"],
            entity_type="character",
            game_title="明日方舟",
            character_name="阿米娅",
            source_score=0.1,
        ),
        SearchDocument(
            id=2,
            url="local://source",
            title="明日方舟 高质量来源整理",
            content="这篇资料在正文中提到阿米娅。",
            tags=["明日方舟"],
            entity_type="news",
            game_title="明日方舟",
            source_score=10.0,
        ),
    ]
    index = InMemoryTfIdfIndex()
    index.rebuild(docs)
    results, _ = index.search("阿米娅")
    assert results[0][0].id == 1


def test_content_quality_is_light_bonus_for_similar_relevance():
    docs = [
        SearchDocument(
            id=1,
            url="local://daily",
            title="原神 攻略",
            content="原神攻略 配队。",
            tags=["原神", "攻略"],
            content_quality_score=0.2,
            content_quality_labels=["daily-chat"],
        ),
        SearchDocument(
            id=2,
            url="local://guide",
            title="原神 攻略",
            content="原神攻略 配队。",
            tags=["原神", "攻略"],
            content_quality_score=0.9,
            content_quality_labels=["guide"],
        ),
    ]
    index = InMemoryTfIdfIndex()
    index.rebuild(docs)

    results, _ = index.search("原神 攻略")
    explanation = index.explain("原神 攻略")

    assert results[0][0].id == 2
    assert explanation.results[0].quality_score > explanation.results[1].quality_score


def test_content_quality_does_not_beat_much_higher_relevance():
    docs = [
        SearchDocument(
            id=1,
            url="local://relevant",
            title="原神 雷电将军攻略",
            content="雷电将军圣遗物配队。",
            tags=["原神", "攻略"],
            content_quality_score=0.5,
        ),
        SearchDocument(
            id=2,
            url="local://quality",
            title="原神 高质量资料",
            content="这是官方精选资料。",
            tags=["原神"],
            content_quality_score=1.0,
            content_quality_labels=["official", "good"],
        ),
    ]
    index = InMemoryTfIdfIndex()
    index.rebuild(docs)

    results, _ = index.search("雷电将军攻略")

    assert results[0][0].id == 1


def test_stage5_news_freshness_prefers_recent_news_for_news_intent():
    docs = [
        SearchDocument(
            id=1,
            url="local://old",
            title="原神 最新活动公告",
            content="原神最新活动公告。",
            tags=["原神", "活动"],
            entity_type="news",
            category="news",
            published_at="2024-01-01T00:00:00+00:00",
        ),
        SearchDocument(
            id=2,
            url="local://recent",
            title="原神 最新活动公告",
            content="原神最新活动公告。",
            tags=["原神", "活动"],
            entity_type="news",
            category="news",
            published_at="2026-05-27T00:00:00+00:00",
        ),
    ]
    index = InMemoryTfIdfIndex()
    index.rebuild(docs)
    results, _ = index.search("原神 最新活动")
    assert results[0][0].id == 2


def test_stage5_freshness_does_not_affect_non_news_intent_query():
    docs = [
        SearchDocument(
            id=1,
            url="local://old",
            title="原神 角色资料",
            content="原神角色资料。",
            tags=["原神"],
            entity_type="work",
            category="anime",
            published_at="2024-01-01T00:00:00+00:00",
        ),
        SearchDocument(
            id=2,
            url="local://recent",
            title="原神 角色资料",
            content="原神角色资料。",
            tags=["原神"],
            entity_type="work",
            category="anime",
            published_at="2026-05-27T00:00:00+00:00",
        ),
    ]
    index = InMemoryTfIdfIndex()
    index.rebuild(docs)
    results, _ = index.search("原神")
    assert results[0][0].id == 1


def test_search_service_returns_highlighted_snippet():
    doc = SearchDocument(
        id=1,
        url="local://1",
        title="芙莉莲",
        summary="芙莉莲是精灵魔法使",
        content="旅行故事",
    )
    index = InMemoryTfIdfIndex()
    index.rebuild([doc])
    service = SearchService(index)
    payload = service.search("芙莉莲")
    assert payload["total"] == 1
    assert "<mark>" in payload["results"][0]["snippet"]


def test_index_explain_matches_search_ranking():
    docs = [
        SearchDocument(
            id=1,
            url="local://1",
            title="原神 提瓦特开放世界",
            content="开放世界",
            tags=["原神"],
            aliases=["Genshin"],
            entity_type="work",
            game_title="原神",
        ),
        SearchDocument(
            id=2,
            url="local://2",
            title="原神 角色资料",
            content="纳西妲",
            tags=["原神"],
            aliases=["Genshin Impact"],
            entity_type="character",
            game_title="原神",
        ),
    ]
    index = InMemoryTfIdfIndex()
    index.rebuild(docs)
    ranked, total = index.search("原神")
    explanation = index.explain("原神")
    assert total == explanation.candidate_count
    assert ranked[0][0].id == explanation.results[0].document.id
    assert explanation.results[0].field_matches


def test_index_stats_reports_basic_counts():
    doc = SearchDocument(id=1, url="local://1", title="爱莉希雅", content="粉色妖精小姐", tags=["崩坏3"])
    index = InMemoryTfIdfIndex()
    index.rebuild([doc])
    stats = index.stats()
    assert stats.document_count == 1
    assert stats.term_count >= 1
    assert stats.posting_count >= stats.term_count
    assert stats.last_rebuilt_at


def test_inmemory_index_implements_search_index_protocol():
    index = InMemoryTfIdfIndex()
    assert isinstance(index, SearchIndex)


def test_stage6_can_create_index_backends_by_name():
    assert isinstance(create_search_index("memory"), InMemoryTfIdfIndex)
    assert isinstance(create_search_index("redis-zset"), RedisZSetLikeIndex)


def test_stage6_can_create_real_redis_backend_by_name(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setenv("ERFAIRY_REDIS_URL", "redis://example.test:6379/9")
    monkeypatch.setenv("ERFAIRY_REDIS_PREFIX", "test-prefix")
    monkeypatch.setattr(indexer_module, "_redis_from_url", lambda redis_url: fake)

    index = create_search_index("redis")

    assert isinstance(index, RedisSearchIndex)
    assert index.redis_url == "redis://example.test:6379/9"
    assert index.key_prefix == "test-prefix"


def test_stage6_can_create_meilisearch_backend_by_name(monkeypatch):
    fake = FakeMeiliSession()
    monkeypatch.setenv("ERFAIRY_MEILI_URL", "http://example.test")
    monkeypatch.setenv("ERFAIRY_MEILI_MASTER_KEY", "secret")
    monkeypatch.setenv("ERFAIRY_MEILI_INDEX", "test")
    monkeypatch.setattr(indexer_module, "_requests_session", lambda: fake)

    index = create_search_index("meilisearch")

    assert isinstance(index, MeiliSearchIndex)
    assert index.meili_url == "http://example.test"
    assert index.api_key == "secret"
    assert index.index_uid == "test"


def test_stage6_redis_zset_like_index_matches_memory_top_result():
    docs = [
        SearchDocument(
            id=1,
            url="local://raiden",
            title="雷电将军 原神角色资料",
            content="雷电将军是原神角色。",
            tags=["原神"],
            aliases=["雷神", "影"],
            entity_type="character",
            game_title="原神",
            character_name="雷电将军",
        ),
        SearchDocument(
            id=2,
            url="local://news",
            title="原神 最新活动新闻",
            content="最新活动公告。",
            tags=["原神", "活动"],
            entity_type="news",
            game_title="原神",
        ),
    ]
    memory = InMemoryTfIdfIndex()
    redis_like = RedisZSetLikeIndex()
    memory.rebuild(docs)
    redis_like.rebuild(docs)

    memory_results, memory_total = memory.search("雷神")
    redis_results, redis_total = redis_like.search("雷神")

    assert redis_total == memory_total
    assert redis_results[0][0].id == memory_results[0][0].id
    assert redis_like.stats().backend == "redis-zset-like"
    assert redis_like.redis_zsets


def test_stage6_incremental_upsert_replaces_existing_memory_terms():
    index = InMemoryTfIdfIndex()
    index.rebuild([SearchDocument(id=1, url="local://one", title="Raiden profile", content="Electro archon")])

    index.upsert_many([SearchDocument(id=1, url="local://one", title="Nahida profile", content="Dendro archon")])

    old_results, old_total = index.search("Raiden")
    new_results, new_total = index.search("Nahida")
    assert old_total == 0
    assert old_results == []
    assert new_total == 1
    assert new_results[0][0].id == 1


def test_stage6_incremental_delete_removes_memory_terms():
    index = InMemoryTfIdfIndex()
    index.rebuild([SearchDocument(id=1, url="local://one", title="Raiden profile", content="Electro archon")])

    index.delete_many([1])

    results, total = index.search("Raiden")
    stats = index.stats()
    assert total == 0
    assert results == []
    assert stats.document_count == 0
    assert stats.term_count == 0


def test_stage6_real_redis_index_writes_zsets_and_matches_memory(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(indexer_module, "_redis_from_url", lambda redis_url: fake)
    docs = [
        SearchDocument(
            id=1,
            url="local://raiden",
            title="Raiden Shogun character profile",
            content="Raiden Shogun is an Electro character.",
            tags=["Genshin"],
            aliases=["Raiden"],
            entity_type="character",
            game_title="Genshin",
            character_name="Raiden Shogun",
        ),
        SearchDocument(
            id=2,
            url="local://news",
            title="Genshin latest event news",
            content="Latest event announcement.",
            tags=["Genshin", "event"],
            entity_type="news",
            game_title="Genshin",
        ),
    ]
    memory = InMemoryTfIdfIndex()
    redis_index = RedisSearchIndex(redis_url="redis://example.test:6379/0", key_prefix="test")
    memory.rebuild(docs)
    redis_index.rebuild(docs)

    memory_results, memory_total = memory.search("Raiden")
    redis_results, redis_total = redis_index.search("Raiden")
    stats = redis_index.stats()

    assert redis_total == memory_total
    assert redis_results[0][0].id == memory_results[0][0].id
    assert stats.backend == "redis"
    assert stats.term_count >= 1
    assert stats.posting_count >= stats.term_count
    assert fake.zsets


def test_stage6_real_redis_incremental_upsert_replaces_old_postings(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(indexer_module, "_redis_from_url", lambda redis_url: fake)
    redis_index = RedisSearchIndex(redis_url="redis://example.test:6379/0", key_prefix="test")
    redis_index.rebuild([SearchDocument(id=1, url="local://one", title="Raiden profile", content="Electro archon")])

    redis_index.upsert_many([SearchDocument(id=1, url="local://one", title="Nahida profile", content="Dendro archon")])

    old_results, old_total = redis_index.search("Raiden")
    new_results, new_total = redis_index.search("Nahida")
    assert old_total == 0
    assert old_results == []
    assert new_total == 1
    assert new_results[0][0].id == 1
    assert "1" not in fake.zsets.get("test:postings:raiden", {})
    assert "1" in fake.zsets["test:postings:nahida"]


def test_stage6_real_redis_incremental_delete_removes_postings(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(indexer_module, "_redis_from_url", lambda redis_url: fake)
    redis_index = RedisSearchIndex(redis_url="redis://example.test:6379/0", key_prefix="test")
    redis_index.rebuild([SearchDocument(id=1, url="local://one", title="Raiden profile", content="Electro archon")])

    redis_index.delete_many([1])

    results, total = redis_index.search("Raiden")
    stats = redis_index.stats()
    assert total == 0
    assert results == []
    assert stats.document_count == 0
    assert "test:postings:raiden" not in fake.zsets
    assert "raiden" not in fake.sets.get("test:terms", set())


def test_stage6_real_redis_debug_snapshot_shows_keys_terms_and_postings(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(indexer_module, "_redis_from_url", lambda redis_url: fake)
    redis_index = RedisSearchIndex(redis_url="redis://user:secret@example.test:6379/0", key_prefix="test")
    redis_index.rebuild(
        [
            SearchDocument(
                id=1,
                url="local://raiden",
                title="Raiden Shogun character profile",
                content="Raiden Shogun is an Electro character.",
                aliases=["Raiden"],
                entity_type="character",
            )
        ]
    )

    snapshot = redis_index.debug_snapshot(term="raiden")

    assert snapshot["available"] is True
    assert snapshot["backend"] == "redis"
    assert snapshot["redis_url"] == "redis://user:***@example.test:6379/0"
    assert snapshot["key_prefix"] == "test"
    assert "test:terms" in snapshot["keys"]
    assert "raiden" in snapshot["sample_terms"]
    assert snapshot["selected_postings_key"] == "test:postings:raiden"
    assert snapshot["postings"][0]["doc_id"] == 1
    assert snapshot["postings"][0]["title"] == "Raiden Shogun character profile"


def test_stage6_meilisearch_backend_searches_and_filters(monkeypatch):
    fake = FakeMeiliSession()
    monkeypatch.setattr(indexer_module, "_requests_session", lambda: fake)
    index = MeiliSearchIndex(meili_url="http://example.test", api_key="", index_uid="test")
    index.rebuild(
        [
            SearchDocument(id=1, url="local://raiden", title="Raiden Shogun profile", content="Electro archon"),
            SearchDocument(
                id=2,
                url="local://news",
                title="Raiden event news",
                content="Latest event",
                category="news",
            ),
        ]
    )

    results, total = index.search("Raiden", category="news")
    explanation = index.explain("Raiden", category="news")

    assert total == 1
    assert results[0][0].id == 2
    assert explanation.results[0].document.id == 2
    assert index.stats().backend == "meilisearch"


def test_stage6_meilisearch_backend_reranks_candidates_with_local_vertical_score(monkeypatch):
    fake = FakeMeiliSession()
    fake.match_all_queries = True
    monkeypatch.setattr(indexer_module, "_requests_session", lambda: fake)
    index = MeiliSearchIndex(meili_url="http://example.test", api_key="", index_uid="test")
    index.rebuild(
        [
            SearchDocument(
                id=1,
                url="local://your-name",
                title="Your Name Shinkai anime movie",
                content="A famous animated movie.",
                category="anime",
                entity_type="work",
            ),
            SearchDocument(
                id=2,
                url="local://genshin",
                title="Genshin Impact open world",
                content="Genshin Impact character and game profile.",
                aliases=["原神", "Genshin"],
                category="anime",
                entity_type="work",
                game_title="Genshin Impact",
            ),
        ]
    )

    results, total = index.search("原神")

    assert total == 1
    assert results[0][0].id == 2
    assert results[0][1] > 1.0


def test_stage6_meilisearch_backend_incremental_update_and_delete(monkeypatch):
    fake = FakeMeiliSession()
    monkeypatch.setattr(indexer_module, "_requests_session", lambda: fake)
    index = MeiliSearchIndex(meili_url="http://example.test", api_key="", index_uid="test")
    index.rebuild([SearchDocument(id=1, url="local://one", title="Raiden profile", content="Electro")])

    index.upsert_many([SearchDocument(id=1, url="local://one", title="Nahida profile", content="Dendro")])
    old_results, old_total = index.search("Raiden")
    new_results, new_total = index.search("Nahida")

    assert old_total == 0
    assert old_results == []
    assert new_total == 1
    assert new_results[0][0].id == 1

    index.delete_many([1])
    deleted_results, deleted_total = index.search("Nahida")

    assert deleted_total == 0
    assert deleted_results == []
    assert 1 not in fake.documents


def test_sqlite_store_upserts_by_url(tmp_path):
    store = SQLiteDocumentStore(tmp_path / "test.sqlite3")
    first = store.upsert(SearchDocument(url="local://same", title="旧标题", content="旧内容"))
    second = store.upsert(SearchDocument(url="local://same", title="新标题", content="新内容"))
    assert first.id == second.id
    assert store.count() == 1
    assert store.get(second.id).title == "新标题"


def test_sqlite_store_persists_content_quality_metadata(tmp_path):
    store = SQLiteDocumentStore(tmp_path / "test.sqlite3")
    saved = store.upsert(
        SearchDocument(
            url="local://quality",
            title="角色攻略",
            content="养成配队",
            content_quality_score=0.82,
            content_quality_labels=["guide", "character-build"],
        )
    )

    loaded = store.get(saved.id)

    assert loaded.content_quality_score == 0.82
    assert loaded.content_quality_labels == ["guide", "character-build"]


def test_sqlite_store_migrates_content_quality_defaults(tmp_path):
    db_path = tmp_path / "legacy.sqlite3"
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE documents (
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

    store = SQLiteDocumentStore(db_path)
    saved = store.upsert(SearchDocument(url="local://legacy", title="旧数据", content="正文"))
    loaded = store.get(saved.id)

    assert loaded.content_quality_score == 0.5
    assert loaded.content_quality_labels == []


def test_sqlite_store_deletes_document_by_id(tmp_path):
    store = SQLiteDocumentStore(tmp_path / "test.sqlite3")
    document = store.upsert(SearchDocument(url="local://delete", title="Delete me", content="temporary"))

    assert document.id is not None
    assert store.delete(document.id) is True
    assert store.delete(document.id) is False
    assert store.get(document.id) is None
    assert store.count() == 0


def test_sqlite_store_lists_recent_crawl_runs_with_errors(tmp_path):
    store = SQLiteDocumentStore(tmp_path / "test.sqlite3")
    run_id = store.start_crawl_run(category="news")
    store.save_crawl_errors(
        run_id,
        [
            CrawlError(
                url="https://example.com/fail",
                stage="download",
                message="timeout",
                depth=1,
                category="news",
                crawled_at="2026-05-28T00:00:00+00:00",
            )
        ],
    )
    store.finish_crawl_run(
        run_id,
        source_count=1,
        saved_count=2,
        error_count=1,
        category="news",
        status="completed",
    )

    runs = store.recent_crawl_runs(limit=5)

    assert len(runs) == 1
    assert runs[0]["id"] == run_id
    assert runs[0]["status"] == "completed"
    assert runs[0]["saved_count"] == 2
    assert runs[0]["error_count"] == 1
    assert runs[0]["errors"][0]["url"] == "https://example.com/fail"
    assert runs[0]["errors"][0]["message"] == "timeout"


def test_sqlite_store_deduplicates_by_content_hash(tmp_path):
    store = SQLiteDocumentStore(tmp_path / "test.sqlite3")
    first = store.upsert(
        SearchDocument(
            url="local://canonical",
            title="雷电将军资料",
            content="同一篇正文",
            content_hash="same-content",
        )
    )
    second = store.upsert(
        SearchDocument(
            url="local://copy",
            title="雷电将军资料副本",
            content="同一篇正文",
            content_hash="same-content",
        )
    )

    assert first.id == second.id
    assert second.url == "local://canonical"
    assert store.count() == 1
    assert store.get(second.id).title == "雷电将军资料副本"


def test_sqlite_store_deduplicates_by_similar_title(tmp_path):
    store = SQLiteDocumentStore(tmp_path / "test.sqlite3")
    first = store.upsert(
        SearchDocument(
            url="local://raiden-a",
            title="雷电将军 原神角色资料",
            content="第一版正文",
            category="anime",
            source="fixture",
        )
    )
    second = store.upsert(
        SearchDocument(
            url="local://raiden-b",
            title="雷电将军原神角色资料",
            content="第二版正文，有轻微更新。",
            category="anime",
            source="fixture",
        )
    )

    assert first.id == second.id
    assert second.url == "local://raiden-a"
    assert store.count() == 1
    assert store.get(second.id).content == "第二版正文，有轻微更新。"
