"""Generic RSS, sitemap, and HTML list feed crawlers."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .models import CrawlError, CrawlResult, SearchDocument
from .parser import AnimePageParser
from .sources import SourceConfig


class GenericFeedCrawler:
    """Fetch article URLs from common feed/list formats, then parse detail pages."""

    def __init__(self, parser: AnimePageParser | None = None) -> None:
        self.parser = parser or AnimePageParser()

    def crawl(self, source: SourceConfig) -> CrawlResult:
        try:
            html_or_xml = self._fetch(source.entry_url)
            urls = self.article_urls(source, html_or_xml, source.max_pages)
        except requests.RequestException as exc:
            return CrawlResult(
                documents=[],
                errors=[CrawlError(url=source.entry_url, stage="fetch", message=str(exc), category=source.category)],
            )
        except Exception as exc:
            return CrawlResult(
                documents=[],
                errors=[CrawlError(url=source.entry_url, stage="parse", message=str(exc), category=source.category)],
            )

        documents: list[SearchDocument] = []
        errors: list[CrawlError] = []
        for url in urls:
            try:
                detail_html = self._fetch(url)
                document, _links = self.parser.parse(detail_html, url, category=source.category)
                document.source_score = document.source_score or source.source_score
                if document.content:
                    documents.append(document)
                else:
                    errors.append(CrawlError(url=url, stage="parse", message="页面没有可索引正文", category=source.category))
            except requests.RequestException as exc:
                errors.append(CrawlError(url=url, stage="fetch", message=str(exc), category=source.category))
            except Exception as exc:
                errors.append(CrawlError(url=url, stage="parse", message=str(exc), category=source.category))
        return CrawlResult(documents=documents, errors=errors)

    def article_urls(self, source: SourceConfig, text: str, limit: int) -> list[str]:
        if source.parse_strategy == "rss-feed":
            return self._rss_urls(text, limit)
        if source.parse_strategy == "sitemap-feed":
            return self._sitemap_urls(text, limit)
        if source.parse_strategy == "html-list-feed":
            return self._html_list_urls(source.entry_url, text, limit)
        raise ValueError(f"Unsupported generic feed strategy: {source.parse_strategy}")

    def _fetch(self, url: str) -> str:
        response = requests.get(
            url,
            headers={"User-Agent": "ERFairyTypewriterBot/0.1 (+local learning project)"},
            timeout=15,
        )
        response.raise_for_status()
        if "charset" not in response.headers.get("content-type", "").lower():
            response.encoding = response.apparent_encoding or "utf-8"
        return response.text

    def _rss_urls(self, text: str, limit: int) -> list[str]:
        root = ET.fromstring(text)
        urls: list[str] = []
        for item in root.findall(".//item"):
            link = (item.findtext("link") or "").strip()
            if link and link not in urls:
                urls.append(link)
            if len(urls) >= max(1, limit):
                return urls
        for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
            link = ""
            for tag in entry.findall("{http://www.w3.org/2005/Atom}link"):
                link = tag.attrib.get("href", "")
                if link:
                    break
            if link and link not in urls:
                urls.append(link)
            if len(urls) >= max(1, limit):
                return urls
        return urls

    def _sitemap_urls(self, text: str, limit: int) -> list[str]:
        root = ET.fromstring(text)
        urls: list[str] = []
        for loc in root.findall(".//{*}url/{*}loc"):
            url = (loc.text or "").strip()
            if url and url not in urls:
                urls.append(url)
            if len(urls) >= max(1, limit):
                break
        return urls

    def _html_list_urls(self, base_url: str, html: str, limit: int) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        scored: list[tuple[int, str]] = []
        seen: set[str] = set()
        for tag in soup.find_all("a", href=True):
            href = urljoin(base_url, tag["href"]).split("#", 1)[0]
            parsed = urlparse(href)
            if parsed.scheme not in {"http", "https"} or href in seen:
                continue
            seen.add(href)
            score = self._link_score(href, tag.get_text(" "))
            if score > 0:
                scored.append((score, href))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [url for _score, url in scored[: max(1, limit)]]

    def _link_score(self, url: str, text: str) -> int:
        haystack = f"{url} {text}".lower()
        score = 0
        for marker in (
            "/news/",
            "/article/",
            "/posts/",
            "/post/",
            "/blog/",
            "/notice/",
            "/event/",
            "/topic/",
            "/app/",
            "/wiki/",
            "/攻略",
        ):
            if marker in haystack:
                score += 3
        if any(char.isdigit() for char in url):
            score += 1
        if len(text.strip()) >= 8:
            score += 1
        if any(skip in haystack for skip in ("login", "signup", "privacy", "terms", "tag/", "category/")):
            score -= 3
        return score
