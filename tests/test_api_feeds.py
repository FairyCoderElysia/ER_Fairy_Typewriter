from __future__ import annotations

from erfairy.api_feeds import ApiFeedCrawler
from erfairy.sources import SourceConfig


def test_bangumi_api_crawler_builds_calendar_documents(monkeypatch):
    payload = [
        {
            "weekday": {"cn": "星期一"},
            "items": [
                {
                    "id": 1,
                    "name": "Sousou no Frieren",
                    "name_cn": "葬送的芙莉莲",
                    "summary": "勇者一行打倒魔王后的故事。",
                    "url": "https://bgm.tv/subject/1",
                    "air_date": "2026-01-01",
                    "rating": {"score": 8.8},
                    "images": {"common": "https://lain.bgm.tv/pic.jpg"},
                }
            ],
        }
    ]

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    monkeypatch.setattr("erfairy.api_feeds.requests.get", lambda *args, **kwargs: Response())
    source = SourceConfig(
        name="Bangumi",
        entry_url="https://api.bgm.tv/calendar",
        allowed_domains=["api.bgm.tv"],
        category="anime",
        max_pages=5,
        source_score=0.88,
        parse_strategy="bangumi-api",
    )

    result = ApiFeedCrawler().crawl(source)

    assert not result.errors
    assert len(result.documents) == 1
    assert result.documents[0].title == "葬送的芙莉莲"
    assert result.documents[0].aliases == ["Sousou no Frieren"]
    assert result.documents[0].source == "bangumi.tv"
    assert result.documents[0].source_score == 0.88


def test_moegirl_api_crawler_builds_search_documents(monkeypatch):
    payload = {
        "query": {
            "pages": {
                "100": {
                    "pageid": 100,
                    "title": "派蒙",
                    "extract": "派蒙是游戏《原神》中的角色。",
                    "fullurl": "https://zh.moegirl.org.cn/派蒙",
                }
            }
        }
    }

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    monkeypatch.setattr("erfairy.api_feeds.requests.get", lambda *args, **kwargs: Response())
    source = SourceConfig(
        name="萌娘百科",
        entry_url="https://zh.moegirl.org.cn/api.php",
        allowed_domains=["zh.moegirl.org.cn"],
        category="anime",
        max_pages=1,
        source_score=0.9,
        parse_strategy="moegirl-api",
    )

    result = ApiFeedCrawler().crawl(source)

    assert not result.errors
    assert len(result.documents) == 1
    assert result.documents[0].title == "派蒙"
    assert result.documents[0].source == "zh.moegirl.org.cn"
    assert result.documents[0].entity_type == "wiki"
