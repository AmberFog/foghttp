from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import socket
from socketserver import BaseRequestHandler
import sys
import threading

import pytest

from tests.support.sync_server import SyncTCPServer


def test_stop_closes_idle_peer_and_joins_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    accepted: Queue[tuple[socket.socket, threading.Thread]] = Queue()
    polls: list[float] = []
    socket_closed = threading.Event()
    release_handler = threading.Event()

    class ObservedServer(SyncTCPServer):
        def serve_forever(self, poll_interval: float = 0.5) -> None:
            polls.append(poll_interval)
            super().serve_forever(poll_interval)

        def close_request(self, request: socket.socket | tuple[bytes, socket.socket]) -> None:
            super().close_request(request)
            socket_closed.set()
            release_handler.wait()

    class IdleHandler(BaseRequestHandler):
        def handle(self) -> None:
            accepted.put((self.request, threading.current_thread()))
            self.request.recv(1)

    server = ObservedServer(("127.0.0.1", 0), IdleHandler)
    thread = server.start()
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            with socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=3) as peer:
                transport, handler = accepted.get(timeout=2)
                join = handler.join

                def join_handler(timeout: float | None = None) -> None:
                    assert socket_closed.wait(timeout=2)
                    release_handler.set()
                    join(timeout)

                monkeypatch.setattr(handler, "join", join_handler)
                executor.submit(server.stop, thread).result(timeout=3)
                assert peer.recv(1) == b""
                assert transport.fileno() == -1
                assert not handler.is_alive()
                assert not thread.is_alive()
                assert server.fileno() == -1
                assert polls == [0.01]
        finally:
            release_handler.set()
            if thread.is_alive():
                server.stop(thread)


def test_interrupted_start_cannot_serve_a_closed_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    resume = threading.Event()
    started: Queue[threading.Thread] = Queue()
    errors: list[threading.ExceptHookArgs] = []
    start = threading.Thread.start

    def interrupt_start(thread: threading.Thread) -> None:
        run = thread.run
        join = thread.join

        def delayed_run() -> None:
            resume.wait()
            run()

        def resume_and_join(timeout: float | None = None) -> None:
            resume.set()
            join(timeout)

        monkeypatch.setattr(thread, "run", delayed_run)
        monkeypatch.setattr(thread, "join", resume_and_join)
        start(thread)
        started.put(thread)
        raise KeyboardInterrupt

    monkeypatch.setattr(threading, "excepthook", errors.append)
    monkeypatch.setattr(threading.Thread, "start", interrupt_start)
    server = SyncTCPServer(("127.0.0.1", 0), BaseRequestHandler)
    try:
        with pytest.raises(KeyboardInterrupt):
            server.start()
        assert server.fileno() == -1
        assert not started.get(timeout=2).is_alive()
    finally:
        resume.set()
    assert not errors


def test_stop_after_request_thread_cannot_start(monkeypatch: pytest.MonkeyPatch) -> None:
    accepted: Queue[threading.Thread] = Queue()
    errors: Queue[BaseException | None] = Queue()
    failure = RuntimeError("cannot start request thread")

    class ObservedServer(SyncTCPServer):
        def handle_error(self, _request: object, _client_address: object) -> None:
            errors.put(sys.exception())

    class IdleHandler(BaseRequestHandler):
        def handle(self) -> None:
            accepted.put(threading.current_thread())
            self.request.recv(1)

    def fail_start(_thread: threading.Thread) -> None:
        raise failure

    server = ObservedServer(("127.0.0.1", 0), IdleHandler)
    address = ("127.0.0.1", server.server_address[1])
    thread = server.start()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor, socket.create_connection(address, timeout=3) as first:
            worker = accepted.get(timeout=2)
            with monkeypatch.context() as patch:
                patch.setattr(threading.Thread, "start", fail_start)
                with socket.create_connection(address, timeout=3) as second:
                    assert errors.get(timeout=2) is failure
                    assert second.recv(1) == b""
            executor.submit(server.stop, thread).result(timeout=3)
            assert first.recv(1) == b""
            assert not worker.is_alive()
            assert not thread.is_alive()
            assert server.fileno() == -1
    finally:
        if thread.is_alive():
            server.stop(thread)
