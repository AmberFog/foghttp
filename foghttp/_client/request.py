__all__ = ("prepare_request",)

from typing import Any

from ..body import encode_body
from ..headers import Headers, HeaderSource
from ..request import Request
from ..types import QueryParams
from ..url import URL, merge_params


def prepare_request(
    *,
    method: str,
    url: str | URL,
    headers: HeaderSource,
    params: QueryParams,
    content: bytes | str | None,
    json: Any,
) -> Request:
    request_url = merge_params(url, params)
    request_headers = Headers(headers)
    body = encode_body(content=content, json=json, headers=request_headers)
    return Request(method, request_url, headers=request_headers, content=body)
