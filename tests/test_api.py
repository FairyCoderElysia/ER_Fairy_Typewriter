from fastapi.testclient import TestClient

from erfairy.web import app


def test_search_api_returns_json_results():
    with TestClient(app) as client:
        response = client.get("/search", params={"q": "原神"}, headers={"accept": "application/json"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "原神"
    assert payload["category"] == "all"
    assert payload["total"] >= 1
    assert payload["results"][0]["title"]
    assert "snippet" in payload["results"][0]


def test_search_html_results_page_renders():
    with TestClient(app) as client:
        response = client.get("/search", params={"q": "原神"})

    assert response.status_code == 200
    assert "ER Fairy Typewriter" in response.text
    assert "找到" in response.text
    assert "原神" in response.text
    assert "全部" in response.text


def test_search_can_filter_to_one_category():
    with TestClient(app) as client:
        all_response = client.get("/search", params={"q": "最新活动"}, headers={"accept": "application/json"})
        news_response = client.get("/search", params={"q": "最新活动", "category": "news"}, headers={"accept": "application/json"})

    assert all_response.status_code == 200
    assert news_response.status_code == 200
    all_payload = all_response.json()
    news_payload = news_response.json()
    assert all_payload["category"] == "all"
    assert news_payload["category"] == "news"
    assert news_payload["total"] >= 1
    assert all(item["category"] == "news" for item in news_payload["results"])
    assert all_payload["total"] >= news_payload["total"]


def test_debug_search_explains_scores():
    with TestClient(app) as client:
        response = client.get("/debug/search", params={"q": "原神", "category": "all"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "原神"
    assert "原神" in payload["tokens"]
    assert payload["candidate_count"] >= 1
    first = payload["results"][0]
    assert first["document"]["title"]
    assert first["field_matches"]
    assert first["final_score"] >= first["tfidf_score"]


def test_debug_index_returns_index_stats():
    with TestClient(app) as client:
        response = client.get("/debug/index")

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_count"] >= 1
    assert payload["term_count"] >= 1
    assert payload["posting_count"] >= payload["term_count"]
    assert payload["backend"] == "memory"


def test_crawl_and_reindex_can_be_disabled(monkeypatch):
    monkeypatch.setenv("ERFAIRY_DEV_MUTATIONS", "0")

    from importlib import reload
    import erfairy.web as web_module

    reload(web_module)

    with TestClient(web_module.app) as client:
        crawl_response = client.post(
            "/crawl",
            json={
                "seeds": ["https://example.com/wiki/anime"],
                "max_pages": 1,
                "max_depth": 0,
                "delay_seconds": 0.0,
                "category": "anime",
            },
        )
        reindex_response = client.post("/reindex")

    assert crawl_response.status_code == 200
    assert "开发写入接口已关闭" in crawl_response.json()["detail"]
    assert reindex_response.status_code == 200
    assert "开发写入接口已关闭" in reindex_response.json()["detail"]


def test_index_backend_can_be_switched_with_env(monkeypatch):
    monkeypatch.setenv("ERFAIRY_INDEX_BACKEND", "redis-zset")

    from importlib import reload
    import erfairy.web as web_module

    reload(web_module)

    with TestClient(web_module.app) as client:
        response = client.get("/debug/index")

    assert response.status_code == 200
    assert response.json()["backend"] == "redis-zset-like"


def test_crawl_request_defaults_to_auto_category():
    from erfairy.web import CrawlRequest

    request = CrawlRequest(seeds=["https://example.com/news"])

    assert request.category == "auto"


def test_crawl_request_accepts_ascii_source_id():
    from erfairy.web import CrawlRequest, _crawl_config_from_request

    request = CrawlRequest(source_id="miyoushe-ys")
    crawl_config, source = _crawl_config_from_request(request)

    assert source is not None
    assert source.name == "原神米游社官方社区"
    assert crawl_config.seeds == ["https://www.miyoushe.com/ys/"]


def test_crawl_uses_miyoushe_feed_strategy(monkeypatch):
    from erfairy.models import CrawlResult, SearchDocument
    from erfairy.web import CrawlRequest, _crawl_config_from_request, _crawl_with_source_strategy

    request = CrawlRequest(source_id="miyoushe-ys")
    crawl_config, source = _crawl_config_from_request(request)

    def fake_crawl(self, source_id, max_pages, source_score):
        assert source_id == "miyoushe-ys"
        assert max_pages == 5
        assert source_score == 0.95
        return CrawlResult(
            documents=[SearchDocument(url="local://miyoushe", title="米游社帖子", content="帖子内容")],
            errors=[],
        )

    monkeypatch.setattr("erfairy.web.MiyousheFeedCrawler.crawl", fake_crawl)

    result = _crawl_with_source_strategy(crawl_config, source)

    assert len(result.documents) == 1
    assert result.documents[0].title == "米游社帖子"


def test_crawl_uses_article_feed_strategy(monkeypatch):
    from erfairy.models import CrawlResult, SearchDocument
    from erfairy.web import CrawlRequest, _crawl_config_from_request, _crawl_with_source_strategy

    request = CrawlRequest(source_id="mal-news")
    crawl_config, source = _crawl_config_from_request(request)

    def fake_crawl(self, source_id, max_pages, source_score):
        assert source_id == "mal-news"
        assert max_pages == 20
        assert source_score == 0.85
        return CrawlResult(
            documents=[SearchDocument(url="local://mal", title="MAL news", content="news body")],
            errors=[],
        )

    monkeypatch.setattr("erfairy.web.ArticleFeedCrawler.crawl", fake_crawl)

    result = _crawl_with_source_strategy(crawl_config, source)

    assert len(result.documents) == 1
    assert result.documents[0].title == "MAL news"
