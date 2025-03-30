import argparse
import logging
import sys
import os
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from logging.handlers import RotatingFileHandler
from typing import Annotated, Any, Literal, Optional, Union, cast, List

from cachetools import LRUCache
from langfuse import Langfuse
from mcp.server.fastmcp import Context, FastMCP
from pydantic import AfterValidator, BaseModel, Field

__version__ = "0.1.0"

# Set up logging with rotation
LOG_FILE = "/tmp/langfuse_mcp.log"
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# Create handlers - only use file handler, no console handler
file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,  # Keep 5 backup files
    encoding='utf-8'
)

# Set formatter for handlers
formatter = logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT)
file_handler.setFormatter(formatter)

# Configure root logger
logging.basicConfig(
    level=logging.INFO,  # Change from DEBUG to INFO to reduce verbosity
    handlers=[file_handler]  # Only use file handler
)

logger = logging.getLogger('langfuse_mcp')
logger.info("=" * 80)
logger.info(f"Langfuse MCP v{__version__} loading...")
logger.info(f"Python version: {sys.version}")
logger.info(f"Running from: {__file__}")
logger.info("=" * 80)

# Constants
HOUR = 60  # minutes
DAY = 24 * HOUR


@dataclass
class MCPState:
    """State object passed from lifespan context to tools.
    
    Contains the Langfuse client instance and various caches used to optimize 
    performance when querying and filtering observations and exceptions.
    """
    langfuse_client: Langfuse
    # LRU caches for efficient exception lookup
    observation_cache: LRUCache = field(
        default_factory=lambda: LRUCache(maxsize=100),
        metadata={"description": "Cache for observations to reduce API calls"}
    )
    file_to_observations_map: LRUCache = field(
        default_factory=lambda: LRUCache(maxsize=100),
        metadata={"description": "Mapping of file paths to observation IDs"}
    )
    exception_type_map: LRUCache = field(
        default_factory=lambda: LRUCache(maxsize=100),
        metadata={"description": "Mapping of exception types to observation IDs"}
    )
    exceptions_by_filepath: LRUCache = field(
        default_factory=lambda: LRUCache(maxsize=100),
        metadata={"description": "Mapping of file paths to exception details"}
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
    if age > 7 * DAY:
        raise ValueError("Age cannot be more than 7 days (10080 minutes)")
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
def _get_cached_observation(langfuse_client: Langfuse, observation_id: str) -> Optional[Any]:
    """Cache observation details to avoid duplicate API calls."""
    try:
        return langfuse_client.fetch_observation(observation_id).data
    except Exception as e:
        logger.warning(f"Error fetching observation {observation_id}: {str(e)}")
        return None


async def _efficient_fetch_observations(
    state: MCPState, 
    from_timestamp: datetime, 
    to_timestamp: datetime,
    filepath: Optional[str] = None
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
    observations_response = langfuse_client.fetch_observations(
        from_start_time=from_timestamp,
        to_start_time=to_timestamp,
        type="SPAN",
    )
    
    # Process observations and build indices
    observations = {}
    for obs in observations_response.data:
        if not hasattr(obs, 'events') or not obs.events:
            continue
            
        for event in obs.events:
            if not event.attributes.get("exception.type"):
                continue
                
            # Store observation
            observations[obs.id] = obs
            
            # Update file index if we have filepath info
            if hasattr(obs, 'metadata') and obs.metadata:
                file = obs.metadata.get("code.filepath")
                if file:
                    if file not in state.file_to_observations_map:
                        state.file_to_observations_map[file] = set()
                    state.file_to_observations_map[file].add(obs.id)
                    
            # Update exception type index
            exc_type = event.attributes["exception.type"]
            if exc_type not in state.exception_type_map:
                state.exception_type_map[exc_type] = set()
            state.exception_type_map[exc_type].add(obs.id)
    
    # Cache the processed observations
    state.observation_cache[cache_key] = observations
    
    return observations


async def fetch_traces(
    ctx: Context,
    age: int = Field(..., description="Minutes ago to start looking (e.g., 1440 for 24 hours)"),
    name: Optional[str] = Field(None, description="Name of the trace to filter by"),
    user_id: Optional[str] = Field(None, description="User ID to filter traces by"),
    session_id: Optional[str] = Field(None, description="Session ID to filter traces by"),
    metadata: Optional[dict] = Field(None, description="Metadata fields to filter by"),
    page: int = Field(1, description="Page number for pagination (starts at 1)"),
    limit: int = Field(50, description="Maximum number of traces to return per page"),
    tags: Optional[str] = Field(None, description="Tag or list of tags to filter traces by")
) -> List[dict]:
    """Find traces based on filters.
    
    Uses the Langfuse API to search for traces that match the provided filters.
    All filter parameters are optional - if not provided, no filtering is applied
    for that field.
    
    Args:
        age: Minutes ago to start looking (e.g., 1440 for 24 hours)
        name: Name of the trace to filter by (optional)
        user_id: User ID to filter traces by (optional)
        session_id: Session ID to filter traces by (optional)
        metadata: Metadata fields to filter by (optional)
        page: Page number for pagination (starts at 1)
        limit: Maximum number of traces to return per page
        tags: Tag or list of tags to filter traces by
    
    Returns:
        List of trace objects matching the filters
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)
    
    # Log the filters being used
    filters_log = {k: v for k, v in locals().items() if k not in ['ctx', 'state']}
    logger.info(f"Fetching traces with filters: {filters_log}")
    
    # Calculate timestamps from age
    from_timestamp = datetime.now(UTC) - timedelta(minutes=age)
    logger.info(f"Calculated from_timestamp from age {age} minutes: {from_timestamp}")
    
    try:
        # Use the fetch_traces method provided by the Langfuse SDK
        logger.debug(f"Calling fetch_traces with params: name={name}, user_id={user_id}, session_id={session_id}, " 
                    f"from_timestamp={from_timestamp}, "
                    f"page={page}, limit={limit}, tags={tags}")
        
        response = state.langfuse_client.fetch_traces(
            name=name,
            user_id=user_id,
            session_id=session_id,
            from_timestamp=from_timestamp,
            page=page,
            limit=limit,
            tags=tags
        )
        
        # Convert response to a serializable format
        # The response is a FetchTracesResponse object with data and meta fields
        traces = [trace.dict() if hasattr(trace, 'dict') else trace for trace in response.data]
        
        logger.info(f"Found {len(traces)} traces")
        return traces
    except Exception as e:
        logger.error(f"Error fetching traces: {str(e)}")
        logger.error(f"Parameters: name={name}, user_id={user_id}, session_id={session_id}, "
                    f"from_timestamp={from_timestamp} (type: {type(from_timestamp)}), "
                    f"page={page}, limit={limit}, tags={tags}")
        logger.exception(e)
        raise


async def find_exceptions(
    ctx: Context,
    age: ValidatedAge = Field(
        ..., 
        description="Number of minutes to look back (positive integer, max 7 days/10080 minutes)",
        gt=0,
        le=7 * DAY
    ),
    group_by: Literal["file", "function", "type"] = Field(
        "file", 
        description="How to group exceptions - 'file' groups by filename, 'function' groups by function name, or 'type' groups by exception type"
    )
) -> List[ExceptionCount]:
    """Get exception counts grouped by file path, function, or type.
    
    Args:
        age: Number of minutes to look back (positive integer, max 7 days/10080 minutes)
        group_by: How to group exceptions - "file" groups by filename, "function" groups by function name, 
                  or "type" groups by exception type
    
    Returns:
        List of exception counts grouped by the specified category (file, function, or type)
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)
    
    # Calculate from_timestamp based on age
    from_timestamp = datetime.now(UTC) - timedelta(minutes=age)
    to_timestamp = datetime.now(UTC)
    
    try:
        # Fetch all SPAN observations since they may contain exceptions
        response = state.langfuse_client.fetch_observations(
            type="SPAN",
            from_start_time=from_timestamp,
            to_start_time=to_timestamp,
            limit=100  # Adjust based on your needs
        )
        
        # Process observations to find and group exceptions
        exception_groups = Counter()
        
        for observation in response.data:
            # Check if this observation has exception events
            if hasattr(observation, 'events'):
                for event in observation.events:
                    if not isinstance(event, dict):
                        event_dict = event.dict() if hasattr(event, 'dict') else {}
                    else:
                        event_dict = event
                        
                    # Check if this is an exception event
                    if event_dict.get('attributes', {}).get('exception.type'):
                        # Get the grouping key based on group_by parameter
                        if group_by == 'file':
                            # Group by file path from metadata
                            if hasattr(observation, 'metadata') and observation.metadata:
                                meta = observation.metadata
                                if isinstance(meta, dict) and meta.get('code.filepath'):
                                    group_key = meta.get('code.filepath')
                                else:
                                    group_key = 'unknown_file'
                            else:
                                group_key = 'unknown_file'
                        elif group_by == 'function':
                            # Group by function name from metadata
                            if hasattr(observation, 'metadata') and observation.metadata:
                                meta = observation.metadata
                                if isinstance(meta, dict) and meta.get('code.function'):
                                    group_key = meta.get('code.function')
                                else:
                                    group_key = 'unknown_function'
                            else:
                                group_key = 'unknown_function'
                        elif group_by == 'type':
                            # Group by exception type
                            group_key = event_dict.get('attributes', {}).get('exception.type', 'unknown_exception')
                        else:
                            group_key = 'unknown'
                            
                        # Increment the counter for this group
                        exception_groups[group_key] += 1
        
        # Convert counter to list of ExceptionCount objects
        results = [
            ExceptionCount(group=group, count=count)
            for group, count in exception_groups.most_common(50)  # Limit to 50 most common
        ]
        
        logger.info(f"Found {len(results)} exception groups")
        return results
    except Exception as e:
        logger.error(f"Error finding exceptions: {str(e)}")
        logger.exception(e)
        raise


async def find_exceptions_in_file(
    ctx: Context,
    filepath: str = Field(..., description="Path to the file to search for exceptions (full path including extension)"),
    age: ValidatedAge = Field(
        ..., 
        description="Number of minutes to look back (positive integer, max 7 days/10080 minutes)",
        gt=0,
        le=7 * DAY
    )
) -> List[dict]:
    """Get detailed exception info for a specific file.
    
    Args:
        filepath: Path to the file to search for exceptions (full path including extension)
        age: Number of minutes to look back (positive integer, max 7 days/10080 minutes)
    
    Returns:
        List of exception details found in the specified file
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)
    
    # Calculate from_timestamp based on age
    from_timestamp = datetime.now(UTC) - timedelta(minutes=age)
    to_timestamp = datetime.now(UTC)
    
    try:
        # Fetch all SPAN observations since they may contain exceptions
        response = state.langfuse_client.fetch_observations(
            type="SPAN",
            from_start_time=from_timestamp,
            to_start_time=to_timestamp,
            limit=100  # Adjust based on your needs
        )
        
        # Process observations to find exceptions in the specified file
        exceptions = []
        
        for observation in response.data:
            # Check if this observation is related to the specified file
            file_matches = False
            if hasattr(observation, 'metadata') and observation.metadata:
                meta = observation.metadata
                if isinstance(meta, dict) and meta.get('code.filepath') == filepath:
                    file_matches = True
            
            if not file_matches:
                continue
                
            # Check if this observation has exception events
            if hasattr(observation, 'events'):
                for event in observation.events:
                    if not isinstance(event, dict):
                        event_dict = event.dict() if hasattr(event, 'dict') else {}
                    else:
                        event_dict = event
                        
                    # Check if this is an exception event
                    if event_dict.get('attributes', {}).get('exception.type'):
                        # Extract exception details
                        exception_info = {
                            'observation_id': observation.id if hasattr(observation, 'id') else 'unknown',
                            'trace_id': observation.trace_id if hasattr(observation, 'trace_id') else 'unknown',
                            'timestamp': observation.start_time if hasattr(observation, 'start_time') else 'unknown',
                            'exception_type': event_dict.get('attributes', {}).get('exception.type', 'unknown'),
                            'exception_message': event_dict.get('attributes', {}).get('exception.message', ''),
                            'exception_stacktrace': event_dict.get('attributes', {}).get('exception.stacktrace', ''),
                            'function': meta.get('code.function', 'unknown') if isinstance(meta, dict) else 'unknown',
                            'line_number': meta.get('code.lineno', 'unknown') if isinstance(meta, dict) else 'unknown',
                        }
                        
                        exceptions.append(exception_info)
        
        # Sort exceptions by timestamp (newest first)
        exceptions.sort(key=lambda x: x['timestamp'] if isinstance(x['timestamp'], str) else '', reverse=True)
        
        logger.info(f"Found {len(exceptions)} exceptions in file {filepath}")
        return exceptions[:10]  # Return at most 10 exceptions
    except Exception as e:
        logger.error(f"Error finding exceptions in file {filepath}: {str(e)}")
        logger.exception(e)
        raise


async def get_session(
    ctx: Context,
    session_id: str
) -> dict:
    """Get session details by ID.
    
    Args:
        session_id: The ID of the session to retrieve (unique identifier string)
    
    Returns:
        Session details including associated traces, timestamps, and metrics
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)
    
    try:
        # Fetch traces with this session ID
        response = state.langfuse_client.fetch_traces(
            session_id=session_id,
            limit=50  # Get a reasonable number of traces for this session
        )
        
        # If no traces were found, return an empty dict
        if not response.data:
            logger.info(f"No session found with ID: {session_id}")
            return {
                "id": session_id,
                "traces": [],
                "found": False
            }
            
        # Convert traces to a serializable format
        traces = [trace.dict() if hasattr(trace, 'dict') else trace for trace in response.data]
        
        # Create a session object with all traces that have this session ID
        session = {
            "id": session_id,
            "traces": traces,
            "trace_count": len(traces),
            "first_timestamp": traces[0].get("timestamp") if traces else None,
            "last_timestamp": traces[-1].get("timestamp") if traces else None,
            "user_id": traces[0].get("user_id") if traces else None,
            "found": True
        }
        
        logger.info(f"Found session {session_id} with {len(traces)} traces")
        return session
    except Exception as e:
        logger.error(f"Error getting session {session_id}: {str(e)}")
        logger.exception(e)
        raise


async def get_user_sessions(
    ctx: Context,
    user_id: str,
    age: int = Field(..., description="Minutes ago to start looking (e.g., 1440 for 24 hours)")
) -> List[dict]:
    """Get sessions for a user within a time range.
    
    Args:
        user_id: The ID of the user to retrieve sessions for (unique identifier string)
        age: Minutes ago to start looking (e.g., 1440 for 24 hours)
    
    Returns:
        List of session objects associated with the user in the specified time range
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)
    
    # Calculate timestamp from age
    from_timestamp = datetime.now(UTC) - timedelta(minutes=age)
    logger.info(f"Calculated from_timestamp from age {age} minutes: {from_timestamp}")
    
    try:
        # Fetch traces for this user
        logger.debug(f"Calling fetch_traces with params: user_id={user_id}, "
                    f"from_timestamp={from_timestamp} (type: {type(from_timestamp)}), "
                    f"limit=100")
        
        response = state.langfuse_client.fetch_traces(
            user_id=user_id,
            from_timestamp=from_timestamp,
            limit=100  # Get a reasonable number of traces
        )
        
        # If no traces were found, return an empty list
        if not response.data:
            logger.info(f"No sessions found for user: {user_id}")
            return []
            
        # Convert traces to a serializable format
        traces = [trace.dict() if hasattr(trace, 'dict') else trace for trace in response.data]
        
        # Group traces by session_id
        sessions_dict = {}
        for trace in traces:
            session_id = trace.get("session_id")
            if not session_id:
                continue
                
            if session_id not in sessions_dict:
                sessions_dict[session_id] = {
                    "id": session_id,
                    "traces": [],
                    "first_timestamp": None,
                    "last_timestamp": None,
                    "user_id": user_id
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
        sessions.sort(key=lambda x: x["last_timestamp"] if x["last_timestamp"] else "", reverse=True)
        
        logger.info(f"Found {len(sessions)} sessions for user {user_id}")
        return sessions
    except Exception as e:
        logger.error(f"Error getting sessions for user {user_id}: {str(e)}")
        logger.exception(e)
        raise


async def get_error_count(
    ctx: Context,
    age: ValidatedAge = Field(
        ..., 
        description="Number of minutes to look back (positive integer, max 100 minutes)",
        gt=0,
        le=100
    )
) -> dict:
    """Get number of traces with exceptions in last N minutes.
    
    Args:
        age: Number of minutes to look back (positive integer, max 100 minutes)
    
    Returns:
        Dictionary with error statistics including trace count, observation count, and exception count
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)
    
    # Calculate from_timestamp based on age
    from_timestamp = datetime.now(UTC) - timedelta(minutes=age)
    to_timestamp = datetime.now(UTC)
    
    try:
        # Fetch all SPAN observations since they may contain exceptions
        response = state.langfuse_client.fetch_observations(
            type="SPAN",
            from_start_time=from_timestamp,
            to_start_time=to_timestamp,
            limit=100  # Limit to 100 as per API constraints
        )
        
        # Count traces and observations with exceptions
        trace_ids_with_exceptions = set()
        observations_with_exceptions = 0
        total_exceptions = 0
        
        for observation in response.data:
            has_exception = False
            exception_count = 0
            
            # Check if this observation has exception events
            if hasattr(observation, 'events'):
                for event in observation.events:
                    if not isinstance(event, dict):
                        event_dict = event.dict() if hasattr(event, 'dict') else {}
                    else:
                        event_dict = event
                        
                    # Check if this is an exception event
                    if event_dict.get('attributes', {}).get('exception.type'):
                        has_exception = True
                        exception_count += 1
            
            if has_exception:
                observations_with_exceptions += 1
                total_exceptions += exception_count
                
                # Add the trace ID to our set
                if hasattr(observation, 'trace_id') and observation.trace_id:
                    trace_ids_with_exceptions.add(observation.trace_id)
        
        result = {
            "age_minutes": age,
            "from_timestamp": from_timestamp.isoformat(),
            "to_timestamp": to_timestamp.isoformat(),
            "trace_count": len(trace_ids_with_exceptions),
            "observation_count": observations_with_exceptions,
            "exception_count": total_exceptions
        }
        
        logger.info(f"Found {total_exceptions} exceptions in {observations_with_exceptions} observations across {len(trace_ids_with_exceptions)} traces")
        return result
    except Exception as e:
        logger.error(f"Error getting error count for the last {age} minutes: {str(e)}")
        logger.exception(e)
        raise


async def get_exception_details(
    ctx: Context,
    trace_id: str,
    span_id: Optional[str] = None
) -> List[dict]:
    """Get detailed exception info for a trace/span.
    
    Args:
        trace_id: The ID of the trace to analyze for exceptions (unique identifier string)
        span_id: Optional span ID to filter by specific span (unique identifier string)
    
    Returns:
        List of detailed exception information objects found in the specified trace/span
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)
    
    try:
        # First get the trace details
        trace_response = state.langfuse_client.fetch_trace(trace_id)
        if not trace_response or not trace_response.data:
            logger.warning(f"Trace not found: {trace_id}")
            return []
            
        # Get all observations for this trace
        observations_response = state.langfuse_client.fetch_observations(
            trace_id=trace_id,
            limit=100  # Get a reasonable number of observations
        )
        
        if not observations_response or not observations_response.data:
            logger.warning(f"No observations found for trace: {trace_id}")
            return []
            
        # Filter observations if span_id is provided
        if span_id:
            filtered_observations = [
                obs for obs in observations_response.data 
                if hasattr(obs, 'id') and obs.id == span_id
            ]
        else:
            filtered_observations = observations_response.data
            
        # Process observations to find exceptions
        exceptions = []
        
        for observation in filtered_observations:
            # Check if this observation has exception events
            if hasattr(observation, 'events'):
                for event in observation.events:
                    if not isinstance(event, dict):
                        event_dict = event.dict() if hasattr(event, 'dict') else {}
                    else:
                        event_dict = event
                        
                    # Check if this is an exception event
                    if event_dict.get('attributes', {}).get('exception.type'):
                        # Get metadata for additional context
                        metadata = {}
                        if hasattr(observation, 'metadata') and observation.metadata:
                            if isinstance(observation.metadata, dict):
                                metadata = observation.metadata
                        
                        # Extract exception details
                        exception_info = {
                            'observation_id': observation.id if hasattr(observation, 'id') else 'unknown',
                            'observation_name': observation.name if hasattr(observation, 'name') else 'unknown',
                            'observation_type': observation.type if hasattr(observation, 'type') else 'unknown',
                            'timestamp': observation.start_time if hasattr(observation, 'start_time') else 'unknown',
                            'exception_type': event_dict.get('attributes', {}).get('exception.type', 'unknown'),
                            'exception_message': event_dict.get('attributes', {}).get('exception.message', ''),
                            'exception_stacktrace': event_dict.get('attributes', {}).get('exception.stacktrace', ''),
                            'filepath': metadata.get('code.filepath', 'unknown'),
                            'function': metadata.get('code.function', 'unknown'),
                            'line_number': metadata.get('code.lineno', 'unknown'),
                            'event_id': event_dict.get('id', 'unknown'),
                            'event_name': event_dict.get('name', 'unknown'),
                        }
                        
                        exceptions.append(exception_info)
        
        # Sort exceptions by timestamp (newest first)
        exceptions.sort(key=lambda x: x['timestamp'] if isinstance(x['timestamp'], str) else '', reverse=True)
        
        logger.info(f"Found {len(exceptions)} exceptions in trace {trace_id}")
        return exceptions
    except Exception as e:
        logger.error(f"Error getting exception details for trace {trace_id}: {str(e)}")
        logger.exception(e)
        raise


async def get_data_schema(
    ctx: Context,
    dummy: str = ""
) -> str:
    """Get schema of trace, span and event objects.
    
    Args:
        dummy: Unused parameter for API compatibility (can be left empty)
    
    Returns:
        String containing the detailed schema definitions for traces, spans, events, 
        and other core Langfuse data structures
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)
    
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


async def get_trace(
    ctx: Context,
    trace_id: str
) -> dict:
    """Get a single trace by ID with full details.
    
    Args:
        trace_id: The ID of the trace to fetch (unique identifier string)
    
    Returns:
        Complete trace object with all associated observations and metadata
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)
    
    try:
        # Use the fetch_trace method provided by the Langfuse SDK
        response = state.langfuse_client.fetch_trace(trace_id)
        
        # Convert response to a serializable format
        trace = response.data.dict() if hasattr(response.data, 'dict') else response.data
        
        logger.info(f"Retrieved trace {trace_id}")
        return trace
    except Exception as e:
        logger.error(f"Error fetching trace {trace_id}: {str(e)}")
        logger.exception(e)
        raise


async def get_observation(
    ctx: Context,
    observation_id: str
) -> dict:
    """Get a single observation by ID.
    
    Args:
        observation_id: The ID of the observation to fetch (unique identifier string)
    
    Returns:
        Complete observation object with all associated events and metadata
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)
    
    try:
        # Use the fetch_observation method provided by the Langfuse SDK
        response = state.langfuse_client.fetch_observation(observation_id)
        
        # Convert response to a serializable format
        observation = response.data.dict() if hasattr(response.data, 'dict') else response.data
        
        logger.info(f"Retrieved observation {observation_id}")
        return observation
    except Exception as e:
        logger.error(f"Error fetching observation {observation_id}: {str(e)}")
        logger.exception(e)
        raise


async def get_observations_by_type(
    ctx: Context,
    type: Literal["SPAN", "GENERATION", "EVENT"] = Field(..., description="The observation type to filter by ('SPAN', 'GENERATION', or 'EVENT')"),
    age: int = Field(..., description="Minutes ago to start looking (e.g., 1440 for 24 hours)"),
    name: Optional[str] = Field(None, description="Optional name filter (string pattern to match)"),
    user_id: Optional[str] = Field(None, description="Optional user ID filter (exact match)"),
    trace_id: Optional[str] = Field(None, description="Optional trace ID filter (exact match)"),
    parent_observation_id: Optional[str] = Field(None, description="Optional parent observation ID filter (exact match)"),
    page: int = Field(1, description="Page number for pagination (starts at 1)"),
    limit: int = Field(50, description="Maximum number of observations to return per page")
) -> List[dict]:
    """Get observations filtered by type.
    
    Args:
        type: The observation type to filter by ("SPAN", "GENERATION", or "EVENT")
        age: Minutes ago to start looking (e.g., 1440 for 24 hours)
        name: Optional name filter (string pattern to match)
        user_id: Optional user ID filter (exact match)
        trace_id: Optional trace ID filter (exact match)
        parent_observation_id: Optional parent observation ID filter (exact match)
        page: Page number for pagination (starts at 1)
        limit: Maximum number of observations to return per page
    
    Returns:
        List of observation objects matching the filters
    """
    state = cast(MCPState, ctx.request_context.lifespan_context)
    
    # Calculate timestamps from age
    from_start_time = datetime.now(UTC) - timedelta(minutes=age)
    logger.info(f"Calculated from_start_time from age {age} minutes: {from_start_time}")
    
    try:
        # Use the fetch_observations method provided by the Langfuse SDK
        response = state.langfuse_client.fetch_observations(
            type=type,
            name=name,
            user_id=user_id,
            trace_id=trace_id,
            parent_observation_id=parent_observation_id,
            from_start_time=from_start_time,
            page=page,
            limit=limit
        )
        
        # Convert response to a serializable format
        observations = [obs.dict() if hasattr(obs, 'dict') else obs for obs in response.data]
        
        logger.info(f"Found {len(observations)} observations of type '{type}'")
        return observations
    except Exception as e:
        logger.error(f"Error fetching observations of type '{type}': {str(e)}")
        logger.exception(e)
        raise


def app_factory(public_key: str, secret_key: str, host: str, no_auth_check: bool = False, cache_size: int = 100) -> FastMCP:
    """Create a FastMCP server with Langfuse tools.
    
    Args:
        public_key: Langfuse public key
        secret_key: Langfuse secret key
        host: Langfuse API host URL
        no_auth_check: Skip authentication check
        cache_size: Size of LRU caches used for caching data
        
    Returns:
        FastMCP server instance
    """
    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[MCPState]:
        """Initialize and cleanup MCP server state.
        
        Args:
            server: MCP server instance
            
        Returns:
            AsyncIterator yielding MCPState
        """
        # Initialize state
        state = MCPState(
            langfuse_client=Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host,
                debug=False,  # Disable debug mode since we're only querying
                threads=1,    # Reduce thread count since we're not sending telemetry
                flush_at=0,   # Disable automatic flushing since we're not sending data
                flush_interval=None,  # Disable flush interval
                enabled=True  # Keep enabled for API queries
            ),
            observation_cache=LRUCache(maxsize=cache_size),
            file_to_observations_map=LRUCache(maxsize=cache_size),
            exception_type_map=LRUCache(maxsize=cache_size),
            exceptions_by_filepath=LRUCache(maxsize=cache_size)
        )
        
        if not no_auth_check:
            logger.info("Running authentication check...")
            auth_result = state.langfuse_client.auth_check()
            if not auth_result:
                raise ValueError("Authentication failed with provided credentials")
        
        try:
            yield state
        finally:
            # Cleanup
            logger.info("Cleaning up Langfuse client")
            state.langfuse_client.flush()
            state.langfuse_client.shutdown()

    # Create the MCP server with lifespan context manager
    mcp = FastMCP("Langfuse MCP Server", lifespan=lifespan)
    
    # Register all tools
    mcp.tool()(fetch_traces)
    mcp.tool()(find_exceptions)
    mcp.tool()(find_exceptions_in_file)
    mcp.tool()(get_session)
    mcp.tool()(get_user_sessions)
    mcp.tool()(get_error_count)
    mcp.tool()(get_exception_details)
    mcp.tool()(get_data_schema)
    mcp.tool()(get_trace)
    mcp.tool()(get_observation)
    mcp.tool()(get_observations_by_type)
    
    return mcp


def main():
    """Entry point for the langfuse_mcp package."""
    logger.info("=" * 80)
    logger.info(f"Starting Langfuse MCP v{__version__}")
    logger.info(f"Python executable: {sys.executable}")
    logger.info("=" * 80)

    parser = argparse.ArgumentParser(description="Langfuse MCP Server")
    parser.add_argument(
        "--public-key",
        type=str,
        required=True,
        help="Langfuse public key"
    )
    parser.add_argument(
        "--secret-key",
        type=str,
        required=True,
        help="Langfuse secret key"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="https://cloud.langfuse.com",
        help="Langfuse host URL"
    )
    parser.add_argument(
        "--no-auth-check",
        action="store_true",
        help="Skip authentication check"
    )
    parser.add_argument(
        "--cache-size",
        type=int,
        default=100,
        help="Size of LRU caches used for caching data"
    )
    
    args = parser.parse_args()
    
    logger.info(f"Starting MCP - host:{args.host} auth:{not args.no_auth_check} cache:{args.cache_size} keys:{args.public_key[:4]}.../{args.secret_key[:4]}...")
    app = app_factory(
        public_key=args.public_key,
        secret_key=args.secret_key,
        host=args.host,
        no_auth_check=args.no_auth_check,
        cache_size=args.cache_size
    )
    
    app.run(transport="stdio")


if __name__ == "__main__":
    main() 