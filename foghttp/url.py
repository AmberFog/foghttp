__all__ = ("merge_params",)

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit


def merge_params(url: str, params: Mapping[str, Any] | None) -> str:
    if not params:
        return url
    parts = urlsplit(url)
    query = urlencode(params, doseq=True)
    merged_query = f"{parts.query}&{query}" if parts.query else query
    return urlunsplit((parts.scheme, parts.netloc, parts.path, merged_query, parts.fragment))
