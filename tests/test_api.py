from fastapi.testclient import TestClient

from erfairy.web import app


def test_search_api_returns_json_results():
    with TestClient(app) as client:
        response = client.get("/search", params={"q": "原神", "category": "anime"}, headers={"accept": "application/json"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "原神"
    assert payload["total"] >= 1
    assert payload["results"][0]["title"]
    assert "snippet" in payload["results"][0]


def test_search_html_results_page_renders():
    with TestClient(app) as client:
        response = client.get("/search", params={"q": "原神", "category": "anime"})

    assert response.status_code == 200
    assert "ER Fairy Typewriter" in response.text
    assert "找到" in response.text
    assert "原神" in response.text


def test_debug_search_explains_scores():
    with TestClient(app) as client:
        response = client.get("/debug/search", params={"q": "原神", "category": "anime"})

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
