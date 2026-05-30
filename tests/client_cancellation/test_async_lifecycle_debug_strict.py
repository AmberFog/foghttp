import asyncio

import pytest

import foghttp

from .constants import SLOW_HEADERS_PATH
from .helpers import wait_for_lifecycle_debug
from .lifecycle_debug_actions import raise_context_body_error_with_active_request
from .lifecycle_debug_assertions import (
    assert_lifecycle_error_is_actionable,
    assert_url_is_redacted,
)
from .lifecycle_debug_data import ContextBodyError, sensitive_url
from .lifecycle_debug_predicates import has_one_buffered_request


async def test_async_lifecycle_debug_strict_context_exit_preserves_body_exception(
    cancellation_server: str,
) -> None:
    client = foghttp.AsyncClient(
        lifecycle_debug=foghttp.AsyncLifecycleDebugConfig(strict=True),
    )
    tasks: list[asyncio.Task[foghttp.Response]] = []

    try:
        with pytest.raises(ContextBodyError):
            await raise_context_body_error_with_active_request(
                client,
                cancellation_server,
                tasks,
            )
    finally:
        for task in tasks:
            with pytest.raises(asyncio.CancelledError):
                await task

    snapshot = client.dump_lifecycle_debug()
    assert snapshot.closed is True
    assert snapshot.active_request_count == 0


async def test_async_lifecycle_debug_strict_aclose_reports_active_request(
    cancellation_server: str,
) -> None:
    client = foghttp.AsyncClient(
        lifecycle_debug=foghttp.AsyncLifecycleDebugConfig(strict=True),
    )
    task = asyncio.create_task(client.get(sensitive_url(cancellation_server, SLOW_HEADERS_PATH)))
    await wait_for_lifecycle_debug(
        client,
        has_one_buffered_request,
        message="active request was not tracked before strict close",
    )

    with pytest.raises(foghttp.LifecycleError, match="active_async_requests=1") as exc_info:
        await client.aclose()
    assert_lifecycle_error_is_actionable(str(exc_info.value))
    assert_url_is_redacted(str(exc_info.value))
    with pytest.raises(asyncio.CancelledError):
        await task

    snapshot = client.dump_lifecycle_debug()
    assert snapshot.closed is True
    assert snapshot.active_request_count == 0
