"""FastAPI Web 应用入口。

项目简介：
    这个文件把“存储、索引、搜索、爬虫、页面模板”组装成一个可运行的搜索引擎服务。

开发目的：
    提供首页、搜索页、JSON 搜索接口、爬虫触发接口和重建索引接口。

技术栈：
    FastAPI、Pydantic、Jinja2Templates、StaticFiles、SQLite、内存 TF-IDF 索引。

学习目标：
    1. 理解 Web 路由如何调用搜索服务。
    2. 理解应用启动时为什么要加载数据并重建索引。
    3. 理解同一个 /search 如何根据 Accept 返回 HTML 或 JSON。

知识点与免费文档：
    - FastAPI: https://fastapi.tiangolo.com/
    - Pydantic Field: https://docs.pydantic.dev/latest/concepts/fields/
    - Jinja2 模板: https://jinja.palletsprojects.com/en/stable/templates/
    - Starlette StaticFiles: https://www.starlette.io/staticfiles/
"""

from __future__ import annotations  # 推迟类型注解解析。

import asyncio
import os  # 读取环境变量 ERFAIRY_DB。
import threading
import time
from contextlib import asynccontextmanager  # FastAPI 推荐用 lifespan 管理应用启动/关闭逻辑。
from pathlib import Path  # 处理项目路径。
from urllib.parse import urlencode  # 安全拼接查询字符串。
from urllib.parse import urlparse  # 从种子 URL 中提取域名。

from fastapi import FastAPI, Form, HTTPException, Query, Request  # FastAPI 核心对象和请求参数工具。
from fastapi.responses import HTMLResponse, RedirectResponse  # HTML 响应和表单跳转响应。
from fastapi.staticfiles import StaticFiles  # 挂载 CSS 等静态文件。
from fastapi.templating import Jinja2Templates  # 渲染 HTML 模板。
from pydantic import BaseModel, Field  # 定义请求体模型和字段校验规则。

from .api_feeds import ApiFeedCrawler
from .cn_site_feeds import BiligameWikiCrawler, GameKeeFeedCrawler, TapTapFeedCrawler
from .crawler import CrawlConfig, SmallCrawler  # 爬虫配置和爬虫实现。
from .crawl_scheduler import CrawlScheduler
from .domain_terms import enrich_documents, load_domain_terms  # 加载别名词典并补全文档字段。
from .generic_feeds import GenericFeedCrawler
from .indexer import SearchIndex, create_search_index  # 搜索索引工厂和接口。
from .miyoushe import MiyousheFeedCrawler  # 米游社帖子流适配器。
from .sample_data import SAMPLE_DOCUMENTS  # 内置样例资料。
from .search import SearchService  # 搜索服务层。
from .site_feeds import ArticleFeedCrawler  # 公开站点文章流适配器。
from .source_discovery import SourceDiscoverer
from .sources import SourceConfig, find_source_config, load_source_configs  # 读取 sources.example.json 中的受控数据源。
from .store import SQLiteDocumentStore  # SQLite 文档存储。
from .wiki_profiles import wiki_game_config
from .models import utc_now_iso


BASE_DIR = Path(__file__).resolve().parent  # erfairy 包目录。
PROJECT_DIR = BASE_DIR.parent  # 项目根目录。
DATA_PATH = Path(os.getenv("ERFAIRY_DB", PROJECT_DIR / "data" / "erfairy.sqlite3"))  # 允许用环境变量覆盖数据库路径。

store = SQLiteDocumentStore(DATA_PATH)  # 文档持久化层。
INDEX_BACKEND = os.getenv("ERFAIRY_INDEX_BACKEND", "memory")  # 可选：memory、redis-zset 或 redis。
index: SearchIndex = create_search_index(INDEX_BACKEND)  # 搜索索引层，便于切换实现做对照。
search_service = SearchService(index)  # 搜索服务层，封装分页和高亮。
domain_terms = load_domain_terms()  # 加载可维护的别名词典，供样例和抓取文档统一补全。
DEV_MUTATION_ENABLED = os.getenv("ERFAIRY_DEV_MUTATIONS", "1").lower() not in {"0", "false", "no"}  # 本地开发接口默认开启。
CRAWL_LOCK = threading.Lock()
INDEX_LOCK = threading.Lock()
CrawlBatchResult = dict
crawl_scheduler: CrawlScheduler | None = None
startup_index_task: asyncio.Task | None = None
index_build_status = {
    "ready": False,
    "running": False,
    "mode": "background",
    "last_started_at": "",
    "last_finished_at": "",
    "last_error": "",
    "document_count": 0,
}
CATEGORY_OPTIONS = [
    {"value": "all", "label": "全部"},
    {"value": "anime", "label": "动漫/游戏"},
    {"value": "news", "label": "资讯"},
    {"value": "character", "label": "角色"},
]
DATE_RANGE_OPTIONS = [
    {"value": "all", "label": "全部时间"},
    {"value": "1d", "label": "最近 1 天"},
    {"value": "7d", "label": "最近 7 天"},
    {"value": "30d", "label": "最近 30 天"},
    {"value": "365d", "label": "最近 1 年"},
]
DEBUG_LINKS = [
    {
        "title": "搜索解释",
        "description": "查看一次查询的 token、候选文档、字段贡献、TF-IDF、boost 和最终分数。",
        "href": "/debug/search?q=原神&category=all",
        "endpoint": "/debug/search",
    },
    {
        "title": "索引状态",
        "description": "查看当前索引后端、文档数、term 数、posting 数和最近重建时间。",
        "href": "/debug/index",
        "endpoint": "/debug/index",
    },
    {
        "title": "Redis 结构",
        "description": "在真实 Redis 后端下查看 keys、terms、meta 和指定 term 的 ZSet postings。",
        "href": "/debug/redis",
        "endpoint": "/debug/redis",
    },
    {
        "title": "抓取状态",
        "description": "查看最近 crawl runs、保存数量、错误数量和失败 URL 明细。",
        "href": "/debug/crawls",
        "endpoint": "/debug/crawls",
    },
    {
        "title": "抓取调度",
        "description": "查看自动抓取调度是否启用、上次运行、下次运行和最近批量结果。",
        "href": "/debug/crawl-scheduler",
        "endpoint": "/debug/crawl-scheduler",
    },
    {
        "title": "数据源候选",
        "description": "查看已配置数据源、审核通过的数据源候选和待审核候选。",
        "href": "/debug/sources",
        "endpoint": "/debug/sources",
    },
    {
        "title": "后端对照",
        "description": "并排比较 memory、redis-zset、redis、meilisearch 对同一查询的 Top 结果。",
        "href": "/debug/compare-index?q=原神&backends=memory,redis-zset,meilisearch",
        "endpoint": "/debug/compare-index",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。

    设计思路：
        FastAPI 新版本推荐用 lifespan 代替 @app.on_event("startup")。
        启动时写入样例数据并重建索引，关闭时无需额外清理。
    """

    global crawl_scheduler, startup_index_task
    store.bulk_upsert(enrich_documents(SAMPLE_DOCUMENTS, domain_terms))  # 写入/更新内置样例文档。
    index_build_status.update(
        {
            "ready": False,
            "running": True,
            "mode": "startup",
            "last_started_at": utc_now_iso(),
            "last_error": "",
            "document_count": store.count(),
        }
    )
    startup_index_task = asyncio.create_task(_rebuild_index_in_background("startup"))
    crawl_scheduler = _create_crawl_scheduler()
    crawl_scheduler.start()
    try:
        yield  # 服务运行期间控制权交给 FastAPI。
    finally:
        if startup_index_task and not startup_index_task.done():
            startup_index_task.cancel()
        if crawl_scheduler:
            await crawl_scheduler.stop()


async def _rebuild_index_in_background(reason: str) -> None:
    try:
        await asyncio.to_thread(_rebuild_index_sync, reason)
    except Exception:
        # _rebuild_index_sync already records the error for /debug/index.
        return


def _rebuild_index_sync(reason: str = "manual") -> dict:
    global index, search_service
    started_at = utc_now_iso()
    index_build_status.update(
        {
            "ready": False,
            "running": True,
            "mode": reason,
            "last_started_at": started_at,
            "last_error": "",
            "document_count": store.count(),
        }
    )
    try:
        documents = store.all()
        next_index = create_search_index(INDEX_BACKEND)
        next_index.rebuild(documents)
        with INDEX_LOCK:
            index = next_index
            search_service = SearchService(index)
        finished_at = utc_now_iso()
        index_build_status.update(
            {
                "ready": True,
                "running": False,
                "mode": reason,
                "last_finished_at": finished_at,
                "last_error": "",
                "document_count": len(documents),
            }
        )
        return {"indexed": len(documents), "status": "ready", "started_at": started_at, "finished_at": finished_at}
    except Exception as exc:
        index_build_status.update(
            {
                "ready": False,
                "running": False,
                "mode": reason,
                "last_finished_at": utc_now_iso(),
                "last_error": str(exc),
            }
        )
        raise


def _index_status_payload() -> dict:
    payload = dict(index_build_status)
    payload["sqlite_document_count"] = store.count()
    return payload


def _wait_for_index_ready(timeout_seconds: float | None = None) -> None:
    if index_build_status.get("ready") or not index_build_status.get("running"):
        return
    if timeout_seconds is None:
        try:
            timeout_seconds = float(os.getenv("ERFAIRY_INDEX_READY_WAIT_SECONDS", "30"))
        except ValueError:
            timeout_seconds = 30.0
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    while index_build_status.get("running") and not index_build_status.get("ready"):
        if time.monotonic() >= deadline:
            return
        time.sleep(0.05)


app = FastAPI(title="ER Fairy Typewriter", version="0.1.0", lifespan=lifespan)  # 创建 FastAPI 应用对象。
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")  # 让 /static/style.css 可被浏览器访问。
templates = Jinja2Templates(directory=BASE_DIR / "templates")  # 指定 HTML 模板目录。


class CrawlRequest(BaseModel):
    """POST /crawl 的请求体模型。

    入参字段：
        seeds: 种子 URL 列表，至少 1 个。
        max_pages: 最多抓取文档数。
        max_depth: 链接扩展深度。
        delay_seconds: 请求间隔。
        category: 写入文档分类。
        source_id: 可选，填写 sources.example.json 中的 ASCII id 时按该数据源配置抓取。
        source_name: 可选，填写 sources.example.json 中的名称时按该数据源配置抓取。

    设计思路：
        用 Pydantic 做边界校验，比在函数里手写 if 更集中、更清楚。
    """

    seeds: list[str] = Field(default_factory=list)  # 提供 source_name 时可以不填；否则至少提供一个种子 URL。
    max_pages: int = Field(default=10, ge=1, le=100)  # 限制 1~100 页，避免误抓太多。
    max_depth: int = Field(default=1, ge=0, le=3)  # 限制深度 0~3，防止爬虫扩散。
    delay_seconds: float = Field(default=0.5, ge=0.0, le=10.0)  # 限制请求间隔范围。
    category: str = "auto"  # 默认自动分类；手动传 anime/news/character 时优先使用手动值。
    source_id: str = ""  # 推荐：使用 ASCII 数据源 ID，避免 PowerShell 中文编码问题。
    source_name: str = ""  # 可选：使用 sources.example.json 中的配置。


class SourceDiscoverRequest(BaseModel):
    url: str = Field(min_length=1)


class CrawlAllRequest(BaseModel):
    source_ids: list[str] = Field(default_factory=list)


class BulkCandidateRequest(BaseModel):
    candidate_ids: list[int] = Field(default_factory=list)


@app.get("/", response_class=HTMLResponse)  # GET 首页，返回 HTML。
def home(request: Request) -> HTMLResponse:
    """渲染搜索首页。"""

    return templates.TemplateResponse(request, "home.html", {"category_options": CATEGORY_OPTIONS})  # 返回 Jinja2 模板响应。


@app.get("/search")  # GET 搜索；既支持浏览器 HTML，也支持 API JSON。
def search(
    request: Request,  # Request 用来读取 Accept 请求头。
    q: str = Query(default=""),  # 查询词，默认空字符串。
    page: int = Query(default=1, ge=1),  # 页码，FastAPI 自动校验 >=1。
    category: str = Query(default="all"),  # 分类过滤；all 表示搜索全部分类。
    source: str = Query(default="all"),  # 来源过滤；all 表示不限来源。
    date_range: str = Query(default="all"),  # 时间过滤；all 表示不限时间。
):
    """搜索接口。

    返回：
        如果 Accept 包含 application/json，返回 JSON；
        否则渲染 results.html 页面。
    """

    _wait_for_index_ready()
    category_filter = _category_filter(category)  # all/空值表示不限制分类。
    source_filter = None if source in {"", "all"} else source
    payload = search_service.search(
        q,
        page=page,
        per_page=10,
        category=category_filter,
        source=source_filter,
        date_range=date_range,
    )  # 调用搜索服务。
    payload["category"] = category or "all"  # API 也返回当前分类，方便前端或脚本确认过滤范围。
    payload["source"] = source or "all"
    payload["date_range"] = date_range or "all"
    payload["index_build"] = _index_status_payload()
    payload["category_options"] = CATEGORY_OPTIONS
    payload["source_options"] = _source_options()
    payload["date_range_options"] = DATE_RANGE_OPTIONS
    wants_json = "application/json" in request.headers.get("accept", "")  # 判断调用方是否希望 JSON。
    if wants_json:  # API 调用场景。
        return payload  # FastAPI 会自动序列化 dict 为 JSON。
    return templates.TemplateResponse(request, "results.html", payload)  # 浏览器场景渲染 HTML。


@app.get("/debug", response_class=HTMLResponse)
def debug_home(request: Request) -> HTMLResponse:
    """渲染本地调试工具总览页。"""

    stats = search_service.stats()
    return templates.TemplateResponse(
        request,
        "debug.html",
        {
            "links": DEBUG_LINKS,
            "backend": stats["backend"],
            "document_count": stats["document_count"],
            "term_count": stats["term_count"],
            "posting_count": stats["posting_count"],
        },
    )


@app.get("/debug/search")  # GET 调试搜索；浏览器返回 HTML，API 返回 JSON。
def debug_search(
    request: Request,
    q: str = Query(default=""),  # 查询词，默认空字符串。
    category: str = Query(default="all"),  # 分类过滤；all 表示搜索全部分类。
):
    """返回一次搜索的分词、候选召回和分数拆解。

    使用场景：
        学习阶段观察 TF-IDF、字段权重和 boost 如何共同影响排序。
    """

    _wait_for_index_ready()
    payload = search_service.explain(q, category=_category_filter(category))  # 返回结构化解释 JSON。
    payload["category"] = category or "all"
    payload["index_build"] = _index_status_payload()
    payload["category_options"] = CATEGORY_OPTIONS
    wants_json = "application/json" in request.headers.get("accept", "")
    if wants_json:
        return payload
    return templates.TemplateResponse(request, "debug_search.html", payload)


@app.get("/debug/index")  # GET 索引状态；阶段一收尾提供最小可观察性。
def debug_index():
    """返回当前内存索引的基本状态。"""

    payload = search_service.stats()  # 返回文档数、token 数、倒排项数量和最近重建时间。
    payload["index_build"] = _index_status_payload()
    return payload


@app.post("/search")  # 表单提交使用 POST，再重定向到 GET 搜索页。
def search_form(q: str = Form(default=""), category: str = Form(default="all")):
    """处理搜索表单提交。

    设计思路：
        搜索结果页使用 GET URL 更方便分享和刷新，因此 POST 表单只负责重定向。
    """

    return RedirectResponse(url=f"/search?{urlencode({'q': q, 'category': category})}", status_code=303)  # 303 表示用 GET 访问新地址。


def _category_filter(category: str | None) -> str | None:
    """把用户可见分类转换成索引层过滤值。"""

    if not category or category == "all":
        return None
    return category


def _source_options() -> list[dict[str, str]]:
    """返回搜索页来源筛选选项。"""

    sources = sorted({document.source for document in store.all() if document.source})
    return [{"value": "all", "label": "全部来源"}] + [
        {"value": source, "label": source}
        for source in sources
    ]


@app.post("/crawl")  # 开发接口：触发爬虫。
def crawl(request: CrawlRequest):
    """抓取种子 URL 并重建索引。

    使用场景：
        开发阶段手动 POST 一批种子 URL，扩充搜索资料。
    """

    if not DEV_MUTATION_ENABLED:  # 生产环境可通过环境变量关闭抓取和重建接口。
        return {"detail": "开发写入接口已关闭，请设置 ERFAIRY_DEV_MUTATIONS=1 后再使用"}  # 明确提示。

    crawl_config, source = _crawl_config_from_request(request)  # 合并请求体和可选数据源配置。
    return _run_crawl(crawl_config, source)


@app.post("/crawl/all")
def crawl_all(request: CrawlAllRequest | None = None):
    """Run all configured and approved sources with a shared crawl lock."""

    if not DEV_MUTATION_ENABLED:
        return {"detail": "开发写入接口已关闭，请设置 ERFAIRY_DEV_MUTATIONS=1 后再使用"}
    return run_crawl_all(request.source_ids if request else None)


@app.post("/sources/discover")
def discover_sources(request: SourceDiscoverRequest):
    """Discover source candidates but keep them pending for review."""

    if not DEV_MUTATION_ENABLED:
        return {"detail": "开发写入接口已关闭，请设置 ERFAIRY_DEV_MUTATIONS=1 后再使用"}
    candidates = SourceDiscoverer().discover(request.url)
    saved = [
        store.upsert_source_candidate(
            url=candidate.url,
            source_type=candidate.source_type,
            title=candidate.title,
            reason=candidate.reason,
            config=candidate.config,
        )
        for candidate in candidates
    ]
    return {"discovered": len(saved), "candidates": saved}


@app.post("/sources/candidates/bulk-approve")
async def bulk_approve_source_candidates(request: Request):
    candidate_ids = await _candidate_ids_from_request(request)
    results = []
    for candidate_id in candidate_ids:
        candidate = store.approve_source_candidate(candidate_id)
        results.append(
            {
                "candidate_id": candidate_id,
                "approved": 1 if candidate else 0,
                "candidate": _candidate_with_effective_config(candidate) if candidate else None,
            }
        )
    return {"approved": sum(item["approved"] for item in results), "results": results}


@app.post("/sources/candidates/bulk-reject")
async def bulk_reject_source_candidates(request: Request):
    candidate_ids = await _candidate_ids_from_request(request)
    results = []
    for candidate_id in candidate_ids:
        candidate = store.reject_source_candidate(candidate_id)
        results.append(
            {
                "candidate_id": candidate_id,
                "rejected": 1 if candidate else 0,
                "candidate": _candidate_with_effective_config(candidate) if candidate else None,
            }
        )
    return {"rejected": sum(item["rejected"] for item in results), "results": results}


async def _candidate_ids_from_request(request: Request) -> list[int]:
    content_type = request.headers.get("content-type", "")
    raw_values: list[object] = []
    if "application/json" in content_type:
        payload = await request.json()
        if isinstance(payload, list):
            raw_values = payload
        elif isinstance(payload, dict):
            raw_values = payload.get("candidate_ids", [])
    else:
        form = await request.form()
        raw_values = list(form.getlist("candidate_ids"))
        if not raw_values and form.get("candidate_ids"):
            raw_values = [form.get("candidate_ids")]

    candidate_ids: list[int] = []
    for value in raw_values:
        for part in str(value).split(","):
            part = part.strip()
            if not part:
                continue
            candidate_ids.append(int(part))
    return candidate_ids


@app.post("/sources/candidates/{candidate_id}/approve")
def approve_source_candidate(candidate_id: int, crawl: bool = Query(default=False)):
    candidate = store.approve_source_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail=f"未找到候选源：{candidate_id}")
    payload = {
        "approved": 1,
        "candidate": _candidate_with_effective_config(candidate),
        "source_id": f"candidate-{candidate_id}",
    }
    if crawl:
        payload["crawl_result"] = run_crawl_for_candidate(candidate_id)
    return payload


@app.post("/sources/candidates/{candidate_id}/reject")
def reject_source_candidate(candidate_id: int):
    candidate = store.reject_source_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail=f"未找到候选源：{candidate_id}")
    return {"rejected": 1, "candidate": candidate}


@app.post("/sources/candidates/{candidate_id}/test-crawl")
def test_crawl_source_candidate(request: Request, candidate_id: int):
    """Try crawling a candidate without changing its review status."""

    payload = run_crawl_for_candidate(candidate_id, persist=False)
    accept = request.headers.get("accept", "")
    wants_html = "text/html" in accept and "application/json" not in accept
    if wants_html:
        return templates.TemplateResponse(request, "debug_source_preview.html", payload)
    return payload


def _crawl_with_source_strategy(crawl_config: CrawlConfig, source: SourceConfig | None):
    """按受控数据源策略选择通用爬虫或站点专用抓取器。"""

    if source and source.parse_strategy == "miyoushe-feed":
        return MiyousheFeedCrawler().crawl(
            source_id=source.source_id,
            max_pages=crawl_config.max_pages,
            source_score=source.source_score,
            entry_url=source.entry_url,
        )
    if source and source.parse_strategy == "article-feed":
        return ArticleFeedCrawler().crawl(
            source_id=source.source_id,
            max_pages=crawl_config.max_pages,
            source_score=source.source_score,
        )
    if source and source.parse_strategy in {"rss-feed", "sitemap-feed", "html-list-feed"}:
        return GenericFeedCrawler().crawl(source)
    if source and source.parse_strategy in {"bangumi-api", "moegirl-api"}:
        return ApiFeedCrawler().crawl(source)
    if source and source.parse_strategy == "gamekee-feed":
        return GameKeeFeedCrawler().crawl(source)
    if source and source.parse_strategy == "taptap-feed":
        return TapTapFeedCrawler().crawl(source)
    if source and source.parse_strategy == "biligame-wiki":
        return BiligameWikiCrawler().crawl(source)
    crawler = SmallCrawler()  # 创建爬虫实例。
    return crawler.crawl(crawl_config)  # 执行爬取。


def _run_crawl(crawl_config: CrawlConfig, source: SourceConfig | None) -> dict:
    result = _crawl_with_source_strategy(crawl_config, source)
    _apply_source_score(result.documents, source)
    result.documents = enrich_documents(result.documents, domain_terms)
    run_id = store.start_crawl_run(category=crawl_config.category)
    saved = store.bulk_upsert(result.documents)
    store.save_crawl_errors(run_id, result.errors)
    store.finish_crawl_run(
        run_id,
        source_count=len(crawl_config.seeds),
        saved_count=len(saved),
        error_count=len(result.errors),
        category=crawl_config.category,
        status="completed",
    )
    with INDEX_LOCK:
        index.upsert_many(saved)
    return {
        "source_id": source.source_id if source else "",
        "source_name": source.name if source else "",
        "entry_url": source.entry_url if source else "",
        "parse_strategy": source.parse_strategy if source else "",
        "category": crawl_config.category,
        "max_pages": crawl_config.max_pages,
        "source_score": source.source_score if source else 0.0,
        "run_id": run_id,
        "saved": len(saved),
        "errors": len(result.errors),
        "error_details": [error.as_dict() for error in result.errors],
        "index_update": "incremental",
        "indexed": len(saved),
        "total_documents": store.count(),
    }


def run_crawl_for_source(source_id: str) -> dict:
    source = _find_any_source_config(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"未找到数据源配置：{source_id}")
    return _run_crawl(source.to_crawl_config(), source)


def run_crawl_for_candidate(candidate_id: int, persist: bool = True) -> dict:
    source = _source_config_from_candidate_id(candidate_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"未找到候选源：{candidate_id}")
    if persist:
        return _run_crawl(source.to_crawl_config(), source)
    result = _crawl_with_source_strategy(source.to_crawl_config(), source)
    return {
        "source_id": source.source_id,
        "source_name": source.name,
        "entry_url": source.entry_url,
        "parse_strategy": source.parse_strategy,
        "category": source.category,
        "max_pages": source.max_pages,
        "source_score": source.source_score,
        "saved": 0,
        "would_save": len(result.documents),
        "preview_count": len(result.documents),
        "errors": len(result.errors),
        "error_details": [error.as_dict() for error in result.errors],
        "preview_documents": [
            {
                "title": document.title,
                "url": document.url,
                "source": document.source,
                "category": document.category,
                "summary": document.summary,
                "content_quality_score": document.content_quality_score,
                "content_quality_labels": document.content_quality_labels,
            }
            for document in result.documents
        ],
        "persisted": False,
    }


def run_crawl_all(source_ids: list[str] | None = None) -> dict:
    if not CRAWL_LOCK.acquire(blocking=False):
        return {"status": "busy", "results": [], "total_documents": store.count()}
    try:
        sources = _enabled_source_configs()
        if source_ids:
            wanted = set(source_ids)
            sources = [source for source in sources if source.source_id in wanted or source.name in wanted]
        results = []
        for source in sources:
            try:
                results.append(run_crawl_for_source(source.source_id or source.name))
            except Exception as exc:
                results.append(
                    {
                        "source_id": source.source_id,
                        "source_name": source.name,
                        "saved": 0,
                        "errors": 1,
                        "error": str(exc),
                    }
                )
        return {
            "status": "completed",
            "source_count": len(sources),
            "results": results,
            "total_documents": store.count(),
        }
    finally:
        CRAWL_LOCK.release()


def _crawl_config_from_request(request: CrawlRequest) -> tuple[CrawlConfig, SourceConfig | None]:
    """从请求体构造爬虫配置，可选按 sources.example.json 覆盖。"""

    source_key = request.source_id or request.source_name
    if source_key:
        source = _find_any_source_config(source_key)
        if source:
            return source.to_crawl_config(), source
        raise HTTPException(status_code=404, detail=f"未找到数据源配置：{source_key}。建议使用 source_id，例如 miyoushe-ys")

    if not request.seeds:
        raise HTTPException(status_code=422, detail="请提供 seeds，或提供 sources.example.json 中的 source_id/source_name")

    allowed_domains = {urlparse(seed).netloc for seed in request.seeds}  # 默认只允许抓种子域名。
    return (
        CrawlConfig(
            seeds=request.seeds,
            max_pages=request.max_pages,
            max_depth=request.max_depth,
            delay_seconds=request.delay_seconds,
            allowed_domains=allowed_domains,
            category=request.category,
        ),
        None,
    )


def _enabled_source_configs() -> list[SourceConfig]:
    return [*load_source_configs(), *_approved_source_configs()]


def _find_any_source_config(source_key: str) -> SourceConfig | None:
    source = find_source_config(source_key)
    if source:
        return source
    for candidate_source in _approved_source_configs():
        if candidate_source.source_id == source_key or candidate_source.name == source_key:
            return candidate_source
    return None


def _approved_source_configs() -> list[SourceConfig]:
    sources: list[SourceConfig] = []
    for candidate in store.source_candidates(status="approved", limit=200):
        source = _source_config_from_candidate_id(int(candidate["id"]))
        if source:
            sources.append(source)
    return sources


def _source_config_from_candidate_id(candidate_id: int) -> SourceConfig | None:
    candidate = store.get_source_candidate(candidate_id)
    if not candidate:
        return None
    parsed = urlparse(candidate["url"])
    config = _effective_candidate_config(candidate)
    allowed_domains = config.get("allowed_domains") or ([parsed.netloc] if parsed.netloc else [])
    return SourceConfig(
        name=candidate["title"] or candidate["url"],
        entry_url=candidate["url"],
        allowed_domains=[str(domain) for domain in allowed_domains],
        source_id=f"candidate-{candidate['id']}",
        category=str(config.get("category", "news")),
        max_pages=int(config.get("max_pages", 50)),
        max_depth=int(config.get("max_depth", 0)),
        delay_seconds=float(config.get("delay_seconds", 1.0)),
        source_score=float(config.get("source_score", 0.7)),
        parse_strategy=candidate["source_type"],
        quality_profile=str(config.get("quality_profile", "")),
        quality_mode=str(config.get("quality_mode", "score")),
        wiki_game_title=str(config.get("wiki_game_title", "")),
        wiki_game_aliases=[str(alias) for alias in config.get("wiki_game_aliases", [])],
        notes=candidate["reason"],
        scheduler_interval_minutes=int(config.get("scheduler_interval_minutes", 0)),
    )


def _effective_candidate_config(candidate: dict) -> dict:
    """Return the runtime config used for candidate test-crawl/approve/crawl.

    Older candidate rows keep the config that was discovered at that time. Known
    profile-based sources should still use today's defaults so the debug page,
    test crawl, approve+crawl, and scheduled crawl paths behave the same.
    """

    config = dict(candidate.get("config") or {})
    source_type = str(candidate.get("source_type") or "")
    url = str(candidate.get("url") or "")
    if source_type == "miyoushe-feed":
        return _merge_candidate_defaults(
            config,
            {
                "category": "anime",
                "max_pages": 20,
                "max_depth": 0,
                "delay_seconds": 1.0,
                "source_score": 0.95,
                "quality_profile": "miyoushe-community",
                "quality_mode": "score",
                "allowed_domains": ["www.miyoushe.com"],
                "miyoushe_profile_id": _infer_miyoushe_profile_id(url),
                "scheduler_interval_minutes": 60,
            },
            minimum_max_pages=20,
        )
    if source_type == "taptap-feed":
        return _merge_candidate_defaults(
            config,
            {
                "category": "game",
                "max_pages": 50,
                "max_depth": 0,
                "delay_seconds": 1.0,
                "source_score": 0.78,
                "quality_profile": "taptap-community",
                "quality_mode": "score",
                "allowed_domains": ["www.taptap.cn"],
                "taptap_app_id": _infer_taptap_app_id(url),
                "scheduler_interval_minutes": 60,
            },
            minimum_max_pages=50,
        )
    if source_type == "biligame-wiki":
        alias = _infer_biligame_wiki_alias(url)
        return _merge_candidate_defaults(
            config,
            {
                "category": "game",
                "max_pages": 50,
                "max_depth": 0,
                "delay_seconds": 1.0,
                "source_score": 0.86,
                "allowed_domains": ["wiki.biligame.com"],
                "biligame_wiki_alias": alias,
                **wiki_game_config(alias, str(candidate.get("title") or "")),
                "scheduler_interval_minutes": 60,
            },
            minimum_max_pages=50,
        )
    if source_type == "gamekee-feed":
        alias = _infer_gamekee_alias(url)
        return _merge_candidate_defaults(
            config,
            {
                "category": "game",
                "max_pages": 50,
                "max_depth": 0,
                "delay_seconds": 1.0,
                "source_score": 0.82,
                "allowed_domains": ["www.gamekee.com"],
                "gamekee_alias": alias,
                **wiki_game_config(alias, str(candidate.get("title") or "")),
                "scheduler_interval_minutes": 60,
            },
            minimum_max_pages=50,
        )
    return config


def _candidate_with_effective_config(candidate: dict) -> dict:
    config = candidate.get("config") or {}
    effective_config = _effective_candidate_config(candidate)
    discovery_origin = str(config.get("discovery_origin") or _infer_candidate_discovery_origin(candidate))
    discovery_label = str(config.get("discovery_label") or _discovery_label(discovery_origin))
    return {
        **candidate,
        "effective_config": effective_config,
        "display_name": _candidate_display_name(candidate, effective_config),
        "discovery_origin": discovery_origin,
        "discovery_label": discovery_label,
        "discovery_site": str(config.get("discovery_site") or ""),
    }


def _candidate_display_name(candidate: dict, config: dict) -> str:
    source_type = str(candidate.get("source_type") or "")
    title = str(candidate.get("title") or "").strip()
    game_title = str(config.get("wiki_game_title") or "").strip()
    url = str(candidate.get("url") or "")

    if source_type == "biligame-wiki":
        game_title = game_title or wiki_game_config(_infer_biligame_wiki_alias(url), title).get("wiki_game_title", "")
        return _format_candidate_display_name(source_type, game_title, title)
    if source_type == "gamekee-feed":
        game_title = game_title or wiki_game_config(_infer_gamekee_alias(url), title).get("wiki_game_title", "")
        return _format_candidate_display_name(source_type, game_title, title)
    if source_type == "miyoushe-feed":
        game_title = _miyoushe_game_title(url) or title
        return _format_candidate_display_name(source_type, game_title, title)
    if source_type == "taptap-feed":
        return _format_candidate_display_name(source_type, title, title)
    if source_type in {"moegirl-api", "bangumi-api"}:
        return _format_candidate_display_name(source_type, title, title)
    return title or source_type or url


def _format_candidate_display_name(source_type: str, game_title: str, fallback_title: str = "") -> str:
    label = (game_title or fallback_title).strip()
    for prefix in ("Biligame", "GameKee", "TapTap"):
        label = label.removeprefix(prefix).strip()
    for suffix in ("官方社区", "官方 Wiki", "官方Wiki", "Wiki", "WIKI", "页面"):
        if label.endswith(suffix):
            label = label[: -len(suffix)].strip()
    return f"{source_type} {label}页面" if label else source_type


def _miyoushe_game_title(url: str) -> str:
    path = urlparse(url).path.strip("/").split("/", 1)[0]
    return {
        "ys": "原神",
        "bh3": "崩坏3",
        "sr": "崩坏：星穹铁道",
    }.get(path, "")


def _infer_candidate_discovery_origin(candidate: dict) -> str:
    reason = str(candidate.get("reason") or "")
    if "首页解析" in reason:
        return "index-page"
    if "RSS" in reason or "Sitemap" in reason or candidate.get("source_type") in {"rss-feed", "sitemap-feed", "html-list-feed"}:
        return "generic-feed"
    return "legacy"


def _discovery_label(origin: str) -> str:
    return {
        "known-profile": "内置推荐源",
        "index-page": "首页解析发现",
        "generic-feed": "通用 RSS/Sitemap 发现",
        "legacy": "历史候选源",
    }.get(origin, "历史候选源")


def _merge_candidate_defaults(config: dict, defaults: dict, minimum_max_pages: int) -> dict:
    merged = dict(defaults)
    merged.update({key: value for key, value in config.items() if value not in (None, "", [])})
    try:
        merged["max_pages"] = max(int(merged.get("max_pages", minimum_max_pages)), minimum_max_pages)
    except (TypeError, ValueError):
        merged["max_pages"] = minimum_max_pages
    return merged


def _infer_miyoushe_profile_id(url: str) -> str:
    path = urlparse(url).path.strip("/").split("/", 1)[0]
    return {
        "ys": "miyoushe-ys",
        "bh3": "miyoushe-bh3",
        "sr": "miyoushe-sr",
    }.get(path, "")


def _infer_taptap_app_id(url: str) -> str:
    parts = urlparse(url).path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "app" and parts[1].isdigit():
        return parts[1]
    return "168332"


def _infer_biligame_wiki_alias(url: str) -> str:
    return urlparse(url).path.strip("/").split("/", 1)[0]


def _infer_gamekee_alias(url: str) -> str:
    return urlparse(url).path.strip("/").split("/", 1)[0]


def _create_crawl_scheduler() -> CrawlScheduler:
    enabled = os.getenv("ERFAIRY_CRAWL_SCHEDULER", "0").lower() in {"1", "true", "yes"}
    try:
        interval = int(os.getenv("ERFAIRY_CRAWL_INTERVAL_MINUTES", "60"))
    except ValueError:
        interval = 60
    source_ids = [
        item.strip()
        for item in os.getenv("ERFAIRY_CRAWL_SOURCE_IDS", "").split(",")
        if item.strip()
    ]
    return CrawlScheduler(
        enabled=enabled,
        interval_minutes=interval,
        source_ids=source_ids,
        crawl_source=run_crawl_for_source,
        source_provider=_enabled_source_configs,
    )


def _apply_source_score(documents: list, source: SourceConfig | None) -> None:
    """把受控数据源的来源评分补到抓取结果中。"""

    if source is None or source.source_score <= 0:
        return
    for document in documents:
        if document.source_score <= 0:
            document.source_score = source.source_score


@app.post("/reindex")  # 开发接口：重建索引。
def reindex():
    """从 SQLite 重新构建内存索引。"""

    if not DEV_MUTATION_ENABLED:  # 生产环境可通过环境变量关闭。
        return {"detail": "开发写入接口已关闭，请设置 ERFAIRY_DEV_MUTATIONS=1 后再使用"}  # 明确提示。

    return _rebuild_index_sync("manual")

@app.get("/debug/compare-index")
def debug_compare_index(
    request: Request,
    q: str = Query(default=""),
    category: str = Query(default="all"),
    backends: str = Query(default="memory,redis-zset,meilisearch"),
    limit: int = Query(default=5, ge=1, le=20),
):
    """Compare top search results across multiple index backends."""

    backend_names = _compare_backend_names(backends)
    category_filter = _category_filter(category)
    documents = store.all()
    comparisons = []
    for backend_name in backend_names:
        comparisons.append(_compare_single_backend(backend_name, documents, q, category_filter, limit))
    payload = {
        "query": q,
        "category": category or "all",
        "limit": limit,
        "document_count": len(documents),
        "backends": comparisons,
    }
    wants_json = "application/json" in request.headers.get("accept", "")
    if wants_json:
        return payload
    return templates.TemplateResponse(request, "debug_compare_index.html", payload)


def _compare_backend_names(backends: str) -> list[str]:
    seen = set()
    names = []
    for item in backends.split(","):
        name = item.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names or ["memory"]


def _compare_single_backend(
    backend_name: str,
    documents: list,
    query: str,
    category: str | None,
    limit: int,
) -> dict:
    try:
        compare_index = create_search_index(backend_name)
        compare_index.rebuild(documents)
        results, total = compare_index.search(query, category=category, limit=limit, offset=0)
        return {
            "backend": compare_index.stats().backend,
            "requested_backend": backend_name,
            "status": "ok",
            "total": total,
            "results": [
                {
                    "rank": rank,
                    "id": document.id,
                    "title": document.title,
                    "url": document.url,
                    "category": document.category,
                    "source": document.source,
                    "score": round(score, 6),
                }
                for rank, (document, score) in enumerate(results, start=1)
            ],
        }
    except Exception as exc:
        return {
            "backend": backend_name,
            "requested_backend": backend_name,
            "status": "error",
            "error": str(exc),
            "total": 0,
            "results": [],
        }
@app.get("/debug/crawls")
def debug_crawls(request: Request, limit: int = Query(default=20, ge=1, le=100)):
    """Show recent crawl runs and their error details."""

    runs = store.recent_crawl_runs(limit=limit)
    payload = {
        "runs": runs,
        "run_count": len(runs),
        "limit": limit,
        "total_documents": store.count(),
    }
    wants_json = "application/json" in request.headers.get("accept", "")
    if wants_json:
        return payload
    return templates.TemplateResponse(request, "debug_crawls.html", payload)


@app.get("/debug/crawl-scheduler")
def debug_crawl_scheduler(request: Request):
    payload = crawl_scheduler.as_dict() if crawl_scheduler else _create_crawl_scheduler().as_dict()
    wants_json = "application/json" in request.headers.get("accept", "")
    if wants_json:
        return payload
    return templates.TemplateResponse(request, "debug_crawl_scheduler.html", payload)


@app.get("/debug/sources")
def debug_sources(
    request: Request,
    status: str = Query(default="all"),
    origin: str = Query(default="all"),
    page: int = Query(default=1, ge=1),
):
    configured = [
        {
            "source_id": source.source_id,
            "name": source.name,
            "entry_url": source.entry_url,
            "parse_strategy": source.parse_strategy,
            "category": source.category,
        }
        for source in load_source_configs()
    ]
    approved = [
        {
            "source_id": source.source_id,
            "name": source.name,
            "entry_url": source.entry_url,
            "parse_strategy": source.parse_strategy,
            "category": source.category,
        }
        for source in _approved_source_configs()
    ]
    per_page = 50
    total_candidates = store.count_source_candidates(status=status, origin=origin)
    page_count = max((total_candidates + per_page - 1) // per_page, 1)
    page = min(page, page_count)
    offset = (page - 1) * per_page
    candidates = [
        _candidate_with_effective_config(candidate)
        for candidate in store.source_candidates_page(status=status, origin=origin, limit=per_page, offset=offset)
    ]
    payload = {
        "configured_sources": configured,
        "approved_sources": approved,
        "candidates": candidates,
        "candidate_count": len(candidates),
        "total_candidates": total_candidates,
        "page": page,
        "per_page": per_page,
        "page_count": page_count,
        "has_prev": page > 1,
        "has_next": page < page_count,
        "prev_href": f"/debug/sources?status={status}&origin={origin}&page={max(page - 1, 1)}",
        "next_href": f"/debug/sources?status={status}&origin={origin}&page={min(page + 1, page_count)}",
        "status": status,
        "origin": origin,
        "status_filters": _source_status_filters(origin),
        "origin_filters": _source_origin_filters(status),
    }
    wants_json = "application/json" in request.headers.get("accept", "")
    if wants_json:
        return payload
    return templates.TemplateResponse(request, "debug_sources.html", payload)
def _source_status_filters(origin: str) -> list[dict[str, str]]:
    return [
        {"value": "all", "label": "全部", "href": f"/debug/sources?status=all&origin={origin}&page=1"},
        {"value": "pending", "label": "待审核", "href": f"/debug/sources?status=pending&origin={origin}&page=1"},
        {"value": "approved", "label": "已启用", "href": f"/debug/sources?status=approved&origin={origin}&page=1"},
        {"value": "rejected", "label": "已拒绝", "href": f"/debug/sources?status=rejected&origin={origin}&page=1"},
    ]


def _source_origin_filters(status: str) -> list[dict[str, str]]:
    return [
        {"value": "all", "label": "全部来源", "href": f"/debug/sources?status={status}&origin=all&page=1"},
        {"value": "index-page", "label": "首页解析发现", "href": f"/debug/sources?status={status}&origin=index-page&page=1"},
        {"value": "known-profile", "label": "内置推荐源", "href": f"/debug/sources?status={status}&origin=known-profile&page=1"},
        {"value": "generic-feed", "label": "通用 Feed", "href": f"/debug/sources?status={status}&origin=generic-feed&page=1"},
        {"value": "legacy", "label": "历史候选源", "href": f"/debug/sources?status={status}&origin=legacy&page=1"},
    ]


@app.get("/debug/redis")
def debug_redis(request: Request, term: str = Query(default="")):
    """Show Redis keys, terms, and postings when the real Redis backend is active."""

    if hasattr(index, "debug_snapshot"):
        payload = index.debug_snapshot(term=term)
    else:
        stats = search_service.stats()
        payload = {
            "available": False,
            "backend": stats["backend"],
            "message": "Redis debug view is only available when ERFAIRY_INDEX_BACKEND=redis.",
            "hint": "Set ERFAIRY_INDEX_BACKEND=redis and ERFAIRY_REDIS_URL=redis://localhost:6379/0, then restart uvicorn.",
            "keys": [],
            "sample_terms": [],
            "postings": [],
            "selected_term": term,
        }
    wants_json = "application/json" in request.headers.get("accept", "")
    if wants_json:
        return payload
    return templates.TemplateResponse(request, "debug_redis.html", payload)

@app.delete("/documents/{doc_id}")
def delete_document(doc_id: int):
    """Delete one document and remove it from the current index incrementally."""

    if not DEV_MUTATION_ENABLED:
        return {"detail": "开发写入接口已关闭，请设置 ERFAIRY_DEV_MUTATIONS=1 后再使用"}
    deleted = store.delete(doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"未找到文档：{doc_id}")
    with INDEX_LOCK:
        index.delete_many([doc_id])
    return {
        "deleted": 1,
        "document_id": doc_id,
        "index_update": "incremental",
        "removed_from_index": 1,
        "total_documents": store.count(),
    }
