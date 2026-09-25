"""Dataset-run compatibility over the cursor-based experiments API."""

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
)


@pytest.fixture()
def state(tmp_path):
    """Return a v4 client with a dataset, experiment, and two in-window items."""
    from langfuse_mcp.__main__ import MCPState

    client = FakeLangfuseV4()
    now = datetime.now(timezone.utc) - timedelta(minutes=5)
    dataset = FakeDataset(id="dataset_eval", name="eval", created_at=now, updated_at=now)
    client._store.datasets[dataset.name] = dataset
    client._store.dataset_items["item_1"] = FakeDatasetItem(id="item_1", dataset_id=dataset.id, input={"q": 1})
    client._store.dataset_runs[(dataset.id, "baseline")] = FakeDatasetRun(
        id="experiment_1",
        dataset_id=dataset.id,
        dataset_name=dataset.name,
        name="baseline",
        description="Baseline",
        metadata={"owner": "eval"},
        created_at=now + timedelta(minutes=1),
        updated_at=now + timedelta(minutes=2),
    )
    for number in (1, 2):
        client._store.dataset_run_items[f"run_item_{number}"] = FakeDatasetRunItem(
            id=f"run_item_{number}",
            dataset_id=dataset.id,
            dataset_item_id="item_1",
            run_name="baseline",
            trace_id="trace_1",
            created_at=now + timedelta(minutes=number),
        )
    client._store.observations["obs_1"].trace_id = "trace_1"
    return MCPState(langfuse_client=client, dump_dir=str(tmp_path))


def _call(tool: Any, state: Any, **kwargs: Any) -> Any:
    """Call a dataset-run tool with the fake MCP context."""
    return asyncio.run(tool(FakeContext(state), **kwargs))


def test_experiments_fake_requires_time_bounds(state):
    """Both fake endpoints reject a request without the required time bound."""
    experiments = state.langfuse_client.api.experiments
    with pytest.raises(FakeHTTPError, match="fromStartTime is required"):
        experiments.list()
    with pytest.raises(FakeHTTPError, match="fromStartTime is required"):
        experiments.list_items()


def test_list_runs_uses_experiments_and_dataset_start(state):
    """A run listing resolves the dataset and returns cursor metadata."""
    from langfuse_mcp.__main__ import list_dataset_runs

    client = state.langfuse_client
    created = client._store.datasets["eval"].created_at
    client._store.dataset_runs[("dataset_eval", "too-old")] = FakeDatasetRun(
        id="old_experiment",
        dataset_id="dataset_eval",
        dataset_name="eval",
        name="too-old",
        created_at=created - timedelta(seconds=1),
    )
    result = _call(list_dataset_runs, state, dataset_name="eval", page=1, limit=1)

    assert [row["id"] for row in result["data"]] == ["experiment_1"]
    assert result["data"][0]["dataset_name"] == "eval"
    assert result["metadata"]["total"] is None
    assert client.api.datasets.last_get_runs_kwargs is None
    assert client.api.experiments.list_calls[-1]["dataset_id"] == "dataset_eval"
    assert client.api.experiments.list_calls[-1]["from_start_time"] == client._store.datasets["eval"].created_at


def test_get_run_rebuilds_items_and_excludes_old_items(state):
    """The combined result keeps equivalent IDs and excludes an item before dataset creation."""
    from langfuse_mcp.__main__ import get_dataset_run

    client = state.langfuse_client
    old = client._store.dataset_run_items["run_item_1"]
    client._store.dataset_run_items["old"] = FakeDatasetRunItem(
        id="old",
        dataset_id=old.dataset_id,
        dataset_item_id=old.dataset_item_id,
        run_name=old.run_name,
        trace_id="old_trace",
        created_at=client._store.datasets["eval"].created_at - timedelta(seconds=1),
    )

    result = _call(get_dataset_run, state, dataset_name="eval", run_name="baseline", output_mode="compact")

    assert result["data"]["name"] == "baseline"
    assert {item["id"] for item in result["data"]["items"]} == {"run_item_1", "run_item_2"}
    assert result["data"]["dataset_run_items"] == result["data"]["items"]
    assert all(item["dataset_item_id"] == "item_1" and item["run_name"] == "baseline" for item in result["data"]["items"])
    assert all(item["dataset_run_id"] == "experiment_1" and item["dataset_run_name"] == "baseline" for item in result["data"]["items"])
    assert result["data"]["items"][0]["input"] == {"q": 1}
    assert client.api.datasets.last_get_run_kwargs is None


def test_run_lookup_filters_plain_name_on_server(state):
    """An ordinary name keeps the server filter to avoid scanning every run."""
    from langfuse_mcp.__main__ import get_dataset_run

    client = state.langfuse_client
    _call(get_dataset_run, state, dataset_name="eval", run_name="baseline")

    assert client.api.experiments.list_calls[-1]["name"] == "baseline"


def test_list_run_items_walks_cursor_and_filters_time(state):
    """A page sees only matching items and carries the next cursor through the tool."""
    from langfuse_mcp.__main__ import list_dataset_run_items

    client = state.langfuse_client
    client._store.dataset_run_items["old"] = FakeDatasetRunItem(
        id="old",
        dataset_id="dataset_eval",
        dataset_item_id="item_1",
        run_name="baseline",
        created_at=client._store.datasets["eval"].created_at - timedelta(seconds=1),
    )

    first = _call(list_dataset_run_items, state, dataset_id="dataset_eval", run_name="baseline", page=1, limit=1)
    second = _call(list_dataset_run_items, state, dataset_id="dataset_eval", run_name="baseline", page=2, limit=1)

    assert [row["id"] for row in first["data"]] == ["run_item_2"]
    assert [row["id"] for row in second["data"]] == ["run_item_1"]
    assert first["metadata"]["next_page"] == 2
    assert "next_page" not in second["metadata"]
    assert client.api.dataset_run_items.last_list_kwargs is None
    assert client.api.experiments.item_calls[-1]["from_start_time"] == client._store.datasets["eval"].created_at


@pytest.mark.parametrize("tool_name", ["get_dataset_run", "list_dataset_run_items"])
def test_run_reads_resolve_comma_name_to_exact_experiment(state, monkeypatch, tool_name):
    """A comma in a run name cannot select the two names on either side of it."""
    from langfuse_mcp import __main__ as server

    client = state.langfuse_client
    run = client._store.dataset_runs.pop(("dataset_eval", "baseline"))
    run.name = "a,b"
    client._store.dataset_runs[("dataset_eval", "a,b")] = run
    for item in client._store.dataset_run_items.values():
        item.run_name = "a,b"
    other = FakeDatasetRun(
        id="experiment_other",
        dataset_id="dataset_eval",
        dataset_name="eval",
        name="a",
        created_at=client._store.datasets["eval"].created_at + timedelta(minutes=1),
    )
    client._store.dataset_runs[("dataset_eval", "a")] = other
    client._store.dataset_run_items["other_item"] = FakeDatasetRunItem(
        id="other_item",
        dataset_id="dataset_eval",
        dataset_item_id="item_1",
        run_name="a",
        trace_id="other_trace",
        created_at=other.created_at,
    )
    original_list = client.api.experiments.list
    original_items = client.api.experiments.list_items

    def comma_run_list(**kwargs: Any) -> Any:
        if kwargs.get("name") == "a,b":
            kwargs["name"] = "a"  # The server parses comma-separated names, not one literal name.
        return original_list(**kwargs)

    def comma_list(**kwargs: Any) -> Any:
        if kwargs.get("experiment_name") == "a,b":
            kwargs.pop("experiment_name")
            kwargs.pop("experiment_id", None)
        return original_items(**kwargs)

    monkeypatch.setattr(client.api.experiments, "list", comma_run_list)
    monkeypatch.setattr(client.api.experiments, "list_items", comma_list)
    args = {
        "get_dataset_run": {"dataset_name": "eval", "run_name": "a,b"},
        "list_dataset_run_items": {"dataset_id": "dataset_eval", "run_name": "a,b"},
    }
    result = _call(getattr(server, tool_name), state, **args[tool_name])

    rows = result["data"]["items"] if tool_name == "get_dataset_run" else result["data"]
    assert {item["id"] for item in rows} == {"run_item_1", "run_item_2"}
    assert client.api.experiments.list_calls[-1]["name"] is None
    assert client.api.experiments.item_calls[-1]["experiment_id"] == "experiment_1"


@pytest.mark.parametrize("tool_name", ["get_dataset_run", "list_dataset_run_items"])
def test_read_rejects_items_from_another_experiment(state, monkeypatch, tool_name):
    """An ignored item filter cannot mix run data in either read tool."""
    from langfuse_mcp import __main__ as server

    client = state.langfuse_client
    original = client.api.experiments.list_items

    def mixed(**kwargs: Any) -> Any:
        response = original(**kwargs)
        response.data.append({"id": "foreign", "experiment_id": "other", "trace_id": "foreign_trace"})
        return response

    monkeypatch.setattr(client.api.experiments, "list_items", mixed)
    args = {
        "get_dataset_run": {"dataset_name": "eval", "run_name": "baseline"},
        "list_dataset_run_items": {"dataset_id": "dataset_eval", "run_name": "baseline"},
    }
    with pytest.raises(RuntimeError, match="ERR_LANGFUSE_EXPERIMENT_ITEM_SCOPE"):
        _call(getattr(server, tool_name), state, **args[tool_name])


@pytest.mark.parametrize("bad_id", [None, "other"])
def test_delete_rejects_mixed_experiment_items_before_any_trace_delete(state, monkeypatch, bad_id):
    """A broken server filter cannot delete traces from another experiment."""
    from langfuse_mcp.__main__ import delete_dataset_run

    client = state.langfuse_client
    created = client._store.datasets["eval"].created_at + timedelta(minutes=1)
    client._store.dataset_runs[("dataset_eval", "other")] = FakeDatasetRun(
        id="other", dataset_id="dataset_eval", dataset_name="eval", name="other", created_at=created
    )
    client._store.dataset_run_items["foreign"] = FakeDatasetRunItem(
        id="foreign", dataset_id="dataset_eval", dataset_item_id="item_1", run_name="other", trace_id="foreign_trace", created_at=created
    )
    original = client.api.experiments.list_items

    def missing(*args: Any, **kwargs: Any) -> Any:
        raise FakeHTTPError(404, "gone")

    def mixed(**kwargs: Any) -> Any:
        kwargs.pop("experiment_id")  # Simulate a server that silently ignores this filter.
        response = original(**kwargs)
        if bad_id is None:
            next(row for row in response.data if row["id"] == "foreign").pop("experiment_id")
        return response

    monkeypatch.setattr(client.api.datasets, "delete_run", missing)
    monkeypatch.setattr(client.api.experiments, "list_items", mixed)
    with pytest.raises(RuntimeError, match="ERR_LANGFUSE_EXPERIMENT_ITEM_SCOPE"):
        _call(delete_dataset_run, state, dataset_name="eval", run_name="baseline", delete_traces=True)
    assert client.api.trace.delete_multiple_calls == []
    assert "trace_1" in client._store.traces


def test_delete_rejects_wrong_dataset_on_matching_experiment(state, monkeypatch):
    """A matching experiment ID does not allow an item from another dataset."""
    from langfuse_mcp.__main__ import delete_dataset_run

    client = state.langfuse_client
    original = client.api.experiments.list_items

    def missing(*args: Any, **kwargs: Any) -> Any:
        raise FakeHTTPError(404, "gone")

    def wrong_dataset(**kwargs: Any) -> Any:
        response = original(**kwargs)
        response.data[0]["experiment_dataset_id"] = "dataset_other"
        return response

    monkeypatch.setattr(client.api.datasets, "delete_run", missing)
    monkeypatch.setattr(client.api.experiments, "list_items", wrong_dataset)
    with pytest.raises(RuntimeError, match="ERR_LANGFUSE_EXPERIMENT_ITEM_SCOPE"):
        _call(delete_dataset_run, state, dataset_name="eval", run_name="baseline", delete_traces=True)
    assert client.api.trace.delete_multiple_calls == []


@pytest.mark.parametrize("status", [404, 405])
@pytest.mark.parametrize("tool_name", ["list_dataset_runs", "get_dataset_run", "list_dataset_run_items"])
def test_experiment_route_missing_falls_back_to_legacy(state, monkeypatch, status, tool_name):
    """Only a missing experiment route sends a read to the legacy API."""
    from langfuse_mcp import __main__ as server

    client = state.langfuse_client

    def missing(**kwargs: Any) -> Any:
        raise FakeHTTPError(status, "not served")

    monkeypatch.setattr(client.api.experiments, "list", missing)
    monkeypatch.setattr(client.api.experiments, "list_items", missing)
    arguments = {
        "list_dataset_runs": {"dataset_name": "eval", "page": 1, "limit": 10},
        "get_dataset_run": {"dataset_name": "eval", "run_name": "baseline"},
        "list_dataset_run_items": {"dataset_id": "dataset_eval", "run_name": "baseline", "page": 1, "limit": 10},
    }
    result = _call(getattr(server, tool_name), state, **arguments[tool_name])

    assert result["data"]
    assert (
        client.api.datasets.last_get_runs_kwargs is not None
        or client.api.datasets.last_get_run_kwargs is not None
        or client.api.dataset_run_items.last_list_kwargs is not None
    )


@pytest.mark.parametrize("tool_name", ["list_dataset_runs", "get_dataset_run", "list_dataset_run_items"])
def test_experiment_server_error_does_not_fall_back(state, monkeypatch, tool_name):
    """A server error from experiments propagates without reading stale routes."""
    from langfuse_mcp import __main__ as server

    client = state.langfuse_client

    def error(**kwargs: Any) -> Any:
        raise FakeHTTPError(500, "failed")

    monkeypatch.setattr(client.api.experiments, "list", error)
    monkeypatch.setattr(client.api.experiments, "list_items", error)
    arguments = {
        "list_dataset_runs": {"dataset_name": "eval"},
        "get_dataset_run": {"dataset_name": "eval", "run_name": "baseline"},
        "list_dataset_run_items": {"dataset_id": "dataset_eval", "run_name": "baseline"},
    }
    with pytest.raises(FakeHTTPError, match="HTTP 500"):
        _call(getattr(server, tool_name), state, **arguments[tool_name])
    assert client.api.datasets.last_get_runs_kwargs is None
    assert client.api.datasets.last_get_run_kwargs is None
    assert client.api.dataset_run_items.last_list_kwargs is None


def test_get_run_falls_back_when_only_experiment_items_are_missing(state, monkeypatch):
    """The second read of a combined run can trigger the legacy fallback."""
    from langfuse_mcp.__main__ import get_dataset_run

    client = state.langfuse_client

    def missing(**kwargs: Any) -> Any:
        raise FakeHTTPError(405, "not served")

    monkeypatch.setattr(client.api.experiments, "list_items", missing)
    result = _call(get_dataset_run, state, dataset_name="eval", run_name="baseline")

    assert result["data"]["id"] == "experiment_1"
    assert client.api.datasets.last_get_run_kwargs is not None


@pytest.mark.parametrize("tool_name", ["list_dataset_runs", "get_dataset_run", "list_dataset_run_items"])
def test_old_sdk_and_removed_legacy_route_explain_upgrade(state, monkeypatch, tool_name):
    """Without experiment methods, a removed legacy route names the minimum SDK."""
    from langfuse_mcp import __main__ as server

    client = state.langfuse_client
    monkeypatch.setattr(client.api, "experiments", None)

    def missing(*args: Any, **kwargs: Any) -> Any:
        raise FakeHTTPError(404, "gone")

    monkeypatch.setattr(client.api.datasets, "get_runs", missing)
    monkeypatch.setattr(client.api.datasets, "get_run", missing)
    monkeypatch.setattr(client.api.dataset_run_items, "list", missing)
    arguments = {
        "list_dataset_runs": {"dataset_name": "eval"},
        "get_dataset_run": {"dataset_name": "eval", "run_name": "baseline"},
        "list_dataset_run_items": {"dataset_id": "dataset_eval", "run_name": "baseline"},
    }
    with pytest.raises(RuntimeError, match="ERR_LANGFUSE_EXPERIMENTS_SDK_UPGRADE.*>=4.13.1"):
        _call(getattr(server, tool_name), state, **arguments[tool_name])


def test_both_read_routes_missing_explain_server_state(state, monkeypatch):
    """An installed experiments SDK does not give a misleading upgrade hint for two missing routes."""
    from langfuse_mcp.__main__ import list_dataset_runs

    client = state.langfuse_client

    def missing(*args: Any, **kwargs: Any) -> Any:
        raise FakeHTTPError(404, "gone")

    monkeypatch.setattr(client.api.experiments, "list", missing)
    monkeypatch.setattr(client.api.datasets, "get_runs", missing)
    with pytest.raises(RuntimeError, match="ERR_LANGFUSE_EXPERIMENTS_READ_UNAVAILABLE"):
        _call(list_dataset_runs, state, dataset_name="eval")


def test_create_run_item_reports_removed_link_api(state, monkeypatch):
    """A removed POST route says an existing trace cannot be linked through this API."""
    from langfuse_mcp.__main__ import create_dataset_run_item

    def missing(**kwargs: Any) -> Any:
        raise FakeHTTPError(404, "gone")

    monkeypatch.setattr(state.langfuse_client.api.dataset_run_items, "create", missing)
    with pytest.raises(RuntimeError, match="ERR_LANGFUSE_RUN_ITEM_CREATE_REMOVED.*existing trace"):
        _call(create_dataset_run_item, state, run_name="baseline", dataset_item_id="item_1")


def test_delete_without_opt_in_never_deletes_traces(state, monkeypatch):
    """A missing legacy DELETE leaves the run and trace data intact by default."""
    from langfuse_mcp.__main__ import delete_dataset_run

    client = state.langfuse_client

    def missing(*args: Any, **kwargs: Any) -> Any:
        raise FakeHTTPError(404, "gone")

    monkeypatch.setattr(client.api.datasets, "delete_run", missing)
    with pytest.raises(RuntimeError, match="ERR_LANGFUSE_RUN_DELETE_REQUIRES_TRACES.*delete_traces=True"):
        _call(delete_dataset_run, state, dataset_name="eval", run_name="baseline")
    assert client.api.trace.delete_multiple_calls == []
    assert "trace_1" in client._store.traces
    assert ("dataset_eval", "baseline") in client._store.dataset_runs


def test_delete_rejects_truthy_text_instead_of_treating_it_as_opt_in(state):
    """A direct call with the string 'false' never authorizes trace deletion."""
    from langfuse_mcp.__main__ import delete_dataset_run

    with pytest.raises(TypeError, match="delete_traces must be a boolean"):
        _call(delete_dataset_run, state, dataset_name="eval", run_name="baseline", delete_traces="false")
    assert state.langfuse_client.api.trace.delete_multiple_calls == []


def test_delete_legacy_server_error_does_not_delete_traces(state, monkeypatch):
    """A legacy 500 is a failure, not permission to switch deletion methods."""
    from langfuse_mcp.__main__ import delete_dataset_run

    client = state.langfuse_client

    def failed(*args: Any, **kwargs: Any) -> Any:
        raise FakeHTTPError(500, "failed")

    monkeypatch.setattr(client.api.datasets, "delete_run", failed)
    with pytest.raises(FakeHTTPError, match="HTTP 500"):
        _call(delete_dataset_run, state, dataset_name="eval", run_name="baseline", delete_traces=True)
    assert client.api.trace.delete_multiple_calls == []


def test_delete_with_opt_in_deduplicates_trace_ids(state, monkeypatch):
    """The explicit replacement deletes each distinct trace once."""
    from langfuse_mcp.__main__ import delete_dataset_run

    client = state.langfuse_client

    def missing(*args: Any, **kwargs: Any) -> Any:
        raise FakeHTTPError(404, "gone")

    monkeypatch.setattr(client.api.datasets, "delete_run", missing)
    result = _call(delete_dataset_run, state, dataset_name="eval", run_name="baseline", delete_traces=True)

    assert result["metadata"]["deleted_trace_count"] == 1
    assert client.api.trace.delete_multiple_calls == [["trace_1"]]
    assert "trace_1" not in client._store.traces


def test_delete_batches_at_one_thousand_trace_ids(state, monkeypatch):
    """The replacement collects all pages before issuing bounded delete batches."""
    from langfuse_mcp.__main__ import delete_dataset_run

    client = state.langfuse_client
    client._store.dataset_run_items.clear()
    start = client._store.datasets["eval"].created_at + timedelta(minutes=2)
    for index in range(1001):
        client._store.dataset_run_items[f"row_{index}"] = FakeDatasetRunItem(
            id=f"row_{index}",
            dataset_id="dataset_eval",
            dataset_item_id="item_1",
            run_name="baseline",
            trace_id=f"trace_{index}",
            created_at=start,
        )

    def missing(*args: Any, **kwargs: Any) -> Any:
        raise FakeHTTPError(405, "gone")

    monkeypatch.setattr(client.api.datasets, "delete_run", missing)
    result = _call(delete_dataset_run, state, dataset_name="eval", run_name="baseline", delete_traces=True)

    assert result["metadata"]["deleted_trace_count"] == 1001
    assert [len(batch) for batch in client.api.trace.delete_multiple_calls] == [1000, 1]
    assert len(client.api.experiments.item_calls) == 11


def test_missing_dataset_created_at_uses_fixed_early_date(state):
    """An absent creation timestamp still sends the required experiment bound."""
    from langfuse_mcp.__main__ import EXPERIMENTS_EARLIEST_START, list_dataset_runs

    client = state.langfuse_client
    client._store.datasets["eval"].created_at = None
    _call(list_dataset_runs, state, dataset_name="eval")

    assert client.api.experiments.list_calls[-1]["from_start_time"] == EXPERIMENTS_EARLIEST_START
