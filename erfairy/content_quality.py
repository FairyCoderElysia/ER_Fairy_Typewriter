"""Community content quality scoring rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .parser import clean_text


@dataclass(slots=True)
class ContentQuality:
    score: float = 0.5
    labels: list[str] = field(default_factory=list)


GUIDE_TERMS = {
    "攻略",
    "养成",
    "培养",
    "配队",
    "阵容",
    "机制",
    "圣遗物",
    "武器",
    "光锥",
    "遗器",
    "词条",
    "抽卡建议",
    "角色测评",
    "技能循环",
    "毕业面板",
}
EVENT_TERMS = {"公告", "活动", "版本", "更新", "前瞻", "维护", "补偿", "复刻", "卡池", "兑换码", "官方"}
DAILY_TERMS = {"每日一水", "水帖", "闲聊", "随手拍", "晒图", "表情包", "打卡", "摸鱼", "整活"}
FAN_ART_TERMS = {"同人", "二创", "绘画", "插画", "摸鱼", "cos", "cosplay", "壁纸"}


def score_community_content(
    title: str,
    content: str = "",
    *,
    topics: list[str] | None = None,
    source: str = "",
    url: str = "",
    is_official: bool = False,
    is_good: bool = False,
    is_hot: bool = False,
    stats: dict[str, Any] | None = None,
    base_score: float = 0.5,
) -> ContentQuality:
    """Return a small quality score and labels for community content."""

    labels: list[str] = []
    score = base_score
    topics = topics or []
    stats = stats or {}
    haystack = clean_text(" ".join([title, content[:500], " ".join(topics), source, url])).lower()

    if is_official or _contains_any(haystack, EVENT_TERMS):
        labels.append("official" if is_official else "event-news")
        score += 0.25 if is_official else 0.18

    if is_good:
        labels.append("good")
        score += 0.18

    if is_hot or _high_interaction(stats):
        labels.append("hot")
        score += 0.14

    if _contains_any(haystack, GUIDE_TERMS):
        labels.append("guide")
        score += 0.2
        if _contains_any(haystack, {"养成", "培养", "配队", "阵容", "圣遗物", "光锥", "遗器", "毕业面板"}):
            labels.append("character-build")
            score += 0.08

    if _contains_any(haystack, EVENT_TERMS) and "event-news" not in labels:
        labels.append("event-news")
        score += 0.12

    if _contains_any(haystack, FAN_ART_TERMS):
        labels.append("fan-art")
        score += 0.03

    if _contains_any(haystack, DAILY_TERMS):
        labels.append("daily-chat")
        score -= 0.16

    content_length = len(clean_text(content))
    if content_length < 20 and not _has_high_value_label(labels) and "fan-art" not in labels:
        score -= 0.1

    return ContentQuality(score=_clamp(score), labels=_dedupe(labels))


def _contains_any(text: str, terms: set[str]) -> bool:
    return any(term.lower() in text for term in terms)


def _high_interaction(stats: dict[str, Any]) -> bool:
    values = []
    for key in ("view_num", "view_count", "reply_num", "reply_count", "like_num", "like_count", "upvote_num", "favorite_num"):
        try:
            values.append(int(stats.get(key) or 0))
        except (TypeError, ValueError):
            continue
    return any(value >= 1000 for value in values) or sum(values) >= 1500


def _has_high_value_label(labels: list[str]) -> bool:
    return any(label in labels for label in ("official", "event-news", "good", "hot", "guide", "character-build"))


def _clamp(score: float) -> float:
    return round(max(0.0, min(1.0, score)), 3)


def _dedupe(labels: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for label in labels:
        if label in seen:
            continue
        seen.add(label)
        unique.append(label)
    return unique
