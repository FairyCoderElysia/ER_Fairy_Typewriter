# ER Fairy Typewriter 学习路线

这份文档用于配合代码学习搜索引擎全流程。建议不要一开始就追求复杂功能，而是按模块理解“数据如何进入系统，又如何被搜索出来”。

当前进度：阶段 6 已开始。现在项目已经具备“fixture/公开站点 -> 爬虫 -> 解析 -> 领域词典补全 -> 去重存储 -> 可切换索引 -> 搜索 -> 调试解释 -> 评测”的完整闭环。学习重点不再是“能不能搜”，而是“数据如何受控进入系统、为什么这样排、为什么这样存、为什么这样更像真实搜索产品”。

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
- `aliases`、`entity_type`、`game_title`、`character_name`、`source_score` 各自负责什么？
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
4. `sources.example.json`
5. `tests/test_crawler.py`
6. `tests/test_parser.py`
7. `tests/test_sources.py`

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
- 为什么文章流源默认 `max_pages=20`，米游社源默认 `max_pages=5`？
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
- `backend`：当前索引后端，例如 `memory` 或 `redis-zset-like`。

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

## 10. 阶段 6 怎么继续学

阶段 5 已经把二次元垂直化和可控数据采集闭环打通，阶段 6 已经开始做索引后端对照。下一步建议按这个顺序继续：

1. 先看 `aliases`、`entity_type`、`game_title`、`character_name`、`source_score` 在 `erfairy/models.py` 和 `erfairy/indexer.py` 里的流动。
2. 再看 `content_hash`、canonical URL 和标题相似度在 `erfairy/parser.py` 与 `erfairy/store.py` 里的去重链路。
3. 再用 `/debug/search` 对照每个字段的分数贡献。
4. 再用 `tests/test_search_eval.py` 看调权重后哪条查询变好、哪条查询变差。
5. 再切换 `ERFAIRY_INDEX_BACKEND=redis-zset`，对照 `memory` 和 `redis-zset-like` 的 `/debug/index`。
6. 最后再去补抓取状态页面、真实 Redis 后端和专业搜索引擎对照。
