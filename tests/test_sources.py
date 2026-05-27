from __future__ import annotations

from pathlib import Path

from erfairy.sources import find_source_config, load_source_configs


def test_sources_example_includes_public_sites():
    sources = load_source_configs(Path(__file__).parent.parent / "sources.example.json")
    names = {source.name for source in sources}

    assert "MyAnimeList 动漫新闻" in names
    assert "Anime News Network 首页" in names
    assert "Fate Grand Order 官方新闻" in names
    assert all(source.max_depth == 0 for source in sources if source.name != "本地二次元样例站")


def test_find_source_config_builds_crawl_config():
    source = find_source_config("MyAnimeList 动漫新闻", Path(__file__).parent.parent / "sources.example.json")

    assert source is not None
    crawl_config = source.to_crawl_config()
    assert crawl_config.seeds == [source.entry_url]
    assert crawl_config.allowed_domains == {"myanimelist.net"}
    assert crawl_config.category == "news"
