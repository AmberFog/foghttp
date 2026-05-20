__all__ = (
    "close_raw_client",
    "create_raw_client",
    "send_raw_request",
    "send_raw_request_async",
)

from collections.abc import Sequence

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from ..errors import (
    PoolTimeout,
    RequestError,
    ResponseBodyBudgetExceededError,
    ResponseBodyTooLargeError,
    TimeoutError,
)
from ..limits import Limits
from ..timeouts import Timeouts
from ..tls import TLSConfig
from .tls import ca_certificate_bytes


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
    timeouts: Timeouts,
) -> _foghttp.RawResponse:
    try:
        return raw_client.request(
            method.upper(),
            url,
            headers,
            body,
            timeouts.pool,
            timeouts.total,
        )
    except _foghttp.FogHttpResponseBodyTooLargeError as exc:
        raise ResponseBodyTooLargeError(str(exc)) from exc
    except _foghttp.FogHttpResponseBodyBudgetExceededError as exc:
        raise ResponseBodyBudgetExceededError(str(exc)) from exc
    except _foghttp.FogHttpPoolTimeoutError as exc:
        raise PoolTimeout(str(exc)) from exc
    except _foghttp.FogHttpTimeoutError as exc:
        raise TimeoutError(str(exc)) from exc
    except _foghttp.FogHttpError as exc:
        raise RequestError(str(exc)) from exc


async def send_raw_request_async(
    *,
    raw_client: _foghttp.RawClient,
    method: str,
    url: str,
    headers: Sequence[tuple[str, str]],
    body: bytes | None,
    timeouts: Timeouts,
) -> _foghttp.RawResponse:
    try:
        return await raw_client.request_async(
            method.upper(),
            url,
            headers,
            body,
            timeouts.pool,
            timeouts.total,
        )
    except _foghttp.FogHttpResponseBodyTooLargeError as exc:
        raise ResponseBodyTooLargeError(str(exc)) from exc
    except _foghttp.FogHttpResponseBodyBudgetExceededError as exc:
        raise ResponseBodyBudgetExceededError(str(exc)) from exc
    except _foghttp.FogHttpPoolTimeoutError as exc:
        raise PoolTimeout(str(exc)) from exc
    except _foghttp.FogHttpTimeoutError as exc:
        raise TimeoutError(str(exc)) from exc
    except _foghttp.FogHttpError as exc:
        raise RequestError(str(exc)) from exc
