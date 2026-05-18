__all__ = ("BodyParameter", "encode_body")

from collections.abc import MutableMapping
from enum import StrEnum
from typing import Any

import orjson

from .messages import BODY_CONTENT_AND_JSON_CONFLICT, BODY_CONTENT_UNSUPPORTED


class BodyParameter(StrEnum):
    CONTENT = "content"
    JSON = "json"


def encode_body(
    *,
    content: bytes | str | None,
    json: Any,
    headers: MutableMapping[str, str],
) -> bytes | None:
    source = _body_parameter(content=content, json=json)
    match source:
        case None:
            return None
        case BodyParameter.CONTENT:
            return _encode_content_body(content)
        case BodyParameter.JSON:
            return _encode_json_body(json, headers)


def _body_parameter(*, content: object, json: object) -> BodyParameter | None:
    sources = []
    if content is not None:
        sources.append(BodyParameter.CONTENT)
    if json is not None:
        sources.append(BodyParameter.JSON)
    if len(sources) > 1:
        raise ValueError(BODY_CONTENT_AND_JSON_CONFLICT)
    if sources:
        return sources[0]
    return None


def _encode_content_body(content: bytes | str | None) -> bytes:
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    raise TypeError(BODY_CONTENT_UNSUPPORTED)


def _encode_json_body(json: Any, headers: MutableMapping[str, str]) -> bytes:
    headers.setdefault("content-type", "application/json")
    return orjson.dumps(json)
