from __future__ import annotations

from erfairy.source_discovery import SourceDiscoverer


def test_source_discovery_finds_rss_common_sitemap_and_html_list(monkeypatch):
    html = """
    <html>
      <head>
        <title>Example News</title>
        <link rel="alternate" type="application/rss+xml" href="/rss.xml" title="Main RSS">
      </head>
      <body>
        <a href="/news/2026/one">One article</a>
        <a href="/article/2026/two">Two article</a>
      </body>
    </html>
    """

    class Response:
        ok = True
        text = html
        headers = {"content-type": "text/html; charset=utf-8"}
        apparent_encoding = "utf-8"

        def raise_for_status(self):
            return None

    monkeypatch.setattr("erfairy.source_discovery.requests.get", lambda *args, **kwargs: Response())

    candidates = SourceDiscoverer().discover("https://example.com/")
    by_url = {candidate.url: candidate for candidate in candidates}

    assert by_url["https://example.com/rss.xml"].source_type == "rss-feed"
    assert by_url["https://example.com/sitemap.xml"].source_type == "sitemap-feed"
    assert by_url["https://example.com/"].source_type == "html-list-feed"


def test_source_discovery_finds_miyoushe_profile_without_fetch(monkeypatch):
    def fail_fetch(*args, **kwargs):
        raise AssertionError("miyoushe profile discovery should not fetch the SPA shell")

    monkeypatch.setattr("erfairy.source_discovery.requests.get", fail_fetch)

    candidates = SourceDiscoverer().discover("https://www.miyoushe.com/ys/")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.url == "https://www.miyoushe.com/ys/"
    assert candidate.source_type == "miyoushe-feed"
    assert candidate.title == "原神米游社官方社区"
    assert candidate.config["max_pages"] == 20
    assert candidate.config["category"] == "anime"
    assert candidate.config["source_score"] == 0.95
    assert candidate.config["miyoushe_profile_id"] == "miyoushe-ys"


def test_source_discovery_maps_miyoushe_bh3_and_sr():
    by_url = {
        "https://www.miyoushe.com/bh3": "miyoushe-bh3",
        "https://www.miyoushe.com/sr": "miyoushe-sr",
    }

    for url, profile_id in by_url.items():
        candidates = SourceDiscoverer().discover(url)
        assert candidates[0].source_type == "miyoushe-feed"
        assert candidates[0].config["miyoushe_profile_id"] == profile_id


def test_source_discovery_ignores_unknown_miyoushe_path(monkeypatch):
    def fail_fetch(*args, **kwargs):
        raise AssertionError("unknown miyoushe paths should not fall back to generic discovery")

    monkeypatch.setattr("erfairy.source_discovery.requests.get", fail_fetch)

    assert SourceDiscoverer().discover("https://www.miyoushe.com/unknown") == []


def test_source_discovery_finds_cn_acg_profiles_without_generic_fetch(monkeypatch):
    def fail_fetch(*args, **kwargs):
        raise AssertionError("known profile discovery should not fetch HTML")

    monkeypatch.setattr("erfairy.source_discovery.requests.get", fail_fetch)

    cases = [
        ("https://zh.moegirl.org.cn/", "moegirl-api", "anime", 0.9, 1),
        ("https://bangumi.tv/", "bangumi-api", "anime", 0.88, 1),
        ("https://www.taptap.cn/", "taptap-feed", "game", 0.78, 1),
        ("https://www.gamekee.com/", "gamekee-feed", "game", 0.84, 4),
    ]
    for url, source_type, category, source_score, count in cases:
        candidates = SourceDiscoverer().discover(url)
        assert len(candidates) == count
        assert candidates[0].source_type == source_type
        assert candidates[0].config["category"] == category
        assert candidates[0].config["source_score"] == source_score


def test_source_discovery_maps_specific_taptap_and_gamekee_profiles():
    taptap = SourceDiscoverer().discover("https://www.taptap.cn/app/168332")[0]
    assert taptap.source_type == "taptap-feed"
    assert taptap.url == "https://www.taptap.cn/app/168332"
    assert taptap.config["taptap_app_id"] == "168332"

    gamekee = SourceDiscoverer().discover("https://www.gamekee.com/ba")
    assert len(gamekee) == 1
    assert gamekee[0].source_type == "gamekee-feed"
    assert gamekee[0].url == "https://www.gamekee.com/ba"
    assert gamekee[0].config["gamekee_alias"] == "ba"
