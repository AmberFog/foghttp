__all__ = (
    "ConnectProxy",
    "ConnectRecord",
    "start_connect_proxy",
)

from contextlib import suppress
from dataclasses import dataclass, field
import socket
import socketserver
import threading

from foghttp.status_codes.redirect import FOUND


PROXY_HOST = "127.0.0.1"
_TUNNEL_ESTABLISHED = b"HTTP/1.1 200 Connection Established\r\n\r\n"
_PIPE_CHUNK = 65536
_MAX_HEAD_BYTES = 8192


@dataclass(frozen=True, slots=True)
class ConnectRecord:
    authority: str
    proxy_authorization: str | None


@dataclass(slots=True)
class _ProxyConfig:
    require_auth: bool
    expected_authorization: str | None
    reject_status: int | None
    reject_body: bytes
    early_close: bool
    http_redirect_location: str | None
    hang: bool


@dataclass(slots=True)
class ConnectProxy:
    server: socketserver.ThreadingTCPServer
    thread: threading.Thread
    _records: list[ConnectRecord] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def connects(self) -> list[ConnectRecord]:
        with self._lock:
            return list(self._records)

    def record(self, connect: ConnectRecord) -> None:
        with self._lock:
            self._records.append(connect)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)


def start_connect_proxy(
    *,
    require_auth: bool = False,
    expected_authorization: str | None = None,
    reject_status: int | None = None,
    reject_body: bytes = b"",
    early_close: bool = False,
    http_redirect_location: str | None = None,
    hang: bool = False,
) -> ConnectProxy:
    config = _ProxyConfig(
        require_auth=require_auth,
        expected_authorization=expected_authorization,
        reject_status=reject_status,
        reject_body=reject_body,
        early_close=early_close,
        http_redirect_location=http_redirect_location,
        hang=hang,
    )

    class _Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = _Server((PROXY_HOST, 0), _ConnectHandler)
    proxy = ConnectProxy(server=server, thread=threading.Thread())
    server.proxy = proxy  # type: ignore[attr-defined]
    server.config = config  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    proxy.thread = thread
    return proxy


class _ConnectHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        proxy: ConnectProxy = self.server.proxy  # type: ignore[attr-defined]
        config: _ProxyConfig = self.server.config  # type: ignore[attr-defined]

        head = _read_head(self.request)
        if head is None:
            return
        method, authority, headers = _parse_head(head)
        authorization = headers.get("proxy-authorization")

        if method != "CONNECT":
            _handle_non_connect(self.request, config)
            return

        proxy.record(ConnectRecord(authority=authority, proxy_authorization=authorization))
        self._serve_tunnel(config, authority, authorization)

    def _serve_tunnel(
        self,
        config: _ProxyConfig,
        authority: str,
        authorization: str | None,
    ) -> None:
        if config.require_auth and authorization != config.expected_authorization:
            _send_status(self.request, 407, "Proxy Authentication Required")
            return
        if config.reject_status is not None:
            _send_status(
                self.request,
                config.reject_status,
                "Proxy Error",
                body=config.reject_body,
            )
            return
        if config.hang:
            # Accept the CONNECT but never answer: blocks until the client gives
            # up (connect timeout) or cancels and drops the socket.
            self.request.recv(1)
            return

        upstream = _open_upstream(authority)
        if upstream is None:
            _send_status(self.request, 502, "Bad Gateway")
            return
        with upstream:
            self.request.sendall(_TUNNEL_ESTABLISHED)
            if config.early_close:
                return
            _pipe(self.request, upstream)


def _handle_non_connect(connection: socket.socket, config: _ProxyConfig) -> None:
    if config.http_redirect_location is not None:
        _send_redirect(connection, config.http_redirect_location)
        return
    _send_status(connection, 405, "Method Not Allowed")


def _read_head(connection: socket.socket) -> bytes | None:
    buffer = bytearray()
    while b"\r\n\r\n" not in buffer:
        chunk = connection.recv(1)
        if not chunk:
            return None
        buffer.extend(chunk)
        if len(buffer) > _MAX_HEAD_BYTES:
            return None
    return bytes(buffer)


def _parse_head(head: bytes) -> tuple[str, str, dict[str, str]]:
    text = head.decode("latin-1")
    lines = text.split("\r\n")
    request_line = lines[0].split(" ")
    method = request_line[0]
    authority = request_line[1] if len(request_line) > 1 else ""
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return method, authority, headers


def _open_upstream(authority: str) -> socket.socket | None:
    host, _, port = authority.rpartition(":")
    try:
        return socket.create_connection((host.strip("[]"), int(port)), timeout=2)
    except (OSError, ValueError):
        return None


def _send_status(
    connection: socket.socket,
    status: int,
    reason: str,
    *,
    body: bytes = b"",
) -> None:
    response = (f"HTTP/1.1 {status} {reason}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode(
        "latin-1",
    )
    with suppress(OSError):
        connection.sendall(response + body)


def _send_redirect(connection: socket.socket, location: str) -> None:
    response = f"HTTP/1.1 {FOUND} Found\r\nLocation: {location}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    with suppress(OSError):
        connection.sendall(response.encode("latin-1"))


def _pipe(client: socket.socket, upstream: socket.socket) -> None:
    forward = threading.Thread(target=_copy, args=(client, upstream), daemon=True)
    backward = threading.Thread(target=_copy, args=(upstream, client), daemon=True)
    forward.start()
    backward.start()
    forward.join()
    backward.join()


def _copy(source: socket.socket, destination: socket.socket) -> None:
    try:
        while True:
            data = source.recv(_PIPE_CHUNK)
            if not data:
                break
            destination.sendall(data)
    except OSError:
        return
    finally:
        with suppress(OSError):
            destination.shutdown(socket.SHUT_WR)
