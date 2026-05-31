# ER Fairy Typewriter 学习路线

这份文档用于配合代码学习搜索引擎全流程。建议不要一开始就追求复杂功能，而是按模块理解“数据如何进入系统，又如何被搜索出来”。

当前进度：阶段 7 持续采集体验已完成第一版。现在项目已经具备“fixture/公开站点/候选源 -> 爬虫 -> 解析 -> 领域词典补全 -> 去重存储 -> 增量索引 -> 可切换后端 -> 搜索 -> 调试解释 -> 评测”的完整闭环。学习重点不再是“能不能搜”，而是“数据如何受控进入系统、为什么这样排、为什么这样存、为什么这样持续更新、为什么这样更像真实搜索产品”。

## 1. 先跑通项目
目标：确认本地环境能启动、能搜索、能运行测试。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn erfairy.web:app --reload
```

打开 `http://127.0.0.1:8000`，搜索 `爱莉希雅`、`原神`、`芙莉莲`。搜索默认覆盖全部分类；如果想精细搜索，可以在结果页选择“动漫/游戏”“资讯”或“角色”。

如果浏览器搜索页能正常显示结果，再访问 `http://127.0.0.1:8000/debug/search?q=原神&category=anime`，观察同一次搜索背后的排序解释。

## 2. 理解文档模型
阅读顺序：

1. `erfairy/models.py`
2. `erfairy/sample_data.py`
3. `erfairy/store.py`
4. `erfairy/domain_terms.py`

重点问题：

- `SearchDocument` 为什么要包含 title、content、summary、tags？
- 为什么 SQLite 先用 URL 去重，再用 `content_hash` 和标题相似度合并重复页面？
- `crawl_runs` 和 `crawl_errors` 分别记录什么？为什么失败记录也值得持久化？
- 为什么存储层和索引层要分开？
- `aliases`、`entity_type`、`game_title`、`character_name`、`source_score`、`content_quality_score` 和 `content_quality_labels` 各自负责什么？
- 为什么词典补全要返回文档副本，而不是直接修改全局样例对象？

## 3. 理解分词和索引
阅读顺序：

1. `erfairy/tokenizer.py`
2. `erfairy/indexer.py`
3. `tests/test_tokenizer_indexer.py`

重点问题：

- 中文为什么需要 n-gram？
- 倒排索引为什么是 `term -> doc_id`？
- TF-IDF 如何降低常见词权重？
- 为什么标题命中比正文命中更重要？
- `SearchIndex` 接口为什么能让内存索引、Redis 索引和未来专业搜索引擎共用同一套搜索服务？
- `RedisZSetLikeIndex` 为什么用 `term -> [(score, doc_id)]` 模拟 Redis ZSet？
- 为什么阶段 6 先做可切换后端，再接真实 Redis 服务？

## 4. 理解搜索服务
阅读顺序：

1. `erfairy/search.py`
2. `erfairy/web.py`
3. `erfairy/templates/home.html`
4. `erfairy/templates/results.html`

重点问题：

- `/search` 如何同时支持 HTML 和 JSON？
- 为什么 `/search` 默认用 `category=all` 搜索全部分类，而精细筛选才传 `anime/news/character`？
- 摘要高亮为什么要先 `html.escape()`？
- 分页里的 `offset` 是如何计算的？

## 5. 理解爬虫和解析
阅读顺序：

1. `erfairy/crawler.py`
2. `erfairy/parser.py`
3. `erfairy/sources.py`
4. `erfairy/source_discovery.py`
5. `erfairy/generic_feeds.py`
6. `erfairy/miyoushe.py`
7. `erfairy/api_feeds.py`
8. `erfairy/cn_site_feeds.py`
9. `erfairy/crawl_scheduler.py`
10. `sources.example.json`
11. `tests/test_crawler.py`
12. `tests/test_parser.py`
13. `tests/test_sources.py`
14. `tests/test_source_discovery.py`
15. `tests/test_crawl_scheduler.py`

重点问题：

- `max_pages`、`max_depth`、`delay_seconds` 分别防止什么问题？
- 为什么要删除 `script`、`style`、`noscript`、`svg`？
- `urljoin()` 如何把相对链接转成绝对链接？
- `CrawlResult.documents` 和 `CrawlResult.errors` 为什么要分开返回？
- `source_id` / `source_name` 如何从 `sources.example.json` 转换成 `CrawlConfig`？
- 为什么 PowerShell 调用时更推荐 ASCII 的 `source_id`，而不是中文 `source_name`？
- `sources.example.json` 里的 `source_score` 如何补进抓取文档？
- MyAnimeList、Anime News Network、FGO 为什么要先抽列表链接，再抓详情页？
- 米游社这类前端应用为什么不能只解析入口 HTML，而要通过帖子流接口生成多篇文档？
- 米游社为什么要同时尝试最新、精品和热门流，而不是只抓最新流？
- 为什么文章流源默认 `max_pages=50`，米游社源默认 `max_pages=20`？
- GameKee 和 TapTap 为什么需要专用抓取器，而不是只依赖通用 `html-list-feed`？
- 为什么社区站点不直接丢弃日常帖，而是用 `content_quality_score` 做评分降权？
- `/sources/discover` 为什么只生成候选源，而不是自动启用新站点？
- 候选源的 `config_json` 为什么要保存 `parse_strategy`、`max_pages`、`category` 和 `source_score`？
- Wiki 候选源为什么还要保存 `wiki_game_title` 和 `wiki_game_aliases`，而不是只用 URL alias？
- `/debug/sources` 为什么要分页，每页 50 条时 `limit`、`offset` 和 `page_count` 是如何计算的？
- 自动调度器为什么默认关闭，但默认间隔从 6 小时改为 1 小时？
- `scheduler_interval_minutes` 为什么要支持按源覆盖？
- `category=auto` 如何根据 URL、标题、摘要、标签和 `entity_type` 推断 `news`、`character` 或 `anime`？
- 为什么公开站点默认使用 `max_depth=0` 和较小的 `max_pages`？

本地 fixture 抓取示例：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/crawl" `
  -ContentType "application/json" `
  -Body '{"seeds":["file:///F:/search_Engine/tests/fixtures/crawl_site/index.html"],"max_pages":10,"max_depth":1,"delay_seconds":0}'
```

公开站点配置抓取示例：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/crawl" `
  -ContentType "application/json" `
  -Body '{"source_id":"mal-news"}'
```

把 `source_id` 换成 `ann-home` 或 `fgo-news`，就可以分别抓 Anime News Network 和 FGO 官方新闻。它们会一次抓取多篇详情页，而不是只保存主页面。

米游社官方社区帖子流抓取示例：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/crawl" `
  -ContentType "application/json" `
  -Body '{"source_id":"miyoushe-ys"}'
```

还可以把 `source_id` 换成 `miyoushe-bh3` 或 `miyoushe-sr`。

## 6. 学习调试搜索
阶段二已经新增 `/debug/search`，建议这样学习：

```http
GET /debug/search?q=原神&category=anime
```

浏览器打开时会看到 HTML 调试页，分区展示 tokens、missing terms、Top 结果、TF-IDF、boost、final score 和字段贡献。脚本或自动化测试需要原始结构时，带上 `Accept: application/json` 即可继续拿 JSON。

观察：

- `tokens`：查询被分成了哪些词。
- `missing_terms`：哪些词没有命中文档。
- `field_matches`：词命中了标题、标签、摘要还是正文。
- `tfidf_score`：统计相关性分数。
- `boost_score`：完整命中带来的业务加分。
- `final_score`：最终排序分数。

阶段 4/5 之后建议额外观察：

- `aliases`：是否帮助中英混合别名召回。
- `entity_type`：是否帮助区分角色页、作品页、资讯页。
- `game_title`：是否帮助角色和作品关联更稳定。
- `character_name`：是否让角色名精确命中更靠前。
- `source_score`：是否只做轻微来源加分，而没有盖过相关性。
- `content_quality_score` / `content_quality_labels`：是否让官方、热门、精品、攻略、养成、活动内容前移，让日常帖后沉。
- `published_at` / `crawled_at`：新闻意图查询下是否让近期资讯更靠前。
- `content_hash`：是否帮助同正文不同 URL 的页面合并。
- 标题相似度：是否帮助标题几乎相同的重复页面合并。
- 自动分类：公开新闻页是否进入 `news`，角色资料页是否进入 `character`。

再访问：

```http
GET /debug/index
```

观察：

- `document_count`：当前索引里的文档数。
- `term_count`：当前索引里的 token 数。
- `posting_count`：倒排索引里的 term-doc 关系数量。
- `last_rebuilt_at`：最近一次重建索引的时间。
- `backend`：当前索引后端，例如 `memory`、`redis-zset-like` 或 `redis`。

如果想切换到 Redis ZSet 风格教学后端：

```powershell
$env:ERFAIRY_INDEX_BACKEND="redis-zset"
uvicorn erfairy.web:app --reload
```

然后访问：

```http
GET /debug/index
```

观察 `backend` 是否变为 `redis-zset-like`。这个后端不需要外部 Redis 服务，它用于学习“Redis ZSet 倒排表长什么样，以及同一批文档能否在不同后端下保持搜索结果一致”。

如果想接入真实 Redis：

```powershell
docker run --name erfairy-redis -p 6379:6379 -d redis:7
$env:ERFAIRY_INDEX_BACKEND="redis"
$env:ERFAIRY_REDIS_URL="redis://localhost:6379/0"
$env:ERFAIRY_REDIS_PREFIX="erfairy"
uvicorn erfairy.web:app --reload
```

再次访问 `/debug/index`，观察 `backend` 是否变为 `redis`。当前真实 Redis 后端把倒排 postings 写入 Redis ZSet，文档对象和字段解释缓存仍保留在 Python 进程内，方便继续学习排序和解释链路。

再打开 Redis 结构可视化页面：

```http
GET /debug/redis
GET /debug/redis?term=genshin
```

重点观察 `erfairy:terms`、`erfairy:postings:<term>` 和 `erfairy:meta`。其中 postings 表示“某个 token 命中了哪些 doc_id，以及权重是多少”。

如果想切换到 Meilisearch 专业搜索后端：

```powershell
$env:ERFAIRY_INDEX_BACKEND="meilisearch"
$env:ERFAIRY_MEILI_URL="http://localhost:7700"
$env:ERFAIRY_MEILI_MASTER_KEY=""
$env:ERFAIRY_MEILI_INDEX="erfairy_documents"
uvicorn erfairy.web:app --reload
```

再次访问 `/debug/index`，观察 `backend` 是否变为 `meilisearch`。这个后端由 Meilisearch 负责召回候选，再由项目自己的字段权重、别名、垂直 boost 和新鲜度规则做二次排序。学习重点是比较“自研 TF-IDF/Redis postings”和“专业搜索引擎召回 + 本地垂直重排”的差异。

抓取新内容时，`/crawl` 现在会返回：

```json
{
  "index_update": "incremental",
  "indexed": 3
}
```

这表示本次保存的文档已通过 `SearchIndex.upsert_many()` 增量写入索引。同一个 `doc_id` 被更新时，旧 token postings 会先被移除，再写入新 token postings。

删除文档时可以调用：

```http
DELETE /documents/{doc_id}
```

这个接口会删除 SQLite 里的文档，并通过 `SearchIndex.delete_many()` 增量移除索引 postings。`/reindex` 仍然保留全量重建，用作调试和兜底。

如果想复盘抓取过程，打开：

```http
GET /debug/crawls
```

这个页面会列出最近的 `crawl_runs`，并展开每次运行的 `crawl_errors`。当你发现 `/crawl` 返回 `errors > 0` 时，优先看这里，而不是直接猜 parser 或网络哪里坏了。

注意：`/search` 默认搜索全部分类。抓取新闻源后，如果只想看资讯结果，可以使用：

```http
GET /search?q=Anime&category=news
```

## 7. 用评测集学习调参
当你修改分词、字段权重、boost 或别名词典时，先运行测试：

```powershell
python -m pytest tests/test_search_eval.py
```

观察：

- Top1 Accuracy 是否下降。
- Top3 Accuracy 是否稳定。
- Zero Result Rate 是否升高。

如果某次修改让一个查询变好、另一个查询变差，优先打开 `/debug/search` 看分数来源，而不是凭感觉继续调。

## 8. 理解开发接口边界
`/crawl` 和 `/reindex` 会修改本地数据，适合学习和开发阶段使用。为了避免部署时误触发写操作，项目增加了 `ERFAIRY_DEV_MUTATIONS` 开关。

验证关闭效果：

```powershell
$env:ERFAIRY_DEV_MUTATIONS="0"
uvicorn erfairy.web:app --reload
```

然后请求：

```http
POST /crawl
POST /reindex
```

观察返回内容是否提示“开发写入接口已关闭”。这一步对应的代码在 `erfairy/web.py`，测试在 `tests/test_api.py`。

重点问题：

- 为什么搜索接口可以公开读数据，而抓取和重建索引接口需要开关？
- 为什么环境变量适合做本地教学项目的第一版开关？
- 如果未来部署到公网，除了环境变量，还可以增加哪些保护？
- 为什么 `source_score` 应该是来源质量的轻微加分，而不是主排序因素？
- 为什么 `content_quality_score` 是单篇内容价值，而不是站点整体可信度？
- 为什么 `category` 支持自动判断，但仍允许手动覆盖？

## 9. 理解回归测试
这轮新增了 API 和页面级测试，建议阅读：

1. `tests/test_api.py`
2. `tests/test_search_eval.py`
3. `tests/test_crawler.py`
4. `tests/test_parser.py`
5. `tests/test_sources.py`
6. `tests/fixtures/search_eval.json`

重点问题：

- 为什么 `/search` 同时要测试 JSON 和 HTML？
- 为什么 HTML 模板中的普通注释也不能随意写 Jinja2 语法？
- 搜索评测为什么允许 Top1 不是 100%，但要求 Top3 和零结果率更稳定？
- 为什么要测试 `InMemoryTfIdfIndex` 是 `SearchIndex` 的实现？
- 为什么要测试关闭 `ERFAIRY_DEV_MUTATIONS` 后 `/crawl` 和 `/reindex` 不再执行写操作？
- 为什么要测试本地 fixture 抓取、公开源配置加载、自动分类和标题相似度去重？

## 10. 阶段 6/7 怎么继续学

阶段 6 已经完成索引后端对照、真实 Redis、Meilisearch、完整增量索引和多后端 debug；阶段 7 已经完成第一轮前端调试体验与持续采集体验。下一步建议按这个顺序继续：

1. 先看 `aliases`、`entity_type`、`game_title`、`character_name`、`source_score`、`content_quality_score` 在 `erfairy/models.py` 和 `erfairy/indexer.py` 里的流动。
2. 再看 `content_hash`、canonical URL 和标题相似度在 `erfairy/parser.py` 与 `erfairy/store.py` 里的去重链路。
3. 再用 `/debug/search` 对照每个字段的分数贡献。
4. 再用 `tests/test_search_eval.py` 看调权重后哪条查询变好、哪条查询变差。
5. 再切换 `ERFAIRY_INDEX_BACKEND=redis-zset`，对照 `memory` 和 `redis-zset-like` 的 `/debug/index`。
6. 再启动真实 Redis，切换 `ERFAIRY_INDEX_BACKEND=redis`，观察 Redis ZSet postings 与搜索结果是否一致。
7. 再打开 `/debug/redis`，用不同 token 查看 Redis key、terms 和 postings。
8. 再观察 `/crawl` 返回的 `index_update=incremental`，理解“抓一批、更新一批索引”和全量 `/reindex` 的区别。
9. 再用 `DELETE /documents/{doc_id}` 删除一篇测试文档，观察搜索结果和 `/debug/redis` postings 是否同步消失。
10. 再打开 `/debug/crawls`，理解 `crawl_runs` / `crawl_errors` 如何帮助定位抓取失败。
11. 再切换 `ERFAIRY_INDEX_BACKEND=meilisearch`，观察专业搜索引擎召回和自研索引有什么不同。
12. 打开 `/debug/compare-index?q=原神&backends=memory,redis-zset,meilisearch`，把 memory / redis / meilisearch 的同一查询结果放在一起对照。
13. 打开 `/debug` 总览页，熟悉搜索、索引、Redis、抓取、候选源和调度器这些调试入口如何互相补位。
14. 用 `/sources/discover` 尝试一个 RSS/Sitemap 站点，再用 `/sources/candidates/{id}/test-crawl` 试抓，确认 `would_save`、`errors` 和 `preview_documents`。
15. 用米游社、萌娘百科、Bangumi、TapTap 或 GameKee 再试一次 Profile 型候选源，观察 `source_type` 和 `config_json` 与普通 RSS 候选有什么不同。
16. 打开 `/debug/crawl-scheduler`，理解全局 interval、每源 `scheduler_interval_minutes`、`last_run_at` 和 `next_run_at` 如何决定下一次自动抓取。
17. 打开米游社或 TapTap 的试抓预览，观察 `official`、`hot`、`good`、`guide`、`daily-chat` 等质量标签如何出现。
18. 新增真实内容后运行 `python -m pytest tests/test_search_eval.py`，确认 Top1/Top3 不因为数据增多而退化。
