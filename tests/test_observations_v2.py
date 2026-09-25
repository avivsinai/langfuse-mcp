"""Trace, session and observation reads over Observations API v2 (GET /api/public/v2/observations).

Langfuse Cloud removes GET /traces, /traces/{id}, /sessions and the v1 /observations routes on
2026-11-16. These tests pin the v2 routing on the v4 fake (which mirrors the real endpoint), the
404/405 fallback for servers without v2, and that the tools keep their legacy output shape.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from tests.fakes import FakeContext, FakeLangfuse, FakeLangfuseV4, FakeObservation, FakeTrace, _ObservationsV4API, _v2_condition_matches

T0 = datetime.now(timezone.utc) - timedelta(minutes=10)


@pytest.fixture()
def v4_state(tmp_path):
    """Return an MCPState backed by the v4 fake client."""
    from langfuse_mcp.__main__ import MCPState

    return MCPState(langfuse_client=FakeLangfuseV4(), dump_dir=str(tmp_path))


def _add_trace(client: Any, trace_id: str, *, minutes: int, session_id: str | None = "s_a", tags: list[str] | None = None) -> None:
    """Add a trace with a root span and one child generation, ``minutes`` after T0."""
    start = T0 + timedelta(minutes=minutes)
    root_id, child_id = f"{trace_id}_root", f"{trace_id}_gen"
    client._store.observations[root_id] = FakeObservation(
        id=root_id,
        type="AGENT",
        name="agent",
        status="SUCCEEDED",
        start_time=start,
        end_time=start + timedelta(seconds=3),
        trace_id=trace_id,
        metadata={"route": "support"},
        input={"question": "where is my order?"},
        output="It ships tomorrow.",
        total_cost=0.25,
    )
    client._store.observations[child_id] = FakeObservation(
        id=child_id,
        type="GENERATION",
        name="llm",
        status="SUCCEEDED",
        start_time=start + timedelta(seconds=1),
        end_time=start + timedelta(seconds=2),
        trace_id=trace_id,
        parent_observation_id=root_id,
        total_cost=0.5,
    )
    client._store.traces[trace_id] = FakeTrace(
        id=trace_id,
        name="support-turn",
        user_id="user_a",
        session_id=session_id,
        created_at=start,
        tags=tags or ["prod"],
        observations=[root_id, child_id],
    )


def _filters(call: dict[str, Any]) -> list[dict[str, Any]]:
    return json.loads(call["filter"])


def _fetch_traces(state: Any, **overrides: Any) -> Any:
    from langfuse_mcp.__main__ import fetch_traces

    kwargs: dict[str, Any] = {
        "age": 60,
        "name": None,
        "user_id": None,
        "session_id": None,
        "metadata": None,
        "page": 1,
        "limit": 50,
        "tags": None,
        "include_observations": False,
        "output_mode": "compact",
    }
    kwargs.update(overrides)
    return asyncio.run(fetch_traces(FakeContext(state), **kwargs))


@pytest.mark.parametrize(
    ("operator", "expected"),
    [("<", True), ("<=", True), (">", False), (">=", False)],
)
def test_v2_datetime_filter_compares_start_time(operator: str, expected: bool):
    """The fake applies all four ordered datetime operators."""
    row = {"startTime": T0.isoformat()}
    condition = {"type": "datetime", "column": "startTime", "operator": operator, "value": (T0 + timedelta(seconds=1)).isoformat()}

    assert _v2_condition_matches(row, condition) is expected


class _Status(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def test_fetch_traces_lists_root_observations_with_every_condition_in_the_filter(v4_state):
    """Trace name and tags only exist as filter columns, and ``filter`` overrides query params server-side."""
    client = v4_state.langfuse_client
    _add_trace(client, "t_1", minutes=1, tags=["prod", "eu"])

    result = _fetch_traces(v4_state, name="support-turn", user_id="user_a", session_id="s_a", tags="prod,eu")

    call = client.api.observations.calls[-1]
    assert not {"user_id", "session_id", "name", "trace_id", "is_root_observation"} & call.keys()
    columns = {(f["column"], f["operator"]) for f in _filters(call)}
    assert columns == {
        ("isRootObservation", "="),
        ("startTime", ">="),
        ("userId", "="),
        ("sessionId", "="),
        ("traceName", "="),
        ("tags", "all of"),
    }
    assert client.api.trace.last_list_kwargs is None

    [trace] = result["data"]
    assert trace["id"] == "t_1"
    assert trace["name"] == "support-turn"
    assert trace["session_id"] == "s_a"
    assert trace["user_id"] == "user_a"
    assert trace["tags"] == ["prod", "eu"]
    assert trace["input"] == {"question": "where is my order?"}
    assert trace["html_path"] == "/project/project_1/traces/t_1"


def test_fetch_traces_excludes_roots_older_than_age(v4_state):
    """The startTime lower bound removes a root just beyond the requested age."""
    client = v4_state.langfuse_client
    _add_trace(client, "inside", minutes=-49)
    _add_trace(client, "outside", minutes=-51)

    result = _fetch_traces(v4_state, age=60)

    assert [trace["id"] for trace in result["data"]] == ["inside"]


def test_fetch_traces_include_observations_hydrates_from_v2(v4_state):
    """Observations come from one v2 listing per trace, as snake_case rows."""
    client = v4_state.langfuse_client
    _add_trace(client, "t_1", minutes=1)

    result = _fetch_traces(v4_state, name="support-turn", include_observations=True)

    [trace] = result["data"]
    assert {obs["id"] for obs in trace["observations"]} == {"t_1_root", "t_1_gen"}
    assert all(obs["trace_id"] == "t_1" and "start_time" in obs for obs in trace["observations"])
    assert client.api.legacy.observations_v1.last_get_kwargs is None


def test_fetch_traces_page_two_walks_the_cursor(v4_state):
    """``page`` survives on the cursor-only endpoint: skipped pages are requested with ``core`` only."""
    client = v4_state.langfuse_client
    for minutes in (1, 2, 3):
        _add_trace(client, f"t_{minutes}", minutes=minutes)

    result = _fetch_traces(v4_state, name="support-turn", limit=1, page=2)

    assert [trace["id"] for trace in result["data"]] == ["t_2"]
    assert result["metadata"]["next_page"] == 3
    skip_call, page_call = client.api.observations.calls[-2:]
    assert skip_call["fields"] == "core" and skip_call["cursor"] is None
    assert page_call["cursor"] == "1"


def test_page_beyond_the_walk_cap_raises(v4_state):
    """A page past the cursor-walk cap fails loudly instead of issuing unbounded requests."""
    from langfuse_mcp.__main__ import V2_PAGE_WALK_MAX

    with pytest.raises(RuntimeError, match="ERR_LANGFUSE_V2_PAGE_LIMIT"):
        _fetch_traces(v4_state, page=V2_PAGE_WALK_MAX + 1)


def test_fetch_trace_rebuilds_the_trace_from_its_observation_rows(v4_state):
    """fetch_trace rebuilds the trace from v2 rows, sums costs and reads scores via Scores API v3."""
    from langfuse_mcp.__main__ import fetch_trace

    client = v4_state.langfuse_client
    _add_trace(client, "t_1", minutes=1)
    client._store.scores["score_1"].trace_id = "t_1"

    result = asyncio.run(fetch_trace(FakeContext(v4_state), trace_id="t_1", include_observations=True, output_mode="compact"))

    trace = result["data"]
    assert trace["id"] == "t_1"
    assert trace["output"] == "It ships tomorrow."
    assert trace["total_cost"] == pytest.approx(0.75)
    assert {obs["id"] for obs in trace["observations"]} == {"t_1_root", "t_1_gen"}
    assert [score["id"] for score in trace["scores"]] == ["score_1"]
    assert client.api.scores_v3.calls[-1]["trace_id"] == "t_1"
    assert client.api.trace.last_get_kwargs is None


def test_fetch_trace_without_observations_reads_root_io_by_id(v4_state):
    """The all-rows listing skips IO; only the root row is read with IO and metadata."""
    from langfuse_mcp.__main__ import V2_TRACE_COST_FIELDS, fetch_trace

    client = v4_state.langfuse_client
    _add_trace(client, "t_1", minutes=1)

    result = asyncio.run(fetch_trace(FakeContext(v4_state), trace_id="t_1", include_observations=False, output_mode="compact"))

    trace = result["data"]
    assert "observations" not in trace
    assert trace["input"] == {"question": "where is my order?"}
    assert trace["metadata"] == {"route": "support"}
    rows_call, root_call = client.api.observations.calls[:2]
    assert rows_call["trace_id"] == "t_1" and rows_call["fields"] == V2_TRACE_COST_FIELDS
    assert {f["column"]: f["value"] for f in _filters(root_call)} == {"id": "t_1_root", "traceId": "t_1"}


def test_fetch_trace_for_an_unknown_id_raises(v4_state):
    """A trace id with no observation rows is reported as not found."""
    from langfuse_mcp.__main__ import fetch_trace

    with pytest.raises(RuntimeError, match="ERR_LANGFUSE_TRACE_NOT_FOUND"):
        asyncio.run(fetch_trace(FakeContext(v4_state), trace_id="missing", include_observations=False, output_mode="compact"))


def test_fetch_observations_page_two_works_on_v2(v4_state):
    """page>1 used to raise on cursor-only clients; v2 walks the cursor instead."""
    from langfuse_mcp.__main__ import fetch_observations

    client = v4_state.langfuse_client
    _add_trace(client, "t_1", minutes=1)

    result = asyncio.run(
        fetch_observations(
            FakeContext(v4_state),
            type=None,
            age=60,
            name=None,
            user_id=None,
            trace_id="t_1",
            parent_observation_id=None,
            page=2,
            limit=1,
            output_mode="compact",
        )
    )

    assert [obs["id"] for obs in result["data"]] == ["t_1_root"]
    assert client.api.observations.calls[-1]["trace_id"] == "t_1"
    assert client.api.legacy.observations_v1.last_get_many_kwargs is None


def test_fetch_observations_excludes_rows_older_than_age(v4_state):
    """The startTime lower bound excludes observations just outside the window."""
    from langfuse_mcp.__main__ import fetch_observations

    client = v4_state.langfuse_client
    _add_trace(client, "inside", minutes=-49)
    _add_trace(client, "outside", minutes=-51)

    result = asyncio.run(
        fetch_observations(
            FakeContext(v4_state),
            type=None,
            age=60,
            name=None,
            user_id=None,
            trace_id=None,
            parent_observation_id=None,
            page=1,
            limit=50,
            output_mode="compact",
        )
    )

    assert {obs["id"] for obs in result["data"]} == {"inside_root", "inside_gen"}


def test_fetch_sessions_groups_root_observations_by_session(v4_state):
    """Sessions come from root observations grouped by sessionId, newest activity first."""
    from langfuse_mcp.__main__ import fetch_sessions

    client = v4_state.langfuse_client
    _add_trace(client, "t_1", minutes=1, session_id="s_old")
    _add_trace(client, "t_2", minutes=2, session_id="s_new")
    _add_trace(client, "t_3", minutes=3, session_id="s_old")
    _add_trace(client, "t_4", minutes=4, session_id=None)

    result = asyncio.run(fetch_sessions(FakeContext(v4_state), age=60, page=1, limit=2, output_mode="compact"))

    # Newest activity first; t_4 has no session, and the seeded 2023 session_1 is outside the window.
    assert [session["id"] for session in result["data"]] == ["s_old", "s_new"]
    assert result["data"][0]["last_trace_at"] == (T0 + timedelta(minutes=3)).isoformat()
    assert "next_page" not in result["metadata"]
    assert {"column": "sessionId", "operator": "is not null", "type": "null", "value": ""} in _filters(client.api.observations.calls[-1])
    assert client.api.sessions.last_list_kwargs is None


def test_fetch_sessions_excludes_sessions_older_than_age(v4_state):
    """A session whose root is just outside the window does not appear."""
    from langfuse_mcp.__main__ import fetch_sessions

    client = v4_state.langfuse_client
    _add_trace(client, "inside", minutes=-49, session_id="inside_session")
    _add_trace(client, "outside", minutes=-51, session_id="outside_session")

    result = asyncio.run(fetch_sessions(FakeContext(v4_state), age=60, page=1, limit=50, output_mode="compact"))

    assert [session["id"] for session in result["data"]] == ["inside_session"]


def test_get_session_details_filters_by_session_without_a_time_bound(v4_state):
    """Mirrors the v3 regression: no epoch-zero lower bound on the session lookup."""
    from langfuse_mcp.__main__ import get_session_details

    client = v4_state.langfuse_client
    _add_trace(client, "t_1", minutes=1, session_id="s_x")

    result = asyncio.run(get_session_details(FakeContext(v4_state), session_id="s_x", include_observations=False, output_mode="compact"))

    assert result["data"]["found"] is True
    assert result["data"]["trace_count"] == 1
    columns = {f["column"] for f in _filters(client.api.observations.calls[-1])}
    assert "sessionId" in columns and "startTime" not in columns


@pytest.mark.parametrize("status_code", [404, 405])
def test_servers_without_v2_fall_back_to_the_legacy_routes(v4_state, monkeypatch, status_code):
    """A self-hosted Langfuse v3 answers 404/405 on /v2/observations; every read falls back."""
    from langfuse_mcp.__main__ import fetch_observation, fetch_sessions, fetch_trace

    client = v4_state.langfuse_client

    def v2_not_served(self: Any, *, cursor=None, filter=None, **kwargs: Any) -> Any:
        raise _Status(status_code)

    # The signature keeps cursor + filter, so the capability check still selects v2.
    monkeypatch.setattr(_ObservationsV4API, "get_many", v2_not_served)

    _fetch_traces(v4_state)
    asyncio.run(fetch_trace(FakeContext(v4_state), trace_id="trace_1", include_observations=False, output_mode="compact"))
    asyncio.run(fetch_sessions(FakeContext(v4_state), age=60, page=1, limit=5, output_mode="compact"))
    asyncio.run(fetch_observation(FakeContext(v4_state), observation_id="obs_1", output_mode="compact"))

    assert client.api.trace.last_list_kwargs is not None
    assert client.api.trace.last_get_kwargs is not None
    assert client.api.sessions.last_list_kwargs is not None
    assert client.api.legacy.observations_v1.last_get_kwargs is not None


def test_other_v2_errors_propagate_without_a_fallback(v4_state, monkeypatch):
    """Only 404/405 means 'v2 not served'; any other error propagates."""
    client = v4_state.langfuse_client

    def server_error(self: Any, *, cursor=None, filter=None, **kwargs: Any) -> Any:
        raise _Status(500)

    monkeypatch.setattr(_ObservationsV4API, "get_many", server_error)

    with pytest.raises(_Status):
        _fetch_traces(v4_state)
    assert client.api.trace.last_list_kwargs is None


def test_sdk_v3_cursor_route_with_filter_is_used(tmp_path):
    """SDK 3.11.2+ exposes v2 as ``api.observations_v_2`` (with ``filter``); it is preferred there too."""
    from langfuse_mcp.__main__ import MCPState

    client = FakeLangfuse()
    client.api.observations_v_2 = _ObservationsV4API(client._store)
    _add_trace(client, "fresh", minutes=1)
    state = MCPState(langfuse_client=client, dump_dir=str(tmp_path))

    result = _fetch_traces(state)

    assert [trace["id"] for trace in result["data"]] == ["fresh"]
    assert client.api.observations_v_2.calls
    assert client.api.trace.last_list_kwargs is None


def test_normalize_v2_row_snake_cases_keys_and_parses_json_io():
    """v2 rows get the snake_case keys and parsed IO the v1 SDK models produced."""
    from langfuse_mcp.__main__ import _normalize_v2_row

    row = {
        "traceId": "t",
        "startTime": "2026-09-01T12:00:00Z",
        "timeToFirstToken": 0.2,
        "input": '{"a": 1}',
        "output": "plain text",
        "metadata": {"camelKey": "kept"},
    }

    assert _normalize_v2_row(row) == {
        "trace_id": "t",
        "start_time": "2026-09-01T12:00:00Z",
        "time_to_first_token": 0.2,
        "input": {"a": 1},
        "output": "plain text",
        "metadata": {"camelKey": "kept"},
    }


def test_get_observations_v2_method_needs_cursor_and_filter():
    """The v2 route is selected only when the method takes both cursor and filter."""
    from types import SimpleNamespace

    from langfuse_mcp import _compat

    def cursor_only(*, cursor=None, limit=None):
        return None

    def cursor_and_filter(*, cursor=None, limit=None, filter=None):
        return None

    assert (
        _compat.get_observations_v2_method(SimpleNamespace(api=SimpleNamespace(observations=SimpleNamespace(get_many=cursor_only)))) is None
    )
    v3_shape = SimpleNamespace(api=SimpleNamespace(observations_v_2=SimpleNamespace(get_many=cursor_and_filter)))
    assert _compat.get_observations_v2_method(v3_shape) is cursor_and_filter
