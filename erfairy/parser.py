"""HTML 页面解析模块。

项目简介：
    爬虫抓到的是 HTML 字符串，搜索引擎需要把它清洗成 SearchDocument。

开发目的：
    从网页中提取标题、正文、摘要、标签、图片、发布时间和链接，为入库和继续爬取做准备。

技术栈：
    BeautifulSoup、正则清洗、urllib.parse URL 解析与补全。

学习目标：
    1. 理解网页解析和网页抓取是两个不同步骤。
    2. 理解为什么要删除 script/style 等无搜索价值内容。
    3. 理解 canonical URL、Open Graph meta、相对链接转绝对链接。

知识点与免费文档：
    - BeautifulSoup: https://www.crummy.com/software/BeautifulSoup/bs4/doc/
    - urllib.parse: https://docs.python.org/3/library/urllib.parse.html
    - re 正则表达式: https://docs.python.org/3/library/re.html
    - Open Graph 协议: https://ogp.me/
"""

from __future__ import annotations  # 推迟类型注解解析。

import hashlib  # 用正文生成内容指纹，帮助同内容不同 URL 去重。
import re  # 用于合并多余空白。
from urllib.parse import urljoin, urlparse  # urljoin 补全相对链接，urlparse 拆分域名/路径。

from bs4 import BeautifulSoup  # HTML 解析库，容错能力比手写正则解析 HTML 强很多。

from .models import SearchDocument, utc_now_iso  # 文档模型和当前 UTC 时间函数。


SPACE_RE = re.compile(r"\s+")  # 匹配连续空白：换行、Tab、多个空格等。

AUTO_CATEGORY = "auto"
NEWS_CATEGORY_TERMS = {
    "news",
    "announce",
    "announcement",
    "notice",
    "event",
    "update",
    "新闻",
    "资讯",
    "公告",
    "活动",
    "更新",
    "版本",
}
CHARACTER_CATEGORY_TERMS = {"character", "role", "角色", "人物", "档案", "资料"}
ANIME_CATEGORY_TERMS = {"anime", "game", "wiki", "作品", "游戏", "动漫", "动画"}
MIYOUSHE_PROFILES = {
    "ys": {
        "title": "原神 米游社官方社区",
        "game_title": "原神",
        "aliases": ["Genshin Impact", "提瓦特"],
        "tags": ["原神", "米游社", "米哈游", "官方社区", "游戏资讯"],
        "summary": "原神米游社官方社区，包含官方资讯、玩家互动、攻略和活动内容。",
    },
    "bh3": {
        "title": "崩坏3 米游社官方社区",
        "game_title": "崩坏3",
        "aliases": ["崩坏三", "Honkai Impact 3rd"],
        "tags": ["崩坏3", "崩坏三", "米游社", "米哈游", "官方社区"],
        "summary": "崩坏3米游社官方社区，包含官方资讯、舰长互动、攻略和活动内容。",
    },
    "sr": {
        "title": "崩坏：星穹铁道 米游社官方社区",
        "game_title": "崩坏：星穹铁道",
        "aliases": ["星穹铁道", "崩铁", "Honkai Star Rail"],
        "tags": ["崩坏：星穹铁道", "星穹铁道", "崩铁", "米游社", "米哈游", "官方社区"],
        "summary": "崩坏：星穹铁道米游社官方社区，包含官方资讯、开拓者互动、攻略和活动内容。",
    },
}


def clean_text(text: str) -> str:
    """压缩文本空白并去掉首尾空白。

    入参：
        text: 从 HTML 中抽取的原始文本。

    出参：
        str，适合展示和索引的紧凑文本。
    """

    return SPACE_RE.sub(" ", text).strip()  # 把多空白合并成一个空格，再去首尾空白。


class AnimePageParser:
    """通用二次元资料页解析器。

    使用场景：
        crawler.py 抓到 HTML 后调用 parse()，把网页转为 SearchDocument，并返回页面中的链接。

    设计思路：
        首版不针对某个站点写死规则，而是使用 article/main/meta 等通用结构；准确率不如站点适配器，但更通用。
    """

    def parse(self, html: str, url: str, category: str = "anime") -> tuple[SearchDocument, list[str]]:
        """解析 HTML 页面。

        入参：
            html: requests 抓到的 HTML 字符串。
            url: 当前页面 URL。
            category: 文档分类。

        出参：
            (SearchDocument, links)，links 是页面中发现的可继续爬取链接。
        """

        soup = BeautifulSoup(html, "html.parser")  # 用 Python 内置 html.parser 解析，依赖少，适合 MVP。
        for element in soup(["script", "style", "noscript", "svg"]):  # 这些节点通常不是正文内容。
            element.decompose()  # 从 DOM 树中删除，避免脚本/CSS 污染索引。

        title = self._title(soup, url)  # 提取标题。
        content_node = soup.find("article") or soup.find("main") or soup.body or soup  # 正文优先级：article > main > body > 整页。
        content = clean_text(content_node.get_text(" "))  # 抽取纯文本并清洗空白。
        summary = self._meta(soup, "description") or content[:220]  # 优先用 meta description，否则取正文前 220 字。
        tags = self._tags(soup)  # 提取关键词/标签。
        profile = self._site_profile(url)  # 对 SPA/官方社区类页面做轻量站点适配。
        if profile:
            title = profile["title"]
            summary = profile["summary"]
            tags = self._merge_unique([*profile["tags"], *tags])
            content = clean_text(" ".join([profile["summary"], content]))
        image_url = self._image(soup, url)  # 提取代表图。
        canonical_url = self._canonical(soup, url)  # 提取 canonical URL，减少重复页面。
        aliases = self._list_meta(soup, "erfairy:aliases")  # 站点适配器可用 meta 提供别名。
        entity_type = self._meta(soup, "erfairy:entity_type")  # 实体类型：work/character/news。
        game_title = self._meta(soup, "erfairy:game_title")  # 所属游戏。
        character_name = self._meta(soup, "erfairy:character_name")  # 角色正式名。
        if profile:
            aliases = self._merge_unique([*aliases, *profile["aliases"]])
            entity_type = entity_type or "work"
            game_title = game_title or profile["game_title"]
        source_score = self._source_score(soup)  # 来源质量轻量评分。
        resolved_category = self._category(soup, url, title, summary, tags, entity_type, category)  # 自动或手动分类。

        document = SearchDocument(  # 组装标准文档模型。
            url=canonical_url,  # 使用 canonical 作为文档 URL。
            title=title,  # 标题。
            content=content,  # 正文。
            summary=clean_text(summary),  # 摘要也清洗空白。
            tags=tags,  # 标签。
            aliases=aliases,  # 别名。
            entity_type=entity_type,  # 实体类型。
            game_title=game_title,  # 所属作品/游戏。
            character_name=character_name,  # 角色正式名。
            source_score=source_score,  # 来源质量分。
            content_hash=self._content_hash(content),  # 正文内容指纹。
            category=resolved_category,  # 分类。
            source=urlparse(url).netloc,  # 来源域名。
            published_at=self._published_at(soup),  # 发布时间，可能为空。
            crawled_at=utc_now_iso(),  # 抓取时间。
            image_url=image_url,  # 图片地址。
        )

        links = self._links(soup, url)  # 提取页面链接，用于爬虫继续扩展。
        return document, links  # 返回结构化文档和链接列表。

    def _title(self, soup: BeautifulSoup, url: str) -> str:
        """提取页面标题。

        设计思路：
            og:title 通常更适合分享/展示；没有时退回 <title>；再没有时使用 URL 路径兜底。
        """

        og_title = self._meta(soup, "og:title", attr="property")  # Open Graph 标题。
        if og_title:  # 找到 og:title。
            return clean_text(og_title)  # 返回清洗后的标题。
        if soup.title and soup.title.string:  # 普通 HTML title 存在。
            return clean_text(soup.title.string)  # 返回 title 文本。
        path = urlparse(url).path.strip("/") or url  # 没标题时用 URL 路径。
        return path.rsplit("/", 1)[-1]  # 取路径最后一段作为兜底标题。

    def _meta(self, soup: BeautifulSoup, name: str, attr: str = "name") -> str:
        """读取 meta 标签 content。

        入参：
            soup: BeautifulSoup 文档树。
            name: meta 的 name/property 值。
            attr: 优先匹配的属性名。
        """

        tag = soup.find("meta", attrs={attr: name})  # 按指定属性查找 meta。
        if not tag and attr == "name":  # 如果按 name 找不到，再尝试 property。
            tag = soup.find("meta", attrs={"property": name})  # 兼容 Open Graph。
        return clean_text(tag.get("content", "")) if tag else ""  # 找到返回 content，否则空字符串。

    def _list_meta(self, soup: BeautifulSoup, name: str) -> list[str]:
        """读取逗号分隔的 meta 列表字段。"""

        value = self._meta(soup, name)  # 读取 meta content。
        return [clean_text(item) for item in value.split(",") if clean_text(item)]  # 清洗并去掉空项。

    def _source_score(self, soup: BeautifulSoup) -> float:
        """读取来源质量分。"""

        value = self._meta(soup, "erfairy:source_score")  # 站点适配器可写入 0~10 的来源分。
        try:
            return float(value) if value else 0.0
        except ValueError:
            return 0.0

    def _category(
        self,
        soup: BeautifulSoup,
        url: str,
        title: str,
        summary: str,
        tags: list[str],
        entity_type: str,
        requested_category: str,
    ) -> str:
        """根据页面内容推断分类；手动传入明确分类时优先使用手动值。"""

        explicit = self._meta(soup, "erfairy:category")
        if explicit:
            return explicit
        if requested_category and requested_category != AUTO_CATEGORY:
            return requested_category
        if entity_type == "news":
            return "news"
        if entity_type == "character":
            return "character"
        if entity_type == "work":
            return "anime"

        haystack = " ".join([url, title, summary, " ".join(tags)]).lower()
        if any(term in haystack for term in NEWS_CATEGORY_TERMS):
            return "news"
        if any(term in haystack for term in CHARACTER_CATEGORY_TERMS):
            return "character"
        if any(term in haystack for term in ANIME_CATEGORY_TERMS):
            return "anime"
        return "anime"

    def _content_hash(self, content: str) -> str:
        """生成正文内容 hash，用于发现同内容不同 URL 的重复文档。"""

        normalized = clean_text(content).lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""

    def _tags(self, soup: BeautifulSoup) -> list[str]:
        """提取页面标签/关键词。"""

        keywords = self._meta(soup, "keywords")  # 读取 meta keywords。
        tags = [clean_text(item) for item in keywords.split(",") if clean_text(item)]  # 逗号分隔并过滤空项。
        for tag in soup.select('[rel="tag"], .tag, .tags a'):  # 常见标签选择器。
            value = clean_text(tag.get_text(" "))  # 读取标签文本。
            if value and value not in tags:  # 去重后加入。
                tags.append(value)
        return tags[:20]  # 限制最多 20 个，避免页面导航词污染。

    def _site_profile(self, url: str) -> dict[str, list[str] | str] | None:
        """识别需要轻量站点适配的官方社区入口。"""

        parsed = urlparse(url)
        if parsed.netloc != "www.miyoushe.com":
            return None
        first_path = parsed.path.strip("/").split("/", 1)[0]
        return MIYOUSHE_PROFILES.get(first_path)

    def _merge_unique(self, values: list[str]) -> list[str]:
        """按顺序合并字符串列表并去重。"""

        merged: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = clean_text(value)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(normalized)
        return merged

    def _image(self, soup: BeautifulSoup, url: str) -> str:
        """提取代表图片 URL。"""

        image = self._meta(soup, "og:image", attr="property")  # 优先使用 Open Graph 图片。
        if image:  # 找到 og:image。
            return urljoin(url, image)  # 可能是相对地址，需要补全。
        tag = soup.find("img")  # 退回使用页面第一张图片。
        return urljoin(url, tag.get("src", "")) if tag else ""  # 有图片则补全 URL，否则空字符串。

    def _canonical(self, soup: BeautifulSoup, url: str) -> str:
        """提取 canonical URL。

        设计思路：
            同一内容可能有带参数/不带参数多个 URL，canonical 可以帮助去重。
        """

        tag = soup.find("link", rel="canonical")  # 查找 <link rel="canonical">。
        return urljoin(url, tag.get("href", "")) if tag and tag.get("href") else url  # 找到则补全，否则用原 URL。

    def _published_at(self, soup: BeautifulSoup) -> str:
        """提取发布时间。"""

        for key in ("article:published_time", "pubdate", "date", "datePublished"):  # 常见发布时间字段。
            value = self._meta(soup, key, attr="property") or self._meta(soup, key)  # 同时兼容 property/name。
            if value:  # 找到发布时间。
                return value
        time_tag = soup.find("time")  # 退回查找 <time> 标签。
        return clean_text(time_tag.get("datetime") or time_tag.get_text(" ")) if time_tag else ""  # 优先 datetime 属性。

    def _links(self, soup: BeautifulSoup, url: str) -> list[str]:
        """提取页面中的 HTTP/HTTPS 链接。"""

        links: list[str] = []  # 保持插入顺序的链接列表。
        for tag in soup.find_all("a", href=True):  # 遍历所有带 href 的 a 标签。
            href = urljoin(url, tag["href"]).split("#", 1)[0]  # 相对链接转绝对链接，并去掉锚点。
            parsed = urlparse(href)  # 解析 URL。
            if parsed.scheme in {"http", "https", "file"} and href not in links:  # 只保留网页/fixture 链接并去重。
                links.append(href)
        return links  # 返回链接列表。
