import asyncio

import pytest

import foghttp
from foghttp.status_codes.success import OK

from .constants import SLOW_BODY_PATH, SLOW_HEADERS_PATH
from .helpers import wait_for_no_active_requests


async def test_cancelled_async_request_aborts_rust_request(cancellation_server: str) -> None:
    async with foghttp.AsyncClient() as client:
        task = asyncio.create_task(client.get(cancellation_server + SLOW_HEADERS_PATH))
        await asyncio.sleep(0.05)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        await wait_for_no_active_requests(client)
        response = await client.get(cancellation_server)

    assert response.status_code == OK
    assert response.content == b"OK"


async def test_asyncio_timeout_aborts_rust_request(cancellation_server: str) -> None:
    async with foghttp.AsyncClient() as client:
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                await client.get(cancellation_server + SLOW_HEADERS_PATH)

        await wait_for_no_active_requests(client)
        response = await client.get(cancellation_server)

    assert response.status_code == OK
    assert response.content == b"OK"


async def test_cancelled_async_request_during_slow_body_aborts_rust_request(cancellation_server: str) -> None:
    async with foghttp.AsyncClient() as client:
        task = asyncio.create_task(client.get(cancellation_server + SLOW_BODY_PATH))
        await asyncio.sleep(0.05)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        await wait_for_no_active_requests(client)
        response = await client.get(cancellation_server)

    assert response.status_code == OK
    assert response.content == b"OK"


async def test_aclose_cancels_in_flight_async_request(cancellation_server: str) -> None:
    client = foghttp.AsyncClient()
    task = asyncio.create_task(client.get(cancellation_server + SLOW_HEADERS_PATH))
    await asyncio.sleep(0.05)

    await client.aclose()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1.0)
