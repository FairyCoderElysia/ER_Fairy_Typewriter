# ER Fairy Typewriter

爱莉希雅的妖精打字机：一个用于学习搜索引擎完整链路的轻量二次元搜索引擎 MVP。

当前进度：阶段 4 已完成，项目已经具备“爬虫 -> 存储 -> 索引 -> 搜索 -> 调试解释 -> 评测”的完整闭环。

## 功能

- 小型爬虫：从种子 URL 抓取公开 HTML 页面，限制域名、深度、数量和请求频率。
- 页面解析：提取标题、正文、摘要、标签、来源、发布时间、图片和链接。
- 文档存储：使用 SQLite 保存结构化文档。
- 抓取记录：使用 `crawl_runs` 和 `crawl_errors` 保存抓取运行状态与失败原因。
- 自研索引：使用中文/英文分词、字段权重、倒排索引和 TF-IDF/余弦相似度排序。
- 索引抽象：`SearchIndex` 定义统一接口，便于后续对照 Redis 或专业搜索引擎后端。
- Web 搜索：FastAPI API + 简洁搜索网页。
- 可解释搜索：`/debug/search` 展示分词、字段命中、TF-IDF、boost 和最终分数。
- 索引状态：`/debug/index` 展示文档数、token 数、倒排项数量和最近重建时间。
- 搜索评测：使用 `tests/fixtures/search_eval.json` 验证 Top1、Top3 和零结果率。
- 二次元垂直化：已接入 `aliases`、`entity_type`、`game_title`、`character_name`、`source_score` 等字段。
- 设计系统：`docs/design-system.md` 约束后续页面和调试界面风格。
- 受控数据源：`sources.example.json` 提供抓取源配置样例。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 启动

```powershell
uvicorn erfairy.web:app --reload
```

打开 `http://127.0.0.1:8000`。

第一次启动会写入几条本地样例数据，你可以直接搜索 `爱莉希雅`、`芙莉莲`、`魔法少女`。
也可以搜索 `原神`、`雷电将军`、`纳西妲`、`明日方舟` 等游戏/角色关键词。

## 学习顺序

建议顺着下面四步学：

1. `docs/learning-roadmap.md`，先看完整路线。
2. `erfairy/models.py` + `erfairy/store.py`，理解文档是怎么存的。
3. `erfairy/indexer.py` + `erfairy/search.py`，理解分词、倒排索引和排序。
4. `erfairy/web.py` + `tests/test_api.py`，理解搜索接口、调试接口和开发写入开关。

建议先阅读 `docs/learning-roadmap.md`。这份文档按“文档模型 -> 存储 -> 分词 -> 索引 -> 搜索服务 -> 爬虫解析 -> 调试搜索”的顺序组织，适合用来复盘完整搜索引擎链路。

## 项目文档

- `docs/learning-roadmap.md`：按代码模块安排学习顺序，适合边读边运行。
- `docs/office-hours-design.md`：记录项目定位、阶段路线、架构决策、测试策略和后续任务。
- `docs/design-system.md`：记录页面视觉和组件规则。

## API

搜索：

```http
GET /search?q=爱莉希雅&page=1&category=anime
Accept: application/json
```

抓取公开网页：

```http
POST /crawl
Content-Type: application/json

{
  "seeds": ["https://example.com/wiki/anime"],
  "max_pages": 10,
  "max_depth": 1,
  "delay_seconds": 0.5,
  "category": "anime"
}
```

返回内容会包含 `saved`、`errors` 和 `total_documents`。其中 `errors` 表示本次抓取中被域名限制、robots 拒绝、下载失败或解析失败的页面数量，详细记录会写入 SQLite。

重建索引：

```http
POST /reindex
```

`/crawl` 和 `/reindex` 是本地开发写入接口，默认开启。部署或演示只读环境时，可以关闭它们：

```powershell
$env:ERFAIRY_DEV_MUTATIONS="0"
uvicorn erfairy.web:app --reload
```

关闭后再请求 `/crawl` 或 `/reindex`，接口会返回“开发写入接口已关闭”的提示，不会写入数据库或重建索引。

### 学习现阶段重点

- 看 `source_score` 如何作为来源质量的轻微加分参与排序。
- 看 `aliases` 如何帮助别名、中英混合查询召回结果。
- 看 `entity_type`、`game_title`、`character_name` 如何让角色页和作品页的排序更稳定。
- 看 `/debug/search` 如何把一次查询的分数来源拆开。

调试一次搜索为什么这样排序：

```http
GET /debug/search?q=原神&category=anime
```

返回内容包括查询分词、未命中 token、候选文档、字段命中、TF-IDF 分数、boost 分数和最终分数。

查看索引状态：

```http
GET /debug/index
```

## 测试

```powershell
pytest
```

搜索质量评测：

```powershell
pytest tests/test_search_eval.py
```

当前测试覆盖普通搜索 JSON、浏览器结果页、调试搜索、索引状态、分词、排序、SearchIndex 接口、SQLite upsert、HTML 解析和开发写入接口开关。

## 学习路线

这个项目故意保持轻量：先把搜索引擎的完整闭环跑通，再逐步替换模块。

下一步可以继续扩展：

- 先把阶段 4 的新字段和二次元垂直化逻辑学透。
- 再继续完善别名词典、站点适配器和来源评分规则。
- 然后补 `/debug/search` 的 HTML 学习页面。
- 最后再把默认内存索引替换为 Redis 倒排索引，并和当前实现做对照。
