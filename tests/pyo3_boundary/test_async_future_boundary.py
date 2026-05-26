import asyncio
from typing import Any

import foghttp
from foghttp.methods import GET
from foghttp.status_codes.success import OK
from tests.client_streaming.constants import GATED_STREAM_PATH
from tests.client_streaming.server import start_async_streaming_server

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

    assert responses
    assert cancellations
    assert all(response.status_code == OK for response in responses)
