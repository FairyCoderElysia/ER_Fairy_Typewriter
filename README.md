# ER Fairy Typewriter

爱莉希雅的妖精打字机：一个用于学习搜索引擎完整链路的轻量二次元搜索引擎 MVP。

当前进度：阶段 7 持续采集体验已完成第一版。项目已经具备“fixture/公开站点/候选源 -> 爬虫 -> 解析 -> 领域词典补全 -> 去重存储 -> 增量索引 -> 可切换后端 -> 搜索 -> 调试解释 -> 评测”的完整闭环。

## 功能

- 小型爬虫：从种子 URL 抓取公开 HTML 页面，限制域名、深度、数量和请求频率。
- 页面解析：提取标题、正文、摘要、标签、来源、发布时间、图片和链接。
- 文档存储：使用 SQLite 保存结构化文档。
- 抓取记录：使用 `crawl_runs` 和 `crawl_errors` 保存抓取运行状态与失败原因。
- 本地 fixture 采集：爬虫支持 `file://` HTML，用本地页面模拟真实站点。
- 内容去重：解析器生成 `content_hash`，SQLite 用 URL、正文指纹和标题相似度避免重复入库。
- 自研索引：使用中文/英文分词、字段权重、倒排索引和 TF-IDF/余弦相似度排序。
- 索引抽象：`SearchIndex` 定义统一接口，便于后续对照 Redis 或专业搜索引擎后端。
- 索引后端切换：默认使用内存 TF-IDF，也可用 `ERFAIRY_INDEX_BACKEND=redis-zset` 切到 Redis ZSet 风格教学后端，或用 `ERFAIRY_INDEX_BACKEND=redis` 接入真实 Redis ZSet postings。
- Web 搜索：FastAPI API + 简洁搜索网页。
- 可解释搜索：`/debug/search` 展示分词、字段命中、TF-IDF、boost 和最终分数。
- 索引状态：`/debug/index` 展示文档数、token 数、倒排项数量和最近重建时间。
- 搜索评测：使用 `tests/fixtures/search_eval.json` 验证 Top1、Top3 和零结果率。
- 二次元垂直化：已接入 `aliases`、`entity_type`、`game_title`、`character_name`、`source_score` 等字段。
- 设计系统：`docs/design-system.md` 约束后续页面和调试界面风格。
- 别名词典：`aliases.example.json` 记录角色、作品和资讯意图词，`erfairy/domain_terms.py` 会在样例入库和爬虫保存前补全文档字段。
- 受控数据源：`sources.example.json` 提供本地 fixture、公开新闻源、米游社源和国内二次元/二游候选源配置示例，并能配置 `source_score`、`max_pages` 和 `scheduler_interval_minutes`。
- 文章流适配：MyAnimeList、Anime News Network、FGO 官方新闻会从列表页抽取多篇文章并抓取详情页。
- 站点专用适配：米游社、GameKee、TapTap 已有专用抓取器；萌娘百科和 Bangumi 使用 API 型抓取器。
- 持续采集：支持 `/crawl/all` 批量抓取、`/sources/discover` 候选源发现、候选源试抓/审核/启用并立即抓取，以及默认关闭的轻量自动调度器。
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

`sources.example.json` 中每个源都有自己的 `max_pages`：MAL / ANN / FGO 默认抓 50 篇详情，米游社源默认抓 20 篇帖子，本地 fixture 保持较小规模。你也可以在请求体里传 `max_pages` 覆盖配置。

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

返回内容会包含 `run_id`、`saved`、`errors`、`error_details`、`index_update`、`indexed` 和 `total_documents`。其中 `errors` 表示本次抓取中被域名限制、robots 拒绝、下载失败或解析失败的页面数量，详细记录会写入 SQLite。`index_update=incremental` 表示本次抓取保存的文档已增量写入当前索引，不再每次抓取后全量 rebuild；如果你怀疑索引状态异常，仍可手动调用 `/reindex` 做全量重建兜底。

删除单篇文档并增量移除索引：

```http
DELETE /documents/{doc_id}
```

PowerShell 示例：

```powershell
Invoke-RestMethod -Method Delete "http://127.0.0.1:8000/documents/123"
```

返回里的 `index_update=incremental` 和 `removed_from_index=1` 表示 SQLite 已删除该文档，并且当前索引已移除对应 postings。

查看最近抓取运行和错误明细：

```http
GET /debug/crawls
GET /debug/crawls?limit=50
```

脚本调用时可以请求 JSON：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/debug/crawls?limit=20" -Headers @{Accept="application/json"}
```

比较同一查询在不同索引后端下的 Top 结果：

```http
GET /debug/compare-index?q=原神&backends=memory,redis-zset,meilisearch
```

如果某个外部后端没有启动，例如 Meilisearch 或 Redis，页面会把该后端标为 `error`，其他可用后端仍会正常显示。JSON 调用：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/debug/compare-index?q=原神&backends=memory,redis-zset" -Headers @{Accept="application/json"}
```

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
- 看 `ERFAIRY_INDEX_BACKEND` 如何在 `memory`、`redis-zset` 和真实 `redis` 后端之间切换。

调试一次搜索为什么这样排序：

```http
GET /debug/search?q=原神&category=anime
```

浏览器访问时会返回 HTML 调试页，把查询分词、未命中 token、候选文档、字段命中、TF-IDF 分数、boost 分数和最终分数分区展示。脚本调用时可以请求 JSON：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/debug/search?q=原神&category=anime" -Headers @{Accept="application/json"}
```

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

切换到真实 Redis ZSet 后端：

```powershell
docker run --name erfairy-redis -p 6379:6379 -d redis:7
$env:ERFAIRY_INDEX_BACKEND="redis"
$env:ERFAIRY_REDIS_URL="redis://localhost:6379/0"
$env:ERFAIRY_REDIS_PREFIX="erfairy"
uvicorn erfairy.web:app --reload
```

启动后访问：

```http
GET /debug/index
```

如果返回里的 `backend` 是 `redis`，说明当前搜索索引的倒排 postings 已写入真实 Redis ZSet。当前版本仍把文档对象、字段命中解释和排序所需的轻量缓存保留在 Python 进程内；Redis 负责保存 `term -> doc_id score` 这一层倒排表。没有启动 Redis 时不要设置 `ERFAIRY_INDEX_BACKEND=redis`，否则应用会明确报错；继续使用默认 `memory` 或教学模拟 `redis-zset` 不需要 Redis 服务。

切换到 Meilisearch 专业搜索后端：

```powershell
$env:ERFAIRY_INDEX_BACKEND="meilisearch"
$env:ERFAIRY_MEILI_URL="http://localhost:7700"
$env:ERFAIRY_MEILI_MASTER_KEY=""
$env:ERFAIRY_MEILI_INDEX="erfairy_documents"
uvicorn erfairy.web:app --reload
```

启动后访问：

```http
GET /debug/index
```

如果返回里的 `backend` 是 `meilisearch`，说明当前搜索先由 Meilisearch 召回候选，再由项目自研的字段权重、别名、垂直 boost 和新鲜度规则做二次排序。Python 进程仍保留文档对象，用于摘要、高亮、调试输出、本地统计和二次排序。`/crawl` 会把新增/更新文档增量同步到 Meilisearch，`DELETE /documents/{doc_id}` 会同步删除 Meilisearch 中的文档。

查看 Redis 里的索引结构：

```http
GET /debug/redis
GET /debug/redis?term=genshin
```

这个页面会展示当前 Redis URL、key prefix、Redis keys、meta、部分 terms，以及某个 term 对应的 ZSet postings。脚本调用时可以请求 JSON：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/debug/redis?term=genshin" -Headers @{Accept="application/json"}
```

## 持续采集与候选源

批量抓取所有已配置和已审核数据源：

```http
POST /crawl/all
```

只抓部分源：

```http
POST /crawl/all
Content-Type: application/json

{
  "source_ids": ["mal-news", "miyoushe-ys"]
}
```

发现新站点候选源，但不会自动启用：

```http
POST /sources/discover
Content-Type: application/json

{
  "url": "https://example.com/"
}
```

米游社、萌娘百科、Bangumi、TapTap、GameKee 这类不一定有普通 RSS 的站点也可以走同一个入口。发现器会先匹配已注册的站点 Profile，再回退到 RSS/Sitemap/HTML 列表页发现：

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/sources/discover" `
  -ContentType "application/json; charset=utf-8" `
  -Body '{"url":"https://www.miyoushe.com/ys/"}'
```

当前已注册的米游社 Profile 包括 `https://www.miyoushe.com/ys/`、`https://www.miyoushe.com/bh3` 和 `https://www.miyoushe.com/sr`，发现后会生成 `miyoushe-feed` 候选源。

当前已注册的国内二次元/二游 Profile：

- `https://zh.moegirl.org.cn/`：生成 `moegirl-api` 候选源，走萌娘百科 MediaWiki API。
- `https://bangumi.tv/`：生成 `bangumi-api` 候选源，走 Bangumi 番组计划公开 API。
- `https://www.taptap.cn/app/168332`：生成 `taptap-feed` 候选源，抓取 TapTap 具体游戏页、介绍、攻略、论坛和活动页。根站 `https://www.taptap.cn/` 会先回退到原神游戏页候选。
- `https://www.gamekee.com/ba`：生成 `gamekee-feed` 候选源，走 GameKee wiki 公开接口。根站 `https://www.gamekee.com/` 会展开蔚蓝档案、原神攻略、NIKKE、崩坏3 四个常用 wiki 候选。

审核候选源：

```http
POST /sources/candidates/{id}/approve
POST /sources/candidates/{id}/approve?crawl=true
POST /sources/candidates/{id}/test-crawl
POST /sources/candidates/{id}/reject
```

`test-crawl` 只试抓候选源，不入库、不改变状态；脚本调用默认返回 JSON，包含 `would_save`、`errors` 和前 5 篇 `preview_documents`。从 `/debug/sources` 页面点击“试抓”时会返回可读的预览页，方便启用前检查标题、URL、来源和分类。`approve?crawl=true` 会在审核通过后立即正式抓取一遍，并把保存的文档增量写入当前索引。审核通过的候选源会生成 `candidate-{id}` 形式的 `source_id`。普通 RSS/Sitemap/List 候选默认按 `news` 分类，最多抓 50 篇详情页，`max_depth=0`，`delay_seconds=1.0`；站点 Profile 可以覆盖默认值，例如米游社候选使用 `category=anime`、`max_pages=20`、`source_score=0.95`，萌娘百科候选使用 `moegirl-api`，Bangumi 候选使用 `bangumi-api`。

自动定时抓取默认关闭。需要启用时设置：

```powershell
$env:ERFAIRY_CRAWL_SCHEDULER="1"
$env:ERFAIRY_CRAWL_INTERVAL_MINUTES="60"
$env:ERFAIRY_CRAWL_SOURCE_IDS="mal-news,ann-home"
uvicorn erfairy.web:app --reload
```

调度器默认每分钟醒一次，检查哪些数据源已经到达自己的下次抓取时间。全局默认间隔是 60 分钟；如果某个 source 或候选源配置了 `scheduler_interval_minutes`，则优先使用该源自己的间隔。

调试页面：

```http
GET /debug/sources
GET /debug/crawl-scheduler
```

`/debug/crawl-scheduler` 会展示全局调度状态，也会列出每个源的 `interval_minutes`、`last_run_at`、`next_run_at` 和最近一次结果。

新增通用采集策略：`rss-feed`、`sitemap-feed`、`html-list-feed`。它们会先从 RSS、Sitemap 或 HTML 列表页抽取详情页 URL，再复用现有 `AnimePageParser` 把详情页转成搜索文档。站点专用采集策略目前包括 `miyoushe-feed`、`moegirl-api`、`bangumi-api`、`gamekee-feed` 和 `taptap-feed`，由发现 Profile 自动写入候选源配置，后续新增非 RSS 站点时也按这个 Profile 机制扩展。

## 测试

```powershell
python -m pytest
```

搜索质量评测：

```powershell
python -m pytest tests/test_search_eval.py
```

当前测试覆盖普通搜索 JSON、浏览器结果页、调试搜索、索引状态、分词、排序、SearchIndex 接口、SQLite upsert、HTML 解析、开发写入接口开关、本地 HTML fixture 抓取、公开站点配置加载、抓取错误记录、meta 垂直字段解析、content hash 去重和标题相似度去重。
阶段 6/7 额外覆盖可切换索引后端、Redis ZSet 风格倒排结构、真实 Redis debug snapshot、完整增量索引更新、Meilisearch 专业后端、后端契约测试、候选源发现/试抓/审核、`/crawl/all`、自动调度器、GameKee/TapTap 专用抓取器和国内站点 Profile。最近一次全量回归为 `107 passed`。

## 学习路线

这个项目故意保持轻量：先把搜索引擎的完整闭环跑通，再逐步替换模块。

下一步建议继续收尾：

- 用 `/debug/sources` 和候选源试抓流程多做真实站点烟测，确认 RSS/Sitemap/API/Profile 四类来源的可用边界。
- 学透阶段 7 的持续采集链路：`/sources/discover`、`test-crawl`、`approve?crawl=true`、`/crawl/all` 和 `/debug/crawl-scheduler`。
- 继续观察搜索评测和 `/debug/search`，避免新增真实内容后排序质量退化。
- 如果后续仍漏抓关键内容，再为具体站点补分页游标或更细的专用 parser。
