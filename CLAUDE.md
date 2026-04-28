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

## Supply chain / dependencies

- `pyproject.toml` sets `[tool.uv] exclude-newer = "7 days"` as a deliberate **supply-chain quarantine**: `uv lock` / `uv sync` will not resolve any package version published in the last 7 days, blocking freshly-published malicious versions from landing in dependency resolution. Dependabot's `cooldown` only delays generated PRs and does **not** cover ad-hoc lock/sync — the two are complementary.
- The relative-duration syntax (`"7 days"`, `"1 week"`, `"24 hours"`) requires uv ≥ 0.9 (added via astral-sh/uv#16814, Dec 2025). Older uv versions emit a parse warning or hard-fail; that is a local-toolchain problem, **not** a config bug. Bump local uv before assuming the line is broken.
- **Do not remove `exclude-newer` or any other security/supply-chain config** as "dead" or "noisy" without confirming what it gates. Investigate root cause (uv version, syntax change) before deleting protections. Past incident: a "follow-up cleanup" PR almost shipped removal of this line.

## Release Contract

- Release from `main` only through `./scripts/release.sh X.Y.Z` and the resulting release PR; do not create manual tags, GitHub releases, or ad hoc release uploads.
- A push to `main` updates the AvivSinai marketplace immediately for the `langfuse` skill.
- Keep one version across `CHANGELOG.md` and skill/plugin metadata in the release commit; after merge, CI validates the merged commit, creates the tag, and then publishes the GitHub release plus PyPI and Docker artifacts. The committed changelog entry becomes the GitHub release notes, while the Python package version remains tag-derived via `uv-dynamic-versioning`.

## Environment variables

- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`
- `LANGFUSE_MCP_LOG_FILE` defaults to `/tmp/langfuse_mcp.log`
- `LANGFUSE_MCP_TOOLS` selects comma-separated tool groups
- `LANGFUSE_MCP_DEFAULT_OUTPUT_MODE` sets the default MCP tool `output_mode`

## Code style

- Use type hints and Google-style docstrings.
- Ruff enforces formatting and lint rules.
- Target Python is 3.10+ with a 140-character line length.

## When adding tools

- Add tests.
- Update README tool docs and examples.
