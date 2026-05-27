__all__ = ("ClientCore",)

import threading
from typing import TYPE_CHECKING, Any, cast
import warnings

from ..errors import ClientClosedError, UnclosedClientError
from ..headers import HeaderSource
from ..limits import Limits
from ..messages import CLIENT_CLOSED, UNCLOSED_CLIENT
from ..pool_diagnostics import OriginPoolDiagnostics, PoolBlockingReason, PoolDiagnostics
from ..request import Request
from ..timeouts import Timeouts
from ..transport_state import OriginPressureState, TransportState
from ..transport_stats import TransportStats
from ..types import QueryParams, RequestData
from ..url import URL
from .config import ClientConfig
from .raw.lifecycle import create_raw_client
from .request_builder.builder import RequestBuilder
from .request_builder.defaults import DEFAULT_REQUEST_BUILD_DEFAULTS
from .request_builder.merge import RequestMergeContract
from .request_builder.models import RequestBuildOptions
from .stats import stats_from_raw


if TYPE_CHECKING:
    from foghttp import _foghttp


_DEFAULT_REQUEST_BUILDER = RequestBuilder(
    merge_contract=RequestMergeContract(),
)


class ClientCore:
    def __init__(self, *, config: ClientConfig) -> None:
        self._config = config
        self._closed = False
        self._client_lock = threading.Lock()
        self._client: _foghttp.RawClient | None = None
        self._request_builder = (
            _DEFAULT_REQUEST_BUILDER
            if config.request_defaults is DEFAULT_REQUEST_BUILD_DEFAULTS
            else RequestBuilder(
                merge_contract=RequestMergeContract(defaults=config.request_defaults),
            )
        )

    def __del__(self) -> None:
        if getattr(self, "_closed", True) is False:
            warnings.warn(UNCLOSED_CLIENT, UnclosedClientError, stacklevel=2)

    def build_request(
        self,
        method: str,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        params: QueryParams = None,
        content: bytes | str | None = None,
        data: RequestData = None,
        json: Any = None,
    ) -> Request:
        return self._request_builder.build(
            RequestBuildOptions(
                method=method,
                url=url,
                headers=headers,
                params=params,
                content=content,
                data=data,
                json=json,
            ),
        )

    def stats(self) -> TransportStats:
        self._ensure_open()
        with self._client_lock:
            self._ensure_open()
            raw_client = self._client
            raw_stats = None if raw_client is None else raw_client.stats()
        if raw_stats is None:
            return TransportStats()
        return stats_from_raw(raw=raw_stats)

    def dump_transport_state(self) -> TransportState:
        self._ensure_open()
        with self._client_lock:
            self._ensure_open()
            raw_client = self._client
            raw_state = None if raw_client is None else raw_client.transport_state()

        if raw_state is None:
            return _empty_transport_state()
        return {
            "active_requests": raw_state.active_requests,
            "pending_requests": raw_state.pending_requests,
            "peak_pending_requests": raw_state.peak_pending_requests,
            "pool_acquire_attempts": raw_state.pool_acquire_attempts,
            "pool_acquire_immediate": raw_state.pool_acquire_immediate,
            "pool_acquire_waited": raw_state.pool_acquire_waited,
            "pool_acquire_timeouts": raw_state.pool_acquire_timeouts,
            "pool_acquire_wait_time_total_ns": raw_state.pool_acquire_wait_time_total_ns,
            "pool_acquire_wait_time_max_ns": raw_state.pool_acquire_wait_time_max_ns,
            "pool_acquire_wait_time_last_ns": raw_state.pool_acquire_wait_time_last_ns,
            "response_body_reuse_eligible": raw_state.response_body_reuse_eligible,
            "response_body_closed": raw_state.response_body_closed,
            "response_body_aborted": raw_state.response_body_aborted,
            "active_connections": raw_state.active_connections,
            "idle_connections": raw_state.idle_connections,
            "connections_opened": raw_state.connections_opened,
            "connections_open_failed": raw_state.connections_open_failed,
            "connections_closed": raw_state.connections_closed,
            "connections_reused": raw_state.connections_reused,
            "connections_aborted": raw_state.connections_aborted,
            "buffered_response_bytes": raw_state.buffered_response_bytes,
            "buffered_response_budget_rejections": raw_state.buffered_response_budget_rejections,
            "origins": {origin.origin: _origin_pressure_state(origin) for origin in raw_state.origins},
        }

    def dump_pool_diagnostics(self) -> PoolDiagnostics:
        self._ensure_open()
        with self._client_lock:
            self._ensure_open()
            raw_client = self._client
            raw_diagnostics = None if raw_client is None else raw_client.pool_diagnostics()

        if raw_diagnostics is None:
            return _empty_pool_diagnostics(self._config.limits)
        return _pool_diagnostics_state(raw_diagnostics)

    def _ensure_open(self) -> None:
        if self._closed:
            raise ClientClosedError(CLIENT_CLOSED)

    def _raw_client(self) -> "_foghttp.RawClient":
        self._ensure_open()
        raw_client = self._client
        if raw_client is not None:
            return raw_client
        with self._client_lock:
            self._ensure_open()
            return self._raw_client_locked()

    def _raw_client_locked(self) -> "_foghttp.RawClient":
        raw_client = self._client
        if raw_client is None:
            raw_client = self._create_raw_client()
            self._client = raw_client
        return raw_client

    def _create_raw_client(self) -> "_foghttp.RawClient":
        return create_raw_client(config=self._config)

    def _request_timeouts(self, timeout: Timeouts | None) -> Timeouts:
        return timeout or self._config.timeouts


def _origin_pressure_state(origin: "_foghttp.RawOriginPressure") -> OriginPressureState:
    return {
        "active_requests": origin.active_requests,
        "pending_requests": origin.pending_requests,
        "peak_pending_requests": origin.peak_pending_requests,
        "pool_acquire_attempts": origin.pool_acquire_attempts,
        "pool_acquire_immediate": origin.pool_acquire_immediate,
        "pool_acquire_waited": origin.pool_acquire_waited,
        "pool_acquire_timeouts": origin.pool_acquire_timeouts,
        "pool_acquire_wait_time_total_ns": origin.pool_acquire_wait_time_total_ns,
        "pool_acquire_wait_time_max_ns": origin.pool_acquire_wait_time_max_ns,
        "pool_acquire_wait_time_last_ns": origin.pool_acquire_wait_time_last_ns,
        "response_body_reuse_eligible": origin.response_body_reuse_eligible,
        "response_body_closed": origin.response_body_closed,
        "response_body_aborted": origin.response_body_aborted,
        "active_connections": origin.active_connections,
        "idle_connections": origin.idle_connections,
        "connections_opened": origin.connections_opened,
        "connections_open_failed": origin.connections_open_failed,
        "connections_closed": origin.connections_closed,
        "connections_reused": origin.connections_reused,
        "connections_aborted": origin.connections_aborted,
        "last_activity_at_ns": origin.last_activity_at_ns,
    }


def _empty_transport_state() -> TransportState:
    return {
        "active_requests": 0,
        "pending_requests": 0,
        "peak_pending_requests": 0,
        "pool_acquire_attempts": 0,
        "pool_acquire_immediate": 0,
        "pool_acquire_waited": 0,
        "pool_acquire_timeouts": 0,
        "pool_acquire_wait_time_total_ns": 0,
        "pool_acquire_wait_time_max_ns": 0,
        "pool_acquire_wait_time_last_ns": 0,
        "response_body_reuse_eligible": 0,
        "response_body_closed": 0,
        "response_body_aborted": 0,
        "active_connections": 0,
        "idle_connections": 0,
        "connections_opened": 0,
        "connections_open_failed": 0,
        "connections_closed": 0,
        "connections_reused": 0,
        "connections_aborted": 0,
        "buffered_response_bytes": 0,
        "buffered_response_budget_rejections": 0,
        "origins": {},
    }


def _empty_pool_diagnostics(limits: Limits) -> PoolDiagnostics:
    return {
        "active_requests": 0,
        "pending_requests": 0,
        "pool_acquire_timeouts": 0,
        "max_active_requests": limits.max_active_requests,
        "max_active_requests_per_origin": limits.max_active_requests_per_origin,
        "max_pending_requests": limits.max_pending_requests,
        "pending_queue_full": limits.max_pending_requests == 0,
        "oldest_pending_request_wait_ns": 0,
        "blocked_by": "none",
        "origins": {},
    }


def _pool_diagnostics_state(raw: "_foghttp.RawPoolDiagnostics") -> PoolDiagnostics:
    return {
        "active_requests": raw.active_requests,
        "pending_requests": raw.pending_requests,
        "pool_acquire_timeouts": raw.pool_acquire_timeouts,
        "max_active_requests": raw.max_active_requests,
        "max_active_requests_per_origin": raw.max_active_requests_per_origin,
        "max_pending_requests": raw.max_pending_requests,
        "pending_queue_full": raw.pending_queue_full,
        "oldest_pending_request_wait_ns": raw.oldest_pending_request_wait_ns,
        "blocked_by": _pool_blocking_reason(raw.blocked_by),
        "origins": {origin.origin: _origin_pool_diagnostics(origin) for origin in raw.origins},
    }


def _origin_pool_diagnostics(raw: "_foghttp.RawOriginPoolDiagnostics") -> OriginPoolDiagnostics:
    return {
        "active_requests": raw.active_requests,
        "pending_requests": raw.pending_requests,
        "pool_acquire_timeouts": raw.pool_acquire_timeouts,
        "oldest_pending_request_wait_ns": raw.oldest_pending_request_wait_ns,
        "blocked_by": _pool_blocking_reason(raw.blocked_by),
        "last_activity_at_ns": raw.last_activity_at_ns,
    }


def _pool_blocking_reason(value: str) -> PoolBlockingReason:
    return cast("PoolBlockingReason", value)
