__all__ = ("StreamingHistoryServer", "start_streaming_history_server")

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
import gzip
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
import threading
from urllib.parse import urlsplit

from tests.client_streaming.server import SyncStreamingHTTPServer


HISTORY_BODY_SIZE = 64 * 1024
FINAL_BODY = b"final streamed payload after redirects"
FINAL_WIRE_BODY = gzip.compress(FINAL_BODY, mtime=0)
RECOVERY_BODY = b"recovered"


@dataclass(frozen=True, slots=True)
class StreamingHistoryServer:
    url: str
    history_bodies: tuple[bytes, ...] = field(repr=False)

    @property
    def start_url(self) -> str:
        return f"{self.url}/history/0"

    @property
    def final_url(self) -> str:
        return f"{self.url}/history/{len(self.history_bodies)}"


@contextmanager
def start_streaming_history_server(history_bodies: tuple[bytes, ...]) -> Iterator[StreamingHistoryServer]:
    class HistoryHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/healthy":
                self._write_response(RECOVERY_BODY)
                return
            hop = int(path.rsplit("/", 1)[-1])
            if hop < len(history_bodies):
                self._write_response(history_bodies[hop], hop=hop)
                return
            self._write_response(FINAL_WIRE_BODY)

        def _write_response(self, body: bytes, *, hop: int | None = None) -> None:
            self.send_response(HTTPStatus.OK if hop is None else HTTPStatus.FOUND)
            self.send_header("content-length", str(len(body)))
            self.send_header("content-type", "application/octet-stream")
            if hop is not None:
                self.send_header("location", f"/history/{hop + 1}")
                self.send_header("x-history-hop", str(hop))
            elif self.path != "/healthy":
                self.send_header("content-encoding", "gzip")
            self.end_headers()
            with suppress(OSError):
                self.wfile.write(body)
                self.wfile.flush()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = SyncStreamingHTTPServer(("127.0.0.1", 0), HistoryHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield StreamingHistoryServer(f"http://127.0.0.1:{server.server_port}", history_bodies)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
        if thread.is_alive():
            msg = "streaming history server did not stop"
            raise AssertionError(msg)
