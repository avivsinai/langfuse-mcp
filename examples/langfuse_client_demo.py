#!/usr/bin/env python3
"""Demo client for the Langfuse MCP integration.

This script provides a demonstration client implementation that connects to the Langfuse MCP
server and shows key functionality by executing various tool calls.
"""

import argparse
import asyncio
import json
import logging
import sys

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("/tmp/langfuse_mcp_runner.log")],
)
logger = logging.getLogger("langfuse-mcp-runner")

logger.info("=" * 80)
logger.info("Langfuse MCP Runner")
logger.info(f"Python version: {sys.version}")
logger.info(f"Running from: {__file__}")
logger.info("=" * 80)


async def run_mcp_tools(public_key: str, secret_key: str, host: str):
    """Run all available MCP tools and display their results.

    Args:
        public_key: Langfuse public key
        secret_key: Langfuse secret key
        host: Langfuse API host URL
    """
    # Create stdio server parameters
    server_params = StdioServerParameters(
        command="uv",  # Using uv consistently
        args=["run", "-m", "langfuse_mcp", "--public-key", public_key, "--secret-key", secret_key, "--host", host],
    )

    logger.info("=" * 80)
    logger.info("Starting MCP runner...")
    logger.info(f"Server command: {server_params.command} {' '.join(server_params.args)}")
    logger.info("=" * 80)

    async with Client(stdio_client(server_params)) as client:
        logger.info("Listing available tools...")
        tools_response = await client.list_tools()
        tool_names = [tool.name for tool in tools_response.tools]

        logger.info("Available tools:")
        for tool in sorted(tool_names):
            logger.info(f"  - {tool}")

        # Get error count for last hour
        logger.info("\nGetting error count for last hour...")
        try:
            result = await client.call_tool("get_error_count", {"age": 1440})
            data, metadata = parse_envelope(result)
            logger.info("Error count results:")
            if isinstance(data, dict):
                for key, value in data.items():
                    logger.info(f"  {key}: {value}")
            logger.info(f"Metadata: {metadata}")
        except Exception as e:
            logger.error(f"Error getting error count: {e}")

        # Find traces from the past 24 hours
        logger.info("\nRetrieving traces from the past 24 hours...")
        try:
            result = await client.call_tool(
                "fetch_traces",
                {
                    "age": 24 * 60,  # 24 hours in minutes
                    "limit": 10,
                    "page": 1,
                },
            )

            data, metadata = parse_envelope(result)
            traces_list = data if isinstance(data, list) else ([] if data in (None, "") else [data])

            if not traces_list:
                logger.info("No traces found in the past 24 hours")
            else:
                logger.info(f"Found {len(traces_list)} traces:")
                for i, trace in enumerate(traces_list[:5], 1):
                    logger.info(f"\nTrace {i}:")
                    logger.info(f"  ID: {trace.get('id', 'unknown')}")
                    logger.info(f"  Name: {trace.get('name', 'unnamed')}")
                    logger.info(f"  Time: {trace.get('timestamp', 'unknown')}")
                    logger.info(f"  User ID: {trace.get('user_id', 'none')}")

                    observations = trace.get("observations", [])
                    if observations:
                        logger.info(f"  Observations: {len(observations)}")
            logger.info(f"Metadata: {metadata}")
        except Exception as e:
            logger.error(f"Error retrieving traces: {e}")

        # Find exceptions
        logger.info("\nFinding exceptions from the past 24 hours...")
        try:
            result = await client.call_tool("find_exceptions", {"age": 24 * 60, "group_by": "file"})
            data, metadata = parse_envelope(result)

            if not data:
                logger.info("No exceptions found")
            else:
                logger.info(f"Found {len(data)} exception groups:")
                for i, exception in enumerate(data[:5], 1):
                    if isinstance(exception, dict):
                        logger.info(f"  Group {i}: {exception.get('group')} - Count: {exception.get('count')}")
                    else:
                        logger.info(f"  Group {i}: {exception}")
            logger.info(f"Metadata: {metadata}")
        except Exception as e:
            logger.error(f"Error finding exceptions: {e}")

        logger.info("\nMCP runner completed successfully!")


def parse_envelope(result):
    """Parse tool response content into data and metadata."""
    if not hasattr(result, "content") or not result.content:
        return None, None

    raw_text = result.content[0].text or ""
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return raw_text, None

    if isinstance(payload, dict) and "data" in payload:
        return payload.get("data"), payload.get("metadata")

    return payload, None


def main():
    """Run the Langfuse MCP demo client.

    Parses command line arguments and runs the main MCP client loop.
    """
    parser = argparse.ArgumentParser(description="Langfuse MCP Runner")
    parser.add_argument("--public-key", type=str, required=True, help="Langfuse public key")
    parser.add_argument("--secret-key", type=str, required=True, help="Langfuse secret key")
    parser.add_argument("--host", type=str, default="https://cloud.langfuse.com", help="Langfuse host URL")

    args = parser.parse_args()

    try:
        asyncio.run(run_mcp_tools(args.public_key, args.secret_key, args.host))
    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"Runner failed with error: {e}")
        logger.error("=" * 80)
        sys.exit(1)


if __name__ == "__main__":
    main()
