from __future__ import annotations

import html
import re

from .indexer import InMemoryTfIdfIndex
from .models import SearchDocument, SearchResult
from .tokenizer import tokenize


class SearchService:
    def __init__(self, index: InMemoryTfIdfIndex) -> None:
        self.index = index

    def search(self, query: str, page: int = 1, per_page: int = 10, category: str | None = None) -> dict:
        page = max(page, 1)
        per_page = min(max(per_page, 1), 50)
        offset = (page - 1) * per_page
        ranked, total = self.index.search(query, category=category, limit=per_page, offset=offset)
        results = [
            SearchResult(document=document, score=score, snippet=self.snippet(document, query)).as_dict()
            for document, score in ranked
        ]
        return {
            "query": query,
            "page": page,
            "per_page": per_page,
            "total": total,
            "results": results,
        }

    def snippet(self, document: SearchDocument, query: str, length: int = 180) -> str:
        terms = tokenize(query)
        text = document.summary or document.content
        lower_text = text.lower()
        start = 0
        for term in terms:
            pos = lower_text.find(term.lower())
            if pos >= 0:
                start = max(pos - 40, 0)
                break
        raw = text[start : start + length]
        if start > 0:
            raw = "..." + raw
        if start + length < len(text):
            raw += "..."
        return self._highlight(raw, terms)

    def _highlight(self, text: str, terms: list[str]) -> str:
        escaped = html.escape(text)
        for term in sorted(set(terms), key=len, reverse=True):
            if not term:
                continue
            pattern = re.compile(re.escape(html.escape(term)), re.IGNORECASE)
            escaped = pattern.sub(lambda match: f"<mark>{match.group(0)}</mark>", escaped)
        return escaped
