"""Unit tests for annotation queue and score v2 tools."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from tests.fakes import FakeContext, FakeLangfuse


def _state(tmp_path):
    """Create MCP state backed by fake Langfuse client."""
    from langfuse_mcp.__main__ import MCPState

    return MCPState(langfuse_client=FakeLangfuse(), dump_dir=str(tmp_path))


def test_annotation_queue_tools_registered_in_groups():
    """Annotation queue and score tools should be registered in group metadata."""
    from langfuse_mcp.__main__ import TOOL_GROUPS, WRITE_TOOLS

    assert "annotation_queues" in TOOL_GROUPS
    assert "scores" in TOOL_GROUPS
    assert "list_annotation_queues" in TOOL_GROUPS["annotation_queues"]
    assert "get_score_v2" in TOOL_GROUPS["scores"]
    assert "create_annotation_queue" in WRITE_TOOLS
    assert "delete_annotation_queue_assignment" in WRITE_TOOLS


def test_annotation_queue_crud_and_assignment(tmp_path):
    """Annotation queue create/read/update and assignment flow should work."""
    from langfuse_mcp.__main__ import (
        create_annotation_queue,
        create_annotation_queue_assignment,
        create_annotation_queue_item,
        delete_annotation_queue_assignment,
        get_annotation_queue,
        get_annotation_queue_item,
        list_annotation_queue_items,
        list_annotation_queues,
        update_annotation_queue_item,
    )

    state = _state(tmp_path)
    ctx = FakeContext(state)

    created = asyncio.run(
        create_annotation_queue(
            ctx,
            name="review-queue",
            description="Queue for manual review",
            score_config_ids=["cfg_1"],
        )
    )
    queue_id = created["data"]["id"]
    assert created["metadata"]["created"] is True

    queues = asyncio.run(list_annotation_queues(ctx, page=1, limit=10))
    assert any(q["id"] == queue_id for q in queues["data"])

    queue = asyncio.run(get_annotation_queue(ctx, queue_id=queue_id))
    assert queue["data"]["name"] == "review-queue"

    item = asyncio.run(
        create_annotation_queue_item(
            ctx,
            queue_id=queue_id,
            object_id="trace_1",
            object_type="TRACE",
            status="PENDING",
        )
    )
    item_id = item["data"]["id"]
    assert item["metadata"]["created"] is True

    items = asyncio.run(list_annotation_queue_items(ctx, queue_id=queue_id, page=1, limit=10))
    assert any(it["id"] == item_id for it in items["data"])

    updated = asyncio.run(update_annotation_queue_item(ctx, queue_id=queue_id, item_id=item_id, status="COMPLETED"))
    assert updated["metadata"]["updated"] is True

    fetched_item = asyncio.run(get_annotation_queue_item(ctx, queue_id=queue_id, item_id=item_id))
    assert fetched_item["data"]["status"] == "COMPLETED"

    assigned = asyncio.run(create_annotation_queue_assignment(ctx, queue_id=queue_id, user_id="user_123"))
    assert assigned["metadata"]["created"] is True
    unassigned = asyncio.run(delete_annotation_queue_assignment(ctx, queue_id=queue_id, user_id="user_123"))
    assert unassigned["metadata"]["deleted"] is True


def test_delete_annotation_queue_item(tmp_path):
    """delete_annotation_queue_item should remove the item from queue lookups."""
    from langfuse_mcp.__main__ import (
        create_annotation_queue,
        create_annotation_queue_item,
        delete_annotation_queue_item,
        get_annotation_queue_item,
    )

    state = _state(tmp_path)
    ctx = FakeContext(state)

    queue = asyncio.run(create_annotation_queue(ctx, name="delete-queue"))
    queue_id = queue["data"]["id"]
    created_item = asyncio.run(
        create_annotation_queue_item(ctx, queue_id=queue_id, object_id="trace_1", object_type="TRACE", status="PENDING")
    )
    item_id = created_item["data"]["id"]

    deleted = asyncio.run(delete_annotation_queue_item(ctx, queue_id=queue_id, item_id=item_id))
    assert deleted["metadata"]["deleted"] is True

    with pytest.raises(LookupError):
        asyncio.run(get_annotation_queue_item(ctx, queue_id=queue_id, item_id=item_id))


def test_score_v2_tools(tmp_path):
    """Score v2 list and get-by-id tools should return seeded score data."""
    from langfuse_mcp.__main__ import get_score_v2, list_scores_v2

    state = _state(tmp_path)
    ctx = FakeContext(state)

    listed = asyncio.run(list_scores_v2(ctx, page=1, limit=10, user_id="user_1"))
    assert listed["metadata"]["item_count"] >= 1
    score_id = listed["data"][0]["id"]

    score = asyncio.run(get_score_v2(ctx, score_id=score_id))
    assert score["data"]["id"] == score_id


def test_list_scores_v2_coerces_iso_timestamps_and_float_value(tmp_path):
    """ISO timestamps should be coerced to datetime and value should be float."""
    from langfuse_mcp.__main__ import list_scores_v2

    state = _state(tmp_path)
    ctx = FakeContext(state)

    result = asyncio.run(
        list_scores_v2(
            ctx,
            page=1,
            limit=10,
            from_timestamp="2026-03-30T10:11:12Z",
            to_timestamp="2026-03-30T11:11:12+00:00",
            value=0.91,
        )
    )
    assert result["metadata"]["item_count"] >= 1

    passed_kwargs = state.langfuse_client.api.score_v_2.last_get_kwargs
    assert passed_kwargs is not None
    assert isinstance(passed_kwargs.get("from_timestamp"), datetime)
    assert isinstance(passed_kwargs.get("to_timestamp"), datetime)
    assert passed_kwargs["from_timestamp"].tzinfo is not None
    assert passed_kwargs["to_timestamp"].tzinfo is not None
    assert isinstance(passed_kwargs.get("value"), float)


def test_list_scores_v2_rejects_invalid_timestamp(tmp_path):
    """Invalid timestamp strings should raise ValueError before API call."""
    from langfuse_mcp.__main__ import list_scores_v2

    state = _state(tmp_path)
    ctx = FakeContext(state)

    with pytest.raises(ValueError, match="from_timestamp"):
        asyncio.run(list_scores_v2(ctx, from_timestamp="not-a-timestamp"))


def test_list_scores_v2_accepts_datetime_objects(tmp_path):
    """Datetime inputs should pass through to score_v_2.get unchanged."""
    from langfuse_mcp.__main__ import list_scores_v2

    state = _state(tmp_path)
    ctx = FakeContext(state)

    start = datetime(2026, 3, 30, 10, 11, 12, tzinfo=timezone.utc)
    end = datetime(2026, 3, 30, 11, 11, 12, tzinfo=timezone.utc)
    asyncio.run(list_scores_v2(ctx, from_timestamp=start, to_timestamp=end, value=1.0))

    passed_kwargs = state.langfuse_client.api.score_v_2.last_get_kwargs
    assert passed_kwargs is not None
    assert passed_kwargs["from_timestamp"] == start
    assert passed_kwargs["to_timestamp"] == end


def test_list_scores_v2_keeps_zero_float_filter(tmp_path):
    """A valid value=0.0 filter should not be dropped from API kwargs."""
    from langfuse_mcp.__main__ import list_scores_v2

    state = _state(tmp_path)
    ctx = FakeContext(state)

    asyncio.run(list_scores_v2(ctx, value=0.0))
    passed_kwargs = state.langfuse_client.api.score_v_2.last_get_kwargs
    assert passed_kwargs is not None
    assert "value" in passed_kwargs
    assert passed_kwargs["value"] == 0.0


def test_list_scores_v2_supports_trace_id_filter(tmp_path):
    """trace_id filter should be forwarded to the score v2 client."""
    from langfuse_mcp.__main__ import list_scores_v2

    state = _state(tmp_path)
    ctx = FakeContext(state)

    result = asyncio.run(list_scores_v2(ctx, trace_id="trace_1"))
    assert result["metadata"]["item_count"] >= 1
    passed_kwargs = state.langfuse_client.api.score_v_2.last_get_kwargs
    assert passed_kwargs is not None
    assert passed_kwargs["trace_id"] == "trace_1"
