from __future__ import annotations

from erfairy.site_feeds import ArticleFeedCrawler, ARTICLE_FEEDS


def test_article_feed_profiles_cover_public_news_sources():
    assert set(ARTICLE_FEEDS) == {"mal-news", "ann-home", "fgo-news"}


def test_article_feed_crawler_builds_documents_from_list_and_details(monkeypatch):
    list_html = """
    <html><body>
      <a href="https://myanimelist.net/news/12345678">First MAL news</a>
      <a href="/news/87654321">Second MAL news</a>
    </body></html>
    """
    detail_html = """
    <html>
      <head>
        <title>First MAL news</title>
        <meta name="description" content="News summary">
      </head>
      <body><article><p>Anime news detail body.</p></article></body>
    </html>
    """

    def fake_fetch(self, url):
        if url == "https://myanimelist.net/news":
            return list_html
        return detail_html

    monkeypatch.setattr("erfairy.site_feeds.ArticleFeedCrawler._fetch", fake_fetch)

    result = ArticleFeedCrawler().crawl("mal-news", max_pages=2, source_score=0.85)

    assert not result.errors
    assert len(result.documents) == 2
    assert result.documents[0].category == "news"
    assert result.documents[0].entity_type == "news"
    assert result.documents[0].source == "myanimelist.net"
    assert result.documents[0].source_score == 0.85


def test_fgo_feed_normalizes_iframe_article_urls():
    crawler = ArticleFeedCrawler()
    html = """
    <html><body>
      <a href="/iframe/2026/0526_advanced_quest_18th/">FGO notice</a>
    </body></html>
    """

    urls = crawler._article_urls(ARTICLE_FEEDS["fgo-news"], html, limit=1)

    assert urls == ["https://webview.fate-go.us/iframe/2026/0526_advanced_quest_18th/"]
