__all__ = ("TLSServer",)

from dataclasses import dataclass
from http.server import ThreadingHTTPServer
import threading

from .constants import TLS_HOST


SERVER_JOIN_TIMEOUT = 1.0


@dataclass(slots=True)
class TLSServer:
    server: ThreadingHTTPServer
    thread: threading.Thread

    @property
    def url(self) -> str:
        _host, port = self.server.server_address
        return f"https://{TLS_HOST}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=SERVER_JOIN_TIMEOUT)

    def __enter__(self) -> "TLSServer":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()
