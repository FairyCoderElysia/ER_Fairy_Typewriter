"""HTML 解析器测试。

项目简介：
    parser.py 负责把 HTML 转成 SearchDocument；这个测试验证标题、摘要、标签和链接抽取是否正确。

技术栈：
    pytest、BeautifulSoup 间接测试、HTML fixture 字符串。

学习目标：
    1. 理解如何用小段 HTML 模拟真实网页。
    2. 理解 parser 的输入输出：HTML + URL -> 文档 + 链接列表。

知识点与免费文档：
    - pytest: https://docs.pytest.org/en/stable/
    - BeautifulSoup 搜索文档树: https://www.crummy.com/software/BeautifulSoup/bs4/doc/#searching-the-tree
"""

from erfairy.parser import AnimePageParser  # 被测对象：HTML 解析器。


def test_parser_extracts_document_and_links():
    """验证解析器能抽取文档字段和页面链接。"""

    html = """  <!-- 构造一个最小但完整的 HTML 页面。 -->
    <html>
      <head>
        <title>测试角色</title>
        <meta name="description" content="角色简介">
        <meta name="keywords" content="动漫,角色">
      </head>
      <body>
        <main><h1>测试角色</h1><p>这是角色正文。</p></main>
        <a href="/next">下一页</a>
      </body>
    </html>
    """

    document, links = AnimePageParser().parse(html, "https://example.com/wiki/role")  # 解析 HTML。

    assert document.title == "测试角色"  # 应优先读取 <title>。
    assert document.summary == "角色简介"  # 应读取 meta description。
    assert "动漫" in document.tags  # 应从 meta keywords 中提取标签。
    assert "https://example.com/next" in links  # 相对链接应被 urljoin 转成绝对链接。


def test_parser_extracts_stage5_vertical_meta_and_content_hash():
    """验证本地 fixture/站点适配器可以通过 meta 写入垂直字段。"""

    html = """
    <html>
      <head>
        <meta name="erfairy:aliases" content="雷神,影,Raiden Shogun">
        <meta name="erfairy:entity_type" content="character">
        <meta name="erfairy:game_title" content="原神">
        <meta name="erfairy:character_name" content="雷电将军">
        <meta name="erfairy:source_score" content="0.88">
      </head>
      <body>
        <article><h1>雷电将军</h1><p>雷电将军是稻妻角色。</p></article>
      </body>
    </html>
    """

    document, _links = AnimePageParser().parse(html, "https://example.com/raiden")

    assert document.aliases == ["雷神", "影", "Raiden Shogun"]
    assert document.entity_type == "character"
    assert document.game_title == "原神"
    assert document.character_name == "雷电将军"
    assert document.source_score == 0.88
    assert document.content_hash


def test_parser_auto_detects_news_category():
    html = """
    <html>
      <head>
        <title>Anime News</title>
        <meta name="description" content="Latest anime news and event updates">
      </head>
      <body>
        <main><p>News and update list.</p></main>
      </body>
    </html>
    """

    document, _links = AnimePageParser().parse(html, "https://example.com/news", category="auto")

    assert document.category == "news"


def test_parser_auto_detects_character_category_from_meta():
    html = """
    <html>
      <head>
        <title>雷电将军资料</title>
        <meta name="erfairy:entity_type" content="character">
      </head>
      <body>
        <article><p>角色资料。</p></article>
      </body>
    </html>
    """

    document, _links = AnimePageParser().parse(html, "https://example.com/raiden", category="auto")

    assert document.category == "character"


def test_parser_manual_category_overrides_auto_detection():
    html = """
    <html>
      <head><title>Anime News</title></head>
      <body><main><p>Latest anime news.</p></main></body>
    </html>
    """

    document, _links = AnimePageParser().parse(html, "https://example.com/news", category="anime")

    assert document.category == "anime"


def test_parser_enriches_miyoushe_community_shell_by_url():
    html = """
    <html>
      <head>
        <title>米游社</title>
        <meta name="description" content="米游社是米哈游miHoYo旗下游戏玩家社区">
        <meta name="Keywords" content="米游社,米哈游社区">
      </head>
      <body><div id="__nuxt"></div></body>
    </html>
    """

    document, _links = AnimePageParser().parse(html, "https://www.miyoushe.com/sr", category="auto")

    assert document.title == "崩坏：星穹铁道 米游社官方社区"
    assert document.entity_type == "work"
    assert document.game_title == "崩坏：星穹铁道"
    assert "崩铁" in document.aliases
    assert "米游社" in document.tags
    assert document.category == "anime"
    assert "开拓者互动" in document.summary
