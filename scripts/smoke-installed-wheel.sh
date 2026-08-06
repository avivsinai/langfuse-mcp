#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: ./scripts/smoke-installed-wheel.sh WHEEL" >&2
}

[ "$#" -eq 1 ] || {
  usage
  exit 2
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "error: required command not found: $1" >&2
    exit 1
  fi
}

require_command uv

python_version="${PYTHON_VERSION:-3.12}"
smoke_root="$(mktemp -d "${TMPDIR:-/tmp}/langfuse-mcp-wheel-smoke.XXXXXX")"
trap 'rm -rf -- "$smoke_root"' EXIT

[ -f "$1" ] || {
  echo "error: wheel not found: $1" >&2
  exit 1
}
wheel="$(cd "$(dirname "$1")" && pwd -P)/$(basename "$1")"

case "$wheel" in
  *.whl) ;;
  *)
    echo "error: expected a .whl artifact, got: $wheel" >&2
    exit 1
    ;;
esac

mkdir -p "$smoke_root/run"
cd "$smoke_root/run"

unset PYTHONPATH
export PYTHONNOUSERSITE=1
export UV_CACHE_DIR="$smoke_root/uv-cache"

uv venv --no-config --python "$python_version" "$smoke_root/venv"
uv pip install --no-config --python "$smoke_root/venv/bin/python" "$wheel"

SMOKE_VENV="$smoke_root/venv" \
LANGFUSE_PUBLIC_KEY="test-api-key" \
LANGFUSE_SECRET_KEY="dummy-secret" \
LANGFUSE_HOST="http://127.0.0.1:9" \
LANGFUSE_MCP_LOG_FILE="$smoke_root/langfuse_mcp.log" \
  "$smoke_root/venv/bin/python" - <<'PY'
import asyncio
import os
import sysconfig
from importlib.metadata import distribution
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


venv = Path(os.environ["SMOKE_VENV"]).resolve()
app_distribution = distribution("langfuse-mcp")
mcp_distribution = distribution("mcp")

for installed_distribution in (app_distribution, mcp_distribution):
    install_root = Path(installed_distribution.locate_file("")).resolve()
    if not install_root.is_relative_to(venv):
        raise RuntimeError(f"{installed_distribution.metadata['Name']} loaded outside smoke venv: {install_root}")

mcp_requirement = next(
    (requirement for requirement in app_distribution.requires or [] if requirement.lower().startswith("mcp[")),
    None,
)
if mcp_requirement is None or "<2" not in mcp_requirement.replace(" ", ""):
    raise RuntimeError(f"wheel metadata is missing the MCP upper bound: {mcp_requirement!r}")

mcp_version = mcp_distribution.version
if int(mcp_version.split(".", 1)[0]) >= 2:
    raise RuntimeError(f"resolved incompatible MCP version: {mcp_version}")

console_script = Path(sysconfig.get_path("scripts")) / "langfuse-mcp"
if not console_script.is_file():
    raise RuntimeError(f"installed console script not found: {console_script}")


async def probe() -> None:
    """Initialize the installed MCP server and exercise one tool-list request."""
    environment = dict(os.environ)
    parameters = StdioServerParameters(
        command=str(console_script),
        args=["--tools", "schema", "--read-only"],
        env=environment,
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            if tool_names != {"get_data_schema"}:
                raise RuntimeError(f"unexpected installed server tools: {sorted(tool_names)}")


asyncio.run(asyncio.wait_for(probe(), timeout=30))

print(f"langfuse-mcp {app_distribution.version}: {app_distribution.locate_file('')}")
print(f"mcp {mcp_version}: {mcp_distribution.locate_file('')}")
print(f"Requires-Dist: {mcp_requirement}")
PY

echo "installed-wheel smoke passed: $(basename "$wheel") (Python $python_version)"
