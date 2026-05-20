from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.parse import urlparse

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .crawler import CrawlConfig, SmallCrawler
from .indexer import InMemoryTfIdfIndex
from .sample_data import SAMPLE_DOCUMENTS
from .search import SearchService
from .store import SQLiteDocumentStore


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DATA_PATH = Path(os.getenv("ERFAIRY_DB", PROJECT_DIR / "data" / "erfairy.sqlite3"))

app = FastAPI(title="ER Fairy Typewriter", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

store = SQLiteDocumentStore(DATA_PATH)
index = InMemoryTfIdfIndex()
search_service = SearchService(index)


class CrawlRequest(BaseModel):
    seeds: list[str] = Field(min_length=1)
    max_pages: int = Field(default=10, ge=1, le=100)
    max_depth: int = Field(default=1, ge=0, le=3)
    delay_seconds: float = Field(default=0.5, ge=0.0, le=10.0)
    category: str = "anime"


@app.on_event("startup")
def startup() -> None:
    store.bulk_upsert(SAMPLE_DOCUMENTS)
    index.rebuild(store.all())


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "home.html", {})


@app.get("/search")
def search(
    request: Request,
    q: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    category: str = Query(default="anime"),
):
    payload = search_service.search(q, page=page, per_page=10, category=category or None)
    wants_json = "application/json" in request.headers.get("accept", "")
    if wants_json:
        return payload
    return templates.TemplateResponse(request, "results.html", {**payload, "category": category})


@app.post("/search")
def search_form(q: str = Form(default=""), category: str = Form(default="anime")):
    return RedirectResponse(url=f"/search?{urlencode({'q': q, 'category': category})}", status_code=303)


@app.post("/crawl")
def crawl(request: CrawlRequest):
    allowed_domains = {urlparse(seed).netloc for seed in request.seeds}
    crawler = SmallCrawler()
    documents = crawler.crawl(
        CrawlConfig(
            seeds=request.seeds,
            max_pages=request.max_pages,
            max_depth=request.max_depth,
            delay_seconds=request.delay_seconds,
            allowed_domains=allowed_domains,
            category=request.category,
        )
    )
    saved = store.bulk_upsert(documents)
    index.rebuild(store.all())
    return {"saved": len(saved), "total_documents": store.count()}


@app.post("/reindex")
def reindex():
    index.rebuild(store.all())
    return {"indexed": len(index.documents)}
