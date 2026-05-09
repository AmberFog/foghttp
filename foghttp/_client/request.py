__all__ = ("prepare_request",)

from collections.abc import Mapping
from typing import Any

from ..body import encode_body
from ..headers import HeaderPairs, Headers, HeaderSource
from ..url import URL, merge_params


def prepare_request(
    *,
    url: str | URL,
    headers: HeaderSource,
    params: Mapping[str, Any] | None,
    content: bytes | str | None,
    json: Any,
) -> tuple[str, HeaderPairs, bytes | None]:
    request_url = merge_params(url, params)
    request_headers = Headers(headers)
    body = encode_body(content=content, json=json, headers=request_headers)
    return request_url, request_headers.multi_items(), body
