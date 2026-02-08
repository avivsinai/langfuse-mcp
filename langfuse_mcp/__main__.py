"""MCP integration for Langfuse SDK.

This module provides the Langfuse MCP (Machine Context Protocol) integration, allowing
agents to query trace data, observations, and exceptions from Langfuse.
"""

import argparse
import inspect
import json
import logging
import os
import sys
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Annotated, Any, Literal, cast

if sys.version_info >= (3, 14):
    raise SystemExit(
        "langfuse-mcp currently requires Python 3.13 or earlier. "
        "Please rerun with `uvx --python 3.11 langfuse-mcp` or pin a supported interpreter."
    )

from cachetools import LRUCache
from langfuse import Langfuse
from mcp.server.fastmcp import Context, FastMCP
from pydantic import AfterValidator, BaseModel, Field

try:
    from pydantic.fields import FieldInfo
except ImportError:  # pragma: no cover - pydantic stubbed in tests
    FieldInfo = None

try:
    __version__ = version("langfuse-mcp")
except PackageNotFoundError:
    # Package is not installed (development mode)
    __version__ = "0.1.1.dev0"

# Set up logging with rotation
LOG_FILE = Path(os.getenv("LANGFUSE_MCP_LOG_FILE", "/tmp/langfuse_mcp.log")).expanduser()
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,  # Keep 5 backup files
    encoding="utf-8",
)

formatter = logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT)
file_handler.setFormatter(formatter)


def configure_logging(log_level: str, log_to_console: bool) -> logging.Logger:
    """Configure application logging based on CLI flags."""
    level = logging.getLevelName(log_level.upper()) if isinstance(log_level, str) else logging.INFO

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    file_handler.setLevel(level)
    root_logger.addHandler(file_handler)

    if log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        root_logger.addHandler(console_handler)

    return logging.getLogger("langfuse_mcp")


logger = logging.getLogger("langfuse_mcp")

# Constants
HOUR = 60  # minutes
DAY = 24 * HOUR
MAX_AGE_MINUTES = 7 * DAY
MAX_FIELD_LENGTH = 500  # Maximum string length for field values
MAX_RESPONSE_SIZE = 20000  # Maximum size of response object in characters
TRUNCATE_SUFFIX = "..."  # Suffix to add to truncated fields

# Tool groups for selective loading (reduces token overhead)
TOOL_GROUPS = {
    "traces": ["fetch_traces", "fetch_trace"],
    "observations": ["fetch_observations", "fetch_observation"],
    "sessions": ["fetch_sessions", "get_session_details", "get_user_sessions"],
    "exceptions": ["find_exceptions", "find_exceptions_in_file", "get_exception_details", "get_error_count"],
    "prompts": ["get_prompt", "get_prompt_unresolved", "list_prompts", "create_text_prompt", "create_chat_prompt", "update_prompt_labels"],
    "schema": ["get_data_schema"],
    "datasets": [
        "list_datasets",
        "get_dataset",
        "list_dataset_items",
        "get_dataset_item",
        "create_dataset",
        "create_dataset_item",
        "delete_dataset_item",
    ],
}
ALL_TOOL_GROUPS = set(TOOL_GROUPS.keys())

# Tools that perform write operations (disabled in read-only mode)
WRITE_TOOLS = {
    "create_text_prompt",
    "create_chat_prompt",
    "update_prompt_labels",
    "create_dataset",
    "create_dataset_item",
    "delete_dataset_item",
}

# Common field names that often contain large values
LARGE_FIELDS = [
    "input",
    "output",
    "content",
    "prompt",
    "completion",
    "system_prompt",
    "user_prompt",
    "message",
    "exception.stacktrace",
    "exception.message",
    "stacktrace",
    # OTEL specific fields
    "llm.prompts",
    "llm.prompt",
    "llm.prompts.system",
    "llm.prompts.user",
    "llm.prompt.system",
    "llm.prompt.user",
    # Langfuse-specific fields
    "langfusePrompt",
    "prompt.content",
    "prompt.messages",
    "prompt.system",
    "metadata.langfusePrompt",
    "metadata.system_prompt",
    "metadata.prompt",
    # Additional attribute paths
    "attributes.llm.prompts",
    "attributes.llm.prompt",
    "attributes.system_prompt",
    "attributes.prompt",
    "attributes.input",
    "attributes.output",
    # Dataset-specific fields
    "expected_output",
    "expectedOutput",
    "input_schema",
    "expected_output_schema",
]

LOWER_LARGE_FIELDS = {field.lower() for field in LARGE_FIELDS}

# Fields that are considered essential and should be preserved even in minimal representation
ESSENTIAL_FIELDS = [
    "id",
    "trace_id",
    "observation_id",
    "parent_observation_id",
    "name",
    "type",
    "timestamp",
    "start_time",
    "end_time",
    "level",
    "status_message",
    "user_id",
    "session_id",
]


# Literal enum for output modes
class OutputMode(str, Enum):
    """Enum for output modes controlling response format."""

    COMPACT = "compact"
    FULL_JSON_STRING = "full_json_string"
    FULL_JSON_FILE = "full_json_file"


OUTPUT_MODE_LITERAL = Literal["compact", "full_json_string", "full_json_file"]

# Define a custom Dict type for our standardized response format
ResponseDict = dict[str, Any]


def _ensure_output_mode(mode: OUTPUT_MODE_LITERAL | OutputMode | str | OutputMode) -> OutputMode:
    """Normalize user-provided output mode values."""
    if isinstance(mode, OutputMode):
        return mode

    try:
        return OutputMode(str(mode))
    except (ValueError, TypeError):
        logger.warning(f"Unknown output mode '{mode}', defaulting to compact")
        return OutputMode.COMPACT


def _load_env_file(env_path: Path | None = None) -> None:
    """Load environment variables from a `.env` file if present."""
    if env_path is None:
        env_path = Path(__file__).resolve().parent.parent / ".env"

    if not env_path.exists() or not env_path.is_file():
        return

    try:
        with env_path.open("r", encoding="utf-8") as env_file:
            for line in env_file:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                key = key.strip()
                value = value.strip()
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError as exc:
        logger.warning(f"Unable to load environment file {env_path}: {exc}")


def _read_env_defaults() -> dict[str, Any]:
    """Read environment defaults used by the CLI."""
    # Parse timeout with fallback to our default of 30s (SDK defaults to 5s which is too aggressive)
    timeout_str = os.getenv("LANGFUSE_TIMEOUT", "30")
    try:
        timeout = int(timeout_str)
    except ValueError:
        timeout = 30
    return {
        "public_key": os.getenv("LANGFUSE_PUBLIC_KEY"),
        "secret_key": os.getenv("LANGFUSE_SECRET_KEY"),
        "host": os.getenv("LANGFUSE_HOST") or "https://cloud.langfuse.com",
        "timeout": timeout,
        "log_level": os.getenv("LANGFUSE_LOG_LEVEL", "INFO"),
        "log_to_console": os.getenv("LANGFUSE_LOG_TO_CONSOLE", "").lower() in {"1", "true", "yes"},
    }


def _build_arg_parser(env_defaults: dict[str, Any]) -> argparse.ArgumentParser:
    """Construct the CLI argument parser using provided defaults."""
    parser = argparse.ArgumentParser(description="Langfuse MCP Server")
    parser.add_argument(
        "--public-key",
        type=str,
        default=env_defaults["public_key"],
        required=env_defaults["public_key"] is None,
        help="Langfuse public key",
    )
    parser.add_argument(
        "--secret-key",
        type=str,
        default=env_defaults["secret_key"],
        required=env_defaults["secret_key"] is None,
        help="Langfuse secret key",
    )
    parser.add_argument("--host", type=str, default=env_defaults["host"], help="Langfuse host URL")
    parser.add_argument(
        "--timeout",
        type=int,
        default=env_defaults["timeout"],
        help="API timeout in seconds (default: 30). SDK defaults to 5s which is too aggressive. Set via LANGFUSE_TIMEOUT.",
    )
    parser.add_argument("--cache-size", type=int, default=100, help="Size of LRU caches used for caching data")
    parser.add_argument(
        "--dump-dir",
        type=str,
        default="/tmp/langfuse_mcp_dumps",
        help=(
            "Directory to save full JSON dumps when 'output_mode' is 'full_json_file'. The directory will be created if it doesn't exist."
        ),
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=env_defaults["log_level"],
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
        help="Logging level (defaults to INFO).",
    )
    parser.add_argument(
        "--log-to-console",
        action="store_true",
        default=env_defaults["log_to_console"],
        help="Also emit logs to stdout in addition to the rotating file handler.",
    )
    parser.add_argument(
        "--no-log-to-console",
        action="store_false",
        dest="log_to_console",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--tools",
        type=str,
        default=os.getenv("LANGFUSE_MCP_TOOLS", "all"),
        help=(
            "Comma-separated tool groups to enable: traces,observations,sessions,exceptions,prompts,datasets,schema "
            "or 'all' (default). Reduces token overhead when only specific capabilities needed."
        ),
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        default=os.getenv("LANGFUSE_MCP_READ_ONLY", "").lower() in ("1", "true", "yes"),
        help="Disable all write operations (create/update/delete tools). Safer for read-only access.",
    )

    return parser


def _sdk_object_to_python(obj: Any) -> Any:
    """Convert Langfuse SDK models (pydantic/dataclasses) into plain Python types."""
    if obj is None:
        return None

    if isinstance(obj, (str, int, float, bool)):
        return obj

    if isinstance(obj, datetime):
        # Preserve timezone info when available
        return obj.isoformat()

    if isinstance(obj, (list, tuple, set)):
        return [_sdk_object_to_python(item) for item in obj]

    if isinstance(obj, dict):
        return {key: _sdk_object_to_python(value) for key, value in obj.items()}

    if hasattr(obj, "model_dump"):
        return _sdk_object_to_python(obj.model_dump())

    if hasattr(obj, "dict"):
        return _sdk_object_to_python(obj.dict())

    if hasattr(obj, "__dict__"):
        data = {key: value for key, value in vars(obj).items() if not key.startswith("_")}
        return _sdk_object_to_python(data)

    return obj


_MIN_SORT_DATETIME = datetime.min.replace(tzinfo=timezone.utc)


def _parse_datetime_for_sort(value: Any) -> datetime | None:
    """Parse ISO8601 timestamps (or datetimes) into an aware datetime.

    Used for stable sorting when timestamps can be strings, datetimes, or None.
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _datetime_sort_key(value: Any) -> datetime:
    """Return a datetime suitable for `key=` sorting with None-safe fallback."""
    return _parse_datetime_for_sort(value) or _MIN_SORT_DATETIME


def _normalize_field_default(value: Any) -> Any:
    """Treat pydantic FieldInfo defaults as unset values for direct function calls."""
    if FieldInfo is not None and isinstance(value, FieldInfo):
        return None
    return value


def _prompts_get(prompts_client: Any, *, name: str, **kwargs: Any) -> Any:
    """Call prompts.get with the correct parameter name across SDK versions."""
    try:
        params = inspect.signature(prompts_client.get).parameters
    except (TypeError, ValueError):
        params = {}

    call_kwargs = dict(kwargs)
    if "prompt_name" in params:
        call_kwargs["prompt_name"] = name
    else:
        call_kwargs["name"] = name

    return prompts_client.get(**call_kwargs)


def _prompts_get_supports_resolve(prompts_client: Any) -> bool:
    try:
        params = inspect.signature(prompts_client.get).parameters
    except (TypeError, ValueError):
        return False
    return "resolve" in params


def _extract_items_from_response(response: Any) -> tuple[list[Any], dict[str, Any]]:
    """Normalize Langfuse SDK list responses into items and pagination metadata."""
    if response is None:
        return [], {}

    if isinstance(response, dict):
        items = response.get("items") or response.get("data") or []
        pagination = response.get("meta") or {}
        return list(items), pagination

    if hasattr(response, "items"):
        items = getattr(response, "items")
        pagination = {
            "next_page": getattr(response, "next_page", None),
            "total": getattr(response, "total", None),
        }
        return list(items), pagination

    if hasattr(response, "data"):
        return list(response.data), {}

    if isinstance(response, list):
        return response, {}

    return [response], {}


def _metadata_matches(item: Any, metadata_filter: dict[str, Any]) -> bool:
    """Determine whether the provided item matches the requested metadata filter."""
    item_dict = _sdk_object_to_python(item)
    metadata = item_dict.get("metadata") or {}
    return all(metadata.get(key) == value for key, value in metadata_filter.items())


def _list_traces(
    langfuse_client: Any,
    *,
    limit: int,
    page: int,
    include_observations: bool,
    tags: list[str] | None,
    from_timestamp: datetime | None,
    name: str | None,
    user_id: str | None,
    session_id: str | None,
    metadata: dict[str, Any] | None,
) -> tuple[list[Any], dict[str, Any]]:
    """Fetch traces via the Langfuse SDK handling both v2 and v3 signatures."""
    if not hasattr(langfuse_client, "api") or not hasattr(langfuse_client.api, "trace"):
        raise RuntimeError("Unsupported Langfuse client: no trace listing method available")

    list_kwargs: dict[str, Any] = {
        "limit": limit or None,
        "page": page or None,
        "user_id": user_id,
        "name": name,
        "session_id": session_id,
        "from_timestamp": from_timestamp,
        "tags": tags,
    }

    # Include observation payloads via the fields selector when requested.
    if include_observations and metadata:
        list_kwargs["fields"] = "core,io,observations"
    elif include_observations:
        list_kwargs["fields"] = "core,observations"
    elif metadata:
        list_kwargs["fields"] = "core,io"

    list_kwargs = {k: v for k, v in list_kwargs.items() if v is not None}

    response = langfuse_client.api.trace.list(**list_kwargs)
    items, pagination = _extract_items_from_response(response)

    if metadata:
        items = [item for item in items if _metadata_matches(item, metadata)]
        pagination = {**pagination, "filtered_count": len(items)}

    return items, pagination


def _list_observations(
    langfuse_client: Any,
    *,
    limit: int,
    page: int,
    from_start_time: datetime | None,
    to_start_time: datetime | None,
    obs_type: str | None,
    name: str | None,
    user_id: str | None,
    trace_id: str | None,
    parent_observation_id: str | None,
    metadata: dict[str, Any] | None,
) -> tuple[list[Any], dict[str, Any]]:
    """Fetch observations via the Langfuse SDK handling v2/v3 differences."""
    if not hasattr(langfuse_client, "api") or not hasattr(langfuse_client.api, "observations"):
        raise RuntimeError("Unsupported Langfuse client: no observation listing method available")

    list_kwargs: dict[str, Any] = {
        "limit": limit or None,
        "page": page or None,
        "name": name,
        "user_id": user_id,
        "type": obs_type,
        "trace_id": trace_id,
        "parent_observation_id": parent_observation_id,
        "from_start_time": from_start_time,
        "to_start_time": to_start_time,
    }
    list_kwargs = {k: v for k, v in list_kwargs.items() if v is not None}

    response = langfuse_client.api.observations.get_many(**list_kwargs)
    items, pagination = _extract_items_from_response(response)

    if metadata:
        items = [item for item in items if _metadata_matches(item, metadata)]
        pagination = {**pagination, "filtered_count": len(items)}

    return items, pagination


def _get_observation(langfuse_client: Any, observation_id: str) -> Any:
    """Fetch a single observation using either the v3 or v2 SDK surface."""
    if hasattr(langfuse_client, "api") and hasattr(langfuse_client.api, "observations"):
        return langfuse_client.api.observations.get(observation_id=observation_id)

    if hasattr(langfuse_client, "fetch_observation"):
        response = langfuse_client.fetch_observation(observation_id)
        return getattr(response, "data", response)

    raise RuntimeError("Unsupported Langfuse client: no observation getter available")


def _get_trace(langfuse_client: Any, trace_id: str, include_observations: bool) -> Any:
    """Fetch a single trace handling SDK version differences.

    Note: Some Langfuse SDK versions do not support a `fields` selector on `get()`. We avoid
    passing `fields` here and rely on embedding observations separately when requested.
    """
    if not hasattr(langfuse_client, "api") or not hasattr(langfuse_client.api, "trace"):
        raise RuntimeError("Unsupported Langfuse client: no trace getter available")

    return langfuse_client.api.trace.get(trace_id=trace_id)


def _list_sessions(
    langfuse_client: Any,
    *,
    limit: int,
    page: int,
    from_timestamp: datetime,
) -> tuple[list[Any], dict[str, Any]]:
    """Fetch sessions via the Langfuse SDK handling v2/v3 differences."""
    if not hasattr(langfuse_client, "api") or not hasattr(langfuse_client.api, "sessions"):
        raise RuntimeError("Unsupported Langfuse client: no session listing method available")

    list_kwargs: dict[str, Any] = {
        "limit": limit or None,
        "page": page or None,
        "from_timestamp": from_timestamp,
    }
    list_kwargs = {k: v for k, v in list_kwargs.items() if v is not None}

    response = langfuse_client.api.sessions.list(**list_kwargs)
    return _extract_items_from_response(response)


def truncate_large_strings(
    obj: Any,
    max_length: int = MAX_FIELD_LENGTH,
    max_response_size: int = MAX_RESPONSE_SIZE,
    path: str = "",
    current_size: int = 0,
    truncation_level: int = 0,
) -> tuple[Any, int]:
    """Recursively process an object and truncate large string values with intelligent list handling.

    Args:
        obj: The object to process (dict, list, string, etc.)
        max_length: Maximum length for string values
        max_response_size: Maximum total response size in characters
        path: Current path in the object (for nested objects)
        current_size: Current size of the processed object
        truncation_level: Level of truncation to apply (0=normal, 1=aggressive, 2=minimal)

    Returns:
        Tuple of (processed object, size of processed object)
    """
    # Calculate adjusted max_length based on truncation level
    adjusted_max_length = max_length
    if truncation_level == 1:
        # More aggressive truncation for level 1
        adjusted_max_length = max(50, max_length // 2)
    elif truncation_level == 2:
        # Minimal representation for level 2 (extreme truncation)
        adjusted_max_length = max(20, max_length // 5)

    # Base case: if we've already exceeded max response size by a lot, return minimal representation
    if current_size > max_response_size * 1.5:
        return "[TRUNCATED]", len("[TRUNCATED]")

    # Handle different types
    if isinstance(obj, dict):
        result = {}
        result_size = 2  # Count braces

        # First pass: always process essential fields first
        for key in list(obj.keys()):
            if key in ESSENTIAL_FIELDS:
                processed_value, value_size = truncate_large_strings(
                    obj[key],
                    adjusted_max_length,
                    max_response_size,
                    f"{path}.{key}" if path else key,
                    current_size + result_size,
                    truncation_level,
                )
                result[key] = processed_value
                result_size += len(str(key)) + 2 + value_size  # key + colon + value size

        # Second pass: process known large fields next
        if truncation_level < 2:  # Skip detailed content at highest truncation level
            for key in list(obj.keys()):
                lower_key = key.lower()
                if lower_key in LOWER_LARGE_FIELDS or any(field in lower_key for field in LOWER_LARGE_FIELDS):
                    if key not in result:  # Skip if already processed
                        value = obj[key]
                        if isinstance(value, str) and len(value) > adjusted_max_length:
                            # For stacktraces, keep first and last few lines
                            if "stack" in key.lower() and "\n" in value:
                                lines = value.split("\n")
                                if len(lines) > 6:
                                    # Keep first 3 and last 3 lines for context
                                    truncated_stack = "\n".join(lines[:3] + ["..."] + lines[-3:])
                                    result[key] = truncated_stack
                                    logger.debug(f"Truncated stack in {path}.{key} from {len(lines)} lines to 7 lines")
                                    result_size += len(str(key)) + 2 + len(truncated_stack)
                                else:
                                    result[key] = value
                                    result_size += len(str(key)) + 2 + len(value)
                            else:
                                # For other large text fields, regular truncation
                                result[key] = value[:adjusted_max_length] + TRUNCATE_SUFFIX
                                logger.debug(f"Truncated field {path}.{key} from {len(value)} to {adjusted_max_length} chars")
                                result_size += len(str(key)) + 2 + adjusted_max_length + len(TRUNCATE_SUFFIX)
                        else:
                            processed_value, value_size = truncate_large_strings(
                                value,
                                adjusted_max_length,
                                max_response_size,
                                f"{path}.{key}" if path else key,
                                current_size + result_size,
                                truncation_level,
                            )
                            result[key] = processed_value
                            result_size += len(str(key)) + 2 + value_size

        # Final pass: process remaining fields if we have size budget remaining
        remaining_fields = [k for k in obj if k not in result]

        # Skip non-essential fields at highest truncation level
        if truncation_level >= 2 and len(remaining_fields) > 0:
            result["_note"] = f"{len(remaining_fields)} non-essential fields omitted"
            result_size += len("_note") + 2 + len(result["_note"])
        else:
            for key in remaining_fields:
                # Skip if we're approaching max size and apply more aggressive truncation
                if current_size + result_size > max_response_size * 0.9:
                    # Instead of breaking, increase truncation level for remaining fields
                    next_truncation_level = min(2, truncation_level + 1)
                    if next_truncation_level > truncation_level:
                        result["_truncation_note"] = "Response truncated due to size constraints"
                        result_size += len("_truncation_note") + 2 + len(result["_truncation_note"])

                processed_value, value_size = truncate_large_strings(
                    obj[key],
                    adjusted_max_length,
                    max_response_size,
                    f"{path}.{key}" if path else key,
                    current_size + result_size,
                    min(2, truncation_level + (1 if current_size + result_size > max_response_size * 0.7 else 0)),
                )
                result[key] = processed_value
                result_size += len(str(key)) + 2 + value_size

        return result, result_size

    elif isinstance(obj, list):
        result = []
        result_size = 2  # Count brackets

        # Special handling for empty lists
        if not obj:
            return [], 2

        # Estimate average item size to plan truncation strategy
        # We'll sample the first item or use a default
        sample_size = 0
        if obj:
            sample_item, sample_size = truncate_large_strings(
                obj[0], adjusted_max_length, max_response_size, f"{path}[0]", current_size + result_size, truncation_level
            )

        estimated_total_size = sample_size * len(obj)

        # Determine the appropriate truncation strategy based on estimated size
        target_truncation_level = truncation_level
        if estimated_total_size > max_response_size * 0.8:
            # If the list would be too large, increase truncation level
            target_truncation_level = min(2, truncation_level + 1)

        # If even at max truncation we'd exceed size, we need to limit the number of items
        will_need_item_limit = False
        if target_truncation_level == 2 and estimated_total_size > max_response_size:
            will_need_item_limit = True
            max_items = max(5, int(max_response_size * 0.8 / (sample_size or 100)))
        else:
            max_items = len(obj)

        # Process items with appropriate truncation level
        for i, item in enumerate(obj):
            if will_need_item_limit and i >= max_items:
                result.append({"_note": f"List truncated, {len(obj) - i} of {len(obj)} items omitted due to size constraints"})
                result_size += 2 + len(result[-1]["_note"])
                break

            item_truncation_level = target_truncation_level
            # Apply even more aggressive truncation as we approach the limit
            if current_size + result_size > max_response_size * 0.8:
                item_truncation_level = 2

            processed_item, item_size = truncate_large_strings(
                item, adjusted_max_length, max_response_size, f"{path}[{i}]", current_size + result_size, item_truncation_level
            )
            result.append(processed_item)
            result_size += item_size
            if i < len(obj) - 1:
                result_size += 1  # Count comma

        return result, result_size

    elif isinstance(obj, str):
        # String truncation strategy based on truncation level
        if len(obj) <= adjusted_max_length:
            return obj, len(obj)

        # Special handling for stacktraces at normal truncation level
        if truncation_level == 0 and ("stacktrace" in path.lower() or "stack" in path.lower()) and "\n" in obj:
            lines = obj.split("\n")
            if len(lines) > 6:
                # Keep first 3 and last 3 lines for context at normal level
                truncated = "\n".join(lines[:3] + ["..."] + lines[-3:])
                return truncated, len(truncated)

        # Regular string truncation with adjusted max length
        if len(obj) > adjusted_max_length:
            truncated = obj[:adjusted_max_length] + TRUNCATE_SUFFIX
            return truncated, len(truncated)

        return obj, len(obj)

    else:
        # For other types (int, float, bool, None), return as is
        return obj, len(str(obj))


def process_compact_data(data: Any) -> Any:
    """Process response data to truncate large values while preserving list item counts.

    Args:
        data: The response data to process

    Returns:
        Processed data with large values truncated
    """
    processed_data, size = truncate_large_strings(data, truncation_level=0)
    logger.debug(f"Processed response data: processed size {size} chars")
    return processed_data


def serialize_full_json_string(data: Any) -> str:
    """Serialize data to a full JSON string without truncation.

    Args:
        data: The full data to serialize

    Returns:
        JSON string representation of the data
    """
    try:
        # Use default=str to handle datetime and other non-serializable objects
        return json.dumps(data, default=str)
    except Exception as e:
        logger.error(f"Error serializing to full JSON string: {str(e)}")
        return json.dumps({"error": f"Failed to serialize response: {str(e)}"})


def save_full_data_to_file(data: Any, base_filename_prefix: str, state: "MCPState") -> dict[str, Any]:
    """Save full data to a JSON file in the configured dump directory.

    Args:
        data: The full data to save
        base_filename_prefix: Prefix for the filename (e.g., "trace_123")
        state: MCPState with dump_dir configuration

    Returns:
        Dictionary with status information about the file save operation
    """
    if not state.dump_dir:
        logger.warning("Cannot save full data: dump_dir not configured")
        return {"status": "error", "message": "Dump directory not configured. Use --dump-dir CLI argument.", "file_path": None}

    # Sanitize the filename prefix
    safe_prefix = "".join(c for c in base_filename_prefix if c.isalnum() or c in "_-.")
    if not safe_prefix:
        safe_prefix = "langfuse_data"

    # Generate a unique filename with timestamp
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{safe_prefix}_{timestamp}.json"
    filepath = os.path.join(state.dump_dir, filename)

    try:
        # Ensure the directory exists (extra safety check)
        os.makedirs(state.dump_dir, exist_ok=True)

        # Serialize the data with pretty-printing for better readability
        json_str = json.dumps(data, default=str, indent=2)

        # Write to file
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(json_str)

        logger.info(f"Full data saved to {filepath}")
        return {"status": "success", "message": "Full data saved successfully.", "file_path": filepath}
    except Exception as e:
        logger.error(f"Error saving full data to file: {str(e)}")
        return {"status": "error", "message": f"Failed to save full data: {str(e)}", "file_path": None}


def process_data_with_mode(
    data: Any,
    output_mode: OUTPUT_MODE_LITERAL | OutputMode,
    base_filename_prefix: str,
    state: "MCPState",
) -> tuple[Any, dict[str, Any] | None]:
    """Process data according to the specified output mode.

    Args:
        data: The raw data to process
        output_mode: The output mode to use
        base_filename_prefix: Prefix for filename when using full_json_file mode
        state: MCPState with configuration

    Returns:
        Tuple of (processed data, optional metadata additions)
    """
    mode = _ensure_output_mode(output_mode)

    if mode == OutputMode.COMPACT:
        return process_compact_data(data), None

    if mode == OutputMode.FULL_JSON_STRING:
        return serialize_full_json_string(data), None

    if mode == OutputMode.FULL_JSON_FILE:
        # Process a compact version of the data
        compact_data = process_compact_data(data)

        # Save the full data to a file
        save_info = save_full_data_to_file(data, base_filename_prefix, state)

        file_meta = {
            "file_path": save_info.get("file_path"),
            "file_info": save_info,
        }
        if save_info.get("status") == "success" and save_info.get("file_path"):
            file_meta["message"] = "Full response saved to file."

        return compact_data, file_meta

    # Fallback
    logger.warning(f"Unknown output mode: {output_mode}, defaulting to compact mode")
    return process_compact_data(data), None


@dataclass
class MCPState:
    """State object passed from lifespan context to tools.

    Contains the Langfuse client instance and various caches used to optimize
    performance when querying and filtering observations and exceptions.
    """

    langfuse_client: Langfuse
    # LRU caches for efficient exception lookup
    observation_cache: LRUCache = field(
        default_factory=lambda: LRUCache(maxsize=100), metadata={"description": "Cache for observations to reduce API calls"}
    )
    file_to_observations_map: LRUCache = field(
        default_factory=lambda: LRUCache(maxsize=100), metadata={"description": "Mapping of file paths to observation IDs"}
    )
    exception_type_map: LRUCache = field(
        default_factory=lambda: LRUCache(maxsize=100), metadata={"description": "Mapping of exception types to observation IDs"}
    )
    exceptions_by_filepath: LRUCache = field(
        default_factory=lambda: LRUCache(maxsize=100), metadata={"description": "Mapping of file paths to exception details"}
    )
    dump_dir: str = field(
        default=None, metadata={"description": "Directory to save full JSON dumps when 'output_mode' is 'full_json_file'"}
    )


class ExceptionCount(BaseModel):
    """Model for exception counts grouped by category.

    Represents the count of exceptions grouped by file path, function name, or exception type.
    Used by the find_exceptions endpoint to return aggregated exception data.
    """

    group: str = Field(description="The grouping key (file path, function name, or exception type)")
    count: int = Field(description="Number of exceptions in this group")


def validate_age(age: int) -> int:
    """Validate that age is positive and ≤ 7 days.

    Args:
        age: Age in minutes to validate

    Returns:
        The validated age if it passes validation

    Raises:
        ValueError: If age is not positive or exceeds 7 days (10080 minutes)
    """
    if age <= 0:
        raise ValueError("Age must be positive")
    if age > MAX_AGE_MINUTES:
        raise ValueError(f"Age cannot be more than {MAX_AGE_MINUTES} minutes")
    logger.debug(f"Age validated: {age} minutes")
    return age


ValidatedAge = Annotated[int, AfterValidator(validate_age)]
"""Type for validated age values (positive integer up to 7 days/10080 minutes)"""


def clear_caches(state: MCPState) -> None:
    """Clear all in-memory caches."""
    state.observation_cache.clear()
    state.file_to_observations_map.clear()
    state.exception_type_map.clear()
    state.exceptions_by_filepath.clear()

    # Also clear the LRU cache
    _get_cached_observation.cache_clear()

    logger.debug("All caches cleared")


@lru_cache(maxsize=1000)
def _get_cached_observation(langfuse_client: Langfuse, observation_id: str) -> Any:
    """Cache observation details to avoid duplicate API calls."""
    try:
        observation = _get_observation(langfuse_client, observation_id)
        return _sdk_object_to_python(observation)
    except Exception as e:
        logger.warning(f"Error fetching observation {observation_id}: {str(e)}")
        return None


async def _efficient_fetch_observations(
    state: MCPState, from_timestamp: datetime, to_timestamp: datetime, filepath: str | None = None
) -> dict[str, Any]:
    """Efficiently fetch observations with exception filtering.

    Args:
        state: MCP state with Langfuse client and caches
        from_timestamp: Start time
        to_timestamp: End time
        filepath: Optional filter by filepath

    Returns:
        Dictionary of observation_id -> observation
    """
    langfuse_client = state.langfuse_client

    # Use a cache key that includes the time range
    cache_key = f"{from_timestamp.isoformat()}-{to_timestamp.isoformat()}"

    # Check if we've already processed this time range
    if hasattr(state, "observation_cache") and cache_key in state.observation_cache:
        logger.info("Using cached observations")
        return state.observation_cache[cache_key]

    # Fetch observations from Langfuse
    observation_items, _ = _list_observations(
        langfuse_client,
        limit=500,
        page=1,
        from_start_time=from_timestamp,
        to_start_time=to_timestamp,
        obs_type="SPAN",
        name=None,
        user_id=None,
        trace_id=None,
        parent_observation_id=None,
        metadata=None,
    )

    # Process observations and build indices
    observations: dict[str, Any] = {}
    for obs in observation_items:
        events = []
        if hasattr(obs, "events"):
            events = getattr(obs, "events") or []
        elif isinstance(obs, dict):
            events = obs.get("events", [])

        if not events:
            continue

        for event in events:
            attributes = getattr(event, "attributes", None)
            if attributes is None and isinstance(event, dict):
                attributes = event.get("attributes")
            if not attributes or not attributes.get("exception.type"):
                continue

            # Store observation
            obs_id = obs.get("id") if isinstance(obs, dict) else getattr(obs, "id", None)
            if not obs_id:
                continue
            observations[obs_id] = _sdk_object_to_python(obs)

            # Update file index if we have filepath info
            metadata_block = getattr(obs, "metadata", None)
            if metadata_block is None and isinstance(obs, dict):
                metadata_block = obs.get("metadata")
            if metadata_block:
                file = metadata_block.get("code.filepath")
                if file:
                    if file not in state.file_to_observations_map:
                        state.file_to_observations_map[file] = set()
                    state.file_to_observations_map[file].add(obs_id)

            # Update exception type index
            exc_type = attributes["exception.type"]
            if exc_type not in state.exception_type_map:
                state.exception_type_map[exc_type] = set()
            state.exception_type_map[exc_type].add(obs_id)

    # Cache the processed observations
    state.observation_cache[cache_key] = observations

    return observations


async def _embed_observations_in_traces(state: MCPState, traces: list[Any]) -> None:
    """Fetch and embed full observation objects into traces.

    This replaces the observation IDs list with a list of the actual observation objects.

    Args:
        state: MCP state with Langfuse client
        traces: List of trace objects to process
    """
    if not traces:
        return

    # Process each trace
    for trace in traces:
        if not isinstance(trace, dict) or "observations" not in trace:
            continue

        observation_refs = trace["observations"]
        if not isinstance(observation_refs, list):
            continue

        # Skip if there are no observations
        if not observation_refs:
            continue

        # If we already have hydrated observation objects, normalize them and continue
        first_ref = observation_refs[0]
        if not isinstance(first_ref, str):
            trace["observations"] = [_sdk_object_to_python(obs) for obs in observation_refs]
            continue

        # Fetch each observation when only IDs are provided
        full_observations = []
        for obs_id in observation_refs:
            try:
                obs = _get_observation(state.langfuse_client, obs_id)
                obs_data = _sdk_object_to_python(obs)
                full_observations.append(obs_data)
                logger.debug(f"Fetched observation {obs_id} for trace {trace.get('id', 'unknown')}")
            except Exception as e:
                logger.warning(f"Error fetching observation {obs_id}: {str(e)}")
                full_observations.append({"id": obs_id, "fetch_error": str(e)})

        trace["observations"] = full_observations
        logger.debug(f"Embedded {len(full_observations)} observations in trace {trace.get('id', 'unknown')}")


async def fetch_traces(
    ctx: Context,
    age: ValidatedAge = Field(..., description="Minutes ago to start looking (e.g., 1440 for 24 hours)", gt=0, le=MAX_AGE_MINUTES),
    name: str | None = Field(None, description="Name of the trace to filter by"),
    user_id: str | None = Field(None, description="User ID to filter traces by"),
    session_id: str | None = Field(None, description="Session ID to filter traces by"),
    metadata: dict[str, Any] | None = Field(None, description="Metadata fields to filter by"),
    page: int = Field(1, description="Page number for pagination (starts at 1)"),
    limit: int = Field(50, description="Maximum number of traces to return per page"),
    tags: str | None = Field(None, description="Tag or comma-separated list of tags to filter traces by"),
    include_observations: bool = Field(
        False,
        description=(
            "If True, fetch and include the full observation objects instead of just IDs. "
            "Use this when you need access to system prompts, model parameters, or other details stored "
            "within observations. Significantly increases response time but provides complete data."
        ),
    ),
    output_mode: OUTPUT_MODE_LITERAL = Field(
        OutputMode.COMPACT,
        description=(
            "Controls the output format: 'compact' (default) returns summarized JSON, "
            "'full_json_string' returns complete raw JSON as string, "
            "'full_json_file' saves complete data to file and returns summary with path."
        ),
    ),
) -> ResponseDict | str:
    """Find traces based on filters. All filter parameters are optional."""
    age = validate_age(age)

    state = cast(MCPState, ctx.request_context.lifespan_context)

    # Calculate timestamps from age
    from_timestamp = datetime.now(timezone.utc) - timedelta(minutes=age)

    try:
        # Process tags if it's a comma-separated string
        tags_list = None
        if tags:
            if "," in tags:
                tags_list = [tag.strip() for tag in tags.split(",") if tag.strip()]
            else:
                tags_list = [tags]

        # Use the resource-style API when available (Langfuse v3) with fallback to v2 helpers
        trace_items, pagination = _list_traces(
            state.langfuse_client,
            limit=limit,
            page=page,
            include_observations=include_observations,
            tags=tags_list,
            from_timestamp=from_timestamp,
            name=name,
            user_id=user_id,
            session_id=session_id,
            metadata=metadata,
        )

        # Convert response to a serializable format
        raw_traces = [_sdk_object_to_python(trace) for trace in trace_items]

        # If include_observations is True, fetch and embed the full observation objects
        if include_observations and raw_traces:
            logger.info(f"Fetching full observation details for {sum(len(t.get('observations', [])) for t in raw_traces)} observations")
            await _embed_observations_in_traces(state, raw_traces)

        # Process based on output mode
        mode = _ensure_output_mode(output_mode)
        base_filename_prefix = "traces"
        processed_data, file_meta = process_data_with_mode(raw_traces, mode, base_filename_prefix, state)

        logger.info(f"Found {len(raw_traces)} traces, returning with output_mode={mode}, include_observations={include_observations}")

        # Return data in the standard response format
        if mode == OutputMode.FULL_JSON_STRING:
            return processed_data

        metadata_block = {
            "item_count": len(raw_traces),
            "file_path": None,
            "file_info": None,
        }
        if pagination.get("next_page") is not None:
            metadata_block["next_page"] = pagination["next_page"]
        if pagination.get("total") is not None:
            metadata_block["total"] = pagination["total"]
        if file_meta:
            metadata_block.update(file_meta)

        return {"data": processed_data, "metadata": metadata_block}
    except Exception:
        logger.exception("Error in fetch_traces")
        raise


async def fetch_trace(
    ctx: Context,
    trace_id: str = Field(..., description="The ID of the trace to fetch (unique identifier string)"),
    include_observations: bool = Field(
        False,
        description=(
            "If True, fetch and include the full observation objects instead of just IDs. "
            "Use this when you need access to system prompts, model parameters, or other details stored "
            "within observations. Significantly increases response time but provides complete data. "
            "Pairs well with output_mode='full_json_file' for complete dumps."
        ),
    ),
    output_mode: OUTPUT_MODE_LITERAL = Field(
        OutputMode.COMPACT,
        description=(
            "Controls the output format and action. "
            "'compact' (default): Returns a summarized JSON object optimized for direct agent consumption. "
            "'full_json_string': Returns the complete, raw JSON data serialized as a string. "
            "'full_json_file': Returns a summarized JSON object AND saves the complete data to a file."
        ),
    ),
) -> ResponseDict | str:
    """Get a single trace by ID with full details.

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        trace_id: The ID of the trace to fetch (unique identifier string)
        include_observations: If True, fetch and include the full observation objects instead of just IDs.
            Use this when you need access to system prompts, model parameters, or other details stored
            within observations. Significantly increases response time but provides complete data.
        output_mode: Controls the output format and detail level

    Returns:
        One of the following based on output_mode:
        - For 'compact' and 'full_json_file': A response dictionary with the structure:
          {
              "data": Single trace object,
              "metadata": {
                  "file_path": Path to saved file (only for full_json_file mode),
                  "file_info": File save details (only for full_json_file mode)
              }
          }
        - For 'full_json_string': A string containing the full JSON response

    Usage Tips:
        - For quick browsing: use include_observations=False with output_mode="compact"
        - For full data but viewable in responses: use include_observations=True with output_mode="compact"
        - For complete data dumps: use include_observations=True with output_mode="full_json_file"
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    try:
        # Use the resource-style API when available
        trace = _get_trace(state.langfuse_client, trace_id, include_observations)

        # Convert response to a serializable format
        raw_trace = _sdk_object_to_python(trace)

        if not isinstance(raw_trace, dict):
            logger.debug("Trace response normalized into dictionary structure")
            raw_trace = _sdk_object_to_python({"trace": raw_trace})

        # If include_observations is True and the API did not hydrate them, fetch and embed
        if include_observations and raw_trace:
            embedded = raw_trace.get("observations", []) if isinstance(raw_trace, dict) else []
            if embedded and isinstance(embedded[0], str):
                logger.info(f"Fetching full observation details for {len(embedded)} observations")
                await _embed_observations_in_traces(state, [raw_trace])

        # Process based on output mode
        mode = _ensure_output_mode(output_mode)
        base_filename_prefix = f"trace_{trace_id}"
        processed_data, file_meta = process_data_with_mode(raw_trace, mode, base_filename_prefix, state)

        logger.info(f"Retrieved trace {trace_id}, returning with output_mode={mode}, include_observations={include_observations}")

        # Return data in the standard response format
        if mode == OutputMode.FULL_JSON_STRING:
            return processed_data

        metadata_block = {
            "file_path": None,
            "file_info": None,
        }
        if file_meta:
            metadata_block.update(file_meta)

        return {"data": processed_data, "metadata": metadata_block}
    except Exception:
        logger.exception(f"Error fetching trace {trace_id}")
        raise


async def fetch_observations(
    ctx: Context,
    type: Literal["SPAN", "GENERATION", "EVENT"] | None = Field(
        None, description="The observation type to filter by ('SPAN', 'GENERATION', or 'EVENT')"
    ),
    age: ValidatedAge = Field(..., description="Minutes ago to start looking (e.g., 1440 for 24 hours)", gt=0, le=MAX_AGE_MINUTES),
    name: str | None = Field(None, description="Optional name filter (string pattern to match)"),
    user_id: str | None = Field(None, description="Optional user ID filter (exact match)"),
    trace_id: str | None = Field(None, description="Optional trace ID filter (exact match)"),
    parent_observation_id: str | None = Field(None, description="Optional parent observation ID filter (exact match)"),
    page: int = Field(1, description="Page number for pagination (starts at 1)"),
    limit: int = Field(50, description="Maximum number of observations to return per page"),
    output_mode: OUTPUT_MODE_LITERAL = Field(
        OutputMode.COMPACT,
        description=(
            "Controls the output format and action. "
            "'compact' (default): Returns a summarized JSON object optimized for direct agent consumption. "
            "'full_json_string': Returns the complete, raw JSON data serialized as a string. "
            "'full_json_file': Returns a summarized JSON object AND saves the complete data to a file."
        ),
    ),
) -> ResponseDict | str:
    """Get observations filtered by type and other criteria.

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        type: The observation type to filter by (SPAN, GENERATION, or EVENT)
        age: Minutes ago to start looking (e.g., 1440 for 24 hours)
        name: Optional name filter (string pattern to match)
        user_id: Optional user ID filter (exact match)
        trace_id: Optional trace ID filter (exact match)
        parent_observation_id: Optional parent observation ID filter (exact match)
        page: Page number for pagination (starts at 1)
        limit: Maximum number of observations to return per page
        output_mode: Controls the output format and detail level

    Returns:
        Based on output_mode:
        - compact: List of summarized observation objects
        - full_json_string: String containing the full JSON response
        - full_json_file: List of summarized observation objects with file save info
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    age = validate_age(age)

    # Calculate timestamps from age
    from_start_time = datetime.now(timezone.utc) - timedelta(minutes=age)
    metadata = None  # Metadata filtering not currently exposed for this tool

    try:
        observation_items, pagination = _list_observations(
            state.langfuse_client,
            limit=limit,
            page=page,
            from_start_time=from_start_time,
            to_start_time=None,
            obs_type=type,
            name=name,
            user_id=user_id,
            trace_id=trace_id,
            parent_observation_id=parent_observation_id,
            metadata=metadata,
        )

        # Convert response to a serializable format
        raw_observations = [_sdk_object_to_python(obs) for obs in observation_items]

        # Process based on output mode
        mode = _ensure_output_mode(output_mode)
        base_filename_prefix = f"observations_{type or 'all'}"
        processed_data, file_meta = process_data_with_mode(raw_observations, mode, base_filename_prefix, state)

        logger.info(f"Found {len(raw_observations)} observations, returning with output_mode={mode}")

        # Return data in the standard response format
        if mode == OutputMode.FULL_JSON_STRING:
            return processed_data

        metadata_block = {
            "item_count": len(raw_observations),
            "file_path": None,
            "file_info": None,
        }
        if pagination.get("next_page") is not None:
            metadata_block["next_page"] = pagination["next_page"]
        if pagination.get("total") is not None:
            metadata_block["total"] = pagination["total"]
        if file_meta:
            metadata_block.update(file_meta)

        return {"data": processed_data, "metadata": metadata_block}
    except Exception:
        logger.exception("Error fetching observations")
        raise


async def fetch_observation(
    ctx: Context,
    observation_id: str = Field(..., description="The ID of the observation to fetch (unique identifier string)"),
    output_mode: OUTPUT_MODE_LITERAL = Field(
        OutputMode.COMPACT,
        description=(
            "Controls the output format and action. "
            "'compact' (default): Returns a summarized JSON object optimized for direct agent consumption. "
            "'full_json_string': Returns the complete, raw JSON data serialized as a string. "
            "'full_json_file': Returns a summarized JSON object AND saves the complete data to a file."
        ),
    ),
) -> ResponseDict | str:
    """Get a single observation by ID.

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        observation_id: The ID of the observation to fetch (unique identifier string)
        output_mode: Controls the output format and detail level

    Returns:
        Based on output_mode:
        - compact: Summarized observation object
        - full_json_string: String containing the full JSON response
        - full_json_file: Summarized observation object with file save info
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    try:
        # Use the resource-style API when available
        observation = _get_observation(state.langfuse_client, observation_id)

        # Convert response to a serializable format
        raw_observation = _sdk_object_to_python(observation)

        # Process based on output mode
        base_filename_prefix = f"observation_{observation_id}"
        mode = _ensure_output_mode(output_mode)
        processed_data, file_meta = process_data_with_mode(raw_observation, mode, base_filename_prefix, state)

        logger.info(f"Retrieved observation {observation_id}, returning with output_mode={mode}")

        if mode == OutputMode.FULL_JSON_STRING:
            return processed_data

        metadata_block = {"file_path": None, "file_info": None}
        if file_meta:
            metadata_block.update(file_meta)

        return {"data": processed_data, "metadata": metadata_block}
    except Exception:
        logger.exception(f"Error fetching observation {observation_id}")
        raise


async def fetch_sessions(
    ctx: Context,
    age: ValidatedAge = Field(..., description="Minutes ago to start looking (e.g., 1440 for 24 hours)", gt=0, le=MAX_AGE_MINUTES),
    page: int = Field(1, description="Page number for pagination (starts at 1)"),
    limit: int = Field(50, description="Maximum number of sessions to return per page"),
    output_mode: OUTPUT_MODE_LITERAL = Field(
        OutputMode.COMPACT,
        description=(
            "Controls the output format and action. "
            "'compact' (default): Returns a summarized JSON object optimized for direct agent consumption. "
            "'full_json_string': Returns the complete, raw JSON data serialized as a string. "
            "'full_json_file': Returns a summarized JSON object AND saves the complete data to a file."
        ),
    ),
) -> ResponseDict | str:
    """Get a list of sessions in the current project.

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        age: Minutes ago to start looking (e.g., 1440 for 24 hours)
        page: Page number for pagination (starts at 1)
        limit: Maximum number of sessions to return per page
        output_mode: Controls the output format and detail level

    Returns:
        Based on output_mode:
        - compact: List of summarized session objects
        - full_json_string: String containing the full JSON response
        - full_json_file: List of summarized session objects with file save info
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    age = validate_age(age)

    # Calculate timestamps from age
    from_timestamp = datetime.now(timezone.utc) - timedelta(minutes=age)

    try:
        session_items, pagination = _list_sessions(
            state.langfuse_client,
            limit=limit,
            page=page,
            from_timestamp=from_timestamp,
        )

        # Convert response to a serializable format
        raw_sessions = [_sdk_object_to_python(session) for session in session_items]

        # Process based on output mode
        base_filename_prefix = "sessions"
        mode = _ensure_output_mode(output_mode)
        sessions_payload, file_meta = process_data_with_mode(raw_sessions, mode, base_filename_prefix, state)

        logger.info(f"Found {len(raw_sessions)} sessions, returning with output_mode={mode}")

        if mode == OutputMode.FULL_JSON_STRING:
            return sessions_payload

        metadata_block = {"item_count": len(raw_sessions), "file_path": None, "file_info": None}
        if pagination.get("next_page") is not None:
            metadata_block["next_page"] = pagination["next_page"]
        if pagination.get("total") is not None:
            metadata_block["total"] = pagination["total"]
        if file_meta:
            metadata_block.update(file_meta)

        return {"data": sessions_payload, "metadata": metadata_block}
    except Exception:
        logger.exception("Error fetching sessions")
        raise


async def get_session_details(
    ctx: Context,
    session_id: str = Field(..., description="The ID of the session to retrieve (unique identifier string)"),
    include_observations: bool = Field(
        False,
        description=(
            "If True, fetch and include the full observation objects instead of just IDs. "
            "Use this when you need access to system prompts, model parameters, or other details stored "
            "within observations. Significantly increases response time but provides complete data. "
            "Pairs well with output_mode='full_json_file' for complete dumps."
        ),
    ),
    output_mode: OUTPUT_MODE_LITERAL = Field(
        OutputMode.COMPACT,
        description=(
            "Controls the output format and action. "
            "'compact' (default): Returns a summarized JSON object optimized for direct agent consumption. "
            "'full_json_string': Returns the complete, raw JSON data serialized as a string. "
            "'full_json_file': Returns a summarized JSON object AND saves the complete data to a file."
        ),
    ),
) -> ResponseDict | str:
    """Get detailed information about a specific session.

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        session_id: The ID of the session to retrieve (unique identifier string)
        include_observations: If True, fetch and include the full observation objects instead of just IDs.
            Use this when you need access to system prompts, model parameters, or other details stored
            within observations. Significantly increases response time but provides complete data.
        output_mode: Controls the output format and detail level

    Returns:
        Based on output_mode:
        - compact: Summarized session details object
        - full_json_string: String containing the full JSON response
        - full_json_file: Summarized session details object with file save info

    Usage Tips:
        - For quick browsing: use include_observations=False with output_mode="compact"
        - For full data but viewable in responses: use include_observations=True with output_mode="compact"
        - For complete data dumps: use include_observations=True with output_mode="full_json_file"
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    try:
        # Fetch traces with this session ID
        trace_items, pagination = _list_traces(
            state.langfuse_client,
            limit=50,
            page=1,
            include_observations=include_observations,
            tags=None,
            from_timestamp=None,
            name=None,
            user_id=None,
            session_id=session_id,
            metadata=None,
        )

        # If no traces were found, return an empty dict
        mode = _ensure_output_mode(output_mode)

        if not trace_items:
            logger.info(f"No session found with ID: {session_id}")
            empty_session = {"id": session_id, "traces": [], "trace_count": 0, "found": False}
            processed_session, file_meta = process_data_with_mode(empty_session, mode, f"session_{session_id}", state)
            if mode == OutputMode.FULL_JSON_STRING:
                return processed_session

            metadata_block = {"item_count": 0, "file_path": None, "file_info": None}
            if file_meta:
                metadata_block.update(file_meta)
            return {"data": processed_session, "metadata": metadata_block}

        # Convert traces to a serializable format
        raw_traces = [_sdk_object_to_python(trace) for trace in trace_items]

        # If include_observations is True, fetch and embed the full observation objects
        if include_observations and raw_traces:
            total_observations = sum(len(t.get("observations", [])) for t in raw_traces)
            if total_observations > 0:
                logger.info(f"Fetching full observation details for {total_observations} observations across {len(raw_traces)} traces")
                await _embed_observations_in_traces(state, raw_traces)

        # Create a session object with all traces that have this session ID
        session = {
            "id": session_id,
            "traces": raw_traces,
            "trace_count": len(raw_traces),
            "first_timestamp": raw_traces[0].get("timestamp") if raw_traces else None,
            "last_timestamp": raw_traces[-1].get("timestamp") if raw_traces else None,
            "user_id": raw_traces[0].get("user_id") if raw_traces else None,
            "found": True,
        }

        # Process the final session object based on output mode
        result, file_meta = process_data_with_mode(session, mode, f"session_{session_id}", state)

        logger.info(
            f"Found session {session_id} with {len(raw_traces)} traces, returning with output_mode={mode}, "
            f"include_observations={include_observations}"
        )
        if mode == OutputMode.FULL_JSON_STRING:
            return result

        metadata_block = {"item_count": 1, "file_path": None, "file_info": None}
        if file_meta:
            metadata_block.update(file_meta)

        return {"data": result, "metadata": metadata_block}
    except Exception:
        logger.exception(f"Error getting session {session_id}")
        raise


async def get_user_sessions(
    ctx: Context,
    user_id: str = Field(..., description="The ID of the user to retrieve sessions for"),
    age: ValidatedAge = Field(..., description="Minutes ago to start looking (e.g., 1440 for 24 hours)", gt=0, le=MAX_AGE_MINUTES),
    include_observations: bool = Field(
        False,
        description=(
            "If True, fetch and include the full observation objects instead of just IDs. "
            "Use this when you need access to system prompts, model parameters, or other details stored "
            "within observations. Significantly increases response time but provides complete data. "
            "Pairs well with output_mode='full_json_file' for complete dumps."
        ),
    ),
    output_mode: OUTPUT_MODE_LITERAL = Field(
        OutputMode.COMPACT,
        description=(
            "Controls the output format and action. "
            "'compact' (default): Returns a summarized JSON object optimized for direct agent consumption. "
            "'full_json_string': Returns the complete, raw JSON data serialized as a string. "
            "'full_json_file': Returns a summarized JSON object AND saves the complete data to a file."
        ),
    ),
) -> ResponseDict | str:
    """Get sessions for a user within a time range.

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        user_id: The ID of the user to retrieve sessions for (unique identifier string)
        age: Minutes ago to start looking (e.g., 1440 for 24 hours)
        include_observations: If True, fetch and include the full observation objects instead of just IDs.
            Use this when you need access to system prompts, model parameters, or other details stored
            within observations. Significantly increases response time but provides complete data.
        output_mode: Controls the output format and detail level

    Returns:
        Based on output_mode:
        - compact: List of summarized session objects
        - full_json_string: String containing the full JSON response
        - full_json_file: List of summarized session objects with file save info

    Usage Tips:
        - For quick browsing: use include_observations=False with output_mode="compact"
        - For full data but viewable in responses: use include_observations=True with output_mode="compact"
        - For complete data dumps: use include_observations=True with output_mode="full_json_file"
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    age = validate_age(age)

    # Calculate timestamp from age
    from_timestamp = datetime.now(timezone.utc) - timedelta(minutes=age)

    try:
        mode = _ensure_output_mode(output_mode)

        # Fetch traces for this user
        trace_items, pagination = _list_traces(
            state.langfuse_client,
            limit=100,
            page=1,
            include_observations=include_observations,
            tags=None,
            from_timestamp=from_timestamp,
            name=None,
            user_id=user_id,
            session_id=None,
            metadata=None,
        )

        # Convert traces to a serializable format
        raw_traces = [_sdk_object_to_python(trace) for trace in trace_items]

        # If include_observations is True, fetch and embed the full observation objects
        if include_observations and raw_traces:
            total_observations = sum(len(t.get("observations", [])) for t in raw_traces)
            if total_observations > 0:
                logger.info(f"Fetching full observation details for {total_observations} observations across {len(raw_traces)} traces")
                await _embed_observations_in_traces(state, raw_traces)

        # Group traces by session_id
        sessions_dict: dict[str, dict[str, Any]] = {}
        for trace in raw_traces:
            session_id = trace.get("session_id")
            if not session_id:
                continue

            if session_id not in sessions_dict:
                sessions_dict[session_id] = {
                    "id": session_id,
                    "traces": [],
                    "first_timestamp": None,
                    "last_timestamp": None,
                    "user_id": user_id,
                }

            # Add trace to this session
            sessions_dict[session_id]["traces"].append(trace)

            # Update timestamps
            trace_timestamp = trace.get("timestamp")
            if trace_timestamp:
                if not sessions_dict[session_id]["first_timestamp"] or trace_timestamp < sessions_dict[session_id]["first_timestamp"]:
                    sessions_dict[session_id]["first_timestamp"] = trace_timestamp
                if not sessions_dict[session_id]["last_timestamp"] or trace_timestamp > sessions_dict[session_id]["last_timestamp"]:
                    sessions_dict[session_id]["last_timestamp"] = trace_timestamp

        # Convert to list and add trace counts
        sessions = list(sessions_dict.values())
        for session in sessions:
            session["trace_count"] = len(session["traces"])

        # Sort sessions by most recent last_timestamp
        sessions.sort(key=lambda x: _datetime_sort_key(x.get("last_timestamp")), reverse=True)

        processed_sessions, file_meta = process_data_with_mode(sessions, mode, f"user_{user_id}_sessions", state)

        logger.info(
            f"Found {len(sessions)} sessions for user {user_id}, returning with output_mode={mode}, "
            f"include_observations={include_observations}"
        )

        if mode == OutputMode.FULL_JSON_STRING:
            return processed_sessions

        metadata_block = {
            "item_count": len(sessions),
            "file_path": None,
            "file_info": None,
        }
        if pagination.get("next_page") is not None:
            metadata_block["next_page"] = pagination["next_page"]
        if pagination.get("total") is not None:
            metadata_block["total"] = pagination["total"]
        if file_meta:
            metadata_block.update(file_meta)

        return {"data": processed_sessions, "metadata": metadata_block}
    except Exception:
        logger.exception(f"Error getting sessions for user {user_id}")
        raise


async def find_exceptions(
    ctx: Context,
    age: ValidatedAge = Field(
        ..., description="Number of minutes to look back (positive integer, max 7 days/10080 minutes)", gt=0, le=MAX_AGE_MINUTES
    ),
    group_by: Literal["file", "function", "type"] = Field(
        "file",
        description=(
            "How to group exceptions - 'file' groups by filename, 'function' groups by function name, or 'type' groups by exception type"
        ),
    ),
) -> ResponseDict:
    """Get exception counts grouped by file path, function, or type.

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        age: Number of minutes to look back (positive integer, max 7 days/10080 minutes)
        group_by: How to group exceptions - "file" groups by filename, "function" groups by function name,
                  or "type" groups by exception type

    Returns:
        List of exception counts grouped by the specified category (file, function, or type)
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    age = validate_age(age)

    # Calculate from_timestamp based on age
    from_timestamp = datetime.now(timezone.utc) - timedelta(minutes=age)
    to_timestamp = datetime.now(timezone.utc)

    try:
        # Fetch all SPAN observations since they may contain exceptions
        observation_items, _ = _list_observations(
            state.langfuse_client,
            limit=100,
            page=1,
            from_start_time=from_timestamp,
            to_start_time=to_timestamp,
            obs_type="SPAN",
            name=None,
            user_id=None,
            trace_id=None,
            parent_observation_id=None,
            metadata=None,
        )

        # Process observations to find and group exceptions
        exception_groups = Counter()

        for observation in (_sdk_object_to_python(obs) for obs in observation_items):
            events = observation.get("events", []) if isinstance(observation, dict) else []
            if not events:
                continue

            for event in events:
                event_dict = event if isinstance(event, dict) else _sdk_object_to_python(event)

                # Check if this is an exception event
                if not event_dict.get("attributes", {}).get("exception.type"):
                    continue

                # Get the grouping key based on group_by parameter
                if group_by == "file":
                    meta = observation.get("metadata", {}) if isinstance(observation, dict) else {}
                    group_key = meta.get("code.filepath", "unknown_file")
                elif group_by == "function":
                    meta = observation.get("metadata", {}) if isinstance(observation, dict) else {}
                    group_key = meta.get("code.function", "unknown_function")
                elif group_by == "type":
                    group_key = event_dict.get("attributes", {}).get("exception.type", "unknown_exception")
                else:
                    group_key = "unknown"

                # Increment the counter for this group
                exception_groups[group_key] += 1

        # Convert counter to list of ExceptionCount objects
        results = [ExceptionCount(group=group, count=count) for group, count in exception_groups.most_common(50)]

        data = [item.model_dump() for item in results]
        metadata_block = {"item_count": len(data)}

        logger.info(f"Found {len(data)} exception groups")
        return {"data": data, "metadata": metadata_block}
    except Exception:
        logger.exception("Error finding exceptions")
        raise


async def find_exceptions_in_file(
    ctx: Context,
    filepath: str = Field(..., description="Path to the file to search for exceptions (full path including extension)"),
    age: ValidatedAge = Field(
        ..., description="Number of minutes to look back (positive integer, max 7 days/10080 minutes)", gt=0, le=MAX_AGE_MINUTES
    ),
    output_mode: OUTPUT_MODE_LITERAL = Field(
        OutputMode.COMPACT,
        description=(
            "Controls the output format and action. "
            "'compact' (default): Returns a summarized JSON object optimized for direct agent consumption. "
            "'full_json_string': Returns the complete, raw JSON data serialized as a string. "
            "'full_json_file': Returns a summarized JSON object AND saves the complete data to a file."
        ),
    ),
) -> ResponseDict | str:
    """Get detailed exception info for a specific file.

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        filepath: Path to the file to search for exceptions (full path including extension)
        age: Number of minutes to look back (positive integer, max 7 days/10080 minutes)
        output_mode: Controls the output format and detail level

    Returns:
        Based on output_mode:
        - compact: List of summarized exception details
        - full_json_string: String containing the full JSON response
        - full_json_file: List of summarized exception details with file save info
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    age = validate_age(age)

    # Calculate from_timestamp based on age
    from_timestamp = datetime.now(timezone.utc) - timedelta(minutes=age)
    to_timestamp = datetime.now(timezone.utc)

    try:
        # Fetch all SPAN observations since they may contain exceptions
        observation_items, _ = _list_observations(
            state.langfuse_client,
            limit=100,
            page=1,
            from_start_time=from_timestamp,
            to_start_time=to_timestamp,
            obs_type="SPAN",
            name=None,
            user_id=None,
            trace_id=None,
            parent_observation_id=None,
            metadata=None,
        )

        # Process observations to find exceptions in the specified file
        exceptions = []

        for observation in (_sdk_object_to_python(obs) for obs in observation_items):
            metadata = observation.get("metadata", {}) if isinstance(observation, dict) else {}
            if metadata.get("code.filepath") != filepath:
                continue

            events = observation.get("events", []) if isinstance(observation, dict) else []
            if not events:
                continue

            for event in events:
                event_dict = event if isinstance(event, dict) else _sdk_object_to_python(event)

                # Check if this is an exception event
                if not event_dict.get("attributes", {}).get("exception.type"):
                    continue

                exception_info = {
                    "observation_id": observation.get("id", "unknown") if isinstance(observation, dict) else "unknown",
                    "trace_id": observation.get("trace_id", "unknown") if isinstance(observation, dict) else "unknown",
                    "timestamp": observation.get("start_time", "unknown") if isinstance(observation, dict) else "unknown",
                    "exception_type": event_dict.get("attributes", {}).get("exception.type", "unknown"),
                    "exception_message": event_dict.get("attributes", {}).get("exception.message", ""),
                    "exception_stacktrace": event_dict.get("attributes", {}).get("exception.stacktrace", ""),
                    "function": metadata.get("code.function", "unknown"),
                    "line_number": metadata.get("code.lineno", "unknown"),
                }

                exceptions.append(exception_info)

        # Sort exceptions by timestamp (newest first)
        exceptions.sort(key=lambda x: _datetime_sort_key(x.get("timestamp")), reverse=True)

        # Only take the top 10 exceptions
        top_exceptions = exceptions[:10]

        mode = _ensure_output_mode(output_mode)
        base_filename_prefix = f"exceptions_{os.path.basename(filepath)}"
        processed_exceptions, file_meta = process_data_with_mode(top_exceptions, mode, base_filename_prefix, state)

        logger.info(f"Found {len(exceptions)} exceptions in file {filepath}, returning with output_mode={mode}")

        if mode == OutputMode.FULL_JSON_STRING:
            return processed_exceptions

        metadata_block = {
            "file_path": filepath,
            "item_count": len(top_exceptions),
            "file_info": None,
        }
        if file_meta:
            metadata_block.update(file_meta)

        return {"data": processed_exceptions, "metadata": metadata_block}
    except Exception:
        logger.exception(f"Error finding exceptions in file {filepath}")
        raise


async def get_exception_details(
    ctx: Context,
    trace_id: str = Field(..., description="The ID of the trace to analyze for exceptions (unique identifier string)"),
    span_id: str | None = Field(None, description="Optional span ID to filter by specific span (unique identifier string)"),
    output_mode: OUTPUT_MODE_LITERAL = Field(
        OutputMode.COMPACT,
        description=(
            "Controls the output format and action. "
            "'compact' (default): Returns a summarized JSON object optimized for direct agent consumption. "
            "'full_json_string': Returns the complete, raw JSON data serialized as a string. "
            "'full_json_file': Returns a summarized JSON object AND saves the complete data to a file."
        ),
    ),
) -> ResponseDict | str:
    """Get detailed exception info for a trace/span.

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        trace_id: The ID of the trace to analyze for exceptions (unique identifier string)
        span_id: Optional span ID to filter by specific span (unique identifier string)
        output_mode: Controls the output format and detail level

    Returns:
        Based on output_mode:
        - compact: List of summarized exception details
        - full_json_string: String containing the full JSON response
        - full_json_file: List of summarized exception details with file save info
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    try:
        # First get the trace details
        trace = _get_trace(state.langfuse_client, trace_id, include_observations=False)
        trace_data = _sdk_object_to_python(trace)
        mode = _ensure_output_mode(output_mode)
        if not trace_data:
            logger.warning(f"Trace not found: {trace_id}")
            empty_payload, file_meta = process_data_with_mode([], mode, f"exceptions_trace_{trace_id}", state)
            if mode == OutputMode.FULL_JSON_STRING:
                return empty_payload
            metadata_block = {"item_count": 0, "file_path": None, "file_info": None}
            if file_meta:
                metadata_block.update(file_meta)
            return {"data": empty_payload, "metadata": metadata_block}

        # Get all observations for this trace
        observation_items, _ = _list_observations(
            state.langfuse_client,
            limit=100,
            page=1,
            from_start_time=None,
            to_start_time=None,
            obs_type=None,
            name=None,
            user_id=None,
            trace_id=trace_id,
            parent_observation_id=None,
            metadata=None,
        )

        if not observation_items:
            logger.warning(f"No observations found for trace: {trace_id}")
            empty_payload, file_meta = process_data_with_mode([], mode, f"exceptions_trace_{trace_id}", state)
            if mode == OutputMode.FULL_JSON_STRING:
                return empty_payload
            metadata_block = {"item_count": 0, "file_path": None, "file_info": None}
            if file_meta:
                metadata_block.update(file_meta)
            return {"data": empty_payload, "metadata": metadata_block}

        # Filter observations if span_id is provided
        normalized_observations = [_sdk_object_to_python(obs) for obs in observation_items]
        if span_id:
            filtered_observations = [obs for obs in normalized_observations if obs.get("id") == span_id]
        else:
            filtered_observations = normalized_observations

        # Process observations to find exceptions
        exceptions = []

        for observation in filtered_observations:
            events = observation.get("events", []) if isinstance(observation, dict) else []
            if not events:
                continue

            for event in events:
                event_dict = event if isinstance(event, dict) else _sdk_object_to_python(event)

                # Check if this is an exception event
                if not event_dict.get("attributes", {}).get("exception.type"):
                    continue

                metadata = observation.get("metadata", {}) if isinstance(observation, dict) else {}

                # Extract exception details
                exception_info = {
                    "observation_id": observation.get("id", "unknown"),
                    "observation_name": observation.get("name", "unknown"),
                    "observation_type": observation.get("type", "unknown"),
                    "timestamp": observation.get("start_time", "unknown"),
                    "exception_type": event_dict.get("attributes", {}).get("exception.type", "unknown"),
                    "exception_message": event_dict.get("attributes", {}).get("exception.message", ""),
                    "exception_stacktrace": event_dict.get("attributes", {}).get("exception.stacktrace", ""),
                    "filepath": metadata.get("code.filepath", "unknown"),
                    "function": metadata.get("code.function", "unknown"),
                    "line_number": metadata.get("code.lineno", "unknown"),
                    "event_id": event_dict.get("id", "unknown"),
                    "event_name": event_dict.get("name", "unknown"),
                }

                exceptions.append(exception_info)

        # Sort exceptions by timestamp (newest first)
        exceptions.sort(key=lambda x: _datetime_sort_key(x.get("timestamp")), reverse=True)

        base_filename_prefix = f"exceptions_trace_{trace_id}"
        if span_id:
            base_filename_prefix += f"_span_{span_id}"
        processed_exceptions, file_meta = process_data_with_mode(exceptions, mode, base_filename_prefix, state)

        logger.info(f"Found {len(exceptions)} exceptions in trace {trace_id}, returning with output_mode={mode}")

        if mode == OutputMode.FULL_JSON_STRING:
            return processed_exceptions

        metadata_block = {
            "item_count": len(exceptions),
            "file_path": None,
            "file_info": None,
        }
        if file_meta:
            metadata_block.update(file_meta)

        return {"data": processed_exceptions, "metadata": metadata_block}
    except Exception:
        logger.exception(f"Error getting exception details for trace {trace_id}")
        raise


async def get_error_count(
    ctx: Context,
    age: ValidatedAge = Field(
        ..., description="Number of minutes to look back (positive integer, max 7 days/10080 minutes)", gt=0, le=MAX_AGE_MINUTES
    ),
) -> ResponseDict:
    """Get number of traces with exceptions in last N minutes.

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        age: Number of minutes to look back (positive integer, max 7 days/10080 minutes)

    Returns:
        Dictionary with error statistics including trace count, observation count, and exception count
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    age = validate_age(age)

    # Calculate from_timestamp based on age
    from_timestamp = datetime.now(timezone.utc) - timedelta(minutes=age)
    to_timestamp = datetime.now(timezone.utc)

    try:
        # Fetch all SPAN observations since they may contain exceptions
        observation_items, _ = _list_observations(
            state.langfuse_client,
            limit=100,
            page=1,
            from_start_time=from_timestamp,
            to_start_time=to_timestamp,
            obs_type="SPAN",
            name=None,
            user_id=None,
            trace_id=None,
            parent_observation_id=None,
            metadata=None,
        )

        # Count traces and observations with exceptions
        trace_ids_with_exceptions = set()
        observations_with_exceptions = 0
        total_exceptions = 0

        for observation in (_sdk_object_to_python(obs) for obs in observation_items):
            events = observation.get("events", []) if isinstance(observation, dict) else []
            if not events:
                continue

            exception_count = sum(1 for event in events if _sdk_object_to_python(event).get("attributes", {}).get("exception.type"))
            if exception_count == 0:
                continue

            observations_with_exceptions += 1
            total_exceptions += exception_count

            trace_id = observation.get("trace_id") if isinstance(observation, dict) else None
            if trace_id:
                trace_ids_with_exceptions.add(trace_id)

        result = {
            "age_minutes": age,
            "from_timestamp": from_timestamp.isoformat(),
            "to_timestamp": to_timestamp.isoformat(),
            "trace_count": len(trace_ids_with_exceptions),
            "observation_count": observations_with_exceptions,
            "exception_count": total_exceptions,
        }

        logger.info(
            f"Found {total_exceptions} exceptions in {observations_with_exceptions} observations across "
            f"{len(trace_ids_with_exceptions)} traces"
        )
        return {"data": result, "metadata": {"file_path": None, "file_info": None}}
    except Exception:
        logger.exception(f"Error getting error count for the last {age} minutes")
        raise


async def get_data_schema(ctx: Context, dummy: str = "") -> str:
    """Get schema of trace, span and event objects.

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        dummy: Unused parameter for API compatibility (can be left empty)

    Returns:
        String containing the detailed schema definitions for traces, spans, events,
        and other core Langfuse data structures
    """
    # Remove the unused state variable assignment
    # state = cast(MCPState, ctx.request_context.lifespan_context)

    # Use the dataclasses and models from Langfuse to generate a schema
    schema = """
# Langfuse Data Schema

## Trace Schema
A trace represents a complete request-response flow.

```
{
  "id": "string",             // Unique identifier
  "name": "string",           // Name of the trace
  "user_id": "string",        // Optional user identifier
  "session_id": "string",     // Optional session identifier
  "timestamp": "datetime",    // When the trace was created
  "metadata": "object",       // Optional JSON metadata
  "tags": ["string"],         // Optional array of tag strings
  "release": "string",        // Optional release version
  "version": "string",        // Optional user-specified version
  "observations": [           // Array of observation objects
    {
      // Observation fields (see below)
    }
  ]
}
```

## Observation Schema
An observation can be a span, generation, or event within a trace.

```
{
  "id": "string",                 // Unique identifier
  "trace_id": "string",           // Parent trace id
  "parent_observation_id": "string", // Optional parent observation id
  "name": "string",               // Name of the observation
  "start_time": "datetime",       // When the observation started
  "end_time": "datetime",         // When the observation ended (for spans/generations)
  "type": "string",               // Type: SPAN, GENERATION, EVENT
  "level": "string",              // Log level: DEBUG, DEFAULT, WARNING, ERROR
  "status_message": "string",     // Optional status message
  "metadata": "object",           // Optional JSON metadata
  "input": "any",                 // Optional input data
  "output": "any",                // Optional output data
  "version": "string",            // Optional version
  
  // Generation-specific fields
  "model": "string",              // LLM model name (for generations)
  "model_parameters": "object",   // Model parameters (for generations)
  "usage": "object",              // Token usage (for generations)
  
  "events": [                     // Array of event objects
    {
      // Event fields (see below)
    }
  ]
}
```

## Event Schema
Events are contained within observations for tracking specific state changes.

```
{
  "id": "string",                 // Unique identifier
  "name": "string",               // Name of the event
  "start_time": "datetime",       // When the event occurred
  "attributes": {                 // Event attributes
    "exception.type": "string",       // Type of exception (for error events)
    "exception.message": "string",    // Exception message (for error events)
    "exception.stacktrace": "string", // Exception stack trace (for error events)
    // ... other attributes
  }
}
```

## Score Schema
Scores are evaluations attached to traces or observations.

```
{
  "id": "string",             // Unique identifier
  "name": "string",           // Score name 
  "value": "number or string", // Score value (numeric or categorical)
  "data_type": "string",      // NUMERIC, BOOLEAN, or CATEGORICAL
  "trace_id": "string",       // Associated trace
  "observation_id": "string", // Optional associated observation
  "timestamp": "datetime",    // When the score was created
  "comment": "string"         // Optional comment
}
```
"""

    return schema


# =============================================================================
# Prompt Management Tools
# =============================================================================


async def get_prompt(
    ctx: Context,
    name: str = Field(..., description="The name of the prompt to fetch"),
    label: str | None = Field(
        None,
        description="Label to fetch (e.g., 'production', 'staging'). Mutually exclusive with version.",
    ),
    version: int | None = Field(
        None,
        description="Specific version number to fetch. Mutually exclusive with label.",
    ),
) -> ResponseDict:
    """Fetch a specific prompt by name with resolved dependencies.

    Retrieves a prompt from Langfuse with all dependency tags resolved. Uses the SDK's
    built-in caching for optimal performance.

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        name: The name of the prompt to fetch
        label: Optional label to fetch (e.g., 'production'). Cannot be used with version.
        version: Optional specific version number. Cannot be used with label.

    Returns:
        A dictionary containing the prompt details:
        - id: Unique prompt identifier
        - name: Prompt name
        - version: Version number
        - type: 'text' or 'chat'
        - prompt: The prompt content (string for text, list for chat)
        - labels: List of labels assigned to this version
        - tags: List of tags
        - config: Model configuration (temperature, model, etc.)

    Raises:
        ValueError: If both label and version are specified
        LookupError: If prompt not found
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    if label and version:
        raise ValueError("Cannot specify both label and version - they are mutually exclusive")

    try:
        # Use SDK's get_prompt for caching benefits
        kwargs: dict[str, Any] = {"name": name}
        if label:
            kwargs["label"] = label
        if version:
            kwargs["version"] = version

        prompt = state.langfuse_client.get_prompt(**kwargs)

        if prompt is None:
            label_msg = f" with label '{label}'" if label else ""
            version_msg = f" with version {version}" if version else ""
            raise LookupError(f"Prompt '{name}' not found{label_msg}{version_msg}")

        # Extract prompt content based on type
        prompt_content: Any
        prompt_type = getattr(prompt, "type", None)
        if isinstance(prompt_type, str):
            prompt_type = prompt_type.lower()
        else:
            prompt_type = None

        if hasattr(prompt, "prompt"):
            prompt_content = prompt.prompt
            if prompt_type is None:
                prompt_type = "chat" if isinstance(prompt_content, list) else "text"
        elif hasattr(prompt, "messages"):
            prompt_content = getattr(prompt, "messages")
            if prompt_type is None:
                prompt_type = "chat"
        else:
            prompt_content = str(prompt)
            prompt_type = prompt_type or "unknown"

        # Build response
        result = {
            "name": name,
            "version": getattr(prompt, "version", None),
            "type": prompt_type or "unknown",
            "prompt": prompt_content,
            "labels": getattr(prompt, "labels", []),
            "tags": getattr(prompt, "tags", []),
            "config": getattr(prompt, "config", {}),
        }
        prompt_id = getattr(prompt, "id", None)
        if prompt_id is None and isinstance(prompt, dict):
            prompt_id = prompt.get("id")
        if prompt_id is not None:
            result["id"] = prompt_id

        logger.info(f"Retrieved prompt '{name}' (version={result['version']}, type={prompt_type})")
        return {"data": result, "metadata": {"found": True}}

    except Exception as e:
        logger.error(f"Error fetching prompt '{name}': {e}")
        raise


async def get_prompt_unresolved(
    ctx: Context,
    name: str = Field(..., description="The name of the prompt to fetch"),
    label: str | None = Field(
        None,
        description="Label to fetch (e.g., 'production', 'staging'). Mutually exclusive with version.",
    ),
    version: int | None = Field(
        None,
        description="Specific version number to fetch. Mutually exclusive with label.",
    ),
) -> ResponseDict:
    """Fetch a specific prompt by name WITHOUT resolving dependencies.

    Returns raw prompt content with dependency tags intact (e.g., @@@langfusePrompt:name=xxx@@@) when
    the SDK supports resolve=false. Otherwise returns the resolved prompt and marks metadata.resolved=True.
    Useful for analyzing prompt composition and debugging dependency chains.

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        name: The name of the prompt to fetch
        label: Optional label to fetch. Cannot be used with version.
        version: Optional specific version number. Cannot be used with label.

    Returns:
        A dictionary containing the raw prompt details with dependency tags preserved.

    Raises:
        ValueError: If both label and version are specified
        LookupError: If prompt not found
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    if label and version:
        raise ValueError("Cannot specify both label and version - they are mutually exclusive")

    try:
        # Use API directly to get unresolved prompt
        api_kwargs: dict[str, Any] = {}
        if label:
            api_kwargs["label"] = label
        if version:
            api_kwargs["version"] = version

        # Access the prompts API directly.
        if not hasattr(state.langfuse_client, "api") or not hasattr(state.langfuse_client.api, "prompts"):
            raise RuntimeError("Langfuse SDK does not expose prompts.get; upgrade the SDK to use this tool.")
        if not hasattr(state.langfuse_client.api.prompts, "get"):
            raise RuntimeError("Langfuse SDK does not expose prompts.get; upgrade the SDK to use this tool.")
        supports_resolve = _prompts_get_supports_resolve(state.langfuse_client.api.prompts)
        try:
            if supports_resolve:
                prompt_response = _prompts_get(state.langfuse_client.api.prompts, name=name, resolve=False, **api_kwargs)
            else:
                prompt_response = _prompts_get(state.langfuse_client.api.prompts, name=name, **api_kwargs)
        except TypeError as e:
            msg = str(e)
            if "resolve" in msg or "unexpected keyword" in msg:
                logger.error("Langfuse SDK does not support resolve=false for prompts.get; cannot fetch unresolved prompt")
                raise RuntimeError("Langfuse SDK does not support resolve=false for prompts.get; upgrade the SDK to use this tool.") from e
            raise

        if prompt_response is None:
            label_msg = f" with label '{label}'" if label else ""
            version_msg = f" with version {version}" if version else ""
            raise LookupError(f"Prompt '{name}' not found{label_msg}{version_msg}")

        # Convert to dict
        raw_prompt = _sdk_object_to_python(prompt_response)

        resolved = not supports_resolve
        if resolved:
            logger.warning("Prompt resolve=false is not supported by the SDK; returning resolved prompt content.")

        logger.info(f"Retrieved prompt '{name}' (version={raw_prompt.get('version')}, resolved={resolved})")
        return {"data": raw_prompt, "metadata": {"found": True, "resolved": resolved}}

    except Exception as e:
        logger.error(f"Error fetching unresolved prompt '{name}': {e}")
        raise


async def list_prompts(
    ctx: Context,
    name: str | None = Field(None, description="Filter by exact prompt name"),
    label: str | None = Field(None, description="Filter by label (e.g., 'production', 'staging')"),
    tag: str | None = Field(None, description="Filter by tag"),
    page: int = Field(1, ge=1, description="Page number for pagination (starts at 1)"),
    limit: int = Field(50, ge=1, le=100, description="Items per page (max 100)"),
) -> ResponseDict:
    """List and filter prompts in the project.

    Returns metadata about prompts including versions, labels, tags, and last updated time.

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        name: Optional filter by exact prompt name
        label: Optional filter by label on any version
        tag: Optional filter by tag
        page: Page number for pagination (starts at 1)
        limit: Maximum items per page (max 100)

    Returns:
        A dictionary containing:
        - data: List of prompt metadata objects
        - metadata: Pagination info (page, limit, total)
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    try:
        # Build API kwargs
        api_kwargs: dict[str, Any] = {
            "page": page,
            "limit": limit,
        }
        if name:
            api_kwargs["name"] = name
        if label:
            api_kwargs["label"] = label
        if tag:
            api_kwargs["tag"] = tag

        # Call prompts list API
        response = state.langfuse_client.api.prompts.list(**api_kwargs)

        # Extract items and pagination
        items, pagination = _extract_items_from_response(response)
        raw_prompts = [_sdk_object_to_python(p) for p in items]

        # Simplify each prompt to metadata
        prompt_list = []
        for p in raw_prompts:
            prompt_list.append(
                {
                    "name": p.get("name"),
                    "type": p.get("type"),
                    "versions": p.get("versions", []),
                    "labels": p.get("labels", []),
                    "tags": p.get("tags", []),
                    "lastUpdatedAt": p.get("lastUpdatedAt") or p.get("updatedAt"),
                    "lastConfig": p.get("lastConfig") or p.get("config"),
                }
            )

        logger.info(f"Listed {len(prompt_list)} prompts (page={page}, limit={limit})")

        return {
            "data": prompt_list,
            "metadata": {
                "page": page,
                "limit": limit,
                "item_count": len(prompt_list),
                "total": pagination.get("total"),
            },
        }

    except Exception as e:
        logger.error(f"Error listing prompts: {e}")
        raise


async def create_text_prompt(
    ctx: Context,
    name: str = Field(..., description="The name of the prompt to create"),
    prompt: str = Field(..., description="Prompt text content (supports {{variables}})"),
    labels: list[str] | None = Field(None, description="Labels to assign (e.g., ['production', 'staging'])"),
    config: dict[str, Any] | None = Field(None, description="Optional JSON config (e.g., {model: 'gpt-4', temperature: 0.7})"),
    tags: list[str] | None = Field(None, description="Optional tags for organization (e.g., ['experimental', 'v2'])"),
    commit_message: str | None = Field(None, description="Optional commit message describing the changes"),
) -> ResponseDict:
    """Create a new text prompt version in Langfuse.

    Prompts are immutable; creating a new version is the only way to update prompt content.
    Labels are unique across versions - assigning a label here will move it from other versions.
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    try:
        labels = _normalize_field_default(labels)
        tags = _normalize_field_default(tags)
        config = _normalize_field_default(config)
        commit_message = _normalize_field_default(commit_message)

        if labels is not None and not isinstance(labels, list):
            raise ValueError("labels must be a list of strings")
        if labels is not None and not all(isinstance(label, str) for label in labels):
            raise ValueError("labels must be a list of strings")
        if labels is not None and not all(isinstance(label, str) for label in labels):
            raise ValueError("labels must be a list of strings")
        if tags is not None and not isinstance(tags, list):
            raise ValueError("tags must be a list of strings")
        if tags is not None and not all(isinstance(tag, str) for tag in tags):
            raise ValueError("tags must be a list of strings")
        if config is not None and not isinstance(config, dict):
            raise ValueError("config must be a JSON object")
        if commit_message is not None and not isinstance(commit_message, str):
            raise ValueError("commit_message must be a string")

        create_kwargs: dict[str, Any] = {
            "name": name,
            "prompt": prompt,
            "labels": labels or [],
            "tags": tags,
            "type": "text",
            "config": config or {},
        }
        if commit_message is not None:
            create_kwargs["commit_message"] = commit_message

        created_prompt = state.langfuse_client.create_prompt(**create_kwargs)

        result = {
            "name": getattr(created_prompt, "name", name),
            "version": getattr(created_prompt, "version", None),
            "type": "text",
            "prompt": getattr(created_prompt, "prompt", prompt),
            "labels": getattr(created_prompt, "labels", labels or []),
            "tags": getattr(created_prompt, "tags", tags or []),
            "config": getattr(created_prompt, "config", config or {}),
        }
        if hasattr(created_prompt, "commit_message"):
            result["commit_message"] = getattr(created_prompt, "commit_message", commit_message)
        if hasattr(created_prompt, "id"):
            result["id"] = getattr(created_prompt, "id")

        logger.info(f"Created text prompt '{result['name']}' (version={result['version']})")
        return {"data": result, "metadata": {"created": True}}

    except Exception as e:
        logger.error(f"Error creating text prompt '{name}': {e}")
        raise


async def create_chat_prompt(
    ctx: Context,
    name: str = Field(..., description="The name of the prompt to create"),
    prompt: list[dict[str, Any]] = Field(
        ..., description="Chat messages in the format [{role: 'system'|'user'|'assistant', content: '...'}]"
    ),
    labels: list[str] | None = Field(None, description="Labels to assign (e.g., ['production', 'staging'])"),
    config: dict[str, Any] | None = Field(None, description="Optional JSON config (e.g., {model: 'gpt-4', temperature: 0.7})"),
    tags: list[str] | None = Field(None, description="Optional tags for organization (e.g., ['experimental', 'v2'])"),
    commit_message: str | None = Field(None, description="Optional commit message describing the changes"),
) -> ResponseDict:
    """Create a new chat prompt version in Langfuse.

    Chat prompts are arrays of role/content messages. Prompts are immutable; create a new
    version to update content. Labels are unique across versions.
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    try:
        labels = _normalize_field_default(labels)
        tags = _normalize_field_default(tags)
        config = _normalize_field_default(config)
        commit_message = _normalize_field_default(commit_message)

        if labels is not None and not isinstance(labels, list):
            raise ValueError("labels must be a list of strings")
        if labels is not None and not all(isinstance(label, str) for label in labels):
            raise ValueError("labels must be a list of strings")
        if tags is not None and not isinstance(tags, list):
            raise ValueError("tags must be a list of strings")
        if tags is not None and not all(isinstance(tag, str) for tag in tags):
            raise ValueError("tags must be a list of strings")
        if config is not None and not isinstance(config, dict):
            raise ValueError("config must be a JSON object")
        if commit_message is not None and not isinstance(commit_message, str):
            raise ValueError("commit_message must be a string")

        create_kwargs: dict[str, Any] = {
            "name": name,
            "prompt": prompt,
            "labels": labels or [],
            "tags": tags,
            "type": "chat",
            "config": config or {},
        }
        if commit_message is not None:
            create_kwargs["commit_message"] = commit_message

        created_prompt = state.langfuse_client.create_prompt(**create_kwargs)

        prompt_content = None
        if hasattr(created_prompt, "prompt"):
            prompt_content = getattr(created_prompt, "prompt")
        elif hasattr(created_prompt, "messages"):
            prompt_content = getattr(created_prompt, "messages")

        result = {
            "name": getattr(created_prompt, "name", name),
            "version": getattr(created_prompt, "version", None),
            "type": "chat",
            "prompt": prompt_content if prompt_content is not None else prompt,
            "labels": getattr(created_prompt, "labels", labels or []),
            "tags": getattr(created_prompt, "tags", tags or []),
            "config": getattr(created_prompt, "config", config or {}),
        }
        if hasattr(created_prompt, "commit_message"):
            result["commit_message"] = getattr(created_prompt, "commit_message", commit_message)
        if hasattr(created_prompt, "id"):
            result["id"] = getattr(created_prompt, "id")

        logger.info(f"Created chat prompt '{result['name']}' (version={result['version']})")
        return {"data": result, "metadata": {"created": True}}

    except Exception as e:
        logger.error(f"Error creating chat prompt '{name}': {e}")
        raise


async def update_prompt_labels(
    ctx: Context,
    name: str = Field(..., description="The name of the prompt to update"),
    version: int = Field(..., ge=1, description="The prompt version to update"),
    labels: list[str] = Field(
        ...,
        description=(
            "Labels to add to this version (can be empty to add none). Existing labels are preserved; labels are unique across versions."
        ),
    ),
) -> ResponseDict:
    """Update labels for a specific prompt version.

    This is the only supported mutation for existing prompts. Provided labels are added
    to the version (existing labels are preserved). Labels are unique across versions,
    and the 'latest' label is managed by Langfuse.
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    try:
        if labels is not None and not isinstance(labels, list):
            raise ValueError("labels must be a list of strings")
        labels_list = list(labels or [])

        def _merge_labels(existing: list[str], additions: list[str]) -> list[str]:
            return list(dict.fromkeys([*additions, *existing]))

        def _get_existing_labels() -> list[str]:
            try:
                if hasattr(state.langfuse_client, "get_prompt"):
                    prompt_obj = state.langfuse_client.get_prompt(name=name, version=version)
                elif hasattr(state.langfuse_client, "api") and hasattr(state.langfuse_client.api, "prompts"):
                    prompt_obj = _prompts_get(state.langfuse_client.api.prompts, name=name, version=version)
                else:
                    prompt_obj = None
            except Exception as exc:
                logger.warning(f"Unable to fetch existing labels for prompt '{name}' version {version}: {exc}")
                prompt_obj = None

            if prompt_obj is None:
                return []

            if isinstance(prompt_obj, dict):
                existing = prompt_obj.get("labels") or []
            else:
                existing = getattr(prompt_obj, "labels", []) or []
            return list(existing)

        def _try_update(update_fn: Any) -> Any | None:
            try:
                return update_fn(name=name, version=version, new_labels=labels_list)
            except TypeError:
                pass
            try:
                return update_fn(name=name, version=version, newLabels=labels_list)
            except TypeError:
                pass
            merged = _merge_labels(_get_existing_labels(), labels_list)
            try:
                return update_fn(name=name, version=version, labels=merged)
            except TypeError:
                return None

        updated_prompt = None
        if hasattr(state.langfuse_client, "update_prompt"):
            updated_prompt = _try_update(state.langfuse_client.update_prompt)
        elif hasattr(state.langfuse_client, "api"):
            api = state.langfuse_client.api
            for attr in ("prompt_version", "promptVersion", "prompt_versions", "promptVersions"):
                if not hasattr(api, attr):
                    continue
                updater = getattr(api, attr)
                if not hasattr(updater, "update"):
                    continue
                updated_prompt = _try_update(updater.update)
                if updated_prompt is not None:
                    break

        if updated_prompt is None:
            raise RuntimeError("Langfuse SDK does not expose a prompt label update method; upgrade the SDK to use this tool.")

        result = {
            "name": getattr(updated_prompt, "name", name),
            "version": getattr(updated_prompt, "version", version),
            "labels": getattr(updated_prompt, "labels", labels),
        }
        if hasattr(updated_prompt, "id"):
            result["id"] = getattr(updated_prompt, "id")

        logger.info(f"Updated labels for prompt '{result['name']}' (version={result['version']})")
        return {"data": result, "metadata": {"updated": True}}

    except Exception as e:
        logger.error(f"Error updating labels for prompt '{name}' (version={version}): {e}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Dataset Tools
# ─────────────────────────────────────────────────────────────────────────────


async def list_datasets(
    ctx: Context,
    page: int = Field(1, ge=1, description="Page number for pagination (starts at 1)"),
    limit: int = Field(50, ge=1, le=100, description="Items per page (max 100)"),
) -> ResponseDict:
    """List all datasets in the project with pagination.

    Returns metadata about datasets including name, description, item count, and timestamps.

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        page: Page number for pagination (starts at 1)
        limit: Maximum items per page (max 100)

    Returns:
        A dictionary containing:
        - data: List of dataset metadata objects
        - metadata: Pagination info (page, limit, total)
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    try:
        # Normalize pagination fields that may be FieldInfo when called directly
        page = _normalize_field_default(page) or 1
        limit = _normalize_field_default(limit) or 50

        response = state.langfuse_client.api.datasets.list(page=page, limit=limit)

        items, pagination = _extract_items_from_response(response)
        raw_datasets = [_sdk_object_to_python(d) for d in items]

        dataset_list = []
        for d in raw_datasets:
            dataset_list.append(
                {
                    "id": d.get("id"),
                    "name": d.get("name"),
                    "description": d.get("description"),
                    "metadata": d.get("metadata"),
                    "projectId": d.get("projectId") or d.get("project_id"),
                    "createdAt": d.get("createdAt") or d.get("created_at"),
                    "updatedAt": d.get("updatedAt") or d.get("updated_at"),
                }
            )

        logger.info(f"Listed {len(dataset_list)} datasets (page={page}, limit={limit})")

        return {
            "data": dataset_list,
            "metadata": {
                "page": page,
                "limit": limit,
                "item_count": len(dataset_list),
                "total": pagination.get("total"),
            },
        }

    except Exception as e:
        logger.error(f"Error listing datasets: {e}")
        raise


async def get_dataset(
    ctx: Context,
    name: str = Field(..., description="The name of the dataset to fetch"),
) -> ResponseDict:
    """Get a specific dataset by name.

    Retrieves dataset details including metadata and item count.

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        name: The name of the dataset to fetch

    Returns:
        A dictionary containing dataset details:
        - id: Unique dataset identifier
        - name: Dataset name
        - description: Dataset description
        - metadata: Custom metadata
        - items: List of dataset items (if included by the API)
        - runs: List of dataset runs (if included by the API)
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    try:
        dataset = state.langfuse_client.api.datasets.get(dataset_name=name)

        if dataset is None:
            raise LookupError(f"Dataset '{name}' not found")

        result = _sdk_object_to_python(dataset)

        logger.info(f"Fetched dataset '{name}'")

        return {
            "data": result,
            "metadata": {"name": name},
        }

    except Exception as e:
        logger.error(f"Error fetching dataset '{name}': {e}")
        raise


async def list_dataset_items(
    ctx: Context,
    dataset_name: str = Field(..., description="The name of the dataset to list items from"),
    source_trace_id: str | None = Field(None, description="Filter by source trace ID"),
    source_observation_id: str | None = Field(None, description="Filter by source observation ID"),
    page: int = Field(1, ge=1, description="Page number for pagination (starts at 1)"),
    limit: int = Field(50, ge=1, le=100, description="Items per page (max 100)"),
    output_mode: OUTPUT_MODE_LITERAL = Field(
        "compact",
        description="Output format: 'compact' truncates, 'full_json_string' returns full data, 'full_json_file' writes to file",
    ),
) -> ResponseDict | str:
    """List items in a dataset with pagination and optional filtering.

    Returns dataset items with their input, expected output, and metadata.

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        dataset_name: The name of the dataset to list items from
        source_trace_id: Optional filter by source trace ID
        source_observation_id: Optional filter by source observation ID
        page: Page number for pagination (starts at 1)
        limit: Maximum items per page (max 100)
        output_mode: How to format the response data

    Returns:
        A dictionary containing:
        - data: List of dataset item objects
        - metadata: Pagination info (page, limit, total, dataset_name)
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    try:
        # Normalize optional fields that may be FieldInfo when called directly
        source_trace_id = _normalize_field_default(source_trace_id)
        source_observation_id = _normalize_field_default(source_observation_id)
        page = _normalize_field_default(page) or 1
        limit = _normalize_field_default(limit) or 50

        api_kwargs: dict[str, Any] = {
            "dataset_name": dataset_name,
            "page": page,
            "limit": limit,
        }
        if source_trace_id:
            api_kwargs["source_trace_id"] = source_trace_id
        if source_observation_id:
            api_kwargs["source_observation_id"] = source_observation_id

        response = state.langfuse_client.api.dataset_items.list(**api_kwargs)

        items, pagination = _extract_items_from_response(response)
        raw_items = [_sdk_object_to_python(item) for item in items]

        mode = _ensure_output_mode(output_mode)
        processed_items, file_meta = process_data_with_mode(raw_items, mode, f"dataset_items_{dataset_name}", state)

        logger.info(f"Listed {len(raw_items)} items from dataset '{dataset_name}' (page={page}, limit={limit})")

        if mode == OutputMode.FULL_JSON_STRING:
            return processed_items

        metadata_block = {
            "dataset_name": dataset_name,
            "page": page,
            "limit": limit,
            "item_count": len(raw_items),
            "total": pagination.get("total"),
            "output_mode": mode.value,
        }
        if file_meta:
            metadata_block.update(file_meta)

        return {
            "data": processed_items,
            "metadata": metadata_block,
        }

    except Exception as e:
        logger.error(f"Error listing items from dataset '{dataset_name}': {e}")
        raise


async def get_dataset_item(
    ctx: Context,
    item_id: str = Field(..., description="The ID of the dataset item to fetch"),
    output_mode: OUTPUT_MODE_LITERAL = Field(
        "compact",
        description="Output format: 'compact' truncates, 'full_json_string' returns full data, 'full_json_file' writes to file",
    ),
) -> ResponseDict | str:
    """Get a specific dataset item by ID.

    Retrieves the full dataset item including input, expected output, metadata, and linked traces.

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        item_id: The ID of the dataset item to fetch
        output_mode: How to format the response data

    Returns:
        A dictionary containing the dataset item details:
        - id: Unique item identifier
        - datasetId: Parent dataset ID
        - input: Input data for the item
        - expectedOutput: Expected output data
        - metadata: Custom metadata
        - sourceTraceId: Linked trace ID (if any)
        - sourceObservationId: Linked observation ID (if any)
        - status: Item status (ACTIVE or ARCHIVED)
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    try:
        item = state.langfuse_client.api.dataset_items.get(id=item_id)

        if item is None:
            raise LookupError(f"Dataset item '{item_id}' not found")

        result = _sdk_object_to_python(item)

        mode = _ensure_output_mode(output_mode)
        processed_result, file_meta = process_data_with_mode(result, mode, f"dataset_item_{item_id}", state)

        logger.info(f"Fetched dataset item '{item_id}'")

        if mode == OutputMode.FULL_JSON_STRING:
            return processed_result

        metadata_block = {"item_id": item_id, "output_mode": mode.value}
        if file_meta:
            metadata_block.update(file_meta)

        return {
            "data": processed_result,
            "metadata": metadata_block,
        }

    except Exception as e:
        logger.error(f"Error fetching dataset item '{item_id}': {e}")
        raise


async def create_dataset(
    ctx: Context,
    name: str = Field(..., description="Name for the new dataset (must be unique in project)"),
    description: str | None = Field(None, description="Optional description of the dataset"),
    metadata: dict[str, Any] | None = Field(None, description="Optional custom metadata as key-value pairs"),
) -> ResponseDict:
    """Create a new dataset in the project.

    Datasets are used to store evaluation test cases with input/expected output pairs.

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        name: Name for the new dataset (must be unique)
        description: Optional description
        metadata: Optional custom metadata

    Returns:
        A dictionary containing the created dataset details:
        - id: Unique dataset identifier
        - name: Dataset name
        - description: Dataset description
        - metadata: Custom metadata
        - createdAt: Creation timestamp
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    try:
        # Normalize optional fields that may be FieldInfo when called directly
        description = _normalize_field_default(description)
        metadata = _normalize_field_default(metadata)

        # Use the high-level SDK method if available, otherwise use API directly
        if hasattr(state.langfuse_client, "create_dataset"):
            kwargs: dict[str, Any] = {"name": name}
            if description:
                kwargs["description"] = description
            if metadata:
                kwargs["metadata"] = metadata
            dataset = state.langfuse_client.create_dataset(**kwargs)
        else:
            from langfuse.api.resources.datasets.types.create_dataset_request import CreateDatasetRequest

            request = CreateDatasetRequest(
                name=name,
                description=description,
                metadata=metadata,
            )
            dataset = state.langfuse_client.api.datasets.create(request=request)

        result = _sdk_object_to_python(dataset)

        logger.info(f"Created dataset '{name}'")

        return {
            "data": result,
            "metadata": {"created": True, "name": name},
        }

    except Exception as e:
        logger.error(f"Error creating dataset '{name}': {e}")
        raise


async def create_dataset_item(
    ctx: Context,
    dataset_name: str = Field(..., description="Name of the dataset to add the item to"),
    input: Any = Field(None, description="Input data for the dataset item (any JSON-serializable value)"),
    expected_output: Any = Field(None, description="Expected output data for evaluation (any JSON-serializable value)"),
    metadata: dict[str, Any] | None = Field(None, description="Optional custom metadata as key-value pairs"),
    source_trace_id: str | None = Field(None, description="Optional trace ID to link this item to"),
    source_observation_id: str | None = Field(None, description="Optional observation ID to link this item to"),
    item_id: str | None = Field(None, description="Optional custom ID for the item (for upsert behavior)"),
    status: Literal["ACTIVE", "ARCHIVED"] | None = Field(None, description="Item status (default: ACTIVE)"),
) -> ResponseDict:
    """Create a new item in a dataset, or update if item_id already exists.

    Dataset items store input/expected output pairs for evaluation. If item_id is provided
    and already exists, the item will be updated (upsert behavior).

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        dataset_name: Name of the target dataset
        input: Input data for the item
        expected_output: Expected output for evaluation
        metadata: Optional custom metadata
        source_trace_id: Optional linked trace ID
        source_observation_id: Optional linked observation ID
        item_id: Optional custom ID (enables upsert)
        status: Item status (ACTIVE or ARCHIVED)

    Returns:
        A dictionary containing the created/updated item details
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    try:
        # Normalize optional fields that may be FieldInfo when called directly
        input = _normalize_field_default(input)
        expected_output = _normalize_field_default(expected_output)
        metadata = _normalize_field_default(metadata)
        source_trace_id = _normalize_field_default(source_trace_id)
        source_observation_id = _normalize_field_default(source_observation_id)
        item_id = _normalize_field_default(item_id)
        status = _normalize_field_default(status)

        # Use the high-level SDK method if available
        if hasattr(state.langfuse_client, "create_dataset_item"):
            kwargs: dict[str, Any] = {"dataset_name": dataset_name}
            if input is not None:
                kwargs["input"] = input
            if expected_output is not None:
                kwargs["expected_output"] = expected_output
            if metadata:
                kwargs["metadata"] = metadata
            if source_trace_id:
                kwargs["source_trace_id"] = source_trace_id
            if source_observation_id:
                kwargs["source_observation_id"] = source_observation_id
            if item_id:
                kwargs["id"] = item_id
            if status:
                kwargs["status"] = status
            item = state.langfuse_client.create_dataset_item(**kwargs)
        else:
            from langfuse.api.resources.dataset_items.types.create_dataset_item_request import CreateDatasetItemRequest

            request_kwargs: dict[str, Any] = {"dataset_name": dataset_name}
            if input is not None:
                request_kwargs["input"] = input
            if expected_output is not None:
                request_kwargs["expected_output"] = expected_output
            if metadata:
                request_kwargs["metadata"] = metadata
            if source_trace_id:
                request_kwargs["source_trace_id"] = source_trace_id
            if source_observation_id:
                request_kwargs["source_observation_id"] = source_observation_id
            if item_id:
                request_kwargs["id"] = item_id
            if status:
                from langfuse.api.resources.commons.types.dataset_status import DatasetStatus

                request_kwargs["status"] = DatasetStatus(status)

            request = CreateDatasetItemRequest(**request_kwargs)
            item = state.langfuse_client.api.dataset_items.create(request=request)

        result = _sdk_object_to_python(item)

        logger.info(f"Created/updated dataset item in '{dataset_name}' (id={result.get('id')})")

        return {
            "data": result,
            "metadata": {"created": True, "dataset_name": dataset_name, "item_id": result.get("id")},
        }

    except Exception as e:
        logger.error(f"Error creating dataset item in '{dataset_name}': {e}")
        raise


async def delete_dataset_item(
    ctx: Context,
    item_id: str = Field(..., description="The ID of the dataset item to delete"),
) -> ResponseDict:
    """Delete a dataset item by ID.

    This is a permanent deletion and cannot be undone.

    Args:
        ctx: Context object containing lifespan context with Langfuse client
        item_id: The ID of the dataset item to delete

    Returns:
        A dictionary confirming the deletion
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)

    try:
        response = state.langfuse_client.api.dataset_items.delete(id=item_id)

        result = _sdk_object_to_python(response) if response else {}

        logger.info(f"Deleted dataset item '{item_id}'")

        return {
            "data": result,
            "metadata": {"deleted": True, "item_id": item_id},
        }

    except Exception as e:
        logger.error(f"Error deleting dataset item '{item_id}': {e}")
        raise


def app_factory(
    public_key: str,
    secret_key: str,
    host: str,
    cache_size: int = 100,
    dump_dir: str = None,
    enabled_tools: set[str] | None = None,
    timeout: int = 30,
    read_only: bool = False,
) -> FastMCP:
    """Create a FastMCP server with Langfuse tools.

    Args:
        public_key: Langfuse public key
        secret_key: Langfuse secret key
        host: Langfuse API host URL
        cache_size: Size of LRU caches
        dump_dir: Directory for full_json_file output mode
        enabled_tools: Tool groups to enable (default: all). Options: traces, observations, sessions, exceptions, prompts, datasets, schema
        timeout: API request timeout in seconds (default: 30). The Langfuse SDK defaults to 5s which is too aggressive.
        read_only: If True, disable all write operations (create/update/delete tools).
    """
    if enabled_tools is None:
        enabled_tools = ALL_TOOL_GROUPS
    else:
        enabled_tools = {tool for tool in enabled_tools if tool in TOOL_GROUPS}
        if not enabled_tools:
            enabled_tools = ALL_TOOL_GROUPS

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[MCPState]:
        init_params = inspect.signature(Langfuse.__init__).parameters
        langfuse_kwargs = {
            "public_key": public_key,
            "secret_key": secret_key,
            "host": host,
            "debug": False,
            "flush_at": 0,
            "flush_interval": None,
        }
        if "timeout" in init_params:
            langfuse_kwargs["timeout"] = timeout
        if "tracing_enabled" in init_params:
            langfuse_kwargs["tracing_enabled"] = False

        state = MCPState(
            langfuse_client=Langfuse(**langfuse_kwargs),
            observation_cache=LRUCache(maxsize=cache_size),
            file_to_observations_map=LRUCache(maxsize=cache_size),
            exception_type_map=LRUCache(maxsize=cache_size),
            exceptions_by_filepath=LRUCache(maxsize=cache_size),
            dump_dir=dump_dir,
        )
        try:
            yield state
        finally:
            logger.info("Cleaning up Langfuse client")
            state.langfuse_client.flush()
            state.langfuse_client.shutdown()

    mcp = FastMCP("Langfuse MCP Server", lifespan=lifespan)

    # Tool function lookup
    tool_funcs = {
        "fetch_traces": fetch_traces,
        "fetch_trace": fetch_trace,
        "fetch_observations": fetch_observations,
        "fetch_observation": fetch_observation,
        "fetch_sessions": fetch_sessions,
        "get_session_details": get_session_details,
        "get_user_sessions": get_user_sessions,
        "find_exceptions": find_exceptions,
        "find_exceptions_in_file": find_exceptions_in_file,
        "get_exception_details": get_exception_details,
        "get_error_count": get_error_count,
        "get_prompt": get_prompt,
        "get_prompt_unresolved": get_prompt_unresolved,
        "list_prompts": list_prompts,
        "create_text_prompt": create_text_prompt,
        "create_chat_prompt": create_chat_prompt,
        "update_prompt_labels": update_prompt_labels,
        "get_data_schema": get_data_schema,
        # Dataset tools
        "list_datasets": list_datasets,
        "get_dataset": get_dataset,
        "list_dataset_items": list_dataset_items,
        "get_dataset_item": get_dataset_item,
        "create_dataset": create_dataset,
        "create_dataset_item": create_dataset_item,
        "delete_dataset_item": delete_dataset_item,
    }

    # Register only enabled tool groups (skip write tools in read-only mode)
    registered = []
    skipped_write = []
    for group in sorted(enabled_tools):
        if group in TOOL_GROUPS:
            for tool_name in TOOL_GROUPS[group]:
                if tool_name in tool_funcs:
                    if read_only and tool_name in WRITE_TOOLS:
                        skipped_write.append(tool_name)
                        continue
                    mcp.tool()(tool_funcs[tool_name])
                    registered.append(tool_name)

    if read_only and skipped_write:
        logger.info(f"Read-only mode: skipped {len(skipped_write)} write tools: {sorted(skipped_write)}")
    logger.info(f"Registered {len(registered)} tools from groups: {sorted(enabled_tools)}")
    return mcp


def main():
    """Entry point for the langfuse_mcp package."""
    _load_env_file()
    env_defaults = _read_env_defaults()
    parser = _build_arg_parser(env_defaults)
    args = parser.parse_args()

    global logger
    logger = configure_logging(args.log_level, args.log_to_console)
    logger.info("=" * 80)
    logger.info(f"Starting Langfuse MCP v{__version__}")
    logger.info(f"Python executable: {sys.executable}")
    logger.info("=" * 80)
    logger.info(
        "Environment defaults loaded: %s",
        {k: ("***" if "key" in k else v) for k, v in env_defaults.items()},
    )

    # Create dump directory if it doesn't exist
    if args.dump_dir:
        try:
            os.makedirs(args.dump_dir, exist_ok=True)
            logger.info(f"Dump directory configured: {args.dump_dir}")
        except (PermissionError, OSError) as e:
            logger.error(f"Failed to create dump directory {args.dump_dir}: {e}")
            args.dump_dir = None

    # Parse enabled tool groups
    if args.tools.lower() == "all":
        enabled_tools = ALL_TOOL_GROUPS
    else:
        enabled_tools = {t.strip().lower() for t in args.tools.split(",") if t.strip()}
        invalid = enabled_tools - ALL_TOOL_GROUPS
        if invalid:
            logger.warning(f"Unknown tool groups ignored: {invalid}. Valid: {ALL_TOOL_GROUPS}")
            enabled_tools = enabled_tools & ALL_TOOL_GROUPS
        if not enabled_tools:
            logger.warning("No valid tool groups provided; defaulting to all tools.")
            enabled_tools = ALL_TOOL_GROUPS

    logger.info(
        f"Starting MCP - host:{args.host} timeout:{args.timeout}s cache:{args.cache_size} "
        f"tools:{sorted(enabled_tools)} read_only:{args.read_only}"
    )
    app = app_factory(
        public_key=args.public_key,
        secret_key=args.secret_key,
        host=args.host,
        cache_size=args.cache_size,
        dump_dir=args.dump_dir,
        enabled_tools=enabled_tools,
        timeout=args.timeout,
        read_only=args.read_only,
    )

    app.run(transport="stdio")


if __name__ == "__main__":
    main()
