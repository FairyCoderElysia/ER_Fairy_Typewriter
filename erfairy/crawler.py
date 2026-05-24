"""小型网页爬虫模块。

项目简介：
    搜索引擎需要数据来源；爬虫负责从种子 URL 出发，抓取网页并交给 parser 解析成文档。

开发目的：
    实现一个轻量、可控、对学习友好的爬虫：限制域名、深度、页数和请求频率，并检查 robots.txt。

技术栈：
    requests、deque 队列、dataclass 配置、urllib.parse、urllib.robotparser。

学习目标：
    1. 理解 BFS 队列爬取。
    2. 理解 max_depth/max_pages/delay_seconds 这些安全边界。
    3. 理解 robots.txt 的基本作用。

知识点与免费文档：
    - requests: https://requests.readthedocs.io/en/latest/
    - deque: https://docs.python.org/3/library/collections.html#collections.deque
    - urllib.robotparser: https://docs.python.org/3/library/urllib.robotparser.html
    - urllib.parse: https://docs.python.org/3/library/urllib.parse.html
"""

from __future__ import annotations  # 推迟类型注解解析。

import time  # 用于请求间隔 sleep，避免对目标站点造成压力。
from collections import deque  # 双端队列，适合 BFS 爬取。
from dataclasses import dataclass, field  # dataclass 表达爬虫配置。
from urllib.parse import urlparse  # 解析 URL 的域名、协议。
from urllib.robotparser import RobotFileParser  # 读取 robots.txt。

import requests  # HTTP 请求库。

from .models import SearchDocument  # 爬虫最终产出文档。
from .parser import AnimePageParser  # HTML 解析器。


@dataclass(slots=True)  # 配置对象用 dataclass，参数集中且易读。
class CrawlConfig:
    """爬虫配置。

    字段：
        seeds: 起始 URL 列表。
        max_pages: 最多保存多少篇文档。
        max_depth: 从种子链接向外扩展几层。
        delay_seconds: 每次请求后的等待时间。
        allowed_domains: 允许抓取的域名集合。
        user_agent: 请求头中的爬虫标识。
        category: 写入文档时使用的分类。
    """

    seeds: list[str]  # 起始 URL。
    max_pages: int = 20  # 页数上限，防止无限抓取。
    max_depth: int = 1  # 深度上限，0 表示只抓种子页。
    delay_seconds: float = 0.5  # 请求间隔，做一个友好的小爬虫。
    allowed_domains: set[str] = field(default_factory=set)  # 域名白名单；空时自动使用种子域名。
    user_agent: str = "ERFairyTypewriterBot/0.1 (+local learning project)"  # 清楚标识爬虫身份。
    category: str = "anime"  # 默认二次元分类。


class SmallCrawler:
    """轻量 BFS 爬虫。

    入参：
        parser: 可注入自定义解析器，默认使用 AnimePageParser。

    设计思路：
        把“抓网页”和“解析网页”拆开，后续不同网站可以替换 parser，而不用改爬虫调度逻辑。
    """

    def __init__(self, parser: AnimePageParser | None = None) -> None:
        self.parser = parser or AnimePageParser()  # 没传解析器就使用默认解析器。
        self._robots: dict[str, RobotFileParser] = {}  # 缓存每个站点的 robots.txt，避免重复请求。

    def crawl(self, config: CrawlConfig) -> list[SearchDocument]:
        """根据配置开始爬取。

        入参：
            config: CrawlConfig。

        出参：
            list[SearchDocument]，抓取并解析成功的文档。
        """

        allowed_domains = config.allowed_domains or {urlparse(seed).netloc for seed in config.seeds}  # 默认只抓种子域名。
        queue = deque((seed, 0) for seed in config.seeds)  # 队列元素是 (url, depth)。
        visited: set[str] = set()  # 已访问 URL，避免循环抓取。
        documents: list[SearchDocument] = []  # 成功解析出的文档。

        while queue and len(documents) < config.max_pages:  # 队列非空且未达到页数上限时继续。
            url, depth = queue.popleft()  # BFS：从队列左侧取出最早加入的链接。
            if url in visited:  # 已访问过则跳过。
                continue
            visited.add(url)  # 标记当前 URL 已访问。

            parsed = urlparse(url)  # 解析协议和域名。
            if parsed.scheme not in {"http", "https"} or parsed.netloc not in allowed_domains:  # 非网页链接或跨域链接跳过。
                continue
            if not self._allowed_by_robots(url, config.user_agent):  # robots.txt 不允许时跳过。
                continue

            html = self._fetch(url, config.user_agent)  # 下载 HTML。
            if not html:  # 下载失败或不是 HTML。
                continue

            document, links = self.parser.parse(html, url, category=config.category)  # 解析文档和页面链接。
            if document.content:  # 有正文才保存，避免空页面污染索引。
                documents.append(document)

            if depth < config.max_depth:  # 未达到深度上限时才扩展链接。
                for link in links:  # 遍历解析出的链接。
                    if link not in visited and urlparse(link).netloc in allowed_domains:  # 未访问且域名允许。
                        queue.append((link, depth + 1))  # 加入下一层队列。

            time.sleep(config.delay_seconds)  # 礼貌等待，避免请求过快。

        return documents  # 返回抓到的文档。

    def _fetch(self, url: str, user_agent: str) -> str:
        """下载一个 HTML 页面。

        入参：
            url: 要抓取的网页。
            user_agent: 请求头中的爬虫标识。

        出参：
            str，HTML 文本；失败时返回空字符串。
        """

        try:  # 网络请求容易失败，必须用异常处理保护爬虫主流程。
            response = requests.get(url, headers={"User-Agent": user_agent}, timeout=10)  # 设置 UA 和超时。
            content_type = response.headers.get("content-type", "")  # 查看响应类型。
            if response.ok and "text/html" in content_type:  # 只接受成功的 HTML 页面。
                return response.text  # requests 会根据响应头尝试解码文本。
        except requests.RequestException:  # DNS、超时、连接失败等都会进入这里。
            return ""  # MVP 中失败即跳过；真实系统可记录日志。
        return ""  # 非 HTML 或非 2xx 响应返回空。

    def _allowed_by_robots(self, url: str, user_agent: str) -> bool:
        """检查 robots.txt 是否允许抓取该 URL。

        入参：
            url: 待抓取 URL。
            user_agent: 当前爬虫 UA。

        出参：
            bool，True 表示允许抓取。

        设计思路：
            学习项目也应该尊重 robots；如果 robots.txt 读取失败，首版选择放行，但生产系统应更保守。
        """

        parsed = urlparse(url)  # 拆分 URL。
        root = f"{parsed.scheme}://{parsed.netloc}"  # 站点根地址。
        if root not in self._robots:  # 没缓存过该站点 robots。
            robot = RobotFileParser()  # 创建解析器。
            robot.set_url(f"{root}/robots.txt")  # 设置 robots.txt 地址。
            try:  # robots.txt 也可能请求失败。
                robot.read()  # 读取并解析 robots.txt。
            except Exception:  # RobotFileParser 可能抛出网络/解析异常。
                return True  # 首版宽松处理，避免单个站点 robots 失败导致全部不可用。
            self._robots[root] = robot  # 缓存解析结果。
        return self._robots[root].can_fetch(user_agent, url)  # 按 UA 和 URL 判断是否可抓取。
