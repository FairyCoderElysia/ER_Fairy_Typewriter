"""公开站点文章流抓取适配器。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .models import CrawlError, CrawlResult, SearchDocument
from .parser import AnimePageParser, clean_text


@dataclass(slots=True)
class ArticleFeedProfile:
    """一个 HTML 文章列表源的解析配置。"""

    source_id: str
    list_url: str
    link_pattern: re.Pattern[str]
    tags: list[str] = field(default_factory=list)
    game_title: str = ""
    aliases: list[str] = field(default_factory=list)
    source: str = ""


ARTICLE_FEEDS = {
    "mal-news": ArticleFeedProfile(
        source_id="mal-news",
        list_url="https://myanimelist.net/news",
        link_pattern=re.compile(r"^https://myanimelist\.net/news/\d+"),
        tags=["MyAnimeList", "动漫新闻", "anime news"],
        source="myanimelist.net",
    ),
    "ann-home": ArticleFeedProfile(
        source_id="ann-home",
        list_url="https://www.animenewsnetwork.com/",
        link_pattern=re.compile(r"^https://www\.animenewsnetwork\.com/(news|interest|press-release)/.+/\.\d+"),
        tags=["Anime News Network", "动漫新闻", "anime news"],
        source="www.animenewsnetwork.com",
    ),
    "fgo-news": ArticleFeedProfile(
        source_id="fgo-news",
        list_url="https://webview.fate-go.us/iframe/index.html",
        link_pattern=re.compile(r"^https://webview\.fate-go\.us/iframe/\d{4}/[^/]+/$"),
        tags=["Fate/Grand Order", "FGO", "官方新闻", "游戏资讯"],
        game_title="Fate/Grand Order",
        aliases=["FGO", "Fate Grand Order"],
        source="fate-go.us",
    ),
}


class ArticleFeedCrawler:
    """从公开站点列表页抓取多篇文章。"""

    def __init__(self, parser: AnimePageParser | None = None) -> None:
        self.parser = parser or AnimePageParser()

    def crawl(self, source_id: str, max_pages: int, source_score: float) -> CrawlResult:
        profile = ARTICLE_FEEDS.get(source_id)
        if profile is None:
            return CrawlResult(
                documents=[],
                errors=[
                    CrawlError(
                        url="",
                        stage="config",
                        message=f"未找到文章流配置：{source_id}",
                        category="news",
                    )
                ],
            )

        errors: list[CrawlError] = []
        try:
            list_html = self._fetch(profile.list_url)
            article_urls = self._article_urls(profile, list_html, max_pages)
        except requests.RequestException as exc:
            return CrawlResult(
                documents=[],
                errors=[
                    CrawlError(
                        url=profile.list_url,
                        stage="fetch",
                        message=f"文章列表下载失败：{exc}",
                        category="news",
                    )
                ],
            )

        documents: list[SearchDocument] = []
        for url in article_urls:
            try:
                html = self._fetch(url)
                document, _links = self.parser.parse(html, url, category="news")
            except requests.RequestException as exc:
                errors.append(CrawlError(url=url, stage="fetch", message=f"文章下载失败：{exc}", category="news"))
                continue
            except Exception as exc:
                errors.append(CrawlError(url=url, stage="parse", message=str(exc), category="news"))
                continue

            self._apply_profile(document, profile, source_score)
            if document.content:
                documents.append(document)
            else:
                errors.append(CrawlError(url=url, stage="parse", message="文章没有可索引正文", category="news"))

        return CrawlResult(documents=documents, errors=errors)

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

    def _article_urls(self, profile: ArticleFeedProfile, html: str, limit: int) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        urls: list[str] = []
        for tag in soup.find_all("a", href=True):
            href = urljoin(profile.list_url, tag["href"]).split("#", 1)[0]
            href = self._normalize_url(href)
            if profile.link_pattern.match(href) and href not in urls:
                urls.append(href)
            if len(urls) >= max(1, limit):
                break
        return urls

    def _normalize_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.netloc == "fate-go.us" and parsed.path.startswith("/iframe/"):
            return f"https://webview.fate-go.us{parsed.path}"
        return url

    def _apply_profile(self, document: SearchDocument, profile: ArticleFeedProfile, source_score: float) -> None:
        document.category = "news"
        document.entity_type = document.entity_type or "news"
        document.source = profile.source or document.source
        document.source_score = document.source_score or source_score
        document.tags = self._merge_unique([*profile.tags, *document.tags])
        document.aliases = self._merge_unique([*document.aliases, *profile.aliases])
        if profile.game_title and not document.game_title:
            document.game_title = profile.game_title

    def _merge_unique(self, values: list[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = clean_text(value)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(normalized)
        return merged
