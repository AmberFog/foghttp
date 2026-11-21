__all__ = ("SyncHTTPServer", "SyncTCPServer")

from collections.abc import Callable
from contextlib import ExitStack
import errno
from http.server import HTTPServer
import socket
from socketserver import BaseRequestHandler, ThreadingTCPServer
import threading
from typing import cast


class SyncTCPServer(ThreadingTCPServer):
    """Stop accepting, wake remaining peers, and wait for their request handlers."""

    def __init__(
        self,
        server_address: tuple[str, int],
        handler: Callable[..., BaseRequestHandler],
    ) -> None:
        self._workers: dict[threading.Thread, socket.socket] = {}
        self._peers_lock = threading.Lock()
        super().__init__(server_address, handler)

    def process_request(
        self,
        request: socket.socket | tuple[bytes, socket.socket],
        client_address: tuple[str, int],
    ) -> None:
        # The accept loop owns this registry until shutdown returns.
        self._workers = {worker: peer for worker, peer in self._workers.items() if worker.is_alive()}
        worker = threading.Thread(target=self.process_request_thread, args=(request, client_address), daemon=False)
        worker.start()
        self._workers[worker] = cast("socket.socket", request)

    def close_request(self, request: socket.socket | tuple[bytes, socket.socket]) -> None:
        with self._peers_lock:
            super().close_request(request)

    def start(self) -> threading.Thread:
        startup_finished = threading.Event()

        def serve() -> None:
            # Thread.start() can be interrupted after the OS thread has launched.
            startup_finished.wait()
            if self.fileno() != -1:
                self.serve_forever(poll_interval=0.01)

        thread = threading.Thread(target=serve, daemon=True)
        try:
            thread.start()
        except BaseException:
            self.server_close()
            raise
        finally:
            startup_finished.set()
            if self.fileno() == -1 and thread.is_alive():
                thread.join()
        return thread

    def stop(self, thread: threading.Thread) -> None:
        self.shutdown()
        try:
            self.server_close()
        finally:
            thread.join(timeout=1)
        if thread.is_alive() or self.fileno() != -1:
            msg = "sync test server did not stop"
            raise RuntimeError(msg)

    def server_close(self) -> None:
        workers, self._workers = self._workers, {}
        with ExitStack() as cleanup:
            for worker in workers:
                cleanup.callback(worker.join)
            cleanup.callback(super().server_close)
            # Interrupt every open peer under the lock, then release it before joining.
            cleanup.enter_context(self._peers_lock)
            for peer in workers.values():
                if peer.fileno() != -1:
                    cleanup.callback(_interrupt_peer, peer)


def _interrupt_peer(peer: socket.socket) -> None:
    try:
        # Wake TLS I/O without changing the SSLSocket state used by its handler.
        socket.socket.shutdown(peer, socket.SHUT_RDWR)
    except ConnectionError:
        return
    except OSError as exc:
        if exc.errno != errno.ENOTCONN and peer.fileno() != -1:
            raise


class SyncHTTPServer(HTTPServer, SyncTCPServer):
    """HTTP request handling with the same thread and socket ownership as TCP fixtures."""
