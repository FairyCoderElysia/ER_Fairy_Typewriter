"""API-backed crawlers for controlled ACG knowledge sources."""

from __future__ import annotations

import hashlib
from urllib.parse import quote

import requests

from .models import CrawlError, CrawlResult, SearchDocument, utc_now_iso
from .parser import clean_text
from .sources import SourceConfig


class ApiFeedCrawler:
    """Turn known public APIs into search documents."""

    MOEGIRL_QUERIES = ("原神", "崩坏3", "崩坏：星穹铁道", "明日方舟", "动画")

    def crawl(self, source: SourceConfig) -> CrawlResult:
        if source.parse_strategy == "bangumi-api":
            return self._crawl_bangumi_calendar(source)
        if source.parse_strategy == "moegirl-api":
            return self._crawl_moegirl_search(source)
        return CrawlResult(
            documents=[],
            errors=[
                CrawlError(
                    url=source.entry_url,
                    stage="config",
                    message=f"Unsupported API feed strategy: {source.parse_strategy}",
                    category=source.category,
                )
            ],
        )

    def _crawl_bangumi_calendar(self, source: SourceConfig) -> CrawlResult:
        try:
            payload = self._get_json(source.entry_url)
        except requests.RequestException as exc:
            return CrawlResult(
                documents=[],
                errors=[CrawlError(url=source.entry_url, stage="fetch", message=str(exc), category=source.category)],
            )

        documents: list[SearchDocument] = []
        for weekday in payload:
            for item in weekday.get("items", []):
                document = self._bangumi_document(item, source)
                if document and document.url not in {existing.url for existing in documents}:
                    documents.append(document)
                if len(documents) >= max(1, source.max_pages):
                    return CrawlResult(documents=documents, errors=[])
        return CrawlResult(documents=documents, errors=[])

    def _bangumi_document(self, item: dict, source: SourceConfig) -> SearchDocument | None:
        subject_id = item.get("id")
        title = clean_text(str(item.get("name_cn") or item.get("name") or ""))
        if not subject_id or not title:
            return None
        original_name = clean_text(str(item.get("name") or ""))
        summary = clean_text(str(item.get("summary") or ""))
        url = str(item.get("url") or f"https://bgm.tv/subject/{subject_id}")
        tags = ["Bangumi", "番组计划", "动画"]
        aliases = [original_name] if original_name and original_name != title else []
        score = item.get("rating", {}).get("score", "")
        content = clean_text(f"{title} {original_name} {summary} 评分 {score}")
        image_url = str((item.get("images") or {}).get("common") or "")
        content_hash = hashlib.sha256(content.lower().encode("utf-8")).hexdigest()
        return SearchDocument(
            url=url,
            title=title,
            content=content or title,
            summary=summary[:220],
            tags=tags,
            aliases=aliases,
            entity_type="work",
            source_score=source.source_score,
            content_hash=content_hash,
            category=source.category,
            source="bangumi.tv",
            published_at=str(item.get("air_date") or ""),
            crawled_at=utc_now_iso(),
            image_url=image_url,
        )

    def _crawl_moegirl_search(self, source: SourceConfig) -> CrawlResult:
        documents: list[SearchDocument] = []
        errors: list[CrawlError] = []
        seen_urls: set[str] = set()
        per_query = max(1, min(10, source.max_pages))
        for query in self.MOEGIRL_QUERIES:
            if len(documents) >= max(1, source.max_pages):
                break
            try:
                payload = self._get_json(
                    source.entry_url,
                    params={
                        "action": "query",
                        "format": "json",
                        "generator": "search",
                        "gsrsearch": query,
                        "gsrlimit": per_query,
                        "prop": "extracts|info",
                        "exintro": 1,
                        "explaintext": 1,
                        "inprop": "url",
                    },
                )
            except requests.RequestException as exc:
                errors.append(CrawlError(url=source.entry_url, stage="fetch", message=str(exc), category=source.category))
                continue
            for page in (payload.get("query", {}).get("pages", {}) or {}).values():
                document = self._moegirl_document(page, source)
                if document and document.url not in seen_urls:
                    seen_urls.add(document.url)
                    documents.append(document)
                if len(documents) >= max(1, source.max_pages):
                    break
        return CrawlResult(documents=documents, errors=errors)

    def _moegirl_document(self, page: dict, source: SourceConfig) -> SearchDocument | None:
        title = clean_text(str(page.get("title") or ""))
        if not title:
            return None
        extract = clean_text(str(page.get("extract") or ""))
        url = str(page.get("fullurl") or f"https://zh.moegirl.org.cn/{quote(title)}")
        content = clean_text(f"{title} {extract}")
        content_hash = hashlib.sha256(content.lower().encode("utf-8")).hexdigest()
        return SearchDocument(
            url=url,
            title=title,
            content=content or title,
            summary=extract[:220],
            tags=["萌娘百科", "ACGN", "百科"],
            aliases=[],
            entity_type="wiki",
            source_score=source.source_score,
            content_hash=content_hash,
            category=source.category,
            source="zh.moegirl.org.cn",
            crawled_at=utc_now_iso(),
        )

    def _get_json(self, url: str, params: dict | None = None) -> object:
        response = requests.get(
            url,
            params=params,
            headers={"User-Agent": "ERFairyTypewriterBot/0.1 (+local learning project)"},
            timeout=15,
        )
        response.raise_for_status()
        return response.json()
