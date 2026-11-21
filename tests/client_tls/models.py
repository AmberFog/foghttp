__all__ = ("TLSServer",)

from dataclasses import dataclass
import threading

from tests.support.sync_server import SyncHTTPServer

from .constants import TLS_HOST


@dataclass(slots=True)
class TLSServer:
    server: SyncHTTPServer
    thread: threading.Thread

    @property
    def url(self) -> str:
        _host, port = self.server.server_address
        return f"https://{TLS_HOST}:{port}"

    def close(self) -> None:
        self.server.stop(self.thread)

    def __enter__(self) -> "TLSServer":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()
