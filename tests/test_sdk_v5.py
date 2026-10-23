"""Langfuse Python SDK 5 surface (langfuse 5.0.x) on the in-memory fakes.

SDK 5 deletes the clients for the routes Langfuse Cloud removes on 2026-11-16: ``api.legacy``,
``api.trace.get``/``list``, ``api.sessions``, ``api.scores_v3``, ``api.dataset_run_items`` and
``api.datasets.get_runs``/``get_run``/``delete_run``. Scores API v3 moves to ``api.scores.get_many``.
These tests pin that every tool reaches the replacement API or a named error, never an
``AttributeError`` or a ``TypeError`` from calling a v3 method with v2 arguments.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from tests.fakes import (
    FakeContext,
    FakeDataset,
    FakeDatasetItem,
    FakeDatasetRun,
    FakeDatasetRunItem,
    FakeHTTPError,
    FakeLangfuseV4,
    FakeLangfuseV5,
)


@pytest.fixture()
def v5_state(tmp_path):
    """Return a v5 client with a dataset, one experiment and its item linked to ``trace_1``."""
    from langfuse_mcp.__main__ import MCPState

    client = FakeLangfuseV5()
    now = datetime.now(timezone.utc) - timedelta(minutes=5)
    dataset = FakeDataset(id="dataset_eval", name="eval", created_at=now, updated_at=now)
    client._store.datasets[dataset.name] = dataset
    client._store.dataset_items["item_1"] = FakeDatasetItem(id="item_1", dataset_id=dataset.id, input={"q": 1})
    client._store.dataset_runs[(dataset.id, "baseline")] = FakeDatasetRun(
        id="experiment_1",
        dataset_id=dataset.id,
        dataset_name=dataset.name,
        name="baseline",
        created_at=now + timedelta(minutes=1),
        updated_at=now + timedelta(minutes=2),
    )
    client._store.dataset_run_items["run_item_1"] = FakeDatasetRunItem(
        id="run_item_1",
        dataset_id=dataset.id,
        dataset_item_id="item_1",
        run_name="baseline",
        trace_id="trace_1",
        created_at=now + timedelta(minutes=1),
    )
    client._store.observations["obs_1"].trace_id = "trace_1"
    return MCPState(langfuse_client=client, dump_dir=str(tmp_path))


def _call(tool: Any, state: Any, **kwargs: Any) -> Any:
    return asyncio.run(tool(FakeContext(state), **kwargs))


def test_fake_matches_the_sdk5_surface():
    """The fake lacks exactly the namespaces SDK 5 removed, so the tests below mean something."""
    api = FakeLangfuseV5().api
    for name in ("legacy", "sessions", "scores_v3", "dataset_run_items"):
        assert not hasattr(api, name)
    for name in ("get", "list"):
        assert not hasattr(api.trace, name)
    for name in ("get_runs", "get_run", "delete_run"):
        assert not hasattr(api.datasets, name)
    assert not hasattr(api.scores, "get_by_id")


def test_compat_finds_scores_v3_under_scores_get_many_on_sdk5():
    """SDK 5's cursor-based ``scores.get_many`` is the v3 reader and never the v2 page reader."""
    from langfuse_mcp import _compat

    v5 = FakeLangfuseV5()
    assert _compat.get_scores_v3_method(v5) == v5.api.scores.get_many
    assert _compat.get_score_list_method(v5.api.scores) is None

    v4 = FakeLangfuseV4()
    assert _compat.get_scores_v3_method(v4) == v4.api.scores_v3.get_many_v3
    assert _compat.get_score_list_method(v4.api.scores) == v4.api.scores.get_many


def test_get_sdk_method_returns_none_for_removed_resources():
    """Missing namespaces and methods resolve to ``None`` instead of raising."""
    from langfuse_mcp import _compat

    v5 = FakeLangfuseV5()
    assert _compat.get_sdk_method(v5, "trace.list") is None
    assert _compat.get_sdk_method(v5, "sessions.list") is None
    assert _compat.get_sdk_method(v5, "dataset_run_items.create") is None
    assert _compat.get_sdk_method(v5, "trace.delete_multiple") == v5.api.trace.delete_multiple


def test_list_scores_reads_v3_through_scores_get_many(v5_state):
    """Filters map to v3 and rows keep the v2 shape."""
    from langfuse_mcp.__main__ import SCORES_V3_FIELDS, list_scores_v2

    client = v5_state.langfuse_client
    result = _call(list_scores_v2, v5_state, score_ids="score_1", name="quality", limit=10)

    call = client.api.scores.calls[-1]
    assert call["id"] == "score_1" and call["name"] == "quality" and call["fields"] == SCORES_V3_FIELDS
    [score] = result["data"]
    assert score["id"] == "score_1" and score["trace_id"] == "trace_1"


def test_list_scores_v2_only_filter_names_the_sdk_removal(v5_state):
    """user_id and trace_tags have no v3 form and SDK 5 has no v2 reader."""
    from langfuse_mcp.__main__ import list_scores_v2

    with pytest.raises(RuntimeError, match="ERR_LANGFUSE_SCORES_V2_ONLY_FILTER.*SDK 5"):
        _call(list_scores_v2, v5_state, user_id="user_a")
    assert v5_state.langfuse_client.api.scores.calls == []


def test_get_score_reads_v3(v5_state):
    """A single score comes from v3 by id."""
    from langfuse_mcp.__main__ import get_score_v2

    result = _call(get_score_v2, v5_state, score_id="score_1")

    assert result["data"]["id"] == "score_1"
    assert v5_state.langfuse_client.api.scores.calls[-1]["id"] == "score_1"


def test_fetch_trace_includes_v3_scores(v5_state):
    """``fetch_trace`` keeps attaching scores once ``scores_v3`` is gone."""
    from langfuse_mcp.__main__ import fetch_trace

    trace = _call(fetch_trace, v5_state, trace_id="trace_1", output_mode="full")["data"]

    assert trace["id"] == "trace_1"
    assert [score["id"] for score in trace["scores"]] == ["score_1"]


def test_trace_reads_on_an_old_server_name_the_removed_sdk_route(v5_state, monkeypatch):
    """If v2 answers 404, the legacy fallback reports the missing SDK method, not an AttributeError."""
    from langfuse_mcp.__main__ import LegacyRouteUnavailableError, fetch_traces

    def gone(**kwargs: Any) -> Any:
        raise FakeHTTPError(404, "gone")

    monkeypatch.setattr(v5_state.langfuse_client.api.observations, "get_many", gone)
    with pytest.raises(LegacyRouteUnavailableError, match="api.trace.list"):
        _call(fetch_traces, v5_state, age=60, output_mode="compact")


def test_dataset_run_reads_use_experiments(v5_state):
    """Run listing and run items come from the experiments API."""
    from langfuse_mcp.__main__ import get_dataset_run, list_dataset_runs

    runs = _call(list_dataset_runs, v5_state, dataset_name="eval")
    run = _call(get_dataset_run, v5_state, dataset_name="eval", run_name="baseline")

    assert [row["id"] for row in runs["data"]] == ["experiment_1"]
    assert [item["trace_id"] for item in run["data"]["dataset_run_items"]] == ["trace_1"]


def test_dataset_run_reads_on_an_old_server_report_unavailable(v5_state, monkeypatch):
    """Experiments 404 plus no legacy SDK client is the documented read-unavailable error."""
    from langfuse_mcp.__main__ import list_dataset_runs

    def gone(**kwargs: Any) -> Any:
        raise FakeHTTPError(404, "gone")

    monkeypatch.setattr(v5_state.langfuse_client.api.experiments, "list", gone)
    with pytest.raises(RuntimeError, match="ERR_LANGFUSE_EXPERIMENTS_READ_UNAVAILABLE"):
        _call(list_dataset_runs, v5_state, dataset_name="eval")


def test_create_run_item_reports_removed_link_api(v5_state):
    """SDK 5 has no run-item create client; the tool returns the documented error."""
    from langfuse_mcp.__main__ import create_dataset_run_item

    with pytest.raises(RuntimeError, match="ERR_LANGFUSE_RUN_ITEM_CREATE_REMOVED"):
        _call(create_dataset_run_item, v5_state, run_name="baseline", dataset_item_id="item_1")


def test_delete_run_requires_opt_in_then_deletes_traces(v5_state):
    """No legacy DELETE client: without opt-in nothing is deleted; with it the run's traces go."""
    from langfuse_mcp.__main__ import delete_dataset_run

    client = v5_state.langfuse_client
    with pytest.raises(RuntimeError, match="ERR_LANGFUSE_RUN_DELETE_REQUIRES_TRACES"):
        _call(delete_dataset_run, v5_state, dataset_name="eval", run_name="baseline")
    assert client.api.trace.delete_multiple_calls == []

    result = _call(delete_dataset_run, v5_state, dataset_name="eval", run_name="baseline", delete_traces=True)

    assert result["metadata"]["deleted_trace_count"] == 1
    assert client.api.trace.delete_multiple_calls == [["trace_1"]]
