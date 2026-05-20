from __future__ import annotations

import math
from collections import Counter, defaultdict

from .models import SearchDocument
from .tokenizer import tokenize


FIELD_WEIGHTS = {
    "title": 3.0,
    "tags": 2.5,
    "summary": 1.5,
    "content": 1.0,
}


class InMemoryTfIdfIndex:
    def __init__(self) -> None:
        self.documents: dict[int, SearchDocument] = {}
        self.document_terms: dict[int, dict[str, float]] = {}
        self.inverted: dict[str, dict[int, float]] = defaultdict(dict)
        self.doc_magnitudes: dict[int, float] = {}

    def clear(self) -> None:
        self.documents.clear()
        self.document_terms.clear()
        self.inverted.clear()
        self.doc_magnitudes.clear()

    def rebuild(self, documents: list[SearchDocument]) -> None:
        self.clear()
        for document in documents:
            self.add(document)

    def add(self, document: SearchDocument) -> None:
        if document.id is None:
            raise ValueError("Document must have an id before indexing")

        terms = self._weighted_terms(document)
        self.documents[document.id] = document
        self.document_terms[document.id] = terms
        for term, weight in terms.items():
            self.inverted[term][document.id] = weight
        self.doc_magnitudes[document.id] = math.sqrt(sum(value * value for value in terms.values()))

    def search(self, query: str, category: str | None = None, limit: int = 10, offset: int = 0) -> tuple[list[tuple[SearchDocument, float]], int]:
        query_terms = tokenize(query)
        if not query_terms:
            return [], 0

        query_counts = Counter(query_terms)
        scores: dict[int, float] = defaultdict(float)
        query_magnitude = 0.0
        total_docs = max(len(self.documents), 1)

        for term, count in query_counts.items():
            postings = self.inverted.get(term)
            if not postings:
                continue
            idf = math.log((total_docs + 1) / (len(postings) + 1)) + 1
            query_weight = count * idf
            query_magnitude += query_weight * query_weight
            for doc_id, doc_weight in postings.items():
                document = self.documents[doc_id]
                if category and document.category != category:
                    continue
                scores[doc_id] += query_weight * doc_weight * idf

        if not scores:
            return [], 0

        query_magnitude = math.sqrt(query_magnitude) or 1.0
        ranked = []
        for doc_id, score in scores.items():
            denominator = self.doc_magnitudes.get(doc_id, 1.0) * query_magnitude
            normalized = score / denominator if denominator else 0.0
            normalized += self._exact_match_boost(self.documents[doc_id], query)
            ranked.append((self.documents[doc_id], normalized))

        ranked.sort(key=lambda item: item[1], reverse=True)
        total = len(ranked)
        return ranked[offset : offset + limit], total

    def _weighted_terms(self, document: SearchDocument) -> dict[str, float]:
        weighted: dict[str, float] = defaultdict(float)
        fields = {
            "title": document.title,
            "tags": " ".join(document.tags),
            "summary": document.summary,
            "content": document.content,
        }
        for field, text in fields.items():
            counts = Counter(tokenize(text))
            total = sum(counts.values()) or 1
            for term, count in counts.items():
                weighted[term] += (count / total) * FIELD_WEIGHTS[field]
        return dict(weighted)

    def _exact_match_boost(self, document: SearchDocument, query: str) -> float:
        query = query.strip().lower()
        if not query:
            return 0.0
        boost = 0.0
        title = document.title.lower()
        if title.startswith(query):
            boost += 0.8
        if query in title:
            boost += 1.0
        if any(query == tag.lower() or query in tag.lower() for tag in document.tags):
            boost += 0.6
        if query in document.summary.lower():
            boost += 0.25
        return boost
