#!/usr/bin/env python3
import asyncio
import json
import logging
import sys
import argparse
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Union

from mcp import ClientSession, StdioServerParameters 
from mcp.client.stdio import stdio_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/tmp/langfuse_mcp_runner.log")
    ]
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
        args=["run", "-m", "langfuse_mcp", 
              "--public-key", public_key, 
              "--secret-key", secret_key, 
              "--host", host]
    )
    
    logger.info("=" * 80)
    logger.info("Starting MCP runner...")
    logger.info(f"Server command: {server_params.command} {' '.join(server_params.args)}")
    logger.info("=" * 80)
    
    # Connect to the server with async context managers
    async with stdio_client(server_params) as stdio_transport:
        read, write = stdio_transport
        async with ClientSession(read, write) as session:
            # Initialize the session
            logger.info("Initializing session...")
            await session.initialize()
            logger.info("Session initialized successfully!")
            
            # List available tools
            logger.info("Listing available tools...")
            tools_response = await session.list_tools()
            
            # Extract and display tool names
            tool_names = []
            for item in tools_response:
                if isinstance(item, tuple) and item[0] == "tools":
                    for tool in item[1]:
                        tool_names.append(tool.name)
            
            logger.info("Available tools:")
            for tool in sorted(tool_names):
                logger.info(f"  - {tool}")
            
            # Get error count for last hour
            logger.info("\nGetting error count for last hour...")
            try:
                result = await session.call_tool("get_error_count", {"age": 60})
                if hasattr(result, 'content') and result.content:
                    error_count_text = result.content[0].text if result.content[0].text else "{}"
                    error_count_data = json.loads(error_count_text)
                    logger.info("Error count results:")
                    for key, value in error_count_data.items():
                        logger.info(f"  {key}: {value}")
            except Exception as e:
                logger.error(f"Error getting error count: {e}")
            
            # Find traces from the past 24 hours
            logger.info("\nRetrieving traces from the past 24 hours...")
            try:
                result = await session.call_tool("fetch_traces", {
                    "age": 24 * 60,  # 24 hours in minutes
                    "limit": 10,
                    "page": 1
                })
                
                if hasattr(result, 'content') and result.content:
                    text_content = result.content[0].text if result.content[0].text else "[]"
                    traces_data = json.loads(text_content)
                    
                    # Handle both single trace and multiple traces
                    traces_list = traces_data if isinstance(traces_data, list) else [traces_data]
                    
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
            except Exception as e:
                logger.error(f"Error retrieving traces: {e}")
            
            # Find exceptions
            logger.info("\nFinding exceptions from the past 24 hours...")
            try:
                result = await session.call_tool("find_exceptions", {
                    "age": 24 * 60,
                    "group_by": "file"
                })
                
                if hasattr(result, 'content') and result.content:
                    exceptions_text = result.content[0].text if result.content[0].text else "[]"
                    exceptions_data = json.loads(exceptions_text)
                    
                    if not exceptions_data:
                        logger.info("No exceptions found")
                    else:
                        logger.info(f"Found {len(exceptions_data)} exception groups:")
                        for i, exception in enumerate(exceptions_data[:5], 1):
                            logger.info(f"  Group {i}: {exception.get('group')} - Count: {exception.get('count')}")
            except Exception as e:
                logger.error(f"Error finding exceptions: {e}")
            
            logger.info("\nMCP runner completed successfully!")

def main():
    """Main entry point for the MCP runner."""
    parser = argparse.ArgumentParser(description="Langfuse MCP Runner")
    parser.add_argument(
        "--public-key",
        type=str,
        required=True,
        help="Langfuse public key"
    )
    parser.add_argument(
        "--secret-key",
        type=str,
        required=True,
        help="Langfuse secret key"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="https://cloud.langfuse.com",
        help="Langfuse host URL"
    )
    
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