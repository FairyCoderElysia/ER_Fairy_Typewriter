"""搜索服务与结果摘要高亮模块。

项目简介：
    indexer.py 负责“算分”，本文件负责把算分结果包装成 Web/API 更好使用的格式。

开发目的：
    把分页、结果字典化、摘要截取、高亮这些展示层逻辑从索引算法中拆出来，降低模块耦合。

技术栈：
    html 转义、正则替换、分页参数保护、结果 DTO。

学习目标：
    1. 理解服务层为什么不直接写在路由函数里。
    2. 理解搜索结果高亮为什么要先 html.escape。
    3. 理解分页 offset 的计算方式。

知识点与免费文档：
    - html.escape: https://docs.python.org/3/library/html.html#html.escape
    - re 正则替换: https://docs.python.org/3/library/re.html
    - FastAPI 响应 JSON: https://fastapi.tiangolo.com/tutorial/response-model/
"""

from __future__ import annotations  # 支持较新的类型注解写法。

import html  # 用于 HTML 转义，防止摘要中的特殊字符破坏页面。
import re  # 用于把命中词替换成 <mark> 高亮。

from .indexer import SearchIndex  # 搜索索引接口，负责召回与排序。
from .models import SearchDocument, SearchResult  # 文档和结果数据结构。
from .tokenizer import tokenize  # 与索引保持一致的分词规则。


class SearchService:
    """面向 Web/API 的搜索服务。

    入参：
        index: 已经构建好的 SearchIndex。

    使用场景：
        web.py 的 /search 路由调用 SearchService，而不是直接操作 indexer。

    设计思路：
        服务层隔离“搜索业务逻辑”和“HTTP 路由逻辑”，后续换前端或换 API 时更容易。
    """

    def __init__(self, index: SearchIndex) -> None:
        self.index = index  # 保存索引实例，后续 search() 使用它查询。

    def search(self, query: str, page: int = 1, per_page: int = 10, category: str | None = None) -> dict:
        """执行一次搜索并返回 API 字典。

        入参：
            query: 用户查询词。
            page: 页码，从 1 开始。
            per_page: 每页数量。
            category: 分类过滤。

        出参：
            dict，包含 query/page/per_page/total/results。
        """

        page = max(page, 1)  # 防御：页码不能小于 1。
        per_page = min(max(per_page, 1), 50)  # 防御：每页 1~50，避免一次请求返回过多。
        offset = (page - 1) * per_page  # 分页公式：第 page 页从 offset 条开始。
        ranked, total = self.index.search(query, category=category, limit=per_page, offset=offset)  # 调用索引层。
        results = [  # 把索引层结果包装成前端/API 需要的 dict。
            SearchResult(document=document, score=score, snippet=self.snippet(document, query)).as_dict()  # 生成摘要并字典化。
            for document, score in ranked  # 遍历当前页排序结果。
        ]
        return {  # 返回稳定的 API 结构。
            "query": query,  # 原始查询词。
            "page": page,  # 当前页码。
            "per_page": per_page,  # 每页数量。
            "total": total,  # 总命中数。
            "results": results,  # 当前页结果。
        }

    def explain(self, query: str, category: str | None = None) -> dict:
        """返回一次搜索的调试解释。

        入参：
            query: 用户查询词。
            category: 分类过滤。

        出参：
            dict，包含分词、候选数、未命中 token 和每篇文档的得分拆解。

        使用场景：
            `/debug/search` 路由调用它，帮助学习者理解排序过程。
        """

        return self.index.explain(query, category=category).as_dict()  # 直接复用索引层解释结构，避免重复算分。

    def stats(self) -> dict:
        """返回索引状态摘要。"""

        return self.index.stats().as_dict()  # 后续索引状态页/API 可以直接复用。

    def snippet(self, document: SearchDocument, query: str, length: int = 180) -> str:
        """为搜索结果生成摘要片段。

        入参：
            document: 命中文档。
            query: 用户查询。
            length: 片段最大长度。

        出参：
            str，可能包含 <mark> 标签的 HTML 安全片段。

        设计思路：
            优先从 summary 截取，因为摘要更短更干净；没有摘要时再使用正文。
        """

        terms = tokenize(query)  # 查询分词，用于找命中位置和高亮。
        text = document.summary or document.content  # 摘要优先，没有摘要才用正文。
        lower_text = text.lower()  # 小写副本用于英文大小写无关查找。
        start = 0  # 默认从开头截取。
        for term in terms:  # 找第一个能在文本中出现的查询词。
            pos = lower_text.find(term.lower())  # 查找命中位置。
            if pos >= 0:  # 找到了命中词。
                start = max(pos - 40, 0)  # 命中词前保留一点上下文。
                break  # 找到第一个即可，避免片段位置跳来跳去。
        raw = text[start : start + length]  # 截取片段。
        if start > 0:  # 如果不是从开头截取，加省略号提示前面还有内容。
            raw = "..." + raw
        if start + length < len(text):  # 如果后面还有内容，也加省略号。
            raw += "..."
        return self._highlight(raw, terms)  # 对片段做 HTML 转义和高亮。

    def _highlight(self, text: str, terms: list[str]) -> str:
        """把片段中的命中词包上 <mark> 标签。

        入参：
            text: 原始片段。
            terms: 查询 token。

        出参：
            str，已转义且带高亮标签。

        安全设计：
            先 html.escape 再插入 <mark>，避免文档内容中的 HTML/脚本被浏览器执行。
        """

        escaped = html.escape(text)  # 先把用户/网页内容转义成安全文本。
        for term in sorted(set(terms), key=len, reverse=True):  # 长词优先，避免短词先替换破坏长词。
            if not term:  # 空词跳过。
                continue
            pattern = re.compile(re.escape(html.escape(term)), re.IGNORECASE)  # 构造大小写无关的安全匹配模式。
            escaped = pattern.sub(lambda match: f"<mark>{match.group(0)}</mark>", escaped)  # 用 mark 包裹命中词。
        return escaped  # 返回可直接放入模板的高亮片段。
