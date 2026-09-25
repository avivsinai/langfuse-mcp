"""Fake classes for testing langfuse-mcp against the Langfuse v3 API surface."""

from __future__ import annotations

import json
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
    """Observation representation compatible with _sdk_object_to_python.

    Mirrors the real API shape (level/status_message; no ``events`` — the API never returns them).
    """

    id: str
    type: str
    name: str
    status: str
    start_time: datetime
    end_time: datetime
    trace_id: str | None = None
    parent_observation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    level: str = "DEFAULT"
    status_message: str | None = None
    input: Any = None
    output: Any = None
    total_cost: float | None = None


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
class FakeDatasetRun:
    """Dataset run record returned by the fake SDK."""

    id: str
    dataset_id: str
    dataset_name: str
    name: str
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class FakeDatasetRunItem:
    """Dataset run item record returned by the fake SDK."""

    id: str
    dataset_id: str
    dataset_item_id: str
    run_name: str
    run_description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    observation_id: str | None = None
    trace_id: str | None = None
    dataset_version: datetime | None = None
    created_at: datetime | None = None


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
    """Minimal paginated response mirroring the real SDK shape (``data`` + ``meta``).

    Real Langfuse SDK responses (``Traces``, ``PaginatedSessions``, ``ObservationsV2Response``,
    etc.) carry only ``data`` and ``meta`` — no ``items`` or ``total`` attribute aliases. The
    fake intentionally omits those aliases so the response-extraction logic in
    ``_extract_items_from_response`` exercises the same ``.data + .meta`` code path as
    against a real client.
    """

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

    def get(self, trace_id: str, *, request_options: dict[str, Any] | None = None) -> dict[str, Any]:
        self.last_get_kwargs = {"trace_id": trace_id}
        if request_options is not None:
            self.last_get_kwargs["request_options"] = request_options
        trace = self._store.traces.get(trace_id)
        if not trace:
            return {}

        query_params = (request_options or {}).get("additional_query_parameters", {})
        fields = query_params.get("fields", "")
        include_observations = bool(fields)
        if include_observations and "observations" in fields:
            obs = [self._store.observations[o_id] for o_id in trace.observations]
            return {**trace.__dict__, "observations": [ob.__dict__ for ob in obs]}
        return trace.__dict__


class _ObservationsAPI:
    """Fake implementation of the v3 observations resource client (page-based ``get_many``)."""

    def __init__(self, store: FakeDataStore) -> None:
        self._store = store
        self.last_get_many_kwargs: dict[str, Any] | None = None
        self.last_get_kwargs: dict[str, Any] | None = None

    def get_many(
        self,
        *,
        page: int | None = None,
        limit: int | None = None,
        level: str | None = None,
        from_start_time: Any = None,
        to_start_time: Any = None,
        trace_id: str | None = None,
        name: str | None = None,
        user_id: str | None = None,
        type: str | None = None,
        parent_observation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> FakePaginatedResponse:
        """Return observations using v3 page-based pagination."""
        self.last_get_many_kwargs = {
            "page": page,
            "limit": limit,
            **{k: v for k, v in (("level", level), ("trace_id", trace_id), ("type", type)) if v is not None},
            **kwargs,
        }
        observations = list(self._store.observations.values())
        if level is not None:
            observations = [obs for obs in observations if obs.level == level]
        if trace_id is not None:
            observations = [obs for obs in observations if obs.trace_id == trace_id]
        data = [obs.__dict__ for obs in observations]
        return FakePaginatedResponse(data=data, meta={"next_page": None, "total": len(data)})

    def get(self, observation_id: str, **kwargs: Any) -> dict[str, Any]:
        """Return a single observation by id (v3 positional-or-keyword signature)."""
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
        self.last_get_runs_kwargs: dict[str, Any] | None = None
        self.last_get_run_kwargs: dict[str, Any] | None = None
        self.last_delete_run_kwargs: dict[str, Any] | None = None

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

    def get_runs(self, dataset_name: str, **kwargs: Any) -> FakePaginatedResponse:
        self.last_get_runs_kwargs = {"dataset_name": dataset_name, **kwargs}
        page = kwargs.get("page", 1)
        limit = kwargs.get("limit", 50)
        dataset = self._store.datasets.get(dataset_name)
        runs = []
        if dataset is not None:
            runs = [run.__dict__ for run in self._store.dataset_runs.values() if run.dataset_id == dataset.id]

        total = len(runs)
        start = (page - 1) * limit
        end = start + limit
        return FakePaginatedResponse(data=runs[start:end], meta={"next_page": None, "total": total})

    def get_run(self, dataset_name: str, run_name: str, **kwargs: Any) -> Any:
        self.last_get_run_kwargs = {"dataset_name": dataset_name, "run_name": run_name, **kwargs}
        dataset = self._store.datasets.get(dataset_name)
        if dataset is None:
            return None
        run = self._store.dataset_runs.get((dataset.id, run_name))
        if run is None:
            return None
        data = run.__dict__.copy()
        run_items = []
        for item in self._store.dataset_run_items.values():
            if item.dataset_id == dataset.id and item.run_name == run_name:
                run_items.append(item.__dict__)
        data["items"] = run_items
        return data

    def delete_run(self, dataset_name: str, run_name: str, **kwargs: Any) -> dict[str, Any]:
        self.last_delete_run_kwargs = {"dataset_name": dataset_name, "run_name": run_name, **kwargs}
        dataset = self._store.datasets.get(dataset_name)
        if dataset is not None:
            self._store.dataset_runs.pop((dataset.id, run_name), None)
            self._store.dataset_run_items = {
                key: item
                for key, item in self._store.dataset_run_items.items()
                if not (item.dataset_id == dataset.id and item.run_name == run_name)
            }
        return {"success": True}


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


class _DatasetRunItemsAPI:
    """Fake implementation of dataset_run_items resource client."""

    def __init__(self, store: FakeDataStore) -> None:
        self._store = store
        self.last_list_kwargs: dict[str, Any] | None = None
        self.last_create_kwargs: dict[str, Any] | None = None

    def list(self, **kwargs: Any) -> FakePaginatedResponse:
        self.last_list_kwargs = kwargs
        dataset_id = kwargs.get("dataset_id")
        run_name = kwargs.get("run_name")
        page = kwargs.get("page", 1)
        limit = kwargs.get("limit", 50)

        items = []
        for item in self._store.dataset_run_items.values():
            if item.dataset_id == dataset_id and item.run_name == run_name:
                items.append(item.__dict__)
        total = len(items)
        start = (page - 1) * limit
        end = start + limit
        return FakePaginatedResponse(data=items[start:end], meta={"next_page": None, "total": total})

    def create(self, *, request: Any, **kwargs: Any) -> FakeDatasetRunItem:
        self.last_create_kwargs = {"request": request, **kwargs}

        def request_value(field: str) -> Any:
            if isinstance(request, dict):
                return request.get(field)
            return getattr(request, field, None)

        return self._create_run_item(
            run_name=request_value("run_name"),
            dataset_item_id=request_value("dataset_item_id"),
            run_description=request_value("run_description"),
            metadata=request_value("metadata"),
            observation_id=request_value("observation_id"),
            trace_id=request_value("trace_id"),
        )

    def _create_run_item(
        self,
        *,
        run_name: str,
        dataset_item_id: str,
        run_description: str | None,
        metadata: dict[str, Any] | None,
        observation_id: str | None,
        trace_id: str | None,
    ) -> FakeDatasetRunItem:
        now = datetime.now(timezone.utc)
        dataset_item = self._store.dataset_items[dataset_item_id]
        metadata = metadata or {}

        run_key = (dataset_item.dataset_id, run_name)
        dataset = next((ds for ds in self._store.datasets.values() if ds.id == dataset_item.dataset_id), None)
        self._store.dataset_runs.setdefault(
            run_key,
            FakeDatasetRun(
                id=f"run_{len(self._store.dataset_runs) + 1}",
                dataset_id=dataset_item.dataset_id,
                dataset_name=dataset.name if dataset else dataset_item.dataset_id,
                name=run_name,
                description=run_description,
                metadata=metadata,
                created_at=now,
                updated_at=now,
            ),
        )

        item = FakeDatasetRunItem(
            id=f"run_item_{len(self._store.dataset_run_items) + 1}",
            dataset_id=dataset_item.dataset_id,
            dataset_item_id=dataset_item_id,
            run_name=run_name,
            run_description=run_description,
            metadata=metadata,
            observation_id=observation_id,
            trace_id=trace_id,
            created_at=now,
        )
        self._store.dataset_run_items[item.id] = item
        return item


class _DatasetRunItemsV4API(_DatasetRunItemsAPI):
    """Fake v4 dataset_run_items client where writes take direct kwargs."""

    def create(
        self,
        *,
        run_name: str,
        dataset_item_id: str,
        run_description: str | None = None,
        metadata: dict[str, Any] | None = None,
        observation_id: str | None = None,
        trace_id: str | None = None,
        **kwargs: Any,
    ) -> FakeDatasetRunItem:
        self.last_create_kwargs = {
            "run_name": run_name,
            "dataset_item_id": dataset_item_id,
            **({"run_description": run_description} if run_description is not None else {}),
            **({"metadata": metadata} if metadata is not None else {}),
            **({"observation_id": observation_id} if observation_id is not None else {}),
            **({"trace_id": trace_id} if trace_id is not None else {}),
            **kwargs,
        }
        return self._create_run_item(
            run_name=run_name,
            dataset_item_id=dataset_item_id,
            run_description=run_description,
            metadata=metadata,
            observation_id=observation_id,
            trace_id=trace_id,
        )


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


class _AnnotationQueuesV4API:
    """Fake v4 annotation_queues namespace: write methods take direct kwargs (no ``request=``)."""

    def __init__(self, store: FakeDataStore) -> None:
        """Bind the v4 annotation_queues namespace to the shared store."""
        self._store = store
        self.last_list_queues_kwargs: dict[str, Any] | None = None
        self.last_create_queue_kwargs: dict[str, Any] | None = None
        self.last_get_queue_kwargs: dict[str, Any] | None = None
        self.last_list_items_kwargs: dict[str, Any] | None = None
        self.last_get_item_kwargs: dict[str, Any] | None = None
        self.last_create_item_kwargs: dict[str, Any] | None = None
        self.last_update_item_kwargs: dict[str, Any] | None = None
        self.last_create_assignment_kwargs: dict[str, Any] | None = None
        self.last_delete_assignment_kwargs: dict[str, Any] | None = None

    def list_queues(self, **kwargs: Any) -> FakePaginatedResponse:
        """List annotation queues (unchanged across v3 and v4)."""
        self.last_list_queues_kwargs = kwargs
        queues = [q.__dict__ for q in self._store.annotation_queues.values()]
        return FakePaginatedResponse(data=queues, meta={"next_page": None, "total": len(queues)})

    def create_queue(
        self,
        *,
        name: str,
        score_config_ids: list[str],
        description: str | None = None,
    ) -> FakeAnnotationQueue:
        """Create a queue using v4 direct-kwargs signature (no ``**kwargs`` — strict v4 contract).

        Real v4 ``api.annotation_queues.create_queue`` rejects unexpected fields. The
        fake omits ``**kwargs`` so production code that drifts back to the v3
        ``request=`` shape (or sneaks in extra fields) raises a TypeError instead
        of silently passing.
        """
        self.last_create_queue_kwargs = {"name": name, "score_config_ids": score_config_ids, "description": description}
        now = datetime.now(timezone.utc)
        queue = FakeAnnotationQueue(
            id=f"queue_{len(self._store.annotation_queues) + 1}",
            name=name,
            description=description,
            score_config_ids=list(score_config_ids),
            created_at=now,
        )
        self._store.annotation_queues[queue.id] = queue
        return queue

    def get_queue(self, queue_id: str) -> Any:
        """Return a queue by id."""
        self.last_get_queue_kwargs = {"queue_id": queue_id}
        return self._store.annotation_queues.get(queue_id)

    def list_queue_items(
        self,
        queue_id: str,
        *,
        page: int | None = None,
        limit: int | None = None,
    ) -> FakePaginatedResponse:
        """List items belonging to a queue."""
        self.last_list_items_kwargs = {"queue_id": queue_id, "page": page, "limit": limit}
        items = [item.__dict__ for item in self._store.annotation_queue_items.values() if item.queue_id == queue_id]
        return FakePaginatedResponse(data=items, meta={"next_page": None, "total": len(items)})

    def get_queue_item(self, queue_id: str, item_id: str) -> Any:
        """Return a single queue item by ids."""
        self.last_get_item_kwargs = {"queue_id": queue_id, "item_id": item_id}
        item = self._store.annotation_queue_items.get(item_id)
        return item if item and item.queue_id == queue_id else None

    def create_queue_item(
        self,
        queue_id: str,
        *,
        object_id: str,
        object_type: Any,
        status: Any | None = None,
    ) -> FakeAnnotationQueueItem:
        """Create a queue item using v4 direct-kwargs signature (strict, no ``**kwargs``)."""
        self.last_create_item_kwargs = {
            "queue_id": queue_id,
            "object_id": object_id,
            "object_type": object_type,
            "status": status,
        }
        now = datetime.now(timezone.utc)
        item = FakeAnnotationQueueItem(
            id=f"queue_item_{len(self._store.annotation_queue_items) + 1}",
            queue_id=queue_id,
            object_id=object_id,
            object_type=object_type,
            status=(status.value if hasattr(status, "value") else status) or "PENDING",
            created_at=now,
        )
        self._store.annotation_queue_items[item.id] = item
        return item

    def update_queue_item(
        self,
        queue_id: str,
        item_id: str,
        *,
        status: Any | None = None,
    ) -> Any:
        """Update a queue item's status using v4 direct-kwargs signature (strict)."""
        self.last_update_item_kwargs = {"queue_id": queue_id, "item_id": item_id, "status": status}
        item = self._store.annotation_queue_items.get(item_id)
        if item and item.queue_id == queue_id:
            item.status = status.value if hasattr(status, "value") else status
            return item
        return None

    def delete_queue_item(self, queue_id: str, item_id: str) -> dict[str, Any]:
        """Delete a queue item by id."""
        item = self._store.annotation_queue_items.get(item_id)
        if item and item.queue_id == queue_id:
            del self._store.annotation_queue_items[item_id]
        return {"success": True}

    def create_queue_assignment(self, queue_id: str, *, user_id: str) -> dict[str, Any]:
        """Create a queue assignment using v4 direct-kwargs signature (strict)."""
        self.last_create_assignment_kwargs = {"queue_id": queue_id, "user_id": user_id}
        self._store.queue_assignments.setdefault(queue_id, set()).add(user_id)
        return {"success": True, "queue_id": queue_id, "user_id": user_id}

    def delete_queue_assignment(self, queue_id: str, *, user_id: str) -> dict[str, Any]:
        """Delete a queue assignment using v4 direct-kwargs signature (strict)."""
        self.last_delete_assignment_kwargs = {"queue_id": queue_id, "user_id": user_id}
        self._store.queue_assignments.setdefault(queue_id, set()).discard(user_id)
        return {"success": True, "queue_id": queue_id, "user_id": user_id}


class _ScoresV4API:
    """Fake v4 scores namespace: ``get_many`` replaces v3's ``get``."""

    def __init__(self, store: FakeDataStore) -> None:
        """Bind the v4 scores namespace to the shared store."""
        self._store = store
        self.last_get_many_kwargs: dict[str, Any] | None = None
        self.last_get_by_id_kwargs: dict[str, Any] | None = None

    def get_many(self, **kwargs: Any) -> FakePaginatedResponse:
        """List scores using v4 ``scores.get_many`` semantics (page-based)."""
        self.last_get_many_kwargs = kwargs
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

    def get_by_id(self, *, score_id: str, **kwargs: Any) -> Any:
        """Return a score by id (v4 keyword-only signature)."""
        self.last_get_by_id_kwargs = {"score_id": score_id, **kwargs}
        return self._store.scores.get(score_id)


@dataclass
class FakeMetricsResponse:
    """Minimal metrics response mirroring the real ``MetricsV2Response`` shape (``data`` only)."""

    data: list[Any]


class _MetricsV2API:
    """Fake implementation of the v2 metrics resource client (``/api/public/v2/metrics``).

    Records the raw ``query`` JSON string so tests can assert how the tool builds the
    query object, and returns canned rows from the backing store.
    """

    def __init__(self, store: FakeDataStore) -> None:
        self._store = store
        self.last_query: str | None = None

    def metrics(self, *, query: str, **kwargs: Any) -> FakeMetricsResponse:
        self.last_query = query
        return FakeMetricsResponse(data=list(self._store.metrics_rows))


class _ObservationsV3CursorAPI:
    """Fake v3 ``api.observations_v_2`` namespace: cursor-based ``get_many`` (SDK 3.11.2+).

    Mirrors the real v3 signature: no first-class ``expand_metadata`` parameter; the scan
    must forward it via ``request_options.additional_query_parameters``.
    """

    def __init__(self, store: FakeDataStore) -> None:
        self._store = store
        self.last_get_many_kwargs: dict[str, Any] | None = None

    def get_many(
        self,
        *,
        fields: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        level: str | None = None,
        from_start_time: Any = None,
        to_start_time: Any = None,
        trace_id: str | None = None,
        request_options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> FakePaginatedResponse:
        self.last_get_many_kwargs = {
            "cursor": cursor,
            "limit": limit,
            **{
                k: v
                for k, v in (
                    ("level", level),
                    ("fields", fields),
                    ("trace_id", trace_id),
                    ("from_start_time", from_start_time),
                    ("to_start_time", to_start_time),
                )
                if v is not None
            },
            **({"request_options": request_options} if request_options is not None else {}),
        }
        observations = list(self._store.observations.values())
        if level is not None:
            observations = [obs for obs in observations if obs.level == level]
        if trace_id is not None:
            observations = [obs for obs in observations if obs.trace_id == trace_id]
        data = [obs.__dict__ for obs in observations]
        return FakePaginatedResponse(data=data, meta={"cursor": None})


class FakeAPI:
    """Aggregate object exposed via FakeLangfuse.api."""

    def __init__(self, store: FakeDataStore) -> None:
        """Wire the fake API resources to the shared backing store."""
        self.trace = _TraceAPI(store)
        self.observations = _ObservationsAPI(store)
        self.observations_v_2 = _ObservationsV3CursorAPI(store)
        self.sessions = _SessionsAPI(store)
        self.prompts = _PromptsAPI(store)
        self.datasets = _DatasetsAPI(store)
        self.dataset_items = _DatasetItemsAPI(store)
        self.dataset_run_items = _DatasetRunItemsAPI(store)
        self.annotation_queues = _AnnotationQueuesAPI(store)
        self.score_v_2 = _ScoreV2API(store)
        self.metrics_v_2 = _MetricsV2API(store)


_V2_FIELD_GROUPS: dict[str, tuple[str, ...]] = {
    "core": ("id", "traceId", "startTime", "endTime", "projectId", "parentObservationId", "type"),
    "basic": (
        "name",
        "level",
        "statusMessage",
        "version",
        "environment",
        "bookmarked",
        "public",
        "userId",
        "sessionId",
        "isRootObservation",
    ),
    "time": ("completionStartTime", "createdAt", "updatedAt"),
    "io": ("input", "output"),
    "metadata": ("metadata",),
    "model": ("model", "internalModelId", "modelParameters"),
    "usage": ("usageDetails", "costDetails", "totalCost", "usagePricingTierName"),
    "prompt": ("promptId", "promptName", "promptVersion"),
    "metrics": ("latency", "timeToFirstToken"),
    "trace_context": ("tags", "release", "traceName"),
}
_V2_FILTER_COLUMN_ALIASES = {"traceTags": "tags"}


def _v2_parse_time(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _v2_condition_matches(row: dict[str, Any], condition: dict[str, Any]) -> bool:
    """Evaluate one v2 ``filter`` condition against a full row."""
    kind, operator, value = condition["type"], condition["operator"], condition.get("value")
    actual = row.get(_V2_FILTER_COLUMN_ALIASES.get(condition["column"], condition["column"]))
    if kind == "datetime":
        if actual is None:
            return False
        actual_time, bound = _v2_parse_time(actual), _v2_parse_time(value)
        if operator == ">=":
            return actual_time >= bound
        if operator == ">":
            return actual_time > bound
        if operator == "<=":
            return actual_time <= bound
        if operator == "<":
            return actual_time < bound
    if kind == "null":
        if value != "":
            # Langfuse answers 400 "expected \"\"" on filter[i].value when it is missing.
            raise ValueError(f'null-type condition needs value "": {condition!r}')
        return actual is None if operator == "is null" else actual is not None
    if kind in ("string", "boolean") and operator in ("=", "<>"):
        return (actual == value) if operator == "=" else (actual != value)
    if kind == "arrayOptions":
        present = set(actual or [])
        wanted = set(value or [])
        if operator == "all of":
            return wanted <= present
        if operator == "any of":
            return bool(wanted & present)
        if operator == "none of":
            return not (wanted & present)
    raise ValueError(f"fake v2 filter does not support {condition!r}")


class _ObservationsV4API:
    """Fake v4 observations namespace: Observations API v2 ``get_many`` (cursor-only); ``get`` is absent.

    Mirrors the real endpoint where production code depends on it: camelCase rows, field
    groups (``core,basic`` by default), cursor pagination by ``limit``, and a structured
    ``filter`` that — like the server — overrides every query-parameter filter.
    """

    def __init__(self, store: FakeDataStore) -> None:
        """Bind the fake v4 observations namespace to the shared store."""
        self._store = store
        self.last_get_many_kwargs: dict[str, Any] | None = None
        self.calls: list[dict[str, Any]] = []

    def _row(self, obs: FakeObservation) -> dict[str, Any]:
        trace = next((t for t in self._store.traces.values() if obs.id in t.observations or t.id == obs.trace_id), None)
        return {
            "id": obs.id,
            "traceId": obs.trace_id or (trace.id if trace else None),
            "startTime": obs.start_time.isoformat(),
            "endTime": obs.end_time.isoformat(),
            "projectId": "project_1",
            "parentObservationId": obs.parent_observation_id,
            "type": obs.type,
            "name": obs.name,
            "level": obs.level,
            "statusMessage": obs.status_message,
            "version": None,
            "environment": "default",
            "bookmarked": False,
            "public": False,
            "userId": trace.user_id if trace else None,
            "sessionId": trace.session_id if trace else None,
            "isRootObservation": obs.parent_observation_id is None,
            "completionStartTime": None,
            "createdAt": obs.start_time.isoformat(),
            "updatedAt": obs.end_time.isoformat(),
            # v2 returns IO as raw strings, never parsed JSON.
            "input": obs.input if obs.input is None or isinstance(obs.input, str) else json.dumps(obs.input),
            "output": obs.output if obs.output is None or isinstance(obs.output, str) else json.dumps(obs.output),
            "metadata": obs.metadata,
            "model": None,
            "internalModelId": None,
            "modelParameters": None,
            "usageDetails": {},
            "costDetails": {},
            "totalCost": obs.total_cost,
            "usagePricingTierName": None,
            "promptId": None,
            "promptName": None,
            "promptVersion": None,
            "latency": (obs.end_time - obs.start_time).total_seconds(),
            "timeToFirstToken": None,
            "tags": list(trace.tags) if trace else [],
            "release": None,
            "traceName": trace.name if trace else None,
        }

    def get_many(
        self,
        *,
        fields: str | None = None,
        expand_metadata: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        name: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        type: str | None = None,
        trace_id: str | None = None,
        level: str | None = None,
        parent_observation_id: str | None = None,
        is_root_observation: bool | None = None,
        from_start_time: Any = None,
        to_start_time: Any = None,
        filter: str | None = None,
        request_options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> FakePaginatedResponse:
        """Return observations using cursor-based pagination (v4 ObservationsV2)."""
        query_filters = {
            "name": name,
            "userId": user_id,
            "sessionId": session_id,
            "type": type,
            "traceId": trace_id,
            "level": level,
            "parentObservationId": parent_observation_id,
            "isRootObservation": is_root_observation,
        }
        recorded = {
            "fields": fields,
            "expand_metadata": expand_metadata,
            "name": name,
            "user_id": user_id,
            "session_id": session_id,
            "type": type,
            "trace_id": trace_id,
            "level": level,
            "parent_observation_id": parent_observation_id,
            "is_root_observation": is_root_observation,
            "from_start_time": from_start_time,
            "to_start_time": to_start_time,
            "filter": filter,
            "request_options": request_options,
        }
        self.last_get_many_kwargs = {"cursor": cursor, "limit": limit, **{k: v for k, v in recorded.items() if v is not None}, **kwargs}
        self.calls.append(self.last_get_many_kwargs)

        rows = [self._row(obs) for obs in self._store.observations.values()]
        if filter is not None:
            conditions = json.loads(filter)
            rows = [row for row in rows if all(_v2_condition_matches(row, c) for c in conditions)]
        else:
            rows = [row for row in rows if all(value is None or row.get(column) == value for column, value in query_filters.items())]
            if from_start_time is not None:
                rows = [
                    row
                    for row in rows
                    if _v2_condition_matches(row, {"type": "datetime", "column": "startTime", "operator": ">=", "value": from_start_time})
                ]
            if to_start_time is not None:
                rows = [
                    row
                    for row in rows
                    if _v2_condition_matches(row, {"type": "datetime", "column": "startTime", "operator": "<=", "value": to_start_time})
                ]
        rows.sort(key=lambda row: _v2_parse_time(row["startTime"]), reverse=True)

        page_size = limit or 50
        offset = int(cursor) if cursor else 0
        page_rows = rows[offset : offset + page_size]
        next_cursor = str(offset + page_size) if offset + page_size < len(rows) else None

        groups = (fields or "core,basic").split(",")
        keep = {key for group in groups for key in _V2_FIELD_GROUPS[group]}
        data = [{key: value for key, value in row.items() if key in keep} for row in page_rows]
        # v4 ObservationsV2Meta carries only ``cursor``; ``None`` means no further pages.
        return FakePaginatedResponse(data=data, meta={"cursor": next_cursor})


class FakeHTTPError(Exception):
    """Stand-in for the SDK's ApiError: carries ``status_code`` like the real one."""

    def __init__(self, status_code: int, message: str) -> None:
        """Record the HTTP status the fake server answered with."""
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code


class _ScoresV3API:
    """Fake v4 ``api.scores_v3`` namespace (SDK 4.8.1+): Scores API v3 ``get_many_v3``.

    Mirrors the real endpoint where production code depends on it: the documented 400 rules,
    comma-separated list filters, cursor pages by ``limit``, and rows shaped like the SDK
    models' ``model_dump()`` (snake_case, typed ``value``, a ``subject`` object). Time bounds
    are recorded but not applied, as in the other fakes.
    """

    def __init__(self, store: FakeDataStore) -> None:
        """Bind the fake Scores v3 namespace to the shared store."""
        self._store = store
        self.calls: list[dict[str, Any]] = []

    def get_many_v3(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        fields: str | None = None,
        id: str | None = None,
        name: str | None = None,
        source: str | None = None,
        data_type: str | None = None,
        environment: str | None = None,
        config_id: str | None = None,
        queue_id: str | None = None,
        author_user_id: str | None = None,
        value: str | None = None,
        value_min: float | None = None,
        value_max: float | None = None,
        trace_id: str | None = None,
        session_id: str | None = None,
        observation_id: str | None = None,
        experiment_id: str | None = None,
        from_timestamp: Any = None,
        to_timestamp: Any = None,
        request_options: dict[str, Any] | None = None,
    ) -> FakePaginatedResponse:
        """Return scores as v3 rows, applying the filters the fixtures can express."""
        recorded = {
            "limit": limit,
            "cursor": cursor,
            "fields": fields,
            "id": id,
            "name": name,
            "source": source,
            "data_type": data_type,
            "environment": environment,
            "config_id": config_id,
            "queue_id": queue_id,
            "value": value,
            "value_min": value_min,
            "value_max": value_max,
            "trace_id": trace_id,
            "session_id": session_id,
            "from_timestamp": from_timestamp,
            "to_timestamp": to_timestamp,
        }
        self.calls.append({k: v for k, v in recorded.items() if v is not None or k in ("limit", "cursor")})

        if limit is not None and limit > 100:
            raise FakeHTTPError(400, "limit must be at most 100")
        if sum(x is not None for x in (trace_id, session_id, experiment_id)) > 1:
            raise FakeHTTPError(400, "traceId, sessionId and experimentId are mutually exclusive")
        if value is not None and (data_type is None or "," in data_type or data_type.upper() not in ("NUMERIC", "BOOLEAN", "CATEGORICAL")):
            raise FakeHTTPError(400, "value needs a single dataType of NUMERIC, BOOLEAN or CATEGORICAL")
        if (value_min is not None or value_max is not None) and (data_type or "").upper() != "NUMERIC":
            raise FakeHTTPError(400, "valueMin/valueMax need dataType=NUMERIC")

        def listed(filter_value: str | None) -> set[str] | None:
            return None if filter_value is None else {part.strip() for part in filter_value.split(",")}

        scores = list(self._store.scores.values())
        for attribute, wanted in (
            ("id", listed(id)),
            ("name", listed(name)),
            ("trace_id", listed(trace_id)),
            ("queue_id", listed(queue_id)),
        ):
            if wanted is not None:
                scores = [s for s in scores if getattr(s, attribute) in wanted]
        if data_type is not None:
            scores = [s for s in scores if s.data_type.upper() in {t.strip().upper() for t in data_type.split(",")}]
        if session_id is not None:
            scores = []  # the seeded scores are trace scores
        if value is not None:
            wanted_values = {v.strip() for v in value.split(",")}
            scores = [
                s
                for s in scores
                if str(s.value).lower() in wanted_values
                or (s.data_type == "NUMERIC" and float(s.value) in {float(v) for v in wanted_values})
            ]
        if value_min is not None:
            scores = [s for s in scores if float(s.value) >= value_min]
        if value_max is not None:
            scores = [s for s in scores if float(s.value) <= value_max]

        page_size = limit or 50
        offset = int(cursor) if cursor else 0
        page = scores[offset : offset + page_size]
        next_cursor = str(offset + page_size) if offset + page_size < len(scores) else None
        groups = set((fields or "").split(",")) - {""}
        data = []
        for s in page:
            row: dict[str, Any] = {
                "id": s.id,
                "project_id": "project_1",
                "name": s.name,
                "value": s.value,
                "data_type": s.data_type,
                "source": "API",
                "timestamp": s.created_at,
                "environment": "default",
                "created_at": s.created_at,
                "updated_at": s.created_at,
            }
            if "details" in groups:
                row.update({"comment": None, "config_id": None, "metadata": None})
            if "subject" in groups:
                row["subject"] = {"kind": "trace", "id": s.trace_id}
            if "annotation" in groups:
                row.update({"author_user_id": None, "queue_id": s.queue_id})
            data.append(row)
        return FakePaginatedResponse(data=data, meta={"limit": page_size, "cursor": next_cursor})


class _LegacyObservationsV1API:
    """Fake v4 ``api.legacy.observations_v1`` namespace exposing the page-based v1 surface."""

    def __init__(self, store: FakeDataStore) -> None:
        """Bind the legacy v1 observations namespace to the shared store."""
        self._store = store
        self.last_get_kwargs: dict[str, Any] | None = None
        self.last_get_many_kwargs: dict[str, Any] | None = None

    def get(self, observation_id: str, **kwargs: Any) -> dict[str, Any]:
        """Return a single observation by id (positional, matching v4 legacy signature)."""
        self.last_get_kwargs = {"observation_id": observation_id, **kwargs}
        obs = self._store.observations.get(observation_id)
        return obs.__dict__ if obs else {}

    def get_many(
        self,
        *,
        page: int | None = None,
        limit: int | None = None,
        level: str | None = None,
        from_start_time: Any = None,
        to_start_time: Any = None,
        trace_id: str | None = None,
        name: str | None = None,
        user_id: str | None = None,
        type: str | None = None,
        parent_observation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> FakePaginatedResponse:
        """Return observations using page-based pagination via the legacy v1 endpoint."""
        self.last_get_many_kwargs = {
            "page": page,
            "limit": limit,
            **{k: v for k, v in (("level", level), ("trace_id", trace_id), ("type", type)) if v is not None},
            **kwargs,
        }
        observations = list(self._store.observations.values())
        if level is not None:
            observations = [obs for obs in observations if obs.level == level]
        if trace_id is not None:
            observations = [obs for obs in observations if obs.trace_id == trace_id]
        data = [obs.__dict__ for obs in observations]
        return FakePaginatedResponse(data=data, meta={"next_page": None, "total": len(data)})


class _LegacyAPI:
    """Fake v4 ``api.legacy`` namespace housing the v1 fallbacks."""

    def __init__(self, store: FakeDataStore) -> None:
        """Wire the legacy v1 namespaces to the shared store."""
        self.observations_v1 = _LegacyObservationsV1API(store)


class FakeAPIV4:
    """Aggregate object exposed via FakeLangfuseV4.api — v4 surface only.

    Differences vs. v3 (``FakeAPI``):
    - No ``score_v_2``; scores resource is renamed to ``scores`` with ``get_many``.
    - ``observations.get`` is absent; ``observations.get_many`` is cursor-only.
    - ``api.legacy.observations_v1`` exposes the page-based v1 fallback.
    - Annotation queue write methods take direct kwargs (no ``request=``).
    - ``api.dataset_run_items.create`` takes direct kwargs (no ``request=``).
    - ``api.datasets`` / ``api.dataset_items`` are intentionally not wired for
      creates — production code calls them through the top-level
      ``Langfuse.create_dataset`` / ``create_dataset_item`` shortcuts.
    """

    def __init__(self, store: FakeDataStore) -> None:
        """Wire the v4-shaped API resources to the shared store."""
        self.trace = _TraceAPI(store)
        self.observations = _ObservationsV4API(store)
        self.sessions = _SessionsAPI(store)
        self.prompts = _PromptsAPI(store)
        self.scores = _ScoresV4API(store)
        self.scores_v3 = _ScoresV3API(store)
        self.annotation_queues = _AnnotationQueuesV4API(store)
        self.metrics_v_2 = _MetricsV2API(store)
        self.dataset_run_items = _DatasetRunItemsV4API(store)
        # datasets/dataset_items are filled in by S4.
        self.legacy = _LegacyAPI(store)


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
        self.dataset_runs: dict[tuple[str, str], FakeDatasetRun] = {}
        self.dataset_run_items: dict[str, FakeDatasetRunItem] = {}
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
        # Canned metric rows returned by the fake v2 metrics endpoint.
        self.metrics_rows: list[dict[str, Any]] = [
            {"providedModelName": "claude-opus-4-8", "totalCost_sum": 1.23, "count_count": 7},
            {"providedModelName": "claude-sonnet-4-6", "totalCost_sum": 0.45, "count_count": 12},
        ]
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
        self.flush_count = 0
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
        """Count flushes for tests while matching the SDK cleanup hook."""
        self.flush_count += 1
        return None

    def shutdown(self) -> None:  # pragma: no cover - compatibility shim
        """Provide the Langfuse SDK shutdown hook by delegating to close()."""
        self.close()


class FakeLangfuseV4:
    """Langfuse client double exposing the v4 API surface.

    Compared to ``FakeLangfuse`` (v3 shape):
    - ``api`` is a ``FakeAPIV4`` (no ``score_v_2``, cursor-only observations,
      legacy fallbacks under ``api.legacy``, kwargs-style annotation queue writes).
    - The top-level ``fetch_observation`` shim is intentionally absent (v4 removed it).
    - The top-level ``create_dataset`` / ``create_dataset_item`` shortcuts are also
      absent here so dataset tests stay scoped to ``FakeLangfuse``; both real v3 and
      v4 expose them, but exercising the v4 dataset path through this fake would just
      re-test the unchanged shortcut shim.
    """

    def __init__(self) -> None:
        """Initialise the fake v4 client with in-memory storage and v4 API facade."""
        self._store = FakeDataStore()
        self.api = FakeAPIV4(self._store)
        self.closed = False

    def flush(self) -> None:  # pragma: no cover - compatibility shim
        """Match the v4 ``Langfuse.flush`` no-op contract."""
        return None

    def shutdown(self) -> None:  # pragma: no cover - compatibility shim
        """Match the v4 ``Langfuse.shutdown`` contract by marking the client closed."""
        self.closed = True


class FakeContext:
    """Mimic `mcp.server.mcpserver.Context` used by the tools."""

    def __init__(self, state: Any) -> None:
        """Expose the minimal request context consumed by tool implementations."""
        self.request_context = type("_RC", (), {"lifespan_context": state})
