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


def test_sync_client_reuses_keepalive_connection(keepalive_http_server: KeepAliveServer) -> None:
    limits = foghttp.Limits(
        keepalive=True,
        max_idle_connections_per_host=EXPECTED_REUSED_CONNECTIONS,
    )

    with foghttp.Client(limits=limits) as client:
        first_response = client.get(keepalive_http_server.url + KEEPALIVE_PATH)
        second_response = client.get(keepalive_http_server.url + KEEPALIVE_PATH)

    assert first_response.status_code == OK
    assert second_response.status_code == OK
    assert_reused_connection_payloads(first_response.json(), second_response.json())
    assert_reused_connection_snapshot(keepalive_http_server.snapshot())


def test_sync_client_does_not_reuse_connection_when_keepalive_is_disabled(
    keepalive_http_server: KeepAliveServer,
) -> None:
    limits = foghttp.Limits(keepalive=False)

    with foghttp.Client(limits=limits) as client:
        first_response = client.get(keepalive_http_server.url + KEEPALIVE_PATH)
        second_response = client.get(keepalive_http_server.url + KEEPALIVE_PATH)

    assert first_response.status_code == OK
    assert second_response.status_code == OK
    assert_distinct_connection_payloads(first_response.json(), second_response.json())
    assert_distinct_connection_snapshot(keepalive_http_server.snapshot())


def test_sync_request_body_write_timeout_path_does_not_reuse_connection(
    keepalive_http_server: KeepAliveServer,
) -> None:
    limits = foghttp.Limits(keepalive=True, max_idle_connections_per_host=1)
    url = keepalive_http_server.url + KEEPALIVE_PATH

    with foghttp.Client(limits=limits) as client:
        first_response = client.post(url, content=b"body")
        second_response = client.post(url, content=b"body")

    assert first_response.status_code == OK
    assert second_response.status_code == OK
    assert_distinct_connection_payloads(first_response.json(), second_response.json())
    assert_distinct_connection_snapshot(keepalive_http_server.snapshot())
