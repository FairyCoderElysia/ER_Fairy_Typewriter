"""分词、索引、存储与搜索的测试。"""

from __future__ import annotations

from erfairy.indexer import InMemoryTfIdfIndex, RedisZSetLikeIndex, SearchIndex, create_search_index
from erfairy.models import SearchDocument
from erfairy.search import SearchService
from erfairy.store import SQLiteDocumentStore
from erfairy.tokenizer import tokenize


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


def test_sqlite_store_upserts_by_url(tmp_path):
    store = SQLiteDocumentStore(tmp_path / "test.sqlite3")
    first = store.upsert(SearchDocument(url="local://same", title="旧标题", content="旧内容"))
    second = store.upsert(SearchDocument(url="local://same", title="新标题", content="新内容"))
    assert first.id == second.id
    assert store.count() == 1
    assert store.get(second.id).title == "新标题"


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
