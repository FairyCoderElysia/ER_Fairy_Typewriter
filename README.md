# ER Fairy Typewriter

爱莉希雅的妖精打字机：一个用于学习搜索引擎完整链路的轻量二次元搜索引擎 MVP。

当前进度：阶段 6 已开始。项目已经具备“fixture/公开站点 -> 爬虫 -> 解析 -> 领域词典补全 -> 去重存储 -> 可切换索引 -> 搜索 -> 调试解释 -> 评测”的完整闭环。

## 功能

- 小型爬虫：从种子 URL 抓取公开 HTML 页面，限制域名、深度、数量和请求频率。
- 页面解析：提取标题、正文、摘要、标签、来源、发布时间、图片和链接。
- 文档存储：使用 SQLite 保存结构化文档。
- 抓取记录：使用 `crawl_runs` 和 `crawl_errors` 保存抓取运行状态与失败原因。
- 本地 fixture 采集：爬虫支持 `file://` HTML，用本地页面模拟真实站点。
- 内容去重：解析器生成 `content_hash`，SQLite 用 URL、正文指纹和标题相似度避免重复入库。
- 自研索引：使用中文/英文分词、字段权重、倒排索引和 TF-IDF/余弦相似度排序。
- 索引抽象：`SearchIndex` 定义统一接口，便于后续对照 Redis 或专业搜索引擎后端。
- 索引后端切换：默认使用内存 TF-IDF，也可用 `ERFAIRY_INDEX_BACKEND=redis-zset` 切到 Redis ZSet 风格教学后端。
- Web 搜索：FastAPI API + 简洁搜索网页。
- 可解释搜索：`/debug/search` 展示分词、字段命中、TF-IDF、boost 和最终分数。
- 索引状态：`/debug/index` 展示文档数、token 数、倒排项数量和最近重建时间。
- 搜索评测：使用 `tests/fixtures/search_eval.json` 验证 Top1、Top3 和零结果率。
- 二次元垂直化：已接入 `aliases`、`entity_type`、`game_title`、`character_name`、`source_score` 等字段。
- 设计系统：`docs/design-system.md` 约束后续页面和调试界面风格。
- 别名词典：`aliases.example.json` 记录角色、作品和资讯意图词，`erfairy/domain_terms.py` 会在样例入库和爬虫保存前补全文档字段。
- 受控数据源：`sources.example.json` 提供本地 fixture 和 6 个真实公开站点抓取源配置，并能配置 `source_score`。
- 文章流适配：MyAnimeList、Anime News Network、FGO 官方新闻会从列表页抽取多篇文章并抓取详情页。
- 站点专用适配：米游社源已从 SPA 入口解析升级为帖子流抓取，能把原神、崩坏3、崩坏：星穹铁道分区里的多篇帖子转成搜索文档。
- 新闻新鲜度：资讯意图查询会给近期新闻轻量加分，不替代 TF-IDF 和字段相关性。

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
- `aliases.example.json`：记录角色/作品别名和资讯意图词，由 `erfairy/domain_terms.py` 加载。
- `sources.example.json`：记录本地 fixture 和公开站点的受控抓取配置，包括来源评分。

## API

搜索默认覆盖全部分类：

```http
GET /search?q=爱莉希雅&page=1
Accept: application/json
```

精细搜索时可以用分类筛选：

```http
GET /search?q=Anime&page=1&category=news
Accept: application/json
```

`category=all` 或省略 `category` 都表示搜索全部分类；`category=anime`、`category=news`、`category=character` 会只搜索某一类。

抓取公开网页：

```http
POST /crawl
Content-Type: application/json

{
  "seeds": ["https://example.com/wiki/anime"],
  "max_pages": 10,
  "max_depth": 1,
  "delay_seconds": 0.5
}
```

`category` 可以省略，默认使用自动分类。解析器会根据 URL、标题、摘要、标签和 `entity_type` 推断 `news`、`character` 或 `anime`。如果你已经确定分类，也可以手动传入 `"category": "news"`、`"category": "anime"` 或 `"category": "character"` 覆盖自动判断。

按 `sources.example.json` 中的数据源名称抓取：

```http
POST /crawl
Content-Type: application/json

{
  "source_id": "mal-news"
}
```

`source_id` 是推荐写法，因为它只包含 ASCII 字符，在 PowerShell 里不会遇到中文 JSON 编码问题。仍然可以使用 `source_name`，但需要确保请求体按 UTF-8 发送。

`sources.example.json` 中每个源都有自己的 `max_pages`：MAL / ANN / FGO 默认抓 20 篇详情，米游社源默认抓 5 篇帖子。你也可以在请求体里传 `max_pages` 覆盖配置。

常用公开源 ID：

- `mal-news`：MyAnimeList 动漫新闻
- `ann-home`：Anime News Network 首页文章流
- `fgo-news`：Fate/Grand Order 官方新闻
- `miyoushe-ys`：原神米游社帖子流
- `miyoushe-bh3`：崩坏3米游社帖子流
- `miyoushe-sr`：崩坏：星穹铁道米游社帖子流

米游社官方社区帖子流也可以用同样方式抓取：

```http
POST /crawl
Content-Type: application/json

{
  "source_id": "miyoushe-ys"
}
```

可用 ID 还包括 `miyoushe-bh3` 和 `miyoushe-sr`。米游社页面是前端应用，当前不再只保存入口壳，而是通过帖子列表接口生成多篇 `news` 文档。

返回内容会包含 `run_id`、`saved`、`errors`、`error_details` 和 `total_documents`。其中 `errors` 表示本次抓取中被域名限制、robots 拒绝、下载失败或解析失败的页面数量，详细记录会写入 SQLite。

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
- 看 `erfairy/domain_terms.py` 如何把 `aliases.example.json` 里的词典补进样例和抓取文档。
- 看新闻意图查询下 `published_at` / `crawled_at` 如何产生轻量新鲜度加分。
- 看 `entity_type`、`game_title`、`character_name` 如何让角色页和作品页的排序更稳定。
- 看 `/debug/search` 如何把一次查询的分数来源拆开。
- 看 `ERFAIRY_INDEX_BACKEND` 如何在 `memory` 和 `redis-zset` 后端之间切换。

调试一次搜索为什么这样排序：

```http
GET /debug/search?q=原神&category=anime
```

返回内容包括查询分词、未命中 token、候选文档、字段命中、TF-IDF 分数、boost 分数和最终分数。

查看索引状态：

```http
GET /debug/index
```

返回里的 `backend` 会显示当前索引后端。默认是 `memory`。

切换到 Redis ZSet 风格教学后端：

```powershell
$env:ERFAIRY_INDEX_BACKEND="redis-zset"
uvicorn erfairy.web:app --reload
```

这个后端不需要外部 Redis 服务；它在本地内存里用 `term -> [(score, doc_id)]` 模拟 Redis ZSet 倒排表，方便先对照数据结构和搜索结果。后续接真 Redis 时，可以把这一层替换为 Redis 命令。

## 测试

```powershell
python -m pytest
```

搜索质量评测：

```powershell
python -m pytest tests/test_search_eval.py
```

当前测试覆盖普通搜索 JSON、浏览器结果页、调试搜索、索引状态、分词、排序、SearchIndex 接口、SQLite upsert、HTML 解析和开发写入接口开关。
阶段 5 额外覆盖本地 HTML fixture 抓取、公开站点配置加载、抓取错误记录、meta 垂直字段解析、content hash 去重和标题相似度去重。阶段 6 已开始覆盖可切换索引后端、Redis ZSet 风格倒排结构和后端契约测试。

## 学习路线

这个项目故意保持轻量：先把搜索引擎的完整闭环跑通，再逐步替换模块。

下一步可以继续扩展：

- 先把阶段 4 的新字段和二次元垂直化逻辑学透。
- 继续细化文章流详情字段，例如作者、更新时间、标签细分。
- 再补抓取状态页面和排序解释 HTML 页面，降低调试门槛。
- 然后把 Redis ZSet 风格教学后端替换/对接到真实 Redis 服务。
- 最后引入 Meilisearch 或 Typesense 做专业搜索引擎对照。
