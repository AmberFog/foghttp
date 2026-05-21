__all__ = (
    "ParsedRequest",
    "parse_request",
    "read_request_head",
    "request_closes_connection",
)

from dataclasses import dataclass
from socket import socket


HTTP_HEAD_END = b"\r\n\r\n"
SOCKET_READ_SIZE = 4096


@dataclass(frozen=True, slots=True)
class ParsedRequest:
    target: str
    headers: dict[str, str]


def read_request_head(connection: socket, pending: bytes) -> tuple[bytes | None, bytes]:
    while HTTP_HEAD_END not in pending:
        try:
            chunk = connection.recv(SOCKET_READ_SIZE)
        except (OSError, TimeoutError):
            return None, pending
        if not chunk:
            return None, pending
        pending += chunk

    request_head, _separator, rest = pending.partition(HTTP_HEAD_END)
    return request_head + HTTP_HEAD_END, rest


def parse_request(request_head: bytes) -> ParsedRequest | None:
    lines = request_head.decode("iso-8859-1").split("\r\n")
    try:
        _method, target, _version = lines[0].split(maxsplit=2)
    except ValueError:
        return None

    return ParsedRequest(
        target=target,
        headers=_parse_headers(lines[1:]),
    )


def request_closes_connection(headers: dict[str, str]) -> bool:
    tokens = {token.strip().casefold() for token in headers.get("connection", "").split(",")}
    return "close" in tokens


def _parse_headers(lines: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in lines:
        name, separator, value = line.partition(":")
        if separator:
            headers[name.strip().casefold()] = value.strip()
    return headers
