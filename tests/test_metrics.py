"""Unit tests for the metrics tools (query_metrics, get_metrics_schema) and compat dispatch."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from tests.fakes import FakeContext, FakeLangfuse, FakeLangfuseV4


def _state(tmp_path, client=None):
    """Create MCP state backed by a fake Langfuse client."""
    from langfuse_mcp.__main__ import MCPState

    return MCPState(langfuse_client=client or FakeLangfuse(), dump_dir=str(tmp_path))


def test_metrics_tools_registered_and_read_only():
    """Metrics tools should be in the metrics group and must not be write tools."""
    from langfuse_mcp.__main__ import TOOL_GROUPS, WRITE_TOOLS

    assert TOOL_GROUPS["metrics"] == ["query_metrics", "get_metrics_schema"]
    assert "query_metrics" not in WRITE_TOOLS
    assert "get_metrics_schema" not in WRITE_TOOLS


@pytest.mark.parametrize("client_factory", [FakeLangfuse, FakeLangfuseV4], ids=["v3", "v4"])
def test_query_metrics_builds_v2_query(tmp_path, client_factory):
    """query_metrics should build a faithful v2 query object and return the response rows."""
    from langfuse_mcp.__main__ import query_metrics

    client = client_factory()
    state = _state(tmp_path, client)
    ctx = FakeContext(state)

    result = asyncio.run(
        query_metrics(
            ctx,
            view="observations",
            metrics=[{"measure": "totalCost", "aggregation": "sum"}, {"measure": "latency", "aggregation": "p95"}],
            dimensions=["providedModelName"],
            filters=[{"column": "userId", "operator": "=", "value": "u1", "type": "string"}],
            age=60,
        )
    )

    # Response surfaces the canned rows plus a descriptive metadata block.
    assert [row["providedModelName"] for row in result["data"]] == ["claude-opus-4-8", "claude-sonnet-4-6"]
    assert result["metadata"]["view"] == "observations"
    assert result["metadata"]["metrics_endpoint"] == "v2"
    assert result["metadata"]["item_count"] == 2

    # The query string sent to the SDK is a faithful v2 query object.
    sent = json.loads(client.api.metrics_v_2.last_query)
    assert sent["view"] == "observations"
    assert sent["metrics"] == [
        {"measure": "totalCost", "aggregation": "sum"},
        {"measure": "latency", "aggregation": "p95"},
    ]
    assert sent["dimensions"] == [{"field": "providedModelName"}]
    assert sent["filters"] == [{"column": "userId", "operator": "=", "value": "u1", "type": "string"}]
    # age=60 -> a 60-minute window ending now.
    start = datetime.fromisoformat(sent["fromTimestamp"])
    end = datetime.fromisoformat(sent["toTimestamp"])
    assert start < end
    assert abs((end - start).total_seconds() - 60 * 60) < 5


def test_query_metrics_explicit_timerange_overrides_age(tmp_path):
    """Explicit from/to timestamps should be used verbatim and override age."""
    from langfuse_mcp.__main__ import query_metrics

    client = FakeLangfuse()
    ctx = FakeContext(_state(tmp_path, client))

    asyncio.run(
        query_metrics(
            ctx,
            view="scores-numeric",
            metrics=[{"measure": "value", "aggregation": "avg"}],
            age=30,
            from_timestamp="2026-01-01T00:00:00+00:00",
            to_timestamp="2026-01-02T00:00:00+00:00",
            time_granularity="day",
        )
    )

    sent = json.loads(client.api.metrics_v_2.last_query)
    assert sent["fromTimestamp"].startswith("2026-01-01T00:00:00")
    assert sent["toTimestamp"].startswith("2026-01-02T00:00:00")
    assert sent["timeDimension"] == {"granularity": "day"}


def test_query_metrics_rejects_high_cardinality_dimension(tmp_path):
    """High-cardinality fields must not be accepted as grouping dimensions."""
    from langfuse_mcp.__main__ import query_metrics

    ctx = FakeContext(_state(tmp_path))
    with pytest.raises(ValueError, match="high-cardinality"):
        asyncio.run(
            query_metrics(
                ctx,
                view="observations",
                metrics=[{"measure": "count", "aggregation": "count"}],
                dimensions=["userId"],
            )
        )


def test_query_metrics_rejects_invalid_aggregation(tmp_path):
    """An unsupported aggregation function should raise."""
    from langfuse_mcp.__main__ import query_metrics

    ctx = FakeContext(_state(tmp_path))
    with pytest.raises(ValueError, match="aggregation"):
        asyncio.run(
            query_metrics(
                ctx,
                view="observations",
                metrics=[{"measure": "totalCost", "aggregation": "median"}],
            )
        )


def test_query_metrics_requires_at_least_one_metric(tmp_path):
    """An empty metrics list should raise."""
    from langfuse_mcp.__main__ import query_metrics

    ctx = FakeContext(_state(tmp_path))
    with pytest.raises(ValueError, match="non-empty"):
        asyncio.run(query_metrics(ctx, view="observations", metrics=[]))


def test_query_metrics_404_surfaces_cloud_only(tmp_path):
    """A 404 from the endpoint should be re-raised with Cloud-only guidance."""
    from langfuse_mcp.__main__ import query_metrics

    class _ApiError(Exception):
        status_code = 404

    class _Boom:
        def metrics(self, *, query):
            raise _ApiError()

    class _Client:
        def __init__(self):
            self.api = SimpleNamespace(metrics_v_2=_Boom())

        def flush(self):  # pragma: no cover - cleanup shim
            pass

        def shutdown(self):  # pragma: no cover - cleanup shim
            pass

    ctx = FakeContext(_state(tmp_path, _Client()))
    with pytest.raises(RuntimeError, match="Cloud-only"):
        asyncio.run(
            query_metrics(
                ctx,
                view="observations",
                metrics=[{"measure": "count", "aggregation": "count"}],
            )
        )


def test_get_metrics_schema_lists_views_and_aggregations(tmp_path):
    """The schema doc should enumerate the three views and the aggregation set."""
    from langfuse_mcp.__main__ import get_metrics_schema

    ctx = FakeContext(_state(tmp_path))
    schema = asyncio.run(get_metrics_schema(ctx))

    for view in ("observations", "scores-numeric", "scores-categorical"):
        assert view in schema
    for aggregation in ("sum", "avg", "p95", "histogram"):
        assert aggregation in schema
    # High-cardinality guidance must be documented so agents avoid 400s.
    assert "high-cardinality" in schema.lower()


def test_get_metrics_method_prefers_v2_then_legacy_then_none():
    """Capability dispatch prefers v2, falls back to legacy, and degrades to None."""
    from langfuse_mcp import _compat

    class _Ns:
        def metrics(self, *, query):  # pragma: no cover - not invoked
            return None

    both = SimpleNamespace(api=SimpleNamespace(metrics_v_2=_Ns(), metrics=_Ns()))
    method, mode = _compat.get_metrics_method(both)
    assert mode == "v2"

    legacy_only = SimpleNamespace(api=SimpleNamespace(metrics=_Ns()))
    method, mode = _compat.get_metrics_method(legacy_only)
    assert mode == "legacy"

    neither = SimpleNamespace(api=SimpleNamespace())
    assert _compat.get_metrics_method(neither) is None
