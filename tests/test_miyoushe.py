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


def test_miyoushe_feed_crawler_builds_multiple_documents(monkeypatch):
    def fake_get(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr("erfairy.miyoushe.requests.get", fake_get)

    result = MiyousheFeedCrawler().crawl("miyoushe-ys", max_pages=5, source_score=0.95)

    assert not result.errors
    assert len(result.documents) == 2
    first = result.documents[0]
    assert first.url == "https://www.miyoushe.com/ys/article/123"
    assert first.title == "原神 最新活动公告"
    assert first.category == "news"
    assert first.entity_type == "news"
    assert first.game_title == "原神"
    assert first.source_score == 0.95
    assert first.published_at


def test_miyoushe_feed_profiles_cover_three_games():
    assert set(MIYOUSHE_FEEDS) == {"miyoushe-ys", "miyoushe-bh3", "miyoushe-sr"}
