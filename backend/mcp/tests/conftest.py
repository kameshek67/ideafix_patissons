"""Локальная папка mcp затеняет SDK при импорте тестов pytest: добавляем путь SDK."""

from importlib.metadata import distribution

import mcp

if not getattr(mcp, "__file__", None):
    sdk = distribution("mcp").locate_file("mcp")
    if sdk is not None and str(sdk) not in mcp.__path__:
        mcp.__path__.append(str(sdk))
