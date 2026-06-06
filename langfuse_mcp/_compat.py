"""Capability-based compatibility helpers for Langfuse SDK v3 and v4.

The Langfuse Python SDK reorganized several namespaces between v3.x and v4.x:

- ``langfuse.api.resources.<x>.types.<y>`` was flattened to ``langfuse.api.<x>.types.<y>``.
- ``client.api.score_v_2`` was renamed to ``client.api.scores`` (with method
  ``get`` -> ``get_many``).
- ``client.api.observations.get(observation_id=...)`` was removed; the v1
  legacy route at ``client.api.legacy.observations_v1`` remains page-based.
- Several ``api.<resource>.create*`` and ``update*`` methods now take direct
  kwargs instead of a Pydantic ``request=...`` model.

This module exposes small, capability-based helpers — branching is done on
*what the client actually exposes* rather than on a sniffed version string,
which avoids the rot of version-coupled flags.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from typing import Any, Literal

ObservationListMode = Literal["page", "cursor"]


def resolve_request_model(category: str, module: str, name: str) -> Any:
    """Import a request-model class from either v4 or v3 paths.

    v4 path:  ``langfuse.api.<category>.types.<module>.<name>``
    v3 path:  ``langfuse.api.resources.<category>.types.<module>.<name>``

    Used only by the v3 ``request=<model>`` branch of the API; v4 callers pass
    direct kwargs and never need to materialize the model. When neither path
    exists (test stubs that mock ``langfuse`` as an empty module, partial SDK
    installs) the function falls back to ``dict`` so callers can still
    construct a request payload via ``Model(**kwargs)``. Only
    ``ModuleNotFoundError`` from absent candidate paths is swallowed —
    ``ImportError`` raised from inside an existing langfuse module (broken
    install, transitive dep failure) is allowed to propagate so genuine
    SDK breakage is not masked.
    """
    candidates = (
        f"langfuse.api.{category}.types.{module}",
        f"langfuse.api.resources.{category}.types.{module}",
    )
    for path in candidates:
        try:
            mod = importlib.import_module(path)
        except ModuleNotFoundError as exc:
            # Only swallow the specific case where this candidate path doesn't
            # exist. ImportError (and other ModuleNotFoundError instances that
            # name a *different* missing module) signal a real SDK problem.
            if exc.name and (exc.name == path or path.startswith(f"{exc.name}.")):
                continue
            raise
        if hasattr(mod, name):
            return getattr(mod, name)
    return dict


def get_score_namespace(client: Any) -> Any | None:
    """Return the score-resource namespace, preferring the v4 ``scores`` name.

    v4: ``client.api.scores`` (methods: ``get_many``, ``get_by_id``).
    v3: ``client.api.score_v_2`` (methods: ``get``, ``get_by_id``).
    Returns ``None`` if neither is present.
    """
    api = getattr(client, "api", None)
    if api is None:
        return None
    return getattr(api, "scores", None) or getattr(api, "score_v_2", None)


def get_score_list_method(scores_namespace: Any) -> Any | None:
    """Return the list-many callable on a score namespace.

    v4 exposes ``get_many``; v3 exposes ``get`` (singular). Returns ``None``
    when neither is present, so callers can degrade gracefully.
    """
    return getattr(scores_namespace, "get_many", None) or getattr(scores_namespace, "get", None)


def get_metrics_method(client: Any) -> tuple[Callable[..., Any], Literal["v2", "legacy"]] | None:
    """Return ``(callable, mode)`` for the metrics query endpoint, or ``None``.

    Prefers v2 (``client.api.metrics_v_2.metrics`` -> ``"v2"``) over legacy
    (``client.api.metrics.metrics`` -> ``"legacy"``). Both accept ``query=<json
    string>``. Presence is an attribute check only: the v2 *HTTP* endpoint is
    Langfuse Cloud-only, so the callable can exist while the server answers 404
    at call time — that 404 is handled by the caller, not here.
    """
    api = getattr(client, "api", None)
    if api is None:
        return None
    v2 = getattr(api, "metrics_v_2", None)
    if v2 is not None and hasattr(v2, "metrics"):
        return v2.metrics, "v2"
    legacy = getattr(api, "metrics", None)
    if legacy is not None and hasattr(legacy, "metrics"):
        return legacy.metrics, "legacy"
    return None


def get_observations_single_fetcher(client: Any) -> Callable[[str], Any] | None:
    """Return a callable ``f(observation_id) -> observation`` or ``None``.

    Precedence:
    1. ``client.api.observations.get(observation_id=...)`` (v3)
    2. ``client.api.legacy.observations_v1.get(observation_id)`` (v4 legacy
       route — page-based, self-host safe)
    3. ``client.fetch_observation(observation_id)`` (legacy v2 top-level)
    """
    api = getattr(client, "api", None)
    if api is not None:
        observations = getattr(api, "observations", None)
        if observations is not None and hasattr(observations, "get"):
            return lambda obs_id: observations.get(observation_id=obs_id)

        legacy = getattr(api, "legacy", None)
        legacy_v1 = getattr(legacy, "observations_v1", None) if legacy is not None else None
        if legacy_v1 is not None and hasattr(legacy_v1, "get"):
            return lambda obs_id: legacy_v1.get(obs_id)

    if hasattr(client, "fetch_observation"):

        def _via_top_level(obs_id: str) -> Any:
            response = client.fetch_observation(obs_id)
            return getattr(response, "data", response)

        return _via_top_level

    return None


def get_observations_list_method(client: Any) -> tuple[Any, ObservationListMode] | None:
    """Return (callable, mode) for listing observations.

    Mode is one of:
    - ``"page"``: callable accepts ``page=`` + ``limit=`` (v3 / v4 legacy_v1)
    - ``"cursor"``: callable accepts ``cursor=`` + ``limit=`` (v4 observations_v2)

    Precedence prefers page-capable routes so the MCP tool's ``page`` input
    keeps its current semantics:
    1. ``client.api.observations.get_many`` if it has a ``page`` param (v3)
    2. ``client.api.legacy.observations_v1.get_many`` if it has a ``page`` param (v4 legacy)
    3. ``client.api.observations.get_many`` cursor mode (v4 observations_v2)

    Each candidate is verified by signature inspection — namespace presence
    alone is not sufficient evidence of a page-capable contract.
    """
    api = getattr(client, "api", None)
    if api is None:
        return None

    observations = getattr(api, "observations", None)
    if observations is not None:
        get_many = getattr(observations, "get_many", None)
        if get_many is not None and method_has_param(get_many, "page") is True:
            return get_many, "page"

    legacy = getattr(api, "legacy", None)
    legacy_v1 = getattr(legacy, "observations_v1", None) if legacy is not None else None
    if legacy_v1 is not None:
        legacy_get_many = getattr(legacy_v1, "get_many", None)
        if legacy_get_many is not None and method_has_param(legacy_get_many, "page") is True:
            return legacy_get_many, "page"

    if observations is not None:
        get_many = getattr(observations, "get_many", None)
        if get_many is not None and method_has_param(get_many, "cursor") is True:
            return get_many, "cursor"

    return None


def call_with_request_or_kwargs(
    method: Callable[..., Any],
    build_v3_request: Callable[[], Any],
    /,
    *,
    path_kwargs: dict[str, Any] | None = None,
    **body_kwargs: Any,
) -> Any:
    """Dispatch a write call across v3 (request=Pydantic) and v4 (direct kwargs).

    v3 SDK call shape: ``method(**path_kwargs, request=<request_model>)``
    v4 SDK call shape: ``method(**path_kwargs, **body_kwargs)``

    ``path_kwargs`` carries identifiers that appear in BOTH call shapes
    (``queue_id``, ``item_id``, ...). They are passed by keyword in both paths
    so the dispatcher does not depend on positional binding through
    ``functools.partial``, which mishandles keyword-only path params on
    hypothetical SDK shapes.

    ``body_kwargs`` are the v4 direct-kwargs payload; the v3 path receives them
    via ``build_v3_request()`` instead.

    Dispatch is decided by inspecting the method signature for a ``request``
    parameter. ``method_has_param`` is tri-state — when signature inspection
    fails the dispatcher raises rather than silently choosing the v4 branch.
    """
    has_request = method_has_param(method, "request")
    path_kwargs = path_kwargs or {}
    if has_request is True:
        return method(**path_kwargs, request=build_v3_request())
    if has_request is False:
        return method(**path_kwargs, **body_kwargs)
    raise RuntimeError(
        f"Cannot determine call shape for {getattr(method, '__qualname__', method)!r}: "
        f"signature inspection failed and dispatch requires a definite "
        f"v3 (request=PydanticModel) vs v4 (direct kwargs) decision."
    )


def method_has_param(method: Callable[..., Any], name: str) -> bool | None:
    """Return tri-state presence of parameter ``name`` on ``method``.

    Returns:
        - ``True`` — signature was inspected and ``name`` is a parameter
        - ``False`` — signature was inspected and ``name`` is not a parameter
        - ``None`` — signature could not be inspected (C extension, exotic
          callable wrapper). Callers must treat this as *unknown*; conflating
          it with ``False`` is the bug that hides v4-on-v3 dispatch errors.
    """
    try:
        params = inspect.signature(method).parameters
    except (TypeError, ValueError):
        return None
    return name in params
