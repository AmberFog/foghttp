import asyncio
from concurrent.futures import ThreadPoolExecutor
import os

import pytest

import foghttp
from foghttp.status_codes.success import OK

from .constants import BLOCKING_RESPONSE_PATH
from .fork_actions import (
    request_with_async_client,
    request_with_sync_client,
    run_in_fork,
)
from .helpers import BlockingSyncHTTPServer


pytestmark = pytest.mark.skipif(not hasattr(os, "fork"), reason="os.fork is unavailable")


def test_inherited_sync_client_close_does_not_touch_parent_resources(
    sync_http_server: str,
) -> None:
    client = foghttp.Client()
    try:
        request_with_sync_client(client, sync_http_server)

        result = run_in_fork(client.close)

        assert result.ok is True
        assert result.exit_status == 0
        request_with_sync_client(client, sync_http_server)
    finally:
        client.close()


def test_inherited_sync_client_close_while_parent_request_is_active(
    sync_blocking_http_server: BlockingSyncHTTPServer,
) -> None:
    client = foghttp.Client()
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        response_future = executor.submit(
            client.get,
            f"{sync_blocking_http_server.base_url}{BLOCKING_RESPONSE_PATH}",
        )
        assert sync_blocking_http_server.request_started.wait(timeout=1.0)

        result = run_in_fork(client.close)

        assert result.ok is True
        assert result.exit_status == 0
        sync_blocking_http_server.release_response.set()
        assert response_future.result(timeout=2.0).status_code == OK
    finally:
        sync_blocking_http_server.release_response.set()
        executor.shutdown(wait=True, cancel_futures=True)
        client.close()


def test_inherited_async_client_close_does_not_touch_parent_resources(
    sync_http_server: str,
) -> None:
    client = foghttp.AsyncClient()
    try:
        request_with_async_client(client, sync_http_server)

        result = run_in_fork(lambda: asyncio.run(client.aclose()))

        assert result.ok is True
        assert result.exit_status == 0
        request_with_async_client(client, sync_http_server)
    finally:
        asyncio.run(client.aclose())
