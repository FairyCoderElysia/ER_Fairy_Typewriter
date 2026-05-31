from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import asyncio

from erfairy.crawl_scheduler import CrawlScheduler


@dataclass(slots=True)
class DummySource:
    source_id: str
    name: str
    scheduler_interval_minutes: int = 0


def test_crawl_scheduler_does_not_start_when_disabled():
    calls = []
    scheduler = CrawlScheduler(
        enabled=False,
        interval_minutes=1,
        source_ids=[],
        crawl_source=lambda source_id: calls.append(source_id) or {},
        source_provider=lambda: [DummySource("mal-news", "MAL")],
    )

    scheduler.start()

    assert scheduler.as_dict()["enabled"] is False
    assert scheduler.as_dict()["running"] is False
    assert calls == []


def test_crawl_scheduler_tracks_per_source_next_run():
    now = datetime(2026, 5, 30, tzinfo=timezone.utc)
    scheduler = CrawlScheduler(
        enabled=True,
        interval_minutes=60,
        source_ids=[],
        crawl_source=lambda source_id: {},
        source_provider=lambda: [
            DummySource("fast", "Fast Source", scheduler_interval_minutes=30),
            DummySource("default", "Default Source"),
        ],
    )

    scheduler.refresh_schedule(now)
    payload = scheduler.as_dict()

    assert payload["interval_minutes"] == 60
    assert payload["next_run_by_source"]["fast"] == (now + timedelta(minutes=30)).isoformat(timespec="seconds")
    assert payload["next_run_by_source"]["default"] == (now + timedelta(minutes=60)).isoformat(timespec="seconds")
    assert payload["next_run_at"] == payload["next_run_by_source"]["fast"]


def test_crawl_scheduler_source_ids_all_selects_every_source():
    now = datetime(2026, 5, 30, tzinfo=timezone.utc)
    scheduler = CrawlScheduler(
        enabled=True,
        interval_minutes=60,
        source_ids=["all"],
        crawl_source=lambda source_id: {},
        source_provider=lambda: [
            DummySource("mal-news", "MAL"),
            DummySource("miyoushe-ys", "Miyoushe"),
        ],
    )

    scheduler.refresh_schedule(now)
    payload = scheduler.as_dict()

    assert {source["source_id"] for source in payload["sources"]} == {"mal-news", "miyoushe-ys"}
    assert set(payload["next_run_by_source"]) == {"mal-news", "miyoushe-ys"}


def test_crawl_scheduler_only_runs_due_sources_and_keeps_going_after_failure():
    now = datetime(2026, 5, 30, tzinfo=timezone.utc)
    calls = []

    def crawl_source(source_id: str) -> dict:
        calls.append(source_id)
        if source_id == "bad":
            raise RuntimeError("boom")
        return {"source_id": source_id, "saved": 2, "errors": 0}

    scheduler = CrawlScheduler(
        enabled=True,
        interval_minutes=60,
        source_ids=[],
        crawl_source=crawl_source,
        source_provider=lambda: [
            DummySource("fast", "Fast Source", scheduler_interval_minutes=30),
            DummySource("bad", "Bad Source", scheduler_interval_minutes=30),
            DummySource("later", "Later Source", scheduler_interval_minutes=90),
        ],
    )
    scheduler.refresh_schedule(now)

    idle = asyncio.run(scheduler.tick(now + timedelta(minutes=29)))
    result = asyncio.run(scheduler.tick(now + timedelta(minutes=30)))

    assert idle["status"] == "idle"
    assert calls == ["fast", "bad"]
    assert result["status"] == "completed"
    assert result["source_count"] == 2
    assert scheduler.last_result_by_source["bad"]["errors"] == 1
    assert "later" not in scheduler.last_run_by_source
