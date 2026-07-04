import json

import foghttp
from foghttp.methods import GET
from foghttp.status_codes.success import OK
from tests.support.transport_state import wait_for_async_transport_state
from tests.support.transport_stats import wait_for_async_transport_stats

from .assertions import (
    assert_distinct_connection_payloads,
    assert_distinct_connection_snapshot,
    assert_reused_connection_payloads,
    assert_reused_connection_snapshot,
    has_idle_origin_detail,
    is_early_remote_idle_close_observed,
    is_idle_timeout_eviction_reported,
)
from .constants import (
    EXPECTED_DISTINCT_CONNECTIONS,
    EXPECTED_REUSED_CONNECTIONS,
    KEEPALIVE_PATH,
)
from .server import KeepAliveServer


IDLE_TIMEOUT_SECONDS = 0.05
LONG_IDLE_TIMEOUT_SECONDS = 30.0


async def test_async_client_reuses_keepalive_connection(keepalive_http_server: KeepAliveServer) -> None:
    limits = foghttp.Limits(
        keepalive=True,
        max_idle_connections_per_host=EXPECTED_REUSED_CONNECTIONS,
    )

    async with foghttp.AsyncClient(limits=limits) as client:
        first_response = await client.get(keepalive_http_server.url + KEEPALIVE_PATH)
        second_response = await client.get(keepalive_http_server.url + KEEPALIVE_PATH)

    assert first_response.status_code == OK
    assert second_response.status_code == OK
    assert_reused_connection_payloads(first_response.json(), second_response.json())
    assert_reused_connection_snapshot(keepalive_http_server.snapshot())


async def test_async_stream_reuses_keepalive_connection_after_clean_eof(
    keepalive_http_server: KeepAliveServer,
) -> None:
    limits = foghttp.Limits(
        keepalive=True,
        max_idle_connections_per_host=EXPECTED_REUSED_CONNECTIONS,
    )
    url = keepalive_http_server.url + KEEPALIVE_PATH

    async with (
        foghttp.AsyncClient(limits=limits) as client,
        client.stream(GET, url) as first_response,
    ):
        first_payload = json.loads(b"".join([chunk async for chunk in first_response.aiter_bytes()]))
        second_response = await client.get(url)

    assert first_response.status_code == OK
    assert second_response.status_code == OK
    assert_reused_connection_payloads(first_payload, second_response.json())
    assert_reused_connection_snapshot(keepalive_http_server.snapshot())


async def test_async_client_does_not_reuse_connection_when_keepalive_is_disabled(
    keepalive_http_server: KeepAliveServer,
) -> None:
    limits = foghttp.Limits(keepalive=False)

    async with foghttp.AsyncClient(limits=limits) as client:
        first_response = await client.get(keepalive_http_server.url + KEEPALIVE_PATH)
        second_response = await client.get(keepalive_http_server.url + KEEPALIVE_PATH)

    assert first_response.status_code == OK
    assert second_response.status_code == OK
    assert_distinct_connection_payloads(first_response.json(), second_response.json())
    assert_distinct_connection_snapshot(keepalive_http_server.snapshot())


async def test_async_request_body_write_timeout_path_does_not_reuse_connection(
    keepalive_http_server: KeepAliveServer,
) -> None:
    limits = foghttp.Limits(keepalive=True, max_idle_connections_per_host=1)
    url = keepalive_http_server.url + KEEPALIVE_PATH

    async with foghttp.AsyncClient(limits=limits) as client:
        first_response = await client.post(url, content=b"body")
        second_response = await client.post(url, content=b"body")

    assert first_response.status_code == OK
    assert second_response.status_code == OK
    assert_distinct_connection_payloads(first_response.json(), second_response.json())
    assert_distinct_connection_snapshot(keepalive_http_server.snapshot())


async def test_async_transport_state_reports_idle_connection_detail(
    keepalive_http_server: KeepAliveServer,
) -> None:
    limits = foghttp.Limits(keepalive=True, max_idle_connections_per_host=1)

    async with foghttp.AsyncClient(limits=limits) as client:
        response = await client.get(keepalive_http_server.url + KEEPALIVE_PATH)
        state = await wait_for_async_transport_state(
            client,
            lambda state: has_idle_origin_detail(state, keepalive_http_server.url),
            message="expected per-origin idle connection detail",
        )

    origin_state = state["origins"][keepalive_http_server.url]

    assert response.status_code == OK
    assert set(state["origins"]) == {keepalive_http_server.url}
    assert origin_state["active_requests"] == 0
    assert origin_state["pending_requests"] == 0
    assert origin_state["connections_reused"] == 0
    assert origin_state["connections_closed"] == 0


async def test_async_idle_timeout_eviction_is_reported(
    keepalive_http_server: KeepAliveServer,
) -> None:
    limits = foghttp.Limits(
        keepalive=True,
        max_idle_connections_per_host=1,
        idle_timeout=IDLE_TIMEOUT_SECONDS,
    )

    async with foghttp.AsyncClient(limits=limits) as client:
        response = await client.get(keepalive_http_server.url + KEEPALIVE_PATH)
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.idle_connections == 1,
            message="expected reusable connection to enter the idle pool",
        )
        await wait_for_async_transport_stats(
            client,
            is_idle_timeout_eviction_reported,
            message="expected idle timeout eviction to be visible in stats",
        )
        stats = client.stats()
        state = client.dump_transport_state()

    origin_state = state["origins"][keepalive_http_server.url]

    assert response.status_code == OK
    assert stats.connections_closed == 1
    assert stats.idle_timeout_evictions == 1
    assert origin_state["connections_closed"] == 1
    assert origin_state["idle_timeout_evictions"] == 1


async def test_async_early_remote_idle_close_is_not_idle_timeout_eviction(
    early_close_keepalive_http_server: KeepAliveServer,
) -> None:
    limits = foghttp.Limits(
        keepalive=True,
        max_idle_connections_per_host=1,
        idle_timeout=LONG_IDLE_TIMEOUT_SECONDS,
    )
    url = early_close_keepalive_http_server.url + KEEPALIVE_PATH

    async with foghttp.AsyncClient(limits=limits) as client:
        first_response = await client.get(url)
        second_response = await client.get(url)
        await wait_for_async_transport_stats(
            client,
            is_early_remote_idle_close_observed,
            message="expected early remote close to force a new connection",
        )
        stats = client.stats()
        state = client.dump_transport_state()

    origin_state = state["origins"][early_close_keepalive_http_server.url]

    assert first_response.status_code == OK
    assert second_response.status_code == OK
    assert_distinct_connection_payloads(first_response.json(), second_response.json())
    assert_distinct_connection_snapshot(early_close_keepalive_http_server.snapshot())
    assert stats.connections_opened == EXPECTED_DISTINCT_CONNECTIONS
    assert stats.connections_closed >= 1
    assert stats.connections_reused == 0
    assert stats.idle_timeout_evictions == 0
    assert origin_state["connections_opened"] == EXPECTED_DISTINCT_CONNECTIONS
    assert origin_state["connections_closed"] >= 1
    assert origin_state["connections_reused"] == 0
    assert origin_state["idle_timeout_evictions"] == 0
