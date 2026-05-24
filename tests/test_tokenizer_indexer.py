"""分词、索引、搜索服务和 SQLite 存储的测试。

项目简介：
    测试文件不是“附属品”，而是项目行为说明书：它用可运行断言描述系统应该如何工作。

开发目的：
    防止后续改分词、排序、存储时破坏 MVP 的核心行为。

技术栈：
    pytest、临时目录 tmp_path、断言 assert。

学习目标：
    1. 理解单元测试如何验证小模块。
    2. 理解搜索排序测试为什么要构造很小的文档集合。
    3. 理解 tmp_path 如何避免测试污染真实数据库。

知识点与免费文档：
    - pytest: https://docs.pytest.org/en/stable/
    - pytest tmp_path: https://docs.pytest.org/en/stable/how-to/tmp_path.html
    - Python assert: https://docs.python.org/3/reference/simple_stmts.html#the-assert-statement
"""

from erfairy.indexer import InMemoryTfIdfIndex  # 被测对象：内存 TF-IDF 索引。
from erfairy.models import SearchDocument  # 构造测试文档。
from erfairy.search import SearchService  # 被测对象：搜索服务层。
from erfairy.store import SQLiteDocumentStore  # 被测对象：SQLite 存储层。
from erfairy.tokenizer import tokenize  # 被测对象：分词函数。


def test_tokenize_supports_chinese_and_english():
    """验证分词器能同时处理中文和英文。

    设计思路：
        搜索引擎常遇到“爱莉希雅 Elysia”这种中英混合查询，因此这是基础能力。
    """

    tokens = tokenize("爱莉希雅 Elysia 是粉色妖精小姐")  # 执行分词。
    assert "elysia" in tokens  # 英文应转小写并保留。
    assert "爱莉希雅" in tokens or "爱莉" in tokens  # 中文名应能被 jieba 或 n-gram 召回。
    assert "是" not in tokens  # 停用词应被过滤。


def test_index_ranks_title_and_tags_higher():
    """验证标题/标签命中的文档应排在正文偶然命中的文档前面。"""

    docs = [  # 构造两篇极小文档，便于隔离排序因素。
        SearchDocument(id=1, url="local://1", title="爱莉希雅 角色资料", content="粉色妖精小姐", tags=["崩坏3"]),
        SearchDocument(id=2, url="local://2", title="普通游戏资讯", content="这篇文章提到了爱莉希雅", tags=[]),
    ]
    index = InMemoryTfIdfIndex()  # 创建空索引。
    index.rebuild(docs)  # 把测试文档加入索引。

    results, total = index.search("爱莉希雅")  # 搜索角色名。

    assert total == 2  # 两篇都命中。
    assert results[0][0].id == 1  # 标题命中的第 1 篇应排第一。


def test_exact_title_match_gets_boost():
    """验证标题开头完整命中会获得额外加分。

    设计思路：
        用户搜“原神”时，作品总览应优先于“纳西妲 原神草神资料”这种子页面。
    """

    docs = [
        SearchDocument(id=1, url="local://1", title="原神 提瓦特开放世界", content="开放世界 七国 元素", tags=["原神"]),
        SearchDocument(id=2, url="local://2", title="纳西妲 原神草神资料", content="原神 须弥 草神 角色", tags=["原神", "纳西妲"]),
    ]
    index = InMemoryTfIdfIndex()  # 创建索引。
    index.rebuild(docs)  # 建立倒排索引。

    results, _ = index.search("原神")  # 搜索作品名。

    assert results[0][0].id == 1  # 作品总览应排第一。


def test_search_service_returns_highlighted_snippet():
    """验证搜索服务会返回带 <mark> 的高亮摘要。"""

    doc = SearchDocument(id=1, url="local://1", title="芙莉莲", summary="芙莉莲是精灵魔法使", content="旅行故事")
    index = InMemoryTfIdfIndex()  # 创建索引。
    index.rebuild([doc])  # 只索引一篇文档。
    service = SearchService(index)  # 创建服务层。

    payload = service.search("芙莉莲")  # 执行搜索。

    assert payload["total"] == 1  # 应命中一条。
    assert "<mark>" in payload["results"][0]["snippet"]  # 摘要应包含高亮标签。


def test_index_explain_matches_search_ranking():
    """验证 explain() 和 search() 使用同一套排序结果。"""

    docs = [
        SearchDocument(id=1, url="local://1", title="原神 提瓦特开放世界", content="开放世界 七国 元素", tags=["原神"]),
        SearchDocument(id=2, url="local://2", title="纳西妲 原神草神资料", content="原神 须弥 草神 角色", tags=["原神", "纳西妲"]),
    ]
    index = InMemoryTfIdfIndex()
    index.rebuild(docs)

    ranked, total = index.search("原神")
    explanation = index.explain("原神")

    assert total == explanation.candidate_count
    assert ranked[0][0].id == explanation.results[0].document.id
    assert explanation.results[0].field_matches
    assert explanation.results[0].final_score == ranked[0][1]


def test_index_stats_reports_basic_counts():
    """验证索引状态能报告文档数、token 数和倒排项数量。"""

    doc = SearchDocument(id=1, url="local://1", title="爱莉希雅", content="粉色妖精小姐", tags=["崩坏3"])
    index = InMemoryTfIdfIndex()
    index.rebuild([doc])

    stats = index.stats()

    assert stats.document_count == 1
    assert stats.term_count >= 1
    assert stats.posting_count >= stats.term_count
    assert stats.last_rebuilt_at


def test_sqlite_store_upserts_by_url(tmp_path):
    """验证 SQLite 存储按 URL 去重更新。

    知识点：
        tmp_path 是 pytest 提供的临时目录，不会污染项目 data/erfairy.sqlite3。
    """

    store = SQLiteDocumentStore(tmp_path / "test.sqlite3")  # 使用临时数据库文件。
    first = store.upsert(SearchDocument(url="local://same", title="旧标题", content="旧内容"))  # 第一次插入。
    second = store.upsert(SearchDocument(url="local://same", title="新标题", content="新内容"))  # 同 URL 第二次更新。

    assert first.id == second.id  # 同 URL 应保持同一个 id。
    assert store.count() == 1  # 表里只应有一条记录。
    assert store.get(second.id).title == "新标题"  # 内容应被更新为新标题。
