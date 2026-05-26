from collections.abc import Callable, Iterator
from socketserver import BaseRequestHandler, ThreadingTCPServer
import threading
from urllib.parse import urlsplit

import pytest

from .constants import MALFORMED_RESPONSE_PATH, MID_RESPONSE_CLOSE_PATH


class BrokenHTTPServer(ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class BrokenHTTPHandler(BaseRequestHandler):
    def handle(self) -> None:
        request = self.request.recv(4096)
        path = _request_path(request)
        if path == MALFORMED_RESPONSE_PATH:
            self.request.sendall(b"this is not an HTTP response\r\n\r\n")
            return
        if path == MID_RESPONSE_CLOSE_PATH:
            self.request.sendall(
                b"HTTP/1.1 200 OK\r\ncontent-length: 64\r\nconnection: close\r\n\r\npartial body",
            )
            return

        self.request.sendall(
            b"HTTP/1.1 404 Not Found\r\ncontent-length: 0\r\nconnection: close\r\n\r\n",
        )


def _request_path(request: bytes) -> str:
    try:
        request_line = request.split(b"\r\n", 1)[0].decode("ascii")
        _method, target, _version = request_line.split(maxsplit=2)
    except (UnicodeDecodeError, ValueError):
        return ""
    return urlsplit(target).path


@pytest.fixture
def broken_http_server() -> Iterator[str]:
    server = BrokenHTTPServer(("127.0.0.1", 0), BrokenHTTPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


@pytest.fixture
def async_connection_refused_url(
    http_server: str,
    unused_tcp_port_factory: Callable[[], int],
) -> str:
    return _connection_refused_url(unused_tcp_port_factory, http_server)


@pytest.fixture
def sync_connection_refused_url(
    sync_http_server: str,
    unused_tcp_port_factory: Callable[[], int],
) -> str:
    return _connection_refused_url(unused_tcp_port_factory, sync_http_server)


def _connection_refused_url(
    unused_tcp_port_factory: Callable[[], int],
    recovery_server: str,
) -> str:
    recovery_port = urlsplit(recovery_server).port
    refused_port = unused_tcp_port_factory()
    while refused_port == recovery_port:
        refused_port = unused_tcp_port_factory()
    return f"http://127.0.0.1:{refused_port}"
