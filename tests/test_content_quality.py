from __future__ import annotations

from erfairy.content_quality import score_community_content


def test_guide_and_character_build_terms_score_high():
    quality = score_community_content("雷电将军养成攻略", "圣遗物词条 配队 技能循环")

    assert "guide" in quality.labels
    assert "character-build" in quality.labels
    assert quality.score > 0.7


def test_daily_chat_short_post_scores_low():
    quality = score_community_content("每日一水", "", topics=["每日一水"])

    assert "daily-chat" in quality.labels
    assert quality.score < 0.5


def test_fan_art_gets_label_without_strong_low_quality_penalty():
    quality = score_community_content("芙宁娜同人插画", "二创绘画分享", topics=["同人图"])

    assert "fan-art" in quality.labels
    assert quality.score >= 0.45
