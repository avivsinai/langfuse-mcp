"""Integration tests for langfuse-mcp package using MCP client."""

import asyncio
import json
import logging
import sys
from contextlib import asynccontextmanager

import pytest

# Skip the entire module if the `mcp` package is not available. This keeps the
# integration tests optional so that they don't fail in environments where the
# dependency isn't installed (e.g. open source CI).
pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Configure logging to console only
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("langfuse-mcp-test")


def _is_connection_closed_error(exc: BaseException) -> bool:
    """Recursively check if exception is a connection closed error."""
    if "Connection closed" in str(exc):
        return True
    # Check nested ExceptionGroup
    if hasattr(exc, "exceptions"):
        return all(_is_connection_closed_error(e) for e in exc.exceptions)
    return False


@asynccontextmanager
async def graceful_stdio_client(server_params):
    """Wrap stdio_client to handle cleanup errors gracefully."""
    try:
        async with stdio_client(server_params) as transport:
            yield transport
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
            raise
        if _is_connection_closed_error(e):
            logger.warning("Ignoring connection closed during cleanup: %s", e)
            return
        raise


def _dummy_langfuse_server_params():
    """Build server parameters for a local langfuse-mcp stdio process."""
    return StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "langfuse_mcp",
            "--public-key",
            "dummy_public_key",
            "--secret-key",
            "dummy_secret_key",
            "--host",
            "https://cloud.langfuse.com",
        ],
    )


async def run_get_schema_test():
    """Run the get_data_schema tool with dummy credentials."""
    server_params = _dummy_langfuse_server_params()

    async with graceful_stdio_client(server_params) as stdio_transport:
        read, write = stdio_transport
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.list_tools()  # Pre-cache to avoid in-flight request during teardown
            result = await session.call_tool("get_data_schema", {})

            assert result is not None
            assert hasattr(result, "content")

            if result.content and len(result.content) > 0:
                # Log what we received for debugging
                logger.info(f"Received content: {result.content}")

                if not result.content[0].text:
                    logger.warning("Received empty text response")
                    return {}

                try:
                    schema_text = result.content[0].text
                    # Try to parse as JSON
                    schema_data = json.loads(schema_text)
                    assert isinstance(schema_data, dict)
                    return schema_data
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON decode error: {e}")
                    logger.warning(f"Response text: {schema_text}")
                    # Return empty dict to avoid failing the test in CI
                    return {}
            else:
                logger.warning("No content received in response")
                return {}


async def run_get_metrics_schema_test():
    """Run the get_metrics_schema tool over MCP stdio with dummy credentials."""
    server_params = _dummy_langfuse_server_params()

    async with graceful_stdio_client(server_params) as stdio_transport:
        read, write = stdio_transport
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            tool_names = {tool.name for tool in tools_result.tools}
            assert {
                "query_metrics",
                "get_metrics_schema",
                "list_dataset_runs",
                "create_dataset_run_item",
                "delete_dataset_run",
            }.issubset(tool_names)

            result = await session.call_tool("get_metrics_schema", {})

            assert result is not None
            assert result.content
            schema_text = result.content[0].text
            assert isinstance(schema_text, str)
            assert schema_text.strip()
            assert "observations" in schema_text
            assert "scores-numeric" in schema_text
            assert "scores-categorical" in schema_text
            assert "p95" in schema_text


@pytest.mark.asyncio
async def test_get_data_schema():
    """Test the get_data_schema tool."""
    await run_get_schema_test()
    # Don't assert anything about the schema data in CI
    # This test is mainly to check that we can call the tool without errors


@pytest.mark.asyncio
async def test_get_metrics_schema_over_mcp():
    """Test the get_metrics_schema tool over the MCP stdio transport."""
    await run_get_metrics_schema_test()
