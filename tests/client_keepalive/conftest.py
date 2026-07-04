from collections.abc import Iterator

import pytest

from .server import KeepAliveServer, start_keepalive_server


@pytest.fixture
def keepalive_http_server() -> Iterator[KeepAliveServer]:
    with start_keepalive_server() as server:
        yield server


@pytest.fixture
def early_close_keepalive_http_server() -> Iterator[KeepAliveServer]:
    with start_keepalive_server(disconnect_after_response=True) as server:
        yield server
