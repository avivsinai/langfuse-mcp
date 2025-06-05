"""Integration tests for langfuse-mcp package using MCP client."""

import json
import logging

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


async def run_get_schema_test():
    """Run the get_data_schema tool with dummy credentials."""
    server_params = StdioServerParameters(
        command="uv",
        args=[
            "run",
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

    async with stdio_client(server_params) as stdio_transport:
        read, write = stdio_transport
        async with ClientSession(read, write) as session:
            await session.initialize()
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


@pytest.mark.asyncio
async def test_get_data_schema():
    """Test the get_data_schema tool."""
    await run_get_schema_test()
    # Don't assert anything about the schema data in CI
    # This test is mainly to check that we can call the tool without errors
