__all__ = ("BodyParameter", "encode_body")

from collections.abc import Mapping, MutableMapping, Sequence
from enum import StrEnum
from typing import Any, TypeAlias, cast
from urllib.parse import urlencode

import orjson

from ._request_body import RequestBody
from ._upload_body import SyncRequestContent, normalize_content_body
from .messages import BODY_DATA_UNSUPPORTED, BODY_PARAMETER_CONFLICT
from .types import RequestData


CONTENT_TYPE = "content-type"
FORM_URLENCODED_CONTENT_TYPE = "application/x-www-form-urlencoded"
JSON_CONTENT_TYPE = "application/json"
_UrlEncodeData: TypeAlias = Mapping[str, object] | Sequence[tuple[str, object]]


class BodyParameter(StrEnum):
    CONTENT = "content"
    DATA = "data"
    JSON = "json"


def encode_body(
    *,
    content: SyncRequestContent | object | None,
    data: RequestData,
    json: Any,
    headers: MutableMapping[str, str],
) -> RequestBody:
    source = _body_parameter(content=content, data=data, json=json)
    match source:
        case None:
            return RequestBody.replayable_body(None)
        case BodyParameter.CONTENT:
            return normalize_content_body(content)
        case BodyParameter.DATA:
            return RequestBody.replayable_body(_encode_data_body(data, headers))
        case BodyParameter.JSON:
            return RequestBody.replayable_body(_encode_json_body(json, headers))


def _body_parameter(*, content: object, data: object, json: object) -> BodyParameter | None:
    sources = []
    if content is not None:
        sources.append(BodyParameter.CONTENT)
    if data is not None:
        sources.append(BodyParameter.DATA)
    if json is not None:
        sources.append(BodyParameter.JSON)
    if len(sources) > 1:
        raise ValueError(BODY_PARAMETER_CONFLICT)
    if sources:
        return sources[0]
    return None


def _encode_data_body(data: RequestData, headers: MutableMapping[str, str]) -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode("utf-8")

    headers.setdefault(CONTENT_TYPE, FORM_URLENCODED_CONTENT_TYPE)
    try:
        return urlencode(cast("_UrlEncodeData", data), doseq=True).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TypeError(BODY_DATA_UNSUPPORTED) from exc


def _encode_json_body(json: Any, headers: MutableMapping[str, str]) -> bytes:
    headers.setdefault(CONTENT_TYPE, JSON_CONTENT_TYPE)
    return orjson.dumps(json)
