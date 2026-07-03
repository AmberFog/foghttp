import asyncio
from typing import Any

import pytest

import foghttp
from foghttp._client import asyncio_futures
from foghttp.status_codes.success import OK
from tests.client_streaming.constants import GATED_STREAM_PATH
from tests.client_streaming.server import start_async_streaming_server

from .async_future_server import (
    EMPTY_HTTP_RESPONSE,
    cache_async_client_future_setters,
    delayed_response_server,
)
from .constants import ASYNC_BOUNDARY_REQUESTS, WAIT_TIMEOUT


async def test_async_completion_and_cancellation_race_has_single_future_winner() -> None:
    loop = asyncio.get_running_loop()
    loop_errors: list[dict[str, Any]] = []
    previous_exception_handler = loop.get_exception_handler()

    def capture_loop_error(_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        loop_errors.append(context)

    loop.set_exception_handler(capture_loop_error)
    try:
        async with (
            start_async_streaming_server() as server,
            foghttp.AsyncClient() as client,
        ):
            tasks = [
                asyncio.create_task(client.get(f"{server.base_url}{GATED_STREAM_PATH}"))
                for _request_index in range(ASYNC_BOUNDARY_REQUESTS)
            ]
            await asyncio.wait_for(server.first_chunk_sent.wait(), timeout=WAIT_TIMEOUT)
            await asyncio.sleep(0)

            for task in tasks[::2]:
                task.cancel()
            server.release_tail.set()

            results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        loop.set_exception_handler(previous_exception_handler)

    if loop_errors:
        msg = f"asyncio loop reported PyO3 boundary errors: {loop_errors!r}"
        raise AssertionError(msg)

    responses = [result for result in results if isinstance(result, foghttp.Response)]
    cancellations = [result for result in results if isinstance(result, asyncio.CancelledError)]
    unexpected_results = [
        result for result in results if not isinstance(result, (asyncio.CancelledError, foghttp.Response))
    ]

    if unexpected_results:
        msg = f"unexpected async boundary results: {unexpected_results!r}"
        raise AssertionError(msg)
    assert responses
    assert cancellations
    assert all(response.status_code == OK for response in responses)


async def test_async_buffered_completion_uses_cached_result_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with (
        start_async_streaming_server() as server,
        foghttp.AsyncClient() as client,
    ):
        await cache_async_client_future_setters(client)

        def fail_set_result(_future: asyncio.Future[object], _result: object) -> None:
            msg = "request completion should use the cached result helper"
            raise AssertionError(msg)

        monkeypatch.setattr(asyncio_futures, "set_result_if_pending", fail_set_result)
        task = asyncio.create_task(client.get(f"{server.base_url}{GATED_STREAM_PATH}"))
        await asyncio.wait_for(server.first_chunk_sent.wait(), timeout=WAIT_TIMEOUT)
        server.release_tail.set()

        response = await asyncio.wait_for(task, timeout=WAIT_TIMEOUT)

    assert response.status_code == OK


async def test_async_stream_completion_uses_cached_result_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with delayed_response_server(EMPTY_HTTP_RESPONSE) as server, foghttp.AsyncClient() as client:
        await cache_async_client_future_setters(client)

        async def read_stream_status() -> int:
            async with client.stream("GET", f"{server.base_url}/stream") as response:
                return response.status_code

        def fail_set_result(_future: asyncio.Future[object], _result: object) -> None:
            msg = "stream completion should use the cached result helper"
            raise AssertionError(msg)

        monkeypatch.setattr(asyncio_futures, "set_result_if_pending", fail_set_result)
        task = asyncio.create_task(read_stream_status())
        await asyncio.wait_for(server.request_seen.wait(), timeout=WAIT_TIMEOUT)
        server.release_response.set()

        status_code = await asyncio.wait_for(task, timeout=WAIT_TIMEOUT)

    assert status_code == OK


async def test_async_error_completion_uses_cached_exception_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with delayed_response_server(None) as server, foghttp.AsyncClient() as client:
        await cache_async_client_future_setters(client)

        def fail_set_exception(
            _future: asyncio.Future[object],
            _exception: BaseException,
        ) -> None:
            msg = "request completion should use the cached exception helper"
            raise AssertionError(msg)

        monkeypatch.setattr(
            asyncio_futures,
            "set_exception_if_pending",
            fail_set_exception,
        )
        task = asyncio.create_task(client.get(f"{server.base_url}/broken"))
        await asyncio.wait_for(server.request_seen.wait(), timeout=WAIT_TIMEOUT)
        server.release_response.set()

        with pytest.raises(foghttp.RequestError):
            await asyncio.wait_for(task, timeout=WAIT_TIMEOUT)


async def test_async_stream_error_completion_uses_cached_exception_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with delayed_response_server(None) as server, foghttp.AsyncClient() as client:
        await cache_async_client_future_setters(client)

        async def open_stream() -> None:
            async with client.stream("GET", f"{server.base_url}/broken-stream"):
                pass

        def fail_set_exception(
            _future: asyncio.Future[object],
            _exception: BaseException,
        ) -> None:
            msg = "stream error completion should use the cached exception helper"
            raise AssertionError(msg)

        monkeypatch.setattr(
            asyncio_futures,
            "set_exception_if_pending",
            fail_set_exception,
        )
        task = asyncio.create_task(open_stream())
        await asyncio.wait_for(server.request_seen.wait(), timeout=WAIT_TIMEOUT)
        server.release_response.set()

        with pytest.raises(foghttp.RequestError):
            await asyncio.wait_for(task, timeout=WAIT_TIMEOUT)
