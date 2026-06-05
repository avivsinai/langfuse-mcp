"""Unit tests for langfuse-mcp tool functions."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from tests.fakes import FakeContext, FakeLangfuse, FakeLangfuseV4, FakeObservation


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
    return MCPState(langfuse_client=client, dump_dir=str(tmp_path))


def _observation_list_fake(client):
    """Return whichever fake namespace recorded the last list call (v3 vs v4 legacy)."""
    legacy = getattr(getattr(client.api, "legacy", None), "observations_v1", None)
    if legacy is not None and legacy.last_get_many_kwargs is not None:
        return legacy
    return client.api.observations


def _observation_get_fake(client):
    """Return whichever fake namespace recorded the last single-fetch call (v3 vs v4 legacy)."""
    legacy = getattr(getattr(client.api, "legacy", None), "observations_v1", None)
    if legacy is not None and legacy.last_get_kwargs is not None:
        return legacy
    return client.api.observations


def _seed_route_decision_observations(client):
    """Add router-neutral route-decision observations to a fake Langfuse client."""
    now = datetime(2026, 5, 19, 11, 6, 34, tzinfo=timezone.utc)
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
    start = datetime(2026, 5, 29, 10, 45, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 29, 10, 45, 5, 78000, tzinfo=timezone.utc)
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
    assert state.langfuse_client.api.trace.last_get_kwargs == {"trace_id": "trace_1"}


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


def test_fetch_observation(observation_state):
    """fetch_observation should resolve via the v3 namespace or the v4 legacy_v1 fallback."""
    from langfuse_mcp.__main__ import fetch_observation

    ctx = FakeContext(observation_state)
    result = asyncio.run(fetch_observation(ctx, observation_id="obs_1", output_mode="compact"))
    assert result["data"]["id"] == "obs_1"

    namespace = _observation_get_fake(observation_state.langfuse_client)
    last = namespace.last_get_kwargs
    assert last is not None
    assert last["observation_id"] == "obs_1"


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
    """find_low_confidence_route_decisions should flag confidence threshold and callable=false cases."""
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
