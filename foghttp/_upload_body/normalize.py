from .._request_body import RequestBody
from ..messages import BODY_CONTENT_UNSUPPORTED
from .file_source import FileUploadSource, file_content_length
from .predicates import is_async_stream, is_binary_file, is_sync_stream


def normalize_content_body(content: object) -> RequestBody:
    buffered = _buffered_content_body(content)
    if buffered is not None:
        return buffered

    streaming = _streaming_content_body(content)
    if streaming is not None:
        return streaming

    raise TypeError(BODY_CONTENT_UNSUPPORTED)


def _buffered_content_body(content: object) -> RequestBody | None:
    if content is None:
        return RequestBody.replayable_body(None)
    if isinstance(content, bytes):
        return RequestBody.replayable_body(content)
    if isinstance(content, str):
        return RequestBody.replayable_body(content.encode("utf-8"))
    return None


def _streaming_content_body(content: object) -> RequestBody | None:
    if is_binary_file(content):
        return RequestBody.streaming_body(
            FileUploadSource(content),
            content_length=file_content_length(content),
        )
    if is_async_stream(content) or is_sync_stream(content):
        return RequestBody.streaming_body(content)
    if callable(content):
        return RequestBody.replayable_streaming_body(content)
    return None
