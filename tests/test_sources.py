from __future__ import annotations

from pathlib import Path

from erfairy.sources import find_source_config, load_source_configs
from erfairy.store import SQLiteDocumentStore


def test_sources_example_includes_public_sites():
    sources = load_source_configs(Path(__file__).parent.parent / "sources.example.json")
    names = {source.name for source in sources}

    assert "MyAnimeList 动漫新闻" in names
    assert "Anime News Network 首页" in names
    assert "Fate Grand Order 官方新闻" in names
    assert "原神米游社官方社区" in names
    assert "崩坏3米游社官方社区" in names
    assert "崩坏星穹铁道米游社官方社区" in names
    assert all(source.max_depth == 0 for source in sources if source.name != "本地二次元样例站")


def test_find_source_config_builds_crawl_config():
    source = find_source_config("MyAnimeList 动漫新闻", Path(__file__).parent.parent / "sources.example.json")

    assert source is not None
    assert source.source_id == "mal-news"
    crawl_config = source.to_crawl_config()
    assert crawl_config.seeds == [source.entry_url]
    assert crawl_config.allowed_domains == {"myanimelist.net"}
    assert crawl_config.category == "news"
    assert source.max_pages == 50
    assert source.parse_strategy == "article-feed"
    assert source.source_score == 0.85
    assert source.scheduler_interval_minutes == 60


def test_miyoushe_source_config_uses_site_specific_strategy():
    source = find_source_config("原神米游社官方社区", Path(__file__).parent.parent / "sources.example.json")

    assert source is not None
    assert source.source_id == "miyoushe-ys"
    assert source.entry_url == "https://www.miyoushe.com/ys/"
    assert source.allowed_domains == ["www.miyoushe.com"]
    assert source.max_pages == 20
    assert source.parse_strategy == "miyoushe-feed"
    assert source.source_score == 0.95
    assert source.quality_profile == "miyoushe-community"
    assert source.quality_mode == "score"
    assert source.scheduler_interval_minutes == 60


def test_find_source_config_accepts_ascii_source_id():
    source = find_source_config("miyoushe-sr", Path(__file__).parent.parent / "sources.example.json")

    assert source is not None
    assert source.name == "崩坏星穹铁道米游社官方社区"
    assert source.entry_url == "https://www.miyoushe.com/sr"


def test_source_candidate_approve_and_reject_flow(tmp_path):
    store = SQLiteDocumentStore(tmp_path / "sources.sqlite3")
    candidate = store.upsert_source_candidate(
        url="https://example.com/feed.xml",
        source_type="rss-feed",
        title="Example Feed",
        reason="RSS link",
        config={"max_pages": 12, "category": "news"},
    )

    assert candidate["status"] == "pending"
    assert candidate["config"]["max_pages"] == 12
    assert candidate["config"]["category"] == "news"

    approved = store.approve_source_candidate(candidate["id"])

    assert approved is not None
    assert approved["status"] == "approved"
    assert approved["approved_at"]

    rejected = store.reject_source_candidate(candidate["id"])

    assert rejected is not None
    assert rejected["status"] == "rejected"
