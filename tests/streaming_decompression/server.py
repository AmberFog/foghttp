__all__ = ("DecompressionServer", "ServerFactory", "start_decompression_server")

from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
import threading
from typing import TypeAlias
from urllib.parse import urlsplit

from tests.client_keepalive.server import KeepAliveState
from tests.client_proxy.http_proxy_server import ProxyRequest
from tests.client_streaming.server import SyncStreamingHTTPServer

from .constants import WAIT_TIMEOUT
from .payloads import EncodedResponse


@dataclass(slots=True)
class DecompressionServer:
    url: str
    state: KeepAliveState
    prefix_sent: threading.Event = field(default_factory=threading.Event)
    release_tail: threading.Event = field(default_factory=threading.Event)
    requests: list[ProxyRequest] = field(default_factory=list)


ServerFactory: TypeAlias = Callable[[EncodedResponse], DecompressionServer]


@contextmanager
def start_decompression_server(response: EncodedResponse) -> Iterator[DecompressionServer]:
    state = KeepAliveState()
    handle: DecompressionServer

    class DecompressionHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self) -> None:
            super().setup()
            self.connection_id = state.register_connection()

        def do_GET(self) -> None:
            state.record_request(self.connection_id)
            handle.requests.append(
                ProxyRequest(
                    request_line=self.requestline,
                    headers={name.lower(): self.headers.get_all(name, []) for name in self.headers},
                    body=b"",
                ),
            )
            selected = response
            if urlsplit(self.path).path == "/healthy":
                selected = EncodedResponse(b"healthy", encodings=())
            with suppress(OSError):
                self._write_response(selected)

        def do_HEAD(self) -> None:
            self.do_GET()

        def _write_response(self, selected: EncodedResponse) -> None:
            self.send_response(selected.status)
            for encoding in selected.encodings:
                self.send_header("content-encoding", encoding)
            self.send_header("content-length", str(len(selected.body)))
            self.send_header("content-type", "text/plain; charset=utf-8")
            self.send_header("etag", '"encoded-validator"')
            self.send_header("x-connection-id", str(self.connection_id))
            self.end_headers()
            if self.command == "HEAD" or selected.status in {
                HTTPStatus.NO_CONTENT,
                HTTPStatus.RESET_CONTENT,
                HTTPStatus.NOT_MODIFIED,
            }:
                return
            _write_body(self, selected, handle)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = SyncStreamingHTTPServer(("127.0.0.1", 0), DecompressionHandler)
    server.daemon_threads = True
    handle = DecompressionServer(url=f"http://127.0.0.1:{server.server_port}", state=state)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield handle
    finally:
        handle.release_tail.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=WAIT_TIMEOUT)
        if thread.is_alive():
            msg = "decompression server did not stop"
            raise AssertionError(msg)


def _write_body(handler: BaseHTTPRequestHandler, response: EncodedResponse, server: DecompressionServer) -> None:
    if response.gate_after is not None:
        handler.wfile.write(response.body[: response.gate_after])
        handler.wfile.flush()
        server.prefix_sent.set()
        if not server.release_tail.wait(timeout=WAIT_TIMEOUT) or response.close_before_tail:
            handler.close_connection = True
            return
        handler.wfile.write(response.body[response.gate_after :])
    else:
        handler.wfile.write(response.body)
    handler.wfile.flush()
