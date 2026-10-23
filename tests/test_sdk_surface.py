"""The compat layer resolves every route it needs on the installed Langfuse SDK.

Runs against the real ``langfuse`` wheel with no network (the client is never asked to send).
CI installs the newest SDK the pin allows on each Python version and the floor on one row,
so this catches an SDK release that moves or deletes a method the server still uses.

Each probe runs in a subprocess: ``tests/conftest.py`` replaces ``langfuse`` and friends with
stubs, and importing the real SDK into this process would leak real modules into later tests.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

_PROBE = textwrap.dedent(
    """
    import importlib.metadata
    import json

    from langfuse import Langfuse

    from langfuse_mcp import _compat

    client = Langfuse(
        public_key="pk-lf-surface-test",
        secret_key="sk-lf-surface-test",
        host="http://127.0.0.1:9",
        tracing_enabled=False,
    )
    paths = [
        "observations.get_many",
        "metrics.metrics",
        "experiments.list",
        "trace.delete_multiple",
        "datasets.list",
        "prompts.list",
        "trace.list",
        "trace.get",
        "sessions.list",
        "datasets.get_runs",
        "dataset_run_items.create",
    ]
    namespace = _compat.get_score_namespace(client)
    v3 = _compat.get_scores_v3_method(client)
    print(json.dumps({
        "version": importlib.metadata.version("langfuse"),
        "paths": {path: _compat.get_sdk_method(client, path) is not None for path in paths},
        "scores_v3": v3 is not None,
        "scores_v3_is_scores_get_many": v3 is not None and v3 == getattr(namespace, "get_many", None),
        "v2_score_list": namespace is not None and _compat.get_score_list_method(namespace) is not None,
    }))
    """
)


def _probe() -> dict:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def _major(probe: dict) -> int:
    return int(probe["version"].split(".", 1)[0])


def test_current_routes_resolve():
    """The v2 observations, v3 scores, v2 metrics, experiments and trace-delete clients exist."""
    probe = _probe()

    assert _major(probe) >= 4, probe["version"]
    assert probe["scores_v3"]
    for path in ("observations.get_many", "metrics.metrics", "experiments.list", "trace.delete_multiple", "datasets.list", "prompts.list"):
        assert probe["paths"][path], path


def test_v2_score_reader_only_on_sdk4():
    """SDK 4 keeps the page-based v2 reader; SDK 5's ``get_many`` is v3 and must not be used as v2."""
    probe = _probe()

    if _major(probe) >= 5:
        assert not probe["v2_score_list"]
        assert probe["scores_v3_is_scores_get_many"]
    else:
        assert probe["v2_score_list"]
        assert not probe["scores_v3_is_scores_get_many"]


def test_removed_routes_are_absent_on_sdk5():
    """SDK 5 deletes the legacy clients, and ``get_sdk_method`` reports each as missing."""
    probe = _probe()

    removed = ("trace.list", "trace.get", "sessions.list", "datasets.get_runs", "dataset_run_items.create")
    if _major(probe) >= 5:
        assert not any(probe["paths"][path] for path in removed)
    else:
        assert all(probe["paths"][path] for path in removed)
