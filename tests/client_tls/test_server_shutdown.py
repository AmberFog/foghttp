from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import socket
import ssl
import threading

import pytest

from .certificates import TLSCertificateBundle
from .constants import TLS_HOST
from .server import start_tls_server


def test_failed_scope_closes_incomplete_tls_handshake(
    tls_certificates: TLSCertificateBundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handshakes: Queue[tuple[ssl.SSLSocket, threading.Thread]] = Queue()
    handshake = ssl.SSLSocket.do_handshake

    def observe(peer: ssl.SSLSocket) -> None:
        handshakes.put((peer, threading.current_thread()))
        handshake(peer)

    monkeypatch.setattr(ssl.SSLSocket, "do_handshake", observe)
    server = start_tls_server(tls_certificates)

    def fail_in_server_scope() -> None:
        with server:
            msg = "fixture body failed"
            raise RuntimeError(msg)

    try:
        with (
            ThreadPoolExecutor(max_workers=1) as executor,
            socket.create_connection((TLS_HOST, server.server.server_address[1]), timeout=3) as peer,
        ):
            transport, handler = handshakes.get(timeout=2)
            with pytest.raises(RuntimeError, match="fixture body failed"):
                executor.submit(fail_in_server_scope).result(timeout=3)
            assert peer.recv(1) == b""
            assert transport.fileno() == -1
            assert not handler.is_alive()
            assert not server.thread.is_alive()
            assert server.server.fileno() == -1
    finally:
        if server.thread.is_alive():
            server.close()
