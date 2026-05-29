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
    def enabled(self) -> bool:
        return self._config is not None

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
        with self._lock:
            active_requests = tuple(
                tracked_request.snapshot(observed_at_ns) for tracked_request in self._active_requests.values()
            )

        return AsyncLifecycleDebugSnapshot(
            enabled=self.enabled,
            strict=self.strict,
            closed=closed,
            active_requests=active_requests,
            transport_active_requests=0 if stats is None else stats.active_requests,
            transport_pending_requests=0 if stats is None else stats.pending_requests,
            pool_acquire_timeouts=0 if stats is None else stats.pool_acquire_timeouts,
        )

    def unclosed_warning_message(self, base_message: str) -> str:
        if not self.enabled:
            return base_message

        with self._lock:
            active_requests = tuple(
                f"{request.request_id}:{request.method} {request.redacted_url}"
                for request in self._active_requests.values()
            )
        return (
            f"{base_message}; lifecycle_debug_enabled=True; "
            f"active_async_requests={len(active_requests)}; "
            f"active_requests={active_requests!r}"
        )


def async_lifecycle_debug_leak_message(snapshot: AsyncLifecycleDebugSnapshot) -> str:
    return (
        f"{_DEBUG_LEAK_MESSAGE}: "
        f"active_async_requests={snapshot.active_request_count}, "
        f"transport_active_requests={snapshot.transport_active_requests}, "
        f"transport_pending_requests={snapshot.transport_pending_requests}"
    )
