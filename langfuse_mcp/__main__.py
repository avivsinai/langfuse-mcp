import argparse
import asyncio
import logging
import os
import sys
import json
from logging.handlers import RotatingFileHandler
from collections.abc import AsyncIterator
from collections import Counter
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Optional, List, Dict, Annotated, Any, Union, cast, Literal
from functools import lru_cache

from langfuse import Langfuse
from mcp.server.fastmcp import Context, FastMCP
from pydantic import AfterValidator, BaseModel

# Set up logging with rotation
LOG_FILE = "langfuse_mcp.log"
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# Create handlers
console_handler = logging.StreamHandler(stream=sys.stdout)
file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,  # Keep 5 backup files
    encoding='utf-8'
)

# Set formatter for handlers
formatter = logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT)
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    handlers=[console_handler, file_handler]
)

logger = logging.getLogger('langfuse_mcp')

# Constants
HOUR = 60  # minutes
DAY = 24 * HOUR


class MCPState:
    """State object passed from lifespan context to tools."""
    def __init__(self, langfuse_client: Optional[Langfuse] = None, error: Optional[str] = None):
        self.langfuse_client = langfuse_client
        self.error = error
        logger.info("MCPState initialized with Langfuse client: %s", 
                   "Active" if langfuse_client else "None")


class ExceptionCount(BaseModel):
    """Model for exception counts grouped by category."""
    group: str
    count: int


def validate_age(age: int) -> int:
    """Validate that age is positive and ≤ 7 days."""
    if age <= 0:
        raise ValueError("Age must be positive")
    if age > 7 * DAY:
        raise ValueError("Age cannot be more than 7 days")
    logger.debug(f"Age validated: {age} minutes")
    return age


ValidatedAge = Annotated[int, AfterValidator(validate_age)]


def get_langfuse_client(ctx: Context) -> tuple[Optional[Langfuse], Optional[str]]:
    """Helper function to get Langfuse client from context.
    
    Args:
        ctx: MCP context with access to lifespan context
        
    Returns:
        Tuple of (langfuse_client, error_message)
    """
    state = ctx.request_context.lifespan_context
    
    if isinstance(state, MCPState):
        return state.langfuse_client, state.error
    elif isinstance(state, dict) and "langfuse_client" in state:
        return state.get("langfuse_client"), state.get("error")
    else:
        return None, "Invalid state type in context"


async def find_traces(
    ctx: Context,
    name: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    from_timestamp: Optional[datetime] = None,
    to_timestamp: Optional[datetime] = None,
    page: int = 1,
    limit: int = 50,
    order_by: Optional[str] = None,
    tags: Optional[Union[str, List[str]]] = None,
) -> List[dict]:
    """Retrieve traces based on filters.
    
    Args:
        ctx: MCP context with access to Langfuse client
        name: Filter by trace name
        user_id: Filter by user ID
        session_id: Filter by session ID
        metadata: Filter by metadata key-value pairs
        from_timestamp: Start time range (ISO 8601)
        to_timestamp: End time range (ISO 8601)
        page: Page number for pagination
        limit: Items per page
        order_by: Field to order results by
        tags: Filter by tags
        
    Returns:
        List of trace dictionaries
    """
    logger.info(f"Finding traces with filters: name={name}, user_id={user_id}, session_id={session_id}")
    
    langfuse_client, error = get_langfuse_client(ctx)
    
    if not langfuse_client:
        error_msg = f"Langfuse client not initialized: {error}"
        logger.error(error_msg)
        return [{"error": error_msg}]

    try:
        traces_response = langfuse_client.fetch_traces(
            name=name,
            user_id=user_id,
            session_id=session_id,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
            page=page,
            limit=limit,
            order_by=order_by,
            tags=tags,
        )
        logger.info(f"Found {len(traces_response.data)} traces")
        return [trace.dict() for trace in traces_response.data]
    except Exception as e:
        logger.error(f"Error retrieving traces: {str(e)}", exc_info=True)
        return [{"error": f"Failed to retrieve traces: {str(e)}"}]


@lru_cache(maxsize=1000)
def _get_cached_observation(langfuse_client, observation_id: str) -> Optional[Any]:
    """Cache observation details to avoid duplicate API calls."""
    try:
        return langfuse_client.fetch_observation(observation_id).data
    except Exception as e:
        logger.warning(f"Error fetching observation {observation_id}: {str(e)}")
        return None


async def _batch_fetch_observations(langfuse_client, observation_ids: List[str]) -> Dict[str, Any]:
    """Batch fetch observations to reduce API calls."""
    observations = {}
    for obs_id in observation_ids:
        observation = _get_cached_observation(langfuse_client, obs_id)
        if observation:
            observations[obs_id] = observation
    return observations


async def find_exceptions(
    ctx: Context,
    age: ValidatedAge,
    group_by: Literal["file", "function", "type"] = "file",
) -> List[ExceptionCount]:
    """Get exception counts grouped by file path, function, or type from spans.

    Args:
        ctx: MCP context providing access to server state.
        age: Number of minutes to look back (max 7 days).
        group_by: Field to group by (file, function, or type).

    Returns:
        List of ExceptionCount objects with group and count.
    """
    logger.info(f"Finding exceptions for the past {age} minutes, grouped by {group_by}")
    
    langfuse_client, error = get_langfuse_client(ctx)
    
    if not langfuse_client:
        error_msg = f"Langfuse client not initialized: {error}"
        logger.error(error_msg)
        return [ExceptionCount(group=f"error: {error_msg}", count=0)]

    to_timestamp = datetime.now(UTC)
    from_timestamp = to_timestamp - timedelta(minutes=age)
    
    try:
        # Fetch all observations in a single call
        observations_response = langfuse_client.fetch_observations(
            from_start_time=from_timestamp,
            to_start_time=to_timestamp,
            type="SPAN"
        )
        
        # Get all observation IDs first
        observation_ids = [span.id for span in observations_response.data]
        
        # Batch fetch all observations
        observations = await _batch_fetch_observations(langfuse_client, observation_ids)
        
        # Process exceptions
        values = []
        for observation in observations.values():
            if not hasattr(observation, 'events') or not observation.events:
                continue
                
            has_exception = any(
                event.attributes.get("exception.type")
                for event in observation.events
            )
            
            if not has_exception:
                continue
                
            if group_by == "file":
                key = "code.filepath"
                if hasattr(observation, 'metadata') and observation.metadata and key in observation.metadata:
                    values.append(observation.metadata[key])
            elif group_by == "function":
                key = "code.function"
                if hasattr(observation, 'metadata') and observation.metadata and key in observation.metadata:
                    values.append(observation.metadata[key])
            elif group_by == "type":
                for event in observation.events:
                    if event.attributes.get("exception.type"):
                        values.append(event.attributes.get("exception.type"))
        
        values = [v for v in values if v is not None]
        counts = Counter(values)
        results = [ExceptionCount(group=group, count=count) for group, count in counts.items()]
        
        logger.info(f"Found {len(results)} exception groups")
        return results
    except Exception as e:
        logger.error(f"Error finding exceptions: {str(e)}", exc_info=True)
        return [ExceptionCount(group=f"error: {str(e)}", count=0)]


async def find_exceptions_in_file(
    ctx: Context,
    filepath: str,
    age: ValidatedAge,
) -> List[dict]:
    """Get detailed info about exceptions in a specific file.
    
    Args:
        ctx: MCP context providing access to server state.
        filepath: Path to the file to analyze.
        age: Number of minutes to look back (max 7 days).
        
    Returns:
        List of dictionaries with exception details.
    """
    logger.info(f"Getting exception details for file: {filepath}, age: {age} minutes")
    if not filepath:
        logger.error("No filepath provided")
        return [{"error": "filepath is required"}]
    
    langfuse_client, error = get_langfuse_client(ctx)
    
    if not langfuse_client:
        error_msg = f"Langfuse client not initialized: {error}"
        logger.error(error_msg)
        return [{"error": error_msg}]
    
    to_timestamp = datetime.now(UTC)
    from_timestamp = to_timestamp - timedelta(minutes=age)
    
    try:
        # Fetch all observations in a single call
        observations_response = langfuse_client.fetch_observations(
            from_start_time=from_timestamp,
            to_start_time=to_timestamp,
            type="SPAN"
        )
        
        # Get all observation IDs first
        observation_ids = [span.id for span in observations_response.data]
        
        # Batch fetch all observations
        observations = await _batch_fetch_observations(langfuse_client, observation_ids)
        
        exception_details = []
        
        # Process exceptions
        for observation in observations.values():
            # Skip if no metadata or doesn't match filepath
            if not hasattr(observation, 'metadata') or observation.metadata.get("code.filepath") != filepath:
                continue
            
            # Skip if no events
            if not hasattr(observation, 'events') or not observation.events:
                continue
            
            for event in observation.events:
                exception_type = event.attributes.get("exception.type")
                if not exception_type:
                    continue
                    
                exception_info = {
                    "observation_id": observation.id,
                    "observation_name": observation.name,
                    "timestamp": event.start_time.isoformat() if hasattr(event, 'start_time') else None,
                    "exception_type": exception_type,
                    "exception_message": event.attributes.get("exception.message"),
                    "stacktrace": event.attributes.get("exception.stacktrace"),
                    "file": filepath,
                    "function": observation.metadata.get("code.function"),
                    "line_number": observation.metadata.get("code.lineno"),
                }
                
                exception_details.append(exception_info)
        
        if not exception_details:
            logger.info(f"No exceptions found for file: {filepath}")
            return [{"message": f"No exceptions found for file: {filepath}"}]
        
        logger.info(f"Found {len(exception_details)} exceptions")
        return exception_details
    except Exception as e:
        logger.error(f"Error getting exception details: {str(e)}", exc_info=True)
        return [{"error": f"Failed to get exception details: {str(e)}"}]


async def get_session(
    ctx: Context,
    session_id: str,
) -> dict:
    """Retrieve a session by ID.
    
    Args:
        ctx: MCP context with access to Langfuse client
        session_id: ID of the session to retrieve
        
    Returns:
        Session data as a dictionary
    """
    logger.info(f"Getting session with ID: {session_id}")
    if not session_id:
        logger.error("No session_id provided")
        return {"error": "session_id is required"}
    
    langfuse_client, error = get_langfuse_client(ctx)
    
    if not langfuse_client:
        error_msg = f"Langfuse client not initialized: {error}"
        logger.error(error_msg)
        return {"error": error_msg}
    
    try:
        sessions_response = langfuse_client.fetch_sessions()
        
        # Filter sessions by id on the client side
        matching_sessions = [s for s in sessions_response.data if s.id == session_id]
        
        if not matching_sessions:
            logger.warning(f"No session found with ID: {session_id}")
            return {"error": f"Session not found: {session_id}"}
        
        session = matching_sessions[0]
        logger.info(f"Found session: {session.id}")
        
        # Convert to dict for serialization
        return session.dict()
    except Exception as e:
        logger.error(f"Error retrieving session: {str(e)}", exc_info=True)
        return {"error": f"Failed to retrieve session: {str(e)}"}


async def get_user_sessions(
    ctx: Context,
    user_id: str,
    from_timestamp: Optional[datetime] = None,
    to_timestamp: Optional[datetime] = None,
) -> List[dict]:
    """Retrieve sessions for a user within a time range.
    
    Args:
        ctx: MCP context with access to Langfuse client
        user_id: ID of the user
        from_timestamp: Start time (ISO 8601)
        to_timestamp: End time (ISO 8601)
        
    Returns:
        List of session dictionaries
    """
    logger.info(f"Getting sessions for user: {user_id}")
    if not user_id:
        logger.error("No user_id provided")
        return [{"error": "user_id is required"}]
    
    langfuse_client, error = get_langfuse_client(ctx)
    
    if not langfuse_client:
        error_msg = f"Langfuse client not initialized: {error}"
        logger.error(error_msg)
        return [{"error": error_msg}]
    
    try:
        sessions_response = langfuse_client.fetch_sessions(
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )
        
        # Get traces for the user to find associated sessions
        traces_response = langfuse_client.fetch_traces(
            user_id=user_id,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )
        
        # Extract session IDs from traces
        session_ids = {trace.session_id for trace in traces_response.data if trace.session_id}
        logger.info(f"Found {len(session_ids)} unique session IDs for user {user_id}")
        
        # Filter sessions to only include those associated with the user's traces
        user_sessions = [session for session in sessions_response.data if session.id in session_ids]
        
        logger.info(f"Returning {len(user_sessions)} sessions for user {user_id}")
        # Include userId in each session
        return [{"userId": user_id, **session.dict()} for session in user_sessions]
    except Exception as e:
        logger.error(f"Error retrieving user sessions: {str(e)}", exc_info=True)
        return [{"error": f"Failed to retrieve user sessions: {str(e)}"}]


async def get_error_count(
    ctx: Context,
    age: ValidatedAge,
) -> dict:
    """Get the number of traces with exceptions within the last N minutes.
    
    Args:
        ctx: MCP context with access to Langfuse client
        age: Number of minutes to look back
        
    Returns:
        Dictionary with error count
    """
    logger.info(f"Getting error count for the past {age} minutes")
    
    langfuse_client, error = get_langfuse_client(ctx)
    
    if not langfuse_client:
        error_msg = f"Langfuse client not initialized: {error}"
        logger.error(error_msg)
        return {"error": error_msg}

    try:
        to_timestamp = datetime.now(UTC)
        from_timestamp = to_timestamp - timedelta(minutes=age)
        logger.debug(f"Time range: {from_timestamp} to {to_timestamp}")

        observations_response = langfuse_client.fetch_observations(
            from_start_time=from_timestamp,
            to_start_time=to_timestamp,
            type="SPAN",
        )
        logger.info(f"Retrieved {len(observations_response.data)} spans from Langfuse")

        # Count spans with errors
        error_count = sum(1 for obs in observations_response.data if obs.level == "ERROR")
        logger.info(f"Found {error_count} errors")

        return {
            "count": error_count,
            "time_range": {
                "from": from_timestamp.isoformat(),
                "to": to_timestamp.isoformat()
            }
        }
    except Exception as e:
        logger.error(f"Error getting error count: {str(e)}", exc_info=True)
        return {"error": f"Failed to get error count: {str(e)}"}


async def get_data_schema(ctx: Context) -> str:
    """Get the schema of trace, span, and event objects.
    
    Args:
        ctx: MCP context (no Langfuse client needed for this)
        
    Returns:
        String with JSON schema description
    """
    logger.info("Getting Langfuse data schema")
    
    # This is a static description of the schema, no API call needed
    schema = """
    {
        "Trace": {
            "id": "string - unique trace identifier",
            "name": "string - name of the trace",
            "user_id": "string? - associated user",
            "session_id": "string? - associated session",
            "metadata": "Record<string, any>? - custom metadata",
            "tags": "string[]? - tags for filtering",
            "start_time": "ISO timestamp - when trace started",
            "end_time": "ISO timestamp? - when trace completed",
            "duration_ms": "number - execution time in milliseconds",
            "observations": "Observation[] - spans and scores"
        },
        "Span": {
            "id": "string - unique span identifier",
            "trace_id": "string - parent trace",
            "name": "string - name of the span",
            "start_time": "ISO timestamp - when span started",
            "end_time": "ISO timestamp? - when span completed",
            "status": "SUCCESS | ERROR | INTERNAL_ERROR - execution status",
            "metadata": "Record<string, any>? - custom metadata",
            "input": "any? - input data",
            "output": "any? - output data",
            "level": "DEFAULT | DEBUG - visibility level",
            "events": "Event[]? - timestamped events"
        },
        "Event": {
            "id": "string - unique event identifier",
            "timestamp": "ISO timestamp - when event occurred",
            "attributes": "Record<string, any> - event data",
            "type": "string - event type"
        },
        "Exception (in Event.attributes)": {
            "exception.type": "string - exception class name",
            "exception.message": "string - error message",
            "exception.stacktrace": "string - full stack trace",
            "code.filepath": "string? - source file",
            "code.function": "string? - function name",
            "code.lineno": "number? - line number"
        }
    }
    """
    
    return schema


async def get_exception_details(
    ctx: Context,
    trace_id: str,
    span_id: Optional[str] = None,
) -> List[dict]:
    """Get detailed exception information for a trace or span.
    
    Args:
        ctx: MCP context providing access to server state.
        trace_id: ID of the trace to analyze.
        span_id: Optional ID of the span (if specified, get exceptions for that span only).
        
    Returns:
        List of dictionaries with exception details.
    """
    logger.info(f"Getting exception details for trace {trace_id}" + 
                (f", span {span_id}" if span_id else ""))
    
    langfuse_client, error = get_langfuse_client(ctx)
    
    if not langfuse_client:
        error_msg = f"Langfuse client not initialized: {error}"
        logger.error(error_msg)
        return [{"error": error_msg}]
        
    try:
        if span_id:
            # If span_id is provided, get that specific observation
            observation = langfuse_client.fetch_observation(span_id)
            if observation.trace_id != trace_id:
                return [{"error": "Span does not belong to the specified trace"}]
            spans = [observation]
        else:
            # Otherwise, get all observations for the trace
            traces = langfuse_client.fetch_traces(trace_id=trace_id).data
            if not traces:
                return [{"error": f"Trace {trace_id} not found"}]
            
            observations = traces[0].observations
            # Get detailed observation data for each observation in the trace
            spans = []
            for obs in observations:
                try:
                    detailed_obs = langfuse_client.fetch_observation(obs.id)
                    spans.append(detailed_obs)
                except Exception as e:
                    logger.warning(f"Error getting observation {obs.id}: {str(e)}")
                    
        # Extract exception details from spans
        details = []
        for span in spans:
            if hasattr(span, 'events'):
                for event in span.events or []:
                    if event.attributes.get("exception.type"):
                        details.append({
                            "observation_id": span.id,
                            "exception_type": event.attributes.get("exception.type"),
                            "exception_message": event.attributes.get("exception.message"),
                            "stacktrace": event.attributes.get("exception.stacktrace"),
                            "timestamp": event.start_time.isoformat() if hasattr(event, 'start_time') else None,
                            "metadata": span.metadata if hasattr(span, 'metadata') else None,
                        })
                        
        return details if details else [{"message": "No exceptions found in the specified trace"}]
    except Exception as e:
        logger.error(f"Error getting exception details: {str(e)}", exc_info=True)
        return [{"error": f"Failed to get exception details: {str(e)}"}]


async def get_trace(
    ctx: Context,
    trace_id: str,
) -> dict:
    """Get a single trace by ID with full details.
    
    Args:
        ctx: MCP context with access to Langfuse client
        trace_id: ID of the trace to retrieve
        
    Returns:
        Trace object with full details as a dictionary
    """
    logger.info(f"Getting trace with ID: {trace_id}")
    if not trace_id:
        logger.error("No trace_id provided")
        return {"error": "trace_id is required"}
    
    langfuse_client, error = get_langfuse_client(ctx)
    
    if not langfuse_client:
        error_msg = f"Langfuse client not initialized: {error}"
        logger.error(error_msg)
        return {"error": error_msg}
    
    try:
        trace_response = langfuse_client.fetch_trace(trace_id)
        logger.info(f"Found trace: {trace_id}")
        return trace_response.data.dict()
    except Exception as e:
        logger.error(f"Error retrieving trace: {str(e)}", exc_info=True)
        return {"error": f"Failed to retrieve trace: {str(e)}"}


async def get_observation(
    ctx: Context,
    observation_id: str,
) -> dict:
    """Get a single observation by ID.
    
    Args:
        ctx: MCP context with access to Langfuse client
        observation_id: ID of the observation to retrieve
        
    Returns:
        Observation object as a dictionary
    """
    logger.info(f"Getting observation with ID: {observation_id}")
    if not observation_id:
        logger.error("No observation_id provided")
        return {"error": "observation_id is required"}
    
    langfuse_client, error = get_langfuse_client(ctx)
    
    if not langfuse_client:
        error_msg = f"Langfuse client not initialized: {error}"
        logger.error(error_msg)
        return {"error": error_msg}
    
    try:
        observation = langfuse_client.fetch_observation(observation_id)
        logger.info(f"Found observation: {observation_id}")
        if hasattr(observation, 'dict'):
            return observation.dict()
        else:
            # Convert to dict manually if dict() method is not available
            return {
                "id": observation.id,
                "trace_id": observation.trace_id if hasattr(observation, 'trace_id') else None,
                "name": observation.name if hasattr(observation, 'name') else None,
                "start_time": observation.start_time.isoformat() if hasattr(observation, 'start_time') else None,
                "end_time": observation.end_time.isoformat() if hasattr(observation, 'end_time') else None,
                "metadata": observation.metadata if hasattr(observation, 'metadata') else None,
                "type": observation.type if hasattr(observation, 'type') else None
            }
    except Exception as e:
        logger.error(f"Error retrieving observation: {str(e)}", exc_info=True)
        return {"error": f"Failed to retrieve observation: {str(e)}"}


async def get_observations_by_type(
    ctx: Context,
    type: str,
    name: Optional[str] = None,
    user_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    parent_observation_id: Optional[str] = None,
    from_start_time: Optional[datetime] = None,
    to_start_time: Optional[datetime] = None,
    page: int = 1,
    limit: int = 50,
) -> List[dict]:
    """Get observations filtered by type.
    
    Args:
        ctx: MCP context with access to Langfuse client
        type: Filter by observation type (e.g., 'SPAN', 'GENERATION', 'SCORE')
        name: Filter by observation name
        user_id: Filter by user ID
        trace_id: Filter by trace ID
        parent_observation_id: Filter by parent observation ID
        from_start_time: Start time range (ISO 8601)
        to_start_time: End time range (ISO 8601)
        page: Page number for pagination
        limit: Items per page
        
    Returns:
        List of observation dictionaries
    """
    logger.info(f"Getting observations of type: {type}")
    
    langfuse_client, error = get_langfuse_client(ctx)
    
    if not langfuse_client:
        error_msg = f"Langfuse client not initialized: {error}"
        logger.error(error_msg)
        return [{"error": error_msg}]
    
    try:
        observations_response = langfuse_client.fetch_observations(
            type=type,
            name=name,
            user_id=user_id,
            trace_id=trace_id,
            parent_observation_id=parent_observation_id,
            from_start_time=from_start_time,
            to_start_time=to_start_time,
            page=page,
            limit=limit,
        )
        
        logger.info(f"Found {len(observations_response.data)} observations of type {type}")
        
        # Convert observations to dictionaries
        observations = []
        for obs in observations_response.data:
            if hasattr(obs, 'dict'):
                observations.append(obs.dict())
            else:
                # Convert to dict manually if dict() method is not available
                observations.append({
                    "id": obs.id if hasattr(obs, 'id') else None,
                    "trace_id": obs.trace_id if hasattr(obs, 'trace_id') else None,
                    "name": obs.name if hasattr(obs, 'name') else None,
                    "start_time": obs.start_time.isoformat() if hasattr(obs, 'start_time') else None,
                    "end_time": obs.end_time.isoformat() if hasattr(obs, 'end_time') else None,
                    "type": obs.type if hasattr(obs, 'type') else None,
                })
        
        return observations
    except Exception as e:
        logger.error(f"Error retrieving observations: {str(e)}", exc_info=True)
        return [{"error": f"Failed to retrieve observations: {str(e)}"}]


def app_factory(public_key: str, secret_key: str, host: str, no_auth_check: bool = False) -> FastMCP:
    """Create a FastMCP server with Langfuse tools.
    
    Args:
        public_key: Langfuse public key
        secret_key: Langfuse secret key
        host: Langfuse API host URL
        no_auth_check: Skip authentication check
        
    Returns:
        FastMCP server instance
    """
    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[MCPState]:
        logger.info(f"Initializing Langfuse client with host: {host}")
        logger.info(f"Python version: {sys.version}")
        logger.info(f"Langfuse client version: {getattr(Langfuse, '__version__', 'unknown')}")
        
        try:
            if not public_key or not secret_key:
                raise ValueError("Both public_key and secret_key must be provided")
                
            logger.info("Creating Langfuse client...")
            langfuse_client = Langfuse(
                public_key=public_key, 
                secret_key=secret_key,
                host=host,
                debug=True
            )
            
            if not no_auth_check:
                logger.info("Checking authentication with Langfuse...")
                try:
                    auth_result = langfuse_client.auth_check()
                    if not auth_result:
                        raise ValueError("Authentication failed with the provided credentials")
                    logger.info("Authentication successful")
                except Exception as auth_error:
                    detailed_error = f"Authentication failed: {str(auth_error)}"
                    logger.error(detailed_error)
                    if "404" in str(auth_error).lower():
                        detailed_error += f" - Check if host URL {host} is correct"
                    elif "unauthorized" in str(auth_error).lower():
                        detailed_error += " - Check if API keys are valid"
                    raise ValueError(detailed_error)
            
            logger.info("Langfuse client initialized successfully")
            
            state = MCPState(langfuse_client=langfuse_client)
            yield state
            
            logger.info("Shutting down Langfuse client...")
            langfuse_client.flush()
            langfuse_client.shutdown()
            logger.info("Langfuse client shutdown complete")
        except Exception as e:
            error_msg = f"Failed to initialize Langfuse client: {str(e)}"
            logger.error(error_msg, exc_info=True)
            yield MCPState(langfuse_client=None, error=error_msg)

    mcp = FastMCP("Langfuse MCP Server", lifespan=lifespan)
    
    # Register resource for API schema documentation
    @mcp.resource("langfuse://api-schema")
    def api_schema() -> str:
        """Schema documentation for Langfuse MCP API endpoints."""
        schema = {
            "traces": {
                "find_traces": {
                    "description": "Search for traces with filtering options",
                    "parameters": {
                        "name": "Filter by trace name",
                        "user_id": "Filter by user ID",
                        "session_id": "Filter by session ID",
                        "metadata": "Filter by metadata key-value pairs",
                        "from_timestamp": "Start time range (ISO 8601)",
                        "to_timestamp": "End time range (ISO 8601)",
                        "page": "Page number for pagination",
                        "limit": "Items per page",
                        "order_by": "Field to order results by",
                        "tags": "Filter by tags (string or list of strings)"
                    },
                    "returns": "List of trace objects"
                },
                "get_trace": {
                    "description": "Get a single trace by ID with full details",
                    "parameters": {
                        "trace_id": "ID of the trace to retrieve"
                    },
                    "returns": "Single trace object with complete details"
                }
            },
            "observations": {
                "get_observation": {
                    "description": "Get a single observation by ID",
                    "parameters": {
                        "observation_id": "ID of the observation to retrieve"
                    },
                    "returns": "Single observation object"
                },
                "get_observations_by_type": {
                    "description": "Get observations filtered by type",
                    "parameters": {
                        "type": "Filter by observation type (e.g., 'SPAN', 'GENERATION', 'SCORE')",
                        "name": "Filter by observation name",
                        "user_id": "Filter by user ID",
                        "trace_id": "Filter by trace ID",
                        "parent_observation_id": "Filter by parent observation ID",
                        "from_start_time": "Start time range (ISO 8601)",
                        "to_start_time": "End time range (ISO 8601)",
                        "page": "Page number for pagination",
                        "limit": "Items per page"
                    },
                    "returns": "List of observation objects"
                }
            },
            "sessions": {
                "get_session": {
                    "description": "Retrieve a session by ID",
                    "parameters": {
                        "session_id": "ID of the session to retrieve"
                    },
                    "returns": "Session object"
                },
                "get_user_sessions": {
                    "description": "Retrieve sessions for a user within a time range",
                    "parameters": {
                        "user_id": "ID of the user",
                        "from_timestamp": "Start time (ISO 8601)",
                        "to_timestamp": "End time (ISO 8601)"
                    },
                    "returns": "List of session objects"
                }
            },
            "errors": {
                "find_exceptions": {
                    "description": "Get exception counts grouped by file path, function, or type",
                    "parameters": {
                        "age": "Number of minutes to look back (max 7 days)",
                        "group_by": "Field to group by (file, function, or type)"
                    },
                    "returns": "List of exception counts"
                },
                "find_exceptions_in_file": {
                    "description": "Get detailed info about exceptions in a specific file",
                    "parameters": {
                        "filepath": "Path to the file to analyze",
                        "age": "Number of minutes to look back (max 7 days)"
                    },
                    "returns": "List of exception details"
                },
                "get_error_count": {
                    "description": "Get the number of traces with exceptions within the last N minutes",
                    "parameters": {
                        "age": "Number of minutes to look back"
                    },
                    "returns": "Error count with time range"
                },
                "get_exception_details": {
                    "description": "Get detailed exception information for a trace or span",
                    "parameters": {
                        "trace_id": "ID of the trace to analyze",
                        "span_id": "Optional ID of the span"
                    },
                    "returns": "List of exception details"
                }
            },
            "schema": {
                "get_data_schema": {
                    "description": "Get the schema of trace, span, and event objects",
                    "parameters": {},
                    "returns": "JSON schema description"
                }
            }
        }
        
        return json.dumps(schema, indent=2)
    
    # Register all tools
    mcp.tool()(find_traces)
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
    
    args = parser.parse_args()
    
    app = app_factory(
        public_key=args.public_key,
        secret_key=args.secret_key,
        host=args.host,
        no_auth_check=args.no_auth_check
    )
    
    app.run(transport="stdio")


if __name__ == "__main__":
    main() 