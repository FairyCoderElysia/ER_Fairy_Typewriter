"""Discover controlled source candidates from a site URL."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .wiki_profiles import wiki_game_config


DISCOVERY_LABELS = {
    "known-profile": "内置推荐源",
    "index-page": "首页解析发现",
    "generic-feed": "通用 RSS/Sitemap 发现",
}


@dataclass(slots=True)
class SourceCandidate:
    url: str
    source_type: str
    title: str = ""
    reason: str = ""
    config: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "source_type": self.source_type,
            "title": self.title,
            "reason": self.reason,
            "config": self.config,
        }


class DiscoveryProfile:
    """A small pluggable source discovery strategy."""

    def discover(self, root_url: str) -> list[SourceCandidate]:
        raise NotImplementedError


def _with_discovery_metadata(config: dict, origin: str, site: str) -> dict:
    return {
        **config,
        "discovery_origin": origin,
        "discovery_label": DISCOVERY_LABELS.get(origin, "历史候选源"),
        "discovery_site": site,
    }


def _fetch_html(url: str, headers: dict | None = None) -> str:
    response = requests.get(
        url,
        headers=headers or {"User-Agent": "ERFairyTypewriterBot/0.1 (+local learning project)"},
        timeout=15,
    )
    response.raise_for_status()
    if "charset" not in response.headers.get("content-type", "").lower():
        response.encoding = response.apparent_encoding or "utf-8"
    return response.text


class MiyousheDiscoveryProfile(DiscoveryProfile):
    """Discover known Miyoushe communities that need the site-specific feed parser."""

    COMMUNITIES = {
        "ys": {"title": "原神米游社官方社区", "profile_id": "miyoushe-ys"},
        "bh3": {"title": "崩坏3米游社官方社区", "profile_id": "miyoushe-bh3"},
        "sr": {"title": "崩坏：星穹铁道米游社官方社区", "profile_id": "miyoushe-sr"},
    }

    def discover(self, root_url: str) -> list[SourceCandidate]:
        parsed = urlparse(root_url)
        if parsed.netloc.lower() != "www.miyoushe.com":
            return []
        path = parsed.path.strip("/").split("/", 1)[0]
        community = self.COMMUNITIES.get(path)
        if not community:
            return []
        canonical_url = f"https://www.miyoushe.com/{path}/"
        return [
            SourceCandidate(
                url=canonical_url,
                source_type="miyoushe-feed",
                title=community["title"],
                reason="内置推荐的站点 Profile",
                config=_with_discovery_metadata(
                    {
                        "category": "anime",
                        "max_pages": 20,
                        "max_depth": 0,
                        "delay_seconds": 1.0,
                        "source_score": 0.95,
                        "quality_profile": "miyoushe-community",
                        "quality_mode": "score",
                        "allowed_domains": ["www.miyoushe.com"],
                        "miyoushe_profile_id": community["profile_id"],
                        "scheduler_interval_minutes": 60,
                    },
                    "known-profile",
                    "miyoushe",
                ),
            )
        ]


class MoegirlDiscoveryProfile(DiscoveryProfile):
    """Discover Moegirl MediaWiki API as a controlled knowledge source."""

    DOMAINS = {"zh.moegirl.org.cn", "mzh.moegirl.org.cn"}

    def discover(self, root_url: str) -> list[SourceCandidate]:
        parsed = urlparse(root_url)
        if parsed.netloc.lower() not in self.DOMAINS:
            return []
        return [
            SourceCandidate(
                url="https://zh.moegirl.org.cn/api.php",
                source_type="moegirl-api",
                title="萌娘百科 MediaWiki API",
                reason="内置推荐的站点 Profile",
                config=_with_discovery_metadata(
                    {
                        "category": "anime",
                        "max_pages": 50,
                        "max_depth": 0,
                        "delay_seconds": 1.0,
                        "source_score": 0.9,
                        "allowed_domains": ["zh.moegirl.org.cn"],
                        "scheduler_interval_minutes": 60,
                    },
                    "known-profile",
                    "moegirl",
                ),
            )
        ]


class BangumiDiscoveryProfile(DiscoveryProfile):
    """Discover Bangumi public API as a controlled metadata source."""

    DOMAINS = {"bangumi.tv", "bgm.tv", "chii.in"}

    def discover(self, root_url: str) -> list[SourceCandidate]:
        parsed = urlparse(root_url)
        if parsed.netloc.lower() not in self.DOMAINS:
            return []
        return [
            SourceCandidate(
                url="https://api.bgm.tv/calendar",
                source_type="bangumi-api",
                title="Bangumi 番组计划 API",
                reason="内置推荐的站点 Profile",
                config=_with_discovery_metadata(
                    {
                        "category": "anime",
                        "max_pages": 50,
                        "max_depth": 0,
                        "delay_seconds": 1.0,
                        "source_score": 0.88,
                        "allowed_domains": ["api.bgm.tv", "bangumi.tv", "bgm.tv"],
                        "scheduler_interval_minutes": 60,
                    },
                    "known-profile",
                    "bangumi",
                ),
            )
        ]


class TapTapDiscoveryProfile(DiscoveryProfile):
    """Discover TapTap pages as game community list candidates."""

    DOMAINS = {"www.taptap.cn", "taptap.cn", "www.taptap.io", "taptap.io"}
    DEFAULT_APP_ID = "168332"

    def discover(self, root_url: str) -> list[SourceCandidate]:
        parsed = urlparse(root_url)
        if parsed.netloc.lower() not in self.DOMAINS:
            return []
        path_parts = parsed.path.strip("/").split("/")
        app_id = self.DEFAULT_APP_ID
        if len(path_parts) >= 2 and path_parts[0] == "app" and path_parts[1].isdigit():
            app_id = path_parts[1]
        return [
            SourceCandidate(
                url=f"https://www.taptap.cn/app/{app_id}",
                source_type="taptap-feed",
                title=f"TapTap 游戏页 {app_id}",
                reason="内置推荐的站点 Profile",
                config=_with_discovery_metadata(
                    {
                        "category": "game",
                        "max_pages": 50,
                        "max_depth": 0,
                        "delay_seconds": 1.0,
                        "source_score": 0.78,
                        "quality_profile": "taptap-community",
                        "quality_mode": "score",
                        "allowed_domains": ["www.taptap.cn"],
                        "taptap_app_id": app_id,
                        "scheduler_interval_minutes": 60,
                    },
                    "known-profile",
                    "taptap",
                ),
            )
        ]


class WikiIndexDiscoveryMixin:
    """Shared helpers for wiki-like sites that expose many game areas on an index page."""

    INDEX_SKIP_ALIASES = {
        "",
        "api.php",
        "index.php",
        "wiki",
        "w",
        "special",
        "user",
        "help",
        "category",
        "template",
        "file",
    }
    HOT_WIKI_LIMIT = 30

    def _index_aliases(self, root_url: str, domain: str, known_aliases: set[str]) -> dict[str, str]:
        html = _fetch_html(root_url, headers=self._index_headers(root_url))
        soup = BeautifulSoup(html, "html.parser")
        hot_aliases = self._aliases_from_hot_sections(root_url, domain, known_aliases, soup)
        if hot_aliases:
            return dict(list(hot_aliases.items())[: self.HOT_WIKI_LIMIT])

        aliases: dict[str, str] = {}
        for tag in soup.find_all("a", href=True):
            if len(aliases) >= self.HOT_WIKI_LIMIT:
                break
            href = urljoin(root_url, tag["href"]).split("#", 1)[0]
            parsed = urlparse(href)
            if parsed.netloc.lower() != domain:
                continue
            alias = parsed.path.strip("/").split("/", 1)[0]
            if not self._valid_index_alias(alias) or alias in known_aliases:
                continue
            title = tag.get_text(" ", strip=True)
            aliases.setdefault(alias, title or alias)
        return aliases

    def _aliases_from_hot_sections(
        self,
        root_url: str,
        domain: str,
        known_aliases: set[str],
        soup: BeautifulSoup,
    ) -> dict[str, str]:
        aliases: dict[str, str] = {}
        hot_markers = ("热门", "推荐", "热门WIKI", "热门wiki", "热门 Wiki", "热门wiki")
        containers = []
        for text_node in soup.find_all(string=lambda value: value and any(marker in value for marker in hot_markers)):
            parent = text_node.parent
            for _ in range(4):
                if parent is None:
                    break
                containers.append(parent)
                parent = parent.parent
        for container in containers:
            for tag in container.find_all("a", href=True):
                if len(aliases) >= self.HOT_WIKI_LIMIT:
                    return aliases
                href = urljoin(root_url, tag["href"]).split("#", 1)[0]
                parsed = urlparse(href)
                if parsed.netloc.lower() != domain:
                    continue
                alias = parsed.path.strip("/").split("/", 1)[0]
                if not self._valid_index_alias(alias) or alias in known_aliases:
                    continue
                title = tag.get_text(" ", strip=True)
                aliases.setdefault(alias, title or alias)
        return aliases

    def _valid_index_alias(self, alias: str) -> bool:
        lowered = alias.lower()
        if lowered in self.INDEX_SKIP_ALIASES:
            return False
        if "." in lowered or len(lowered) > 48:
            return False
        return any(char.isalnum() for char in lowered)

    def _index_headers(self, root_url: str) -> dict:
        return {"User-Agent": "Mozilla/5.0 ERFairyTypewriterBot/0.1"}


class GameKeeDiscoveryProfile(WikiIndexDiscoveryMixin, DiscoveryProfile):
    """Discover GameKee wiki/list pages as game knowledge candidates."""

    DOMAINS = {"www.gamekee.com", "gamekee.com"}
    COMMON_WIKIS = {
        "ba": "GameKee 蔚蓝档案 Wiki",
        "ysgl": "GameKee 原神攻略 Wiki",
        "nikke": "GameKee NIKKE Wiki",
        "bh3": "GameKee 崩坏3 Wiki",
    }

    def discover(self, root_url: str) -> list[SourceCandidate]:
        parsed = urlparse(root_url)
        if parsed.netloc.lower() not in self.DOMAINS:
            return []
        alias = parsed.path.strip("/").split("/", 1)[0]
        if alias:
            return [self._candidate(alias, self.COMMON_WIKIS.get(alias, f"GameKee {alias} Wiki"), "known-profile")]

        candidates = [
            self._candidate(wiki_alias, title, "known-profile")
            for wiki_alias, title in self.COMMON_WIKIS.items()
        ]
        for wiki_alias, title in self._safe_index_aliases(root_url).items():
            candidates.append(self._candidate(wiki_alias, f"GameKee {title}", "index-page"))
        return candidates

    def _candidate(self, alias: str, title: str, origin: str) -> SourceCandidate:
        return SourceCandidate(
            url=f"https://www.gamekee.com/{alias}",
            source_type="gamekee-feed",
            title=title,
            reason="从 GameKee 首页解析发现" if origin == "index-page" else "内置推荐的站点 Profile",
            config=_with_discovery_metadata(
                {
                    "category": "game",
                    "max_pages": 50,
                    "max_depth": 0,
                    "delay_seconds": 1.0,
                    "source_score": 0.84,
                    "allowed_domains": ["www.gamekee.com"],
                    "gamekee_alias": alias,
                    **wiki_game_config(alias, title),
                    "scheduler_interval_minutes": 60,
                },
                origin,
                "gamekee",
            ),
        )

    def _safe_index_aliases(self, root_url: str) -> dict[str, str]:
        try:
            return self._index_aliases(root_url, "www.gamekee.com", set(self.COMMON_WIKIS))
        except requests.RequestException:
            return {}


class BiligameWikiDiscoveryProfile(WikiIndexDiscoveryMixin, DiscoveryProfile):
    """Discover Biligame Wiki communities that can be crawled through MediaWiki APIs."""

    DOMAINS = {"wiki.biligame.com"}
    COMMON_WIKIS = {
        "ys": "Biligame 原神 Wiki",
        "sr": "Biligame 崩坏：星穹铁道 Wiki",
        "bh3": "Biligame 崩坏3 Wiki",
        "blhx": "Biligame 碧蓝航线 Wiki",
    }

    def discover(self, root_url: str) -> list[SourceCandidate]:
        parsed = urlparse(root_url)
        if parsed.netloc.lower() not in self.DOMAINS:
            return []
        alias = parsed.path.strip("/").split("/", 1)[0]
        if alias:
            return [self._candidate(alias, self.COMMON_WIKIS.get(alias, f"Biligame {alias} Wiki"), "known-profile")]

        candidates = [
            self._candidate(wiki_alias, title, "known-profile")
            for wiki_alias, title in self.COMMON_WIKIS.items()
        ]
        for wiki_alias, title in self._safe_index_aliases(root_url).items():
            candidates.append(self._candidate(wiki_alias, f"Biligame {title} Wiki", "index-page"))
        return candidates

    def _candidate(self, alias: str, title: str, origin: str) -> SourceCandidate:
        return SourceCandidate(
            url=f"https://wiki.biligame.com/{alias}",
            source_type="biligame-wiki",
            title=title,
            reason="从 Biligame Wiki 首页解析发现" if origin == "index-page" else "内置推荐的站点 Profile",
            config=_with_discovery_metadata(
                {
                    "category": "game",
                    "max_pages": 50,
                    "max_depth": 0,
                    "delay_seconds": 1.0,
                    "source_score": 0.86,
                    "allowed_domains": ["wiki.biligame.com"],
                    "biligame_wiki_alias": alias,
                    **wiki_game_config(alias, title),
                    "scheduler_interval_minutes": 60,
                },
                origin,
                "biligame-wiki",
            ),
        )

    def _safe_index_aliases(self, root_url: str) -> dict[str, str]:
        try:
            return self._index_aliases(root_url, "wiki.biligame.com", set(self.COMMON_WIKIS))
        except requests.RequestException:
            return {}

    def _index_headers(self, root_url: str) -> dict:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }


class GenericWebDiscoveryProfile(DiscoveryProfile):
    """Find RSS, sitemap, and static HTML list candidates."""

    COMMON_FEEDS = ("rss", "feed", "atom.xml", "sitemap.xml")

    def discover(self, root_url: str) -> list[SourceCandidate]:
        html = _fetch_html(root_url)
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[SourceCandidate] = []
        self._add_alternate_feeds(candidates, soup, root_url)
        self._add_common_feed_urls(candidates, root_url)
        self._add_html_list_candidate(candidates, soup, root_url)
        return candidates

    def _generic_config(self) -> dict:
        return _with_discovery_metadata({}, "generic-feed", "generic")

    def _add_alternate_feeds(self, candidates: list[SourceCandidate], soup: BeautifulSoup, root_url: str) -> None:
        for tag in soup.find_all("link", rel=lambda value: value and "alternate" in value):
            href = tag.get("href", "")
            feed_type = tag.get("type", "").lower()
            if not href or not any(marker in feed_type for marker in ("rss", "atom", "xml")):
                continue
            candidates.append(
                SourceCandidate(
                    url=urljoin(root_url, href),
                    source_type="rss-feed",
                    title=tag.get("title", "") or "RSS/Atom feed",
                    reason="从页面 RSS/Sitemap 规则发现",
                    config=self._generic_config(),
                )
            )

    def _add_common_feed_urls(self, candidates: list[SourceCandidate], root_url: str) -> None:
        base = root_url.rstrip("/") + "/"
        for path in self.COMMON_FEEDS:
            url = urljoin(base, path)
            source_type = "sitemap-feed" if path == "sitemap.xml" else "rss-feed"
            candidates.append(
                SourceCandidate(
                    url=url,
                    source_type=source_type,
                    title=path,
                    reason="从页面 RSS/Sitemap 规则发现",
                    config=self._generic_config(),
                )
            )

    def _add_html_list_candidate(self, candidates: list[SourceCandidate], soup: BeautifulSoup, root_url: str) -> None:
        article_like_links = 0
        for tag in soup.find_all("a", href=True):
            href = urljoin(root_url, tag["href"]).lower()
            if any(marker in href for marker in ("/news/", "/article/", "/post/", "/blog/", "/notice/")):
                article_like_links += 1
        if article_like_links >= 2:
            title = soup.title.string.strip() if soup.title and soup.title.string else urlparse(root_url).netloc
            candidates.append(
                SourceCandidate(
                    url=root_url,
                    source_type="html-list-feed",
                    title=title,
                    reason="从页面 RSS/Sitemap 规则发现",
                    config=self._generic_config(),
                )
            )


class SourceDiscoverer:
    """Find controlled source candidates without enabling them automatically."""

    def __init__(self, profiles: list[DiscoveryProfile] | None = None) -> None:
        self.profiles = profiles or [
            MiyousheDiscoveryProfile(),
            MoegirlDiscoveryProfile(),
            BangumiDiscoveryProfile(),
            TapTapDiscoveryProfile(),
            GameKeeDiscoveryProfile(),
            BiligameWikiDiscoveryProfile(),
            GenericWebDiscoveryProfile(),
        ]

    def discover(self, root_url: str) -> list[SourceCandidate]:
        candidates: list[SourceCandidate] = []
        for profile in self.profiles:
            discovered = profile.discover(root_url)
            candidates.extend(discovered)
            if discovered and not isinstance(profile, GenericWebDiscoveryProfile):
                break
            if self._profile_claims_domain(profile, root_url):
                break
        return self._dedupe(candidates)

    def _profile_claims_domain(self, profile: DiscoveryProfile, root_url: str) -> bool:
        domain = urlparse(root_url).netloc.lower()
        if isinstance(profile, MiyousheDiscoveryProfile):
            return domain == "www.miyoushe.com"
        if isinstance(profile, MoegirlDiscoveryProfile):
            return domain in MoegirlDiscoveryProfile.DOMAINS
        if isinstance(profile, BangumiDiscoveryProfile):
            return domain in BangumiDiscoveryProfile.DOMAINS
        if isinstance(profile, TapTapDiscoveryProfile):
            return domain in TapTapDiscoveryProfile.DOMAINS
        if isinstance(profile, GameKeeDiscoveryProfile):
            return domain in GameKeeDiscoveryProfile.DOMAINS
        if isinstance(profile, BiligameWikiDiscoveryProfile):
            return domain in BiligameWikiDiscoveryProfile.DOMAINS
        return False

    def _dedupe(self, candidates: list[SourceCandidate]) -> list[SourceCandidate]:
        by_url: dict[str, SourceCandidate] = {}
        for candidate in candidates:
            current = by_url.get(candidate.url)
            if current is None or self._candidate_score(candidate) > self._candidate_score(current):
                by_url[candidate.url] = candidate
        return list(by_url.values())

    def _candidate_score(self, candidate: SourceCandidate) -> tuple[int, int]:
        origin = candidate.config.get("discovery_origin", "")
        origin_score = {"known-profile": 3, "index-page": 2, "generic-feed": 1}.get(origin, 0)
        return origin_score, len(candidate.config)
