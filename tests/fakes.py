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
class FakeDataset:
    """Dataset record returned by the fake SDK."""

    id: str
    name: str
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    project_id: str = "project_1"
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class FakeDatasetItem:
    """Dataset item record returned by the fake SDK."""

    id: str
    dataset_id: str
    input: Any = None
    expected_output: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    source_trace_id: str | None = None
    source_observation_id: str | None = None
    status: str = "ACTIVE"
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class FakeAnnotationQueue:
    """Annotation queue record returned by the fake SDK."""

    id: str
    name: str
    description: str | None = None
    score_config_ids: list[str] = field(default_factory=list)
    created_at: datetime | None = None


@dataclass
class FakeAnnotationQueueItem:
    """Annotation queue item record returned by the fake SDK."""

    id: str
    queue_id: str
    object_id: str
    object_type: str
    status: str = "PENDING"
    created_at: datetime | None = None


@dataclass
class FakeScore:
    """Score record returned by the fake SDK."""

    id: str
    name: str
    value: Any
    trace_id: str
    data_type: str = "NUMERIC"
    user_id: str | None = None
    queue_id: str | None = None
    created_at: datetime | None = None


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

    @property
    def items(self) -> list[Any]:
        """Alias for data to match SDK response format."""
        return self.data

    @property
    def total(self) -> int | None:
        """Extract total from meta to match SDK response format."""
        return self.meta.get("total")


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


class _DatasetsAPI:
    """Fake implementation of datasets resource client."""

    def __init__(self, store: FakeDataStore) -> None:
        self._store = store
        self.last_list_kwargs: dict[str, Any] | None = None
        self.last_get_kwargs: dict[str, Any] | None = None
        self.last_create_kwargs: dict[str, Any] | None = None

    def list(self, **kwargs: Any) -> FakePaginatedResponse:
        self.last_list_kwargs = kwargs
        page = kwargs.get("page", 1)
        limit = kwargs.get("limit", 50)

        datasets = [ds.__dict__ for ds in self._store.datasets.values()]
        total = len(datasets)
        start = (page - 1) * limit
        end = start + limit
        paged = datasets[start:end]
        return FakePaginatedResponse(data=paged, meta={"next_page": None, "total": total})

    def get(self, dataset_name: str, **kwargs: Any) -> Any:
        self.last_get_kwargs = {"dataset_name": dataset_name, **kwargs}
        dataset = self._store.datasets.get(dataset_name)
        return dataset if dataset else None

    def create(self, *, request: Any, **kwargs: Any) -> FakeDataset:
        self.last_create_kwargs = {"request": request, **kwargs}
        now = datetime.now(timezone.utc)
        name = request.name if hasattr(request, "name") else request.get("name")
        description = getattr(request, "description", None) or request.get("description")
        metadata = getattr(request, "metadata", None) or request.get("metadata", {})

        dataset = FakeDataset(
            id=f"dataset_{name}",
            name=name,
            description=description,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )
        self._store.datasets[name] = dataset
        return dataset


class _DatasetItemsAPI:
    """Fake implementation of dataset_items resource client."""

    def __init__(self, store: FakeDataStore) -> None:
        self._store = store
        self.last_list_kwargs: dict[str, Any] | None = None
        self.last_get_kwargs: dict[str, Any] | None = None
        self.last_create_kwargs: dict[str, Any] | None = None
        self.last_delete_kwargs: dict[str, Any] | None = None

    def list(self, **kwargs: Any) -> FakePaginatedResponse:
        self.last_list_kwargs = kwargs
        dataset_name = kwargs.get("dataset_name")
        source_trace_id = kwargs.get("source_trace_id")
        source_observation_id = kwargs.get("source_observation_id")
        page = kwargs.get("page", 1)
        limit = kwargs.get("limit", 50)

        items = []
        for item in self._store.dataset_items.values():
            # Filter by dataset_name (via dataset_id lookup)
            if dataset_name:
                dataset = self._store.datasets.get(dataset_name)
                if not dataset or item.dataset_id != dataset.id:
                    continue
            if source_trace_id and item.source_trace_id != source_trace_id:
                continue
            if source_observation_id and item.source_observation_id != source_observation_id:
                continue
            items.append(item.__dict__)

        total = len(items)
        start = (page - 1) * limit
        end = start + limit
        paged = items[start:end]
        return FakePaginatedResponse(data=paged, meta={"next_page": None, "total": total})

    def get(self, id: str, **kwargs: Any) -> Any:
        self.last_get_kwargs = {"id": id, **kwargs}
        item = self._store.dataset_items.get(id)
        return item if item else None

    def create(self, *, request: Any, **kwargs: Any) -> FakeDatasetItem:
        self.last_create_kwargs = {"request": request, **kwargs}
        now = datetime.now(timezone.utc)

        # Extract fields from request object or dict
        dataset_name = getattr(request, "dataset_name", None) or request.get("dataset_name")
        item_id = getattr(request, "id", None) or request.get("id")
        input_data = getattr(request, "input", None) or request.get("input")
        expected_output = getattr(request, "expected_output", None) or request.get("expected_output")
        metadata = getattr(request, "metadata", None) or request.get("metadata", {})
        source_trace_id = getattr(request, "source_trace_id", None) or request.get("source_trace_id")
        source_observation_id = getattr(request, "source_observation_id", None) or request.get("source_observation_id")
        status = getattr(request, "status", None) or request.get("status", "ACTIVE")
        if hasattr(status, "value"):
            status = status.value

        # Get dataset_id from dataset_name
        dataset = self._store.datasets.get(dataset_name)
        dataset_id = dataset.id if dataset else f"dataset_{dataset_name}"

        # Generate ID if not provided
        if not item_id:
            item_id = f"item_{len(self._store.dataset_items) + 1}"

        item = FakeDatasetItem(
            id=item_id,
            dataset_id=dataset_id,
            input=input_data,
            expected_output=expected_output,
            metadata=metadata or {},
            source_trace_id=source_trace_id,
            source_observation_id=source_observation_id,
            status=status,
            created_at=now,
            updated_at=now,
        )
        self._store.dataset_items[item_id] = item
        return item

    def delete(self, id: str, **kwargs: Any) -> dict[str, Any]:
        self.last_delete_kwargs = {"id": id, **kwargs}
        if id in self._store.dataset_items:
            del self._store.dataset_items[id]
        return {"success": True}


class _AnnotationQueuesAPI:
    """Fake implementation of annotation_queues resource client."""

    def __init__(self, store: FakeDataStore) -> None:
        self._store = store
        self.last_list_queues_kwargs: dict[str, Any] | None = None
        self.last_create_queue_kwargs: dict[str, Any] | None = None
        self.last_get_queue_kwargs: dict[str, Any] | None = None
        self.last_list_items_kwargs: dict[str, Any] | None = None
        self.last_get_item_kwargs: dict[str, Any] | None = None

    def list_queues(self, **kwargs: Any) -> FakePaginatedResponse:
        self.last_list_queues_kwargs = kwargs
        queues = [q.__dict__ for q in self._store.annotation_queues.values()]
        return FakePaginatedResponse(data=queues, meta={"next_page": None, "total": len(queues)})

    def create_queue(self, *, request: Any, **kwargs: Any) -> FakeAnnotationQueue:
        self.last_create_queue_kwargs = {"request": request, **kwargs}
        now = datetime.now(timezone.utc)
        name = getattr(request, "name", None) or request.get("name")
        description = getattr(request, "description", None) or request.get("description")
        score_config_ids = getattr(request, "score_config_ids", None) or request.get("score_config_ids", []) or []
        queue = FakeAnnotationQueue(
            id=f"queue_{len(self._store.annotation_queues) + 1}",
            name=name,
            description=description,
            score_config_ids=list(score_config_ids),
            created_at=now,
        )
        self._store.annotation_queues[queue.id] = queue
        return queue

    def get_queue(self, queue_id: str, **kwargs: Any) -> Any:
        self.last_get_queue_kwargs = {"queue_id": queue_id, **kwargs}
        return self._store.annotation_queues.get(queue_id)

    def list_queue_items(self, queue_id: str, **kwargs: Any) -> FakePaginatedResponse:
        self.last_list_items_kwargs = {"queue_id": queue_id, **kwargs}
        items = [item.__dict__ for item in self._store.annotation_queue_items.values() if item.queue_id == queue_id]
        return FakePaginatedResponse(data=items, meta={"next_page": None, "total": len(items)})

    def get_queue_item(self, queue_id: str, item_id: str, **kwargs: Any) -> Any:
        self.last_get_item_kwargs = {"queue_id": queue_id, "item_id": item_id, **kwargs}
        item = self._store.annotation_queue_items.get(item_id)
        return item if item and item.queue_id == queue_id else None

    def create_queue_item(self, queue_id: str, *, request: Any, **kwargs: Any) -> FakeAnnotationQueueItem:
        now = datetime.now(timezone.utc)
        object_id = getattr(request, "object_id", None) or request.get("object_id")
        object_type = getattr(request, "object_type", None) or request.get("object_type")
        status = getattr(request, "status", None) or request.get("status") or "PENDING"
        item = FakeAnnotationQueueItem(
            id=f"queue_item_{len(self._store.annotation_queue_items) + 1}",
            queue_id=queue_id,
            object_id=object_id,
            object_type=object_type,
            status=status.value if hasattr(status, "value") else status,
            created_at=now,
        )
        self._store.annotation_queue_items[item.id] = item
        return item

    def update_queue_item(self, queue_id: str, item_id: str, *, request: Any, **kwargs: Any) -> Any:
        item = self._store.annotation_queue_items.get(item_id)
        if item and item.queue_id == queue_id:
            status = getattr(request, "status", None) or request.get("status")
            item.status = status.value if hasattr(status, "value") else status
            return item
        return None

    def delete_queue_item(self, queue_id: str, item_id: str, **kwargs: Any) -> dict[str, Any]:
        item = self._store.annotation_queue_items.get(item_id)
        if item and item.queue_id == queue_id:
            del self._store.annotation_queue_items[item_id]
        return {"success": True}

    def create_queue_assignment(self, queue_id: str, *, request: Any, **kwargs: Any) -> dict[str, Any]:
        user_id = getattr(request, "user_id", None) or request.get("user_id")
        self._store.queue_assignments.setdefault(queue_id, set()).add(user_id)
        return {"success": True, "queue_id": queue_id, "user_id": user_id}

    def delete_queue_assignment(self, queue_id: str, *, request: Any, **kwargs: Any) -> dict[str, Any]:
        user_id = getattr(request, "user_id", None) or request.get("user_id")
        self._store.queue_assignments.setdefault(queue_id, set()).discard(user_id)
        return {"success": True, "queue_id": queue_id, "user_id": user_id}


class _ScoreV2API:
    """Fake implementation of score_v_2 resource client."""

    def __init__(self, store: FakeDataStore) -> None:
        self._store = store
        self.last_get_kwargs: dict[str, Any] | None = None
        self.last_get_by_id_kwargs: dict[str, Any] | None = None

    def get(self, **kwargs: Any) -> FakePaginatedResponse:
        self.last_get_kwargs = kwargs
        from_timestamp = kwargs.get("from_timestamp")
        if from_timestamp is not None and not isinstance(from_timestamp, datetime):
            raise TypeError("from_timestamp must be datetime")
        to_timestamp = kwargs.get("to_timestamp")
        if to_timestamp is not None and not isinstance(to_timestamp, datetime):
            raise TypeError("to_timestamp must be datetime")
        value = kwargs.get("value")
        if value is not None and not isinstance(value, float):
            raise TypeError("value must be float")

        scores = [s.__dict__ for s in self._store.scores.values()]
        user_id = kwargs.get("user_id")
        if user_id:
            scores = [s for s in scores if s.get("user_id") == user_id]
        queue_id = kwargs.get("queue_id")
        if queue_id:
            scores = [s for s in scores if s.get("queue_id") == queue_id]
        trace_id = kwargs.get("trace_id")
        if trace_id:
            scores = [s for s in scores if s.get("trace_id") == trace_id]
        return FakePaginatedResponse(data=scores, meta={"next_page": None, "total": len(scores)})

    def get_by_id(self, score_id: str, **kwargs: Any) -> Any:
        self.last_get_by_id_kwargs = {"score_id": score_id, **kwargs}
        return self._store.scores.get(score_id)


class FakeAPI:
    """Aggregate object exposed via FakeLangfuse.api."""

    def __init__(self, store: FakeDataStore) -> None:
        """Wire the fake API resources to the shared backing store."""
        self.trace = _TraceAPI(store)
        self.observations = _ObservationsAPI(store)
        self.sessions = _SessionsAPI(store)
        self.prompts = _PromptsAPI(store)
        self.datasets = _DatasetsAPI(store)
        self.dataset_items = _DatasetItemsAPI(store)
        self.annotation_queues = _AnnotationQueuesAPI(store)
        self.score_v_2 = _ScoreV2API(store)


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
        self.datasets: dict[str, FakeDataset] = {}
        self.dataset_items: dict[str, FakeDatasetItem] = {}
        self.annotation_queues: dict[str, FakeAnnotationQueue] = {
            "queue_1": FakeAnnotationQueue(
                id="queue_1",
                name="default-annotation-queue",
                description="seed queue",
                score_config_ids=[],
                created_at=now,
            )
        }
        self.annotation_queue_items: dict[str, FakeAnnotationQueueItem] = {}
        self.queue_assignments: dict[str, set[str]] = {}
        self.scores: dict[str, FakeScore] = {
            "score_1": FakeScore(
                id="score_1",
                name="quality",
                value=0.91,
                trace_id="trace_1",
                data_type="NUMERIC",
                user_id="user_1",
                queue_id="queue_1",
                created_at=now,
            )
        }


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

    def create_dataset(
        self,
        *,
        name: str,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> FakeDataset:
        """Create a fake dataset and return it."""
        now = datetime.now(timezone.utc)
        dataset = FakeDataset(
            id=f"dataset_{name}",
            name=name,
            description=description,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )
        self._store.datasets[name] = dataset
        return dataset

    def create_dataset_item(
        self,
        *,
        dataset_name: str,
        input: Any = None,
        expected_output: Any = None,
        metadata: dict[str, Any] | None = None,
        source_trace_id: str | None = None,
        source_observation_id: str | None = None,
        id: str | None = None,
        status: str | None = None,
        **kwargs: Any,
    ) -> FakeDatasetItem:
        """Create a fake dataset item and return it."""
        now = datetime.now(timezone.utc)
        dataset = self._store.datasets.get(dataset_name)
        dataset_id = dataset.id if dataset else f"dataset_{dataset_name}"
        item_id = id or f"item_{len(self._store.dataset_items) + 1}"

        item = FakeDatasetItem(
            id=item_id,
            dataset_id=dataset_id,
            input=input,
            expected_output=expected_output,
            metadata=metadata or {},
            source_trace_id=source_trace_id,
            source_observation_id=source_observation_id,
            status=status or "ACTIVE",
            created_at=now,
            updated_at=now,
        )
        self._store.dataset_items[item_id] = item
        return item

    def get_dataset(self, name: str, **kwargs: Any) -> FakeDataset | None:
        """Fetch a dataset by name."""
        return self._store.datasets.get(name)

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
