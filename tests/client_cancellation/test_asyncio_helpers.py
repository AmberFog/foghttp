import asyncio

import pytest

from foghttp._client.asyncio_futures import cancel_if_pending, set_exception_if_pending, set_result_if_pending


async def test_future_helpers_update_pending_future() -> None:
    result_future: asyncio.Future[object] = asyncio.Future()
    set_result_if_pending(result_future, "done")

    assert await result_future == "done"

    exception_future: asyncio.Future[object] = asyncio.Future()
    error = RuntimeError("failed")
    set_exception_if_pending(exception_future, error)

    with pytest.raises(RuntimeError, match="failed"):
        await exception_future

    cancel_future: asyncio.Future[object] = asyncio.Future()
    cancel_if_pending(cancel_future)

    assert cancel_future.cancelled()


async def test_future_helpers_ignore_completed_future() -> None:
    result_future: asyncio.Future[object] = asyncio.Future()
    result_future.set_result("original")
    set_result_if_pending(result_future, "ignored")

    assert await result_future == "original"

    exception_future: asyncio.Future[object] = asyncio.Future()
    error = RuntimeError("original")
    exception_future.set_exception(error)
    set_exception_if_pending(exception_future, ValueError("ignored"))

    assert exception_future.exception() is error

    cancel_future: asyncio.Future[object] = asyncio.Future()
    cancel_future.cancel()
    cancel_if_pending(cancel_future)

    assert cancel_future.cancelled()
