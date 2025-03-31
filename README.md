# Langfuse MCP (Model Context Protocol)

This project provides a Model Context Protocol (MCP) server for Langfuse, allowing AI agents to query Langfuse trace data for better debugging and observability.

## Features

- Integration with Langfuse for trace and observation data
- Tool suite for AI agents to query trace data
- Exception and error tracking capabilities
- Session and user activity monitoring

## Version Management

This project uses dynamic versioning based on Git tags:

1. The version is automatically determined from git tags using `uv-dynamic-versioning`
2. To create a new release:
   - Tag your commit with `git tag v0.1.2` (following semantic versioning)
   - Push the tag with `git push --tags`
   - Create a GitHub release from the tag
3. The GitHub workflow will automatically build and publish the package with the correct version to PyPI

For a detailed history of changes, please see the [CHANGELOG.md](CHANGELOG.md) file.

## Development

To run the server locally:

```bash
uvx langfuse-mcp --public-key YOUR_KEY --secret-key YOUR_SECRET --host https://cloud.langfuse.com
```

## Installation

```bash
pip install langfuse-mcp
```

## Setup and Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/langfuse-mcp.git
cd langfuse-mcp
```

2. Install uv (if not already installed):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

3. Create and activate a virtual environment with uv:
```bash
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

4. Install dependencies with uv:
```bash
uv pip install -e .
```

5. Set up Langfuse credentials as environment variables:
```bash
export LANGFUSE_SECRET_KEY="your-secret-key"
export LANGFUSE_PUBLIC_KEY="your-public-key"
export LANGFUSE_HOST="https://cloud.langfuse.com"  # Or your self-hosted URL
```

## Usage

### Running the MCP Server

To start the MCP server:

```bash
uv run -m langfuse_mcp
```

### Available Tools

The MCP server provides the following tools for AI agents:

- `find_traces` - Find traces based on criteria like user ID, session ID, etc.
- `find_exceptions` - Find exceptions and errors in traces
- `find_exceptions_in_file` - Find exceptions in a specific file
- `get_session` - Get session details
- `get_user_sessions` - Get all sessions for a user
- `get_error_count` - Get the count of errors
- `get_exception_details` - Get detailed information about an exception
- `get_trace` - Get a specific trace by ID
- `get_observation` - Get a specific observation by ID
- `get_observations_by_type` - Get observations filtered by type

### Output Modes and File Paths

Each tool supports different output modes to control the level of detail in responses:

- `compact` (default): Returns a summary with large values truncated
- `full_json_string`: Returns the complete data as a JSON string
- `full_json_file`: Saves the complete data to a file and returns a summary with file information

When using `full_json_file` mode, the file path information is included in the response in these ways:

1. For single object responses (dictionaries), the file path is included directly in the object:
   ```json
   {
     "id": "trace_12345",
     "name": "Example Trace",
     "observations": [...],
     "_file_save_info": {
       "status": "success",
       "message": "Full data saved successfully.",
       "file_path": "/tmp/langfuse_mcp_dumps/trace_12345_20230101_120000.json"
     },
     "_full_json_file_path": "/tmp/langfuse_mcp_dumps/trace_12345_20230101_120000.json",
     "_message": "Response summarized. Full details in the saved file."
   }
   ```

2. For list responses, the list is wrapped in a special structure to preserve the list while adding file info:
   ```json
   {
     "_type": "list_response",
     "_items": [
       { "id": "trace_1", "name": "First Trace", ... },
       { "id": "trace_2", "name": "Second Trace", ... },
       ...
     ],
     "_count": 5,
     "_file_save_info": {
       "status": "success",
       "message": "Full data saved successfully.",
       "file_path": "/tmp/langfuse_mcp_dumps/traces_20230101_120000.json"
     },
     "_full_json_file_path": "/tmp/langfuse_mcp_dumps/traces_20230101_120000.json",
     "_message": "Response contains 5 items. Full details in the saved file."
   }
   ```

This approach ensures that file path information is always available in a consistent and predictable way, regardless of whether the response is a single object or a list of objects.

### Testing

To run the test client:

```bash
uv run test_mcp_client.py
```

See [the testing documentation](langfuse_mcp/tests/README.md) for more details on the testing approach.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

# Langfuse MCP Cache Management

This document provides details about how caching is implemented in the Langfuse MCP server.

### Cache Management Improvements

We use the `cachetools` library to implement efficient caching with proper size limits:

1. Replaced custom cache implementation with `cachetools.LRUCache` for better reliability
2. Added a configurable cache size limit via the `CACHE_SIZE` constant
3. Leveraged `cachetools.cached` decorator for function memoization

The implementation automatically evicts the least recently used items when caches exceed their size limits, preventing unbounded memory growth in long-running servers.

### Implementation Details

- `langfuse_mcp/__main__.py`: Uses `cachetools.LRUCache` and `cachetools.cached` for all caching needs

### Configuration

The cache size can be configured by modifying the `CACHE_SIZE` constant at the top of the `__main__.py` file. The default value is 1000 items per cache.

```python
# Constants
HOUR = 60  # minutes
DAY = 24 * HOUR
CACHE_SIZE = 1000  # Maximum number of items to store in caches
```

### How It Works

We use the `cachetools` library which provides several caching implementations:

```python
from cachetools import LRUCache, cached, keys

# Create caches with size limits
_OBSERVATION_CACHE = LRUCache(maxsize=CACHE_SIZE)

# Cached function with LRU eviction
@cached(cache=LRUCache(maxsize=CACHE_SIZE))
def _get_cached_observation(langfuse_client, observation_id: str):
    # Function logic here
```

This implementation automatically removes the oldest accessed items when the cache exceeds its maximum size.
