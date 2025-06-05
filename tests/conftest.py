"""Test configuration and fixtures for langfuse-mcp package."""

from __future__ import annotations

import sys
import types

import pytest

from tests.fakes import FakeLangfuse


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch: pytest.MonkeyPatch):
    """Provide fake `langfuse` and `mcp.server.fastmcp` modules for tests."""
    # Fake langfuse module with Langfuse class
    langfuse_mod = types.ModuleType("langfuse")
    langfuse_mod.Langfuse = FakeLangfuse
    sys.modules.setdefault("langfuse", langfuse_mod)

    # Minimal mcp.server.fastmcp with Context and FastMCP used at import time
    fastmcp_mod = types.ModuleType("mcp.server.fastmcp")

    class Context:
        def __init__(self, lifespan_context=None) -> None:
            self.request_context = types.SimpleNamespace(lifespan_context=lifespan_context)

    class FastMCP:
        def __init__(self, *args, **kwargs) -> None:
            self._tools = []
            self.lifespan = kwargs.get("lifespan")

        def tool(self):
            def decorator(func):
                self._tools.append(func)
                return func

            return decorator

    fastmcp_mod.Context = Context
    fastmcp_mod.FastMCP = FastMCP

    mcp_mod = types.ModuleType("mcp")
    server_pkg = types.ModuleType("mcp.server")

    sys.modules.setdefault("mcp", mcp_mod)
    sys.modules.setdefault("mcp.server", server_pkg)
    sys.modules.setdefault("mcp.server.fastmcp", fastmcp_mod)

    # Minimal cachetools with an LRUCache placeholder so that `langfuse_mcp` can
    # import it without requiring the real dependency.
    cachetools_mod = types.ModuleType("cachetools")

    class LRUCache(dict):
        def __init__(self, maxsize=128) -> None:
            super().__init__()
            self.maxsize = maxsize

    cachetools_mod.LRUCache = LRUCache
    sys.modules.setdefault("cachetools", cachetools_mod)

    # Provide a minimal stub of the `pydantic` module with BaseModel and Field
    # used only for type hints within `langfuse_mcp`.
    pydantic_mod = types.ModuleType("pydantic")

    class BaseModel:
        pass

    def Field(default=None, **kwargs):
        return default

    class AfterValidator:
        def __init__(self, fn):
            self.fn = fn

        def __call__(self, value):
            return self.fn(value)

    pydantic_mod.BaseModel = BaseModel
    pydantic_mod.Field = Field
    pydantic_mod.AfterValidator = AfterValidator
    sys.modules.setdefault("pydantic", pydantic_mod)

    yield

    # Cleanup modules inserted during the test session
    for name in ["mcp.server.fastmcp", "mcp.server", "mcp", "langfuse"]:
        sys.modules.pop(name, None)
