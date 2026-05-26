"""分词、索引、存储与搜索的测试。"""

from __future__ import annotations

from erfairy.indexer import InMemoryTfIdfIndex, SearchIndex
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


def test_sqlite_store_upserts_by_url(tmp_path):
    store = SQLiteDocumentStore(tmp_path / "test.sqlite3")
    first = store.upsert(SearchDocument(url="local://same", title="旧标题", content="旧内容"))
    second = store.upsert(SearchDocument(url="local://same", title="新标题", content="新内容"))
    assert first.id == second.id
    assert store.count() == 1
    assert store.get(second.id).title == "新标题"
