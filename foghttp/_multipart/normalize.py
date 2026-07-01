from collections.abc import MutableMapping

from .._request_body import RequestBody
from ..types import RequestData
from .constants import CONTENT_TYPE, MULTIPART_FORM_DATA
from .content_type import (
    content_type_with_boundary,
    explicit_content_type_with_boundary,
)
from .encoding import generate_boundary
from .length import multipart_content_length
from .parts import multipart_payload
from .stream import (
    AsyncMultipartStream,
    MultipartStream,
    MultipartStreamFactory,
    multipart_buffer,
)


def normalize_multipart_body(
    *,
    data: RequestData,
    files: object,
    headers: MutableMapping[str, str],
) -> RequestBody:
    boundary = generate_boundary()
    payload = multipart_payload(boundary=boundary, data=data, files=files)
    _set_content_type(headers, boundary)

    if not payload.has_streaming_files:
        return RequestBody.replayable_body(multipart_buffer(payload))
    if payload.replayable:
        return RequestBody.replayable_streaming_body(
            MultipartStreamFactory(payload),
            content_length=multipart_content_length(payload),
        )
    if payload.async_source:
        return RequestBody.streaming_body(
            AsyncMultipartStream(payload),
            content_length=multipart_content_length(payload),
        )
    return RequestBody.streaming_body(
        MultipartStream(payload),
        content_length=multipart_content_length(payload),
    )


def _set_content_type(headers: MutableMapping[str, str], boundary: str) -> None:
    content_type = headers.get(CONTENT_TYPE)
    if content_type is None:
        headers[CONTENT_TYPE] = content_type_with_boundary(MULTIPART_FORM_DATA, (), boundary)
        return
    headers[CONTENT_TYPE] = explicit_content_type_with_boundary(content_type, boundary)
