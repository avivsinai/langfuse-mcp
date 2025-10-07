# Langfuse MCP (Model Context Protocol)

[![Test](https://github.com/avivsinai/langfuse-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/avivsinai/langfuse-mcp/actions/workflows/test.yml)
[![PyPI version](https://badge.fury.io/py/langfuse-mcp.svg)](https://badge.fury.io/py/langfuse-mcp)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

This project provides a Model Context Protocol (MCP) server for Langfuse, allowing AI agents to query Langfuse trace data for better debugging and observability.

## Quick Start with Cursor

<a href="cursor://anysphere.cursor-deeplink/mcp/install?name=langfuse-mcp&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJsYW5nZnVzZS1tY3AiLCItLXB1YmxpYy1rZXkiLCJZT1VSX1BVQkxJQ19LRVkiLCItLXNlY3JldC1rZXkiLCJZT1VSX1NFQ1JFVF9LRVkiLCItLWhvc3QiLCJodHRwczovL2Nsb3VkLmxhbmdmdXNlLmNvbSJdfQ==">
  <img src="https://img.shields.io/badge/Add%20to-Cursor-blue?style=for-the-badge&logo=cursor" alt="Add to Cursor">
</a>

### Installation Options

🎯 **From Cursor IDE**: Click the button above (works seamlessly!)  
🌐 **From GitHub Web**: Copy this deeplink and paste into your browser address bar:
```
cursor://anysphere.cursor-deeplink/mcp/install?name=langfuse-mcp&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJsYW5nZnVzZS1tY3AiLCItLXB1YmxpYy1rZXkiLCJZT1VSX1BVQkxJQ19LRVkiLCItLXNlY3JldC1rZXkiLCJZT1VSX1NFQ1JFVF9LRVkiLCItLWhvc3QiLCJodHRwczovL2Nsb3VkLmxhbmdmdXNlLmNvbSJdfQ==
```
⚙️ **Manual Setup**: See [Configuration](#configuration-with-mcp-clients) section below

> **💡 Note**: The "Add to Cursor" button only works from within Cursor IDE due to browser security restrictions on custom protocols (`cursor://`). This is normal and expected behavior per [Cursor's documentation](https://docs.cursor.com/deeplinks).

**After installation**: Replace `YOUR_PUBLIC_KEY` and `YOUR_SECRET_KEY` with your actual Langfuse credentials in Cursor's MCP settings.

## Features

- Integration with Langfuse for trace and observation data
- Tool suite for AI agents to query trace data
- Exception and error tracking capabilities
- Session and user activity monitoring

## Available Tools

The MCP server provides the following tools for AI agents:

- `fetch_traces` - Find traces based on criteria like user ID, session ID, etc.
- `fetch_trace` - Get a specific trace by ID
- `fetch_observations` - Get observations filtered by type
- `fetch_observation` - Get a specific observation by ID
- `fetch_sessions` - List sessions in the current project
- `get_session_details` - Get detailed information about a session
- `get_user_sessions` - Get all sessions for a user
- `find_exceptions` - Find exceptions and errors in traces
- `find_exceptions_in_file` - Find exceptions in a specific file
- `get_exception_details` - Get detailed information about an exception
- `get_error_count` - Get the count of errors
- `get_data_schema` - Get schema information for the data structures

## Setup

### Install `uv`

First, make sure `uv` is installed. For installation instructions, see the [`uv` installation docs](https://docs.astral.sh/uv/getting-started/installation/).

If you already have an older version of `uv` installed, you might need to update it with `uv self update`.

### Installation

> **Requirement**: The server now depends on the Langfuse Python SDK v3. Installations automatically pull `langfuse>=3.0.0`.

```bash
uv pip install langfuse-mcp
```

If you're iterating on this repository, install the local checkout instead of PyPI:

```bash
# from the repo root
uv pip install --editable .
```

### Recommended local environment

For development we suggest creating an isolated environment pinned to Python 3.11 (the version used in CI):

```bash
uv venv --python 3.11 .venv
source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
uv pip install --python .venv/bin/python -e .
```

All subsequent examples assume the virtual environment is activated.

### Obtain Langfuse credentials

You'll need your Langfuse credentials:
- Public key
- Secret key
- Host URL (usually https://cloud.langfuse.com or your self-hosted URL)

You can store these in a local `.env` file instead of passing CLI flags each time:

```
LANGFUSE_PUBLIC_KEY=your_public_key
LANGFUSE_SECRET_KEY=your_secret_key
LANGFUSE_HOST=https://cloud.langfuse.com
```

When present, the MCP server reads these values automatically. CLI arguments still override the environment if provided.

## Running the Server

Run the server using `uvx` or the project virtual environment:

```bash
uvx langfuse-mcp --public-key YOUR_KEY --secret-key YOUR_SECRET --host https://cloud.langfuse.com

# or, once inside the repo virtual environment
langfuse-mcp --public-key YOUR_KEY --secret-key YOUR_SECRET --host https://cloud.langfuse.com
```

> **Local checkout tip**: During development run `uv run --from /path/to/langfuse-mcp langfuse-mcp ...` (or `uv run python -m langfuse_mcp ...`) so `uv` executes the code in your working tree. Using the PyPI shortcut skips repository-only changes such as the new environment-based credential defaults and logging tweaks.

The server writes diagnostic logs to `/tmp/langfuse_mcp.log`. Remove the `--host` switch if you are targeting the default Cloud endpoint.
Use `--log-level` (e.g., `--log-level DEBUG`) and `--log-to-console` to control verbosity during debugging.

### Run with Docker

#### Option 1: Pull from GitHub Container Registry (Recommended)

Pull and run the pre-built image:

```bash
docker pull ghcr.io/avivsinai/langfuse-mcp:latest
docker run --rm -i \
  -e LANGFUSE_PUBLIC_KEY=YOUR_PUBLIC_KEY \
  -e LANGFUSE_SECRET_KEY=YOUR_SECRET_KEY \
  -e LANGFUSE_HOST=https://cloud.langfuse.com \
  -e LANGFUSE_MCP_LOG_FILE=/logs/langfuse_mcp.log \
  -v "$(pwd)/logs:/logs" \
  ghcr.io/avivsinai/langfuse-mcp:latest
```

Available tags:
- `latest` - Most recent release
- `v0.2.0` - Specific version
- `0.2` - Major.minor version

#### Option 2: Build from source

Build the image from the repository root so the container installs the current checkout instead of the latest PyPI release:

```bash
docker build -t langfuse-logs-mcp .
docker run --rm -i \
  -e LANGFUSE_PUBLIC_KEY=YOUR_PUBLIC_KEY \
  -e LANGFUSE_SECRET_KEY=YOUR_SECRET_KEY \
  -e LANGFUSE_HOST=https://cloud.langfuse.com \
  -e LANGFUSE_MCP_LOG_FILE=/logs/langfuse_mcp.log \
  -v "$(pwd)/logs:/logs" \
  langfuse-logs-mcp
```

> **Why no `-t`?** Allocating a pseudo-TTY can interfere with MCP stdio clients. Use `-i` only so the server communicates over plain stdin/stdout.

The Dockerfile copies the local source tree and installs it with `pip install .`, so the container always runs your latest commits - a must while testing features that have not shipped on PyPI.


## Configuration with MCP clients

### Configure for Cursor

Create a `.cursor/mcp.json` file in your project root:

```json
{
  "mcpServers": {
    "langfuse": {
      "command": "uvx",
      "args": ["langfuse-mcp", "--public-key", "YOUR_KEY", "--secret-key", "YOUR_SECRET", "--host", "https://cloud.langfuse.com"]
    }
  }
}
```

### Configure for Claude Desktop

Add to your Claude settings:

```json
{
  "command": ["uvx"],
  "args": ["langfuse-mcp"],
  "type": "stdio",
  "env": {
    "LANGFUSE_PUBLIC_KEY": "YOUR_KEY",
    "LANGFUSE_SECRET_KEY": "YOUR_SECRET",
    "LANGFUSE_HOST": "https://cloud.langfuse.com"
  }
}
```

## Output Modes

Each tool supports different output modes to control the level of detail in responses:

- `compact` (default): Returns a summary with large values truncated
- `full_json_string`: Returns the complete data as a JSON string
- `full_json_file`: Saves the complete data to a file and returns a summary with file information

## Development

### Clone the repository

```bash
git clone https://github.com/yourusername/langfuse-mcp.git
cd langfuse-mcp
```

### Create a virtual environment and install dependencies

```bash
uv venv --python 3.11 .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install --python .venv/bin/python -e ".[dev]"
```

### Set up environment variables

```bash
export LANGFUSE_SECRET_KEY="your-secret-key"
export LANGFUSE_PUBLIC_KEY="your-public-key"
export LANGFUSE_HOST="https://cloud.langfuse.com"  # Or your self-hosted URL
```

### Testing

Run the unit test suite (mirrors CI):

```bash
pytest
```

To run the demo client:

```bash
uv run examples/langfuse_client_demo.py --public-key YOUR_PUBLIC_KEY --secret-key YOUR_SECRET_KEY
```


## Version Management

This project uses dynamic versioning based on Git tags:

1. The version is automatically determined from git tags using `uv-dynamic-versioning`
2. To create a new release:
   - Tag your commit with `git tag v0.1.2` (following semantic versioning)
   - Push the tag with `git push --tags`
   - Create a GitHub release from the tag
3. The GitHub workflow will automatically build and publish the package with the correct version to PyPI

For a detailed history of changes, please see the [CHANGELOG.md](CHANGELOG.md) file.

## Langfuse 3.x migration notes

- The MCP server now uses the Langfuse Python SDK v3 resource clients (`langfuse.api.trace.list`, `langfuse.api.observations.get_many`, etc.).
- Unit tests use a v3-style fake client that fails if legacy `fetch_*` helpers are invoked, helping catch regressions early.
- Tool responses now include pagination metadata when the Langfuse API returns cursors, while retaining the existing MCP interface.
- Diagnostic logs continue to stream to `/tmp/langfuse_mcp.log`; this is useful when verifying the upgraded integration against a live Langfuse deployment.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Cache Management

We use the `cachetools` library to implement efficient caching with proper size limits:

- Uses `cachetools.LRUCache` for better reliability
- Configurable cache size via the `CACHE_SIZE` constant
- Automatically evicts the least recently used items when caches exceed their size limits
