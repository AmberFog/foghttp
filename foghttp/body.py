__all__ = ("encode_body",)

from collections.abc import MutableMapping
from typing import Any

import orjson

from .messages import BODY_CONTENT_AND_JSON_CONFLICT


def encode_body(
    *,
    content: bytes | str | None,
    json: Any,
    headers: MutableMapping[str, str],
) -> bytes | None:
    if content is not None and json is not None:
        raise ValueError(BODY_CONTENT_AND_JSON_CONFLICT)
    if json is not None:
        headers.setdefault("content-type", "application/json")
        return orjson.dumps(json)
    if isinstance(content, str):
        return content.encode("utf-8")
    return content
