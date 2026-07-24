__all__ = ("ClientCore",)

import threading
from typing import Any, cast
import warnings

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from .._telemetry import SYNTHETIC_TELEMETRY_SNAPSHOT_SEQUENCE, TELEMETRY_SNAPSHOT_SCHEMA_VERSION
from .._upload_body import AsyncRequestContent, SyncRequestContent
from ..errors import ClientClosedError, UnclosedClientError
from ..headers import HeaderSource
from ..limits import Limits
from ..messages import CLIENT_CLOSED, UNCLOSED_CLIENT
from ..pool_diagnostics import OriginPoolDiagnostics, PoolBlockingReason, PoolDiagnostics
from ..request import Request
from ..request_extensions import RequestExtensionsSource
from ..timeouts import Timeouts
from ..transport_state import TransportState
from ..transport_stats import TransportStats
from ..types import AsyncMultipartFiles, QueryParams, RequestData, SyncMultipartFiles
from ..url import URL
from .config import ClientConfig
from .lifecycle_debug import AsyncLifecycleDebugTracker
from .process import current_process_id, forked_process_error
from .raw.errors import raise_public_raw_error
from .raw.lifecycle import create_raw_client
from .request_builder.builder import RequestBuilder
from .request_builder.defaults import DEFAULT_REQUEST_BUILD_DEFAULTS
from .request_builder.merge import RequestMergeContract
from .request_builder.models import RequestBuildOptions
from .stats import stats_from_raw
from .telemetry import TelemetryDispatcher
from .transport_snapshot_mapping import empty_transport_state, transport_state_from_raw


_DEFAULT_REQUEST_BUILDER = RequestBuilder(
    merge_contract=RequestMergeContract(),
)


class ClientCore:
    def __init__(self, *, config: ClientConfig) -> None:
        self._config = config
        self._closed = False
        self._process_id = current_process_id()
        self._client_lock = threading.Lock()
        self._client: _foghttp.RawClient | None = None
        self._telemetry = TelemetryDispatcher(config.telemetry)
        self._lifecycle_debug = AsyncLifecycleDebugTracker(config.lifecycle_debug)
        self._request_builder = (
            _DEFAULT_REQUEST_BUILDER
            if config.request_defaults is DEFAULT_REQUEST_BUILD_DEFAULTS and config.auth is None
            else RequestBuilder(
                merge_contract=RequestMergeContract(defaults=config.request_defaults),
                track_auth_header_provenance=config.auth is not None,
            )
        )

    def __del__(self) -> None:
        if getattr(self, "_closed", True):
            return
        if getattr(self, "_process_id", None) != current_process_id():
            return
        warnings.warn(self._unclosed_client_message(), UnclosedClientError, stacklevel=2)

    def build_request(
        self,
        method: str,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        params: QueryParams = None,
        content: SyncRequestContent | AsyncRequestContent | None = None,
        data: RequestData = None,
        files: SyncMultipartFiles | AsyncMultipartFiles | None = None,
        json: Any = None,
        extensions: RequestExtensionsSource = None,
    ) -> Request:
        return self._request_builder.build(
            RequestBuildOptions(
                method=method,
                url=url,
                headers=headers,
                params=params,
                content=content,
                data=data,
                files=files,
                json=json,
                extensions=extensions,
            ),
        )

    def stats(self) -> TransportStats:
        self._ensure_open()
        with self._client_lock:
            self._ensure_open()
            raw_client = self._client
            try:
                raw_stats = None if raw_client is None else raw_client.stats()
            except _foghttp.FogHttpError as exc:
                raise_public_raw_error(exc)
        if raw_stats is None:
            return TransportStats()
        return stats_from_raw(raw=raw_stats)

    def dump_transport_state(self) -> TransportState:
        self._ensure_open()
        with self._client_lock:
            self._ensure_open()
            raw_client = self._client
            try:
                raw_state = None if raw_client is None else raw_client.transport_state()
            except _foghttp.FogHttpError as exc:
                raise_public_raw_error(exc)

        if raw_state is None:
            return empty_transport_state()
        return transport_state_from_raw(raw_state)

    def dump_pool_diagnostics(self) -> PoolDiagnostics:
        self._ensure_open()
        with self._client_lock:
            self._ensure_open()
            raw_client = self._client
            try:
                raw_diagnostics = None if raw_client is None else raw_client.pool_diagnostics()
            except _foghttp.FogHttpError as exc:
                raise_public_raw_error(exc)

        if raw_diagnostics is None:
            return _empty_pool_diagnostics(self._config.limits)
        return _pool_diagnostics_state(raw_diagnostics)

    def _ensure_open(self) -> None:
        self._ensure_not_closed()
        self._ensure_current_process()

    def _ensure_not_closed(self) -> None:
        if self._closed:
            raise ClientClosedError(CLIENT_CLOSED)

    def _ensure_current_process(self) -> None:
        process_id = current_process_id()
        if self._process_id == process_id:
            return
        raise forked_process_error(
            resource="client",
            created_process_id=self._process_id,
            current_process_id=process_id,
        )

    def _is_current_process(self) -> bool:
        return self._process_id == current_process_id()

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

    def _unclosed_client_message(self) -> str:
        return UNCLOSED_CLIENT


def _empty_pool_diagnostics(limits: Limits) -> PoolDiagnostics:
    return {
        "schema_version": TELEMETRY_SNAPSHOT_SCHEMA_VERSION,
        "snapshot_sequence": SYNTHETIC_TELEMETRY_SNAPSHOT_SEQUENCE,
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
        "schema_version": raw.schema_version,
        "snapshot_sequence": raw.snapshot_sequence,
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
