"""米游社帖子流抓取适配器。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests

from .models import CrawlError, CrawlResult, SearchDocument, utc_now_iso
from .parser import clean_text


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

    def crawl(self, source_id: str, max_pages: int, source_score: float) -> CrawlResult:
        profile = MIYOUSHE_FEEDS.get(source_id)
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

        documents = [self._document_from_post(profile, post, source_score) for post in posts]
        return CrawlResult(documents=[document for document in documents if document.title], errors=[])

    def _fetch_posts(self, profile: MiyousheFeedProfile, limit: int) -> list[dict[str, Any]]:
        response = requests.get(
            MIYOUSHE_API,
            params={
                "forum_id": profile.forum_id,
                "gids": profile.gids,
                "page_size": max(1, min(limit, 20)),
                "is_good": "false",
                "is_hot": "false",
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
        return [item.get("post", {}) for item in payload.get("data", {}).get("list", [])]

    def _document_from_post(
        self,
        profile: MiyousheFeedProfile,
        post: dict[str, Any],
        source_score: float,
    ) -> SearchDocument:
        post_id = str(post.get("post_id", ""))
        title = clean_text(str(post.get("subject", "")))
        content = clean_text(str(post.get("content", ""))) or self._structured_text(post)
        if not content:
            content = title
        url = f"https://www.miyoushe.com/{profile.path}/article/{post_id}"
        published_at = self._timestamp_to_iso(post.get("created_at"))
        image_url = str(post.get("cover", "")) or self._first_image(post)
        content_hash = hashlib.sha256(clean_text(f"{title} {content}").lower().encode("utf-8")).hexdigest()

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
            content_hash=content_hash,
            category="news",
            source="www.miyoushe.com",
            published_at=published_at,
            crawled_at=utc_now_iso(),
            image_url=image_url,
        )

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
