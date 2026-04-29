"""Live smoke tests against a real Langfuse deployment.

These tests verify the v3/v4 compatibility shim against a real ``Langfuse``
client and the live HTTP API, rather than the in-memory fakes used by the
rest of the suite.

Skipped unless the standard Langfuse credentials are present in the
environment (``LANGFUSE_PUBLIC_KEY``, ``LANGFUSE_SECRET_KEY``, optional
``LANGFUSE_HOST`` defaulting to ``https://cloud.langfuse.com``).

The smoke also requires ``langfuse>=4.0.0,<5.0.0`` to be installed —
exercising it against the v3 SDK only re-tests the v3 path the rest of
the suite already covers. With v3 installed (or v4 missing entirely) the
``_require_v4_sdk`` skip fires.

Run against a v4 venv::

    uv venv --python 3.11 .venv-v4
    .venv-v4/bin/uv pip install -e ".[dev]" "langfuse>=4.0.0,<5.0.0"
    LANGFUSE_PUBLIC_KEY=... LANGFUSE_SECRET_KEY=... \
        .venv-v4/bin/python -m pytest tests/test_v4_smoke.py -m integration -v -s

The ``-s`` flag is recommended so the introspection test prints which
dispatcher path was selected — useful when verifying a new SDK release.

Write tests are gated behind ``LANGFUSE_MCP_SMOKE_DATASET`` (an existing
dataset name in the project) because creating an annotation queue leaves
data behind that has no exposed delete tool.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import os
import uuid
from typing import Any

import pytest

# Bypass the autouse ``patch_dependencies`` fixture in conftest.py — it stubs
# out ``langfuse``, ``mcp.server.fastmcp``, and ``pydantic`` with hand-rolled
# fakes that prevent the real SDK from being imported. The fixture runs at
# module import time, so we have to clear the stubbed modules and import the
# real ones before anything else can touch ``langfuse``.
_REAL_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY")
_REAL_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY")
_REAL_HOST = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (_REAL_PUBLIC_KEY and _REAL_SECRET_KEY),
        reason="LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be set for live smoke tests",
    ),
]


_STUBBED_MODULE_PREFIXES = (
    "langfuse",
    "langfuse_mcp",
    "pydantic",
    "mcp",
    "cachetools",
)


@pytest.fixture(autouse=True)
def _restore_real_langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undo conftest's autouse module stubs for this file only.

    ``tests/conftest.py`` installs fake ``langfuse``, ``pydantic``, ``mcp``
    (and submodules), and ``cachetools`` into ``sys.modules`` so the rest of
    the suite can import ``langfuse_mcp`` without the real dependencies. The
    fake ``pydantic`` in particular is missing ``VERSION`` and other attrs
    that real Langfuse imports rely on. This fixture runs before each test
    body (after ``conftest.patch_dependencies`` has already inserted the
    stubs) and drops every stubbed package so the real installed wheels load.
    """
    import sys

    for name in list(sys.modules):
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in _STUBBED_MODULE_PREFIXES):
            monkeypatch.delitem(sys.modules, name, raising=False)
    yield


def _require_v4_sdk() -> str:
    """Return the installed ``langfuse`` version after asserting it's a v4."""
    sdk_version = importlib.metadata.version("langfuse")
    major = int(sdk_version.split(".", 1)[0])
    if major < 4:
        pytest.skip(
            f"This smoke targets v4 SDK behavior (legacy.observations_v1 fallback, scores.get_many, "
            f"annotation_queue direct-kwargs). Installed `langfuse=={sdk_version}` is v{major}; "
            f"install langfuse>=4.0.0,<5.0.0 to run."
        )
    return sdk_version


def _make_state(tmp_path):
    """Construct an MCPState backed by a real ``Langfuse`` client."""
    from langfuse import Langfuse

    from langfuse_mcp.__main__ import MCPState

    client = Langfuse(
        public_key=_REAL_PUBLIC_KEY,
        secret_key=_REAL_SECRET_KEY,
        host=_REAL_HOST,
        tracing_enabled=False,
        flush_at=0,
        flush_interval=None,
    )
    return MCPState(langfuse_client=client, dump_dir=str(tmp_path))


def _ctx(state):
    """Wrap state in the shape ``Context.request_context.lifespan_context`` expects."""
    from types import SimpleNamespace

    return SimpleNamespace(request_context=SimpleNamespace(lifespan_context=state))


# ---------- Dispatcher introspection ----------


def test_dispatcher_paths_against_live_sdk(tmp_path, capsys):
    """Print which compat dispatcher path is selected against the live SDK.

    This isn't strictly a behavior test — it's a diagnostic that prints the
    SDK version, the observation list/single-fetch route selection, and the
    score namespace name. Useful when bumping ``langfuse`` to a new release
    to confirm the shim is still picking the route you expect.
    """
    from langfuse_mcp import _compat

    sdk_version = _require_v4_sdk()
    state = _make_state(tmp_path)

    score_ns = _compat.get_score_namespace(state.langfuse_client)
    score_ns_name = type(score_ns).__name__ if score_ns is not None else None

    list_method = _compat.get_observations_list_method(state.langfuse_client)
    if list_method is not None:
        method, mode = list_method
        list_repr = f"{type(method.__self__).__name__}.{method.__name__} ({mode})"
    else:
        list_repr = "<unsupported>"

    fetcher = _compat.get_observations_single_fetcher(state.langfuse_client)
    fetcher_repr = "<present>" if fetcher is not None else "<unsupported>"

    print()
    print(f"langfuse-version    : {sdk_version}")
    print(f"score-namespace     : {score_ns_name}")
    print(f"observations-list   : {list_repr}")
    print(f"observations-single : {fetcher_repr}")

    assert sdk_version
    assert score_ns is not None, "Both api.scores and api.score_v_2 missing"
    assert list_method is not None, "No observation list endpoint found"
    assert fetcher is not None, "No observation single-fetch endpoint found"


# ---------- Read smoke (always safe — no writes) ----------


def test_fetch_traces_live(tmp_path):
    """``fetch_traces`` should round-trip against the live API on both v3 and v4."""
    from langfuse_mcp.__main__ import fetch_traces

    _require_v4_sdk()
    state = _make_state(tmp_path)
    result = asyncio.run(
        fetch_traces(
            _ctx(state),
            age=1,
            name=None,
            user_id=None,
            session_id=None,
            metadata=None,
            page=1,
            limit=5,
            tags=None,
            include_observations=False,
            output_mode="compact",
        )
    )
    assert "data" in result and "metadata" in result
    assert isinstance(result["data"], list)
    assert result["metadata"]["item_count"] == len(result["data"])


def test_fetch_observations_live(tmp_path):
    """``fetch_observations`` should round-trip; v4 routes through legacy.observations_v1."""
    from langfuse_mcp.__main__ import fetch_observations

    _require_v4_sdk()
    state = _make_state(tmp_path)
    result = asyncio.run(
        fetch_observations(
            _ctx(state),
            type=None,
            age=1,
            name=None,
            user_id=None,
            trace_id=None,
            parent_observation_id=None,
            page=1,
            limit=5,
            output_mode="compact",
        )
    )
    assert "data" in result and "metadata" in result
    assert isinstance(result["data"], list)


def test_fetch_observation_live_when_present(tmp_path):
    """``fetch_observation`` should resolve through the live single-fetch route when an observation exists."""
    from langfuse_mcp.__main__ import fetch_observation, fetch_observations

    _require_v4_sdk()
    state = _make_state(tmp_path)
    listed = asyncio.run(
        fetch_observations(
            _ctx(state),
            type=None,
            age=7,
            name=None,
            user_id=None,
            trace_id=None,
            parent_observation_id=None,
            page=1,
            limit=1,
            output_mode="compact",
        )
    )
    if not listed["data"]:
        pytest.skip("No observations in the project's last 7 days; skipping single-fetch probe")

    obs_id: Any = listed["data"][0].get("id")
    assert obs_id, f"observation listing did not include an 'id' field: {listed['data'][0]!r}"

    fetched = asyncio.run(fetch_observation(_ctx(state), observation_id=obs_id, output_mode="compact"))
    assert fetched["data"]
    assert fetched["data"].get("id") == obs_id


def test_list_scores_v2_live(tmp_path):
    """``list_scores_v2`` should reach the right namespace on both SDK majors."""
    from langfuse_mcp.__main__ import list_scores_v2

    _require_v4_sdk()
    state = _make_state(tmp_path)
    result = asyncio.run(list_scores_v2(_ctx(state), page=1, limit=5))
    assert "data" in result and "metadata" in result
    assert isinstance(result["data"], list)


def test_list_annotation_queues_live(tmp_path):
    """``list_annotation_queues`` should round-trip on both SDK majors."""
    from langfuse_mcp.__main__ import list_annotation_queues

    _require_v4_sdk()
    state = _make_state(tmp_path)
    result = asyncio.run(list_annotation_queues(_ctx(state), page=1, limit=5))
    assert "data" in result and "metadata" in result


def test_list_datasets_live(tmp_path):
    """``list_datasets`` should round-trip on both SDK majors."""
    from langfuse_mcp.__main__ import list_datasets

    _require_v4_sdk()
    state = _make_state(tmp_path)
    result = asyncio.run(list_datasets(_ctx(state), page=1, limit=5))
    assert "data" in result and "metadata" in result


def test_list_prompts_live(tmp_path):
    """``list_prompts`` should round-trip; verifies the prompts API surface."""
    from langfuse_mcp.__main__ import list_prompts

    _require_v4_sdk()
    state = _make_state(tmp_path)
    result = asyncio.run(list_prompts(_ctx(state), page=1, limit=5))
    assert "data" in result and "metadata" in result


# ---------- Write smoke (opt-in via env var so we don't pollute) ----------


_SMOKE_DATASET = os.environ.get("LANGFUSE_MCP_SMOKE_DATASET")


@pytest.mark.skipif(
    not _SMOKE_DATASET,
    reason="LANGFUSE_MCP_SMOKE_DATASET must point to an existing dataset name to exercise dataset-item writes",
)
def test_create_then_delete_dataset_item_live(tmp_path):
    """Round-trip a dataset_item create + delete to verify the v4 direct-kwargs path.

    The v4 ``Langfuse.create_dataset_item`` and ``api.dataset_items.delete``
    surfaces are the most likely place the v3 ``request=<PydanticModel>``
    style would surface a Pydantic validation error if our coercion is wrong.
    Cleanup deletes the item in a ``finally`` so even an assertion failure
    after a successful create can't leave the dataset polluted.
    """
    from langfuse_mcp.__main__ import create_dataset_item, delete_dataset_item

    _require_v4_sdk()
    state = _make_state(tmp_path)
    item_id = f"smoke-{uuid.uuid4().hex[:12]}"
    created_id: str | None = None
    try:
        created = asyncio.run(
            create_dataset_item(
                _ctx(state),
                dataset_name=_SMOKE_DATASET,
                input={"prompt": "smoke test"},
                expected_output="smoke result",
                metadata={"smoke": True},
                source_trace_id=None,
                source_observation_id=None,
                item_id=item_id,
                status="ACTIVE",
            )
        )
        # Capture id for cleanup BEFORE asserting on shape, so a shape mismatch
        # in the response payload doesn't strand the item in the dataset.
        created_id = (created.get("data") or {}).get("id") or item_id
        assert created["metadata"]["created"] is True
    finally:
        if created_id is not None:
            deleted = asyncio.run(delete_dataset_item(_ctx(state), item_id=created_id))
            assert deleted["metadata"]["deleted"] is True
