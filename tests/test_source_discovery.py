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
    assert candidate.config["quality_profile"] == "miyoushe-community"
    assert candidate.config["quality_mode"] == "score"


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
    assert taptap.config["quality_profile"] == "taptap-community"

    gamekee = SourceDiscoverer().discover("https://www.gamekee.com/ba")
    assert len(gamekee) == 1
    assert gamekee[0].source_type == "gamekee-feed"
    assert gamekee[0].url == "https://www.gamekee.com/ba"
    assert gamekee[0].config["gamekee_alias"] == "ba"


def test_source_discovery_parses_biligame_index_page(monkeypatch):
    html = """
    <html><body>
      <a href="/ys">原神</a>
      <a href="/sr">星穹铁道</a>
      <a href="/arknights">明日方舟</a>
      <a href="/pcr">公主连结</a>
      <a href="/wiki/index.php">帮助</a>
    </body></html>
    """

    class Response:
        text = html
        headers = {"content-type": "text/html; charset=utf-8"}
        apparent_encoding = "utf-8"

        def raise_for_status(self):
            return None

    monkeypatch.setattr("erfairy.source_discovery.requests.get", lambda *args, **kwargs: Response())

    candidates = SourceDiscoverer().discover("https://wiki.biligame.com/")
    by_url = {candidate.url: candidate for candidate in candidates}

    assert by_url["https://wiki.biligame.com/ys"].config["discovery_origin"] == "known-profile"
    assert by_url["https://wiki.biligame.com/arknights"].source_type == "biligame-wiki"
    assert by_url["https://wiki.biligame.com/arknights"].reason == "从 Biligame Wiki 首页解析发现"
    assert by_url["https://wiki.biligame.com/arknights"].config["discovery_label"] == "首页解析发现"
    assert by_url["https://wiki.biligame.com/arknights"].config["wiki_game_title"] == "明日方舟"


def test_source_discovery_parses_gamekee_index_page(monkeypatch):
    html = """
    <html><body>
      <a href="/ba">蔚蓝档案</a>
      <a href="/reverse1999">重返未来1999</a>
      <a href="/girlsfrontline2">少女前线2</a>
    </body></html>
    """

    class Response:
        text = html
        headers = {"content-type": "text/html; charset=utf-8"}
        apparent_encoding = "utf-8"

        def raise_for_status(self):
            return None

    monkeypatch.setattr("erfairy.source_discovery.requests.get", lambda *args, **kwargs: Response())

    candidates = SourceDiscoverer().discover("https://www.gamekee.com/")
    by_url = {candidate.url: candidate for candidate in candidates}

    assert by_url["https://www.gamekee.com/ba"].config["discovery_origin"] == "known-profile"
    assert by_url["https://www.gamekee.com/reverse1999"].source_type == "gamekee-feed"
    assert by_url["https://www.gamekee.com/reverse1999"].reason == "从 GameKee 首页解析发现"
    assert by_url["https://www.gamekee.com/reverse1999"].config["discovery_site"] == "gamekee"
    assert by_url["https://www.gamekee.com/reverse1999"].config["wiki_game_title"] == "重返未来1999"


def test_wiki_index_discovery_limits_index_page_candidates(monkeypatch):
    links = "\n".join(f'<a href="/wiki{i}">热门游戏 {i}</a>' for i in range(40))
    html = f"<html><body><section><h2>热门 Wiki</h2>{links}</section></body></html>"

    class Response:
        text = html
        headers = {"content-type": "text/html; charset=utf-8"}
        apparent_encoding = "utf-8"

        def raise_for_status(self):
            return None

    monkeypatch.setattr("erfairy.source_discovery.requests.get", lambda *args, **kwargs: Response())

    candidates = SourceDiscoverer().discover("https://wiki.biligame.com/")
    index_candidates = [
        candidate
        for candidate in candidates
        if candidate.config.get("discovery_origin") == "index-page"
    ]

    assert len(index_candidates) == 30
    assert index_candidates[0].reason == "从 Biligame Wiki 首页解析发现"
    assert index_candidates[0].config["discovery_label"] == "首页解析发现"
    assert index_candidates[0].config["wiki_game_title"] == "热门游戏 0"


def test_source_discovery_maps_specific_biligame_wiki_profile():
    candidates = SourceDiscoverer().discover("https://wiki.biligame.com/ys")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source_type == "biligame-wiki"
    assert candidate.url == "https://wiki.biligame.com/ys"
    assert candidate.config["biligame_wiki_alias"] == "ys"
    assert candidate.config["max_pages"] == 50
    assert candidate.config["source_score"] == 0.86
