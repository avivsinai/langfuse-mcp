from __future__ import annotations

import types
from dataclasses import dataclass
from typing import Any


@dataclass
class FakeResponse:
    data: Any


class FakeLangfuse:
    """Simple stand-in for the real Langfuse SDK."""

    def __init__(self) -> None:
        self._traces = [
            {
                "id": "trace_1",
                "observations": ["obs_1"],
                "timestamp": "2023-01-01T00:00:00Z",
                "user_id": "user_1",
                "session_id": "session_1",
            }
        ]
        self._observations = {
            "obs_1": {
                "id": "obs_1",
                "type": "SPAN",
                "timestamp": "2023-01-01T00:00:01Z",
                "metadata": {"code.filepath": "app.py"},
                "events": [
                    {
                        "attributes": {"exception.type": "ValueError"},
                    }
                ],
            }
        }
        self._sessions = [
            {
                "id": "session_1",
                "user_id": "user_1",
                "timestamp": "2023-01-01T00:00:00Z",
            }
        ]

    # The following methods mimic the SDK and return objects with a `data` attr
    def fetch_traces(self, **kwargs: Any) -> FakeResponse:
        """Return fake traces regardless of filters."""
        return FakeResponse(self._traces)

    def fetch_trace(self, trace_id: str) -> FakeResponse:
        """Return a single fake trace."""
        for t in self._traces:
            if t["id"] == trace_id:
                return FakeResponse(t)
        return FakeResponse({})

    def fetch_observations(self, **kwargs: Any) -> FakeResponse:
        """Return fake observations."""
        return FakeResponse(list(self._observations.values()))

    def fetch_observation(self, observation_id: str) -> FakeResponse:
        """Return a single fake observation."""
        return FakeResponse(self._observations.get(observation_id, {}))

    def fetch_sessions(self, **kwargs: Any) -> FakeResponse:
        """Return fake sessions."""
        return FakeResponse(self._sessions)

    def flush(self) -> None:
        """No-op flush."""
        return None

    def shutdown(self) -> None:
        """No-op shutdown."""
        return None


class FakeContext:
    """Mimic `mcp.server.fastmcp.Context` used by the tools."""

    def __init__(self, state: Any) -> None:
        self.request_context = types.SimpleNamespace(lifespan_context=state)
