# ER Fairy Typewriter

爱莉希雅的妖精打字机：一个用于学习搜索引擎完整链路的轻量二次元搜索引擎 MVP。

## 功能

- 小型爬虫：从种子 URL 抓取公开 HTML 页面，限制域名、深度、数量和请求频率。
- 页面解析：提取标题、正文、摘要、标签、来源、发布时间、图片和链接。
- 文档存储：使用 SQLite 保存结构化文档。
- 自研索引：使用中文/英文分词、字段权重、倒排索引和 TF-IDF/余弦相似度排序。
- Web 搜索：FastAPI API + 简洁搜索网页。

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

重建索引：

```http
POST /reindex
```

## 测试

```powershell
pytest
```

## 学习路线

这个项目故意保持轻量：先把搜索引擎的完整闭环跑通，再逐步替换模块。

下一步可以继续扩展：

- 把默认内存索引替换为 Redis 倒排索引。
- 增加站点适配器，让不同二次元资料站有更精准的解析规则。
- 加入新鲜度、来源可信度、点击反馈等排序特征。
- 增加图片搜索、角色别名词典和同义词扩展。
