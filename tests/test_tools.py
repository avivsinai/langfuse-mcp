"""Unit tests for langfuse-mcp tool functions."""

from __future__ import annotations

import asyncio
import json

import pytest

from tests.fakes import FakeContext, FakeLangfuse


@pytest.fixture()
def state(tmp_path):
    """Return an MCPState instance using the fake client."""
    from langfuse_mcp.__main__ import MCPState

    return MCPState(langfuse_client=FakeLangfuse(), dump_dir=str(tmp_path))


def test_fetch_traces_with_observations(state):
    """fetch_traces should use the v3 traces resource and embed observations."""
    from langfuse_mcp.__main__ import fetch_traces

    ctx = FakeContext(state)
    result = asyncio.run(
        fetch_traces(
            ctx,
            age=10,
            name=None,
            user_id=None,
            session_id=None,
            metadata=None,
            page=1,
            limit=50,
            tags=None,
            include_observations=True,
            output_mode="compact",
        )
    )
    assert result["metadata"]["item_count"] == 1
    assert result["data"][0]["id"] == "trace_1"
    assert isinstance(result["data"][0]["observations"], list)
    assert result["data"][0]["observations"][0]["id"] == "obs_1"
    assert state.langfuse_client.api.trace.last_list_kwargs is not None
    trace_kwargs = state.langfuse_client.api.trace.last_list_kwargs
    assert trace_kwargs["limit"] == 50
    assert "observations" in (trace_kwargs.get("fields") or "")


def test_fetch_trace(state):
    """fetch_trace should pull from the v3 traces resource."""
    from langfuse_mcp.__main__ import fetch_trace

    ctx = FakeContext(state)
    result = asyncio.run(fetch_trace(ctx, trace_id="trace_1", include_observations=True, output_mode="compact"))
    assert result["data"]["id"] == "trace_1"
    assert result["data"]["observations"][0]["id"] == "obs_1"
    assert state.langfuse_client.api.trace.last_get_kwargs == {"trace_id": "trace_1"}


def test_fetch_observations(state):
    """fetch_observations should call the v3 observations resource."""
    from langfuse_mcp.__main__ import fetch_observations

    ctx = FakeContext(state)
    result = asyncio.run(
        fetch_observations(
            ctx,
            type=None,
            age=10,
            name=None,
            user_id=None,
            trace_id=None,
            parent_observation_id=None,
            page=1,
            limit=50,
            output_mode="compact",
        )
    )
    assert result["metadata"]["item_count"] == 1
    assert result["data"][0]["id"] == "obs_1"
    assert state.langfuse_client.api.observations.last_get_many_kwargs is not None
    obs_kwargs = state.langfuse_client.api.observations.last_get_many_kwargs
    assert obs_kwargs["limit"] == 50


def test_fetch_observation(state):
    """fetch_observation should hit the observations resource."""
    from langfuse_mcp.__main__ import fetch_observation

    ctx = FakeContext(state)
    result = asyncio.run(fetch_observation(ctx, observation_id="obs_1", output_mode="compact"))
    assert result["data"]["id"] == "obs_1"
    assert state.langfuse_client.api.observations.last_get_kwargs == {"observation_id": "obs_1"}


def test_fetch_sessions(state):
    """fetch_sessions should rely on the v3 sessions resource."""
    from langfuse_mcp.__main__ import fetch_sessions

    ctx = FakeContext(state)
    result = asyncio.run(fetch_sessions(ctx, age=10, page=1, limit=50, output_mode="compact"))
    assert result["metadata"]["item_count"] == 1
    assert result["data"][0]["id"] == "session_1"
    assert state.langfuse_client.api.sessions.last_list_kwargs is not None
    sessions_kwargs = state.langfuse_client.api.sessions.last_list_kwargs
    assert sessions_kwargs["limit"] == 50


def test_get_session_details(state):
    """get_session_details should reuse the v3 traces resource."""
    from langfuse_mcp.__main__ import get_session_details

    ctx = FakeContext(state)
    result = asyncio.run(get_session_details(ctx, session_id="session_1", include_observations=True, output_mode="compact"))
    assert result["data"]["found"] is True
    assert result["data"]["trace_count"] == 1
    assert state.langfuse_client.api.trace.last_list_kwargs is not None
    trace_kwargs = state.langfuse_client.api.trace.last_list_kwargs
    assert trace_kwargs["session_id"] == "session_1"
    # Regression: Langfuse ClickHouse rejects epoch-zero DateTime64 filters.
    assert "from_timestamp" not in trace_kwargs


def test_get_exception_details_omits_time_filters(state):
    """get_exception_details should not include epoch-zero time filters in observation lookups."""
    from langfuse_mcp.__main__ import get_exception_details

    ctx = FakeContext(state)
    result = asyncio.run(get_exception_details(ctx, trace_id="trace_1", span_id=None, output_mode="compact"))
    assert isinstance(result["data"], list)
    assert result["metadata"]["item_count"] == len(result["data"])

    assert state.langfuse_client.api.observations.last_get_many_kwargs is not None
    obs_kwargs = state.langfuse_client.api.observations.last_get_many_kwargs
    assert obs_kwargs["trace_id"] == "trace_1"
    assert "from_start_time" not in obs_kwargs
    assert "to_start_time" not in obs_kwargs


def test_fetch_traces_full_json_string(state):
    """fetch_traces should honor explicit output mode strings."""
    from langfuse_mcp.__main__ import fetch_traces

    ctx = FakeContext(state)
    result = asyncio.run(
        fetch_traces(
            ctx,
            age=10,
            name=None,
            user_id=None,
            session_id=None,
            metadata=None,
            page=1,
            limit=50,
            tags=None,
            include_observations=False,
            output_mode="full_json_string",
        )
    )
    assert isinstance(result, str)
    loaded = json.loads(result)
    assert isinstance(loaded, list)


def test_find_exceptions_returns_envelope(state):
    """find_exceptions should return the standard response envelope."""
    from langfuse_mcp.__main__ import find_exceptions

    ctx = FakeContext(state)
    result = asyncio.run(find_exceptions(ctx, age=60, group_by="file"))
    assert set(result.keys()) == {"data", "metadata"}
    assert isinstance(result["data"], list)
    assert result["metadata"].get("item_count") == len(result["data"])


def test_get_user_sessions_returns_envelope(state):
    """get_user_sessions should always return an envelope structure."""
    from langfuse_mcp.__main__ import get_user_sessions

    ctx = FakeContext(state)
    result = asyncio.run(get_user_sessions(ctx, user_id="user_1", age=60, include_observations=False, output_mode="compact"))
    assert set(result.keys()) == {"data", "metadata"}
    assert isinstance(result["data"], list)


def test_negative_age_rejected(state):
    """All age parameters should be validated."""
    from langfuse_mcp.__main__ import fetch_traces

    ctx = FakeContext(state)
    with pytest.raises(ValueError):
        asyncio.run(
            fetch_traces(
                ctx,
                age=-5,
                name=None,
                user_id=None,
                session_id=None,
                metadata=None,
                page=1,
                limit=10,
                tags=None,
                include_observations=False,
                output_mode="compact",
            )
        )


def test_truncate_large_strings_case_insensitive():
    """Large field detection should be case-insensitive."""
    from langfuse_mcp.__main__ import MAX_FIELD_LENGTH, truncate_large_strings

    payload = {"Metadata.langfusePrompt": "x" * (MAX_FIELD_LENGTH + 50)}
    truncated, _ = truncate_large_strings(payload)
    value = truncated["Metadata.langfusePrompt"]
    assert isinstance(value, str)
    assert value.endswith("...")
    assert len(value) <= MAX_FIELD_LENGTH + len("...")
