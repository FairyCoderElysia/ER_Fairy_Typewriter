from erfairy.indexer import InMemoryTfIdfIndex
from erfairy.models import SearchDocument
from erfairy.search import SearchService
from erfairy.store import SQLiteDocumentStore
from erfairy.tokenizer import tokenize


def test_tokenize_supports_chinese_and_english():
    tokens = tokenize("爱莉希雅 Elysia 是粉色妖精小姐")
    assert "elysia" in tokens
    assert "爱莉希雅" in tokens or "爱莉" in tokens
    assert "是" not in tokens


def test_index_ranks_title_and_tags_higher():
    docs = [
        SearchDocument(id=1, url="local://1", title="爱莉希雅 角色资料", content="粉色妖精小姐", tags=["崩坏3"]),
        SearchDocument(id=2, url="local://2", title="普通游戏资讯", content="这篇文章提到了爱莉希雅", tags=[]),
    ]
    index = InMemoryTfIdfIndex()
    index.rebuild(docs)

    results, total = index.search("爱莉希雅")

    assert total == 2
    assert results[0][0].id == 1


def test_exact_title_match_gets_boost():
    docs = [
        SearchDocument(id=1, url="local://1", title="原神 提瓦特开放世界", content="开放世界 七国 元素", tags=["原神"]),
        SearchDocument(id=2, url="local://2", title="纳西妲 原神草神资料", content="原神 须弥 草神 角色", tags=["原神", "纳西妲"]),
    ]
    index = InMemoryTfIdfIndex()
    index.rebuild(docs)

    results, _ = index.search("原神")

    assert results[0][0].id == 1


def test_search_service_returns_highlighted_snippet():
    doc = SearchDocument(id=1, url="local://1", title="芙莉莲", summary="芙莉莲是精灵魔法使", content="旅行故事")
    index = InMemoryTfIdfIndex()
    index.rebuild([doc])
    service = SearchService(index)

    payload = service.search("芙莉莲")

    assert payload["total"] == 1
    assert "<mark>" in payload["results"][0]["snippet"]


def test_sqlite_store_upserts_by_url(tmp_path):
    store = SQLiteDocumentStore(tmp_path / "test.sqlite3")
    first = store.upsert(SearchDocument(url="local://same", title="旧标题", content="旧内容"))
    second = store.upsert(SearchDocument(url="local://same", title="新标题", content="新内容"))

    assert first.id == second.id
    assert store.count() == 1
    assert store.get(second.id).title == "新标题"
