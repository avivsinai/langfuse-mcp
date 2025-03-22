import asyncio
import json
import os
import pytest
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from langfuse import Langfuse

# Configure pytest-asyncio to use function scope for async fixtures
pytest.asyncio_fixture_scope = "function"

from langfuse_mcp.__main__ import (
    find_traces, 
    find_exceptions,
    find_exceptions_in_file,
    get_session,
    get_user_sessions,
    get_error_count,
    get_data_schema,
    get_exception_details,
    get_trace,
    get_observation,
    get_observations_by_type,
    MCPState,
    Context
)

# Load environment variables from .env file
load_dotenv()

# Sample data from JSON dumps for comparison
with open('data/1742387601717-lf-traces-export-cm8d93twc00s0ad07krwaek64.json', 'r') as f:
    SAMPLE_TRACES_1 = json.load(f)

with open('data/1742393128173-lf-traces-export-cm8d93twc00s0ad07krwaek64.json', 'r') as f:
    SAMPLE_TRACES_2 = json.load(f)

with open('data/1742673386131-lf-traces-export-cm8d93twc00s0ad07krwaek64.json', 'r') as f:
    SAMPLE_TRACES_3 = json.load(f)

# Create a combined dataset for testing
ALL_SAMPLE_TRACES = SAMPLE_TRACES_1 + SAMPLE_TRACES_2 + SAMPLE_TRACES_3

# Extract unique trace IDs, session IDs, and user IDs for testing
TRACE_IDS = list(set(trace.get('id') for trace in ALL_SAMPLE_TRACES if 'id' in trace))
SESSION_IDS = list(set(trace.get('sessionId') for trace in ALL_SAMPLE_TRACES if trace.get('sessionId')))
USER_IDS = list(set(trace.get('userId') for trace in ALL_SAMPLE_TRACES if trace.get('userId')))

# Extract observations from traces
OBSERVATIONS = []
for trace in ALL_SAMPLE_TRACES:
    if 'observations' in trace:
        OBSERVATIONS.extend(trace['observations'])

OBSERVATION_IDS = list(set(obs.get('id') for obs in OBSERVATIONS if 'id' in obs))
OBSERVATION_TYPES = list(set(obs.get('type') for obs in OBSERVATIONS if 'type' in obs))

# Get a mapping of trace_id -> trace for easy lookup
TRACE_MAP = {trace.get('id'): trace for trace in ALL_SAMPLE_TRACES if 'id' in trace}

# Setup fixtures
@pytest.fixture
def langfuse_client() -> Langfuse:
    """Create a Langfuse client using environment variables."""
    return Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    )

@pytest.fixture
def mcp_context(langfuse_client) -> Context:
    """Create a Context object with the Langfuse client."""
    from mcp.server.fastmcp.server import RequestContext
    state = MCPState(langfuse_client=langfuse_client)
    ctx = Context(state=state)
    # Set up request context with lifespan context
    ctx._request_context = RequestContext(
        request_id="test",
        meta=None,
        session=None,
        lifespan_context=state
    )
    return ctx

# Helper function to compare API results with our sample data
def match_with_sample_data(api_results: List[Dict[str, Any]], sample_field: str, match_field: str) -> bool:
    """Check if API results match with our sample data."""
    if not api_results:
        return False
    
    for result in api_results:
        result_id = result.get(match_field)
        if not result_id:
            continue
        
        # Look for this ID in our sample data
        for trace in ALL_SAMPLE_TRACES:
            if trace.get(sample_field) == result_id:
                return True
    
    return False

# Tests for each function
@pytest.mark.asyncio
async def test_find_traces(mcp_context):
    """Test find_traces function with various parameters."""
    # Get traces from the last 30 days to ensure we capture our sample data
    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)
    
    # Test with default parameters
    results = await find_traces(
        mcp_context,
        from_timestamp=thirty_days_ago,
        to_timestamp=now,
        limit=100
    )
    
    assert results, "Should return some traces"
    assert match_with_sample_data(results, 'id', 'id'), "Results should contain traces from our sample data"
    
    # Test with specific user_id
    if USER_IDS:
        user_results = await find_traces(
            mcp_context,
            user_id=USER_IDS[0],
            from_timestamp=thirty_days_ago,
            to_timestamp=now
        )
        assert any(r.get('userId') == USER_IDS[0] for r in user_results), "Results should contain traces for the specified user"
    
    # Test with specific session_id
    if SESSION_IDS:
        session_results = await find_traces(
            mcp_context,
            session_id=SESSION_IDS[0],
            from_timestamp=thirty_days_ago,
            to_timestamp=now
        )
        assert any(r.get('sessionId') == SESSION_IDS[0] for r in session_results), "Results should contain traces for the specified session"

@pytest.mark.asyncio
async def test_find_exceptions(mcp_context):
    """Test find_exceptions function."""
    # Test with different group_by options
    for group_by in ["file", "function", "type"]:
        results = await find_exceptions(mcp_context, age=30*24*60, group_by=group_by)  # 30 days in minutes
        # We can't easily verify the exact content since exceptions are dynamic,
        # but we can check the structure
        if results:
            for item in results:
                assert hasattr(item, "group"), f"Each result should have a 'group' when grouped by {group_by}"
                assert hasattr(item, "count"), f"Each result should have a 'count' when grouped by {group_by}"

@pytest.mark.asyncio
async def test_find_exceptions_in_file(mcp_context):
    """Test find_exceptions_in_file function."""
    # Since we don't know which files have exceptions, we'll try a generic approach
    # First get the exceptions grouped by file
    grouped_exceptions = await find_exceptions(mcp_context, age=30*24*60, group_by="file")
    
    if grouped_exceptions:
        # Take the first file that has exceptions
        file = grouped_exceptions[0].group
        
        # Now find exceptions in that specific file
        results = await find_exceptions_in_file(mcp_context, filepath=file, age=30*24*60)
        
        assert results, f"Should find exceptions in file {file}"
        for exception in results:
            assert "trace_id" in exception or "error" in exception or "message" in exception, "Each exception should have a trace_id or error message"
            if "error" not in exception and "message" not in exception:
                assert "message" in exception, "Each exception should have a message"
                assert "timestamp" in exception, "Each exception should have a timestamp"

@pytest.mark.asyncio
async def test_get_session(mcp_context):
    """Test get_session function."""
    if SESSION_IDS:
        session_id = SESSION_IDS[0]
        result = await get_session(mcp_context, session_id=session_id)
        
        assert result, f"Should retrieve session with id {session_id}"
        assert result.get("id") == session_id, "Retrieved session should have the correct ID"

@pytest.mark.asyncio
async def test_get_user_sessions(mcp_context):
    """Test get_user_sessions function."""
    if USER_IDS:
        user_id = USER_IDS[0]
        now = datetime.now(timezone.utc)
        thirty_days_ago = now - timedelta(days=30)
        
        results = await get_user_sessions(
            mcp_context,
            user_id=user_id,
            from_timestamp=thirty_days_ago,
            to_timestamp=now
        )
        
        if results:
            for session in results:
                assert "id" in session, "Each session should have an id"
                assert session.get("userId") == user_id, "Sessions should belong to the requested user"

@pytest.mark.asyncio
async def test_get_error_count(mcp_context):
    """Test get_error_count function."""
    result = await get_error_count(mcp_context, age=30*24*60)  # 30 days in minutes
    
    assert isinstance(result, dict), "Result should be a dictionary"
    assert "count" in result, "Result should contain a count"
    assert isinstance(result["count"], int), "Count should be an integer"

@pytest.mark.asyncio
async def test_get_data_schema(mcp_context):
    """Test get_data_schema function."""
    result = await get_data_schema(mcp_context)
    
    assert result, "Should return the data schema"
    assert isinstance(result, str), "Schema should be a string"
    # Try parsing it as JSON to ensure it's valid
    schema_json = json.loads(result)
    assert isinstance(schema_json, dict), "Schema should be valid JSON"

@pytest.mark.asyncio
async def test_get_exception_details(mcp_context):
    """Test get_exception_details function."""
    # First find traces with exceptions
    grouped_exceptions = await find_exceptions(mcp_context, age=30*24*60, group_by="file")
    
    if grouped_exceptions and len(grouped_exceptions) > 0:
        # Get exceptions for a specific file
        file = grouped_exceptions[0].group
        exceptions = await find_exceptions_in_file(mcp_context, filepath=file, age=30*24*60)
        
        if exceptions and len(exceptions) > 0:
            # Get details for the first exception
            trace_id = exceptions[0].get("trace_id")
            span_id = exceptions[0].get("span_id")
            
            if trace_id and span_id:
                results = await get_exception_details(mcp_context, trace_id=trace_id, span_id=span_id)
                
                assert results, f"Should return exception details for trace {trace_id}"
                for detail in results:
                    if "error" not in detail:
                        assert "message" in detail, "Each detail should have a message"
                        assert "timestamp" in detail, "Each detail should have a timestamp"

@pytest.mark.asyncio
async def test_get_trace(mcp_context):
    """Test get_trace function."""
    if TRACE_IDS:
        trace_id = TRACE_IDS[0]
        result = await get_trace(mcp_context, trace_id=trace_id)
        
        assert result, f"Should retrieve trace with id {trace_id}"
        assert result.get("id") == trace_id, "Retrieved trace should have the correct ID"
        
        # Compare with our sample data
        sample_trace = TRACE_MAP.get(trace_id)
        if sample_trace:
            assert result.get("name") == sample_trace.get("name"), "Trace name should match sample data"
            assert result.get("userId") == sample_trace.get("userId"), "Trace userId should match sample data"

@pytest.mark.asyncio
async def test_get_observation(mcp_context):
    """Test get_observation function."""
    if OBSERVATION_IDS:
        observation_id = OBSERVATION_IDS[0]
        result = await get_observation(mcp_context, observation_id=observation_id)
        
        assert result, f"Should retrieve observation with id {observation_id}"
        assert result.get("id") == observation_id, "Retrieved observation should have the correct ID"

@pytest.mark.asyncio
async def test_get_observations_by_type(mcp_context):
    """Test get_observations_by_type function."""
    if OBSERVATION_TYPES:
        observation_type = OBSERVATION_TYPES[0]
        now = datetime.now(timezone.utc)
        thirty_days_ago = now - timedelta(days=30)
        
        results = await get_observations_by_type(
            mcp_context,
            type=observation_type,
            from_start_time=thirty_days_ago,
            to_start_time=now,
            limit=100
        )
        
        assert results, f"Should retrieve observations of type {observation_type}"
        for observation in results:
            assert observation.get("type") == observation_type, "Retrieved observations should have the correct type"

if __name__ == "__main__":
    # For manual testing
    asyncio.run(pytest.main(["-xvs", __file__])) 