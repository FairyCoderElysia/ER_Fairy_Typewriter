from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from .models import SearchDocument
from .parser import AnimePageParser


@dataclass(slots=True)
class CrawlConfig:
    seeds: list[str]
    max_pages: int = 20
    max_depth: int = 1
    delay_seconds: float = 0.5
    allowed_domains: set[str] = field(default_factory=set)
    user_agent: str = "ERFairyTypewriterBot/0.1 (+local learning project)"
    category: str = "anime"


class SmallCrawler:
    def __init__(self, parser: AnimePageParser | None = None) -> None:
        self.parser = parser or AnimePageParser()
        self._robots: dict[str, RobotFileParser] = {}

    def crawl(self, config: CrawlConfig) -> list[SearchDocument]:
        allowed_domains = config.allowed_domains or {urlparse(seed).netloc for seed in config.seeds}
        queue = deque((seed, 0) for seed in config.seeds)
        visited: set[str] = set()
        documents: list[SearchDocument] = []

        while queue and len(documents) < config.max_pages:
            url, depth = queue.popleft()
            if url in visited:
                continue
            visited.add(url)

            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or parsed.netloc not in allowed_domains:
                continue
            if not self._allowed_by_robots(url, config.user_agent):
                continue

            html = self._fetch(url, config.user_agent)
            if not html:
                continue

            document, links = self.parser.parse(html, url, category=config.category)
            if document.content:
                documents.append(document)

            if depth < config.max_depth:
                for link in links:
                    if link not in visited and urlparse(link).netloc in allowed_domains:
                        queue.append((link, depth + 1))

            time.sleep(config.delay_seconds)

        return documents

    def _fetch(self, url: str, user_agent: str) -> str:
        try:
            response = requests.get(url, headers={"User-Agent": user_agent}, timeout=10)
            content_type = response.headers.get("content-type", "")
            if response.ok and "text/html" in content_type:
                return response.text
        except requests.RequestException:
            return ""
        return ""

    def _allowed_by_robots(self, url: str, user_agent: str) -> bool:
        parsed = urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        if root not in self._robots:
            robot = RobotFileParser()
            robot.set_url(f"{root}/robots.txt")
            try:
                robot.read()
            except Exception:
                return True
            self._robots[root] = robot
        return self._robots[root].can_fetch(user_agent, url)
