from __future__ import annotations

import re
from collections import Counter

try:
    import jieba
except ImportError:  # pragma: no cover - used only before dependencies are installed
    jieba = None


TOKEN_RE = re.compile(r"[a-zA-Z0-9_+#.]+|[\u4e00-\u9fff]+")

STOP_WORDS = {
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
    return token.strip().lower()


def tokenize(text: str) -> list[str]:
    if not text:
        return []

    parts: list[str] = []
    for raw in TOKEN_RE.findall(text):
        raw = normalize_token(raw)
        if not raw:
            continue
        if jieba and re.search(r"[\u4e00-\u9fff]", raw):
            parts.extend(normalize_token(item) for item in jieba.cut(raw))
            parts.extend(_chinese_ngrams(raw))
        else:
            parts.append(raw)

    return [
        token
        for token in parts
        if token and token not in STOP_WORDS and (len(token) > 1 or token.isalnum())
    ]


def _chinese_ngrams(text: str, min_size: int = 2, max_size: int = 6) -> list[str]:
    """Add short phrase tokens so names like 雷姆 or 初音未来 are easy to recall."""
    if not text or not re.fullmatch(r"[\u4e00-\u9fff]+", text):
        return []
    tokens: list[str] = []
    max_size = min(max_size, len(text))
    for size in range(min_size, max_size + 1):
        for start in range(0, len(text) - size + 1):
            tokens.append(text[start : start + size])
    return tokens


def term_frequency(text: str) -> dict[str, float]:
    tokens = tokenize(text)
    if not tokens:
        return {}
    counts = Counter(tokens)
    total = len(tokens)
    return {term: count / total for term, count in counts.items()}
