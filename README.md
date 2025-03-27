# Langfuse MCP Server

This repository contains a Model Context Protocol (MCP) server with tools that can access traces, sessions, and metrics stored in Langfuse using the Langfuse SDK.

This MCP server enables LLMs to retrieve and analyze your application's telemetry data without needing to write SQL queries.

## Available Tools

- **`find_traces`** - Retrieve traces based on filters
  - **Arguments:**
    - `name`: Optional[str] - Name of the trace
    - `user_id`: Optional[str] - User ID
    - `session_id`: Optional[str] - Session ID
    - `version`: Optional[str] - Application version
    - `metadata`: Optional[dict] - Metadata to filter on
    - `from_timestamp`: Optional[datetime] - Start time (ISO 8601)
    - `to_timestamp`: Optional[datetime] - End time (ISO 8601)
    - `page`: int - Page number (default: 1)
    - `limit`: int - Number of traces per page (default: 50)

- **`find_exceptions`** - Get exception counts grouped by file, function, or type
  - **Arguments:**
    - `age`: int - Number of minutes to look back
    - `group_by`: str - Field to group by ('file', 'function', 'type')

- **`get_exception_details`** - Get detailed exception information for a trace or span
  - **Arguments:**
    - `trace_id`: str - ID of the trace
    - `span_id`: Optional[str] - ID of the span (if specified, get exceptions for that span only)

- **`get_session`** - Retrieve a session by ID
  - **Arguments:**
    - `session_id`: str - ID of the session

- **`get_user_sessions`** - Retrieve sessions for a user within a time range
  - **Arguments:**
    - `user_id`: str - ID of the user
    - `from_timestamp`: Optional[datetime] - Start time (ISO 8601)
    - `to_timestamp`: Optional[datetime] - End time (ISO 8601)

- **`get_error_count`** - Get the number of traces with exceptions within the last N minutes
  - **Arguments:**
    - `age`: int - Number of minutes to look back

- **`get_data_schema`** - Get the schema of trace, span, and event objects
  - **No arguments**

## Setup

### Install `uv`

Ensure `uv` is installed to manage dependencies and run the server. See the [uv installation docs](https://docs.astral.sh/uv/getting-started/installation/).

### Obtain Langfuse Credentials

You need your Langfuse public key and secret key from your project settings (cloud or self-hosted).

### Install with `uv`

```bash
uv pip install langfuse-mcp
```

### Manually Run the Server

Use command-line flags:

```bash
uv run -m langfuse_mcp --public-key YOUR_PUBLIC_KEY --secret-key YOUR_SECRET_KEY
```

You can also run directly from source:

```bash
git clone https://github.com/langfuse/langfuse-mcp.git
cd langfuse-mcp
uv pip install -e .
uv run -m langfuse_mcp --public-key YOUR_PUBLIC_KEY --secret-key YOUR_SECRET_KEY
```

## Configuration with MCP Clients

### Cursor

Create a `.cursor/mcp.json` file in your project root:

```json
{
  "mcpServers": {
    "langfuse": {
      "command": "uv",
      "args": ["run", "-m", "langfuse_mcp", "--public-key", "YOUR_PUBLIC_KEY", "--secret-key", "YOUR_SECRET_KEY", "--host", "https://cloud.langfuse.com"]
    }
  }
}
```

### Claude Desktop

Add to your Claude settings:

```json
{
  "command": ["uv"],
  "args": ["run", "-m", "langfuse_mcp", "--public-key", "YOUR_PUBLIC_KEY", "--secret-key", "YOUR_SECRET_KEY", "--host", "https://cloud.langfuse.com"],
  "type": "stdio"
}
```

### Cline

Add to your Cline settings in `cline_mcp_settings.json`:

```json
{
  "mcpServers": {
    "langfuse": {
      "command": "uv",
      "args": ["run", "-m", "langfuse_mcp", "--public-key", "YOUR_PUBLIC_KEY", "--secret-key", "YOUR_SECRET_KEY", "--host", "https://cloud.langfuse.com"],
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

### Customization - Host URL

The default API endpoint is `https://cloud.langfuse.com` (EU region). You can override it with:

Command-line argument:
```bash
uv run -m langfuse_mcp --host https://us.cloud.langfuse.com
```

In your client configuration:
```json
{
  "mcpServers": {
    "langfuse": {
      "command": "uv",
      "args": ["run", "-m", "langfuse_mcp", "--public-key", "YOUR_PUBLIC_KEY", "--secret-key", "YOUR_SECRET_KEY", "--host", "https://us.cloud.langfuse.com"],
    }
  }
}
```

#### Available Regions

- **EU (Default)**: `https://cloud.langfuse.com`
- **US**: `https://us.cloud.langfuse.com`
- **Self-hosted**: Your custom Langfuse URL (e.g., `https://langfuse.your-company.com`)

## Example Interactions

1. **Find traces from the last hour:**
   ```json
   {
     "name": "find_traces",
     "arguments": {
       "from_timestamp": "2024-10-15T09:00:00Z",
       "to_timestamp": "2024-10-15T10:00:00Z",
       "limit": 10
     }
   }
   ```
   **Response:**
   ```json
   [
     {"id": "trace1", "name": "trace_name", "user_id": "user123", "session_id": "session456", ...},
     ...
   ]
   ```

2. **Get exception counts grouped by file:**
   ```json
   {
     "name": "find_exceptions",
     "arguments": {
       "age": 60,
       "group_by": "file"
     }
   }
   ```
   **Response:**
   ```json
   [
     {"group": "app/main.py", "count": 5},
     {"group": "utils/helper.py", "count": 3}
   ]
   ```

3. **Get detailed exceptions for a trace:**
   ```json
   {
     "name": "get_exception_details",
     "arguments": {
       "trace_id": "abc123"
     }
   }
   ```
   **Response:**
   ```json
   [
     {
       "observation_id": "obs123",
       "observation_name": "process_data",
       "timestamp": "2024-10-15T10:00:00Z",
       "exception_type": "ZeroDivisionError",
       "exception_message": "division by zero",
       "stacktrace": "Traceback (most recent call last):\n  File \"app.py\", line 42...",
       "file": "app/utils.py",
       "function": "calculate_ratio",
       "line_number": 42
     },
     ...
   ]
   ```

4. **Get error count for the last 24 hours:**
   ```json
   {
     "name": "get_error_count",
     "arguments": {
       "age": 1440
     }
   }
   ```
   **Response:**
   ```json
   {
     "error_count": 12,
     "time_range": {
       "from": "2024-10-14T10:00:00Z",
       "to": "2024-10-15T10:00:00Z"
     }
   }
   ```

5. **Get sessions for a user:**
   ```json
   {
     "name": "get_user_sessions",
     "arguments": {
       "user_id": "user123",
       "from_timestamp": "2024-10-10T00:00:00Z",
       "to_timestamp": "2024-10-15T23:59:59Z"
     }
   }
   ```
   **Response:**
   ```json
   [
     {"id": "session1", "user_id": "user123", "created_at": "2024-10-12T14:22:33Z", ...},
     {"id": "session2", "user_id": "user123", "created_at": "2024-10-13T09:15:44Z", ...}
   ]
   ```

## Examples of Questions for Claude

Now you can ask Claude natural language questions about your Langfuse data:

1. "Show me all traces from the last 30 minutes."
2. "What are the most common exception types in the past hour?"
3. "Get details about exceptions in trace 'abc123'."
4. "How many errors occurred in the last 24 hours?"
5. "List all sessions for user 'user123' from yesterday."
6. "What files have the most exceptions in the past week?"
7. "Show me the stack trace for the most recent ZeroDivisionError exception."
8. "How many unique users had errors in their sessions today?"
9. "What's the structure of a trace object in Langfuse?"
10. "Find all traces with the tag 'production' from the last 3 hours."
11. "What are all the filtering options I can use with traces?"
12. "Display a summary of exceptions by error type for the last 48 hours."

## Getting Started

1. Obtain your Langfuse public and secret keys from your project settings.
2. Install the MCP server:
   ```bash
   uv pip install langfuse-mcp
   ```
3. Run the MCP server:
   ```bash
   # Default EU region
   uv run -m langfuse_mcp --public-key YOUR_PUBLIC_KEY --secret-key YOUR_SECRET_KEY
   
   # US region
   uv run -m langfuse_mcp --public-key YOUR_PUBLIC_KEY --secret-key YOUR_SECRET_KEY --host https://us.cloud.langfuse.com
   
   # Self-hosted
   uv run -m langfuse_mcp --public-key YOUR_PUBLIC_KEY --secret-key YOUR_SECRET_KEY --host https://your-langfuse-instance.com
   ```
4. Configure your preferred client (Cursor, Claude Desktop, or Cline).
5. Start analyzing your Langfuse data!

## Contributing

Contributions are welcome! Add new tools, enhance functionality, or improve docs. See the [Model Context Protocol servers repository](https://github.com/modelcontextprotocol/servers) for examples.

## License

Licensed under the MIT License.
