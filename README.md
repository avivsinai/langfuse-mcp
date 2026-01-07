# Langfuse MCP Server

[![Test](https://github.com/avivsinai/langfuse-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/avivsinai/langfuse-mcp/actions/workflows/test.yml)
[![PyPI version](https://badge.fury.io/py/langfuse-mcp.svg)](https://badge.fury.io/py/langfuse-mcp)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%E2%80%933.14-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A comprehensive [Model Context Protocol](https://modelcontextprotocol.io) server for [Langfuse](https://langfuse.com) observability. Provides **18 tools** for AI agents to query traces, debug errors, analyze sessions, and manage prompts.

## Quick Start

```bash
uvx langfuse-mcp --public-key YOUR_KEY --secret-key YOUR_SECRET --host https://cloud.langfuse.com
```

Or set environment variables and run without flags:
```bash
export LANGFUSE_PUBLIC_KEY=pk-...
export LANGFUSE_SECRET_KEY=sk-...
export LANGFUSE_HOST=https://cloud.langfuse.com
uvx langfuse-mcp
```

## Why langfuse-mcp?

| | langfuse-mcp | Official Langfuse MCP |
|-|--------------|----------------------|
| **Tools** | 18 | 2-4 |
| **Traces & Observations** | Yes | No |
| **Sessions & Users** | Yes | No |
| **Exception Tracking** | Yes | No |
| **Prompt Management** | Yes | Yes |
| **Language** | Python | TypeScript |
| **Selective Tool Loading** | Yes | No |

This project provides a **full observability toolkit** — traces, observations, sessions, exceptions, and prompts — while the [official Langfuse MCP](https://github.com/langfuse/mcp-server-langfuse) focuses on prompt management only.

## Available Tools

### Traces
| Tool | Description |
|------|-------------|
| `fetch_traces` | Search/filter traces with pagination |
| `fetch_trace` | Fetch a specific trace by ID |

### Observations
| Tool | Description |
|------|-------------|
| `fetch_observations` | Search/filter observations with pagination |
| `fetch_observation` | Fetch a specific observation by ID |

### Sessions
| Tool | Description |
|------|-------------|
| `fetch_sessions` | List recent sessions with pagination |
| `get_session_details` | Get detailed session info by ID |
| `get_user_sessions` | Get all sessions for a user |

### Exceptions
| Tool | Description |
|------|-------------|
| `find_exceptions` | Find exceptions grouped by file/function/type |
| `find_exceptions_in_file` | Find exceptions in a specific file |
| `get_exception_details` | Get detailed info about a specific exception |
| `get_error_count` | Get total error count |

### Prompts
| Tool | Description |
|------|-------------|
| `get_prompt` | Fetch prompt with resolved dependencies |
| `get_prompt_unresolved` | Fetch prompt with dependency tags intact |
| `list_prompts` | List/filter prompts with pagination |
| `create_text_prompt` | Create new text prompt version |
| `create_chat_prompt` | Create new chat prompt version |
| `update_prompt_labels` | Update labels for a prompt version |

### Schema
| Tool | Description |
|------|-------------|
| `get_data_schema` | Get schema information for response structures |

## Installation

### Using uvx (recommended)
```bash
uvx langfuse-mcp --help
```

### Using pip
```bash
pip install langfuse-mcp
langfuse-mcp --help
```

### Using Docker
```bash
docker pull ghcr.io/avivsinai/langfuse-mcp:latest
docker run --rm -i \
  -e LANGFUSE_PUBLIC_KEY=pk-... \
  -e LANGFUSE_SECRET_KEY=sk-... \
  -e LANGFUSE_HOST=https://cloud.langfuse.com \
  ghcr.io/avivsinai/langfuse-mcp:latest
```

## Configuration

### Claude Code

Create `.mcp.json` in your project root:
```json
{
  "mcpServers": {
    "langfuse": {
      "command": "uvx",
      "args": ["langfuse-mcp"],
      "env": {
        "LANGFUSE_PUBLIC_KEY": "pk-...",
        "LANGFUSE_SECRET_KEY": "sk-...",
        "LANGFUSE_HOST": "https://cloud.langfuse.com"
      }
    }
  }
}
```

### Codex CLI

Add to `~/.codex/config.toml`:
```toml
[mcp_servers.langfuse]
command = "uvx"
args = ["langfuse-mcp"]

[mcp_servers.langfuse.env]
LANGFUSE_PUBLIC_KEY = "pk-..."
LANGFUSE_SECRET_KEY = "sk-..."
LANGFUSE_HOST = "https://cloud.langfuse.com"
```

Or via CLI:
```bash
codex mcp add langfuse \
  --env LANGFUSE_PUBLIC_KEY=pk-... \
  --env LANGFUSE_SECRET_KEY=sk-... \
  --env LANGFUSE_HOST=https://cloud.langfuse.com \
  -- uvx langfuse-mcp
```

### Cursor

Create `.cursor/mcp.json` in your project:
```json
{
  "mcpServers": {
    "langfuse": {
      "command": "uvx",
      "args": ["langfuse-mcp"],
      "env": {
        "LANGFUSE_PUBLIC_KEY": "pk-...",
        "LANGFUSE_SECRET_KEY": "sk-...",
        "LANGFUSE_HOST": "https://cloud.langfuse.com"
      }
    }
  }
}
```

Or use the deeplink for quick setup:
```
cursor://anysphere.cursor-deeplink/mcp/install?name=langfuse-mcp&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJsYW5nZnVzZS1tY3AiXX0=
```

### Claude Desktop

Add to Claude Desktop settings:
```json
{
  "mcpServers": {
    "langfuse": {
      "command": "uvx",
      "args": ["langfuse-mcp"],
      "env": {
        "LANGFUSE_PUBLIC_KEY": "pk-...",
        "LANGFUSE_SECRET_KEY": "sk-...",
        "LANGFUSE_HOST": "https://cloud.langfuse.com"
      }
    }
  }
}
```

## Usage

### Selective Tool Loading

Load only the tool groups you need to reduce token overhead:

```bash
# Load only trace and prompt tools
langfuse-mcp --tools traces,prompts

# Available groups: traces, observations, sessions, exceptions, prompts, schema
```

Or via environment variable:
```bash
export LANGFUSE_MCP_TOOLS=traces,prompts
```

### Output Modes

Each tool supports different output modes:

| Mode | Description |
|------|-------------|
| `compact` | Summary with large values truncated (default) |
| `full_json_string` | Complete data as JSON string |
| `full_json_file` | Save to file, return summary with path |

### Logging

```bash
# Debug logging to console
langfuse-mcp --log-level DEBUG --log-to-console

# Custom log file location
export LANGFUSE_MCP_LOG_FILE=/var/log/langfuse_mcp.log
```

Default log location: `/tmp/langfuse_mcp.log`

## Development

```bash
git clone https://github.com/avivsinai/langfuse-mcp.git
cd langfuse-mcp

# Create virtual environment
uv venv --python 3.11 .venv
source .venv/bin/activate

# Install with dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Lint and format
ruff check --fix . && ruff format .
```

## Version Management

This project uses Git tags for versioning:
1. Tag: `git tag v1.0.0`
2. Push: `git push --tags`
3. GitHub Actions builds and publishes to PyPI

See [CHANGELOG.md](CHANGELOG.md) for release history.

## Contributing

Contributions welcome! Please submit a Pull Request.

## License

MIT License - see [LICENSE](LICENSE) for details.
