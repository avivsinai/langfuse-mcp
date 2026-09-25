"""Score reads over Scores API v3 (GET /api/public/v3/scores).

Langfuse Cloud removes GET /v2/scores and /v2/scores/{id} on 2026-11-16. These tests pin the v3
routing on the v4 fake (which enforces the real endpoint's 400 rules), the mapping of the v2
filters, the v2 fallback, and that the tools keep the v2 score shape.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from tests.fakes import FakeContext, FakeHTTPError, FakeLangfuseV4, FakeScore, _ScoresV3API


@pytest.fixture()
def v4_state(tmp_path):
    """Return an MCPState backed by the v4 fake client (which exposes ``api.scores_v3``)."""
    from langfuse_mcp.__main__ import MCPState

    return MCPState(langfuse_client=FakeLangfuseV4(), dump_dir=str(tmp_path))


def _list(state: Any, **filters: Any) -> Any:
    from langfuse_mcp.__main__ import list_scores_v2

    return asyncio.run(list_scores_v2(FakeContext(state), **filters))


def test_list_scores_reads_v3_and_keeps_the_v2_shape(v4_state):
    """Rows come back flat (trace_id from the v3 subject) and the v2 score endpoint is never called."""
    from langfuse_mcp.__main__ import SCORES_V3_FIELDS

    client = v4_state.langfuse_client
    result = _list(v4_state, score_ids="score_1", name="quality", limit=10)

    call = client.api.scores_v3.calls[-1]
    assert call["id"] == "score_1" and call["name"] == "quality" and call["fields"] == SCORES_V3_FIELDS
    assert client.api.scores.last_get_many_kwargs is None
    [score] = result["data"]
    assert score["id"] == "score_1"
    assert score["trace_id"] == "trace_1"
    assert score["subject"] == {"kind": "trace", "id": "trace_1"}
    assert result["metadata"]["total"] is None and result["metadata"]["next_page"] is None


@pytest.mark.parametrize(
    ("operator", "data_type", "expected", "item_count"),
    [
        (None, None, {"value": "0.91", "data_type": "NUMERIC"}, 1),
        ("=", "NUMERIC", {"value": "0.91", "data_type": "NUMERIC"}, 1),
        (">=", None, {"value_min": 0.91, "data_type": "NUMERIC"}, 1),
        ("<=", None, {"value_max": 0.91, "data_type": "NUMERIC"}, 1),
        (">", None, {"value_min": 0.91, "data_type": "NUMERIC"}, 0),
        ("<", None, {"value_max": 0.91, "data_type": "NUMERIC"}, 0),
    ],
)
def test_operator_and_value_map_to_v3_filters(v4_state, operator, data_type, expected, item_count):
    """Exact values need one data type; bounds are inclusive, so strict ones drop the boundary row."""
    result = _list(v4_state, value=0.91, operator=operator, data_type=data_type)

    call = v4_state.langfuse_client.api.scores_v3.calls[-1]
    assert {key: call[key] for key in expected} == expected
    assert result["metadata"]["item_count"] == item_count


def test_boolean_values_are_sent_as_true_or_false(v4_state):
    """v2 took booleans as 1/0; v3 wants the words."""
    _list(v4_state, value=1.0, data_type="BOOLEAN")

    assert v4_state.langfuse_client.api.scores_v3.calls[-1]["value"] == "true"


def test_exact_value_without_data_type_reports_numeric_default(v4_state):
    """An omitted type excludes boolean scores and tells the caller how to request them."""
    client = v4_state.langfuse_client
    client._store.scores["boolean_score"] = FakeScore(
        id="boolean_score", name="approved", value=True, data_type="BOOLEAN", trace_id="trace_1"
    )

    defaulted = _list(v4_state, value=1)
    explicit = _list(v4_state, value=1, data_type="BOOLEAN")

    assert defaulted["data"] == []
    assert defaulted["metadata"]["data_type"] == "NUMERIC"
    assert "data_type=BOOLEAN" in defaulted["metadata"]["data_type_hint"]
    assert [score["id"] for score in explicit["data"]] == ["boolean_score"]
    assert "data_type_hint" not in explicit["metadata"]


def test_strict_boundary_can_leave_a_short_page_with_next_page(v4_state):
    """Dropping a boundary score does not erase the cursor for the next page."""
    client = v4_state.langfuse_client
    client._store.scores["higher"] = FakeScore(id="higher", name="quality", value=0.92, trace_id="trace_2")

    first = _list(v4_state, value=0.91, operator=">", limit=1)
    second = _list(v4_state, value=0.91, operator=">", page=2, limit=1)

    assert first["data"] == []
    assert first["metadata"]["next_page"] == 2
    assert [score["id"] for score in second["data"]] == ["higher"]


@pytest.mark.parametrize(
    ("filters", "message"),
    [
        ({"value": 0.5, "operator": "!="}, "no Scores API v3 equivalent"),
        ({"value": 0.5, "operator": ">=", "data_type": "CATEGORICAL"}, "needs data_type NUMERIC"),
        ({"trace_id": "trace_1", "session_id": "s_1"}, "cannot combine trace_id and session_id"),
    ],
)
def test_filters_v3_cannot_express_fail_before_any_request(v4_state, filters, message):
    """A combination v3 would reject with a 400 is reported up front, with the reason."""
    with pytest.raises(ValueError, match=message):
        _list(v4_state, **filters)
    assert v4_state.langfuse_client.api.scores_v3.calls == []


def test_user_id_and_trace_tags_keep_the_v2_route(v4_state):
    """v3 dropped both filters, so they still go to GET /v2/scores while it is served."""
    client = v4_state.langfuse_client

    result = _list(v4_state, user_id="user_1")

    assert result["metadata"]["item_count"] == 1
    assert client.api.scores.last_get_many_kwargs["user_id"] == "user_1"
    assert client.api.scores_v3.calls == []


def test_v2_only_filters_explain_themselves_once_v2_is_gone(v4_state, monkeypatch):
    """After the cutover GET /v2/scores answers 404; the error says which filters to use instead."""

    def v2_gone(**kwargs: Any) -> Any:
        raise FakeHTTPError(404, "not found")

    monkeypatch.setattr(v4_state.langfuse_client.api.scores, "get_many", v2_gone)

    with pytest.raises(RuntimeError, match="ERR_LANGFUSE_SCORES_V2_ONLY_FILTER"):
        _list(v4_state, trace_tags="prod")


def test_page_two_walks_the_v3_cursor(v4_state):
    """Skipped pages are requested with the core fields only."""
    client = v4_state.langfuse_client
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    client._store.scores["score_2"] = FakeScore(id="score_2", name="quality", value=0.4, trace_id="trace_2", created_at=now)

    result = _list(v4_state, page=2, limit=1)

    assert [score["id"] for score in result["data"]] == ["score_2"]
    skip_call, page_call = client.api.scores_v3.calls[-2:]
    assert "fields" not in skip_call and page_call["cursor"] == "1"


@pytest.mark.parametrize("status_code", [404, 405])
def test_servers_without_scores_v3_fall_back_to_v2(v4_state, monkeypatch, status_code):
    """A server that does not serve /v3/scores gets the v2 routes for both tools."""
    from langfuse_mcp.__main__ import get_score_v2

    client = v4_state.langfuse_client

    def v3_not_served(self: Any, **kwargs: Any) -> Any:
        raise FakeHTTPError(status_code, "not served")

    monkeypatch.setattr(_ScoresV3API, "get_many_v3", v3_not_served)

    listed = _list(v4_state, limit=10)
    fetched = asyncio.run(get_score_v2(FakeContext(v4_state), score_id="score_1"))

    assert listed["metadata"]["item_count"] == 1 and client.api.scores.last_get_many_kwargs is not None
    assert fetched["data"]["id"] == "score_1" and client.api.scores.last_get_by_id_kwargs == {"score_id": "score_1"}


def test_other_v3_errors_propagate(v4_state, monkeypatch):
    """Only 404/405 means 'v3 not served'; a 400 from a bad filter surfaces as is."""

    def bad_request(self: Any, **kwargs: Any) -> Any:
        raise FakeHTTPError(400, "bad filter")

    monkeypatch.setattr(_ScoresV3API, "get_many_v3", bad_request)

    with pytest.raises(FakeHTTPError):
        _list(v4_state, limit=10)
    assert v4_state.langfuse_client.api.scores.last_get_many_kwargs is None


def test_get_score_reads_v3_by_id(v4_state):
    """get_score_v2 filters v3 by id; v3 has no get-by-id endpoint."""
    from langfuse_mcp.__main__ import get_score_v2

    client = v4_state.langfuse_client
    result = asyncio.run(get_score_v2(FakeContext(v4_state), score_id="score_1"))

    assert result["data"]["id"] == "score_1" and result["data"]["trace_id"] == "trace_1"
    assert client.api.scores_v3.calls[-1]["id"] == "score_1"
    assert client.api.scores.last_get_by_id_kwargs is None

    with pytest.raises(LookupError):
        asyncio.run(get_score_v2(FakeContext(v4_state), score_id="missing"))


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (
            {"id": "s", "value": 1.0, "data_type": "NUMERIC", "subject": {"kind": "observation", "id": "o", "trace_id": "t"}},
            {"observation_id": "o", "trace_id": "t"},
        ),
        (
            {"id": "s", "value": "good", "data_type": "CATEGORICAL", "subject": {"kind": "session", "id": "sess"}},
            {"session_id": "sess", "string_value": "good"},
        ),
        (
            {"id": "s", "value": True, "dataType": "BOOLEAN", "subject": {"kind": "experiment", "id": "exp"}},
            {"experiment_id": "exp", "data_type": "BOOLEAN"},
        ),
    ],
)
def test_score_v3_row_flattens_the_subject(row, expected):
    """Every subject kind maps back to the flat v2 id fields; camelCase keys are normalized."""
    from langfuse_mcp.__main__ import _score_v3_row

    flattened = _score_v3_row(row)
    assert {key: flattened[key] for key in expected} == expected
