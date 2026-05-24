"""文本分词与词频计算模块。

项目简介：
    搜索引擎的第一步是把用户查询和文档正文都拆成“词项 token”，后续倒排索引和 TF-IDF 才能工作。

开发目的：
    同时支持中文、英文、数字、游戏名中的符号词，并用中文 n-gram 提高角色名/作品名召回率。

技术栈：
    Python re、collections.Counter、jieba 中文分词。

学习目标：
    1. 理解 token、停用词、词频 TF 的含义。
    2. 理解中文搜索为什么不能只按空格切词。
    3. 理解 n-gram 对召回率的帮助与代价。

知识点与免费文档：
    - re 正则表达式: https://docs.python.org/3/library/re.html
    - Counter 计数器: https://docs.python.org/3/library/collections.html#collections.Counter
    - jieba 中文分词: https://github.com/fxsjy/jieba
    - Stanford IR 词项与词频: https://nlp.stanford.edu/IR-book/html/htmledition/tokenization-1.html
"""

from __future__ import annotations  # 让 list[str] 等类型注解在旧一点的运行环境中更稳。

import re  # 正则表达式用于从文本中抽取中英文 token。
from collections import Counter  # Counter 用于统计每个词出现了几次。

try:  # 设计思路：jieba 是可选依赖；即使没安装，也能让模块被导入，便于提示/测试。
    import jieba  # 中文分词库，比按单字切分更符合自然语言。
except ImportError:  # pragma: no cover - 只有依赖未安装时才会走到这里，测试环境通常已安装。
    jieba = None  # 没有 jieba 时退化为正则切分，保证系统不直接崩溃。


TOKEN_RE = re.compile(r"[a-zA-Z0-9_+#.]+|[\u4e00-\u9fff]+")  # 抽取英文/数字符号词，或连续中文片段。

STOP_WORDS = {  # 停用词：高频但信息量低的词，去掉后能减少噪声。
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
    "一个",
    "一些",
    "以及",
    "他们",
    "但是",
    "你",
    "我们",
    "是",
    "的",
    "了",
    "和",
    "在",
    "与",
    "及",
    "等",
    "这",
    "那",
}


def normalize_token(token: str) -> str:
    """规范化单个 token。

    入参：
        token: 正则或 jieba 产出的原始词。

    出参：
        str，去掉首尾空白并转小写后的词。

    设计思路：
        英文统一小写后，Elysia 和 elysia 才会被当成同一个词。
    """

    return token.strip().lower()  # strip 去空白，lower 统一英文大小写。


def tokenize(text: str) -> list[str]:
    """把文本切成搜索引擎可用的 token 列表。

    入参：
        text: 用户查询或文档字段文本。

    出参：
        list[str]，清洗后的 token。

    使用场景：
        indexer.py 建索引、search.py 生成高亮、测试用例验证召回。

    设计思路：
        先用正则分出中文片段和英文片段，再对中文片段用 jieba，并额外生成 n-gram。
        n-gram 会增加索引体积，但对“雷电将军”“初音未来”这类名字更友好。
    """

    if not text:  # 空字符串没有可搜索内容，直接返回空列表。
        return []

    parts: list[str] = []  # 收集所有候选 token，后面再统一过滤停用词。
    for raw in TOKEN_RE.findall(text):  # 正则先找到候选词片段，跳过标点和无意义符号。
        raw = normalize_token(raw)  # 每个候选词先规范化。
        if not raw:  # 防御性判断：空 token 不进入后续流程。
            continue
        if jieba and re.search(r"[\u4e00-\u9fff]", raw):  # 中文片段走中文分词逻辑。
            parts.extend(normalize_token(item) for item in jieba.cut(raw))  # jieba 给出更自然的中文词。
            parts.extend(_chinese_ngrams(raw))  # n-gram 给角色名/作品名提供兜底召回。
        else:  # 英文、数字、带 #/+/. 的技术词或作品词直接保留。
            parts.append(raw)

    return [  # 最终过滤停用词、空词和太短的噪声词。
        token  # 返回清洗后的 token。
        for token in parts  # 遍历候选 token。
        if token and token not in STOP_WORDS and (len(token) > 1 or token.isalnum())  # 保留有意义词。
    ]


def _chinese_ngrams(text: str, min_size: int = 2, max_size: int = 6) -> list[str]:
    """为中文片段生成短语 n-gram。

    入参：
        text: 连续中文文本。
        min_size: 最短短语长度，默认 2，避免单字噪声太大。
        max_size: 最长短语长度，默认 6，覆盖多数角色/作品短名。

    出参：
        list[str]，例如“雷电将军”会产生“雷电”“电将”“将军”“雷电将”等。

    设计思路：
        只对纯中文片段做 n-gram，避免英文词被切碎；这是召回率和索引大小之间的折中。
    """

    if not text or not re.fullmatch(r"[\u4e00-\u9fff]+", text):  # 只处理纯中文，混合文本交给主 tokenize 流程。
        return []
    tokens: list[str] = []  # 存放生成出的短语 token。
    max_size = min(max_size, len(text))  # 文本比 max_size 短时，最大长度不能超过文本本身。
    for size in range(min_size, max_size + 1):  # 从短到长生成 n-gram。
        for start in range(0, len(text) - size + 1):  # 滑动窗口起点。
            tokens.append(text[start : start + size])  # 截取 [start, start+size) 作为一个短语。
    return tokens  # 返回所有短语 token。


def term_frequency(text: str) -> dict[str, float]:
    """计算文本中每个 token 的词频 TF。

    入参：
        text: 文档字段或查询文本。

    出参：
        dict[str, float]，key 是 token，value 是 token 出现次数 / token 总数。

    使用场景：
        当前 indexer 使用自己的加权逻辑；这个函数保留给学习 TF-IDF 原理和未来扩展。
    """

    tokens = tokenize(text)  # 先分词，TF 必须基于 token 而不是原始字符串。
    if not tokens:  # 没有 token 时不能除以 0。
        return {}
    counts = Counter(tokens)  # 统计每个 token 出现次数。
    total = len(tokens)  # token 总数用于归一化。
    return {term: count / total for term, count in counts.items()}  # 词频 = 某词次数 / 全部词数。
