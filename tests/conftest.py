"""Test configuration and fixtures for langfuse-mcp package."""

from __future__ import annotations

import sys
import types

import pytest

from tests.fakes import FakeLangfuse


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch: pytest.MonkeyPatch):
    """Provide fake `langfuse` and `mcp.server.mcpserver` modules for tests."""
    # Fake langfuse module with Langfuse class
    langfuse_mod = types.ModuleType("langfuse")
    langfuse_mod.Langfuse = FakeLangfuse
    sys.modules.setdefault("langfuse", langfuse_mod)

    # Minimal mcp.server.mcpserver with Context and MCPServer used at import time
    mcpserver_mod = types.ModuleType("mcp.server.mcpserver")

    class Context:
        def __init__(self, lifespan_context=None) -> None:
            self.request_context = types.SimpleNamespace(lifespan_context=lifespan_context)

    class MCPServer:
        def __init__(self, *args, **kwargs) -> None:
            self._tools = []
            self.lifespan = kwargs.get("lifespan")

        def tool(self):
            def decorator(func):
                self._tools.append(func)
                return func

            return decorator

    mcpserver_mod.Context = Context
    mcpserver_mod.MCPServer = MCPServer

    mcp_mod = types.ModuleType("mcp")
    server_pkg = types.ModuleType("mcp.server")

    sys.modules.setdefault("mcp", mcp_mod)
    sys.modules.setdefault("mcp.server", server_pkg)
    sys.modules.setdefault("mcp.server.mcpserver", mcpserver_mod)

    # `cachetools` is a declared project dependency: no stub needed.  Installing a
    # plain-dict stub here would silently disable maxsize enforcement and break the
    # _BoundedClientCache tests.  The real library is always available in the dev env.

    # `pydantic` is not stubbed: the real package is a transitive dependency (via mcp), and a
    # stub whose Field() returns the bare default would hide the FieldInfo defaults a direct tool
    # call really receives.

    yield

    # Cleanup modules inserted during the test session
    for name in ["mcp.server.mcpserver", "mcp.server", "mcp", "langfuse"]:
        sys.modules.pop(name, None)
