"""Unit tests for langfuse-mcp tool functions."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from tests.fakes import FakeContext, FakeLangfuse, FakeLangfuseV4, FakeObservation, FakePaginatedResponse


@pytest.fixture()
def state(tmp_path):
    """Return an MCPState instance using the v3-shaped fake client."""
    from langfuse_mcp.__main__ import MCPState

    return MCPState(langfuse_client=FakeLangfuse(), dump_dir=str(tmp_path))


@pytest.fixture(params=["v3", "v4"], ids=["v3", "v4"])
def observation_state(request, tmp_path):
    """Return an MCPState parametrized across the v3 and v4 fake client shapes.

    Tests using this fixture run twice — once against ``FakeLangfuse`` (v3 surface
    with ``api.observations.{get,get_many}``) and once against ``FakeLangfuseV4``
    (v4 surface with cursor-only ``api.observations.get_many`` and
    ``api.legacy.observations_v1`` page-based fallbacks).
    """
    from langfuse_mcp.__main__ import MCPState

    client = FakeLangfuse() if request.param == "v3" else FakeLangfuseV4()
    if request.param == "v4":
        recent = datetime.now(timezone.utc) - timedelta(minutes=1)
        client._store.observations["obs_1"].start_time = recent
        client._store.observations["obs_1"].end_time = recent
    return MCPState(langfuse_client=client, dump_dir=str(tmp_path))


def _observation_list_fake(client):
    """Return whichever fake namespace recorded the last list call (v3 vs v4 legacy)."""
    legacy = getattr(getattr(client.api, "legacy", None), "observations_v1", None)
    if legacy is not None and legacy.last_get_many_kwargs is not None:
        return legacy
    return client.api.observations


def _seed_route_decision_observations(client):
    """Add router-neutral route-decision observations to a fake Langfuse client."""
    now = datetime.now(timezone.utc) - timedelta(minutes=1)
    client._store.observations["route_ok"] = FakeObservation(
        id="route_ok",
        trace_id="trace_route",
        type="SPAN",
        name="mcp.route_decision",
        status="SUCCEEDED",
        start_time=now,
        end_time=now,
        metadata={
            "schema_version": "mcp.route_decision.v1",
            "decision_id": "dec_ok",
            "session_id": "session_route",
            "router_name": "wisepick",
            "provider": "canva",
            "execution_type": "api",
            "capability_id": "canva_capability",
            "callable": True,
            "confidence": 0.91,
            "latency_ms": 120,
            "candidate_count": 2,
            "reason_codes": ["capability_match"],
            "top_candidates": [{"rank": 1, "capability_id": "canva_capability", "score": 0.91}],
        },
    )
    client._store.observations["route_low"] = FakeObservation(
        id="route_low",
        trace_id="trace_route",
        type="SPAN",
        name="mcp.route_decision",
        status="SUCCEEDED",
        start_time=now,
        end_time=now,
        metadata={
            "schema_version": "mcp.route_decision.v1",
            "decision_id": "dec_low",
            "session_id": "session_route",
            "router_name": "wisepick",
            "provider": None,
            "execution_type": None,
            "capability_id": None,
            "callable": False,
            "confidence": 0.08,
            "latency_ms": 7535,
            "candidate_count": 5,
            "reason_codes": ["below_threshold"],
            "top_candidates": [{"rank": 1, "capability_id": "canva_capability", "score": 0.08, "pruned": True}],
        },
    )


def _seed_emitted_failed_route_decision(client):
    """Add the real WisePick-emitted no-route span from issue #43 as a fixture.

    Unlike the synthetic ``route_ok`` / ``route_low`` seeds, this is the exact
    failed-path envelope a producing runtime emits: full span envelope with parent
    linkage, a W3C ``traceparent``, the stable protocol fields
    (``router_version`` / ``policy_version`` / ``decision_method`` /
    ``feedback_expected``), and null selected-decision fields for the no-match case.
    It exercises metadata fields the synthetic seeds never set.
    """
    start = datetime.now(timezone.utc) - timedelta(minutes=1)
    end = start + timedelta(seconds=5, milliseconds=78)
    client._store.observations["obs_failed_route_19c5fa4"] = FakeObservation(
        id="obs_failed_route_19c5fa4",
        trace_id="trace_wisepick_eval_002",
        parent_observation_id="obs_parent_agent_turn_99f",
        type="SPAN",
        name="mcp.route_decision",
        status="SUCCEEDED",
        start_time=start,
        end_time=end,
        metadata={
            "schema_version": "mcp.route_decision.v1",
            "traceparent": "00-trace_wisepick_eval_002-span_failed_route_19c5fa4-01",
            "decision_id": "dec_19c5fa40a0f64ff4",
            "router_name": "wisepick",
            "router_version": "0.1.6",
            "policy_version": "bootstrap-v0",
            "decision_method": "ecu_deterministic_routing",
            "capability_id": None,
            "provider": None,
            "execution_type": None,
            "callable": False,
            "selected_tool": None,
            "confidence": 0.0008,
            "latency_ms": 5078,
            "candidate_count": 0,
            "top_candidates": [],
            "reason_codes": ["no_match_found"],
            "feedback_expected": False,
        },
    )


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
    # include_observations=True scopes the request to all field groups and raises
    # the per-request read timeout so large traces do not time out.
    kwargs = state.langfuse_client.api.trace.last_get_kwargs
    assert kwargs["trace_id"] == "trace_1"
    request_options = kwargs["request_options"]
    assert request_options["additional_query_parameters"]["fields"] == "core,io,scores,observations,metrics"
    assert request_options["timeout_in_seconds"] == 120


def test_fetch_trace_without_observations_scopes_fields(state):
    """include_observations=False must drop the expensive observations field group."""
    from langfuse_mcp.__main__ import fetch_trace

    ctx = FakeContext(state)
    asyncio.run(fetch_trace(ctx, trace_id="trace_1", include_observations=False, output_mode="compact"))
    fields = state.langfuse_client.api.trace.last_get_kwargs["request_options"]["additional_query_parameters"]["fields"]
    assert "observations" not in fields
    assert fields == "core,io,scores,metrics"


def test_fetch_trace_falls_back_for_clients_without_request_options(tmp_path):
    """Older trace clients without request_options still return a trace."""
    from langfuse_mcp.__main__ import MCPState, fetch_trace

    class LegacyTraceAPI:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def get(self, trace_id: str, **kwargs: Any) -> dict[str, Any]:
            self.calls.append({"trace_id": trace_id, **kwargs})
            if "request_options" in kwargs:
                raise TypeError("unexpected keyword argument 'request_options'")
            return {"id": trace_id, "observations": ["obs_1"]}

    class LegacyAPI:
        def __init__(self) -> None:
            self.trace = LegacyTraceAPI()

    class LegacyLangfuse:
        def __init__(self) -> None:
            self.api = LegacyAPI()

    client = LegacyLangfuse()
    state = MCPState(langfuse_client=client, dump_dir=str(tmp_path))
    ctx = FakeContext(state)

    result = asyncio.run(fetch_trace(ctx, trace_id="trace_1", include_observations=True, output_mode="compact"))

    assert result["data"]["id"] == "trace_1"
    assert client.api.trace.calls == [
        {
            "trace_id": "trace_1",
            "request_options": {
                "additional_query_parameters": {"fields": "core,io,scores,observations,metrics"},
                "timeout_in_seconds": 120,
            },
        },
        {"trace_id": "trace_1"},
    ]


def test_fetch_observations(observation_state):
    """fetch_observations should drive the active page-based observations endpoint."""
    from langfuse_mcp.__main__ import fetch_observations

    ctx = FakeContext(observation_state)
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

    namespace = _observation_list_fake(observation_state.langfuse_client)
    assert namespace.last_get_many_kwargs is not None
    assert namespace.last_get_many_kwargs["limit"] == 50


def test_fetch_observations_type_filter_covers_every_langfuse_observation_type():
    """The Literal on the ``type`` filter must list exactly what the Langfuse SDK's enum lists."""
    import typing

    from langfuse_mcp import _compat
    from langfuse_mcp.__main__ import OBSERVATION_TYPE_LITERAL

    # langfuse.api ObservationType, as of langfuse 4.15
    expected = {"SPAN", "GENERATION", "EVENT", "AGENT", "TOOL", "CHAIN", "RETRIEVER", "EVALUATOR", "EMBEDDING", "GUARDRAIL"}
    assert set(typing.get_args(OBSERVATION_TYPE_LITERAL)) == expected

    observation_type = _compat.resolve_request_model("ingestion", "observation_type", "ObservationType")
    if observation_type is not dict:  # the suite stubs langfuse; the real SDK is only present locally
        assert {member.value for member in observation_type} == expected


def test_fetch_observations_passes_a_tool_type_filter_through(observation_state):
    """A TOOL filter reaches the observations endpoint unchanged."""
    from langfuse_mcp.__main__ import fetch_observations

    ctx = FakeContext(observation_state)
    asyncio.run(
        fetch_observations(
            ctx,
            type="TOOL",
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

    namespace = _observation_list_fake(observation_state.langfuse_client)
    assert namespace.last_get_many_kwargs is not None
    assert namespace.last_get_many_kwargs["type"] == "TOOL"


@pytest.mark.parametrize("observation_type", ["TOOL", "AGENT"])
def test_fetch_observations_type_literal_accepts_non_span_types(observation_type):
    """Types beyond the original SPAN/GENERATION/EVENT trio pass the tool's actual type validation."""
    import typing

    from pydantic import TypeAdapter

    from langfuse_mcp.__main__ import fetch_observations

    annotation = typing.get_type_hints(fetch_observations)["type"]
    assert TypeAdapter(annotation).validate_python(observation_type) == observation_type


def test_fetch_observation(observation_state):
    """fetch_observation resolves via the v3 getter, or on v4 via an ``id`` filter on Observations API v2."""
    from langfuse_mcp.__main__ import fetch_observation

    ctx = FakeContext(observation_state)
    result = asyncio.run(fetch_observation(ctx, observation_id="obs_1", output_mode="compact"))
    assert result["data"]["id"] == "obs_1"

    client = observation_state.langfuse_client
    legacy = getattr(getattr(client.api, "legacy", None), "observations_v1", None)
    if legacy is None:
        assert client.api.observations.last_get_kwargs["observation_id"] == "obs_1"
    else:
        assert legacy.last_get_kwargs is None
        assert json.loads(client.api.observations.last_get_many_kwargs["filter"]) == [
            {"type": "string", "column": "id", "operator": "=", "value": "obs_1"}
        ]


def test_find_route_decisions_filters_on_metadata_contract(observation_state):
    """find_route_decisions should depend on route-decision metadata, not output payload shape."""
    from langfuse_mcp.__main__ import find_route_decisions

    _seed_route_decision_observations(observation_state.langfuse_client)
    ctx = FakeContext(observation_state)
    result = asyncio.run(
        find_route_decisions(
            ctx,
            age=10,
            trace_id=None,
            session_id="session_route",
            decision_id=None,
            router_name="wisepick",
            provider="canva",
            capability_id=None,
            page=1,
            limit=50,
            output_mode="compact",
        )
    )

    assert result["metadata"]["item_count"] == 1
    assert result["metadata"]["metadata_filter"] == {
        "schema_version": "mcp.route_decision.v1",
        "session_id": "session_route",
        "router_name": "wisepick",
        "provider": "canva",
    }
    assert result["data"][0]["decision_id"] == "dec_ok"
    assert result["data"][0]["provider"] == "canva"

    namespace = _observation_list_fake(observation_state.langfuse_client)
    assert namespace.last_get_many_kwargs is not None
    assert namespace.last_get_many_kwargs["type"] == "SPAN"


def test_get_route_decision_returns_metadata_decision(observation_state):
    """get_route_decision should return a single route decision by metadata decision_id."""
    from langfuse_mcp.__main__ import get_route_decision

    _seed_route_decision_observations(observation_state.langfuse_client)
    ctx = FakeContext(observation_state)
    result = asyncio.run(get_route_decision(ctx, decision_id="dec_ok", age=10, output_mode="compact"))

    assert result["metadata"]["found"] is True
    assert result["data"]["decision_id"] == "dec_ok"
    assert result["data"]["capability_id"] == "canva_capability"


def test_find_route_decisions_excludes_non_route_metadata(observation_state):
    """Only observations declaring mcp.route_decision.v1 in metadata should be returned."""
    from langfuse_mcp.__main__ import find_route_decisions

    now = datetime(2026, 5, 19, 11, 6, 34, tzinfo=timezone.utc)
    observation_state.langfuse_client._store.observations["wrong_schema"] = FakeObservation(
        id="wrong_schema",
        trace_id="trace_route",
        type="SPAN",
        name="mcp.route_decision",
        status="SUCCEEDED",
        start_time=now,
        end_time=now,
        metadata={
            "schema_version": "agent.route_decision.v1",
            "decision_id": "dec_wrong",
            "session_id": "session_route",
            "router_name": "wisepick",
        },
    )
    observation_state.langfuse_client._store.observations["missing_metadata"] = FakeObservation(
        id="missing_metadata",
        trace_id="trace_route",
        type="SPAN",
        name="mcp.route_decision",
        status="SUCCEEDED",
        start_time=now,
        end_time=now,
    )

    ctx = FakeContext(observation_state)
    result = asyncio.run(
        find_route_decisions(
            ctx,
            age=10,
            trace_id=None,
            session_id="session_route",
            decision_id=None,
            router_name="wisepick",
            provider=None,
            capability_id=None,
            page=1,
            limit=50,
            output_mode="compact",
        )
    )

    assert result["metadata"]["item_count"] == 0
    assert result["data"] == []


def test_get_route_decision_round_trips_real_emitted_failed_path(observation_state):
    """The real WisePick failed-path envelope (issue #43) round-trips through the read layer.

    Guards the full no-route contract end to end: span envelope linkage, the stable
    protocol fields the synthetic seeds never set, and null selected-decision fields.
    """
    from langfuse_mcp.__main__ import get_route_decision

    _seed_emitted_failed_route_decision(observation_state.langfuse_client)
    ctx = FakeContext(observation_state)
    result = asyncio.run(get_route_decision(ctx, decision_id="dec_19c5fa40a0f64ff4", age=30, output_mode="compact"))

    assert result["metadata"]["found"] is True
    decision = result["data"]
    # Read-layer mapping preserves the schema contract the filter keyed on.
    assert decision["schema_version"] == "mcp.route_decision.v1"
    # Span envelope linkage.
    assert decision["trace_id"] == "trace_wisepick_eval_002"
    assert decision["parent_observation_id"] == "obs_parent_agent_turn_99f"
    assert decision["metadata"]["traceparent"] == "00-trace_wisepick_eval_002-span_failed_route_19c5fa4-01"
    # Stable protocol fields not covered by the synthetic seeds.
    assert decision["router_version"] == "0.1.6"
    assert decision["policy_version"] == "bootstrap-v0"
    assert decision["decision_method"] == "ecu_deterministic_routing"
    assert decision["feedback_expected"] is False
    # No-route contract: null selected-decision fields, no candidates.
    assert decision["callable"] is False
    assert decision["selected_tool"] is None
    assert decision["capability_id"] is None
    assert decision["provider"] is None
    assert decision["execution_type"] is None
    assert decision["confidence"] == 0.0008
    assert decision["candidate_count"] == 0
    assert decision["top_candidates"] == []
    assert decision["reason_codes"] == ["no_match_found"]


def test_find_low_confidence_flags_real_emitted_failed_path(observation_state):
    """The real failed-path envelope is surfaced as both low-confidence and uncallable."""
    from langfuse_mcp.__main__ import find_low_confidence_route_decisions

    _seed_emitted_failed_route_decision(observation_state.langfuse_client)
    ctx = FakeContext(observation_state)
    result = asyncio.run(
        find_low_confidence_route_decisions(
            ctx,
            age=30,
            trace_id=None,
            session_id=None,
            router_name="wisepick",
            provider=None,
            capability_id=None,
            max_confidence=0.5,
            include_uncallable=True,
            page=1,
            limit=50,
            output_mode="compact",
        )
    )

    assert result["metadata"]["item_count"] == 1
    assert result["data"][0]["decision_id"] == "dec_19c5fa40a0f64ff4"
    assert result["data"][0]["callable"] is False


def test_summarize_route_decisions_counts_low_confidence(observation_state):
    """summarize_route_decisions should aggregate over generic metadata fields."""
    from langfuse_mcp.__main__ import summarize_route_decisions

    _seed_route_decision_observations(observation_state.langfuse_client)
    ctx = FakeContext(observation_state)
    result = asyncio.run(
        summarize_route_decisions(
            ctx,
            age=10,
            trace_id=None,
            session_id="session_route",
            router_name="wisepick",
            provider=None,
            capability_id=None,
            max_confidence=0.5,
            page=1,
            limit=50,
        )
    )

    assert result["data"]["total_decisions"] == 2
    assert result["data"]["provider_counts"]["canva"] == 1
    assert result["data"]["provider_counts"]["unknown"] == 1
    assert result["data"]["callable_counts"]["True"] == 1
    assert result["data"]["callable_counts"]["False"] == 1
    assert result["data"]["low_confidence_count"] == 1
    assert result["data"]["uncallable_count"] == 1


def test_find_low_confidence_route_decisions_includes_uncallable(observation_state):
    """find_low_confidence_route_decisions should flag confidence threshold and callable cases."""
    from langfuse_mcp.__main__ import find_low_confidence_route_decisions

    _seed_route_decision_observations(observation_state.langfuse_client)
    ctx = FakeContext(observation_state)
    result = asyncio.run(
        find_low_confidence_route_decisions(
            ctx,
            age=10,
            trace_id=None,
            session_id="session_route",
            router_name="wisepick",
            provider=None,
            capability_id=None,
            max_confidence=0.5,
            include_uncallable=True,
            page=1,
            limit=50,
            output_mode="compact",
        )
    )

    assert result["metadata"]["item_count"] == 1
    assert result["metadata"]["candidate_count"] == 2
    assert result["data"][0]["decision_id"] == "dec_low"
    assert result["data"][0]["callable"] is False


def test_list_observations_cursor_only_rejects_page_gt_one(tmp_path):
    """A v4 client without the page-based legacy fallback must raise on page>1."""
    from types import SimpleNamespace

    from langfuse_mcp.__main__ import _list_observations

    def cursor_only_get_many(*, cursor=None, limit=None, **_: object):
        return SimpleNamespace(data=[], meta=SimpleNamespace(cursor=None))

    cursor_client = SimpleNamespace(api=SimpleNamespace(observations=SimpleNamespace(get_many=cursor_only_get_many)))

    with pytest.raises(RuntimeError, match="legacy.observations_v1"):
        _list_observations(
            cursor_client,
            limit=10,
            page=2,
            from_start_time=None,
            to_start_time=None,
            obs_type=None,
            name=None,
            user_id=None,
            trace_id=None,
            parent_observation_id=None,
            metadata=None,
        )


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


@pytest.mark.parametrize("observation_state", ["v4"], indirect=True)
def test_get_exception_details_works_when_legacy_trace_read_404s(observation_state):
    """B3: self-hosted server v4 removes legacy trace reads; the scan must run on observations alone."""
    from langfuse_mcp.__main__ import get_exception_details

    client = observation_state.langfuse_client
    _seed_error_observation(client._store, obs_id="obs_trace404", metadata={"code.filepath": "sv4.py"})

    class ServerV4Trace404(Exception):
        status_code = 404

    def trace_gone(*args, **kwargs):
        raise ServerV4Trace404("legacy trace endpoint unavailable on server v4")

    client.api.trace.get = trace_gone
    if hasattr(client.api, "legacy") and hasattr(client.api.legacy, "traces"):
        client.api.legacy.traces.get = trace_gone

    ctx = FakeContext(observation_state)
    result = asyncio.run(get_exception_details(ctx, trace_id="trace_1", span_id=None, output_mode="compact"))
    assert result["metadata"]["item_count"] == 1
    assert result["data"][0]["observation_id"] == "obs_trace404"


def test_get_exception_details_freezes_upper_time_bound(state):
    """get_exception_details scans by trace_id with one frozen to_start_time upper bound and no lower bound."""
    from langfuse_mcp.__main__ import get_exception_details

    ctx = FakeContext(state)
    result = asyncio.run(get_exception_details(ctx, trace_id="trace_1", span_id=None, output_mode="compact"))
    assert isinstance(result["data"], list)
    assert result["metadata"]["item_count"] == len(result["data"])

    obs_kwargs = state.langfuse_client.api.observations.last_get_many_kwargs
    if obs_kwargs is None:
        obs_kwargs = state.langfuse_client.api.observations_v_2.last_get_many_kwargs
    assert obs_kwargs is not None
    assert obs_kwargs["trace_id"] == "trace_1"
    assert "from_start_time" not in obs_kwargs
    assert "to_start_time" in obs_kwargs
    assert obs_kwargs["to_start_time"] <= datetime.now(tz=timezone.utc)


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


def _seed_error_observation(
    store, *, obs_id, trace_id="trace_1", type="TOOL", level="ERROR", metadata=None, status_message=None, name="tool_call"
):
    """Seed one realistic observation (no invented events) into a fake store."""
    start = datetime.now(timezone.utc) - timedelta(minutes=1)
    store.observations[obs_id] = FakeObservation(
        id=obs_id,
        type=type,
        name=name,
        status="ERROR" if level == "ERROR" else "SUCCEEDED",
        start_time=start,
        end_time=start,
        trace_id=trace_id,
        metadata=metadata or {},
        level=level,
        status_message=status_message,
    )


@pytest.mark.parametrize("observation_state", ["v3", "v4"], indirect=True)
def test_error_scan_finds_non_span_error_observation(observation_state):
    """All four tools reach an ERROR observation recorded on a TOOL-type observation."""
    from langfuse_mcp.__main__ import find_exceptions, find_exceptions_in_file, get_error_count

    client = observation_state.langfuse_client
    _seed_error_observation(
        client._store,
        obs_id="obs_tool_err",
        metadata={"code.filepath": "src/ai/tools.py", "code.function": "run_tool", "exception.type": "ValueError"},
    )
    ctx = FakeContext(observation_state)

    grouped = asyncio.run(find_exceptions(ctx, age=60, group_by="file"))
    assert grouped["metadata"]["count_basis"] == "error_level_observations"
    file_groups = [g for g in grouped["data"] if g["group"] == "src/ai/tools.py"]
    assert len(file_groups) == 1
    assert file_groups[0]["count"] == 1
    assert file_groups[0]["observation_id"] == "obs_tool_err"
    assert file_groups[0]["trace_id"] == "trace_1"

    in_file = asyncio.run(find_exceptions_in_file(ctx, filepath="src/ai/tools.py", age=60, output_mode="compact"))
    assert in_file["metadata"]["item_count"] == 1
    record = in_file["data"][0]
    assert record["observation_id"] == "obs_tool_err"
    assert record["exception_type"] == "ValueError"
    assert record["level"] == "ERROR"
    assert record["observation_type"] == "TOOL"
    assert record["event_id"] is None and record["event_name"] is None

    count = asyncio.run(get_error_count(ctx, age=60))
    assert count["data"]["observation_count"] == 1
    assert count["data"]["trace_count"] == 1
    assert count["data"]["exception_count"] is None
    assert count["metadata"]["count_basis"] == "error_level_observations"


def test_status_message_alone_is_not_an_error(observation_state):
    """A non-empty status_message without level=ERROR is never counted as an error."""
    from langfuse_mcp.__main__ import get_error_count

    client = observation_state.langfuse_client
    _seed_error_observation(
        client._store,
        obs_id="obs_warn_msg",
        level="WARNING",
        status_message="something notable happened",
    )
    ctx = FakeContext(observation_state)

    result = asyncio.run(get_error_count(ctx, age=60))
    assert result["data"]["observation_count"] == 0


def test_absent_metadata_yields_unknown_group_and_null_fields(observation_state):
    """Missing recorded metadata groups as unknown and leaves exception fields null — no invention."""
    from langfuse_mcp.__main__ import find_exceptions

    client = observation_state.langfuse_client
    _seed_error_observation(client._store, obs_id="obs_bare_err", metadata={})
    ctx = FakeContext(observation_state)

    result = asyncio.run(find_exceptions(ctx, age=60, group_by="file"))
    unknown = [g for g in result["data"] if g["group"] == "unknown"]
    assert len(unknown) == 1


def test_metadata_attributes_fallback_and_top_level_precedence(observation_state):
    """Key-presence precedence: top-level selected when present (invalid -> null, no resurrection); attributes only when key absent."""
    from langfuse_mcp.__main__ import _metadata_value

    obs = {"metadata": {"attributes": {"exception.type": "TimeoutError"}}}
    assert _metadata_value(obs, "exception.type") == "TimeoutError"

    obs_precedence = {"metadata": {"exception.type": "ValueError", "attributes": {"exception.type": "TimeoutError"}}}
    assert _metadata_value(obs_precedence, "exception.type") == "ValueError"

    # Cleared top-level value must NOT resurrect the copied attributes value (B5).
    obs_cleared = {"metadata": {"exception.type": None, "attributes": {"exception.type": "TimeoutError"}}}
    assert _metadata_value(obs_cleared, "exception.type") is None

    obs_empty = {"metadata": {"exception.type": "", "attributes": {"exception.type": "TimeoutError"}}}
    assert _metadata_value(obs_empty, "exception.type") is None

    # Absent at both locations -> None.
    assert _metadata_value({"metadata": {}}, "exception.type") is None
    assert _metadata_value({}, "exception.type") is None


def test_error_scan_cap_raises_no_partial_data(observation_state, monkeypatch):
    """Hitting the request cap raises the scan-limit error instead of returning partial counts."""
    from langfuse_mcp import __main__ as m

    monkeypatch.setattr(m, "ERROR_SCAN_MAX_REQUESTS", 2)

    client = observation_state.langfuse_client

    calls = {"n": 0}

    def endless_cursor(*, cursor=None, limit=None, level=None, fields=None, expand_metadata=None, **kwargs):
        calls["n"] += 1
        return FakePaginatedResponse(data=[], meta={"cursor": f"cursor-{calls['n']}"})

    # Both cursor surfaces get the endless stub; v3 also has observations_v_2, which is preferred.
    client.api.observations.get_many = endless_cursor
    if hasattr(client.api, "observations_v_2"):
        client.api.observations_v_2.get_many = endless_cursor
    if hasattr(client.api, "legacy") and hasattr(client.api.legacy, "observations_v1"):
        client.api.legacy.observations_v1.get_many = endless_cursor

    with pytest.raises(m.ErrorScanLimitError) as exc_info:
        asyncio.run(
            m._scan_error_observations(
                client, from_start_time=datetime(2023, 1, 1, tzinfo=timezone.utc), to_start_time=datetime(2023, 1, 2, tzinfo=timezone.utc)
            )
        )
    assert "ERR_LANGFUSE_ERROR_SCAN_LIMIT" in str(exc_info.value)
    assert calls["n"] == 2


@pytest.mark.parametrize("observation_state", ["v4"], indirect=True)
def test_error_scan_normalizes_v3_alias_serialized_rows(observation_state):
    """SDK v3 serializes observations by_alias=True (camelCase; V2 rows are raw dicts); the scan dedupes and builds details."""
    from langfuse_mcp import __main__ as m

    client = observation_state.langfuse_client
    # v3.11.2 Observation.dict() returns by_alias=True keys; V2 data rows are raw dicts.
    alias_row = {
        "id": "obs_alias_1",
        "traceId": "trace_alias_1",
        "type": "TOOL",
        "name": "tool_call",
        "startTime": "2023-01-01T00:00:00Z",
        "level": "ERROR",
        "statusMessage": "boom",
        "metadata": {"attributes": {"exception.message": "boom from attrs"}},
    }
    alias_row_same_id_diff_trace = {
        "id": "obs_alias_1",
        "traceId": "trace_alias_2",
        "type": "TOOL",
        "name": "tool_call",
        "startTime": "2023-01-01T00:00:00Z",
        "level": "ERROR",
        "statusMessage": None,
    }

    def alias_cursor(*, cursor=None, limit=None, level=None, trace_id=None, fields=None, expand_metadata=None, **kwargs):
        rows = [alias_row, alias_row_same_id_diff_trace]
        if trace_id is not None:
            rows = [r for r in rows if r.get("traceId") == trace_id]
        return FakePaginatedResponse(data=rows, meta={"cursor": None})

    client.api.observations.get_many = alias_cursor

    # Dedupe identity is (trace_id, observation_id): same obs id in two traces -> both kept.
    observations = m._scan_error_observations(
        client,
        from_start_time=datetime(2023, 1, 1, tzinfo=timezone.utc),
        to_start_time=datetime(2023, 1, 2, tzinfo=timezone.utc),
    )
    assert len(observations) == 2
    assert {obs["trace_id"] for obs in observations} == {"trace_alias_1", "trace_alias_2"}

    # Detail fields read snake_case after normalization.
    from langfuse_mcp.__main__ import get_exception_details

    ctx = FakeContext(observation_state)
    result = asyncio.run(get_exception_details(ctx, trace_id="trace_alias_1", span_id=None, output_mode="compact"))
    assert result["metadata"]["item_count"] == 1
    record = result["data"][0]
    assert record["trace_id"] == "trace_alias_1"
    assert record["timestamp"] == "2023-01-01T00:00:00Z"
    assert record["status_message"] == "boom"


@pytest.mark.parametrize("observation_state", ["v3"], indirect=True)
def test_error_scan_prefers_v3_cursor_route_and_forwards_expand_metadata(observation_state):
    """On v3 the scan prefers observations_v_2 (cursor) and forwards expandMetadata via request_options (3.11.2 lacks the param)."""
    from langfuse_mcp import __main__ as m

    client = observation_state.langfuse_client
    _seed_error_observation(client._store, obs_id="obs_v3_cursor", metadata={"code.filepath": "v3.py"})

    observations = m._scan_error_observations(
        client,
        from_start_time=datetime(2023, 1, 1, tzinfo=timezone.utc),
        to_start_time=datetime(2023, 1, 2, tzinfo=timezone.utc),
    )
    assert [obs["id"] for obs in observations] == ["obs_v3_cursor"]

    cursor_kwargs = client.api.observations_v_2.last_get_many_kwargs
    assert cursor_kwargs is not None, "cursor route must be preferred over v3 page route"
    assert client.api.observations.last_get_many_kwargs is None, "page route must not be called when cursor works"
    assert cursor_kwargs["fields"] == "core,basic,metadata"
    assert cursor_kwargs["request_options"]["additional_query_parameters"]["expandMetadata"] == (
        "attributes,code.filepath,code.function,code.lineno,exception.type,exception.message,exception.stacktrace"
    )


@pytest.mark.parametrize("observation_state", ["v3"], indirect=True)
def test_error_scan_v3_cursor_404_falls_back_to_v3_page_route(observation_state):
    """v3: cursor route 404s -> scan falls back to v3's OWN page route (api.observations.get_many), not just v4 legacy."""
    from langfuse_mcp import __main__ as m

    client = observation_state.langfuse_client
    _seed_error_observation(client._store, obs_id="obs_v3_page", metadata={"code.filepath": "page.py"})

    class EndpointNotFound(Exception):
        status_code = 404

    calls = {"cursor": 0, "page": 0}

    def cursor_404(*, cursor=None, limit=None, level=None, **kwargs):
        calls["cursor"] += 1
        raise EndpointNotFound("not found")

    real_page_get_many = client.api.observations.get_many

    def page_spy(*, page=None, limit=None, level=None, **kwargs):
        calls["page"] += 1
        return real_page_get_many(page=page, limit=limit, level=level, **kwargs)

    client.api.observations_v_2.get_many = cursor_404
    client.api.observations.get_many = page_spy

    observations = m._scan_error_observations(
        client,
        from_start_time=datetime(2023, 1, 1, tzinfo=timezone.utc),
        to_start_time=datetime(2023, 1, 2, tzinfo=timezone.utc),
    )
    assert [obs["id"] for obs in observations] == ["obs_v3_page"]
    assert calls["cursor"] == 1 and calls["page"] == 1


def test_error_scan_two_page_cursor_happy_path(observation_state):
    """V2 cursor scan: later-page ERROR found; same (trace_id, observation_id) on page 1 AND page 2 dedupes."""
    from langfuse_mcp import __main__ as m

    client = observation_state.langfuse_client
    # Exercise the v4 cursor route directly; v3's preferred observations_v_2 would win otherwise.
    if hasattr(client.api, "observations_v_2"):
        del client.api.observations_v_2
    _seed_error_observation(client._store, obs_id="obs_page1_dupe", metadata={"code.filepath": "early.py"})
    _seed_error_observation(client._store, obs_id="obs_page2", metadata={"code.filepath": "late.py"})
    dupe_dict = client._store.observations["obs_page1_dupe"].__dict__
    page2_dict = client._store.observations["obs_page2"].__dict__

    requests: list[dict[str, Any]] = []

    def two_page_cursor(*, cursor=None, limit=None, level=None, fields=None, expand_metadata=None, **kwargs):
        requests.append({"cursor": cursor, "level": level, "fields": fields, "expand_metadata": expand_metadata})
        if cursor is None:
            return FakePaginatedResponse(data=[dupe_dict], meta={"cursor": "cursor-2"})
        return FakePaginatedResponse(data=[page2_dict, dupe_dict], meta={"cursor": None})

    client.api.observations.get_many = two_page_cursor

    result = m._scan_error_observations(
        client,
        from_start_time=datetime(2023, 1, 1, tzinfo=timezone.utc),
        to_start_time=datetime(2023, 1, 2, tzinfo=timezone.utc),
    )
    # Cross-page duplicate (page1 dupe re-served on page 2) appears once; distinct page-2 ERROR included.
    assert [obs["id"] for obs in result] == ["obs_page1_dupe", "obs_page2"]
    assert len(requests) == 2
    assert requests[0]["cursor"] is None and requests[1]["cursor"] == "cursor-2"
    assert all(req["level"] == "ERROR" for req in requests)
    assert all(req["fields"] == "core,basic,metadata" for req in requests)
    assert all(
        req["expand_metadata"] == "attributes,code.filepath,code.function,code.lineno,exception.type,exception.message,exception.stacktrace"
        for req in requests
    )


def test_error_scan_404_falls_back_to_page_route_then_propagates_without_one(observation_state):
    """v4 cursor surface: 404 switches once to a confirmed page route; without one the original 404 propagates."""
    from langfuse_mcp import __main__ as m

    if not (
        hasattr(observation_state.langfuse_client.api, "legacy")
        and hasattr(observation_state.langfuse_client.api.legacy, "observations_v1")
    ):
        pytest.skip("v3 surface has no cursor-capable primary route; 404-fallback logic is cursor-only")

    client = observation_state.langfuse_client

    class EndpointNotFound(Exception):
        status_code = 404

    calls = {"cursor": 0, "page": 0}

    def cursor_404(*, cursor=None, limit=None, level=None, **kwargs):
        calls["cursor"] += 1
        raise EndpointNotFound("not found")

    def page_ok(*, page=None, limit=None, level=None, **kwargs):
        calls["page"] += 1
        return FakePaginatedResponse(data=[], meta={"next_page": None, "total_pages": 1, "total": 0})

    # Case 1: a confirmed page route exists -> fallback happens exactly once, then success via page mode.
    client.api.observations.get_many = cursor_404
    client.api.legacy.observations_v1.get_many = page_ok
    result = m._scan_error_observations(
        client,
        from_start_time=datetime(2023, 1, 1, tzinfo=timezone.utc),
        to_start_time=datetime(2023, 1, 2, tzinfo=timezone.utc),
    )
    assert result == []
    assert calls["cursor"] == 1 and calls["page"] == 1

    # Case 2: remove the page route -> the original 404 propagates with exactly one cursor call.
    del client.api.legacy.observations_v1
    calls["cursor"] = 0
    client.api.observations.get_many = cursor_404
    with pytest.raises(EndpointNotFound):
        asyncio.run(
            m._scan_error_observations(
                client,
                from_start_time=datetime(2023, 1, 1, tzinfo=timezone.utc),
                to_start_time=datetime(2023, 1, 2, tzinfo=timezone.utc),
            )
        )
    assert calls["cursor"] == 1


def test_error_scan_page_mode_uses_total_pages_and_level_filter(observation_state):
    """V1 page scan: real total_pages shape drives continuation, level filter is sent and applied."""
    from langfuse_mcp import __main__ as m

    client = observation_state.langfuse_client
    # Exercise the page route directly: remove the preferred cursor surface on v3.
    if hasattr(client.api, "observations_v_2"):
        del client.api.observations_v_2
    _seed_error_observation(client._store, obs_id="obs_v1_p2")
    obs_dict = client._store.observations["obs_v1_p2"].__dict__

    requests: list[dict[str, Any]] = []

    def two_page_v1(*, page=None, limit=None, level=None, trace_id=None, **kwargs):
        requests.append({"page": page, "level": level})
        if page == 1:
            # v1 MetaResponse carries only integer pagination fields (totalPages + page);
            # no next_page. Continuation MUST come from total_pages.
            return FakePaginatedResponse(data=[], meta={"total_pages": 2, "total": 1})
        return FakePaginatedResponse(data=[obs_dict], meta={"total_pages": 2, "total": 1})

    client.api.observations.get_many = two_page_v1  # v3 surface: page-mode primary
    if hasattr(client.api, "legacy") and hasattr(client.api.legacy, "observations_v1"):
        client.api.legacy.observations_v1.get_many = two_page_v1

    result = m._scan_error_observations(
        client,
        from_start_time=datetime(2023, 1, 1, tzinfo=timezone.utc),
        to_start_time=datetime(2023, 1, 2, tzinfo=timezone.utc),
    )
    assert [obs["id"] for obs in result] == ["obs_v1_p2"]
    assert [req["page"] for req in requests] == [1, 2]
    assert all(req["level"] == "ERROR" for req in requests)


def test_error_scan_preserves_integer_line_number(observation_state):
    """A recorded integer code.lineno passes through as an int — not stringified or dropped."""
    from langfuse_mcp.__main__ import _error_record

    obs = {
        "id": "obs_lineno",
        "trace_id": "trace_1",
        "start_time": "2023-01-01T00:00:00+00:00",
        "level": "ERROR",
        "type": "TOOL",
        "status_message": None,
        "metadata": {"code.function": "run", "code.lineno": 42},
    }
    record = _error_record(obs)
    assert record["line_number"] == 42
    assert isinstance(record["line_number"], int)


def test_find_exceptions_group_by_name_and_observation_type(observation_state):
    """New grouping choices work; existing default (file) unchanged."""
    from langfuse_mcp.__main__ import find_exceptions

    client = observation_state.langfuse_client
    _seed_error_observation(client._store, obs_id="obs_named", name="my_tool", type="TOOL")
    ctx = FakeContext(observation_state)

    by_name = asyncio.run(find_exceptions(ctx, age=60, group_by="name"))
    assert any(g["group"] == "my_tool" for g in by_name["data"])

    by_type = asyncio.run(find_exceptions(ctx, age=60, group_by="observation_type"))
    assert any(g["group"] == "TOOL" for g in by_type["data"])


def test_get_exception_details_scans_by_trace_id(observation_state):
    """get_exception_details uses the shared scan filtered by trace_id; span_id filters by observation id."""
    from langfuse_mcp.__main__ import get_exception_details

    client = observation_state.langfuse_client
    _seed_error_observation(client._store, obs_id="obs_t1_err", trace_id="trace_1")
    _seed_error_observation(client._store, obs_id="obs_t1_err2", trace_id="trace_1")
    ctx = FakeContext(observation_state)

    result = asyncio.run(get_exception_details(ctx, trace_id="trace_1", span_id="obs_t1_err2", output_mode="compact"))
    assert result["metadata"]["item_count"] == 1
    assert result["data"][0]["observation_id"] == "obs_t1_err2"
    assert result["data"][0]["status_message"] is None or isinstance(result["data"][0]["status_message"], str)


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


def test_app_factory_accepts_default_output_mode():
    """app_factory should accept and store the configured default_output_mode."""
    from langfuse_mcp.__main__ import OutputMode, app_factory

    app = app_factory(
        public_key="pk",
        secret_key="sk",
        host="https://cloud.langfuse.com",
        default_output_mode=OutputMode.FULL_JSON_FILE,
    )

    assert app is not None


def test_bind_default_output_mode_noop_for_compact():
    """_bind_default_output_mode returns the original function when default is COMPACT."""
    from langfuse_mcp.__main__ import OutputMode, _bind_default_output_mode, fetch_trace

    result = _bind_default_output_mode(fetch_trace, OutputMode.COMPACT)
    assert result is fetch_trace


def test_bind_default_output_mode_preserves_schema_description():
    """_bind_default_output_mode must preserve the FieldInfo description in the new signature."""
    import inspect

    from langfuse_mcp.__main__ import FieldInfo, OutputMode, _bind_default_output_mode, fetch_trace

    bound = _bind_default_output_mode(fetch_trace, OutputMode.FULL_JSON_FILE)
    sig = inspect.signature(bound)
    new_default = sig.parameters["output_mode"].default

    if FieldInfo is not None and isinstance(new_default, FieldInfo):
        assert new_default.default == "full_json_file"
        assert new_default.description is not None and len(new_default.description) > 0
        orig_sig = inspect.signature(fetch_trace)
        orig_desc = orig_sig.parameters["output_mode"].default.description
        assert new_default.description == orig_desc
    else:
        assert new_default == "full_json_file"


def test_bind_default_output_mode_does_not_mutate_original():
    """_bind_default_output_mode must not mutate the original module-level function."""
    import inspect

    from langfuse_mcp.__main__ import OutputMode, _bind_default_output_mode, fetch_trace

    orig_sig = inspect.signature(fetch_trace)
    orig_default = orig_sig.parameters["output_mode"].default

    _bind_default_output_mode(fetch_trace, OutputMode.FULL_JSON_FILE)

    after_sig = inspect.signature(fetch_trace)
    assert after_sig.parameters["output_mode"].default is orig_default


def test_explicit_compact_stays_compact(state):
    """Explicit output_mode='compact' must remain compact even when default is FULL_JSON_FILE."""
    from langfuse_mcp.__main__ import OutputMode, _bind_default_output_mode, fetch_traces

    bound = _bind_default_output_mode(fetch_traces, OutputMode.FULL_JSON_FILE)
    ctx = FakeContext(state)
    result = asyncio.run(
        bound(
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
            output_mode="compact",
        )
    )
    assert isinstance(result, dict)
    assert "data" in result


def test_omitted_output_mode_uses_configured_default(state):
    """When output_mode is omitted, the bound function should use the configured default."""
    import inspect

    from langfuse_mcp.__main__ import FieldInfo, OutputMode, _bind_default_output_mode, fetch_traces

    bound = _bind_default_output_mode(fetch_traces, OutputMode.FULL_JSON_FILE)
    sig = inspect.signature(bound)
    schema_default = sig.parameters["output_mode"].default

    if FieldInfo is not None and isinstance(schema_default, FieldInfo):
        assert schema_default.default == "full_json_file"
    else:
        assert schema_default == "full_json_file"

    ctx = FakeContext(state)
    result = asyncio.run(
        bound(
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
            output_mode="full_json_file",
        )
    )
    assert isinstance(result, dict)
    assert result["metadata"].get("file_path") is not None


def test_invalid_output_mode_falls_back_to_compact(state):
    """Invalid output_mode values must fall back to compact, not to the configured default."""
    from langfuse_mcp.__main__ import OutputMode, _ensure_output_mode

    assert _ensure_output_mode("bogus_value") == OutputMode.COMPACT


def test_ensure_output_mode_normalizes_valid_values():
    """_ensure_output_mode should normalize all valid string values."""
    from langfuse_mcp.__main__ import OutputMode, _ensure_output_mode

    assert _ensure_output_mode("compact") == OutputMode.COMPACT
    assert _ensure_output_mode("full_json_string") == OutputMode.FULL_JSON_STRING
    assert _ensure_output_mode("full_json_file") == OutputMode.FULL_JSON_FILE
    assert _ensure_output_mode(OutputMode.COMPACT) == OutputMode.COMPACT
