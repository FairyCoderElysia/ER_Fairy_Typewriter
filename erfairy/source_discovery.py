"""Discover controlled source candidates from a site URL."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


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


class MiyousheDiscoveryProfile(DiscoveryProfile):
    """Discover known Miyoushe communities that need the site-specific feed parser."""

    COMMUNITIES = {
        "ys": {
            "title": "原神米游社官方社区",
            "profile_id": "miyoushe-ys",
        },
        "bh3": {
            "title": "崩坏3米游社官方社区",
            "profile_id": "miyoushe-bh3",
        },
        "sr": {
            "title": "崩坏：星穹铁道米游社官方社区",
            "profile_id": "miyoushe-sr",
        },
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
                reason="Known Miyoushe community profile",
                config={
                    "category": "anime",
                    "max_pages": 20,
                    "max_depth": 0,
                    "delay_seconds": 1.0,
                    "source_score": 0.95,
                    "allowed_domains": ["www.miyoushe.com"],
                    "miyoushe_profile_id": community["profile_id"],
                    "scheduler_interval_minutes": 60,
                },
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
                reason="Known Moegirl MediaWiki API profile",
                config={
                    "category": "anime",
                    "max_pages": 50,
                    "max_depth": 0,
                    "delay_seconds": 1.0,
                    "source_score": 0.9,
                    "allowed_domains": ["zh.moegirl.org.cn"],
                    "scheduler_interval_minutes": 60,
                },
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
                reason="Known Bangumi public API profile",
                config={
                    "category": "anime",
                    "max_pages": 50,
                    "max_depth": 0,
                    "delay_seconds": 1.0,
                    "source_score": 0.88,
                    "allowed_domains": ["api.bgm.tv", "bangumi.tv", "bgm.tv"],
                    "scheduler_interval_minutes": 60,
                },
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
        if len(path_parts) >= 2 and path_parts[0] == "app" and path_parts[1].isdigit():
            app_id = path_parts[1]
            return [
                SourceCandidate(
                    url=f"https://www.taptap.cn/app/{app_id}",
                    source_type="taptap-feed",
                    title=f"TapTap 游戏页 {app_id}",
                    reason="Known TapTap app profile",
                    config={
                        "category": "game",
                        "max_pages": 50,
                        "max_depth": 0,
                        "delay_seconds": 1.0,
                        "source_score": 0.78,
                        "allowed_domains": ["www.taptap.cn"],
                        "taptap_app_id": app_id,
                        "scheduler_interval_minutes": 60,
                    },
                )
            ]
        app_id = self.DEFAULT_APP_ID
        return [
            SourceCandidate(
                url=f"https://www.taptap.cn/app/{app_id}",
                source_type="taptap-feed",
                title="TapTap 原神游戏页",
                reason="Known TapTap app profile fallback",
                config={
                    "category": "game",
                    "max_pages": 50,
                    "max_depth": 0,
                    "delay_seconds": 1.0,
                    "source_score": 0.78,
                    "allowed_domains": ["www.taptap.cn"],
                    "taptap_app_id": app_id,
                    "scheduler_interval_minutes": 60,
                },
            )
        ]


class GameKeeDiscoveryProfile(DiscoveryProfile):
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
        aliases = [alias] if alias else list(self.COMMON_WIKIS)
        candidates: list[SourceCandidate] = []
        for wiki_alias in aliases:
            title = self.COMMON_WIKIS.get(wiki_alias, f"GameKee {wiki_alias} Wiki")
            candidates.append(
                SourceCandidate(
                    url=f"https://www.gamekee.com/{wiki_alias}",
                    source_type="gamekee-feed",
                    title=title,
                    reason="Known GameKee wiki API profile",
                    config={
                        "category": "game",
                        "max_pages": 50,
                        "max_depth": 0,
                        "delay_seconds": 1.0,
                        "source_score": 0.84,
                        "allowed_domains": ["www.gamekee.com"],
                        "gamekee_alias": wiki_alias,
                        "scheduler_interval_minutes": 60,
                    },
                )
            )
        return candidates


class GenericWebDiscoveryProfile(DiscoveryProfile):
    """Find RSS, sitemap, and static HTML list candidates."""

    COMMON_FEEDS = ("rss", "feed", "atom.xml", "sitemap.xml")

    def discover(self, root_url: str) -> list[SourceCandidate]:
        html = self._fetch(root_url)
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[SourceCandidate] = []
        self._add_alternate_feeds(candidates, soup, root_url)
        self._add_common_feed_urls(candidates, root_url)
        self._add_html_list_candidate(candidates, soup, root_url)
        return candidates

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

    def _add_alternate_feeds(self, candidates: list[SourceCandidate], soup: BeautifulSoup, root_url: str) -> None:
        for tag in soup.find_all("link", rel=lambda value: value and "alternate" in value):
            href = tag.get("href", "")
            feed_type = tag.get("type", "").lower()
            if not href or not any(marker in feed_type for marker in ("rss", "atom", "xml")):
                continue
            source_type = "rss-feed"
            candidates.append(
                SourceCandidate(
                    url=urljoin(root_url, href),
                    source_type=source_type,
                    title=tag.get("title", "") or "RSS/Atom feed",
                    reason="HTML alternate feed link",
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
                    reason="Common feed URL pattern",
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
                    reason=f"Found {article_like_links} article-like links",
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
        return False

    def _dedupe(self, candidates: list[SourceCandidate]) -> list[SourceCandidate]:
        unique: list[SourceCandidate] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate.url in seen:
                continue
            seen.add(candidate.url)
            unique.append(candidate)
        return unique
