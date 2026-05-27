__all__ = (
    "TLSHandshakeStallServer",
    "start_tls_handshake_stall_server",
)

from dataclasses import dataclass, field
from socketserver import BaseRequestHandler, ThreadingTCPServer
import threading
from typing import Self, cast

from .constants import TLS_HOST


SERVER_JOIN_TIMEOUT = 1.0
WAIT_TIMEOUT = 2.0


@dataclass(slots=True)
class TLSHandshakeStallServer:
    server: "TLSHandshakeStallTCPServer"
    thread: threading.Thread

    @property
    def url(self) -> str:
        _host, port = cast("tuple[str, int]", self.server.server_address)
        return f"https://{TLS_HOST}:{port}"

    def wait_for_connections(
        self,
        expected: int,
        *,
        timeout: float = WAIT_TIMEOUT,
    ) -> None:
        self.server.state.wait_for_connections(expected, timeout=timeout)

    def close(self) -> None:
        self.server.state.release()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=SERVER_JOIN_TIMEOUT)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()


@dataclass(slots=True)
class TLSHandshakeStallState:
    connections: int = 0
    released: threading.Event = field(default_factory=threading.Event)
    _condition: threading.Condition = field(default_factory=threading.Condition)

    def record_connection(self) -> None:
        with self._condition:
            self.connections += 1
            self._condition.notify_all()

    def wait_for_connections(self, expected: int, *, timeout: float) -> None:
        with self._condition:
            completed = self._condition.wait_for(
                lambda: self.connections >= expected,
                timeout=timeout,
            )
        if not completed:
            msg = f"expected {expected} TLS handshake connection(s), got {self.connections}"
            raise AssertionError(msg)

    def release(self) -> None:
        self.released.set()


def start_tls_handshake_stall_server() -> TLSHandshakeStallServer:
    server = TLSHandshakeStallTCPServer((TLS_HOST, 0), TLSHandshakeStallHandler)
    server.state = TLSHandshakeStallState()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return TLSHandshakeStallServer(server=server, thread=thread)


class TLSHandshakeStallTCPServer(ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    state: TLSHandshakeStallState


class TLSHandshakeStallHandler(BaseRequestHandler):
    def handle(self) -> None:
        server = cast("TLSHandshakeStallTCPServer", self.server)
        server.state.record_connection()
        server.state.released.wait()
