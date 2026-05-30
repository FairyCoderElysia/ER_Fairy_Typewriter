from __future__ import annotations

from erfairy.generic_feeds import GenericFeedCrawler
from erfairy.site_feeds import ArticleFeedCrawler, ARTICLE_FEEDS
from erfairy.sources import SourceConfig


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


def test_generic_rss_feed_extracts_article_urls():
    crawler = GenericFeedCrawler()
    source = SourceConfig(
        name="RSS",
        entry_url="https://example.com/feed.xml",
        allowed_domains=["example.com"],
        parse_strategy="rss-feed",
    )
    xml = """
    <rss><channel>
      <item><link>https://example.com/news/1</link></item>
      <item><link>https://example.com/news/2</link></item>
    </channel></rss>
    """

    urls = crawler.article_urls(source, xml, limit=2)

    assert urls == ["https://example.com/news/1", "https://example.com/news/2"]


def test_generic_sitemap_feed_respects_max_pages():
    crawler = GenericFeedCrawler()
    source = SourceConfig(
        name="Sitemap",
        entry_url="https://example.com/sitemap.xml",
        allowed_domains=["example.com"],
        parse_strategy="sitemap-feed",
    )
    xml = """
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/a</loc></url>
      <url><loc>https://example.com/b</loc></url>
    </urlset>
    """

    urls = crawler.article_urls(source, xml, limit=1)

    assert urls == ["https://example.com/a"]


def test_generic_html_list_feed_scores_article_links():
    crawler = GenericFeedCrawler()
    source = SourceConfig(
        name="List",
        entry_url="https://example.com/",
        allowed_domains=["example.com"],
        parse_strategy="html-list-feed",
    )
    html = """
    <html><body>
      <a href="/privacy">Privacy</a>
      <a href="/news/2026/first">First article title</a>
      <a href="/article/2026/second">Second article title</a>
    </body></html>
    """

    urls = crawler.article_urls(source, html, limit=2)

    assert urls == ["https://example.com/news/2026/first", "https://example.com/article/2026/second"]
