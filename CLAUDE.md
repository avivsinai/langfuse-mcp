# Claude Code Instructions

This is the master agent instruction file for this repository. Keep repository policy here. `AGENTS.md` exists only as a Codex compatibility shim and should contain only Codex-specific notes.

## Project summary

Langfuse MCP server for accessing Langfuse telemetry such as traces, observations, prompts, and datasets via MCP.
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
uv run python -m langfuse_mcp --public-key YOUR_KEY --secret-key YOUR_SECRET --host https://cloud.langfuse.com
uv run -m pytest
uv run -m ruff format .
uv run -m ruff check --fix .
```

## Release Contract

- Release from `main` only; do not create manual GitHub releases or ad hoc release uploads.
- A push to `main` updates the AvivSinai marketplace immediately for the `langfuse` skill.
- For a versioned release, keep `CHANGELOG.md` and skill/plugin metadata on one version, then push the tag and let CI publish the GitHub release plus PyPI and Docker artifacts.

## Environment variables

- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`
- `LANGFUSE_MCP_LOG_FILE` defaults to `/tmp/langfuse_mcp.log`
- `LANGFUSE_MCP_TOOLS` selects comma-separated tool groups

## Code style

- Use type hints and Google-style docstrings.
- Ruff enforces formatting and lint rules.
- Target Python is 3.10+ with a 140-character line length.

## When adding tools

- Add tests.
- Update README tool docs and examples.
