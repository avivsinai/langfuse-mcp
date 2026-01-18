# Langfuse MCP Tool Reference

Complete documentation for all 18 Langfuse MCP tools.

## Tools by Category

| Category | Tools |
|----------|-------|
| Traces | fetch_traces, fetch_trace |
| Observations | fetch_observations, fetch_observation |
| Sessions | fetch_sessions, get_session_details, get_user_sessions |
| Exceptions | find_exceptions, find_exceptions_in_file, get_exception_details, get_error_count |
| Prompts | list_prompts, get_prompt, get_prompt_unresolved, create_text_prompt, create_chat_prompt, update_prompt_labels |
| Schema | get_data_schema |

## Output Modes

Most tools support three output modes via the `output_mode` parameter:

| Mode | Description |
|------|-------------|
| `compact` | Summary with large values truncated (default) |
| `full_json_string` | Complete data as JSON string (returns string, not object) |
| `full_json_file` | Save to file, return summary with path |

**Exceptions:** `find_exceptions` and `get_error_count` do not support `output_mode` (always return compact format).

## Filter Semantics

| Filter | Matching Rule |
|--------|---------------|
| `name` | Case-insensitive substring match |
| `tags` | Comma-separated, matches ANY tag (OR logic) |
| `metadata` | Exact key/value match, top-level keys only |
| `user_id`, `session_id`, `trace_id` | Exact match |

## Sort Order

All paginated results are sorted by **timestamp descending** (newest first).

## Pagination

Tools that return lists support pagination via `page` and `limit` parameters:

- `page`: Page number (starts at 1)
- `limit`: Items per page (default 50, max varies by tool)

**Response metadata includes:**
```json
{
  "metadata": {
    "page": 1,
    "total": 147,
    "next_page": 2,
    "item_count": 50
  }
}
```

**Pattern:** If `next_page` exists, call again with `page=next_page` to get more results.

**Tip:** For large datasets, use `output_mode="full_json_file"` to avoid context overflow.

---

## Traces

### fetch_traces

Search and filter traces with pagination.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `age` | int | Yes | - | Look back window in minutes from now (e.g., 1440 for 24h). Max 10080 (7 days). |
| `name` | string | No | null | Name filter (case-insensitive substring match) |
| `user_id` | string | No | null | User ID to filter traces by (exact match) |
| `session_id` | string | No | null | Session ID to filter traces by (exact match) |
| `metadata` | object | No | null | Metadata fields to filter by (exact key/value match) |
| `tags` | string | No | null | Tag or comma-separated list of tags (matches any) |
| `page` | int | No | 1 | Page number for pagination (starts at 1) |
| `limit` | int | No | 50 | Maximum traces per page |
| `include_observations` | bool | No | false | Include full observation objects instead of just IDs |
| `output_mode` | string | No | "compact" | Output format |

**Returns:** List of trace objects with metadata including pagination info.

**Example:**
```
fetch_traces(age=1440, user_id="user_123", include_observations=true)
```

---

### fetch_trace

Fetch a specific trace by ID.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `trace_id` | string | Yes | - | The ID of the trace to fetch |
| `include_observations` | bool | No | false | Include full observation objects |
| `output_mode` | string | No | "compact" | Output format |

**Returns:** Single trace object with all details.

**Example:**
```
fetch_trace(trace_id="abc-123", include_observations=true, output_mode="full_json_file")
```

---

## Observations

### fetch_observations

Search and filter observations (spans, generations, events).

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `age` | int | Yes | - | Look back window in minutes from now. Max 10080 (7 days). |
| `type` | string | No | null | Filter by type: "SPAN", "GENERATION", or "EVENT" |
| `name` | string | No | null | Name filter (case-insensitive substring match) |
| `user_id` | string | No | null | User ID filter (exact match) |
| `trace_id` | string | No | null | Trace ID filter (exact match) |
| `parent_observation_id` | string | No | null | Parent observation ID filter (exact match) |
| `page` | int | No | 1 | Page number |
| `limit` | int | No | 50 | Max items per page |
| `output_mode` | string | No | "compact" | Output format |

**Returns:** List of observation objects.

**Example:**
```
fetch_observations(age=60, type="GENERATION", name="chat-completion")
```

---

### fetch_observation

Fetch a specific observation by ID.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `observation_id` | string | Yes | - | The ID of the observation to fetch |
| `output_mode` | string | No | "compact" | Output format |

**Returns:** Single observation object with full details.

---

## Sessions

### fetch_sessions

List recent sessions with pagination.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `age` | int | Yes | - | Look back window in minutes from now. Max 10080 (7 days). |
| `page` | int | No | 1 | Page number |
| `limit` | int | No | 50 | Max items per page |
| `output_mode` | string | No | "compact" | Output format |

**Returns:** List of session summaries.

---

### get_session_details

Get detailed session info by ID.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `session_id` | string | Yes | - | The session ID to fetch |
| `output_mode` | string | No | "compact" | Output format |

**Returns:** Session object with all traces.

---

### get_user_sessions

Get all sessions for a user.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `user_id` | string | Yes | - | The user ID to look up |
| `age` | int | Yes | - | Look back window in minutes from now. Max 10080 (7 days). |
| `page` | int | No | 1 | Page number |
| `limit` | int | No | 50 | Max items per page |
| `output_mode` | string | No | "compact" | Output format |

**Returns:** List of sessions for the user.

---

## Exceptions

### find_exceptions

Find exceptions grouped by file, function, or type.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `age` | int | Yes | - | Look back window in minutes from now. Max 10080 (7 days). |
| `group_by` | string | No | "file" | How to group: "file", "function", or "type" |

**Returns:** List of `{group: string, count: int}` objects, sorted by count descending (top 50).

**Note:** Does not support `output_mode` parameter.

**Example:**
```
find_exceptions(age=1440, group_by="type")
```

---

### find_exceptions_in_file

Find exceptions in a specific file.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `filepath` | string | Yes | - | Path to the file as recorded in Langfuse metadata (typically relative to project root, e.g., `src/utils/ai.ts`) |
| `age` | int | Yes | - | Look back window in minutes from now. Max 10080 (7 days). |
| `output_mode` | string | No | "compact" | Output format |

**Returns:** List of exception details (top 10, newest first):
- `observation_id`, `trace_id`, `timestamp`
- `exception_type`, `exception_message`, `exception_stacktrace`
- `function`, `line_number`

**Example:**
```
find_exceptions_in_file(filepath="src/ai/chat.py", age=1440)
```

---

### get_exception_details

Get detailed exception info for a trace/span.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `trace_id` | string | Yes | - | The trace ID to analyze |
| `span_id` | string | No | null | Optional span ID to filter by |
| `output_mode` | string | No | "compact" | Output format |

**Returns:** List of exceptions with full context including observation details.

---

### get_error_count

Get total error count.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `age` | int | Yes | - | Look back window in minutes from now. Max 10080 (7 days). |

**Returns:** `{data: {error_count: int}, metadata: {...}}`

**Note:** Does not support `output_mode` parameter.

---

## Prompts

### list_prompts

List and filter prompts in the project.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `name` | string | No | null | Filter by exact prompt name |
| `label` | string | No | null | Filter by label (e.g., "production") |
| `tag` | string | No | null | Filter by tag |
| `page` | int | No | 1 | Page number |
| `limit` | int | No | 50 | Max items per page (max 100) |

**Returns:** List of prompt metadata:
- `name`, `type` ("text" or "chat")
- `versions`, `labels`, `tags`
- `lastUpdatedAt`, `lastConfig`

---

### get_prompt

Fetch a specific prompt with resolved dependencies.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `name` | string | Yes | - | The prompt name |
| `label` | string | No | null | Label to fetch (e.g., "production"). Mutually exclusive with version. |
| `version` | int | No | null | Specific version number. Mutually exclusive with label. |

**Returns:** Prompt object:
- `id`, `name`, `version`, `type`
- `prompt` (string for text, list for chat)
- `labels`, `tags`, `config`

**Example:**
```
get_prompt(name="chat-system", label="production")
```

---

### get_prompt_unresolved

Fetch a prompt WITHOUT resolving dependencies.

Returns raw prompt content with dependency tags intact (e.g., `@@@langfusePrompt:name=xxx@@@`).

**Parameters:** Same as `get_prompt`.

**Returns:** Same structure but with dependency tags preserved in prompt content.

---

### create_text_prompt

Create a new text prompt version.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `name` | string | Yes | - | The prompt name |
| `prompt` | string | Yes | - | Prompt text content (supports `{{variables}}`) |
| `labels` | list[string] | No | null | Labels to assign (e.g., ["staging"]) |
| `config` | object | No | null | Model config (see example below) |
| `tags` | list[string] | No | null | Tags for organization |
| `commit_message` | string | No | null | Commit message describing changes |

**Config Example:**
```json
{
  "model": "gpt-4",
  "temperature": 0.7,
  "max_tokens": 1000,
  "top_p": 1.0
}
```

**Returns:** Created prompt object.

**Note:** Prompts are immutable. Creating a new version is the only way to update content. Labels are unique across versions - assigning a label here removes it from other versions.

**Example:**
```
create_text_prompt(
  name="greeting",
  prompt="Hello {{name}}, welcome to {{app}}!",
  labels=["staging"],
  config={"model": "gpt-4", "temperature": 0.7},
  commit_message="feat: add personalized greeting"
)
```

---

### create_chat_prompt

Create a new chat prompt version.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `name` | string | Yes | - | The prompt name |
| `prompt` | list[object] | Yes | - | Chat messages (see format below) |
| `labels` | list[string] | No | null | Labels to assign |
| `config` | object | No | null | Model config (same as create_text_prompt) |
| `tags` | list[string] | No | null | Tags for organization |
| `commit_message` | string | No | null | Commit message |

**Prompt Format:**
```json
[
  {"role": "system", "content": "You are a helpful assistant."},
  {"role": "user", "content": "{{user_input}}"}
]
```

**Returns:** Created prompt object.

**Example:**
```
create_chat_prompt(
  name="assistant",
  prompt=[
    {"role": "system", "content": "You are a helpful coding assistant."},
    {"role": "user", "content": "{{question}}"}
  ],
  labels=["staging"],
  config={"model": "gpt-4", "temperature": 0.3}
)
```

---

### update_prompt_labels

Update labels for a specific prompt version.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `name` | string | Yes | - | The prompt name |
| `version` | int | Yes | - | The version to update |
| `labels` | list[string] | Yes | - | Labels to add (existing labels preserved) |

**Returns:** Updated prompt object.

**Note:** This is the only supported mutation for existing prompts. Labels are unique across versions - adding a label here removes it from other versions.

**Example (promote to production):**
```
update_prompt_labels(name="greeting", version=3, labels=["production"])
```

**Example (rollback):**
```
update_prompt_labels(name="greeting", version=2, labels=["production"])
```

---

## Schema

### get_data_schema

Get schema information for response structures.

**Parameters:** None (dummy parameter for compatibility).

**Returns:** Documentation of response schemas for all tools.

---

## Response Format

Tools return responses in one of two formats depending on `output_mode`:

### For `compact` and `full_json_file` modes:

```json
{
  "data": [...] | {...},
  "metadata": {
    "item_count": 10,
    "page": 1,
    "total": 100,
    "next_page": 2,
    "file_path": "/tmp/langfuse_mcp/traces_2024...json",
    "file_info": {...}
  }
}
```

### For `full_json_string` mode:

Returns a **string** containing serialized JSON (not an object). Parse it if you need structured access.

---

## Example Response (compact)

```json
{
  "data": [
    {
      "id": "trace-abc-123",
      "name": "chat-completion",
      "user_id": "user-456",
      "timestamp": "2024-01-15T10:30:00Z",
      "observations": ["obs-1", "obs-2"]
    }
  ],
  "metadata": {
    "item_count": 1,
    "page": 1,
    "total": 47,
    "next_page": 2,
    "file_path": null,
    "file_info": null
  }
}
```

## Example Response (full_json_file)

```json
{
  "data": [{"id": "trace-abc-123", "...": "truncated"}],
  "metadata": {
    "item_count": 1,
    "page": 1,
    "total": 47,
    "file_path": "/tmp/langfuse_mcp/traces_20240115_103000.json",
    "file_info": {
      "size_bytes": 15234,
      "created_at": "2024-01-15T10:30:05Z"
    }
  }
}
```
