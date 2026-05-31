from __future__ import annotations

from erfairy.miyoushe import MiyousheFeedCrawler, MIYOUSHE_FEEDS


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {
            "retcode": 0,
            "message": "OK",
            "data": {
                "list": [
                    {
                        "post": {
                            "post_id": "123",
                            "subject": "原神 最新活动公告",
                            "content": "活动今日开启。",
                            "cover": "https://example.com/cover.jpg",
                            "created_at": 1779943926,
                            "images": [],
                        }
                    },
                    {
                        "post": {
                            "post_id": "456",
                            "subject": "原神 攻略讨论",
                            "content": "",
                            "structured_content": '[{"insert":"配队思路"}]',
                            "created_at": 1779943927,
                            "images": ["https://example.com/image.jpg"],
                        }
                    },
                ]
            },
        }


def test_miyoushe_feed_requests_latest_good_and_hot(monkeypatch):
    seen = []

    def fake_get(*args, **kwargs):
        seen.append(kwargs["params"])
        return FakeResponse()

    monkeypatch.setattr("erfairy.miyoushe.requests.get", fake_get)

    result = MiyousheFeedCrawler().crawl("miyoushe-ys", max_pages=5, source_score=0.95)

    assert not result.errors
    assert {(params["is_good"], params["is_hot"]) for params in seen} == {
        ("false", "false"),
        ("true", "false"),
        ("false", "true"),
    }


def test_miyoushe_quality_scores_official_hot_good_and_daily(monkeypatch):
    payload = {
        "retcode": 0,
        "message": "OK",
        "data": {
            "list": [
                {
                    "post": {
                        "post_id": "1",
                        "subject": "官方 版本更新公告",
                        "content": "新活动开启",
                        "created_at": 1,
                    },
                    "is_official_master": True,
                    "stat": {"view_num": 3000},
                    "topics": [{"name": "公告", "is_good": True}],
                },
                {
                    "post": {
                        "post_id": "2",
                        "subject": "每日一水",
                        "content": "",
                        "created_at": 2,
                    },
                    "topics": [{"name": "每日一水", "is_good": False}],
                },
            ]
        },
    }

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    def fake_get(*args, **kwargs):
        params = kwargs["params"]
        if params["is_good"] == "true" or params["is_hot"] == "true":
            payload["data"]["list"] = [payload["data"]["list"][0]]
        else:
            payload["data"]["list"] = [
                {
                    "post": {
                        "post_id": "1",
                        "subject": "官方 版本更新公告",
                        "content": "新活动开启",
                        "created_at": 1,
                    },
                    "is_official_master": True,
                    "stat": {"view_num": 3000},
                    "topics": [{"name": "公告", "is_good": True}],
                },
                {
                    "post": {
                        "post_id": "2",
                        "subject": "每日一水",
                        "content": "",
                        "created_at": 2,
                    },
                    "topics": [{"name": "每日一水", "is_good": False}],
                },
            ]
        return Response()

    monkeypatch.setattr("erfairy.miyoushe.requests.get", fake_get)

    result = MiyousheFeedCrawler().crawl("miyoushe-ys", max_pages=5, source_score=0.95)

    official = next(document for document in result.documents if document.title == "官方 版本更新公告")
    daily = next(document for document in result.documents if document.title == "每日一水")
    assert {"official", "good", "hot", "event-news"} & set(official.content_quality_labels)
    assert official.content_quality_score > daily.content_quality_score
    assert "daily-chat" in daily.content_quality_labels
    assert daily.content_quality_score < 0.5


def test_miyoushe_feed_crawler_builds_multiple_documents(monkeypatch):
    def fake_get(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr("erfairy.miyoushe.requests.get", fake_get)

    result = MiyousheFeedCrawler().crawl("miyoushe-ys", max_pages=5, source_score=0.95)

    assert not result.errors
    assert len(result.documents) == 2
    first = result.documents[0]
    assert first.url == "https://www.miyoushe.com/ys/article/456"
    assert first.title == "原神 攻略讨论"
    assert "guide" in first.content_quality_labels
    assert first.content_quality_score > 0.5
    assert first.category == "news"
    assert first.entity_type == "news"
    assert first.game_title == "原神"
    assert first.source_score == 0.95
    assert first.published_at


def test_miyoushe_feed_profiles_cover_three_games():
    assert set(MIYOUSHE_FEEDS) == {"miyoushe-ys", "miyoushe-bh3", "miyoushe-sr"}


def test_miyoushe_feed_crawler_resolves_candidate_entry_url():
    crawler = MiyousheFeedCrawler()

    profile = crawler._resolve_profile("candidate-9", "https://www.miyoushe.com/sr/")

    assert profile is not None
    assert profile.source_id == "miyoushe-sr"
