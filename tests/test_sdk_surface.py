"""The compat layer resolves every route it needs on the installed Langfuse SDK.

Runs against the real ``langfuse`` wheel (no network: the client is never asked to send).
CI installs the newest SDK the pin allows per Python version, so this catches an SDK release
that moves or deletes a method the server still serves.
"""

from __future__ import annotations

import importlib.metadata
import sys

import pytest

_STUBBED_MODULE_PREFIXES = ("langfuse", "langfuse_mcp", "pydantic", "mcp", "cachetools")


@pytest.fixture()
def real_client(monkeypatch: pytest.MonkeyPatch):
    """Drop conftest's module stubs and build a real client that never connects."""
    for name in list(sys.modules):
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in _STUBBED_MODULE_PREFIXES):
            monkeypatch.delitem(sys.modules, name, raising=False)
    from langfuse import Langfuse

    return Langfuse(
        public_key="pk-lf-surface-test",
        secret_key="sk-lf-surface-test",
        host="http://127.0.0.1:9",
        tracing_enabled=False,
    )


def _major() -> int:
    return int(importlib.metadata.version("langfuse").split(".", 1)[0])


def test_current_routes_resolve(real_client):
    """The v2 observations, v3 scores, v2 metrics, experiments and trace-delete clients exist."""
    from langfuse_mcp import _compat

    assert _major() >= 4
    assert _compat.get_scores_v3_method(real_client) is not None
    for path in (
        "observations.get_many",
        "metrics.metrics",
        "experiments.list",
        "trace.delete_multiple",
        "datasets.list",
        "prompts.list",
    ):
        assert _compat.get_sdk_method(real_client, path) is not None, path


def test_v2_score_reader_only_on_sdk4(real_client):
    """SDK 4 keeps the page-based v2 reader; SDK 5's ``get_many`` is v3 and must not be used as v2."""
    from langfuse_mcp import _compat

    v2 = _compat.get_score_list_method(real_client.api.scores)
    if _major() >= 5:
        assert v2 is None
        assert _compat.get_scores_v3_method(real_client) == real_client.api.scores.get_many
    else:
        assert v2 is not None


def test_removed_routes_are_absent_on_sdk5(real_client):
    """SDK 5 deletes the legacy clients; the server tools must not depend on them."""
    from langfuse_mcp import _compat

    if _major() < 5:
        pytest.skip("SDK 4 still ships the legacy clients")
    for path in ("trace.list", "trace.get", "sessions.list", "datasets.get_runs", "dataset_run_items.create"):
        assert _compat.get_sdk_method(real_client, path) is None, path
