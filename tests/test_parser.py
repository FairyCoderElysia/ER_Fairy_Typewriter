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
