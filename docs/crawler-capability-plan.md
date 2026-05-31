# 爬虫能力增强计划：自动更新 + 半自动站点接入 + 通用 Feed/List 解析

## Summary

下一步不把项目直接升级成开放式大爬虫，而是做一个可控的“持续采集系统”：

- 已配置站点可以自动定时抓取，减少手动调用 `/crawl`。
- 新站点先自动发现 RSS/Sitemap/列表页候选，进入待审核状态，确认后才启用。
- 优先支持 RSS、Sitemap、HTML 列表页，不优先做 JS 动态站点和全网开放探索。

## Key Changes

### 新增爬虫编排层

- 抽出 `run_crawl_for_source(source_id)`，让手动 `/crawl`、定时任务、批量抓取共用同一套保存、错误记录、增量索引逻辑。
- 新增 `POST /crawl/all`：按已启用数据源批量抓取，返回每个 source 的 `saved`、`errors`、`run_id`。
- 增加并发锁，避免同一时间多个批量抓取任务互相覆盖。

### 新增自动定时抓取

- 在 FastAPI `lifespan` 中启动轻量后台循环，不引入复杂任务队列。
- 环境变量：
  - `ERFAIRY_CRAWL_SCHEDULER=1` 开启。
  - `ERFAIRY_CRAWL_INTERVAL_MINUTES=60` 默认 1 小时。
  - `ERFAIRY_CRAWL_SOURCE_IDS=all` 或留空表示自动抓取全部源；`mal-news,ann-home,...` 可选限制自动抓取源。
- 新增 `/debug/crawl-scheduler` 页面/JSON，展示是否启用、上次运行、下次运行、最近批量结果。

### 新增半自动站点接入

- 新增 SQLite 表 `source_candidates`，保存发现到的候选源：`url`、`source_type`、`title`、`status`、`reason`、`config_json`、`discovered_at`、`approved_at`。
- 新增 `POST /sources/discover`：输入一个站点根 URL，尝试发现：
  - 已注册站点 Profile，例如米游社 `ys`、`bh3`、`sr`、萌娘百科、Bangumi、TapTap、GameKee、Biligame Wiki
  - `<link rel="alternate" type="application/rss+xml">`
  - 常见 `/rss`、`/feed`、`/atom.xml`
  - `/sitemap.xml`
  - HTML 列表页中的文章链接候选
- 新增 `POST /sources/candidates/{id}/approve`：把候选转成可抓取 source 配置。
- 新增 `POST /sources/candidates/{id}/reject`：拒绝候选，避免重复提示。
- 新增 `/debug/sources` 页面查看已配置源、候选源、启用状态和最近抓取状态。
- 新增 `POST /sources/candidates/{id}/test-crawl`：试抓候选源但不入库、不改变审核状态。
- `POST /sources/candidates/{id}/approve?crawl=true` 支持审核通过后立即正式抓取一遍。

### 新增通用 RSS/Sitemap/List 抓取器

- `rss-feed`：用标准库 XML 解析 RSS/Atom 条目，抽取链接后交给现有 `AnimePageParser` 解析正文。
- `sitemap-feed`：解析 sitemap URL 列表，按最近/靠前 URL 抓取详情页。
- `html-list-feed`：用通用链接评分规则找文章链接，不再为每个站点写硬编码 profile。
- 保留现有 `article-feed`、`miyoushe-feed`，作为已知站点高质量适配器。

## Public Interfaces

新增 API：

- `POST /crawl/all`
- `POST /sources/discover`
- `POST /sources/candidates/{id}/approve`
- `POST /sources/candidates/{id}/approve?crawl=true`
- `POST /sources/candidates/{id}/test-crawl`
- `POST /sources/candidates/{id}/reject`
- `GET /debug/crawl-scheduler`
- `GET /debug/sources`

新增 `parse_strategy`：

- `rss-feed`
- `sitemap-feed`
- `html-list-feed`

兼容性：

- 保持现有 `/crawl`、`source_id`、`source_name` 行为兼容。

## Test Plan

### 单元测试

- RSS fixture 能发现多篇文章链接。
- Sitemap fixture 能发现 URL 并限制 `max_pages`。
- HTML 列表页 fixture 能按链接评分挑出文章链接。
- `source_candidates` approve/reject 状态流转正确。
- 自动调度关闭时不启动后台任务。
- 批量抓取遇到单个 source 失败时继续处理其他 source。

### API 测试

- `/crawl/all` 返回每个 source 的抓取结果。
- `/sources/discover` 写入 pending candidates。
- `/sources/candidates/{id}/test-crawl` 能返回 `would_save`、`preview_documents`，且不持久化文档。
- `/sources/candidates/{id}/approve?crawl=true` 能触发正式抓取、入库和增量索引。
- `/debug/sources` HTML/JSON 可查看候选和已启用源。
- `/debug/crawl-scheduler` HTML/JSON 可查看调度状态。

### 回归测试

- `python -m pytest`
- 搜索评测 Top1/Top3 不下降。
- 现有 6 个站点仍可通过原 `source_id` 抓取。

## Assumptions

- 默认不做开放域名递归探索，所有新站点必须经过候选审核。
- 默认不接 JS 动态渲染站点，后续如需要再单独接 Playwright/browser 渲染。
- 自动抓取默认关闭，需要设置 `ERFAIRY_CRAWL_SCHEDULER=1` 才启用。
- 第一版优先做“轻量后台循环”，暂不引入 Celery、APScheduler 或外部任务队列。

## Current Implementation Status

当前已落地第一版：

- 已新增通用 `rss-feed`、`sitemap-feed`、`html-list-feed` 抓取器。
- 已将发现器重构为 Profile 注册结构，普通 RSS/Sitemap/List 由 `GenericWebDiscoveryProfile` 负责，米游社由 `MiyousheDiscoveryProfile` 负责。
- 已新增国内二次元/二游站点 Profile：萌娘百科 `moegirl-api`、Bangumi `bangumi-api`、TapTap `taptap-feed`、GameKee `gamekee-feed`、Biligame Wiki `biligame-wiki`。
- 已新增 API 型抓取器，能把萌娘百科 MediaWiki API 和 Bangumi 番组计划 API 转成搜索文档。
- 已新增 TapTap/GameKee/Biligame Wiki 专用抓取器：TapTap 抓具体 app 页及介绍/攻略/论坛/活动子页；GameKee 通过 wiki 公开接口抓最近更新内容；Biligame Wiki 通过 MediaWiki API 抓最近更新页面正文。
- GameKee 和 Biligame Wiki 根站发现已支持“内置推荐源 + 首页热门/推荐区域发现”组合：常用分区继续稳定推荐，首页热门区域最多解析 30 个游戏 Wiki 候选；如果热门区域解析不到，再回退到页面前 30 个像 Wiki 分区的链接，避免一次生成上千个低活跃候选源。
- 候选源 `config_json` 已记录 `discovery_origin`、`discovery_label`、`discovery_site`，用于区分 `内置推荐源`、`首页解析发现` 和 `通用 RSS/Sitemap 发现`。
- Wiki 类候选源 `config_json` 已记录 `wiki_game_title` 和 `wiki_game_aliases`；GameKee/Biligame Wiki 文档会把分区 alias、规范游戏名、别名和页面分类写入 `tags`，并把规范游戏名写入 `game_title`，修复非原神 Wiki 误标为原神以及中文游戏名无法通过 tags 命中的问题。
- 已新增社区内容质量评分：文档会保存 `content_quality_score` 和 `content_quality_labels`，搜索排序用轻量加分让高价值社区内容前移。
- 米游社已从单一最新流升级为最新/精品/热门多路采样，合并去重后按内容质量分和发布时间截取 `max_pages`。
- TapTap 已对 app 主页面、介绍、攻略、论坛、活动页接入质量评分，攻略和活动页会优先获得更高质量分。
- 已新增候选源发现、审核和拒绝 API。
- 已支持候选源试抓：`POST /sources/candidates/{id}/test-crawl`。
- 已支持候选源启用前预览：脚本调用返回 JSON，`/debug/sources` 页面点击试抓返回 HTML 预览页，展示本次试抓得到的候选文档。
- 已支持启用并立即抓取：`POST /sources/candidates/{id}/approve?crawl=true`。
- 已支持 `/debug/sources` 按候选源状态和发现来源筛选、按 `page` 分页，每页 50 条；批量启用/批量拒绝只作用于当前页勾选的候选源。
- 已新增 `source_candidates` 表，并用 `config_json` 保存候选源默认抓取配置。
- 已支持对 `https://www.miyoushe.com/ys/`、`https://www.miyoushe.com/bh3`、`https://www.miyoushe.com/sr` 执行 `/sources/discover`，生成 `miyoushe-feed` 候选源。
- 米游社候选源审核后仍使用 `candidate-{id}`，抓取时会根据 `entry_url` 解析到原神、崩坏3或星穹铁道对应 profile。
- 已新增 `/crawl/all` 批量抓取接口。
- 已新增轻量调度器和 `/debug/crawl-scheduler`。
- 已将自动调度默认间隔从 6 小时调整为 1 小时，并支持每个 source 通过 `scheduler_interval_minutes` 覆盖。
- 调度器已改为每分钟检查到期 source，`/debug/crawl-scheduler` 会显示每源 `last_run_at`、`next_run_at`、`interval_minutes` 和最近结果。
- 已新增 `/debug/sources`，并提供试抓、启用、启用并抓取、拒绝操作入口。
- 已补充测试并通过 `python -m pytest`。

候选源审核通过后会转换成临时 source 配置：

- `source_id = candidate-{id}`
- `max_pages = 50`
- `max_depth = 0`
- `delay_seconds = 1.0`
- `category = news`
- `source_score = 0.7`
- `scheduler_interval_minutes = 60`

普通 RSS/Sitemap/List 候选使用以上默认值。米游社候选使用站点专用默认值：

- `parse_strategy = miyoushe-feed`
- `max_pages = 20`
- `max_depth = 0`
- `delay_seconds = 1.0`
- `category = anime`
- `source_score = 0.95`
- `quality_profile = miyoushe-community`
- `quality_mode = score`
- `scheduler_interval_minutes = 60`

国内二次元/二游 Profile 默认值：

- 萌娘百科：`parse_strategy = moegirl-api`，`category = anime`，`max_pages = 50`，`source_score = 0.9`
- Bangumi：`parse_strategy = bangumi-api`，`category = anime`，`max_pages = 50`，`source_score = 0.88`
- TapTap：`parse_strategy = taptap-feed`，`category = game`，`max_pages = 50`，`source_score = 0.78`，`quality_profile = taptap-community`
- GameKee：`parse_strategy = gamekee-feed`，`category = game`，`max_pages = 50`，`source_score = 0.84`
- Biligame Wiki：`parse_strategy = biligame-wiki`，`category = game`，`max_pages = 50`，`source_score = 0.86`

## Smoke Test Record

2026-05-30 手动用 `https://www.otakunews.com/` 验证半自动接入流程：

- `POST /sources/discover` 发现 8 个候选源，包含 RSS、Sitemap 和 HTML 列表页。
- `POST /sources/candidates/5/test-crawl` 返回 `would_save=20`、`errors=0`，未持久化文档。
- `POST /sources/candidates/5/approve?crawl=true` 将 `https://www.otakunews.com/rss/rss-uk.xml` 启用为 `candidate-5`，正式抓取保存 20 篇，`run_id=28`，`errors=0`。
- `POST /crawl/all` 限定 `source_ids=["candidate-5"]` 时成功复用批量抓取入口，`saved=20`、`errors=0`。
- `/search?q=Otaku&source=www.otakunews.com` 可搜索到新入库内容。
- `/debug/sources`、`/debug/crawl-scheduler`、`/debug/crawls` 均返回 200。

2026-05-30 追加验证国内站点 Profile、专用抓取器和调度器覆盖量：

- GameKee `https://www.gamekee.com/ba` 通过 `/sources/discover` 生成 `gamekee-feed` 候选源，`test-crawl` 返回 `would_save=20`、`errors=0`，预览能看到 wiki 最近更新内容。
- TapTap `https://www.taptap.cn/app/168332` 通过 `/sources/discover` 生成 `taptap-feed` 候选源，`test-crawl` 返回 `would_save=5`、`errors=0`，预览包含游戏页、介绍、攻略、论坛和活动页。
- `/debug/crawl-scheduler` JSON 返回 200，当前全局 `interval_minutes=60`，并展示每个源的 `interval_minutes`、`last_run_at`、`next_run_at` 和最近结果。
- 2026-05-31 Wiki 候选分页/热门发现/游戏名规范化改造后，相关回归通过：`python -m compileall erfairy`、`python -m pytest tests/test_wiki_profiles.py tests/test_cn_site_feeds.py tests/test_source_discovery.py tests/test_sources.py tests/test_tokenizer_indexer.py tests/test_crawl_scheduler.py -q` 为 `64 passed`，候选源分页和审核相关 API 定向测试为 `5 passed`。当前本地全量 `python -m pytest` 因多次启动 FastAPI 测试客户端并读取较大的本地 SQLite 数据，10 分钟超时，后续建议使用隔离测试数据库再恢复全量耗时基线。
- 搜索评测保持稳定：23 个用例 Top1 100%、Top3 100%、Zero Result Rate 0。
