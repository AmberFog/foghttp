import asyncio
from collections.abc import Callable
import os
from typing import Literal

import pytest

import foghttp
from foghttp.methods import GET
from foghttp.status_codes.success import OK

from .fork_actions import (
    ForkResult,
    request_with_async_client,
    request_with_new_async_client,
    request_with_new_sync_client,
    request_with_sync_client,
    run_in_fork,
    stream_with_async_client,
    stream_with_sync_client,
)


pytestmark = pytest.mark.skipif(not hasattr(os, "fork"), reason="os.fork is unavailable")


@pytest.mark.parametrize("runtime", ["shared", "dedicated"])
def test_inherited_sync_client_request_after_fork_raises_lifecycle_error(
    sync_http_server: str,
    runtime: Literal["shared", "dedicated"],
) -> None:
    client = foghttp.Client(runtime=runtime)
    try:
        request_with_sync_client(client, sync_http_server)

        result = run_in_fork(lambda: request_with_sync_client(client, sync_http_server))

        _assert_fork_lifecycle_error(result, resource="client")
        request_with_sync_client(client, sync_http_server)
    finally:
        client.close()


def test_inherited_sync_client_stream_after_fork_raises_lifecycle_error(
    sync_http_server: str,
) -> None:
    client = foghttp.Client()
    try:
        request_with_sync_client(client, sync_http_server)

        result = run_in_fork(lambda: stream_with_sync_client(client, sync_http_server))

        _assert_fork_lifecycle_error(result, resource="client")
    finally:
        client.close()


def test_inherited_sync_client_stats_after_fork_raises_lifecycle_error(
    sync_http_server: str,
) -> None:
    client = foghttp.Client()
    try:
        request_with_sync_client(client, sync_http_server)

        result = run_in_fork(client.stats)

        _assert_fork_lifecycle_error(result, resource="client")
    finally:
        client.close()


@pytest.mark.parametrize(
    ("action_name", "action"),
    [
        pytest.param("transport state", foghttp.Client.dump_transport_state, id="transport-state"),
        pytest.param("pool diagnostics", foghttp.Client.dump_pool_diagnostics, id="pool-diagnostics"),
    ],
)
def test_inherited_sync_client_diagnostics_after_fork_raise_lifecycle_error(
    sync_http_server: str,
    action_name: str,
    action: Callable[[foghttp.Client], object],
) -> None:
    client = foghttp.Client()
    try:
        request_with_sync_client(client, sync_http_server)

        result = run_in_fork(lambda: action(client))

        _assert_fork_lifecycle_error(result, resource="client", context=action_name)
    finally:
        client.close()


def test_new_sync_client_after_fork_uses_child_process_runtime(sync_http_server: str) -> None:
    parent_client = foghttp.Client()
    try:
        request_with_sync_client(parent_client, sync_http_server)

        result = run_in_fork(lambda: request_with_new_sync_client(sync_http_server))

        assert result.ok is True
        assert result.exit_status == 0
        request_with_sync_client(parent_client, sync_http_server)
    finally:
        parent_client.close()


@pytest.mark.parametrize("runtime", ["shared", "dedicated"])
def test_inherited_async_client_request_after_fork_raises_lifecycle_error(
    sync_http_server: str,
    runtime: Literal["shared", "dedicated"],
) -> None:
    client = foghttp.AsyncClient(runtime=runtime)
    try:
        request_with_async_client(client, sync_http_server)

        result = run_in_fork(lambda: request_with_async_client(client, sync_http_server))

        _assert_fork_lifecycle_error(result, resource="client")
        request_with_async_client(client, sync_http_server)
    finally:
        asyncio.run(client.aclose())


def test_inherited_async_client_stream_after_fork_raises_lifecycle_error(
    sync_http_server: str,
) -> None:
    client = foghttp.AsyncClient()
    try:
        request_with_async_client(client, sync_http_server)

        result = run_in_fork(lambda: stream_with_async_client(client, sync_http_server))

        _assert_fork_lifecycle_error(result, resource="client")
    finally:
        asyncio.run(client.aclose())


def test_inherited_async_client_lifecycle_debug_after_fork_raises_lifecycle_error(
    sync_http_server: str,
) -> None:
    client = foghttp.AsyncClient(lifecycle_debug=foghttp.AsyncLifecycleDebugConfig())
    try:
        request_with_async_client(client, sync_http_server)

        result = run_in_fork(client.dump_lifecycle_debug)

        _assert_fork_lifecycle_error(result, resource="client")
    finally:
        asyncio.run(client.aclose())


def test_new_async_client_after_fork_uses_child_process_runtime(sync_http_server: str) -> None:
    parent_client = foghttp.AsyncClient()
    try:
        request_with_async_client(parent_client, sync_http_server)

        result = run_in_fork(lambda: request_with_new_async_client(sync_http_server))

        assert result.ok is True
        assert result.exit_status == 0
        request_with_async_client(parent_client, sync_http_server)
    finally:
        asyncio.run(parent_client.aclose())


@pytest.mark.parametrize("client_factory", [foghttp.Client, foghttp.AsyncClient])
def test_lazy_inherited_client_after_fork_raises_before_raw_client_creation(
    client_factory: Callable[[], foghttp.Client | foghttp.AsyncClient],
) -> None:
    client = client_factory()
    try:
        result = run_in_fork(client.stats)

        _assert_fork_lifecycle_error(result, resource="client")
        assert client.stats() == foghttp.TransportStats()
    finally:
        if isinstance(client, foghttp.AsyncClient):
            asyncio.run(client.aclose())
        else:
            client.close()


def test_lazy_inherited_sync_client_send_after_fork_raises_before_lock(
    sync_http_server: str,
) -> None:
    client = foghttp.Client()
    request = client.build_request(GET, sync_http_server)
    try:
        result = run_in_fork(lambda: client.send(request))

        _assert_fork_lifecycle_error(result, resource="client")
        assert client.send(request).status_code == OK
    finally:
        client.close()


def test_lazy_inherited_async_client_send_after_fork_raises_lifecycle_error(
    sync_http_server: str,
) -> None:
    client = foghttp.AsyncClient()
    request = client.build_request(GET, sync_http_server)
    try:
        result = run_in_fork(lambda: asyncio.run(client.send(request)))

        _assert_fork_lifecycle_error(result, resource="client")
        assert asyncio.run(client.send(request)).status_code == OK
    finally:
        asyncio.run(client.aclose())


def test_inherited_client_process_guard_runs_before_client_lock() -> None:
    client = foghttp.Client()
    client._client_lock.acquire()  # noqa: SLF001 - regression target is guard-before-lock ordering.
    try:
        result = run_in_fork(client.stats)
    finally:
        client._client_lock.release()  # noqa: SLF001
        client.close()

    _assert_fork_lifecycle_error(result, resource="client")


def _assert_fork_lifecycle_error(
    result: ForkResult,
    *,
    resource: str,
    context: str = "",
) -> None:
    assert result.ok is False, context
    assert result.error_type == "LifecycleError"
    assert f"FogHTTP {resource} was created" in result.message
    assert "cannot be used in forked process" in result.message
