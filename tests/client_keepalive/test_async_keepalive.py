import foghttp
from foghttp.status_codes.success import OK

from .assertions import (
    assert_distinct_connection_payloads,
    assert_distinct_connection_snapshot,
    assert_reused_connection_payloads,
    assert_reused_connection_snapshot,
)
from .constants import EXPECTED_REUSED_CONNECTIONS, KEEPALIVE_PATH
from .server import KeepAliveServer


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
