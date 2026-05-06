from collections.abc import Mapping
import time
from typing import Any

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from .body import encode_body
from .errors import RequestError, TimeoutError
from .limits import Limits
from .messages import (
    COOKIES_UNSUPPORTED,
    HTTP_VERSION_UNSUPPORTED,
    REDIRECTS_UNSUPPORTED,
    TRUST_ENV_UNSUPPORTED,
)
from .pool_stats import PoolStats
from .response import Response
from .timeouts import Timeouts
from .url import merge_params


def validate_client_options(
    *,
    cookies: bool,
    follow_redirects: bool,
    trust_env: bool,
    http_versions: list[str] | None,
) -> None:
    if cookies:
        raise NotImplementedError(COOKIES_UNSUPPORTED)
    if follow_redirects:
        raise NotImplementedError(REDIRECTS_UNSUPPORTED)
    if trust_env:
        raise NotImplementedError(TRUST_ENV_UNSUPPORTED)
    if http_versions and http_versions != ["HTTP/1.1"]:
        raise NotImplementedError(HTTP_VERSION_UNSUPPORTED)


def create_raw_client(
    *,
    limits: Limits,
    timeouts: Timeouts,
    follow_redirects: bool,
    trust_env: bool,
) -> _foghttp.RawClient:
    return _foghttp.RawClient(
        limits.max_connections,
        limits.max_connections_per_host,
        limits.idle_timeout,
        limits.keepalive,
        timeouts.connect,
        follow_redirects,
        trust_env,
    )


def prepare_request(
    *,
    url: str,
    headers: Mapping[str, str] | None,
    params: Mapping[str, Any] | None,
    content: bytes | str | None,
    json: Any,
) -> tuple[str, dict[str, str], bytes | None]:
    request_url = merge_params(url, params)
    request_headers = dict(headers or {})
    body = encode_body(content=content, json=json, headers=request_headers)
    return request_url, request_headers, body


def send_raw_request(
    *,
    raw_client: _foghttp.RawClient,
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeouts: Timeouts,
) -> _foghttp.RawResponse:
    try:
        return raw_client.request(
            method.upper(),
            url,
            headers,
            body,
            timeouts.connect,
            timeouts.total,
        )
    except _foghttp.FogHttpTimeoutError as exc:
        raise TimeoutError(str(exc)) from exc
    except _foghttp.FogHttpError as exc:
        raise RequestError(str(exc)) from exc


def response_from_raw(*, raw: _foghttp.RawResponse, started: float) -> Response:
    elapsed = raw.elapsed if raw.elapsed >= 0 else time.perf_counter() - started
    return Response(
        status_code=raw.status_code,
        headers=raw.headers,
        content=raw.content,
        url=raw.url,
        http_version=raw.http_version,
        elapsed=elapsed,
    )


def stats_from_raw(
    *,
    raw: _foghttp.RawStats,
    pending_acquires: int,
    pool_timeouts: int,
) -> PoolStats:
    return PoolStats(
        active_connections=raw.active_connections,
        idle_connections=raw.idle_connections,
        pending_acquires=pending_acquires,
        total_requests=raw.total_requests,
        failed_requests=raw.failed_requests,
        reused_connections=raw.reused_connections,
        opened_connections=raw.opened_connections,
        closed_connections=raw.closed_connections,
        pool_timeouts=raw.pool_timeouts + pool_timeouts,
    )
