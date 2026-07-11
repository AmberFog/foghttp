__all__ = (
    "assert_cross_origin_query_is_sanitized",
    "assert_query_echo",
    "assert_query_redirect",
)

from typing import Any

from foghttp.methods import QUERY
from foghttp.response import Response
from foghttp.status_codes.success import OK
from tests.redirect_helpers import SECURITY_HEADERS_PATH, header_values


def assert_query_echo(
    response: Response,
    *,
    body: str,
    content_type: str,
) -> None:
    payload = response.json()
    actual_values = {
        "request_line": payload["request_line"],
        "body": payload["body"],
        "content_type": header_values(payload, "content-type"),
    }
    expected_values = {
        "request_line": f"{QUERY} {SECURITY_HEADERS_PATH} HTTP/1.1",
        "body": body,
        "content_type": [content_type],
    }
    if actual_values != expected_values:
        raise AssertionError(actual_values)


def assert_query_redirect(
    response: Response,
    *,
    base_url: str,
    status_code: int,
    body: str,
) -> None:
    payload = response.json()
    history_item = response.history[0] if response.history else None
    actual_values = {
        "status_code": response.status_code,
        "url": response.url,
        "request_method": response.request.method,
        "request_url": response.request.url,
        "request_line": payload["request_line"],
        "body": payload["body"],
        "history_length": len(response.history),
        "history_status_code": None if history_item is None else history_item.status_code,
        "history_method": None if history_item is None else history_item.request.method,
    }
    expected_values = {
        "status_code": OK,
        "url": f"{base_url}/final",
        "request_method": QUERY,
        "request_url": f"{base_url}/final",
        "request_line": f"{QUERY} /final HTTP/1.1",
        "body": body,
        "history_length": 1,
        "history_status_code": status_code,
        "history_method": QUERY,
    }
    if actual_values != expected_values:
        raise AssertionError(actual_values)


def assert_cross_origin_query_is_sanitized(
    payload: dict[str, Any],
    *,
    host: str,
) -> None:
    actual_values = {
        "request_line": payload["request_line"],
        "body": payload["body"],
        "accept": header_values(payload, "accept"),
        "authorization": header_values(payload, "authorization"),
        "content_encoding": header_values(payload, "content-encoding"),
        "content_type": header_values(payload, "content-type"),
        "cookie": header_values(payload, "cookie"),
        "host": header_values(payload, "host"),
        "origin": header_values(payload, "origin"),
        "proxy_authorization": header_values(payload, "proxy-authorization"),
        "referer": header_values(payload, "referer"),
    }
    expected_values = {
        "request_line": f"{QUERY} {SECURITY_HEADERS_PATH} HTTP/1.1",
        "body": "",
        "accept": ["application/json"],
        "authorization": [],
        "content_encoding": [],
        "content_type": [],
        "cookie": [],
        "host": [host],
        "origin": [],
        "proxy_authorization": [],
        "referer": [],
    }
    if actual_values != expected_values:
        raise AssertionError(actual_values)
