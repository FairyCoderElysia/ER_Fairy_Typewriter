from __future__ import annotations

from pathlib import Path

from erfairy.crawler import CrawlConfig, SmallCrawler
from erfairy.store import SQLiteDocumentStore


def test_crawler_reads_local_html_fixture_and_records_fetch_errors(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "crawl_site" / "index.html"
    result = SmallCrawler().crawl(
        CrawlConfig(
            seeds=[fixture.as_uri()],
            max_pages=10,
            max_depth=1,
            delay_seconds=0.0,
            category="anime",
        )
    )

    assert any(document.character_name == "雷电将军" for document in result.documents)
    assert any(error.stage == "fetch" and error.url.endswith("missing.html") for error in result.errors)

    store = SQLiteDocumentStore(tmp_path / "crawl.sqlite3")
    run_id = store.start_crawl_run(category="anime")
    saved = store.bulk_upsert(result.documents)
    store.save_crawl_errors(run_id, result.errors)
    store.finish_crawl_run(
        run_id,
        source_count=1,
        saved_count=len(saved),
        error_count=len(result.errors),
        category="anime",
        status="completed",
    )

    assert store.count() == 2
    assert len(store.crawl_errors_for_run(run_id)) == 1
