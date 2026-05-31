"""Site-specific crawlers for Chinese ACG/game community sources."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .models import CrawlError, CrawlResult, SearchDocument, utc_now_iso
from .parser import clean_text
from .sources import SourceConfig
from .content_quality import score_community_content
from .wiki_profiles import wiki_game_profile_from_config


def _clean_unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = clean_text(str(value))
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


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
        game_profile = wiki_game_profile_from_config(
            alias,
            {"wiki_game_title": source.wiki_game_title, "wiki_game_aliases": source.wiki_game_aliases},
        )
        title = clean_text(str(item.get("title") or ""))
        summary = clean_text(str(item.get("summary") or ""))
        content = clean_text(f"{title} {summary} {self._content_from_item(alias, item)}")
        content_id = str(item.get("id") or "")
        url = f"https://www.gamekee.com/{alias}/{content_id}.html" if content_id else source.entry_url
        image_url = self._absolute_url(str(item.get("thumb") or ""))
        published_at = self._timestamp_to_iso(item.get("created_at"))
        tags = _clean_unique(["GameKee", "游戏攻略", "Wiki", *game_profile.tags])
        content_hash = hashlib.sha256(content.lower().encode("utf-8")).hexdigest()
        return SearchDocument(
            url=url,
            title=title,
            content=content or title,
            summary=(summary or content)[:220],
            tags=tags,
            aliases=game_profile.aliases,
            entity_type="wiki",
            game_title=game_profile.game_title,
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
        quality = score_community_content(
            title,
            content,
            topics=self._topics_for_url(url),
            source="www.taptap.cn",
            url=url,
            base_score=self._base_quality_for_url(url),
        )
        return SearchDocument(
            url=url,
            title=title or url,
            content=content or title or url,
            summary=clean_text(description or text)[:220],
            tags=["TapTap", "游戏社区", "游戏资讯"],
            entity_type="news",
            source_score=source.source_score,
            content_quality_score=quality.score,
            content_quality_labels=quality.labels,
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

    def _topics_for_url(self, url: str) -> list[str]:
        if url.endswith("/strategy"):
            return ["攻略"]
        if url.endswith("/game-event"):
            return ["活动", "公告"]
        if url.endswith("/topic"):
            return ["论坛", "社区"]
        if url.endswith("/all-info"):
            return ["游戏介绍"]
        return ["TapTap", "游戏"]

    def _base_quality_for_url(self, url: str) -> float:
        if url.endswith("/strategy") or url.endswith("/game-event"):
            return 0.68
        if url.endswith("/all-info"):
            return 0.6
        if url.endswith("/topic"):
            return 0.5
        return 0.55

    def _app_id_from_url(self, url: str) -> str:
        parts = urlparse(url).path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "app" and parts[1].isdigit():
            return parts[1]
        return ""


class BiligameWikiCrawler:
    """Fetch Biligame Wiki pages through the MediaWiki API."""

    RETRYABLE_EXCEPTIONS = (
        requests.ConnectionError,
        requests.Timeout,
        requests.exceptions.ProxyError,
    )

    def crawl(self, source: SourceConfig) -> CrawlResult:
        alias = self._alias_from_source(source)
        if not alias:
            return CrawlResult(
                documents=[],
                errors=[
                    CrawlError(
                        url=source.entry_url,
                        stage="config",
                        message="Biligame Wiki source needs a concrete wiki alias",
                        category=source.category,
                    )
                ],
            )
        api_url = f"https://wiki.biligame.com/{alias}/api.php"
        try:
            titles = self._fetch_titles(api_url, alias, source.max_pages)
        except requests.RequestException as exc:
            return CrawlResult(
                documents=[],
                errors=[CrawlError(url=api_url, stage="fetch", message=str(exc), category=source.category)],
            )
        except Exception as exc:
            return CrawlResult(
                documents=[],
                errors=[CrawlError(url=api_url, stage="parse", message=str(exc), category=source.category)],
            )

        documents: list[SearchDocument] = []
        errors: list[CrawlError] = []
        for title in titles[: max(1, source.max_pages)]:
            try:
                document = self._fetch_document(api_url, alias, title, source)
                if document.content:
                    documents.append(document)
            except requests.RequestException as exc:
                errors.append(CrawlError(url=api_url, stage="fetch", message=str(exc), category=source.category))
            except Exception as exc:
                errors.append(CrawlError(url=api_url, stage="parse", message=str(exc), category=source.category))
        return CrawlResult(documents=documents, errors=errors)

    def _fetch_titles(self, api_url: str, alias: str, limit: int) -> list[str]:
        payload = self._get_json(
            api_url,
            alias,
            {
                "action": "query",
                "list": "recentchanges",
                "rcnamespace": 0,
                "rcprop": "title|timestamp",
                "rctype": "edit|new",
                "rclimit": max(1, min(limit * 2, 50)),
                "format": "json",
                "formatversion": 2,
            },
        )
        titles = self._unique_titles(change.get("title", "") for change in payload.get("query", {}).get("recentchanges", []))
        if titles:
            return titles[: max(1, limit)]
        payload = self._get_json(
            api_url,
            alias,
            {
                "action": "query",
                "list": "allpages",
                "apnamespace": 0,
                "aplimit": max(1, min(limit, 50)),
                "format": "json",
                "formatversion": 2,
            },
        )
        return self._unique_titles(page.get("title", "") for page in payload.get("query", {}).get("allpages", []))

    def _fetch_document(self, api_url: str, alias: str, title: str, source: SourceConfig) -> SearchDocument:
        game_profile = wiki_game_profile_from_config(
            alias,
            {"wiki_game_title": source.wiki_game_title, "wiki_game_aliases": source.wiki_game_aliases},
        )
        payload = self._get_json(
            api_url,
            alias,
            {
                "action": "parse",
                "page": title,
                "prop": "text|displaytitle|categories",
                "format": "json",
                "formatversion": 2,
                "disableeditsection": 1,
            },
        )
        parsed = payload.get("parse", {})
        html = str(parsed.get("text") or "")
        display_title = clean_text(str(parsed.get("displaytitle") or title))
        text = clean_text(BeautifulSoup(html, "html.parser").get_text(" "))
        category_names = [
            clean_text(str(category.get("category") or ""))
            for category in parsed.get("categories", [])
            if category.get("category")
        ]
        content = clean_text(f"{display_title} {' '.join(category_names)} {text}")
        url = self._page_url(alias, title)
        content_hash = hashlib.sha256(content.lower().encode("utf-8")).hexdigest()
        return SearchDocument(
            url=url,
            title=display_title or title,
            content=content or display_title or title,
            summary=text[:220],
            tags=_clean_unique(["Biligame", "Wiki", *game_profile.tags, *category_names[:8]]),
            aliases=game_profile.aliases,
            entity_type="wiki",
            game_title=game_profile.game_title,
            source_score=source.source_score,
            content_hash=content_hash,
            category=source.category,
            source="wiki.biligame.com",
            crawled_at=utc_now_iso(),
        )

    def _get_json(self, api_url: str, alias: str, params: dict) -> dict:
        last_error: requests.RequestException | None = None
        for attempt in range(3):
            try:
                response = requests.get(
                    api_url,
                    params=params,
                    headers=self._headers(alias),
                    timeout=20,
                )
                response.raise_for_status()
                return response.json()
            except self.RETRYABLE_EXCEPTIONS as exc:
                last_error = exc
                if attempt == 2:
                    break
                time.sleep(0.5 * (attempt + 1))
        if last_error:
            raise last_error
        raise requests.RequestException(f"Failed to fetch {api_url}")

    def _headers(self, alias: str) -> dict:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": f"https://wiki.biligame.com/{alias}/%E9%A6%96%E9%A1%B5",
            "X-Requested-With": "XMLHttpRequest",
        }

    def _alias_from_source(self, source: SourceConfig) -> str:
        parsed = urlparse(source.entry_url)
        return parsed.path.strip("/").split("/", 1)[0]

    def _page_url(self, alias: str, title: str) -> str:
        normalized = quote(title.replace(" ", "_"), safe="")
        return f"https://wiki.biligame.com/{alias}/{normalized}"

    def _unique_titles(self, values) -> list[str]:
        titles: list[str] = []
        seen: set[str] = set()
        for value in values:
            title = clean_text(str(value or ""))
            if not title or title in seen or title.startswith(("特殊:", "Special:", "User:", "用户:")):
                continue
            seen.add(title)
            titles.append(title)
        return titles
