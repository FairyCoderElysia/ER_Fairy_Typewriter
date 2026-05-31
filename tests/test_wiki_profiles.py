from __future__ import annotations

from erfairy.wiki_profiles import wiki_game_profile, wiki_game_profile_from_config


def test_known_wiki_aliases_expand_to_chinese_game_titles():
    bh3 = wiki_game_profile("bh3")
    sr = wiki_game_profile("sr")

    assert bh3.game_title == "崩坏3"
    assert "崩坏三" in bh3.tags
    assert "bh3" in bh3.tags
    assert sr.game_title == "崩坏：星穹铁道"
    assert "星穹铁道" in sr.tags
    assert "崩铁" in sr.tags


def test_wiki_profile_config_overrides_alias_fallback():
    profile = wiki_game_profile_from_config(
        "unknown",
        {"wiki_game_title": "明日方舟", "wiki_game_aliases": ["Arknights"]},
    )

    assert profile.game_title == "明日方舟"
    assert profile.tags == ["unknown", "明日方舟", "Arknights"]
