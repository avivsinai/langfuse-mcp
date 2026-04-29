"""Unit tests for langfuse_mcp._compat capability helpers."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from typing import Any

import pytest

from langfuse_mcp._compat import (
    call_with_request_or_kwargs,
    get_observations_list_method,
    get_observations_single_fetcher,
    get_score_list_method,
    get_score_namespace,
    method_has_param,
    resolve_request_model,
)


def _install_fake_module(monkeypatch: pytest.MonkeyPatch, name: str, **attrs: Any) -> None:
    """Register a fake module under ``name`` and stash any provided attributes."""
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)


# ---------- resolve_request_model ----------


def test_resolve_request_model_prefers_v4_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolver should pick the flattened v4 path before falling back to v3."""

    class V4Request:
        pass

    _install_fake_module(monkeypatch, "langfuse")
    _install_fake_module(monkeypatch, "langfuse.api")
    _install_fake_module(monkeypatch, "langfuse.api.datasets")
    _install_fake_module(monkeypatch, "langfuse.api.datasets.types")
    _install_fake_module(
        monkeypatch,
        "langfuse.api.datasets.types.create_dataset_request",
        CreateDatasetRequest=V4Request,
    )
    resolved = resolve_request_model("datasets", "create_dataset_request", "CreateDatasetRequest")
    assert resolved is V4Request


def test_resolve_request_model_falls_back_to_v3(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolver should locate the v3 ``langfuse.api.resources.*`` path when v4 is absent."""

    class V3Request:
        pass

    _install_fake_module(monkeypatch, "langfuse")
    _install_fake_module(monkeypatch, "langfuse.api")
    _install_fake_module(monkeypatch, "langfuse.api.resources")
    _install_fake_module(monkeypatch, "langfuse.api.resources.datasets")
    _install_fake_module(monkeypatch, "langfuse.api.resources.datasets.types")
    _install_fake_module(
        monkeypatch,
        "langfuse.api.resources.datasets.types.create_dataset_request",
        CreateDatasetRequest=V3Request,
    )
    resolved = resolve_request_model("datasets", "create_dataset_request", "CreateDatasetRequest")
    assert resolved is V3Request


def test_resolve_request_model_falls_back_to_dict_when_neither_path_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolver should fall back to ``dict`` so ``Model(**kwargs)`` still constructs a payload."""
    monkeypatch.setitem(sys.modules, "langfuse", types.ModuleType("langfuse"))
    resolved = resolve_request_model("datasets", "missing_module", "MissingModel")
    assert resolved is dict
    payload = resolved(name="alpha", description="bravo")
    assert payload == {"name": "alpha", "description": "bravo"}


# ---------- get_score_namespace / get_score_list_method ----------


def test_get_score_namespace_prefers_v4_scores() -> None:
    """Helper should prefer ``api.scores`` (v4) when both namespaces are present."""
    v4_scores = SimpleNamespace(get_many=lambda **_: None, get_by_id=lambda **_: None)
    v3_scores = SimpleNamespace(get=lambda **_: None, get_by_id=lambda **_: None)
    client = SimpleNamespace(api=SimpleNamespace(scores=v4_scores, score_v_2=v3_scores))
    assert get_score_namespace(client) is v4_scores


def test_get_score_namespace_falls_back_to_v3() -> None:
    """Helper should return ``api.score_v_2`` when only the v3 namespace exists."""
    v3_scores = SimpleNamespace(get=lambda **_: None, get_by_id=lambda **_: None)
    client = SimpleNamespace(api=SimpleNamespace(score_v_2=v3_scores))
    assert get_score_namespace(client) is v3_scores


def test_get_score_namespace_returns_none_when_missing() -> None:
    """Helper should yield ``None`` when neither score namespace is exposed."""
    client = SimpleNamespace(api=SimpleNamespace())
    assert get_score_namespace(client) is None


def test_get_score_list_method_prefers_get_many_for_v4() -> None:
    """List-method helper should prefer ``get_many`` (v4 plural)."""
    sentinel_v4 = lambda **_: None  # noqa: E731
    sentinel_v3 = lambda **_: None  # noqa: E731
    namespace = SimpleNamespace(get_many=sentinel_v4, get=sentinel_v3)
    assert get_score_list_method(namespace) is sentinel_v4


def test_get_score_list_method_falls_back_to_get_for_v3() -> None:
    """List-method helper should fall back to ``get`` for v3-shaped namespaces."""
    sentinel_v3 = lambda **_: None  # noqa: E731
    namespace = SimpleNamespace(get=sentinel_v3)
    assert get_score_list_method(namespace) is sentinel_v3


# ---------- get_observations_single_fetcher ----------


def test_observations_single_fetcher_prefers_v3_get() -> None:
    """Single-fetcher should select ``api.observations.get`` first when present."""
    captured: dict[str, Any] = {}

    def v3_get(*, observation_id: str) -> str:
        captured["called"] = observation_id
        return "v3"

    api = SimpleNamespace(observations=SimpleNamespace(get=v3_get))
    client = SimpleNamespace(api=api)
    fetcher = get_observations_single_fetcher(client)
    assert fetcher is not None
    assert fetcher("obs1") == "v3"
    assert captured["called"] == "obs1"


def test_observations_single_fetcher_uses_legacy_when_v3_absent() -> None:
    """Single-fetcher should drop to ``api.legacy.observations_v1.get`` on v4 SDKs."""
    captured: dict[str, Any] = {}

    def legacy_get(observation_id: str) -> str:
        captured["called"] = observation_id
        return "legacy"

    legacy = SimpleNamespace(observations_v1=SimpleNamespace(get=legacy_get))
    # observations namespace exists but has no .get (v4 with cursor get_many only)
    observations = SimpleNamespace(get_many=lambda **_: None)
    api = SimpleNamespace(observations=observations, legacy=legacy)
    client = SimpleNamespace(api=api)
    fetcher = get_observations_single_fetcher(client)
    assert fetcher is not None
    assert fetcher("obs2") == "legacy"
    assert captured["called"] == "obs2"


def test_observations_single_fetcher_uses_top_level_fallback() -> None:
    """Single-fetcher should accept the top-level ``client.fetch_observation`` shim."""

    def fetch_observation(obs_id: str) -> str:
        return f"top:{obs_id}"

    client = SimpleNamespace(api=SimpleNamespace(), fetch_observation=fetch_observation)
    fetcher = get_observations_single_fetcher(client)
    assert fetcher is not None
    assert fetcher("obs3") == "top:obs3"


def test_observations_single_fetcher_unwraps_top_level_envelope() -> None:
    """Top-level ``fetch_observation`` envelopes (``.data``) must be unwrapped to match the v3/legacy contract."""
    payload = {"id": "obs9", "name": "envelope"}

    def fetch_observation(obs_id: str) -> SimpleNamespace:
        return SimpleNamespace(data=payload)

    client = SimpleNamespace(api=SimpleNamespace(), fetch_observation=fetch_observation)
    fetcher = get_observations_single_fetcher(client)
    assert fetcher is not None
    assert fetcher("obs9") is payload


def test_observations_single_fetcher_returns_none_when_unsupported() -> None:
    """Single-fetcher should yield ``None`` when no observation route is exposed."""
    client = SimpleNamespace(api=SimpleNamespace())
    assert get_observations_single_fetcher(client) is None


# ---------- get_observations_list_method ----------


def test_observations_list_prefers_v3_page_get_many() -> None:
    """List-method helper should pick the page-based ``api.observations.get_many`` first."""

    def v3_get_many(*, page: int | None = None, limit: int | None = None) -> dict:
        return {"data": [], "page": page, "limit": limit}

    api = SimpleNamespace(observations=SimpleNamespace(get_many=v3_get_many))
    client = SimpleNamespace(api=api)
    method, mode = get_observations_list_method(client)  # type: ignore[misc]
    assert method is v3_get_many
    assert mode == "page"


def test_observations_list_falls_back_to_legacy_v1() -> None:
    """List-method helper should jump to ``legacy.observations_v1`` when only cursor v2 is present."""

    def cursor_only(*, cursor: str | None = None, limit: int | None = None) -> dict:
        return {}

    def legacy_page(*, page: int | None = None, limit: int | None = None) -> dict:
        return {}

    api = SimpleNamespace(
        observations=SimpleNamespace(get_many=cursor_only),
        legacy=SimpleNamespace(observations_v1=SimpleNamespace(get_many=legacy_page)),
    )
    client = SimpleNamespace(api=api)
    method, mode = get_observations_list_method(client)  # type: ignore[misc]
    assert method is legacy_page
    assert mode == "page"


def test_observations_list_uses_cursor_when_no_page_route() -> None:
    """List-method helper should fall through to cursor mode when nothing else exists."""

    def cursor_only(*, cursor: str | None = None, limit: int | None = None) -> dict:
        return {}

    api = SimpleNamespace(observations=SimpleNamespace(get_many=cursor_only))
    client = SimpleNamespace(api=api)
    method, mode = get_observations_list_method(client)  # type: ignore[misc]
    assert method is cursor_only
    assert mode == "cursor"


def test_observations_list_returns_none_when_unsupported() -> None:
    """List-method helper should return ``None`` when no observation route is found."""
    client = SimpleNamespace(api=SimpleNamespace())
    assert get_observations_list_method(client) is None


# ---------- call_with_request_or_kwargs ----------


def test_dispatcher_uses_request_when_method_accepts_it() -> None:
    """Dispatcher should call ``method(request=...)`` when the v3 signature is present."""
    captured: dict[str, Any] = {}

    def v3_method(*, request: Any) -> str:
        captured["request"] = request
        return "v3"

    class _Req:
        def __init__(self, **kw: Any) -> None:
            self.__dict__.update(kw)

    result = call_with_request_or_kwargs(
        v3_method,
        lambda: _Req(name="alpha"),
        name="alpha",
    )
    assert result == "v3"
    assert captured["request"].name == "alpha"


def test_dispatcher_uses_kwargs_when_method_lacks_request() -> None:
    """Dispatcher should switch to direct kwargs against v4 signatures."""
    captured: dict[str, Any] = {}

    def v4_method(*, name: str) -> str:
        captured["name"] = name
        return "v4"

    result = call_with_request_or_kwargs(
        v4_method,
        lambda: pytest.fail("v3 builder should not run"),  # type: ignore[arg-type]
        name="beta",
    )
    assert result == "v4"
    assert captured["name"] == "beta"


def test_dispatcher_threads_path_kwargs_to_v3_branch() -> None:
    """Path identifiers should pass through to the v3 ``request=`` branch alongside the request body."""
    captured: dict[str, Any] = {}

    def v3_method(*, queue_id: str, item_id: str, request: Any) -> str:
        captured["queue_id"] = queue_id
        captured["item_id"] = item_id
        captured["request"] = request
        return "v3"

    class _Req:
        def __init__(self, **kw: Any) -> None:
            self.__dict__.update(kw)

    result = call_with_request_or_kwargs(
        v3_method,
        lambda: _Req(status="OPEN"),
        path_kwargs={"queue_id": "Q1", "item_id": "I1"},
        status="OPEN",
    )
    assert result == "v3"
    assert captured["queue_id"] == "Q1"
    assert captured["item_id"] == "I1"
    assert captured["request"].status == "OPEN"


def test_dispatcher_threads_path_kwargs_to_v4_branch() -> None:
    """Path identifiers should pass through to the v4 direct-kwargs branch alongside body kwargs."""
    captured: dict[str, Any] = {}

    def v4_method(*, queue_id: str, item_id: str, status: str) -> str:
        captured["queue_id"] = queue_id
        captured["item_id"] = item_id
        captured["status"] = status
        return "v4"

    result = call_with_request_or_kwargs(
        v4_method,
        lambda: pytest.fail("v3 builder should not run"),  # type: ignore[arg-type]
        path_kwargs={"queue_id": "Q1", "item_id": "I1"},
        status="OPEN",
    )
    assert result == "v4"
    assert captured["queue_id"] == "Q1"
    assert captured["item_id"] == "I1"
    assert captured["status"] == "OPEN"


def test_dispatcher_raises_on_unknown_method_shape() -> None:
    """Dispatcher must raise rather than silently default to v4 when shape is unknown."""

    class _Unsignable:
        """Callable wrapper whose signature ``inspect.signature`` cannot resolve."""

        def __call__(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - never invoked
            raise AssertionError("dispatcher should refuse to call this")

        @property
        def __signature__(self) -> Any:
            raise ValueError("signature unresolvable")

    with pytest.raises(RuntimeError, match="signature inspection failed"):
        call_with_request_or_kwargs(_Unsignable(), lambda: None, name="x")


def test_method_has_param_tri_state_returns_none_on_failure() -> None:
    """``method_has_param`` must return ``None`` (not ``False``) when introspection fails."""

    class _Unsignable:
        @property
        def __signature__(self) -> Any:
            raise ValueError("unresolvable")

        def __call__(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
            return None

    assert method_has_param(_Unsignable(), "request") is None


def test_method_has_param_returns_true_for_present_param() -> None:
    """Sanity check that ``method_has_param`` still returns explicit ``True`` for present params."""

    def has_request(*, request: Any) -> None:
        return None

    assert method_has_param(has_request, "request") is True


def test_method_has_param_returns_false_for_absent_param() -> None:
    """Sanity check that ``method_has_param`` returns explicit ``False`` for absent params."""

    def no_request(*, name: str) -> None:
        return None

    assert method_has_param(no_request, "request") is False


def test_observations_list_skips_legacy_v1_when_page_param_absent() -> None:
    """A legacy ``observations_v1.get_many`` lacking a ``page`` param must not be selected."""

    def cursor_only_obs(*, cursor: str | None = None, limit: int | None = None) -> dict:
        return {}

    def cursor_only_legacy(*, cursor: str | None = None, limit: int | None = None) -> dict:
        return {}

    api = SimpleNamespace(
        observations=SimpleNamespace(get_many=cursor_only_obs),
        legacy=SimpleNamespace(observations_v1=SimpleNamespace(get_many=cursor_only_legacy)),
    )
    client = SimpleNamespace(api=api)
    # legacy doesn't expose `page`, so the helper must fall through to cursor mode
    # rather than blindly trusting the legacy namespace's existence.
    method, mode = get_observations_list_method(client)  # type: ignore[misc]
    assert mode == "cursor"
    assert method is cursor_only_obs


def test_resolve_request_model_propagates_unrelated_module_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Broken transitive imports inside an existing langfuse module must not be silently swallowed."""
    broken_path = "langfuse.api.datasets.types.create_dataset_request"

    def faulting_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == broken_path:
            raise ModuleNotFoundError("No module named 'somethirdpartydep'", name="somethirdpartydep")
        raise ModuleNotFoundError(f"No module named {name!r}", name=name)

    monkeypatch.setattr("langfuse_mcp._compat.importlib.import_module", faulting_import)
    with pytest.raises(ModuleNotFoundError, match="somethirdpartydep"):
        resolve_request_model("datasets", "create_dataset_request", "CreateDatasetRequest")


# ---------- _extract_items_from_response (response.data + meta) ----------


def test_extract_items_preserves_meta_on_data_branch() -> None:
    """Response with ``.data`` + ``.meta`` should expose pagination, not collapse to ``{}``."""
    from langfuse_mcp.__main__ import _extract_items_from_response

    class CursorMeta:
        def __init__(self) -> None:
            self.cursor = "abc123"

    class CursorResponse:
        def __init__(self) -> None:
            self.data = ["a", "b"]
            self.meta = CursorMeta()

    items, pagination = _extract_items_from_response(CursorResponse())
    assert items == ["a", "b"]
    assert pagination.get("cursor") == "abc123"
