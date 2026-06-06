"""Unit tests for dataset management tools."""

from __future__ import annotations

import asyncio

import pytest

from tests.fakes import FakeContext, FakeLangfuse

# ─────────────────────────────────────────────────────────────────────────────
# Tool Registration Test
# ─────────────────────────────────────────────────────────────────────────────


def test_dataset_tools_in_tool_groups():
    """Verify dataset tools are defined in TOOL_GROUPS."""
    from langfuse_mcp.__main__ import TOOL_GROUPS

    assert "datasets" in TOOL_GROUPS
    dataset_tools = TOOL_GROUPS["datasets"]
    expected_tools = [
        "list_datasets",
        "get_dataset",
        "list_dataset_items",
        "get_dataset_item",
        "create_dataset",
        "create_dataset_item",
        "delete_dataset_item",
        "list_dataset_runs",
        "get_dataset_run",
        "list_dataset_run_items",
        "create_dataset_run_item",
        "delete_dataset_run",
    ]
    for tool in expected_tools:
        assert tool in dataset_tools, f"Tool {tool} missing from TOOL_GROUPS['datasets']"


def test_write_tools_defined():
    """Verify write tools constant includes dataset write operations."""
    from langfuse_mcp.__main__ import WRITE_TOOLS

    expected_write_tools = [
        "create_dataset",
        "create_dataset_item",
        "delete_dataset_item",
        "create_dataset_run_item",
        "delete_dataset_run",
        "create_text_prompt",
        "create_chat_prompt",
        "update_prompt_labels",
    ]
    for tool in expected_write_tools:
        assert tool in WRITE_TOOLS, f"Tool {tool} missing from WRITE_TOOLS"


@pytest.fixture()
def state(tmp_path):
    """Return an MCPState instance using the fake client."""
    from langfuse_mcp.__main__ import MCPState

    return MCPState(langfuse_client=FakeLangfuse(), dump_dir=str(tmp_path))


# ─────────────────────────────────────────────────────────────────────────────
# Dataset CRUD Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_create_dataset(state):
    """create_dataset should create a new dataset."""
    from langfuse_mcp.__main__ import create_dataset

    ctx = FakeContext(state)
    result = asyncio.run(
        create_dataset(
            ctx,
            name="eval-set-1",
            description="Test evaluation dataset",
            metadata={"version": "1.0"},
        )
    )
    data = result["data"]
    assert data["name"] == "eval-set-1"
    assert data["description"] == "Test evaluation dataset"
    assert data["metadata"]["version"] == "1.0"
    assert result["metadata"]["created"] is True


def test_list_datasets(state):
    """list_datasets should return all datasets with pagination."""
    from langfuse_mcp.__main__ import create_dataset, list_datasets

    ctx = FakeContext(state)

    # Create some datasets
    asyncio.run(create_dataset(ctx, name="dataset-1", description="First"))
    asyncio.run(create_dataset(ctx, name="dataset-2", description="Second"))

    result = asyncio.run(list_datasets(ctx, page=1, limit=10))
    assert len(result["data"]) == 2
    assert result["metadata"]["page"] == 1
    assert result["metadata"]["limit"] == 10
    assert result["metadata"]["total"] == 2

    names = [d["name"] for d in result["data"]]
    assert "dataset-1" in names
    assert "dataset-2" in names


def test_get_dataset(state):
    """get_dataset should return a specific dataset by name."""
    from langfuse_mcp.__main__ import create_dataset, get_dataset

    ctx = FakeContext(state)

    # Create a dataset
    asyncio.run(create_dataset(ctx, name="my-dataset", description="Test dataset"))

    result = asyncio.run(get_dataset(ctx, name="my-dataset"))
    data = result["data"]
    assert data["name"] == "my-dataset"
    assert data["description"] == "Test dataset"


def test_get_dataset_not_found(state):
    """get_dataset should raise LookupError for non-existent dataset."""
    from langfuse_mcp.__main__ import get_dataset

    ctx = FakeContext(state)

    with pytest.raises(LookupError, match="not found"):
        asyncio.run(get_dataset(ctx, name="nonexistent"))


# ─────────────────────────────────────────────────────────────────────────────
# Dataset Item CRUD Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_create_dataset_item(state):
    """create_dataset_item should create a new item in a dataset."""
    from langfuse_mcp.__main__ import create_dataset, create_dataset_item

    ctx = FakeContext(state)

    # First create a dataset
    asyncio.run(create_dataset(ctx, name="test-dataset"))

    # Then create an item
    result = asyncio.run(
        create_dataset_item(
            ctx,
            dataset_name="test-dataset",
            input={"question": "What is 2+2?"},
            expected_output={"answer": "4"},
            metadata={"difficulty": "easy"},
        )
    )
    data = result["data"]
    assert data["input"] == {"question": "What is 2+2?"}
    assert data["expected_output"] == {"answer": "4"}
    assert data["metadata"]["difficulty"] == "easy"
    assert result["metadata"]["created"] is True


def test_create_dataset_item_with_custom_id(state):
    """create_dataset_item should support custom item IDs for upsert."""
    from langfuse_mcp.__main__ import create_dataset, create_dataset_item

    ctx = FakeContext(state)

    asyncio.run(create_dataset(ctx, name="test-dataset"))

    result = asyncio.run(
        create_dataset_item(
            ctx,
            dataset_name="test-dataset",
            item_id="custom-item-123",
            input="test input",
        )
    )
    data = result["data"]
    assert data["id"] == "custom-item-123"


def test_list_dataset_items(state):
    """list_dataset_items should return items in a dataset with pagination."""
    from langfuse_mcp.__main__ import create_dataset, create_dataset_item, list_dataset_items

    ctx = FakeContext(state)

    # Create dataset and items
    asyncio.run(create_dataset(ctx, name="test-dataset"))
    asyncio.run(create_dataset_item(ctx, dataset_name="test-dataset", input="input 1"))
    asyncio.run(create_dataset_item(ctx, dataset_name="test-dataset", input="input 2"))

    result = asyncio.run(list_dataset_items(ctx, dataset_name="test-dataset", page=1, limit=10))
    assert len(result["data"]) == 2
    assert result["metadata"]["dataset_name"] == "test-dataset"
    assert result["metadata"]["page"] == 1


def test_list_dataset_items_with_filter(state):
    """list_dataset_items should support filtering by source_trace_id."""
    from langfuse_mcp.__main__ import create_dataset, create_dataset_item, list_dataset_items

    ctx = FakeContext(state)

    asyncio.run(create_dataset(ctx, name="test-dataset"))
    asyncio.run(create_dataset_item(ctx, dataset_name="test-dataset", input="input 1", source_trace_id="trace-123"))
    asyncio.run(create_dataset_item(ctx, dataset_name="test-dataset", input="input 2", source_trace_id="trace-456"))

    result = asyncio.run(list_dataset_items(ctx, dataset_name="test-dataset", source_trace_id="trace-123"))
    assert len(result["data"]) == 1
    assert result["data"][0]["source_trace_id"] == "trace-123"


def test_get_dataset_item(state):
    """get_dataset_item should return a specific item by ID."""
    from langfuse_mcp.__main__ import create_dataset, create_dataset_item, get_dataset_item

    ctx = FakeContext(state)

    asyncio.run(create_dataset(ctx, name="test-dataset"))
    create_result = asyncio.run(
        create_dataset_item(
            ctx,
            dataset_name="test-dataset",
            input={"test": "data"},
            expected_output="expected",
        )
    )
    item_id = create_result["data"]["id"]

    result = asyncio.run(get_dataset_item(ctx, item_id=item_id))
    data = result["data"]
    assert data["id"] == item_id
    assert data["input"] == {"test": "data"}
    assert data["expected_output"] == "expected"


def test_get_dataset_item_not_found(state):
    """get_dataset_item should raise LookupError for non-existent item."""
    from langfuse_mcp.__main__ import get_dataset_item

    ctx = FakeContext(state)

    with pytest.raises(LookupError, match="not found"):
        asyncio.run(get_dataset_item(ctx, item_id="nonexistent-id"))


def test_delete_dataset_item(state):
    """delete_dataset_item should remove an item from the dataset."""
    from langfuse_mcp.__main__ import create_dataset, create_dataset_item, delete_dataset_item, get_dataset_item

    ctx = FakeContext(state)

    asyncio.run(create_dataset(ctx, name="test-dataset"))
    create_result = asyncio.run(create_dataset_item(ctx, dataset_name="test-dataset", input="to delete"))
    item_id = create_result["data"]["id"]

    # Delete the item
    result = asyncio.run(delete_dataset_item(ctx, item_id=item_id))
    assert result["metadata"]["deleted"] is True
    assert result["metadata"]["item_id"] == item_id

    # Verify it's gone
    with pytest.raises(LookupError):
        asyncio.run(get_dataset_item(ctx, item_id=item_id))


# ─────────────────────────────────────────────────────────────────────────────
# Dataset Run Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_create_dataset_run_item_flushes_and_returns_submitted_metadata(state):
    """create_dataset_run_item should submit through the SDK and flush the write."""
    from langfuse_mcp.__main__ import create_dataset, create_dataset_item, create_dataset_run_item

    ctx = FakeContext(state)
    asyncio.run(create_dataset(ctx, name="eval-set"))
    item_result = asyncio.run(create_dataset_item(ctx, dataset_name="eval-set", input={"question": "q"}))
    item_id = item_result["data"]["id"]

    result = asyncio.run(
        create_dataset_run_item(
            ctx,
            run_name="baseline",
            dataset_item_id=item_id,
            run_description="nightly eval",
            metadata={"model": "gpt-4.1"},
            trace_id="trace_1",
            observation_id="obs_1",
        )
    )

    assert state.langfuse_client.flush_count == 1
    assert result["data"]["dataset_item_id"] == item_id
    assert result["data"]["run_name"] == "baseline"
    assert result["data"]["trace_id"] == "trace_1"
    assert result["metadata"]["submitted"] is True
    assert result["metadata"]["run_name"] == "baseline"
    assert result["metadata"]["dataset_item_id"] == item_id


def test_list_dataset_runs_uses_dataset_name(state):
    """list_dataset_runs should call datasets.get_runs by dataset name."""
    from langfuse_mcp.__main__ import create_dataset, create_dataset_item, create_dataset_run_item, list_dataset_runs

    ctx = FakeContext(state)
    asyncio.run(create_dataset(ctx, name="eval-set"))
    item_result = asyncio.run(create_dataset_item(ctx, dataset_name="eval-set", input="input"))
    asyncio.run(create_dataset_run_item(ctx, run_name="baseline", dataset_item_id=item_result["data"]["id"]))

    result = asyncio.run(list_dataset_runs(ctx, dataset_name="eval-set", page=1, limit=10))

    assert result["data"][0]["name"] == "baseline"
    assert result["metadata"]["dataset_name"] == "eval-set"
    assert state.langfuse_client.api.datasets.last_get_runs_kwargs == {"dataset_name": "eval-set", "page": 1, "limit": 10}


def test_get_dataset_run_returns_items(state):
    """get_dataset_run should return a run with its run items."""
    from langfuse_mcp.__main__ import create_dataset, create_dataset_item, create_dataset_run_item, get_dataset_run

    ctx = FakeContext(state)
    asyncio.run(create_dataset(ctx, name="eval-set"))
    item_result = asyncio.run(create_dataset_item(ctx, dataset_name="eval-set", input="input"))
    item_id = item_result["data"]["id"]
    asyncio.run(create_dataset_run_item(ctx, run_name="baseline", dataset_item_id=item_id))

    result = asyncio.run(get_dataset_run(ctx, dataset_name="eval-set", run_name="baseline"))

    assert result["data"]["name"] == "baseline"
    assert result["data"]["items"][0]["dataset_item_id"] == item_id
    assert result["metadata"]["dataset_name"] == "eval-set"
    assert result["metadata"]["run_name"] == "baseline"


def test_list_dataset_run_items_uses_dataset_id_and_run_name(state):
    """list_dataset_run_items should call dataset_run_items.list with dataset_id and run_name."""
    from langfuse_mcp.__main__ import (
        create_dataset,
        create_dataset_item,
        create_dataset_run_item,
        list_dataset_run_items,
    )

    ctx = FakeContext(state)
    dataset = asyncio.run(create_dataset(ctx, name="eval-set"))["data"]
    item_result = asyncio.run(create_dataset_item(ctx, dataset_name="eval-set", input="input"))
    asyncio.run(create_dataset_run_item(ctx, run_name="baseline", dataset_item_id=item_result["data"]["id"]))

    result = asyncio.run(list_dataset_run_items(ctx, dataset_id=dataset["id"], run_name="baseline", page=1, limit=5))

    assert len(result["data"]) == 1
    assert result["metadata"]["dataset_id"] == dataset["id"]
    assert result["metadata"]["run_name"] == "baseline"
    assert state.langfuse_client.api.dataset_run_items.last_list_kwargs == {
        "dataset_id": dataset["id"],
        "run_name": "baseline",
        "page": 1,
        "limit": 5,
    }


def test_delete_dataset_run_removes_run_and_items(state):
    """delete_dataset_run should delete the run by dataset name and run name."""
    from langfuse_mcp.__main__ import (
        create_dataset,
        create_dataset_item,
        create_dataset_run_item,
        delete_dataset_run,
        list_dataset_runs,
    )

    ctx = FakeContext(state)
    asyncio.run(create_dataset(ctx, name="eval-set"))
    item_result = asyncio.run(create_dataset_item(ctx, dataset_name="eval-set", input="input"))
    asyncio.run(create_dataset_run_item(ctx, run_name="baseline", dataset_item_id=item_result["data"]["id"]))

    result = asyncio.run(delete_dataset_run(ctx, dataset_name="eval-set", run_name="baseline"))

    assert result["metadata"]["deleted"] is True
    assert result["metadata"]["dataset_name"] == "eval-set"
    assert result["metadata"]["run_name"] == "baseline"
    runs = asyncio.run(list_dataset_runs(ctx, dataset_name="eval-set"))
    assert runs["data"] == []


# ─────────────────────────────────────────────────────────────────────────────
# Output Mode Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_list_dataset_items_output_mode(state):
    """list_dataset_items should respect output_mode parameter."""
    from langfuse_mcp.__main__ import create_dataset, create_dataset_item, list_dataset_items

    ctx = FakeContext(state)

    asyncio.run(create_dataset(ctx, name="test-dataset"))
    asyncio.run(create_dataset_item(ctx, dataset_name="test-dataset", input="test"))

    # Test compact mode (default)
    result = asyncio.run(list_dataset_items(ctx, dataset_name="test-dataset", output_mode="compact"))
    assert result["metadata"]["output_mode"] == "compact"

    # Test full_json_string mode - returns raw JSON string, not dict
    result = asyncio.run(list_dataset_items(ctx, dataset_name="test-dataset", output_mode="full_json_string"))
    assert isinstance(result, str)
    assert "test" in result  # The input value should be in the JSON string


def test_get_dataset_item_output_mode(state):
    """get_dataset_item should respect output_mode parameter."""
    from langfuse_mcp.__main__ import create_dataset, create_dataset_item, get_dataset_item

    ctx = FakeContext(state)

    asyncio.run(create_dataset(ctx, name="test-dataset"))
    create_result = asyncio.run(create_dataset_item(ctx, dataset_name="test-dataset", input="test"))
    item_id = create_result["data"]["id"]

    # full_json_string mode returns raw JSON string, not dict
    result = asyncio.run(get_dataset_item(ctx, item_id=item_id, output_mode="full_json_string"))
    assert isinstance(result, str)
    assert item_id in result  # The item ID should be in the JSON string
