from erfairy.parser import AnimePageParser


def test_parser_extracts_document_and_links():
    html = """
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

    document, links = AnimePageParser().parse(html, "https://example.com/wiki/role")

    assert document.title == "测试角色"
    assert document.summary == "角色简介"
    assert "动漫" in document.tags
    assert "https://example.com/next" in links
