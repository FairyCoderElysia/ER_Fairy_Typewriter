from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .models import SearchDocument, utc_now_iso


SPACE_RE = re.compile(r"\s+")


def clean_text(text: str) -> str:
    return SPACE_RE.sub(" ", text).strip()


class AnimePageParser:
    def parse(self, html: str, url: str, category: str = "anime") -> tuple[SearchDocument, list[str]]:
        soup = BeautifulSoup(html, "html.parser")
        for element in soup(["script", "style", "noscript", "svg"]):
            element.decompose()

        title = self._title(soup, url)
        content_node = soup.find("article") or soup.find("main") or soup.body or soup
        content = clean_text(content_node.get_text(" "))
        summary = self._meta(soup, "description") or content[:220]
        tags = self._tags(soup)
        image_url = self._image(soup, url)
        canonical_url = self._canonical(soup, url)

        document = SearchDocument(
            url=canonical_url,
            title=title,
            content=content,
            summary=clean_text(summary),
            tags=tags,
            category=category,
            source=urlparse(url).netloc,
            published_at=self._published_at(soup),
            crawled_at=utc_now_iso(),
            image_url=image_url,
        )

        links = self._links(soup, url)
        return document, links

    def _title(self, soup: BeautifulSoup, url: str) -> str:
        og_title = self._meta(soup, "og:title", attr="property")
        if og_title:
            return clean_text(og_title)
        if soup.title and soup.title.string:
            return clean_text(soup.title.string)
        path = urlparse(url).path.strip("/") or url
        return path.rsplit("/", 1)[-1]

    def _meta(self, soup: BeautifulSoup, name: str, attr: str = "name") -> str:
        tag = soup.find("meta", attrs={attr: name})
        if not tag and attr == "name":
            tag = soup.find("meta", attrs={"property": name})
        return clean_text(tag.get("content", "")) if tag else ""

    def _tags(self, soup: BeautifulSoup) -> list[str]:
        keywords = self._meta(soup, "keywords")
        tags = [clean_text(item) for item in keywords.split(",") if clean_text(item)]
        for tag in soup.select('[rel="tag"], .tag, .tags a'):
            value = clean_text(tag.get_text(" "))
            if value and value not in tags:
                tags.append(value)
        return tags[:20]

    def _image(self, soup: BeautifulSoup, url: str) -> str:
        image = self._meta(soup, "og:image", attr="property")
        if image:
            return urljoin(url, image)
        tag = soup.find("img")
        return urljoin(url, tag.get("src", "")) if tag else ""

    def _canonical(self, soup: BeautifulSoup, url: str) -> str:
        tag = soup.find("link", rel="canonical")
        return urljoin(url, tag.get("href", "")) if tag and tag.get("href") else url

    def _published_at(self, soup: BeautifulSoup) -> str:
        for key in ("article:published_time", "pubdate", "date", "datePublished"):
            value = self._meta(soup, key, attr="property") or self._meta(soup, key)
            if value:
                return value
        time_tag = soup.find("time")
        return clean_text(time_tag.get("datetime") or time_tag.get_text(" ")) if time_tag else ""

    def _links(self, soup: BeautifulSoup, url: str) -> list[str]:
        links: list[str] = []
        for tag in soup.find_all("a", href=True):
            href = urljoin(url, tag["href"]).split("#", 1)[0]
            parsed = urlparse(href)
            if parsed.scheme in {"http", "https"} and href not in links:
                links.append(href)
        return links
