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
    assert 'name="source"' in response.text
    assert 'name="date_range"' in response.text
    assert "fine-filters" in response.text


def test_search_api_accepts_source_and_date_filters():
    with TestClient(app) as client:
        response = client.get(
            "/search",
            params={"q": "原神", "source": "sample", "date_range": "365d"},
            headers={"accept": "application/json"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "sample"
    assert payload["date_range"] == "365d"
    assert payload["total"] >= 1
    assert all(item["source"] == "sample" for item in payload["results"])


def test_search_html_empty_query_renders_empty_state():
    with TestClient(app) as client:
        response = client.get("/search")

    assert response.status_code == 200
    assert "输入关键词开始搜索" in response.text
    assert 'name="source"' in response.text
    assert 'name="date_range"' in response.text


def test_search_html_no_results_renders_empty_result_state(monkeypatch):
    import erfairy.web as web_module

    monkeypatch.setattr(
        web_module.search_service,
        "search",
        lambda q, page, per_page, category, source, date_range: {
            "query": q,
            "page": page,
            "per_page": per_page,
            "total": 0,
            "results": [],
        },
    )

    with TestClient(web_module.app) as client:
        response = client.get("/search", params={"q": "没有结果"})

    assert response.status_code == 200
    assert "没有找到匹配结果" in response.text


def test_search_html_keeps_selected_fine_filters():
    with TestClient(app) as client:
        response = client.get(
            "/search",
            params={"q": "原神", "source": "sample", "date_range": "365d"},
        )

    assert response.status_code == 200
    assert '<option value="sample" selected>sample</option>' in response.text
    assert '<option value="365d" selected>最近 1 年</option>' in response.text


def test_search_pagination_preserves_fine_filters(monkeypatch):
    import erfairy.web as web_module

    def fake_search(q, page, per_page, category, source, date_range):
        return {
            "query": q,
            "page": page,
            "per_page": per_page,
            "total": 11,
            "results": [
                {
                    "id": 1,
                    "url": "local://page",
                    "title": "分页测试",
                    "summary": "",
                    "content": "",
                    "tags": [],
                    "aliases": [],
                    "entity_type": "",
                    "game_title": "",
                    "character_name": "",
                    "source_score": 0.0,
                    "content_hash": "",
                    "category": category or "anime",
                    "source": source or "sample",
                    "published_at": "",
                    "crawled_at": "",
                    "image_url": "",
                    "score": 1.0,
                    "snippet": "分页测试",
                }
            ],
        }

    monkeypatch.setattr(web_module.search_service, "search", fake_search)

    with TestClient(web_module.app) as client:
        response = client.get(
            "/search",
            params={"q": "分页", "source": "sample", "date_range": "7d"},
        )

    assert response.status_code == 200
    assert "source=sample" in response.text
    assert "date_range=7d" in response.text
    assert "page=2" in response.text


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
        response = client.get("/debug/search", params={"q": "原神", "category": "all"}, headers={"accept": "application/json"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "原神"
    assert "原神" in payload["tokens"]
    assert payload["candidate_count"] >= 1
    first = payload["results"][0]
    assert first["document"]["title"]
    assert "content_quality_score" in first["document"]
    assert "content_quality_labels" in first["document"]
    assert "quality_score" in first
    assert first["field_matches"]
    assert first["final_score"] >= first["tfidf_score"]


def test_debug_search_html_page_renders():
    with TestClient(app) as client:
        response = client.get("/debug/search", params={"q": "原神", "category": "all"})

    assert response.status_code == 200
    assert "Search Debug - ER Fairy Typewriter" in response.text
    assert "搜索解释" in response.text
    assert "field_weight" in response.text


def test_debug_home_page_renders():
    with TestClient(app) as client:
        response = client.get("/debug")

    assert response.status_code == 200
    assert "Debug Console - ER Fairy Typewriter" in response.text
    assert "调试总览" in response.text
    assert "/debug/search" in response.text
    assert "/debug/index" in response.text
    assert "/debug/redis" in response.text
    assert "/debug/crawls" in response.text
    assert "/debug/compare-index" in response.text


def test_debug_index_returns_index_stats():
    with TestClient(app) as client:
        response = client.get("/debug/index")

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_count"] >= 1
    assert payload["term_count"] >= 1
    assert payload["posting_count"] >= payload["term_count"]
    assert payload["backend"] == "memory"
    assert payload["index_build"]["sqlite_document_count"] >= payload["document_count"]
    assert "ready" in payload["index_build"]


def test_debug_redis_returns_guidance_when_backend_is_not_redis():
    with TestClient(app) as client:
        response = client.get("/debug/redis", headers={"accept": "application/json"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["backend"] == "memory"
    assert "ERFAIRY_INDEX_BACKEND=redis" in payload["message"]


def test_debug_redis_html_page_renders():
    with TestClient(app) as client:
        response = client.get("/debug/redis")

    assert response.status_code == 200
    assert "Redis Debug - ER Fairy Typewriter" in response.text
    assert "ERFAIRY_INDEX_BACKEND=redis" in response.text


def test_debug_crawls_returns_recent_runs_json(monkeypatch):
    import erfairy.web as web_module

    runs = [
        {
            "id": 7,
            "started_at": "2026-05-28T00:00:00+00:00",
            "finished_at": "2026-05-28T00:00:01+00:00",
            "source_count": 1,
            "saved_count": 3,
            "error_count": 1,
            "category": "news",
            "status": "completed",
            "errors": [
                {
                    "url": "https://example.com/fail",
                    "stage": "download",
                    "message": "timeout",
                    "depth": 0,
                    "category": "news",
                    "crawled_at": "2026-05-28T00:00:00+00:00",
                }
            ],
        }
    ]
    monkeypatch.setattr(web_module.store, "recent_crawl_runs", lambda limit: runs)
    monkeypatch.setattr(web_module.store, "count", lambda: 42)

    with TestClient(web_module.app) as client:
        response = client.get("/debug/crawls", params={"limit": 5}, headers={"accept": "application/json"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_count"] == 1
    assert payload["limit"] == 5
    assert payload["total_documents"] == 42
    assert payload["runs"][0]["id"] == 7
    assert payload["runs"][0]["errors"][0]["message"] == "timeout"


def test_debug_crawls_html_page_renders(monkeypatch):
    import erfairy.web as web_module

    monkeypatch.setattr(web_module.store, "recent_crawl_runs", lambda limit: [])
    monkeypatch.setattr(web_module.store, "count", lambda: 0)

    with TestClient(web_module.app) as client:
        response = client.get("/debug/crawls")

    assert response.status_code == 200
    assert "Crawl Runs - ER Fairy Typewriter" in response.text
    assert "暂无抓取记录" in response.text


def test_crawl_all_continues_when_one_source_fails(monkeypatch):
    import erfairy.web as web_module
    from erfairy.sources import SourceConfig

    sources = [
        SourceConfig(name="Good", entry_url="https://good.example/rss", allowed_domains=["good.example"], source_id="good"),
        SourceConfig(name="Bad", entry_url="https://bad.example/rss", allowed_domains=["bad.example"], source_id="bad"),
    ]
    monkeypatch.setattr(web_module, "_enabled_source_configs", lambda: sources)
    monkeypatch.setattr(web_module.store, "count", lambda: 10)

    def fake_run(source_id):
        if source_id == "bad":
            raise RuntimeError("boom")
        return {"source_id": source_id, "saved": 2, "errors": 0}

    monkeypatch.setattr(web_module, "run_crawl_for_source", fake_run)

    with TestClient(web_module.app) as client:
        response = client.post("/crawl/all")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["source_count"] == 2
    assert payload["results"][0]["saved"] == 2
    assert payload["results"][1]["errors"] == 1


def test_sources_discover_writes_pending_candidates(monkeypatch):
    from erfairy.source_discovery import SourceCandidate

    monkeypatch.setattr(
        "erfairy.web.SourceDiscoverer.discover",
        lambda self, url: [
            SourceCandidate(
                url="https://example.com/feed.xml",
                source_type="rss-feed",
                title="Feed",
                reason="RSS",
                config={"max_pages": 12},
            )
        ],
    )

    with TestClient(app) as client:
        response = client.post("/sources/discover", json={"url": "https://example.com/"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["discovered"] == 1
    assert payload["candidates"][0]["status"] == "pending"
    assert payload["candidates"][0]["config"]["max_pages"] == 12


def test_debug_sources_returns_configured_and_candidate_sources(monkeypatch):
    import erfairy.web as web_module
    candidates = [
        {
            "id": 1,
            "url": "https://www.miyoushe.com/ys/",
            "source_type": "miyoushe-feed",
            "title": "Miyoushe",
            "status": "pending",
            "reason": "Known Miyoushe community profile",
            "config": {"max_pages": 5, "category": "anime", "source_score": 0.95},
            "config_json": '{"max_pages": 5, "category": "anime", "source_score": 0.95}',
            "discovered_at": "2026-05-30T00:00:00+00:00",
            "approved_at": "",
        }
    ]

    monkeypatch.setattr(web_module.store, "source_candidates_page", lambda **kwargs: candidates)
    monkeypatch.setattr(web_module.store, "count_source_candidates", lambda **kwargs: len(candidates))

    with TestClient(web_module.app) as client:
        response = client.get("/debug/sources", headers={"accept": "application/json"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["configured_sources"]
    assert "candidates" in payload
    assert payload["candidates"][0]["effective_config"]["max_pages"] == 20
    assert payload["candidates"][0]["effective_config"]["quality_profile"] == "miyoushe-community"

    html_response = client.get("/debug/sources")
    assert html_response.status_code == 200
    assert "/sources/candidates/1/test-crawl" in html_response.text
    assert "/sources/candidates/1/approve?crawl=true" in html_response.text
    assert "max=20" in html_response.text
    assert "miyoushe-community" in html_response.text


def test_debug_sources_filters_by_status_and_origin(monkeypatch):
    import erfairy.web as web_module

    candidates = [
        {
            "id": 1,
            "url": "https://wiki.biligame.com/arknights",
            "source_type": "biligame-wiki",
            "title": "Biligame Arknights",
            "status": "pending",
            "reason": "从 Biligame Wiki 首页解析发现",
            "config": {"discovery_origin": "index-page", "discovery_label": "首页解析发现"},
            "config_json": "{}",
            "discovered_at": "2026-05-30T00:00:00+00:00",
            "approved_at": "",
        },
        {
            "id": 2,
            "url": "https://wiki.biligame.com/ys",
            "source_type": "biligame-wiki",
            "title": "Biligame Ys",
            "status": "approved",
            "reason": "内置推荐的站点 Profile",
            "config": {"discovery_origin": "known-profile", "discovery_label": "内置推荐源"},
            "config_json": "{}",
            "discovered_at": "2026-05-30T00:00:00+00:00",
            "approved_at": "2026-05-30T00:00:01+00:00",
        },
    ]
    def filtered_candidates_page(status=None, origin=None, limit=50, offset=0):
        filtered = [
            candidate
            for candidate in candidates
            if (not status or status == "all" or candidate["status"] == status)
            and (not origin or origin == "all" or candidate["config"].get("discovery_origin") == origin)
        ]
        return filtered[offset : offset + limit]

    def count_filtered_candidates(status=None, origin=None):
        return len(filtered_candidates_page(status=status, origin=origin, limit=100, offset=0))

    monkeypatch.setattr(web_module.store, "source_candidates_page", filtered_candidates_page)
    monkeypatch.setattr(web_module.store, "count_source_candidates", count_filtered_candidates)

    with TestClient(web_module.app) as client:
        response = client.get(
            "/debug/sources",
            params={"status": "pending", "origin": "index-page"},
            headers={"accept": "application/json"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_count"] == 1
    assert payload["total_candidates"] == 1
    assert payload["candidates"][0]["id"] == 1
    assert payload["candidates"][0]["discovery_label"] == "首页解析发现"
    assert payload["candidates"][0]["display_name"] == "biligame-wiki Arknights页面"


def test_debug_sources_paginates_candidates(monkeypatch):
    import erfairy.web as web_module

    candidates = [
        {
            "id": index,
            "url": f"https://wiki.biligame.com/wiki{index}",
            "source_type": "biligame-wiki",
            "title": f"Wiki {index}",
            "status": "pending",
            "reason": "从 Biligame Wiki 首页解析发现",
            "config": {"discovery_origin": "index-page", "discovery_label": "首页解析发现"},
            "config_json": "{}",
            "discovered_at": "2026-05-30T00:00:00+00:00",
            "approved_at": "",
        }
        for index in range(1, 61)
    ]

    monkeypatch.setattr(
        web_module.store,
        "source_candidates_page",
        lambda status=None, origin=None, limit=50, offset=0: candidates[offset : offset + limit],
    )
    monkeypatch.setattr(web_module.store, "count_source_candidates", lambda status=None, origin=None: len(candidates))

    with TestClient(web_module.app) as client:
        response = client.get("/debug/sources?page=2", headers={"accept": "application/json"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_count"] == 10
    assert payload["total_candidates"] == 60
    assert payload["page"] == 2
    assert payload["page_count"] == 2
    assert payload["has_prev"] is True
    assert payload["has_next"] is False
    assert payload["candidates"][0]["id"] == 51


def test_debug_sources_candidate_display_name_uses_wiki_game_title(monkeypatch):
    import erfairy.web as web_module

    candidates = [
        {
            "id": 1,
            "url": "https://wiki.biligame.com/ys",
            "source_type": "biligame-wiki",
            "title": "Biligame 原神 Wiki",
            "status": "pending",
            "reason": "内置推荐的站点 Profile",
            "config": {
                "discovery_origin": "known-profile",
                "discovery_label": "内置推荐源",
                "wiki_game_title": "原神",
                "wiki_game_aliases": ["Genshin Impact"],
            },
            "config_json": "{}",
            "discovered_at": "2026-05-30T00:00:00+00:00",
            "approved_at": "",
        }
    ]

    monkeypatch.setattr(web_module.store, "source_candidates_page", lambda **kwargs: candidates)
    monkeypatch.setattr(web_module.store, "count_source_candidates", lambda **kwargs: len(candidates))

    with TestClient(web_module.app) as client:
        response = client.get("/debug/sources", headers={"accept": "application/json"})
        html_response = client.get("/debug/sources")

    assert response.status_code == 200
    assert response.json()["candidates"][0]["display_name"] == "biligame-wiki 原神页面"
    assert "biligame-wiki 原神页面" in html_response.text


def test_bulk_candidate_approve_and_reject(monkeypatch):
    import erfairy.web as web_module

    def candidate(candidate_id, status):
        return {
            "id": candidate_id,
            "url": f"https://example.com/{candidate_id}",
            "source_type": "rss-feed",
            "title": f"Candidate {candidate_id}",
            "status": status,
            "reason": "从页面 RSS/Sitemap 规则发现",
            "config": {"discovery_origin": "generic-feed", "discovery_label": "通用 RSS/Sitemap 发现"},
            "config_json": "{}",
            "discovered_at": "2026-05-30T00:00:00+00:00",
            "approved_at": "",
        }

    monkeypatch.setattr(web_module.store, "approve_source_candidate", lambda candidate_id: candidate(candidate_id, "approved"))
    monkeypatch.setattr(web_module.store, "reject_source_candidate", lambda candidate_id: candidate(candidate_id, "rejected"))

    with TestClient(web_module.app) as client:
        approve = client.post("/sources/candidates/bulk-approve", json={"candidate_ids": [1, 2]})
        reject = client.post("/sources/candidates/bulk-reject", data={"candidate_ids": ["3", "4"]})

    assert approve.status_code == 200
    assert approve.json()["approved"] == 2
    assert approve.json()["results"][0]["candidate"]["discovery_label"] == "通用 RSS/Sitemap 发现"
    assert reject.status_code == 200
    assert reject.json()["rejected"] == 2


def test_candidate_test_crawl_does_not_persist(monkeypatch):
    import erfairy.web as web_module
    from erfairy.models import CrawlResult, SearchDocument

    candidate = {
        "id": 7,
        "url": "https://example.com/feed.xml",
        "source_type": "rss-feed",
        "title": "Feed",
        "status": "pending",
        "reason": "RSS",
        "config": {},
        "config_json": "{}",
        "discovered_at": "2026-05-30T00:00:00+00:00",
        "approved_at": "",
    }
    monkeypatch.setattr(web_module.store, "get_source_candidate", lambda candidate_id: candidate)
    monkeypatch.setattr(
        web_module,
        "_crawl_with_source_strategy",
        lambda crawl_config, source: CrawlResult(
            documents=[
                SearchDocument(
                    url=f"local://candidate-{index}",
                    title=f"Candidate {index}",
                    content="body",
                    content_quality_score=0.82,
                    content_quality_labels=["guide"],
                )
                for index in range(6)
            ],
            errors=[],
        ),
    )

    with TestClient(web_module.app) as client:
        response = client.post("/sources/candidates/7/test-crawl")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_id"] == "candidate-7"
    assert payload["would_save"] == 6
    assert payload["preview_count"] == 6
    assert len(payload["preview_documents"]) == 6
    assert payload["preview_documents"][0]["title"] == "Candidate 0"
    assert payload["preview_documents"][0]["content_quality_score"] == 0.82
    assert payload["preview_documents"][0]["content_quality_labels"] == ["guide"]
    assert payload["entry_url"] == "https://example.com/feed.xml"
    assert payload["persisted"] is False

    with TestClient(web_module.app) as client:
        html_response = client.post("/sources/candidates/7/test-crawl", headers={"accept": "text/html"})

    assert html_response.status_code == 200
    assert "Candidate Preview" in html_response.text
    assert "Candidate 5" in html_response.text
    assert "guide" in html_response.text


def test_miyoushe_candidate_uses_profile_config_for_test_crawl(monkeypatch):
    import erfairy.web as web_module
    from erfairy.models import CrawlResult, SearchDocument

    candidate = {
        "id": 9,
        "url": "https://www.miyoushe.com/ys/",
        "source_type": "miyoushe-feed",
        "title": "原神米游社官方社区",
        "status": "pending",
        "reason": "Known Miyoushe community profile",
        "config": {
            "category": "anime",
            "max_pages": 5,
            "max_depth": 0,
            "delay_seconds": 1.0,
            "source_score": 0.95,
            "allowed_domains": ["www.miyoushe.com"],
        },
        "config_json": "{}",
        "discovered_at": "2026-05-30T00:00:00+00:00",
        "approved_at": "",
    }
    monkeypatch.setattr(web_module.store, "get_source_candidate", lambda candidate_id: candidate)

    def fake_crawl(self, source_id, max_pages, source_score, entry_url=""):
        assert source_id == "candidate-9"
        assert max_pages == 20
        assert source_score == 0.95
        assert entry_url == "https://www.miyoushe.com/ys/"
        return CrawlResult(
            documents=[SearchDocument(url="local://miyoushe-candidate", title="米游社候选", content="body")],
            errors=[],
        )

    monkeypatch.setattr("erfairy.web.MiyousheFeedCrawler.crawl", fake_crawl)

    with TestClient(web_module.app) as client:
        response = client.post("/sources/candidates/9/test-crawl")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_id"] == "candidate-9"
    assert payload["would_save"] == 1
    assert payload["persisted"] is False


def test_candidate_approve_can_trigger_crawl(monkeypatch):
    import erfairy.web as web_module

    candidate = {
        "id": 8,
        "url": "https://example.com/feed.xml",
        "source_type": "rss-feed",
        "title": "Feed",
        "status": "approved",
        "reason": "RSS",
        "config": {},
        "config_json": "{}",
        "discovered_at": "2026-05-30T00:00:00+00:00",
        "approved_at": "2026-05-30T00:00:01+00:00",
    }
    monkeypatch.setattr(web_module.store, "approve_source_candidate", lambda candidate_id: candidate)
    monkeypatch.setattr(web_module.store, "get_source_candidate", lambda candidate_id: candidate)
    monkeypatch.setattr(web_module, "_run_crawl", lambda crawl_config, source: {"source_id": source.source_id, "saved": 1})

    with TestClient(web_module.app) as client:
        response = client.post("/sources/candidates/8/approve", params={"crawl": "true"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["approved"] == 1
    assert payload["source_id"] == "candidate-8"
    assert "effective_config" in payload["candidate"]
    assert payload["crawl_result"]["saved"] == 1


def test_miyoushe_candidate_approve_response_reports_effective_config(monkeypatch):
    import erfairy.web as web_module

    candidate = {
        "id": 34,
        "url": "https://www.miyoushe.com/sr/",
        "source_type": "miyoushe-feed",
        "title": "Miyoushe SR",
        "status": "approved",
        "reason": "Known Miyoushe community profile",
        "config": {
            "category": "anime",
            "max_pages": 5,
            "max_depth": 0,
            "delay_seconds": 1.0,
            "source_score": 0.95,
            "allowed_domains": ["www.miyoushe.com"],
            "miyoushe_profile_id": "miyoushe-sr",
        },
        "config_json": "{}",
        "discovered_at": "2026-05-30T09:01:40+00:00",
        "approved_at": "2026-05-31T04:33:49+00:00",
    }
    monkeypatch.setattr(web_module.store, "approve_source_candidate", lambda candidate_id: candidate)
    monkeypatch.setattr(web_module.store, "get_source_candidate", lambda candidate_id: candidate)

    def fake_run(crawl_config, source):
        return {
            "source_id": source.source_id,
            "saved": 19,
            "max_pages": crawl_config.max_pages,
            "parse_strategy": source.parse_strategy,
        }

    monkeypatch.setattr(web_module, "_run_crawl", fake_run)

    with TestClient(web_module.app) as client:
        response = client.post("/sources/candidates/34/approve", params={"crawl": "true"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate"]["config"]["max_pages"] == 5
    assert payload["candidate"]["effective_config"]["max_pages"] == 20
    assert payload["candidate"]["effective_config"]["quality_profile"] == "miyoushe-community"
    assert payload["crawl_result"]["max_pages"] == 20
    assert payload["crawl_result"]["parse_strategy"] == "miyoushe-feed"


def test_crawl_with_source_strategy_dispatches_biligame_wiki(monkeypatch):
    import erfairy.web as web_module
    from erfairy.models import CrawlResult, SearchDocument
    from erfairy.sources import SourceConfig

    source = SourceConfig(
        name="Biligame 原神 Wiki",
        entry_url="https://wiki.biligame.com/ys",
        allowed_domains=["wiki.biligame.com"],
        category="game",
        max_pages=3,
        source_score=0.86,
        parse_strategy="biligame-wiki",
    )

    def fake_crawl(self, received_source):
        assert received_source is source
        return CrawlResult(documents=[SearchDocument(url="local://biligame", title="Wiki", content="body")], errors=[])

    monkeypatch.setattr("erfairy.web.BiligameWikiCrawler.crawl", fake_crawl)

    result = web_module._crawl_with_source_strategy(source.to_crawl_config(), source)

    assert len(result.documents) == 1
    assert result.documents[0].title == "Wiki"


def test_debug_crawl_scheduler_returns_disabled_state(monkeypatch):
    import erfairy.web as web_module

    monkeypatch.setattr(web_module, "crawl_scheduler", None)
    monkeypatch.delenv("ERFAIRY_CRAWL_INTERVAL_MINUTES", raising=False)

    with TestClient(web_module.app) as client:
        response = client.get("/debug/crawl-scheduler", headers={"accept": "application/json"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert payload["interval_minutes"] == 60
    assert "sources" in payload


def test_debug_crawl_scheduler_respects_interval_env(monkeypatch):
    import erfairy.web as web_module

    monkeypatch.setattr(web_module, "crawl_scheduler", None)
    monkeypatch.setenv("ERFAIRY_CRAWL_INTERVAL_MINUTES", "30")

    with TestClient(web_module.app) as client:
        response = client.get("/debug/crawl-scheduler", headers={"accept": "application/json"})

    assert response.status_code == 200
    assert response.json()["interval_minutes"] == 30


def test_debug_compare_index_returns_backend_results_json():
    with TestClient(app) as client:
        response = client.get(
            "/debug/compare-index",
            params={"q": "原神", "backends": "memory,redis-zset", "limit": 3},
            headers={"accept": "application/json"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "原神"
    assert payload["document_count"] >= 1
    assert [item["status"] for item in payload["backends"]] == ["ok", "ok"]
    assert payload["backends"][0]["backend"] == "memory"
    assert payload["backends"][1]["backend"] == "redis-zset-like"
    assert payload["backends"][0]["results"][0]["title"]


def test_debug_compare_index_html_page_renders():
    with TestClient(app) as client:
        response = client.get("/debug/compare-index", params={"q": "原神", "backends": "memory,redis-zset"})

    assert response.status_code == 200
    assert "Index Compare - ER Fairy Typewriter" in response.text
    assert "索引后端对照" in response.text
    assert "redis-zset-like" in response.text


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


def test_crawl_endpoint_updates_index_incrementally(monkeypatch):
    import erfairy.web as web_module
    from erfairy.models import CrawlResult, SearchDocument

    saved_doc = SearchDocument(id=99, url="local://incremental", title="Incremental Doc", content="fresh body")
    crawl_config = web_module.CrawlConfig(
        seeds=["https://example.com"],
        max_pages=1,
        max_depth=0,
        delay_seconds=0.0,
        allowed_domains={"example.com"},
        category="anime",
    )
    calls = {}

    monkeypatch.setattr(web_module, "_crawl_config_from_request", lambda request: (crawl_config, None))
    monkeypatch.setattr(
        web_module,
        "_crawl_with_source_strategy",
        lambda config, source: CrawlResult(documents=[saved_doc], errors=[]),
    )
    monkeypatch.setattr(web_module.store, "start_crawl_run", lambda category: 123)
    monkeypatch.setattr(web_module.store, "save_crawl_errors", lambda run_id, errors: [])
    monkeypatch.setattr(web_module.store, "finish_crawl_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(web_module.store, "bulk_upsert", lambda documents: list(documents))
    monkeypatch.setattr(web_module.store, "count", lambda: 99)

    def fake_upsert_many(documents):
        calls["documents"] = documents

    monkeypatch.setattr(web_module.index, "upsert_many", fake_upsert_many)

    with TestClient(web_module.app) as client:
        response = client.post("/crawl", json={"seeds": ["https://example.com"], "max_pages": 1})

    assert response.status_code == 200
    payload = response.json()
    assert payload["index_update"] == "incremental"
    assert payload["indexed"] == 1
    assert calls["documents"] == [saved_doc]


def test_delete_document_updates_index_incrementally(monkeypatch):
    import erfairy.web as web_module

    calls = {}
    monkeypatch.setattr(web_module.store, "delete", lambda doc_id: doc_id == 99)
    monkeypatch.setattr(web_module.store, "count", lambda: 12)

    def fake_delete_many(document_ids):
        calls["document_ids"] = document_ids

    monkeypatch.setattr(web_module.index, "delete_many", fake_delete_many)

    with TestClient(web_module.app) as client:
        response = client.delete("/documents/99")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"] == 1
    assert payload["document_id"] == 99
    assert payload["index_update"] == "incremental"
    assert payload["removed_from_index"] == 1
    assert calls["document_ids"] == [99]


def test_delete_document_returns_404_for_missing_document(monkeypatch):
    import erfairy.web as web_module

    monkeypatch.setattr(web_module.store, "delete", lambda doc_id: False)

    with TestClient(web_module.app) as client:
        response = client.delete("/documents/404")

    assert response.status_code == 404
    assert "404" in response.json()["detail"]


def test_crawl_uses_miyoushe_feed_strategy(monkeypatch):
    from erfairy.models import CrawlResult, SearchDocument
    from erfairy.web import CrawlRequest, _crawl_config_from_request, _crawl_with_source_strategy

    request = CrawlRequest(source_id="miyoushe-ys")
    crawl_config, source = _crawl_config_from_request(request)

    def fake_crawl(self, source_id, max_pages, source_score, entry_url=""):
        assert source_id == "miyoushe-ys"
        assert max_pages == 20
        assert source_score == 0.95
        assert entry_url == "https://www.miyoushe.com/ys/"
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
        assert max_pages == 50
        assert source_score == 0.85
        return CrawlResult(
            documents=[SearchDocument(url="local://mal", title="MAL news", content="news body")],
            errors=[],
        )

    monkeypatch.setattr("erfairy.web.ArticleFeedCrawler.crawl", fake_crawl)

    result = _crawl_with_source_strategy(crawl_config, source)

    assert len(result.documents) == 1
    assert result.documents[0].title == "MAL news"
