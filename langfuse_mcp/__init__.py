"""Langfuse MCP: Access and analyze telemetry data via natural language."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("langfuse-mcp")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"

__all__ = ["__version__"] 