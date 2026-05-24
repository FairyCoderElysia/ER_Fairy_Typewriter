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
    """搜索引擎内部统一使用的“文档”结构。

    入参/字段：
        url: 文档唯一来源地址，本项目用它做去重依据。
        title: 搜索结果标题，通常权重最高。
        content: 正文内容，是召回更多结果的主要来源。
        summary: 摘要，负责结果页展示和片段生成。
        tags: 标签/别名/类别词，用来提升二次元角色、作品名的召回。
        category: 分类，首版默认为 anime，后续可扩展 game/coser/news。
        source: 来源站点或 sample，方便用户判断出处。
        published_at: 原网页发布时间，首版不参与主排序。
        crawled_at: 抓取入库时间。
        image_url: 结果卡片预留图片字段。
        id: SQLite 入库后生成的主键；入库前可以是 None。

    出参：
        dataclass 实例，可通过 as_dict() 转成 API/模板需要的 dict。

    使用场景：
        parser 产出 SearchDocument，store 保存它，indexer 读取它，search 返回它。
    """

    url: str  # 文档地址；设计上要求唯一，避免同一页面被重复索引。
    title: str  # 标题字段；搜索排序中会获得更高权重。
    content: str  # 正文字段；用于构建倒排索引的主体文本。
    summary: str = ""  # 摘要字段；没有摘要时 search.py 会退回使用 content。
    tags: list[str] = field(default_factory=list)  # 用 default_factory 避免多个文档共享同一个 list。
    category: str = "anime"  # 默认分类；比写死在搜索函数里更利于后续扩展。
    source: str = ""  # 来源展示字段；真实爬虫会写入域名。
    published_at: str = ""  # 发布时间先保留为字符串，避免不同站点时间格式过早复杂化。
    crawled_at: str = field(default_factory=utc_now_iso)  # 每次创建文档时动态生成当前时间。
    image_url: str = ""  # 图片地址预留字段；首版页面暂未重点使用。
    id: int | None = None  # SQLite 主键；未保存前为空，保存后由 store.py 回填。

    def as_dict(self) -> dict[str, Any]:
        """把文档对象转成普通字典。

        入参：
            self: 当前 SearchDocument。

        出参：
            dict，可被 FastAPI 自动序列化成 JSON，也可传给 Jinja2 模板。

        设计思路：
            不直接暴露 __dict__，是为了明确 API 返回哪些字段，避免未来对象内部字段意外泄露。
        """

        return {  # 逐项列出字段，保持 API 输出稳定。
            "id": self.id,  # 文档主键。
            "url": self.url,  # 来源 URL。
            "title": self.title,  # 标题。
            "content": self.content,  # 正文；真实产品里可考虑不向前端全量返回。
            "summary": self.summary,  # 摘要。
            "tags": self.tags,  # 标签列表。
            "category": self.category,  # 分类。
            "source": self.source,  # 来源。
            "published_at": self.published_at,  # 发布时间。
            "crawled_at": self.crawled_at,  # 抓取时间。
            "image_url": self.image_url,  # 图片地址。
        }


@dataclass(slots=True)  # 搜索结果对象同样用 dataclass，代码短且字段清楚。
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

    def as_dict(self) -> dict[str, Any]:
        """转成状态接口可返回的字典。"""

        return {
            "document_count": self.document_count,
            "term_count": self.term_count,
            "posting_count": self.posting_count,
            "last_rebuilt_at": self.last_rebuilt_at,
        }
