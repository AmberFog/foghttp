__all__ = (
    "AsyncLifecycleDebugTracker",
    "LifecycleDebugRequestToken",
    "async_lifecycle_debug_leak_message",
)

from dataclasses import dataclass
import threading
import time
from typing import TypeAlias

from ..lifecycle_debug import (
    AsyncLifecycleDebugConfig,
    AsyncLifecycleDebugRequest,
    AsyncLifecycleDebugRequestMode,
    AsyncLifecycleDebugSnapshot,
)
from ..request import Request
from ..transport_stats import TransportStats
from .telemetry.url import redacted_url, url_origin


LifecycleDebugRequestToken: TypeAlias = int | None

_DEBUG_LEAK_MESSAGE = "AsyncClient lifecycle debug detected active transport state"
_MAX_DEBUG_REQUEST_DESCRIPTIONS = 10
_NANOSECONDS_PER_MILLISECOND = 1_000_000


@dataclass(frozen=True, slots=True)
class _TrackedAsyncRequest:
    request_id: int
    mode: AsyncLifecycleDebugRequestMode
    method: str
    origin: str | None
    redacted_url: str
    started_at_ns: int

    def snapshot(self, observed_at_ns: int) -> AsyncLifecycleDebugRequest:
        return AsyncLifecycleDebugRequest(
            request_id=self.request_id,
            mode=self.mode,
            method=self.method,
            origin=self.origin,
            redacted_url=self.redacted_url,
            started_at_ns=self.started_at_ns,
            age_ns=max(0, observed_at_ns - self.started_at_ns),
        )


class AsyncLifecycleDebugTracker:
    def __init__(self, config: AsyncLifecycleDebugConfig | None) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._next_request_id = 1
        self._active_requests: dict[int, _TrackedAsyncRequest] = {}

    @property
    def strict(self) -> bool:
        return False if self._config is None else self._config.strict

    def start_request(
        self,
        request: Request,
        *,
        mode: AsyncLifecycleDebugRequestMode,
    ) -> LifecycleDebugRequestToken:
        if self._config is None:
            return None

        started_at_ns = time.perf_counter_ns()
        with self._lock:
            request_id = self._next_request_id
            self._next_request_id += 1
            self._active_requests[request_id] = _TrackedAsyncRequest(
                request_id=request_id,
                mode=mode,
                method=request.method,
                origin=url_origin(request.url),
                redacted_url=redacted_url(request.url),
                started_at_ns=started_at_ns,
            )
            return request_id

    def finish_request(self, token: LifecycleDebugRequestToken) -> None:
        if token is None:
            return

        with self._lock:
            self._active_requests.pop(token, None)

    def snapshot(
        self,
        *,
        closed: bool,
        stats: TransportStats | None,
    ) -> AsyncLifecycleDebugSnapshot:
        observed_at_ns = time.perf_counter_ns()

        return AsyncLifecycleDebugSnapshot(
            enabled=self._config is not None,
            strict=self.strict,
            closed=closed,
            active_requests=self._active_request_snapshots(observed_at_ns),
            transport_active_requests=0 if stats is None else stats.active_requests,
            transport_pending_requests=0 if stats is None else stats.pending_requests,
            pool_acquire_timeouts=0 if stats is None else stats.pool_acquire_timeouts,
        )

    def unclosed_warning_message(self, base_message: str) -> str:
        if self._config is None:
            return base_message

        active_requests = self._active_request_snapshots(time.perf_counter_ns())
        return (
            f"{base_message}; lifecycle_debug_enabled=True; "
            f"active_async_requests={len(active_requests)}; "
            f"active_requests={_request_descriptions(active_requests)!r}; "
            f"omitted_active_requests={_omitted_request_count(active_requests)}"
        )

    def _active_request_snapshots(self, observed_at_ns: int) -> tuple[AsyncLifecycleDebugRequest, ...]:
        with self._lock:
            return tuple(tracked_request.snapshot(observed_at_ns) for tracked_request in self._active_requests.values())


def async_lifecycle_debug_leak_message(snapshot: AsyncLifecycleDebugSnapshot) -> str:
    return (
        f"{_DEBUG_LEAK_MESSAGE}: "
        f"active_async_requests={snapshot.active_request_count}, "
        f"transport_active_requests={snapshot.transport_active_requests}, "
        f"transport_pending_requests={snapshot.transport_pending_requests}, "
        f"active_requests={_request_descriptions(snapshot.active_requests)!r}, "
        f"omitted_active_requests={_omitted_request_count(snapshot.active_requests)}"
    )


def _request_descriptions(active_requests: tuple[AsyncLifecycleDebugRequest, ...]) -> tuple[str, ...]:
    return tuple(
        _request_description(active_request) for active_request in active_requests[:_MAX_DEBUG_REQUEST_DESCRIPTIONS]
    )


def _request_description(active_request: AsyncLifecycleDebugRequest) -> str:
    age_ms = active_request.age_ns // _NANOSECONDS_PER_MILLISECOND
    return (
        f"{active_request.request_id}:{active_request.method} "
        f"{active_request.mode} {active_request.redacted_url} "
        f"age_ms={age_ms}"
    )


def _omitted_request_count(active_requests: tuple[AsyncLifecycleDebugRequest, ...]) -> int:
    return max(0, len(active_requests) - _MAX_DEBUG_REQUEST_DESCRIPTIONS)
