"""Site-specific crawlers for Chinese ACG/game community sources."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .models import CrawlError, CrawlResult, SearchDocument, utc_now_iso
from .parser import clean_text
from .sources import SourceConfig


class GameKeeFeedCrawler:
    """Fetch GameKee wiki updates through its public web API."""

    API_BASE = "https://www.gamekee.com"
    CDN_HOST = "https://cdnimg-test.gamekee.com"

    def crawl(self, source: SourceConfig) -> CrawlResult:
        alias = self._alias_from_source(source)
        if not alias:
            return CrawlResult(
                documents=[],
                errors=[CrawlError(url=source.entry_url, stage="config", message="GameKee source needs a wiki alias")],
            )
        try:
            items = self._fetch_items(alias, source.max_pages)
        except requests.RequestException as exc:
            return CrawlResult(
                documents=[],
                errors=[CrawlError(url=source.entry_url, stage="fetch", message=str(exc), category=source.category)],
            )
        documents = [self._document_from_item(alias, item, source) for item in items]
        return CrawlResult(documents=[document for document in documents if document.title], errors=[])

    def _alias_from_source(self, source: SourceConfig) -> str:
        parsed = urlparse(source.entry_url)
        return parsed.path.strip("/").split("/", 1)[0]

    def _fetch_items(self, alias: str, limit: int) -> list[dict]:
        payload = self._get_json(
            "/v1/wiki/entry/updateList",
            alias,
            params={"limit": max(1, min(limit, 50))},
        )
        data = payload.get("data") or []
        if not data:
            payload = self._get_json(
                "/v1/content/pageList",
                alias,
                params={"page_no": 1, "limit": max(1, min(limit, 50))},
            )
            data = payload.get("data") or []
        return data[: max(1, limit)]

    def _document_from_item(self, alias: str, item: dict, source: SourceConfig) -> SearchDocument:
        title = clean_text(str(item.get("title") or ""))
        summary = clean_text(str(item.get("summary") or ""))
        content = clean_text(f"{title} {summary} {self._content_from_item(alias, item)}")
        content_id = str(item.get("id") or "")
        url = f"https://www.gamekee.com/{alias}/{content_id}.html" if content_id else source.entry_url
        image_url = self._absolute_url(str(item.get("thumb") or ""))
        published_at = self._timestamp_to_iso(item.get("created_at"))
        tags = ["GameKee", "游戏攻略", "Wiki", alias]
        content_hash = hashlib.sha256(content.lower().encode("utf-8")).hexdigest()
        return SearchDocument(
            url=url,
            title=title,
            content=content or title,
            summary=(summary or content)[:220],
            tags=tags,
            entity_type="wiki",
            source_score=source.source_score,
            content_hash=content_hash,
            category=source.category,
            source="www.gamekee.com",
            published_at=published_at,
            crawled_at=utc_now_iso(),
            image_url=image_url,
        )

    def _content_from_item(self, alias: str, item: dict) -> str:
        content_cdn = str(item.get("content_cdn") or "")
        if not content_cdn and item.get("id"):
            try:
                detail = self._get_json(f"/v1/content/detail/{item['id']}", alias).get("data") or {}
                content_cdn = str(detail.get("content_cdn") or "")
                inline = clean_text(str(detail.get("content") or detail.get("content_json") or ""))
                if inline:
                    return inline
            except requests.RequestException:
                return ""
        if not content_cdn:
            return ""
        try:
            payload = self._get_json_from_cdn(content_cdn)
        except requests.RequestException:
            return ""
        blocks = payload.get("content") or payload.get("content1") or ""
        return self._text_from_rich_content(blocks)

    def _text_from_rich_content(self, value: object) -> str:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return clean_text(value)
        fragments: list[str] = []

        def walk(node: object) -> None:
            if isinstance(node, dict):
                text = node.get("text")
                if text:
                    fragments.append(str(text))
                for child in node.get("children") or []:
                    walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)

        walk(value)
        return clean_text(" ".join(fragments))

    def _get_json(self, path: str, alias: str, params: dict | None = None) -> dict:
        response = requests.get(
            f"{self.API_BASE}{path}",
            params=params,
            headers={
                "User-Agent": "ERFairyTypewriterBot/0.1 (+local learning project)",
                "X-Requested-With": "XMLHttpRequest",
                "game-alias": alias,
                "Lang": "zh-cn",
            },
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    def _get_json_from_cdn(self, url: str) -> dict:
        if url.startswith("//"):
            url = "https:" + url
        url = url.replace("https://api-cdn.gamekee.com", self.CDN_HOST)
        response = requests.get(url, headers={"User-Agent": "ERFairyTypewriterBot/0.1"}, timeout=15)
        response.raise_for_status()
        return response.json()

    def _absolute_url(self, url: str) -> str:
        if url.startswith("//"):
            return "https:" + url
        return url

    def _timestamp_to_iso(self, value: object) -> str:
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            return ""
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")


class TapTapFeedCrawler:
    """Fetch TapTap app pages and selected app subpages from SSR HTML."""

    def crawl(self, source: SourceConfig) -> CrawlResult:
        app_id = self._app_id_from_url(source.entry_url)
        if not app_id:
            return CrawlResult(
                documents=[],
                errors=[
                    CrawlError(
                        url=source.entry_url,
                        stage="config",
                        message="TapTap source needs a concrete /app/{id} URL",
                        category=source.category,
                    )
                ],
            )
        urls = self._candidate_urls(source.entry_url, app_id, source.max_pages)
        documents: list[SearchDocument] = []
        errors: list[CrawlError] = []
        for url in urls:
            try:
                html = self._fetch(url)
                document = self._document_from_html(url, html, source)
                if document.title:
                    documents.append(document)
            except requests.RequestException as exc:
                errors.append(CrawlError(url=url, stage="fetch", message=str(exc), category=source.category))
        return CrawlResult(documents=documents, errors=errors)

    def _candidate_urls(self, entry_url: str, app_id: str, limit: int) -> list[str]:
        base = f"https://www.taptap.cn/app/{app_id}"
        urls = [base, f"{base}/all-info", f"{base}/strategy", f"{base}/topic", f"{base}/game-event"]
        return urls[: max(1, limit)]

    def _document_from_html(self, url: str, html: str, source: SourceConfig) -> SearchDocument:
        soup = BeautifulSoup(html, "html.parser")
        title = self._meta(soup, "og:title") or (soup.title.string if soup.title and soup.title.string else "")
        title = clean_text(title.replace("丨TapTap", "").replace("| TapTap", ""))
        description = self._meta(soup, "description") or self._meta(soup, "og:description")
        text = clean_text(soup.get_text(" "))
        content = clean_text(f"{title} {description} {text[:2000]}")
        image_url = self._meta(soup, "og:image")
        content_hash = hashlib.sha256(content.lower().encode("utf-8")).hexdigest()
        return SearchDocument(
            url=url,
            title=title or url,
            content=content or title or url,
            summary=clean_text(description or text)[:220],
            tags=["TapTap", "游戏社区", "游戏资讯"],
            entity_type="news",
            source_score=source.source_score,
            content_hash=content_hash,
            category=source.category,
            source="www.taptap.cn",
            crawled_at=utc_now_iso(),
            image_url=image_url,
        )

    def _fetch(self, url: str) -> str:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 ERFairyTypewriterBot/0.1"},
            timeout=15,
        )
        response.raise_for_status()
        if "charset" not in response.headers.get("content-type", "").lower():
            response.encoding = response.apparent_encoding or "utf-8"
        return response.text

    def _meta(self, soup: BeautifulSoup, name: str) -> str:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        return clean_text(str(tag.get("content", ""))) if tag else ""

    def _app_id_from_url(self, url: str) -> str:
        parts = urlparse(url).path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "app" and parts[1].isdigit():
            return parts[1]
        return ""
