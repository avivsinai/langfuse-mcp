# Claude Code Instructions

## Project summary
Langfuse MCP server for accessing Langfuse telemetry (traces, observations, prompts, etc.) via MCP.
The CLI entrypoint is `langfuse-mcp`, which runs `langfuse_mcp.__main__:main` using FastMCP.

## Repo layout
- `langfuse_mcp/__main__.py`: Core server implementation and tool definitions
- `tests/`: Pytest suite; integration tests are marked with `pytest.mark.integration`

## Dev setup (uv)
```bash
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Common commands
```bash
# Run the server from a local checkout
uv run python -m langfuse_mcp --public-key YOUR_KEY --secret-key YOUR_SECRET --host https://cloud.langfuse.com

# Tests
uv run -m pytest

# Lint/format
uv run -m ruff format .
uv run -m ruff check --fix .
```

## Environment variables
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`
- `LANGFUSE_MCP_LOG_FILE` (default: `/tmp/langfuse_mcp.log`)
- `LANGFUSE_MCP_TOOLS` (comma-separated tool groups)

## Code style
- Use type hints and Google-style docstrings
- Ruff enforces formatting and lint rules
- Line length: 140; target Python: 3.10+

## When adding tools
- Add tests
- Update README tool docs/examples
