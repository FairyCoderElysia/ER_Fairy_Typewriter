"""Lightweight background scheduler for controlled crawl runs."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Protocol


class CrawlSource(Protocol):
    source_id: str
    name: str
    scheduler_interval_minutes: int


class CrawlScheduler:
    """Run a crawl callback periodically when explicitly enabled."""

    def __init__(
        self,
        enabled: bool,
        interval_minutes: int,
        source_ids: list[str],
        crawl_source: Callable[[str], dict],
        source_provider: Callable[[], Iterable[CrawlSource]],
    ) -> None:
        self.enabled = enabled
        self.interval_minutes = max(1, interval_minutes)
        self.source_ids = source_ids
        self._crawl_source = crawl_source
        self._source_provider = source_provider
        self._task: asyncio.Task | None = None
        self.last_run_at = ""
        self.next_run_at = ""
        self.last_result: dict | None = None
        self.last_run_by_source: dict[str, str] = {}
        self.next_run_by_source: dict[str, str] = {}
        self.last_result_by_source: dict[str, dict] = {}
        self.running = False

    def start(self) -> None:
        if not self.enabled or self._task:
            return
        self.refresh_schedule()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "running": self.running,
            "interval_minutes": self.interval_minutes,
            "source_ids": self.source_ids,
            "last_run_at": self.last_run_at,
            "next_run_at": self.next_run_at,
            "last_result": self.last_result,
            "last_run_by_source": self.last_run_by_source,
            "next_run_by_source": self.next_run_by_source,
            "last_result_by_source": self.last_result_by_source,
            "sources": self.source_status(),
        }

    def refresh_schedule(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        for source in self._selected_sources():
            source_id = self._source_id(source)
            if source_id not in self.next_run_by_source:
                interval = self._source_interval(source)
                self.next_run_by_source[source_id] = self._iso(now + timedelta(minutes=interval))
        self._refresh_global_next_run()

    def source_status(self) -> list[dict]:
        self.refresh_schedule()
        statuses = []
        for source in self._selected_sources():
            source_id = self._source_id(source)
            statuses.append(
                {
                    "source_id": source_id,
                    "source_name": source.name,
                    "interval_minutes": self._source_interval(source),
                    "last_run_at": self.last_run_by_source.get(source_id, ""),
                    "next_run_at": self.next_run_by_source.get(source_id, ""),
                    "last_result": self.last_result_by_source.get(source_id),
                }
            )
        return statuses

    async def tick(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        self.refresh_schedule(now)
        due_sources = [
            source
            for source in self._selected_sources()
            if self._is_due(self._source_id(source), now)
        ]
        if not due_sources:
            return {"status": "idle", "results": []}

        self.running = True
        self.last_run_at = self._iso(now)
        results = []
        try:
            for source in due_sources:
                source_id = self._source_id(source)
                try:
                    result = await asyncio.to_thread(self._crawl_source, source_id)
                except Exception as exc:
                    result = {
                        "source_id": source_id,
                        "source_name": source.name,
                        "saved": 0,
                        "errors": 1,
                        "error": str(exc),
                    }
                self.last_run_by_source[source_id] = self._iso(now)
                self.next_run_by_source[source_id] = self._iso(
                    now + timedelta(minutes=self._source_interval(source))
                )
                self.last_result_by_source[source_id] = result
                results.append(result)
            self.last_result = {
                "status": "completed",
                "source_count": len(due_sources),
                "results": results,
            }
            return self.last_result
        finally:
            self.running = False
            self._refresh_global_next_run()

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            await self.tick()

    def _selected_sources(self) -> list[CrawlSource]:
        sources = list(self._source_provider())
        if not self.source_ids:
            return sources
        wanted = set(self.source_ids)
        return [source for source in sources if self._source_id(source) in wanted or source.name in wanted]

    def _source_id(self, source: CrawlSource) -> str:
        return source.source_id or source.name

    def _source_interval(self, source: CrawlSource) -> int:
        return max(1, source.scheduler_interval_minutes or self.interval_minutes)

    def _is_due(self, source_id: str, now: datetime) -> bool:
        next_run_at = self.next_run_by_source.get(source_id)
        if not next_run_at:
            return False
        try:
            return now >= datetime.fromisoformat(next_run_at)
        except ValueError:
            return True

    def _refresh_global_next_run(self) -> None:
        values = [value for value in self.next_run_by_source.values() if value]
        self.next_run_at = min(values) if values else ""

    def _iso(self, value: datetime) -> str:
        return value.isoformat(timespec="seconds")
