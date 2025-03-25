import asyncio
import json
import logging
import os
import shutil
import sys
from contextlib import AsyncExitStack
from datetime import datetime, timedelta
import datetime as dt
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


class LangfuseMCPServer:
    """Manages connection and interaction with the Langfuse MCP server."""
    
    def __init__(self, public_key: str, secret_key: str, host: str = "https://cloud.langfuse.com") -> None:
        """Initialize the server connection parameters.
        
        Args:
            public_key: Langfuse public key
            secret_key: Langfuse secret key
            host: Langfuse API host URL
        """
        self.public_key = public_key
        self.secret_key = secret_key
        self.host = host
        self.session: Optional[ClientSession] = None
        self._cleanup_lock = asyncio.Lock()
        self.exit_stack = AsyncExitStack()

    async def initialize(self) -> None:
        """Initialize the server connection."""
        # Get the Python executable from the virtual environment
        venv_python = os.path.join(os.path.dirname(sys.executable), "python")
        if not os.path.exists(venv_python):
            raise ValueError(f"Virtual environment Python not found at {venv_python}")

        # Server parameters
        server_params = StdioServerParameters(
            command=venv_python,
            args=[
                "-m", "langfuse_mcp",
                "--public-key", self.public_key,
                "--secret-key", self.secret_key,
                "--host", self.host
            ],
            env=os.environ
        )

        try:
            # Initialize server connection
            stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
            read, write = stdio_transport
            session = await self.exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.session = session
            logger.info("Successfully initialized Langfuse MCP server connection")
        except Exception as e:
            logger.error(f"Error initializing server: {e}")
            await self.cleanup()
            raise

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from the server."""
        if not self.session:
            raise RuntimeError("Server not initialized")

        tools_response = await self.session.list_tools()
        tools = []

        for item in tools_response:
            if isinstance(item, tuple) and item[0] == "tools":
                tools.extend(item[1])

        return tools

    async def find_exceptions(self, age_minutes: int = 30) -> Any:
        """Find exceptions in the last N minutes.
        
        Args:
            age_minutes: Number of minutes to look back
            
        Returns:
            List of exceptions found
        """
        if not self.session:
            raise RuntimeError("Server not initialized")

        return await self.session.call_tool(
            "find_exceptions",
            {"age": age_minutes, "group_by": "file"}
        )

    async def get_error_count(self, age_minutes: int = 30) -> Any:
        """Get the count of errors in the last N minutes.
        
        Args:
            age_minutes: Number of minutes to look back
            
        Returns:
            Error count information
        """
        if not self.session:
            raise RuntimeError("Server not initialized")

        return await self.session.call_tool(
            "get_error_count",
            {"age": age_minutes}
        )

    async def find_traces(
        self,
        name: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        from_timestamp: Optional[datetime] = None,
        to_timestamp: Optional[datetime] = None,
    ) -> Any:
        """Find traces with optional filters.
        
        Args:
            name: Filter by trace name
            user_id: Filter by user ID
            session_id: Filter by session ID
            from_timestamp: Start time range
            to_timestamp: End time range
            
        Returns:
            List of matching traces
        """
        if not self.session:
            raise RuntimeError("Server not initialized")

        args = {
            "name": name,
            "user_id": user_id,
            "session_id": session_id,
            "from_timestamp": from_timestamp.isoformat() if from_timestamp else None,
            "to_timestamp": to_timestamp.isoformat() if to_timestamp else None,
        }
        # Remove None values
        args = {k: v for k, v in args.items() if v is not None}

        return await self.session.call_tool("find_traces", args)

    async def cleanup(self) -> None:
        """Clean up server resources."""
        async with self._cleanup_lock:
            try:
                await self.exit_stack.aclose()
                self.session = None
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")


async def main() -> None:
    """Main test function."""
    # Default credentials from mcp.json
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "pk-lf-c6231d33-f98d-4393-9b28-4205f74984ae")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "sk-lf-e23afc03-982b-4f68-a4c2-f721af28691a")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    server = LangfuseMCPServer(public_key, secret_key, host)
    
    try:
        # Initialize server
        await server.initialize()
        
        # List available tools
        logger.info("Listing available tools:")
        tools = await server.list_tools()
        
        # Print info about tools without full serialization
        for i, tool_response in enumerate(tools):
            if isinstance(tool_response, tuple) and tool_response[0] == "tools":
                for j, tool in enumerate(tool_response[1]):
                    print(f"Tool {j+1}: {getattr(tool, 'name', 'Unknown')}")
        
        # Test error count
        logger.info("\nGetting error count for last 30 minutes:")
        error_count = await server.get_error_count(30)
        print(f"Error count results: {error_count}")
        
        # Test finding exceptions
        logger.info("\nFinding exceptions in last 30 minutes:")
        exceptions = await server.find_exceptions(30)
        print(f"Exceptions found: {exceptions}")
        
        # Test finding traces
        logger.info("\nFinding traces from last hour:")
        # Use timezone-aware datetime objects that work in all Python versions
        now = datetime.now(dt.timezone.utc)
        one_hour_ago = now - timedelta(hours=1)
        
        traces = await server.find_traces(
            from_timestamp=one_hour_ago,
            to_timestamp=now
        )
        print(f"Traces found: {traces}")
        
    except Exception as e:
        logger.error(f"Error during test: {e}")
    finally:
        await server.cleanup()


if __name__ == "__main__":
    asyncio.run(main()) 