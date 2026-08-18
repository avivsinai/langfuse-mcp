"""Print the first 20 lines of the newest Langfuse trace using compact output."""

import asyncio
import json
import os

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

pk = os.environ["LANGFUSE_PUBLIC_KEY"]
sk = os.environ["LANGFUSE_SECRET_KEY"]
host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")


async def parse_envelope(res):
    """Extract data and metadata payloads from an MCP response envelope."""
    if not hasattr(res, "content") or not res.content or not res.content[0].text:
        return None, None
    raw = res.content[0].text
    try:
        payload = json.loads(raw)
    except Exception:
        # Not JSON; return raw
        return raw, None
    if isinstance(payload, dict) and "data" in payload:
        return payload.get("data"), payload.get("metadata")
    return payload, None


async def main():
    """Connect to the MCP server and display a compact trace excerpt."""
    params = StdioServerParameters(
        command="uv", args=["run", "-m", "langfuse_mcp", "--public-key", pk, "--secret-key", sk, "--host", host, "--log-level", "INFO"]
    )
    async with Client(stdio_client(params)) as client:
        res = await client.call_tool("fetch_traces", {"age": 10080, "limit": 1, "page": 1, "output_mode": "compact"})
        data, meta = await parse_envelope(res)
        if not isinstance(data, list) or len(data) == 0:
            print("No traces found in the last 7 days.")
            return
        trace = data[0]
        pretty = json.dumps(trace, indent=2, default=str)
        lines = pretty.splitlines()
        for line in lines[:20]:
            print(line)
        if len(lines) > 20:
            print(f"\n... (truncated, total lines: {len(lines)})")


asyncio.run(main())
