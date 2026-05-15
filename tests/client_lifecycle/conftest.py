from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import threading
from typing import Any
from urllib.parse import urlsplit

import pytest

import foghttp
from foghttp.status_codes.server_error import INTERNAL_SERVER_ERROR
from foghttp.status_codes.success import OK

from .constants import BLOCKING_RESPONSE_PATH, OK_BODY
from .helpers import BlockingSyncHTTPServer, CloseTrackingRawClient, RawClientFactory


@pytest.fixture
def raw_client() -> CloseTrackingRawClient:
    return CloseTrackingRawClient()


@pytest.fixture
def raw_client_factory(raw_client: CloseTrackingRawClient) -> RawClientFactory:
    return RawClientFactory(raw_client)


@pytest.fixture
def sync_blocking_http_server() -> Iterator[BlockingSyncHTTPServer]:
    request_started = threading.Event()
    release_response = threading.Event()

    class BlockingHTTPHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            if urlsplit(self.path).path != BLOCKING_RESPONSE_PATH:
                self.send_response(INTERNAL_SERVER_ERROR)
                self.send_header("content-length", "0")
                self.send_header("connection", "close")
                self.end_headers()
                return

            request_started.set()
            if not release_response.wait(timeout=2.0):
                self.send_response(INTERNAL_SERVER_ERROR)
                self.send_header("content-length", "0")
                self.send_header("connection", "close")
                self.end_headers()
                return

            self.send_response(OK)
            self.send_header("content-length", str(len(OK_BODY)))
            self.send_header("connection", "close")
            self.end_headers()
            self.wfile.write(OK_BODY)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), BlockingHTTPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield BlockingSyncHTTPServer(
            base_url=f"http://{host}:{port}",
            request_started=request_started,
            release_response=release_response,
        )
    finally:
        release_response.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


@pytest.fixture
def sync_client_factory(
    monkeypatch: pytest.MonkeyPatch,
    raw_client_factory: RawClientFactory,
) -> Iterator[type[foghttp.Client]]:
    client_module = importlib.import_module("foghttp.client")
    monkeypatch.setattr(client_module, "create_raw_client", raw_client_factory.create)
    yield foghttp.Client


@pytest.fixture
def async_client_factory(
    monkeypatch: pytest.MonkeyPatch,
    raw_client_factory: RawClientFactory,
) -> Iterator[type[foghttp.AsyncClient]]:
    client_module = importlib.import_module("foghttp.async_client")
    monkeypatch.setattr(client_module, "create_raw_client", raw_client_factory.create)
    yield foghttp.AsyncClient


@pytest.fixture
def sync_noop_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    client_module = importlib.import_module("foghttp.client")

    def fake_send_raw_request(**_kwargs: object) -> object:
        return object()

    def fake_response_from_raw(**_kwargs: object) -> object:
        return object()

    monkeypatch.setattr(client_module, "send_raw_request", fake_send_raw_request)
    monkeypatch.setattr(client_module, "response_from_raw", fake_response_from_raw)


@pytest.fixture
def async_noop_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    client_module = importlib.import_module("foghttp.async_client")

    async def fake_send_raw_request_async(**_kwargs: object) -> object:
        return object()

    def fake_response_from_raw(**_kwargs: object) -> object:
        return object()

    monkeypatch.setattr(client_module, "send_raw_request_async", fake_send_raw_request_async)
    monkeypatch.setattr(client_module, "response_from_raw", fake_response_from_raw)
