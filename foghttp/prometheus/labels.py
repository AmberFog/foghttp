import threading

from ..methods import HTTP_METHODS
from ..telemetry import (
    TelemetryRequestOutcome,
    TelemetryRetryDecision,
    TelemetryRetryReason,
)
from ..timeout_diagnostics import TimeoutPhase
from ..url import URL


_MAX_RETRY_ATTEMPT_LABEL = 10
_MAX_ORIGIN_LABEL_LENGTH = 512
_MIN_HTTP_STATUS_CLASS = 1
_MAX_HTTP_STATUS_CLASS = 5
_AGGREGATE_ORIGIN = "all"
_OTHER_ORIGIN = "other"
_UNKNOWN_ORIGIN = "unknown"
_OTHER_METHOD = "OTHER"
_UNKNOWN_VALUE = "unknown"
_OTHER_ERROR = "OtherError"
_NO_ERROR = "none"
_STABLE_ERROR_CLASSES = frozenset(
    (
        "CancelledError",
        "ClientClosedError",
        "ConnectTimeout",
        "FogHTTPError",
        "HTTPStatusError",
        "LifecycleError",
        "NetworkError",
        "PoolTimeout",
        "ReadTimeout",
        "RequestError",
        "ResponseBodyBudgetExceededError",
        "ResponseBodyTooLargeError",
        "ResponseError",
        "SSRFError",
        "TelemetryHookError",
        "TimeoutError",
        "WriteTimeout",
    ),
)
_TIMEOUT_ERROR_CLASSES = frozenset(
    (
        "ConnectTimeout",
        "PoolTimeout",
        "ReadTimeout",
        "TimeoutError",
        "WriteTimeout",
    ),
)
_TIMEOUT_PHASES: frozenset[TimeoutPhase] = frozenset(
    (
        "connection_acquire",
        "pool_acquire",
        "request_body",
        "retry_backoff",
        "response_headers",
        "response_body",
    ),
)


class OriginLabeler:
    __slots__ = ("_admitted", "_limit", "_lock")

    def __init__(self, limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            msg = "origin_label_limit must be an integer"
            raise TypeError(msg)
        if limit < 0:
            msg = "origin_label_limit must be greater than or equal to zero"
            raise ValueError(msg)
        self._limit = limit
        self._admitted: set[str] = set()
        self._lock = threading.Lock()

    def label(self, origin: str | None) -> str:
        if self._limit == 0:
            return _AGGREGATE_ORIGIN
        if origin is None:
            normalized = _UNKNOWN_ORIGIN
        else:
            try:
                normalized = URL(origin).origin
            except (TypeError, ValueError):
                normalized = _UNKNOWN_ORIGIN
        if normalized == _UNKNOWN_ORIGIN:
            return normalized
        if len(normalized) > _MAX_ORIGIN_LABEL_LENGTH:
            return _OTHER_ORIGIN
        with self._lock:
            if normalized not in self._admitted:
                if len(self._admitted) >= self._limit:
                    return _OTHER_ORIGIN
                self._admitted.add(normalized)
            return normalized


def method_label(method: str | None) -> str:
    if method in HTTP_METHODS:
        return method
    return _OTHER_METHOD


def status_class_label(status_code: object) -> str:
    if status_code is None:
        return "none"
    if isinstance(status_code, bool) or not isinstance(status_code, int):
        return "other"
    status_class = status_code // 100
    if _MIN_HTTP_STATUS_CLASS <= status_class <= _MAX_HTTP_STATUS_CLASS:
        return f"{status_class}xx"
    return "other"


def enum_label(
    value: object,
) -> str:
    if isinstance(
        value,
        TelemetryRequestOutcome | TelemetryRetryDecision | TelemetryRetryReason,
    ):
        return value.value
    return _UNKNOWN_VALUE


def error_class_label(error_type: object) -> str:
    if error_type is None:
        return _NO_ERROR
    if not isinstance(error_type, str):
        return _OTHER_ERROR
    if error_type in _STABLE_ERROR_CLASSES:
        return error_type
    return _OTHER_ERROR


def retry_attempt_label(attempt: object) -> str:
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        return _UNKNOWN_VALUE
    if attempt > _MAX_RETRY_ATTEMPT_LABEL:
        return f"{_MAX_RETRY_ATTEMPT_LABEL}+"
    return str(attempt)


def timeout_phase_label(
    error_type: object,
    timeout_phase: object,
) -> str | None:
    if not isinstance(error_type, str) or error_type not in _TIMEOUT_ERROR_CLASSES:
        return None
    if isinstance(timeout_phase, str) and timeout_phase in _TIMEOUT_PHASES:
        return timeout_phase
    return _UNKNOWN_VALUE
