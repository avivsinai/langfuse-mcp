#!/usr/bin/env python3
import asyncio
import json
import logging
import subprocess
import sys
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
        logging.FileHandler("/tmp/langfuse_mcp_test.log")
    ]
)
logger = logging.getLogger("langfuse-mcp-test")

logger.info("=" * 80)
logger.info("Langfuse MCP Test Client")
logger.info(f"Python version: {sys.version}")
logger.info(f"Running from: {__file__}")
logger.info("=" * 80)

async def main():
    # Parameters from mcp.json
    public_key = "YOUR_PUBLIC_KEY"
    secret_key = "YOUR_SECRET_KEY"
    host = "https://cloud.langfuse.com"
    
    # Create stdio server parameters
    server_params = StdioServerParameters(
        command="uv",  # Using uv consistently
        args=["run", "-m", "langfuse_mcp", 
              "--public-key", public_key, 
              "--secret-key", secret_key, 
              "--host", host,
              "--no-auth-check"]  # Added for testing
    )
    
    logger.info("=" * 80)
    logger.info("Starting MCP client test...")
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
            
            # Get error count
            logger.info("\nTesting get_error_count tool...")
            try:
                result = await session.call_tool("get_error_count", {"age": 60})
                logger.info("Tool execution successful!")
                
                # Display result data safely
                if hasattr(result, 'content') and result.content:
                    error_count_text = result.content[0].text if result.content[0].text else "{}"
                    error_count_data = json.loads(error_count_text)
                    logger.info(f"Error count data: {error_count_data}")
                else:
                    logger.info(f"Result: {result}")
            except Exception as e:
                logger.error(f"Error executing tool: {e}")
            
            # Find traces from the past 48 hours
            logger.info("\nRetrieving traces from the past 48 hours...")
            trace_id = None  # Will store trace ID for detailed lookup
            
            try:
                # Calculate age in minutes for 48 hours
                age_minutes = 48 * 60  # 48 hours in minutes
                
                # Fetch traces with age parameter explicitly provided
                result = await session.call_tool("fetch_traces", {
                    "age": age_minutes,
                    "limit": 20,
                    "page": 1
                })
                logger.info("Retrieved traces successfully!")
                
                # Extract and display trace information
                if hasattr(result, 'content') and result.content:
                    # Parse JSON from the text content
                    text_content = result.content[0].text if result.content[0].text else "[]"
                    logger.info(f"Raw response length: {len(text_content)} chars")  # Show length of response
                    
                    try:
                        traces_data = json.loads(text_content)
                        
                        # Handle both single trace (dict) and multiple traces (list)
                        traces_list = []
                        if isinstance(traces_data, dict):
                            # Single trace
                            traces_list = [traces_data]
                            logger.info("Found a single trace")
                        elif isinstance(traces_data, list):
                            # Multiple traces
                            traces_list = traces_data
                            logger.info(f"Found {len(traces_list)} traces")
                        
                        if not traces_list:
                            logger.info("No traces found in the past 48 hours. Check if your Langfuse account has traces.")
                        else:
                            # Display details of each trace (up to 5)
                            for i, trace in enumerate(traces_list[:5]):
                                trace_id = trace.get("id", "unknown")
                                trace_name = trace.get("name", "unnamed")
                                trace_time = trace.get("timestamp", "unknown")
                                
                                logger.info(f"Trace {i+1}: ID={trace_id}, Name={trace_name}, Time={trace_time}")
                                
                                # If the trace has observations, count them
                                observations = trace.get("observations", [])
                                if observations:
                                    logger.info(f"  - Contains {len(observations)} observations")
                                
                                # Display user info if available
                                user_id = trace.get("user_id")
                                if user_id:
                                    logger.info(f"  - User ID: {user_id}")
                                
                                # Save the first trace ID for detailed lookup
                                if i == 0:
                                    trace_id = trace_id
                    except json.JSONDecodeError as e:
                        logger.error(f"Error parsing JSON response: {e}")
                        logger.info(f"First 100 chars of response: {text_content[:100]}")
                else:
                    logger.info(f"Raw result: {result}")
            except Exception as e:
                logger.error(f"Error retrieving traces: {e}")
                logger.exception(e)
            
            # Get detailed information about a specific trace
            if trace_id and trace_id != "unknown":
                logger.info(f"\nFetching detailed information for trace: {trace_id}")
                try:
                    trace_result = await session.call_tool("fetch_trace", {
                        "trace_id": trace_id
                    })
                    
                    if hasattr(trace_result, 'content') and trace_result.content:
                        detailed_content = trace_result.content[0].text if trace_result.content[0].text else "{}"
                        try:
                            detailed_trace = json.loads(detailed_content)
                            
                            # Display trace details
                            logger.info("Trace details:")
                            logger.info(f"  Name: {detailed_trace.get('name')}")
                            logger.info(f"  Start time: {detailed_trace.get('timestamp')}")
                            logger.info(f"  Duration: {detailed_trace.get('duration_ms')} ms")
                            
                            # Display metadata if available
                            metadata = detailed_trace.get('metadata')
                            if metadata:
                                logger.info(f"  Metadata: {json.dumps(metadata, indent=2)[:200]}...")
                            
                            # Display observations
                            observations = detailed_trace.get('observations', [])
                            logger.info(f"  Observations: {len(observations)}")
                            
                            # Show details for first few observations
                            for i, obs in enumerate(observations[:3]):
                                logger.info(f"    Observation {i+1}: Type={obs.get('type')}, Name={obs.get('name')}")
                                
                            # Log full response length for verification
                            logger.info(f"Full trace response length: {len(detailed_content)} characters")
                            logger.info(f"First observation has truncated fields: {'...' in json.dumps(observations[0]) if observations else False}")
                            
                            # Check if any input or output fields were truncated
                            truncated_count = 0
                            for obs in observations:
                                if isinstance(obs.get('input'), str) and '...' in obs.get('input', ''):
                                    truncated_count += 1
                                if isinstance(obs.get('output'), str) and '...' in obs.get('output', ''):
                                    truncated_count += 1
                            
                            logger.info(f"Number of truncated input/output fields found: {truncated_count}")
                        except json.JSONDecodeError as e:
                            logger.error(f"Error parsing trace JSON: {e}")
                            logger.info(f"First 100 chars of trace response: {detailed_content[:100]}")
                except Exception as e:
                    logger.error(f"Error retrieving trace details: {e}")
                    logger.exception(e)
            
            # Test find_exceptions
            logger.info("\nTesting find_exceptions tool...")
            try:
                result = await session.call_tool("find_exceptions", {"age": 1440, "group_by": "file"})
                logger.info("find_exceptions executed successfully!")
                
                if hasattr(result, 'content') and result.content:
                    exceptions_text = result.content[0].text if result.content[0].text else "[]"
                    try:
                        exceptions_data = json.loads(exceptions_text)
                        logger.info(f"Found {len(exceptions_data)} exception groups")
                        
                        # Display first few exception groups
                        for i, exception in enumerate(exceptions_data[:3]):
                            logger.info(f"  Exception group {i+1}: {exception.get('group')} - Count: {exception.get('count')}")
                    except json.JSONDecodeError as e:
                        logger.error(f"Error parsing exceptions JSON: {e}")
                        logger.info(f"First 100 chars of exceptions response: {exceptions_text[:100]}")
            except Exception as e:
                logger.error(f"Error executing find_exceptions: {e}")
                logger.exception(e)
            
            # Shutdown session
            logger.info("\nShutting down session...")
    
    logger.info("=" * 80)
    logger.info("Test completed successfully!")
    logger.info("=" * 80)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"Test failed with error: {e}")
        logger.error("=" * 80)
        sys.exit(1) 