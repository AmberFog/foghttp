__all__ = (
    "FaultInjectionServer",
    "start_fault_injection_server",
)

from dataclasses import dataclass
from socketserver import BaseRequestHandler, ThreadingTCPServer
import threading
from typing import TYPE_CHECKING, Self, cast
from urllib.parse import urlsplit

from foghttp.status_codes.client_error import BAD_REQUEST, NOT_FOUND

from .models import FaultInjectionSnapshot
from .protocol import parse_request, read_request_head, request_closes_connection
from .responses import write_empty_response, write_fault_response
from .state import FaultInjectionState


if TYPE_CHECKING:
    from socket import socket


SERVER_HOST = "127.0.0.1"
SERVER_JOIN_TIMEOUT = 1.0
SOCKET_TIMEOUT = 1.0
WAIT_TIMEOUT = 2.0


@dataclass(slots=True)
class FaultInjectionServer:
    server: "FaultInjectionTCPServer"
    thread: threading.Thread

    @property
    def url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def snapshot(self) -> FaultInjectionSnapshot:
        return self.server.state.snapshot()

    def wait_for_path_hits(
        self,
        path: str,
        expected: int,
        *,
        timeout: float = WAIT_TIMEOUT,
    ) -> None:
        self.server.state.wait_for_path_hits(path, expected, timeout=timeout)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=SERVER_JOIN_TIMEOUT)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()


def start_fault_injection_server() -> FaultInjectionServer:
    state = FaultInjectionState()
    server = FaultInjectionTCPServer((SERVER_HOST, 0), FaultInjectionHTTPHandler)
    server.state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return FaultInjectionServer(server=server, thread=thread)


class FaultInjectionTCPServer(ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    state: FaultInjectionState


class FaultInjectionHTTPHandler(BaseRequestHandler):
    def handle(self) -> None:
        connection = cast("socket", self.request)
        connection.settimeout(SOCKET_TIMEOUT)
        server = cast("FaultInjectionTCPServer", self.server)
        connection_id = server.state.register_connection()
        pending = b""

        while True:
            request_head, pending = read_request_head(connection, pending)
            if request_head is None:
                return

            request = parse_request(request_head)
            if request is None:
                write_empty_response(connection, BAD_REQUEST, "Bad Request", close=True)
                return

            path = urlsplit(request.target).path
            request_index = server.state.record_request(connection_id, path)
            close_after_response = request_closes_connection(request.headers)
            try:
                result = write_fault_response(
                    connection,
                    path=path,
                    connection_id=connection_id,
                    request_index=request_index,
                    close=close_after_response,
                )
            except OSError:
                return

            if not result.handled:
                write_empty_response(connection, NOT_FOUND, "Not Found", close=True)
                return
            if result.closes_connection:
                return
