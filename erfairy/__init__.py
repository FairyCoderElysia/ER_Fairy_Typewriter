"""ER Fairy Typewriter 搜索引擎包。

项目简介：
    这是一个用于学习搜索引擎完整链路的轻量 Python 包。

开发目的：
    让 erfairy 目录可以作为 Python package 被导入，例如 `from erfairy.web import app`。

知识点与免费文档：
    - Python 包与模块: https://docs.python.org/3/tutorial/modules.html#packages
"""

__all__ = ["__version__"]  # 控制 `from erfairy import *` 时暴露的公共名称。

__version__ = "0.1.0"  # 包版本号，方便后续发布和排查部署版本。
