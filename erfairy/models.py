"""ER Fairy Typewriter 的核心数据模型。

项目简介：
    本项目是一个轻量级二次元搜索引擎 MVP，用来学习“文档 -> 存储 -> 索引 -> 搜索 -> 展示”的完整链路。

开发目的：
    把搜索引擎里的抽象概念落成 Python 对象，让后续 SQLite、索引器、API、模板都围绕同一套数据结构协作。

技术栈：
    Python dataclasses、类型注解、UTC 时间、字典序列化。

学习目标：
    1. 理解“文档模型”和“搜索结果模型”的区别。
    2. 学会用 dataclass 表达结构化数据。
    3. 理解为什么 Web API 最终需要把对象转成 dict/JSON。

知识点与免费文档：
    - dataclasses: https://docs.python.org/3/library/dataclasses.html
    - datetime/timezone: https://docs.python.org/3/library/datetime.html
    - typing: https://docs.python.org/3/library/typing.html
"""

from __future__ import annotations  # 知识点：延迟解析类型注解，减少循环引用/前向引用带来的麻烦。

from dataclasses import dataclass, field  # dataclass 用来少写样板代码；field 用来处理 list 这类可变默认值。
from datetime import datetime, timezone  # datetime 负责生成抓取时间；timezone.utc 保证时间不受本机时区影响。
from typing import Any  # Any 表示字典里的值可能是 int/str/list/float 等多种类型。


def utc_now_iso() -> str:
    """返回当前 UTC 时间的 ISO 字符串。

    入参：
        无。

    出参：
        str，例如 "2026-05-22T10:30:00+00:00"。

    使用场景：
        给每篇文档记录 crawled_at，方便以后做增量抓取、新鲜度排序和调试。

    设计思路：
        使用 UTC 而不是本地时间，是为了避免部署到不同时区后出现时间排序混乱。
    """

    return datetime.now(timezone.utc).isoformat(timespec="seconds")  # 生成带时区的秒级时间，秒级足够搜索 MVP 使用。


@dataclass(slots=True)  # slots=True 减少对象内存开销；文档多起来后比普通对象更省。
class SearchDocument:
    """搜索引擎中的一篇结构化文档。

    字段说明：
        url: 文档来源地址，用于去重和跳转原文。
        title: 标题，通常比正文更能代表主题，因此索引权重较高。
        content: 正文内容，是搜索召回的主要文本来源。
        summary: 摘要，用于搜索结果展示和轻量命中。
        tags: 标签列表，用于表达作品名、角色名、题材等主题词。
        aliases: 别名列表，用于支持简称、外文名、玩家常用称呼等查询。
        entity_type: 实体类型，例如 character、work、news。
        game_title: 所属游戏或作品名，帮助角色和作品建立关联。
        character_name: 角色正式名，适合做角色搜索的精确命中加权。
        source_score: 来源质量分，目前作为排序中的轻微加分。
        content_hash: 正文内容指纹，用于发现同内容不同 URL 的重复文档。
        category: 内容分类，首版默认 anime，也可以扩展 game、character、news。
        source: 来源站点或数据来源名称。
        published_at: 发布时间，后续可用于新鲜度排序。
        crawled_at: 抓取或写入时间，默认使用当前 UTC 时间。
        image_url: 结果展示图片。
        id: SQLite 入库后的主键，索引阶段需要用它作为 doc_id。

    设计思路：
        用一个 dataclass 统一承载爬虫、存储、索引、搜索和 API 之间传递的数据，
        比在不同模块里传散乱 dict 更容易维护字段含义，也更适合新手复盘数据流。
    """

    url: str
    title: str
    content: str
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    entity_type: str = ""
    game_title: str = ""
    character_name: str = ""
    source_score: float = 0.0
    content_hash: str = ""
    category: str = "anime"
    source: str = ""
    published_at: str = ""
    crawled_at: str = field(default_factory=utc_now_iso)
    image_url: str = ""
    id: int | None = None

    def as_dict(self) -> dict[str, Any]:
        """把文档对象转换成 API/模板容易使用的字典。

        使用场景：
            FastAPI 返回 JSON、Jinja2 模板渲染结果页、调试接口展示文档详情时，
            都需要把 Python 对象转换成普通 dict。

        设计思路：
            字段映射集中放在这里，后续新增字段时只需要维护一个出口，
            避免多个接口各自拼装 dict 导致遗漏或字段名不一致。
        """

        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "summary": self.summary,
            "tags": self.tags,
            "aliases": self.aliases,
            "entity_type": self.entity_type,
            "game_title": self.game_title,
            "character_name": self.character_name,
            "source_score": self.source_score,
            "content_hash": self.content_hash,
            "category": self.category,
            "source": self.source,
            "published_at": self.published_at,
            "crawled_at": self.crawled_at,
            "image_url": self.image_url,
        }


@dataclass(slots=True)
class SearchResult:
    """搜索结果结构，封装“文档 + 分数 + 高亮片段”。

    入参/字段：
        document: 命中的原始文档。
        score: 排序分数，越大越靠前。
        snippet: 摘要片段，可能带 <mark> 高亮标签。

    使用场景：
        SearchService 把 indexer 返回的 (document, score) 包装成面向前端/API 的结果。
    """

    document: SearchDocument  # 命中文档。
    score: float  # 相关性分数；由 TF-IDF/余弦相似度和精确命中加权组成。
    snippet: str  # 展示片段；由 search.py 生成。

    def as_dict(self) -> dict[str, Any]:
        """把搜索结果转成 API 友好的字典。

        设计思路：
            复用 document.as_dict()，避免重复维护字段映射；再额外附加 score/snippet。
        """

        data = self.document.as_dict()  # 先得到文档字段。
        data["score"] = round(self.score, 6)  # 分数保留 6 位，避免 JSON 里出现过长浮点数。
        data["snippet"] = self.snippet  # 加入高亮片段。
        return data  # 返回完整结果字典。


@dataclass(slots=True)
class FieldMatch:
    """单个字段里某个查询词的得分贡献。

    使用场景：
        `/debug/search` 需要告诉学习者：某个词是在标题、标签、摘要还是正文中贡献了分数。
    """

    field: str  # 命中的字段名，例如 title/tags/summary/content。
    term: str  # 命中的查询 token。
    tf: float  # 该 token 在字段中的加权词频。
    idf: float  # 该 token 的逆文档频率，越稀有通常越重要。
    field_weight: float  # 字段权重，例如 title 通常高于 content。
    contribution: float  # 该字段命中对原始点积分数的贡献。

    def as_dict(self) -> dict[str, Any]:
        """转成 JSON 友好的字典。"""

        return {
            "field": self.field,
            "term": self.term,
            "tf": round(self.tf, 6),
            "idf": round(self.idf, 6),
            "field_weight": round(self.field_weight, 6),
            "contribution": round(self.contribution, 6),
        }


@dataclass(slots=True)
class DocumentScoreExplanation:
    """单篇候选文档的排序解释。

    使用场景：
        调试某个结果为什么排在前面，尤其适合学习 TF-IDF、字段权重和 boost 的关系。
    """

    document: SearchDocument  # 被解释的文档。
    field_matches: list[FieldMatch]  # 字段级命中明细。
    tfidf_score: float  # 余弦归一化后的 TF-IDF 分数。
    boost_score: float  # 标题/标签/摘要完整命中的额外加分。
    final_score: float  # 最终排序分数。

    def as_dict(self) -> dict[str, Any]:
        """转成 `/debug/search` 可直接返回的字典。"""

        return {
            "document": {
                "id": self.document.id,
                "url": self.document.url,
                "title": self.document.title,
                "summary": self.document.summary,
                "tags": self.document.tags,
                "aliases": self.document.aliases,
                "entity_type": self.document.entity_type,
                "game_title": self.document.game_title,
                "character_name": self.document.character_name,
                "source_score": self.document.source_score,
                "category": self.document.category,
                "source": self.document.source,
            },
            "field_matches": [match.as_dict() for match in self.field_matches],
            "tfidf_score": round(self.tfidf_score, 6),
            "boost_score": round(self.boost_score, 6),
            "final_score": round(self.final_score, 6),
        }


@dataclass(slots=True)
class SearchExplanation:
    """一次搜索请求的完整解释结构。

    使用场景：
        普通搜索可以用它排序，`/debug/search` 可以把它展示给学习者，评测集可以用它定位失败原因。
    """

    query: str  # 原始查询词。
    tokens: list[str]  # 查询分词结果。
    candidate_count: int  # 进入排序阶段的候选文档数量。
    missing_terms: list[str]  # 没有命中任何文档的查询 token。
    results: list[DocumentScoreExplanation]  # 排序后的文档解释列表。

    def as_dict(self) -> dict[str, Any]:
        """转成 API 友好的字典。"""

        return {
            "query": self.query,
            "tokens": self.tokens,
            "candidate_count": self.candidate_count,
            "missing_terms": self.missing_terms,
            "results": [result.as_dict() for result in self.results],
        }


@dataclass(slots=True)
class IndexStats:
    """索引状态摘要。

    使用场景：
        后续索引状态页可以展示文档数、token 数、倒排项数量和重建时间。
    """

    document_count: int  # 索引中的文档数。
    term_count: int  # 不同 token 的数量。
    posting_count: int  # 倒排表中的 term-doc 关系数量。
    last_rebuilt_at: str  # 最近一次重建索引时间。
    backend: str = "memory"  # 当前索引后端名称。

    def as_dict(self) -> dict[str, Any]:
        """转成状态接口可返回的字典。"""

        return {
            "document_count": self.document_count,
            "term_count": self.term_count,
            "posting_count": self.posting_count,
            "last_rebuilt_at": self.last_rebuilt_at,
            "backend": self.backend,
        }


@dataclass(slots=True)
class CrawlError:
    """爬虫在抓取过程中记录的一条失败信息。

    使用场景：
        `/crawl` 需要把抓取失败、robots 拒绝、解析失败等信息保存到 SQLite，方便以后做状态页。
    """

    url: str  # 出错的页面 URL。
    stage: str  # 出错阶段，例如 robots/fetch/parse/domain。
    message: str  # 人能看懂的失败原因。
    depth: int = 0  # 当前抓取深度。
    category: str = "anime"  # 文档分类。
    crawled_at: str = field(default_factory=utc_now_iso)  # 记录失败时间，便于回看。

    def as_dict(self) -> dict[str, Any]:
        """转成 JSON 友好的字典。"""

        return {
            "url": self.url,
            "stage": self.stage,
            "message": self.message,
            "depth": self.depth,
            "category": self.category,
            "crawled_at": self.crawled_at,
        }


@dataclass(slots=True)
class CrawlResult:
    """一次爬取运行的结果。"""

    documents: list[SearchDocument]  # 成功抓取并解析出的文档。
    errors: list[CrawlError]  # 抓取过程中的失败记录。

    def as_dict(self) -> dict[str, Any]:
        """转成 API 友好的字典。"""

        return {
            "documents": [document.as_dict() for document in self.documents],
            "errors": [error.as_dict() for error in self.errors],
        }
