from __future__ import annotations

import json

import requests

from erfairy.cn_site_feeds import BiligameWikiCrawler, GameKeeFeedCrawler, TapTapFeedCrawler
from erfairy.sources import SourceConfig


def test_gamekee_feed_crawler_builds_documents_from_update_api(monkeypatch):
    update_payload = {
        "code": 0,
        "data": [
            {
                "id": 123,
                "title": "角色攻略",
                "summary": "培养建议",
                "created_at": 1760000000,
                "thumb": "//cdn.example.com/cover.jpg",
                "content_cdn": "//api-cdn.gamekee.com/wiki2.0/pro/1/content/123.json",
            }
        ],
    }
    cdn_payload = {
        "content": json.dumps(
            [{"type": "paragraph", "children": [{"text": "技能循环和配队说明"}]}],
            ensure_ascii=False,
        )
    }

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, **kwargs):
        if "updateList" in url:
            assert kwargs["headers"]["game-alias"] == "ba"
            return Response(update_payload)
        if "cdnimg-test" in url:
            return Response(cdn_payload)
        raise AssertionError(url)

    monkeypatch.setattr("erfairy.cn_site_feeds.requests.get", fake_get)
    source = SourceConfig(
        name="GameKee BA",
        entry_url="https://www.gamekee.com/ba",
        allowed_domains=["www.gamekee.com"],
        category="game",
        max_pages=5,
        source_score=0.84,
        parse_strategy="gamekee-feed",
    )

    result = GameKeeFeedCrawler().crawl(source)

    assert not result.errors
    assert len(result.documents) == 1
    assert result.documents[0].title == "角色攻略"
    assert result.documents[0].url == "https://www.gamekee.com/ba/123.html"
    assert "技能循环" in result.documents[0].content
    assert result.documents[0].source == "www.gamekee.com"
    assert result.documents[0].game_title == "蔚蓝档案"
    assert "蔚蓝档案" in result.documents[0].tags
    assert "ba" in result.documents[0].tags


def test_taptap_feed_crawler_builds_documents_from_app_pages(monkeypatch):
    html = """
    <html>
      <head>
        <title>原神 - TapTap</title>
        <meta property="og:title" content="原神 | TapTap">
        <meta name="description" content="开放世界冒险游戏">
        <meta property="og:image" content="https://img.example.com/app.jpg">
      </head>
      <body><main>版本更新 攻略 论坛 活动</main></body>
    </html>
    """

    class Response:
        status_code = 200
        text = html
        headers = {"content-type": "text/html; charset=utf-8"}
        apparent_encoding = "utf-8"

        def raise_for_status(self):
            return None

    monkeypatch.setattr("erfairy.cn_site_feeds.requests.get", lambda *args, **kwargs: Response())
    source = SourceConfig(
        name="TapTap 原神",
        entry_url="https://www.taptap.cn/app/168332",
        allowed_domains=["www.taptap.cn"],
        category="game",
        max_pages=2,
        source_score=0.78,
        parse_strategy="taptap-feed",
    )

    result = TapTapFeedCrawler().crawl(source)

    assert not result.errors
    assert len(result.documents) == 2
    assert result.documents[0].title == "原神"
    assert result.documents[0].source == "www.taptap.cn"
    assert result.documents[0].source_score == 0.78
    assert result.documents[1].url.endswith("/all-info")
    assert result.documents[1].content_quality_score >= 0.6


def test_taptap_strategy_and_event_pages_get_higher_quality(monkeypatch):
    def fake_get(url, **kwargs):
        class Response:
            headers = {"content-type": "text/html; charset=utf-8"}
            apparent_encoding = "utf-8"

            def raise_for_status(self):
                return None

            @property
            def text(self):
                if url.endswith("/strategy"):
                    body = "角色攻略 配队 养成 技能循环"
                elif url.endswith("/game-event"):
                    body = "版本活动 更新公告"
                else:
                    body = "玩家论坛 闲聊"
                return f"<html><head><title>原神 - TapTap</title></head><body>{body}</body></html>"

        return Response()

    monkeypatch.setattr("erfairy.cn_site_feeds.requests.get", fake_get)
    source = SourceConfig(
        name="TapTap 原神",
        entry_url="https://www.taptap.cn/app/168332",
        allowed_domains=["www.taptap.cn"],
        category="game",
        max_pages=5,
        source_score=0.78,
        parse_strategy="taptap-feed",
    )

    result = TapTapFeedCrawler().crawl(source)

    by_url = {document.url: document for document in result.documents}
    strategy = by_url["https://www.taptap.cn/app/168332/strategy"]
    event = by_url["https://www.taptap.cn/app/168332/game-event"]
    topic = by_url["https://www.taptap.cn/app/168332/topic"]
    assert "guide" in strategy.content_quality_labels
    assert "event-news" in event.content_quality_labels
    assert strategy.content_quality_score > topic.content_quality_score
    assert event.content_quality_score > topic.content_quality_score


def test_taptap_feed_requires_app_url():
    source = SourceConfig(
        name="TapTap",
        entry_url="https://www.taptap.cn/",
        allowed_domains=["www.taptap.cn"],
        category="game",
        parse_strategy="taptap-feed",
    )

    result = TapTapFeedCrawler().crawl(source)

    assert not result.documents
    assert result.errors[0].stage == "config"


def test_biligame_wiki_crawler_builds_documents_from_mediawiki_api(monkeypatch):
    recent_payload = {
        "query": {
            "recentchanges": [
                {"title": "芙宁娜", "timestamp": "2026-05-31T00:00:00Z"},
                {"title": "芙宁娜", "timestamp": "2026-05-30T00:00:00Z"},
                {"title": "特殊:最近更改", "timestamp": "2026-05-29T00:00:00Z"},
                {"title": "那维莱特", "timestamp": "2026-05-28T00:00:00Z"},
            ]
        }
    }
    parse_payloads = {
        "芙宁娜": {
            "parse": {
                "displaytitle": "芙宁娜",
                "text": "<div><p>水元素角色，拥有治疗和增伤机制。</p></div>",
                "categories": [{"category": "角色"}, {"category": "枫丹"}],
            }
        },
        "那维莱特": {
            "parse": {
                "displaytitle": "那维莱特",
                "text": "<div><p>重击输出角色，适合围绕生命值构筑。</p></div>",
                "categories": [{"category": "角色"}],
            }
        },
    }

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, params=None, **kwargs):
        assert url == "https://wiki.biligame.com/ys/api.php"
        assert kwargs["headers"]["X-Requested-With"] == "XMLHttpRequest"
        assert kwargs["headers"]["Referer"] == "https://wiki.biligame.com/ys/%E9%A6%96%E9%A1%B5"
        if params["action"] == "query":
            return Response(recent_payload)
        if params["action"] == "parse":
            return Response(parse_payloads[params["page"]])
        raise AssertionError(params)

    monkeypatch.setattr("erfairy.cn_site_feeds.requests.get", fake_get)
    source = SourceConfig(
        name="Biligame 原神 Wiki",
        entry_url="https://wiki.biligame.com/ys",
        allowed_domains=["wiki.biligame.com"],
        category="game",
        max_pages=2,
        source_score=0.86,
        parse_strategy="biligame-wiki",
    )

    result = BiligameWikiCrawler().crawl(source)

    assert not result.errors
    assert len(result.documents) == 2
    assert result.documents[0].title == "芙宁娜"
    assert result.documents[0].url == "https://wiki.biligame.com/ys/%E8%8A%99%E5%AE%81%E5%A8%9C"
    assert "治疗" in result.documents[0].content
    assert "角色" in result.documents[0].tags
    assert result.documents[0].source == "wiki.biligame.com"
    assert result.documents[0].source_score == 0.86
    assert result.documents[0].game_title == "原神"
    assert "原神" in result.documents[0].tags
    assert "ys" in result.documents[0].tags


def test_biligame_wiki_crawler_requires_alias():
    source = SourceConfig(
        name="Biligame",
        entry_url="https://wiki.biligame.com/",
        allowed_domains=["wiki.biligame.com"],
        category="game",
        parse_strategy="biligame-wiki",
    )

    result = BiligameWikiCrawler().crawl(source)

    assert not result.documents
    assert result.errors[0].stage == "config"


def test_biligame_wiki_retries_transient_proxy_errors(monkeypatch):
    calls = {"count": 0}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"query": {"recentchanges": [{"title": "测试页面"}]}}

    def fake_get(url, params=None, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            raise requests.exceptions.ProxyError("proxy disconnected")
        return Response()

    monkeypatch.setattr("erfairy.cn_site_feeds.requests.get", fake_get)
    monkeypatch.setattr("erfairy.cn_site_feeds.time.sleep", lambda seconds: None)

    titles = BiligameWikiCrawler()._fetch_titles("https://wiki.biligame.com/ys/api.php", "ys", 1)

    assert titles == ["测试页面"]
    assert calls["count"] == 3
