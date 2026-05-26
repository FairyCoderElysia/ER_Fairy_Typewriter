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

import os  # 读取环境变量 ERFAIRY_DB。
from contextlib import asynccontextmanager  # FastAPI 推荐用 lifespan 管理应用启动/关闭逻辑。
from pathlib import Path  # 处理项目路径。
from urllib.parse import urlencode  # 安全拼接查询字符串。
from urllib.parse import urlparse  # 从种子 URL 中提取域名。

from fastapi import FastAPI, Form, Query, Request  # FastAPI 核心对象和请求参数工具。
from fastapi.responses import HTMLResponse, RedirectResponse  # HTML 响应和表单跳转响应。
from fastapi.staticfiles import StaticFiles  # 挂载 CSS 等静态文件。
from fastapi.templating import Jinja2Templates  # 渲染 HTML 模板。
from pydantic import BaseModel, Field  # 定义请求体模型和字段校验规则。

from .crawler import CrawlConfig, SmallCrawler  # 爬虫配置和爬虫实现。
from .indexer import InMemoryTfIdfIndex, SearchIndex  # 内存搜索索引和接口。
from .sample_data import SAMPLE_DOCUMENTS  # 内置样例资料。
from .search import SearchService  # 搜索服务层。
from .store import SQLiteDocumentStore  # SQLite 文档存储。


BASE_DIR = Path(__file__).resolve().parent  # erfairy 包目录。
PROJECT_DIR = BASE_DIR.parent  # 项目根目录。
DATA_PATH = Path(os.getenv("ERFAIRY_DB", PROJECT_DIR / "data" / "erfairy.sqlite3"))  # 允许用环境变量覆盖数据库路径。

store = SQLiteDocumentStore(DATA_PATH)  # 文档持久化层。
index: SearchIndex = InMemoryTfIdfIndex()  # 搜索索引层，类型先抽象成接口，便于后续切换实现。
search_service = SearchService(index)  # 搜索服务层，封装分页和高亮。
DEV_MUTATION_ENABLED = os.getenv("ERFAIRY_DEV_MUTATIONS", "1").lower() not in {"0", "false", "no"}  # 本地开发接口默认开启。


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。

    设计思路：
        FastAPI 新版本推荐用 lifespan 代替 @app.on_event("startup")。
        启动时写入样例数据并重建索引，关闭时无需额外清理。
    """

    store.bulk_upsert(SAMPLE_DOCUMENTS)  # 写入/更新内置样例文档。
    index.rebuild(store.all())  # 从 SQLite 全量重建内存索引。
    yield  # 服务运行期间控制权交给 FastAPI。


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

    设计思路：
        用 Pydantic 做边界校验，比在函数里手写 if 更集中、更清楚。
    """

    seeds: list[str] = Field(min_length=1)  # 至少提供一个种子 URL。
    max_pages: int = Field(default=10, ge=1, le=100)  # 限制 1~100 页，避免误抓太多。
    max_depth: int = Field(default=1, ge=0, le=3)  # 限制深度 0~3，防止爬虫扩散。
    delay_seconds: float = Field(default=0.5, ge=0.0, le=10.0)  # 限制请求间隔范围。
    category: str = "anime"  # 默认分类。


@app.get("/", response_class=HTMLResponse)  # GET 首页，返回 HTML。
def home(request: Request) -> HTMLResponse:
    """渲染搜索首页。"""

    return templates.TemplateResponse(request, "home.html", {})  # 返回 Jinja2 模板响应。


@app.get("/search")  # GET 搜索；既支持浏览器 HTML，也支持 API JSON。
def search(
    request: Request,  # Request 用来读取 Accept 请求头。
    q: str = Query(default=""),  # 查询词，默认空字符串。
    page: int = Query(default=1, ge=1),  # 页码，FastAPI 自动校验 >=1。
    category: str = Query(default="anime"),  # 分类过滤。
):
    """搜索接口。

    返回：
        如果 Accept 包含 application/json，返回 JSON；
        否则渲染 results.html 页面。
    """

    payload = search_service.search(q, page=page, per_page=10, category=category or None)  # 调用搜索服务。
    wants_json = "application/json" in request.headers.get("accept", "")  # 判断调用方是否希望 JSON。
    if wants_json:  # API 调用场景。
        return payload  # FastAPI 会自动序列化 dict 为 JSON。
    return templates.TemplateResponse(request, "results.html", {**payload, "category": category})  # 浏览器场景渲染 HTML。


@app.get("/debug/search")  # GET 调试搜索；首版只返回 JSON，方便学习排序细节。
def debug_search(
    q: str = Query(default=""),  # 查询词，默认空字符串。
    category: str = Query(default="anime"),  # 分类过滤。
):
    """返回一次搜索的分词、候选召回和分数拆解。

    使用场景：
        学习阶段观察 TF-IDF、字段权重和 boost 如何共同影响排序。
    """

    return search_service.explain(q, category=category or None)  # 返回结构化解释 JSON。


@app.get("/debug/index")  # GET 索引状态；阶段一收尾提供最小可观察性。
def debug_index():
    """返回当前内存索引的基本状态。"""

    return search_service.stats()  # 返回文档数、token 数、倒排项数量和最近重建时间。


@app.post("/search")  # 表单提交使用 POST，再重定向到 GET 搜索页。
def search_form(q: str = Form(default=""), category: str = Form(default="anime")):
    """处理搜索表单提交。

    设计思路：
        搜索结果页使用 GET URL 更方便分享和刷新，因此 POST 表单只负责重定向。
    """

    return RedirectResponse(url=f"/search?{urlencode({'q': q, 'category': category})}", status_code=303)  # 303 表示用 GET 访问新地址。


@app.post("/crawl")  # 开发接口：触发爬虫。
def crawl(request: CrawlRequest):
    """抓取种子 URL 并重建索引。

    使用场景：
        开发阶段手动 POST 一批种子 URL，扩充搜索资料。
    """

    if not DEV_MUTATION_ENABLED:  # 生产环境可通过环境变量关闭抓取和重建接口。
        return {"detail": "开发写入接口已关闭，请设置 ERFAIRY_DEV_MUTATIONS=1 后再使用"}  # 明确提示。

    allowed_domains = {urlparse(seed).netloc for seed in request.seeds}  # 默认只允许抓种子域名。
    crawler = SmallCrawler()  # 创建爬虫实例。
    result = crawler.crawl(  # 执行爬取。
        CrawlConfig(  # 把请求体转换成爬虫配置。
            seeds=request.seeds,  # 种子 URL。
            max_pages=request.max_pages,  # 页数上限。
            max_depth=request.max_depth,  # 深度上限。
            delay_seconds=request.delay_seconds,  # 请求间隔。
            allowed_domains=allowed_domains,  # 域名白名单。
            category=request.category,  # 文档分类。
        )
    )
    run_id = store.start_crawl_run(category=request.category)  # 记录这次抓取运行。
    saved = store.bulk_upsert(result.documents)  # 保存抓取文档。
    store.save_crawl_errors(run_id, result.errors)  # 保存抓取失败记录。
    store.finish_crawl_run(  # 更新运行结束状态。
        run_id,
        source_count=len(request.seeds),
        saved_count=len(saved),
        error_count=len(result.errors),
        category=request.category,
        status="completed",
    )
    index.rebuild(store.all())  # 数据变化后重建索引，保证立即可搜。
    return {"saved": len(saved), "errors": len(result.errors), "total_documents": store.count()}  # 返回本次保存数、错误数和总文档数。


@app.post("/reindex")  # 开发接口：重建索引。
def reindex():
    """从 SQLite 重新构建内存索引。"""

    if not DEV_MUTATION_ENABLED:  # 生产环境可通过环境变量关闭。
        return {"detail": "开发写入接口已关闭，请设置 ERFAIRY_DEV_MUTATIONS=1 后再使用"}  # 明确提示。

    index.rebuild(store.all())  # 全量重建索引。
    return {"indexed": len(index.documents)}  # 返回索引中文档数量。
