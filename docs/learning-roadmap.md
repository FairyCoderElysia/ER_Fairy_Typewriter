# ER Fairy Typewriter 学习路线

这份文档用于配合代码学习搜索引擎全流程。建议不要一开始就追求复杂功能，而是按模块理解“数据如何进入系统，又如何被搜索出来”。

## 1. 先跑通项目
目标：确认本地环境能启动、能搜索、能运行测试。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn erfairy.web:app --reload
```

打开 `http://127.0.0.1:8000`，搜索 `爱莉希雅`、`原神`、`芙莉莲`。

如果浏览器搜索页能正常显示结果，再访问 `http://127.0.0.1:8000/debug/search?q=原神&category=anime`，观察同一次搜索背后的排序解释。

## 2. 理解文档模型
阅读顺序：

1. `erfairy/models.py`
2. `erfairy/sample_data.py`
3. `erfairy/store.py`

重点问题：

- `SearchDocument` 为什么要包含 title、content、summary、tags？
- 为什么 SQLite 用 URL 去重？
- 为什么存储层和索引层要分开？

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

## 4. 理解搜索服务
阅读顺序：

1. `erfairy/search.py`
2. `erfairy/web.py`
3. `erfairy/templates/home.html`
4. `erfairy/templates/results.html`

重点问题：

- `/search` 如何同时支持 HTML 和 JSON？
- 摘要高亮为什么要先 `html.escape()`？
- 分页里的 `offset` 是如何计算的？

## 5. 理解爬虫和解析
阅读顺序：

1. `erfairy/crawler.py`
2. `erfairy/parser.py`
3. `tests/test_parser.py`

重点问题：

- `max_pages`、`max_depth`、`delay_seconds` 分别防止什么问题？
- 为什么要删除 `script`、`style`、`noscript`、`svg`？
- `urljoin()` 如何把相对链接转成绝对链接？

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

再访问：

```http
GET /debug/index
```

观察：

- `document_count`：当前索引里的文档数。
- `term_count`：当前索引里的 token 数。
- `posting_count`：倒排索引里的 term-doc 关系数量。
- `last_rebuilt_at`：最近一次重建索引的时间。

## 7. 用评测集学习调参
当你修改分词、字段权重、boost 或别名词典时，先运行测试：

```powershell
pytest tests/test_search_eval.py
```

观察：

- Top1 Accuracy 是否下降。
- Top3 Accuracy 是否稳定。
- Zero Result Rate 是否升高。

如果某次修改让一个查询变好、另一个查询变差，优先打开 `/debug/search` 看分数来源，而不是凭感觉继续调。

## 8. 理解回归测试
这轮新增了 API 和页面级测试，建议阅读：

1. `tests/test_api.py`
2. `tests/test_search_eval.py`
3. `tests/fixtures/search_eval.json`

重点问题：

- 为什么 `/search` 同时要测试 JSON 和 HTML？
- 为什么 HTML 模板中的普通注释也不能随意写 Jinja2 语法？
- 搜索评测为什么允许 Top1 不是 100%，但要求 Top3 和零结果率更稳定？
