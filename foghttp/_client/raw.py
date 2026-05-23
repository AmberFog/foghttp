__all__ = (
    "close_raw_client",
    "create_raw_client",
    "send_raw_request",
    "send_raw_request_async",
)

from collections.abc import Sequence
from typing import cast

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from ..errors import (
    PoolTimeout,
    ReadTimeout,
    RequestError,
    ResponseBodyBudgetExceededError,
    ResponseBodyTooLargeError,
    TimeoutError,
)
from ..limits import Limits
from ..timeout_diagnostics import TimeoutDiagnostic, TimeoutPhase
from ..timeouts import Timeouts
from ..tls import TLSConfig
from .tls import ca_certificate_bytes, trust_webpki_roots


_TIMEOUT_DIAGNOSTIC_ARG_COUNT = 6


def close_raw_client(raw_client: _foghttp.RawClient) -> None:
    raw_client.close()


def create_raw_client(
    *,
    limits: Limits,
    timeouts: Timeouts,
    follow_redirects: bool,
    max_redirects: int,
    runtime_workers: int | None,
    trust_env: bool,
    tls: TLSConfig | None,
) -> _foghttp.RawClient:
    try:
        return _foghttp.RawClient(
            limits.max_active_requests,
            limits.max_active_requests_per_origin,
            limits.max_idle_connections_per_host,
            limits.max_pending_requests,
            limits.max_response_body_size,
            limits.max_buffered_response_bytes,
            limits.idle_timeout,
            limits.keepalive,
            timeouts.connect,
            follow_redirects,
            max_redirects,
            ca_certificate_bytes(tls),
            trust_webpki_roots(tls),
            trust_env,
            runtime_workers,
        )
    except _foghttp.FogHttpError as exc:
        raise ValueError(str(exc)) from exc


def send_raw_request(
    *,
    raw_client: _foghttp.RawClient,
    method: str,
    url: str,
    headers: Sequence[tuple[str, str]],
    body: bytes | None,
    body_replayable: bool,
    timeouts: Timeouts,
) -> _foghttp.RawResponse:
    try:
        return raw_client.request(
            method.upper(),
            url,
            headers,
            body,
            body_replayable,
            timeouts.pool,
            timeouts.read,
            timeouts.total,
        )
    except _foghttp.FogHttpResponseBodyTooLargeError as exc:
        raise ResponseBodyTooLargeError(str(exc)) from exc
    except _foghttp.FogHttpResponseBodyBudgetExceededError as exc:
        raise ResponseBodyBudgetExceededError(str(exc)) from exc
    except _foghttp.FogHttpPoolTimeoutError as exc:
        raise _timeout_error_from_raw(exc, PoolTimeout) from exc
    except _foghttp.FogHttpReadTimeoutError as exc:
        raise _timeout_error_from_raw(exc, ReadTimeout) from exc
    except _foghttp.FogHttpTimeoutError as exc:
        raise _timeout_error_from_raw(exc, TimeoutError) from exc
    except _foghttp.FogHttpError as exc:
        raise RequestError(str(exc)) from exc


async def send_raw_request_async(
    *,
    raw_client: _foghttp.RawClient,
    method: str,
    url: str,
    headers: Sequence[tuple[str, str]],
    body: bytes | None,
    body_replayable: bool,
    timeouts: Timeouts,
) -> _foghttp.RawResponse:
    try:
        return await raw_client.request_async(
            method.upper(),
            url,
            headers,
            body,
            body_replayable,
            timeouts.pool,
            timeouts.read,
            timeouts.total,
        )
    except _foghttp.FogHttpResponseBodyTooLargeError as exc:
        raise ResponseBodyTooLargeError(str(exc)) from exc
    except _foghttp.FogHttpResponseBodyBudgetExceededError as exc:
        raise ResponseBodyBudgetExceededError(str(exc)) from exc
    except _foghttp.FogHttpPoolTimeoutError as exc:
        raise _timeout_error_from_raw(exc, PoolTimeout) from exc
    except _foghttp.FogHttpReadTimeoutError as exc:
        raise _timeout_error_from_raw(exc, ReadTimeout) from exc
    except _foghttp.FogHttpTimeoutError as exc:
        raise _timeout_error_from_raw(exc, TimeoutError) from exc
    except _foghttp.FogHttpError as exc:
        raise RequestError(str(exc)) from exc


def _timeout_error_from_raw(
    exc: BaseException,
    error_type: type[TimeoutError],
) -> TimeoutError:
    message, diagnostic = _timeout_error_parts(exc)
    return error_type(message, diagnostic=diagnostic)


def _timeout_error_parts(exc: BaseException) -> tuple[str, TimeoutDiagnostic | None]:
    args = _raw_exception_args(exc)
    if len(args) != _TIMEOUT_DIAGNOSTIC_ARG_COUNT:
        return _raw_exception_message(exc), None

    message, phase, elapsed, timeout, origin, redirect_hop = args
    diagnostic_elapsed = _coerce_timeout_float(elapsed)
    diagnostic_timeout = _coerce_timeout_float(timeout)
    diagnostic_redirect_hop = _coerce_timeout_int(redirect_hop)
    if diagnostic_elapsed is None or diagnostic_timeout is None or diagnostic_redirect_hop is None:
        return str(message), None

    return (
        str(message),
        TimeoutDiagnostic(
            phase=cast("TimeoutPhase", str(phase)),
            elapsed=diagnostic_elapsed,
            timeout=diagnostic_timeout,
            origin=str(origin),
            redirect_hop=diagnostic_redirect_hop,
        ),
    )


def _raw_exception_args(exc: BaseException) -> tuple[object, ...]:
    if len(exc.args) == 1 and isinstance(exc.args[0], tuple):
        return exc.args[0]
    return exc.args


def _raw_exception_message(exc: BaseException) -> str:
    if not exc.args:
        return str(exc)
    return str(exc.args[0])


def _coerce_timeout_float(value: object) -> float | None:
    if not isinstance(value, str | bytes | bytearray | int | float):
        return None

    try:
        return float(value)
    except ValueError:
        return None


def _coerce_timeout_int(value: object) -> int | None:
    if not isinstance(value, str | bytes | bytearray | int):
        return None

    try:
        return int(value)
    except ValueError:
        return None
