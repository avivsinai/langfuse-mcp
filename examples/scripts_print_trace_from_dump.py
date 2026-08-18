"""Read a trace from the dump file produced by the MCP server."""

import asyncio
import json
import os

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

pk = os.environ["LANGFUSE_PUBLIC_KEY"]
sk = os.environ["LANGFUSE_SECRET_KEY"]
host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")


async def main():
    """Request a full JSON dump and print the first 20 lines from disk."""
    params = StdioServerParameters(
        command="uv", args=["run", "-m", "langfuse_mcp", "--public-key", pk, "--secret-key", sk, "--host", host, "--log-level", "INFO"]
    )
    async with Client(stdio_client(params)) as client:
        res = await client.call_tool(
            "fetch_traces", {"age": 10080, "limit": 1, "page": 1, "include_observations": True, "output_mode": "full_json_file"}
        )
        if not hasattr(res, "content") or not res.content or not res.content[0].text:
            print("ERROR: empty MCP response")
            return
        try:
            payload = json.loads(res.content[0].text)
        except Exception as e:
            print("ERROR: unable to parse envelope JSON:", e)
            print("RAW:", res.content[0].text[:200])
            return
        meta = payload.get("metadata") or {}
        file_path = meta.get("file_path") or meta.get("full_json_file_path") or meta.get("file_info", {}).get("file_path")
        if not file_path:
            print("ERROR: no dump file path returned in metadata:", meta)
            return
        # Load saved file
        try:
            with open(file_path, encoding="utf-8") as f:
                full_data = json.load(f)
        except Exception as e:
            print("ERROR: unable to read saved file:", e, file_path)
            return
        if not isinstance(full_data, list) or not full_data:
            print("No traces in saved file.")
            return
        trace = full_data[0]
        pretty = json.dumps(trace, indent=2, default=str)
        lines = pretty.splitlines()
        for i, line in enumerate(lines[:20], 1):
            print(line)
        if len(lines) > 20:
            print(f"\n... (truncated, total lines: {len(lines)})")


asyncio.run(main())
