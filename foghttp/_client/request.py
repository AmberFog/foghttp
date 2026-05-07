__all__ = ("prepare_request",)

from collections.abc import Mapping
from typing import Any

from ..body import encode_body
from ..url import merge_params


def prepare_request(
    *,
    url: str,
    headers: Mapping[str, str] | None,
    params: Mapping[str, Any] | None,
    content: bytes | str | None,
    json: Any,
) -> tuple[str, dict[str, str], bytes | None]:
    request_url = merge_params(url, params)
    request_headers = dict(headers or {})
    body = encode_body(content=content, json=json, headers=request_headers)
    return request_url, request_headers, body
