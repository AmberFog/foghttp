from collections.abc import Iterator

import pytest

from .server import KeepAliveServer, start_keepalive_server


@pytest.fixture
def keepalive_http_server() -> Iterator[KeepAliveServer]:
    with start_keepalive_server() as server:
        yield server


@pytest.fixture
def idle_timeout_http_server() -> Iterator[KeepAliveServer]:
    # A server-side timeout must not satisfy client-side pool expiry tests.
    with start_keepalive_server(socket_timeout=None) as server:
        yield server


@pytest.fixture
def early_close_keepalive_http_server() -> Iterator[KeepAliveServer]:
    with start_keepalive_server(disconnect_after_response=True) as server:
        yield server
