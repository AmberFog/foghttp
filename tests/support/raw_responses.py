__all__ = (
    "SECURITY_HEADER_NAMES",
    "header_values",
    "headers_payload",
    "json_payload",
    "raw_http_server_response",
    "raw_response",
    "security_headers_payload",
)

from http import HTTPStatus
import json
from urllib.parse import urlsplit

from foghttp.methods import HEAD
from foghttp.status_codes.redirect import FOUND
from foghttp.status_codes.success import OK
from tests.http_body_scenarios import raw_too_large_size_hint_response
from tests.support.http_routes import (
    ECHO_HEADERS_PATH,
    OBS_TEXT_HEADERS_PATH,
    REPEATED_HEADERS_PATH,
    SECURITY_HEADERS_PATH,
    TEXT_PATH,
    bytes_response_size,
    cookie_response,
    redirect_status,
    redirect_to_location,
    redirect_to_status,
    status_code,
    unknown_size_bytes_response_size,
)


SECURITY_HEADER_NAMES = (
    "accept",
    "authorization",
    "content-checksum",
    "content-digest",
    "content-disposition",
    "content-encoding",
    "content-language",
    "content-length",
    "content-location",
    "content-range",
    "content-type",
    "cookie",
    "digest",
    "host",
    "if-match",
    "if-modified-since",
    "if-none-match",
    "if-range",
    "if-unmodified-since",
    "last-modified",
    "origin",
    "proxy-authorization",
    "referer",
    "repr-digest",
    "transfer-encoding",
    "x-api-key",
)


def header_values(headers: str, name: str) -> list[str]:
    values: list[str] = []
    for line in headers.splitlines()[1:]:
        header_name, separator, value = line.partition(":")
        if separator and header_name.lower() == name:
            values.append(value.strip())
    return values


def headers_payload(values: list[str]) -> bytes:
    return json.dumps({"x-repeat": values}).encode()


def security_headers_payload(*, headers: dict[str, list[str]], request_line: str, body: bytes) -> bytes:
    return json.dumps(
        {
            "headers": headers,
            "request_line": request_line,
            "body": body.decode(),
        },
    ).encode()


def raw_response(
    status_code: int,
    reason: str,
    headers: list[tuple[str, str]],
    content: bytes = b"",
) -> bytes:
    header_lines = "".join(f"{name}: {value}\r\n" for name, value in headers)
    head = f"HTTP/1.1 {status_code} {reason}\r\n{header_lines}\r\n".encode("latin-1")
    return head + content


def raw_http_server_response(headers: str, body: bytes) -> bytes:
    request_line = headers.splitlines()[0]
    method, target, _version = request_line.split()
    target_parts = urlsplit(target)
    path = target_parts.path
    response = (
        _raw_cookie_response(path, target_parts.query, headers)
        or _raw_redirect_to_location_response(path, target_parts.query)
        or _raw_redirect_to_status_response(path)
        or _raw_redirect_response(path)
        or _raw_status_response(path)
        or raw_too_large_size_hint_response(path)
        or _raw_bytes_response(path)
        or _raw_unknown_size_bytes_response(path)
        or _raw_text_response(path)
        or _raw_repeated_headers_response(path)
        or _raw_obs_text_headers_response(path)
        or _raw_echo_headers_response(path, headers)
        or _raw_security_headers_response(path, headers, body)
    )
    return response or _raw_json_response(method=method, request_line=request_line, body=body)


def _raw_cookie_response(path: str, query: str, headers: str) -> bytes | None:
    response = cookie_response(path, query, header_values(headers, "cookie"))
    if response is None:
        return None
    status_code, response_headers, content = response
    return raw_response(
        status_code,
        _reason_phrase(status_code),
        [
            *response_headers,
            ("content-length", str(len(content))),
            ("connection", "close"),
        ],
        content,
    )


def json_payload(*, request_line: str, body: bytes) -> bytes:
    return json.dumps(
        {
            "request_line": request_line,
            "body": body.decode(),
        },
    ).encode()


def _raw_empty_response(status: int, reason: str, headers: list[tuple[str, str]]) -> bytes:
    return raw_response(
        status,
        reason,
        [*headers, ("content-length", "0"), ("connection", "close")],
    )


def _raw_redirect_to_status_response(path: str) -> bytes | None:
    redirect = redirect_to_status(path)
    if redirect is None:
        return None

    redirect_code, final_status = redirect
    return _raw_empty_response(redirect_code, "Redirect", [("location", f"/status/{final_status}")])


def _raw_redirect_to_location_response(path: str, query: str) -> bytes | None:
    redirect = redirect_to_location(path, query)
    if redirect is None:
        return None

    redirect_code, location = redirect
    return _raw_empty_response(redirect_code, "Redirect", [("location", location)])


def _raw_redirect_response(path: str) -> bytes | None:
    redirect_code = redirect_status(path)
    if redirect_code is not None:
        return _raw_empty_response(redirect_code, "Redirect", [("location", "/final")])
    if path == "/loop":
        return _raw_empty_response(FOUND, "Redirect", [("location", "/loop")])
    return None


def _raw_status_response(path: str) -> bytes | None:
    status = status_code(path)
    if status is None:
        return None

    return _raw_empty_response(status, _reason_phrase(status), [])


def _raw_bytes_response(path: str) -> bytes | None:
    response_size = bytes_response_size(path)
    if response_size is None:
        return None

    content = b"x" * response_size
    return raw_response(
        OK,
        "OK",
        [
            ("content-type", "application/octet-stream"),
            ("content-length", str(len(content))),
            ("connection", "close"),
        ],
        content,
    )


def _raw_unknown_size_bytes_response(path: str) -> bytes | None:
    response_size = unknown_size_bytes_response_size(path)
    if response_size is None:
        return None

    content = b"x" * response_size
    return raw_response(
        OK,
        "OK",
        [
            ("content-type", "application/octet-stream"),
            ("connection", "close"),
        ],
        content,
    )


def _raw_text_response(path: str) -> bytes | None:
    if path != TEXT_PATH:
        return None

    content = b"Latin-1: \xe9"
    return raw_response(
        OK,
        "OK",
        [
            ("content-type", "text/plain; charset=iso-8859-1"),
            ("content-length", str(len(content))),
            ("connection", "close"),
        ],
        content,
    )


def _raw_repeated_headers_response(path: str) -> bytes | None:
    if path != REPEATED_HEADERS_PATH:
        return None

    return _raw_empty_response(
        OK,
        "OK",
        [
            ("set-cookie", "first=1"),
            ("set-cookie", "second=2"),
            ("x-trace", "one"),
            ("x-trace", "two"),
        ],
    )


def _raw_obs_text_headers_response(path: str) -> bytes | None:
    if path != OBS_TEXT_HEADERS_PATH:
        return None

    return (
        b"HTTP/1.1 200 OK\r\n"
        b"x-obs-text: value-\xe9\r\n"
        b"x-repeat: ascii\r\n"
        b"x-repeat: repeat-\xe9\r\n"
        b"content-length: 0\r\n"
        b"connection: close\r\n"
        b"\r\n"
    )


def _raw_echo_headers_response(path: str, headers: str) -> bytes | None:
    if path != ECHO_HEADERS_PATH:
        return None

    payload = headers_payload(header_values(headers, "x-repeat"))
    return raw_response(
        OK,
        "OK",
        [
            ("content-type", "application/json"),
            ("content-length", str(len(payload))),
            ("connection", "close"),
        ],
        payload,
    )


def _raw_security_headers_response(path: str, headers: str, body: bytes) -> bytes | None:
    if path != SECURITY_HEADERS_PATH:
        return None

    payload = security_headers_payload(
        headers=_security_headers_from_raw(headers),
        request_line=headers.splitlines()[0],
        body=body,
    )
    return raw_response(
        OK,
        "OK",
        [
            ("content-type", "application/json"),
            ("content-length", str(len(payload))),
            ("connection", "close"),
        ],
        payload,
    )


def _raw_json_response(*, method: str, request_line: str, body: bytes) -> bytes:
    payload = json_payload(request_line=request_line, body=body)
    content = b"" if method == HEAD else payload
    return raw_response(
        OK,
        "OK",
        [
            ("content-type", "application/json"),
            ("content-length", str(len(content))),
            ("connection", "close"),
        ],
        content,
    )


def _security_headers_from_raw(headers: str) -> dict[str, list[str]]:
    return {name: header_values(headers, name) for name in SECURITY_HEADER_NAMES}


def _reason_phrase(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Status"
