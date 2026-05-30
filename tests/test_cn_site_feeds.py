from __future__ import annotations

import json

from erfairy.cn_site_feeds import GameKeeFeedCrawler, TapTapFeedCrawler
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
