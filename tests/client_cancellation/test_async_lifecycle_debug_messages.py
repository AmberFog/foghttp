import asyncio

import pytest

import foghttp
from foghttp._client.lifecycle_debug import AsyncLifecycleDebugTracker
from foghttp.methods import GET

from .constants import SLOW_HEADERS_PATH
from .helpers import wait_for_lifecycle_debug, wait_for_no_active_requests
from .lifecycle_debug_actions import drop_client
from .lifecycle_debug_assertions import assert_url_is_redacted
from .lifecycle_debug_data import CAPPED_DEBUG_REQUEST_COUNT, sensitive_url
from .lifecycle_debug_predicates import has_debug_request_count


async def test_async_lifecycle_debug_leak_message_caps_active_request_details(
    cancellation_server: str,
) -> None:
    async with foghttp.AsyncClient(
        lifecycle_debug=foghttp.AsyncLifecycleDebugConfig(),
    ) as client:
        tasks = [
            asyncio.create_task(client.get(cancellation_server + SLOW_HEADERS_PATH))
            for _request_index in range(CAPPED_DEBUG_REQUEST_COUNT)
        ]
        try:
            await wait_for_lifecycle_debug(
                client,
                has_debug_request_count(CAPPED_DEBUG_REQUEST_COUNT),
                message="active request cap scenario was not reached",
            )

            with pytest.raises(foghttp.LifecycleError) as exc_info:
                client.assert_no_lifecycle_leaks()
            message = str(exc_info.value)
            assert f"active_async_requests={CAPPED_DEBUG_REQUEST_COUNT}" in message
            assert "omitted_active_requests=1" in message
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with pytest.raises(asyncio.CancelledError):
                    await task

        await wait_for_no_active_requests(client)


def test_async_lifecycle_debug_unclosed_warning_includes_debug_context() -> None:
    client_holder = [
        foghttp.AsyncClient(
            lifecycle_debug=foghttp.AsyncLifecycleDebugConfig(),
        ),
    ]

    with pytest.warns(
        foghttp.UnclosedClientError,
        match="lifecycle_debug_enabled=True; active_async_requests=0",
    ):
        drop_client(client_holder)


def test_async_lifecycle_debug_unclosed_warning_redacts_and_caps_active_request_context() -> None:
    tracker = AsyncLifecycleDebugTracker(foghttp.AsyncLifecycleDebugConfig())
    for request_index in range(CAPPED_DEBUG_REQUEST_COUNT):
        tracker.start_request(
            foghttp.Request(
                GET,
                sensitive_url("http://example.com", f"/requests/{request_index}"),
            ),
            mode="buffered",
        )

    message = tracker.unclosed_warning_message("unclosed")

    assert f"active_async_requests={CAPPED_DEBUG_REQUEST_COUNT}" in message
    assert "omitted_active_requests=1" in message
    assert_url_is_redacted(message)
