"""米游社帖子流抓取适配器。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from .models import CrawlError, CrawlResult, SearchDocument, utc_now_iso
from .parser import clean_text
from .content_quality import score_community_content


MIYOUSHE_API = "https://bbs-api.miyoushe.com/post/wapi/getForumPostList"


@dataclass(slots=True)
class MiyousheFeedProfile:
    """一个米游社游戏分区的帖子流配置。"""

    source_id: str
    path: str
    gids: int
    forum_id: int
    game_title: str
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


MIYOUSHE_FEEDS = {
    "miyoushe-ys": MiyousheFeedProfile(
        source_id="miyoushe-ys",
        path="ys",
        gids=2,
        forum_id=26,
        game_title="原神",
        aliases=["Genshin Impact", "提瓦特"],
        tags=["原神", "米游社", "米哈游", "帖子", "资讯流"],
    ),
    "miyoushe-bh3": MiyousheFeedProfile(
        source_id="miyoushe-bh3",
        path="bh3",
        gids=1,
        forum_id=1,
        game_title="崩坏3",
        aliases=["崩坏三", "Honkai Impact 3rd"],
        tags=["崩坏3", "崩坏三", "米游社", "米哈游", "帖子", "资讯流"],
    ),
    "miyoushe-sr": MiyousheFeedProfile(
        source_id="miyoushe-sr",
        path="sr",
        gids=6,
        forum_id=52,
        game_title="崩坏：星穹铁道",
        aliases=["星穹铁道", "崩铁", "Honkai Star Rail"],
        tags=["崩坏：星穹铁道", "星穹铁道", "崩铁", "米游社", "米哈游", "帖子", "资讯流"],
    ),
}


class MiyousheFeedCrawler:
    """把米游社帖子列表 API 转换为搜索文档。"""

    def crawl(self, source_id: str, max_pages: int, source_score: float, entry_url: str = "") -> CrawlResult:
        profile = self._resolve_profile(source_id, entry_url)
        if profile is None:
            return CrawlResult(
                documents=[],
                errors=[
                    CrawlError(
                        url=MIYOUSHE_API,
                        stage="config",
                        message=f"未找到米游社 feed 配置：{source_id}",
                        category="anime",
                    )
                ],
            )

        try:
            posts = self._fetch_posts(profile, max_pages)
        except requests.RequestException as exc:
            return CrawlResult(
                documents=[],
                errors=[
                    CrawlError(
                        url=MIYOUSHE_API,
                        stage="fetch",
                        message=f"米游社帖子流下载失败：{exc}",
                        category="anime",
                    )
                ],
            )
        except ValueError as exc:
            return CrawlResult(
                documents=[],
                errors=[
                    CrawlError(
                        url=MIYOUSHE_API,
                        stage="parse",
                        message=str(exc),
                        category="anime",
                    )
                ],
            )

        documents = [self._document_from_post(profile, item, source_score) for item in posts]
        return CrawlResult(documents=[document for document in documents if document.title], errors=[])

    def _resolve_profile(self, source_id: str, entry_url: str = "") -> MiyousheFeedProfile | None:
        if source_id in MIYOUSHE_FEEDS:
            return MIYOUSHE_FEEDS[source_id]
        parsed = urlparse(entry_url)
        if parsed.netloc.lower() != "www.miyoushe.com":
            return None
        path = parsed.path.strip("/").split("/", 1)[0]
        for profile in MIYOUSHE_FEEDS.values():
            if profile.path == path:
                return profile
        return None

    def _fetch_posts(self, profile: MiyousheFeedProfile, limit: int) -> list[dict[str, Any]]:
        flows = [
            ("latest", False, False, max(1, min(limit, 20))),
            ("good", True, False, max(1, min(limit, 20))),
            ("hot", False, True, max(1, min(limit, 20))),
        ]
        errors: list[str] = []
        merged: dict[str, dict[str, Any]] = {}
        for flow_name, is_good, is_hot, page_size in flows:
            try:
                for item in self._fetch_flow(profile, page_size, is_good=is_good, is_hot=is_hot):
                    post = item.get("post", {})
                    post_id = str(post.get("post_id", ""))
                    if not post_id:
                        continue
                    item["_erfairy_flow"] = flow_name
                    if is_good:
                        item["_erfairy_is_good"] = True
                    if is_hot:
                        item["_erfairy_is_hot"] = True
                    merged[post_id] = self._merge_item(merged.get(post_id), item)
            except requests.RequestException as exc:
                errors.append(f"{flow_name}: {exc}")
        if not merged and errors:
            raise requests.RequestException("; ".join(errors))
        ranked = sorted(
            merged.values(),
            key=lambda item: (
                self._quality_for_item(profile, item).score,
                self._post_timestamp(item),
            ),
            reverse=True,
        )
        return ranked[: max(1, limit)]

    def _fetch_flow(
        self,
        profile: MiyousheFeedProfile,
        page_size: int,
        *,
        is_good: bool,
        is_hot: bool,
    ) -> list[dict[str, Any]]:
        response = requests.get(
            MIYOUSHE_API,
            params={
                "forum_id": profile.forum_id,
                "gids": profile.gids,
                "page_size": max(1, min(page_size, 20)),
                "is_good": str(is_good).lower(),
                "is_hot": str(is_hot).lower(),
                "sort_type": 1,
            },
            headers={
                "User-Agent": "ERFairyTypewriterBot/0.1 (+local learning project)",
                "Referer": f"https://www.miyoushe.com/{profile.path}/",
                "Origin": "https://www.miyoushe.com",
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("retcode") != 0:
            raise ValueError(f"米游社 API 返回错误：{payload.get('message', 'unknown')}")
        return payload.get("data", {}).get("list", [])

    def _merge_item(self, existing: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
        if existing is None:
            return incoming
        existing["_erfairy_is_good"] = bool(existing.get("_erfairy_is_good") or incoming.get("_erfairy_is_good"))
        existing["_erfairy_is_hot"] = bool(existing.get("_erfairy_is_hot") or incoming.get("_erfairy_is_hot"))
        flows = {str(existing.get("_erfairy_flow", "")), str(incoming.get("_erfairy_flow", ""))}
        existing["_erfairy_flow"] = ",".join(sorted(flow for flow in flows if flow))
        return existing

    def _document_from_post(
        self,
        profile: MiyousheFeedProfile,
        item: dict[str, Any],
        source_score: float,
    ) -> SearchDocument:
        post = item.get("post", item)
        post_id = str(post.get("post_id", ""))
        title = clean_text(str(post.get("subject", "")))
        content = clean_text(str(post.get("content", ""))) or self._structured_text(post)
        if not content:
            content = title
        url = f"https://www.miyoushe.com/{profile.path}/article/{post_id}"
        published_at = self._timestamp_to_iso(post.get("created_at"))
        image_url = str(post.get("cover", "")) or self._first_image(post)
        content_hash = hashlib.sha256(clean_text(f"{title} {content}").lower().encode("utf-8")).hexdigest()
        quality = self._quality_for_item(profile, item, content=content)

        return SearchDocument(
            url=url,
            title=title,
            content=content,
            summary=content[:220],
            tags=profile.tags,
            aliases=profile.aliases,
            entity_type="news",
            game_title=profile.game_title,
            source_score=source_score,
            content_quality_score=quality.score,
            content_quality_labels=quality.labels,
            content_hash=content_hash,
            category="news",
            source="www.miyoushe.com",
            published_at=published_at,
            crawled_at=utc_now_iso(),
            image_url=image_url,
        )

    def _quality_for_item(self, profile: MiyousheFeedProfile, item: dict[str, Any], content: str = ""):
        post = item.get("post", item)
        title = clean_text(str(post.get("subject", "")))
        text = content or clean_text(str(post.get("content", ""))) or self._structured_text(post)
        topics = [clean_text(str(topic.get("name", ""))) for topic in item.get("topics", []) if isinstance(topic, dict)]
        topic_good = any(bool(topic.get("is_good")) for topic in item.get("topics", []) if isinstance(topic, dict))
        user = item.get("user") or {}
        certification = user.get("certification") or {}
        is_official = bool(item.get("is_official_master") or item.get("is_user_master") or certification.get("type"))
        return score_community_content(
            title,
            text,
            topics=[*topics, *profile.tags],
            source="www.miyoushe.com",
            url=f"https://www.miyoushe.com/{profile.path}/article/{post.get('post_id', '')}",
            is_official=is_official,
            is_good=bool(item.get("_erfairy_is_good") or topic_good),
            is_hot=bool(item.get("_erfairy_is_hot")),
            stats=item.get("stat") or {},
        )

    def _post_timestamp(self, item: dict[str, Any]) -> int:
        post = item.get("post", item)
        try:
            return int(post.get("created_at") or 0)
        except (TypeError, ValueError):
            return 0

    def _structured_text(self, post: dict[str, Any]) -> str:
        value = str(post.get("structured_content", ""))
        return clean_text(value.replace('"insert"', " ").replace("image", " "))

    def _first_image(self, post: dict[str, Any]) -> str:
        images = post.get("images") or []
        return str(images[0]) if images else ""

    def _timestamp_to_iso(self, value: Any) -> str:
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            return ""
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")
