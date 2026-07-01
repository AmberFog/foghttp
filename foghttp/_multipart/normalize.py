from collections.abc import MutableMapping

from .._request_body import RequestBody
from ..messages import (
    MULTIPART_CONTENT_TYPE_BOUNDARY_UNSUPPORTED,
    MULTIPART_CONTENT_TYPE_UNSUPPORTED,
)
from ..types import RequestData
from .constants import BOUNDARY_PARAMETER, CONTENT_TYPE, MULTIPART_FORM_DATA
from .encoding import generate_boundary
from .length import multipart_content_length
from .parts import multipart_payload
from .stream import (
    AsyncMultipartStream,
    MultipartStream,
    MultipartStreamFactory,
    multipart_buffer,
)
from .values import header_value


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
        headers[CONTENT_TYPE] = _content_type_with_boundary(MULTIPART_FORM_DATA, (), boundary)
        return
    headers[CONTENT_TYPE] = _explicit_content_type_with_boundary(content_type, boundary)


def _explicit_content_type_with_boundary(content_type: str, boundary: str) -> str:
    media_type, parameters = _content_type_parts(content_type)
    if not media_type.lower().startswith("multipart/"):
        raise ValueError(MULTIPART_CONTENT_TYPE_UNSUPPORTED)
    if any(_parameter_name(parameter) == BOUNDARY_PARAMETER for parameter in parameters):
        raise ValueError(MULTIPART_CONTENT_TYPE_BOUNDARY_UNSUPPORTED)
    return _content_type_with_boundary(media_type, parameters, boundary)


def _content_type_parts(content_type: str) -> tuple[str, tuple[str, ...]]:
    header_value(content_type)
    parts = tuple(part.strip() for part in content_type.split(";") if part.strip())
    if not parts:
        raise ValueError(MULTIPART_CONTENT_TYPE_UNSUPPORTED)
    return parts[0], parts[1:]


def _content_type_with_boundary(
    media_type: str,
    parameters: tuple[str, ...],
    boundary: str,
) -> str:
    return "; ".join((media_type, *parameters, f"{BOUNDARY_PARAMETER}={boundary}"))


def _parameter_name(parameter: str) -> str:
    return parameter.partition("=")[0].strip().lower()
