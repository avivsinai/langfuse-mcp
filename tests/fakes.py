"""Fake classes for testing langfuse-mcp against the Langfuse v3 API surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class FakeTrace:
    """Simple trace record returned by the fake SDK."""

    id: str
    name: str
    user_id: str | None
    session_id: str | None
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)


@dataclass
class FakeObservation:
    """Observation representation compatible with _sdk_object_to_python."""

    id: str
    type: str
    name: str
    status: str
    start_time: datetime
    end_time: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FakeSession:
    """Session object returned by the fake sessions API."""

    id: str
    user_id: str
    created_at: datetime
    trace_ids: list[str] = field(default_factory=list)


@dataclass
class FakePromptBase:
    """Base prompt record used by fake prompt APIs."""

    id: str
    name: str
    version: int
    type: str
    labels: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    commit_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class FakeTextPrompt(FakePromptBase):
    """Fake text prompt record."""

    prompt: str = ""


@dataclass
class FakeChatPrompt(FakePromptBase):
    """Fake chat prompt record."""

    messages: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FakePaginatedResponse:
    """Minimal paginated response with data/meta attributes."""

    data: list[Any]
    meta: dict[str, Any]


class _TraceAPI:
    """Fake implementation of the v3 trace resource client."""

    def __init__(self, store: FakeDataStore) -> None:
        self._store = store
        self.last_list_kwargs: dict[str, Any] | None = None
        self.last_get_kwargs: dict[str, Any] | None = None

    def list(self, **kwargs: Any) -> FakePaginatedResponse:
        self.last_list_kwargs = kwargs
        traces = list(self._store.traces.values())

        # Expand observation ids if requested via fields
        fields = kwargs.get("fields") or ""
        if "observations" in fields:
            enriched = []
            for trace in traces:
                obs = [self._store.observations[o_id] for o_id in trace.observations]
                enriched.append({**trace.__dict__, "observations": [ob.__dict__ for ob in obs]})
            data: list[Any] = enriched
        else:
            data = [trace.__dict__ for trace in traces]

        return FakePaginatedResponse(data=data, meta={"next_page": None, "total": len(data)})

    def get(self, trace_id: str, **kwargs: Any) -> dict[str, Any]:
        self.last_get_kwargs = {"trace_id": trace_id, **kwargs}
        trace = self._store.traces.get(trace_id)
        if not trace:
            return {}

        include_observations = "fields" in kwargs and kwargs["fields"]
        if include_observations and "observations" in kwargs["fields"]:
            obs = [self._store.observations[o_id] for o_id in trace.observations]
            return {**trace.__dict__, "observations": [ob.__dict__ for ob in obs]}
        return trace.__dict__


class _ObservationsAPI:
    """Fake implementation of observations resource client."""

    def __init__(self, store: FakeDataStore) -> None:
        self._store = store
        self.last_get_many_kwargs: dict[str, Any] | None = None
        self.last_get_kwargs: dict[str, Any] | None = None

    def get_many(self, **kwargs: Any) -> FakePaginatedResponse:
        self.last_get_many_kwargs = kwargs
        observations = list(self._store.observations.values())
        data = [obs.__dict__ for obs in observations]
        return FakePaginatedResponse(data=data, meta={"next_page": None, "total": len(data)})

    def get(self, observation_id: str, **kwargs: Any) -> dict[str, Any]:
        self.last_get_kwargs = {"observation_id": observation_id, **kwargs}
        obs = self._store.observations.get(observation_id)
        return obs.__dict__ if obs else {}


class _SessionsAPI:
    """Fake implementation of sessions resource client."""

    def __init__(self, store: FakeDataStore) -> None:
        self._store = store
        self.last_list_kwargs: dict[str, Any] | None = None
        self.last_get_kwargs: dict[str, Any] | None = None

    def list(self, **kwargs: Any) -> FakePaginatedResponse:
        self.last_list_kwargs = kwargs
        sessions = [session.__dict__ for session in self._store.sessions.values()]
        return FakePaginatedResponse(data=sessions, meta={"next_page": None, "total": len(sessions)})

    def get(self, session_id: str, **kwargs: Any) -> dict[str, Any]:
        self.last_get_kwargs = {"session_id": session_id, **kwargs}
        session = self._store.sessions.get(session_id)
        return session.__dict__ if session else {}


class _PromptsAPI:
    """Fake implementation of prompts resource client."""

    def __init__(self, store: FakeDataStore) -> None:
        self._store = store
        self.last_list_kwargs: dict[str, Any] | None = None
        self.last_get_kwargs: dict[str, Any] | None = None

    def list(self, **kwargs: Any) -> FakePaginatedResponse:
        self.last_list_kwargs = kwargs
        name_filter = kwargs.get("name")
        label_filter = kwargs.get("label")
        tag_filter = kwargs.get("tag")
        page = kwargs.get("page", 1)
        limit = kwargs.get("limit", 50)

        items = []
        for name, versions in self._store.prompts.items():
            if name_filter and name != name_filter:
                continue
            if label_filter and not any(label_filter in p.labels for p in versions):
                continue
            if tag_filter and not any(tag_filter in (p.tags or []) for p in versions):
                continue

            latest = versions[-1]
            item = {
                "name": name,
                "type": latest.type,
                "versions": [p.version for p in versions],
                "labels": latest.labels,
                "tags": latest.tags,
                "lastUpdatedAt": latest.updated_at.isoformat() if latest.updated_at else None,
                "lastConfig": latest.config,
            }
            items.append(item)

        total = len(items)
        start = (page - 1) * limit
        end = start + limit
        paged = items[start:end]
        return FakePaginatedResponse(data=paged, meta={"next_page": None, "total": total})

    def get(self, name: str, **kwargs: Any) -> Any:
        self.last_get_kwargs = {"name": name, **kwargs}
        label = kwargs.get("label")
        version = kwargs.get("version")
        versions = self._store.prompts.get(name, [])
        if not versions:
            return None
        if version is not None:
            for prompt in versions:
                if prompt.version == version:
                    return prompt
            return None
        if label is not None:
            for prompt in versions:
                if label in prompt.labels:
                    return prompt
            return None
        return versions[-1]


class FakeAPI:
    """Aggregate object exposed via FakeLangfuse.api."""

    def __init__(self, store: FakeDataStore) -> None:
        """Wire the fake API resources to the shared backing store."""
        self.trace = _TraceAPI(store)
        self.observations = _ObservationsAPI(store)
        self.sessions = _SessionsAPI(store)
        self.prompts = _PromptsAPI(store)


class FakeDataStore:
    """In-memory backing store shared across fake API resources."""

    def __init__(self) -> None:
        """Seed deterministic trace, observation, and session fixtures."""
        now = datetime(2023, 1, 1, tzinfo=timezone.utc)
        self.observations: dict[str, FakeObservation] = {
            "obs_1": FakeObservation(
                id="obs_1",
                type="SPAN",
                name="root_span",
                status="SUCCEEDED",
                start_time=now,
                end_time=now,
                metadata={"code.filepath": "app.py"},
                events=[{"attributes": {"exception.type": "ValueError"}}],
            )
        }
        self.traces: dict[str, FakeTrace] = {
            "trace_1": FakeTrace(
                id="trace_1",
                name="test-trace",
                user_id="user_1",
                session_id="session_1",
                created_at=now,
                metadata={},
                tags=["unit-test"],
                observations=["obs_1"],
            )
        }
        self.sessions: dict[str, FakeSession] = {
            "session_1": FakeSession(
                id="session_1",
                user_id="user_1",
                created_at=now,
                trace_ids=["trace_1"],
            )
        }
        self.prompts: dict[str, list[FakePromptBase]] = {}


class FakeLangfuse:
    """Langfuse client double exposing the real v3 API surface."""

    def __init__(self) -> None:
        """Initialise the fake client with in-memory storage and API facade."""
        self._store = FakeDataStore()
        self.api = FakeAPI(self._store)
        self.closed = False
        self.last_create_kwargs: dict[str, Any] | None = None
        self.last_update_kwargs: dict[str, Any] | None = None

    def create_prompt(
        self,
        *,
        name: str,
        prompt: Any,
        labels: list[str] | None = None,
        tags: list[str] | None = None,
        type: str = "text",
        config: dict[str, Any] | None = None,
        commit_message: str | None = None,
        **kwargs: Any,
    ) -> FakePromptBase:
        """Create a fake prompt and return it."""
        if labels is not None and not isinstance(labels, list):
            labels = None
        if tags is not None and not isinstance(tags, list):
            tags = None
        if config is not None and not isinstance(config, dict):
            config = None
        if commit_message is not None and not isinstance(commit_message, str):
            commit_message = None

        self.last_create_kwargs = {
            "name": name,
            "prompt": prompt,
            "labels": labels,
            "tags": tags,
            "type": type,
            "config": config,
            "commit_message": commit_message,
            **kwargs,
        }

        versions = self._store.prompts.setdefault(name, [])
        version = len(versions) + 1
        now = datetime.now(timezone.utc)

        base_kwargs = {
            "id": f"prompt_{name}_{version}",
            "name": name,
            "version": version,
            "type": type,
            "labels": list(labels or []),
            "tags": list(tags or []) if tags is not None else [],
            "config": config or {},
            "commit_message": commit_message,
            "created_at": now,
            "updated_at": now,
        }

        if type == "chat":
            prompt_obj: FakePromptBase = FakeChatPrompt(messages=prompt, **base_kwargs)
        else:
            prompt_obj = FakeTextPrompt(prompt=prompt, **base_kwargs)

        versions.append(prompt_obj)
        return prompt_obj

    def update_prompt(self, *, name: str, version: int, new_labels: list[str] | None = None) -> FakePromptBase:
        """Update labels for a prompt version."""
        self.last_update_kwargs = {"name": name, "version": version, "new_labels": new_labels}
        versions = self._store.prompts.get(name, [])
        if not versions:
            raise LookupError(f"Prompt '{name}' not found")

        updated = None
        new_labels_list = list(new_labels or [])
        for prompt in versions:
            if prompt.version == version:
                # Add new labels while preserving existing ones (new labels first).
                merged = list(dict.fromkeys([*new_labels_list, *prompt.labels]))
                prompt.labels = merged
                prompt.updated_at = datetime.now(timezone.utc)
                updated = prompt
            else:
                if new_labels_list:
                    prompt.labels = [label for label in prompt.labels if label not in new_labels_list]

        if updated is None:
            raise LookupError(f"Prompt '{name}' version {version} not found")

        return updated

    def get_prompt(self, name: str, label: str | None = None, version: int | None = None, **kwargs: Any) -> Any:
        """Fetch a prompt by name, optional label or version."""
        versions = self._store.prompts.get(name, [])
        if not versions:
            return None
        if version is not None:
            for prompt in versions:
                if prompt.version == version:
                    return prompt
            return None
        if label is not None:
            for prompt in versions:
                if label in prompt.labels:
                    return prompt
            return None
        return versions[-1]

    def close(self) -> None:
        """Mark the fake client as closed to mirror the real SDK."""
        self.closed = True

    # Backwards compatibility for cleanup logic.
    def flush(self) -> None:  # pragma: no cover - compatibility shim
        """No-op for compatibility with legacy cleanup hooks."""
        return None

    def shutdown(self) -> None:  # pragma: no cover - compatibility shim
        """Provide the Langfuse SDK shutdown hook by delegating to close()."""
        self.close()


class FakeContext:
    """Mimic `mcp.server.fastmcp.Context` used by the tools."""

    def __init__(self, state: Any) -> None:
        """Expose the minimal request context consumed by tool implementations."""
        self.request_context = type("_RC", (), {"lifespan_context": state})
