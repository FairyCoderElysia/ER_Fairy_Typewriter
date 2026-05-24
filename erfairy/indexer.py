"""倒排索引、TF-IDF 与向量空间排序模块。

项目简介：
    本文件是 ER Fairy Typewriter 的搜索核心：把文档变成索引，并把用户查询变成排序结果。

开发目的：
    用纯 Python 实现一个教学友好的搜索索引，让你能看清搜索引擎如何“召回候选文档 + 计算相关性”。

技术栈：
    dict/defaultdict、Counter、math、TF-IDF、余弦相似度、字段权重。

学习目标：
    1. 理解倒排索引：term -> doc_id -> weight。
    2. 理解 TF-IDF：常见词权重低，稀有词权重高。
    3. 理解余弦相似度：把查询和文档看成向量后比较方向接近程度。
    4. 理解字段权重：标题命中通常比正文命中更重要。

知识点与免费文档：
    - defaultdict/Counter: https://docs.python.org/3/library/collections.html
    - math: https://docs.python.org/3/library/math.html
    - Stanford IR TF-IDF: https://nlp.stanford.edu/IR-book/html/htmledition/tf-idf-weighting-1.html
    - Stanford IR 向量空间模型: https://nlp.stanford.edu/IR-book/html/htmledition/vector-space-classification-1.html
"""

from __future__ import annotations  # 推迟类型注解解析，方便在类里写现代类型语法。

import math  # 提供 log、sqrt，用于 IDF 和向量模长计算。
from collections import Counter, defaultdict  # Counter 统计词频；defaultdict 简化嵌套字典初始化。

from .models import DocumentScoreExplanation, FieldMatch, IndexStats, SearchDocument, SearchExplanation  # 搜索相关数据模型。
from .models import utc_now_iso  # 记录索引最近一次重建时间。
from .tokenizer import tokenize  # 统一分词函数，保证建索引和查询使用同一套规则。


FIELD_WEIGHTS = {  # 字段权重表：体现“不同字段的命中价值不同”。
    "title": 3.0,  # 标题通常最能代表页面主题，所以权重最高。
    "tags": 2.5,  # 标签往往是人工提炼的关键词，权重也很高。
    "summary": 1.5,  # 摘要比全文更浓缩，但没有标题精确。
    "content": 1.0,  # 正文最长、噪声最多，因此作为基准权重。
}


class InMemoryTfIdfIndex:
    """内存版 TF-IDF 搜索索引。

    入参：
        无；创建空索引后通过 rebuild/add 写入文档。

    出参：
        search() 返回 (结果列表, 总数)。

    使用场景：
        适合 MVP、教学、几十到几千条文档的本地搜索。后续规模变大时可替换成 Redis/Meilisearch/Elasticsearch。

    设计思路：
        内存索引比 Redis 更容易调试和学习；缺点是进程重启后必须从 SQLite 重建索引。
    """

    def __init__(self) -> None:
        """初始化四个核心索引结构。"""

        self.documents: dict[int, SearchDocument] = {}  # doc_id -> 文档对象，排序后用 id 找回完整文档。
        self.document_terms: dict[int, dict[str, float]] = {}  # doc_id -> term 权重，便于调试单篇文档向量。
        self.document_field_terms: dict[int, dict[str, dict[str, float]]] = {}  # doc_id -> field -> term 权重，解释排序时使用。
        self.inverted: dict[str, dict[int, float]] = defaultdict(dict)  # term -> {doc_id: weight}，这就是倒排索引。
        self.doc_magnitudes: dict[int, float] = {}  # doc_id -> 文档向量模长，用于余弦相似度归一化。
        self.last_rebuilt_at = ""  # 最近一次重建索引时间，后续索引状态页会用到。

    def clear(self) -> None:
        """清空索引。

        使用场景：
            重建索引前先清空旧数据，避免旧文档残留。
        """

        self.documents.clear()  # 清空文档表。
        self.document_terms.clear()  # 清空文档向量。
        self.document_field_terms.clear()  # 清空字段级向量。
        self.inverted.clear()  # 清空倒排索引。
        self.doc_magnitudes.clear()  # 清空模长缓存。

    def rebuild(self, documents: list[SearchDocument]) -> None:
        """从一批文档完整重建索引。

        入参：
            documents: 已经有 id 的文档列表，通常来自 SQLiteDocumentStore.all()。

        设计思路：
            MVP 使用全量重建最简单可靠；未来数据大了再做增量更新。
        """

        self.clear()  # 先清空，保证重建结果只包含当前文档集合。
        for document in documents:  # 逐篇文档加入索引。
            self.add(document)  # add 负责构建单篇文档向量和倒排项。
        self.last_rebuilt_at = utc_now_iso()  # 记录重建完成时间。

    def add(self, document: SearchDocument) -> None:
        """把一篇文档加入索引。

        入参：
            document: 必须已经写入 SQLite 并拥有 id。

        异常：
            document.id 为 None 时抛 ValueError，因为倒排索引必须用稳定 id 做键。
        """

        if document.id is None:  # 没有 id 无法建立 term -> doc_id 的倒排关系。
            raise ValueError("Document must have an id before indexing")

        field_terms = self._weighted_field_terms(document)  # 计算字段级词向量，供 debug 解释使用。
        terms = self._merge_field_terms(field_terms)  # 合并成普通文档向量，供倒排索引使用。
        self.documents[document.id] = document  # 缓存完整文档。
        self.document_terms[document.id] = terms  # 缓存向量，方便调试/未来解释排序。
        self.document_field_terms[document.id] = field_terms  # 缓存字段级向量。
        for term, weight in terms.items():  # 遍历该文档中的每个词。
            self.inverted[term][document.id] = weight  # 写入倒排索引：词 -> 文档 -> 权重。
        self.doc_magnitudes[document.id] = math.sqrt(sum(value * value for value in terms.values()))  # 预计算文档向量模长。

    def search(
        self,
        query: str,
        category: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[tuple[SearchDocument, float]], int]:
        """搜索并按相关性排序。

        入参：
            query: 用户输入关键词。
            category: 分类过滤，None 表示不过滤。
            limit: 返回条数。
            offset: 分页起点。

        出参：
            ([(SearchDocument, score), ...], total)，total 是过滤后的命中总数。

        算法流程：
            查询分词 -> 倒排索引召回候选文档 -> TF-IDF 点积累加 -> 余弦归一化 -> 精确命中加分 -> 排序分页。
        """

        explanation = self.explain(query, category=category)  # 复用解释路径，避免普通搜索和 debug 搜索算分不一致。
        ranked = [(item.document, item.final_score) for item in explanation.results]  # 转回旧搜索接口需要的结构。
        total = len(ranked)  # 总命中数用于分页。
        return ranked[offset : offset + limit], total  # 返回当前页结果和总命中数。

    def explain(self, query: str, category: str | None = None) -> SearchExplanation:
        """返回一次搜索的完整排序解释。

        设计思路：
            普通搜索和 `/debug/search` 都调用这里，让“搜索结果”和“解释结果”永远来自同一套算法。
        """

        query_terms = tokenize(query)  # 查询也必须用同一套分词规则，否则建索引和搜索会对不上。
        if not query_terms:  # 空查询没有召回意义。
            return SearchExplanation(query=query, tokens=[], candidate_count=0, missing_terms=[], results=[])

        query_counts = Counter(query_terms)  # 查询词频；重复输入的词会有更高查询权重。
        scores: dict[int, float] = defaultdict(float)  # doc_id -> TF-IDF 原始点积分数。
        field_matches: dict[int, list[FieldMatch]] = defaultdict(list)  # doc_id -> 字段命中明细。
        query_magnitude = 0.0  # 查询向量模长的平方和，最后开根号。
        total_docs = max(len(self.documents), 1)  # 文档总数，至少为 1，避免 IDF 除零。
        missing_terms: list[str] = []  # 保存没有命中倒排表的 token。

        for term, count in query_counts.items():  # 遍历查询中的每个词。
            postings = self.inverted.get(term)  # 从倒排索引取出包含该词的文档列表。
            if not postings:  # 该词没有任何文档包含。
                missing_terms.append(term)  # 记录下来，debug 时告诉学习者为什么无召回。
                continue
            idf = math.log((total_docs + 1) / (len(postings) + 1)) + 1  # 平滑 IDF，避免除零并保持正数。
            query_weight = count * idf  # 查询向量中该词的权重。
            query_magnitude += query_weight * query_weight  # 累加查询向量模长平方。
            for doc_id, doc_weight in postings.items():  # 遍历包含该词的候选文档。
                document = self.documents[doc_id]  # 取出文档对象，用于分类过滤。
                if category and document.category != category:  # 分类不匹配则不计分。
                    continue
                scores[doc_id] += query_weight * doc_weight * idf  # 点积贡献：查询权重 * 文档权重 * 稀有度。
                field_matches[doc_id].extend(self._field_matches(doc_id, term, query_weight, idf))  # 保存字段级贡献。

        if not scores:  # 没有任何候选文档。
            return SearchExplanation(
                query=query,
                tokens=query_terms,
                candidate_count=0,
                missing_terms=missing_terms,
                results=[],
            )

        query_magnitude = math.sqrt(query_magnitude) or 1.0  # 查询向量模长，兜底 1.0 避免除零。
        results: list[DocumentScoreExplanation] = []  # 排序解释列表。
        for doc_id, score in scores.items():  # 遍历候选文档分数。
            denominator = self.doc_magnitudes.get(doc_id, 1.0) * query_magnitude  # 余弦相似度分母。
            tfidf_score = score / denominator if denominator else 0.0  # 余弦归一化，避免长文档天然占优。
            boost_score = self._exact_match_boost(self.documents[doc_id], query)  # 标题/标签精确命中额外加分。
            results.append(
                DocumentScoreExplanation(
                    document=self.documents[doc_id],
                    field_matches=field_matches[doc_id],
                    tfidf_score=tfidf_score,
                    boost_score=boost_score,
                    final_score=tfidf_score + boost_score,
                )
            )

        results.sort(key=lambda item: item.final_score, reverse=True)  # 按最终分数从高到低排序。
        return SearchExplanation(
            query=query,
            tokens=query_terms,
            candidate_count=len(results),
            missing_terms=missing_terms,
            results=results,
        )

    def stats(self) -> IndexStats:
        """返回当前索引的轻量统计信息。"""

        posting_count = sum(len(postings) for postings in self.inverted.values())  # 统计 term-doc 关系数量。
        return IndexStats(
            document_count=len(self.documents),
            term_count=len(self.inverted),
            posting_count=posting_count,
            last_rebuilt_at=self.last_rebuilt_at,
        )

    def _weighted_terms(self, document: SearchDocument) -> dict[str, float]:
        """把一篇文档转换成字段加权词向量。

        入参：
            document: 搜索文档。

        出参：
            dict[str, float]，term -> 字段加权 TF。

        设计思路：
            不同字段分别计算词频，再乘以字段权重；比把所有文本拼一起更符合搜索直觉。
        """

        return self._merge_field_terms(self._weighted_field_terms(document))  # 保留旧方法，方便测试或后续复用。

    def _weighted_field_terms(self, document: SearchDocument) -> dict[str, dict[str, float]]:
        """把一篇文档转换成字段级加权词向量。"""

        weighted: dict[str, dict[str, float]] = {}  # field -> term -> 字段内权重。
        fields = {  # 把文档对象映射成可遍历字段。
            "title": document.title,  # 标题。
            "tags": " ".join(document.tags),  # 标签列表先拼成字符串，复用 tokenize。
            "summary": document.summary,  # 摘要。
            "content": document.content,  # 正文。
        }
        for field, text in fields.items():  # 分字段处理。
            weighted[field] = {}  # 初始化当前字段的词向量。
            counts = Counter(tokenize(text))  # 统计该字段内每个词出现次数。
            total = sum(counts.values()) or 1  # 字段 token 总数；or 1 避免空字段除零。
            for term, count in counts.items():  # 遍历字段里的词。
                weighted[field][term] = (count / total) * FIELD_WEIGHTS[field]  # 字段 TF * 字段权重。
        return dict(weighted)  # 转回普通 dict，让外部看到更直观的数据结构。

    def _merge_field_terms(self, field_terms: dict[str, dict[str, float]]) -> dict[str, float]:
        """把字段级词向量合并成文档级词向量。"""

        merged: dict[str, float] = defaultdict(float)  # term -> 所有字段累积权重。
        for terms in field_terms.values():  # 遍历每个字段的词向量。
            for term, weight in terms.items():  # 遍历字段内 token。
                merged[term] += weight  # 同一个 token 在多个字段出现时累加。
        return dict(merged)  # 返回普通 dict。

    def _field_matches(self, doc_id: int, term: str, query_weight: float, idf: float) -> list[FieldMatch]:
        """生成某个 doc_id 对某个查询词的字段级贡献。"""

        matches: list[FieldMatch] = []  # 保存命中的字段。
        for field, terms in self.document_field_terms.get(doc_id, {}).items():  # 遍历字段级词向量。
            tf = terms.get(term, 0.0)  # 获取该字段中 term 的加权 TF。
            if tf <= 0:  # 没命中则跳过。
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

    def _exact_match_boost(self, document: SearchDocument, query: str) -> float:
        """给标题/标签中的完整命中额外加分。

        入参：
            document: 候选文档。
            query: 原始查询字符串。

        出参：
            float，额外加分。

        设计思路：
            TF-IDF 擅长统计相关性，但用户搜“原神”时通常希望“原神 总览”排在“纳西妲 原神角色”前面。
            所以这里增加简单、可解释的业务规则。
        """

        query = query.strip().lower()  # 清理查询，统一大小写。
        if not query:  # 空查询不加分。
            return 0.0
        boost = 0.0  # 加分累加器。
        title = document.title.lower()  # 标题统一小写，方便英文大小写无关匹配。
        if title.startswith(query):  # 标题以查询词开头，通常是总览页或最精确页面。
            boost += 0.8
        if query in title:  # 标题包含完整查询词。
            boost += 1.0
        if any(query == tag.lower() or query in tag.lower() for tag in document.tags):  # 标签完整或部分命中。
            boost += 0.6
        if query in document.summary.lower():  # 摘要包含完整查询词。
            boost += 0.25
        return boost  # 返回总加分。
