__all__ = (
    "BASE_URL_QUERY_OR_FRAGMENT_UNSUPPORTED",
    "BODY_CONTENT_UNSUPPORTED",
    "BODY_DATA_UNSUPPORTED",
    "BODY_PARAMETER_CONFLICT",
    "CLIENT_CLOSED",
    "COOKIES_UNSUPPORTED",
    "HTTP_VERSION_UNSUPPORTED",
    "MAX_REDIRECTS_INVALID",
    "MULTIPART_CONTENT_TYPE_BOUNDARY_UNSUPPORTED",
    "MULTIPART_CONTENT_TYPE_UNSUPPORTED",
    "MULTIPART_DATA_UNSUPPORTED",
    "MULTIPART_FILES_UNSUPPORTED",
    "MULTIPART_FILE_FACTORY_MIX_UNSUPPORTED",
    "MULTIPART_HEADER_VALUE_UNSUPPORTED",
    "POOL_ACQUIRE_QUEUE_FULL",
    "POOL_ACQUIRE_TIMEOUT",
    "RUNTIME_WORKERS_ENV_INVALID",
    "RUNTIME_WORKERS_INVALID",
    "STREAMING_BODY_CHUNK_UNSUPPORTED",
    "STREAM_CONTEXT_REENTERED",
    "STREAM_RESPONSE_BODY_CONSUMED",
    "STREAM_RESPONSE_CLOSED",
    "SYNC_CLIENT_ASYNC_BODY_UNSUPPORTED",
    "UNCLOSED_CLIENT",
    "http_status_error",
    "http_status_reason",
    "transport_managed_header_error",
)

from http import HTTPStatus

from ._redaction import redact_url


BASE_URL_QUERY_OR_FRAGMENT_UNSUPPORTED = "base_url must not include query or fragment"
BODY_CONTENT_UNSUPPORTED = (
    "content must be bytes, str, binary file-like, bytes-like iterable, async bytes-like iterable, or None"
)
BODY_DATA_UNSUPPORTED = "data must be a mapping, sequence of pairs, bytes, str, or None"
BODY_PARAMETER_CONFLICT = (
    "body source conflict: use content, data, json, or files; files may be combined with form fields"
)
CLIENT_CLOSED = "FogHTTP client is closed"
COOKIES_UNSUPPORTED = "cookies are planned after the MVP"
HTTP_VERSION_UNSUPPORTED = "only HTTP/1.1 is supported in the MVP"
MAX_REDIRECTS_INVALID = "max_redirects must be greater than or equal to 0"
MULTIPART_DATA_UNSUPPORTED = "files can only be combined with mapping or repeated-pair form data"
MULTIPART_FILE_FACTORY_MIX_UNSUPPORTED = (
    "multipart file factories cannot be mixed with non-replayable direct file or stream parts"
)
MULTIPART_FILES_UNSUPPORTED = (
    "files must be a mapping or sequence of pairs with bytes, binary file-like, byte streams, "
    "stream factories, or file tuples"
)
MULTIPART_CONTENT_TYPE_BOUNDARY_UNSUPPORTED = "multipart content-type boundary is managed by FogHTTP"
MULTIPART_CONTENT_TYPE_UNSUPPORTED = "files require a multipart content-type"
MULTIPART_HEADER_VALUE_UNSUPPORTED = "multipart field names, filenames, and content types must be safe strings"
POOL_ACQUIRE_QUEUE_FULL = "request acquire queue is full"
POOL_ACQUIRE_TIMEOUT = "request acquire timeout expired"
RUNTIME_WORKERS_ENV_INVALID = "FOGHTTP_RUNTIME_WORKERS must be an integer between 1 and 32"
RUNTIME_WORKERS_INVALID = "runtime_workers must be an integer between 1 and 32"
STREAM_CONTEXT_REENTERED = "stream context cannot be entered more than once"
STREAM_RESPONSE_BODY_CONSUMED = "stream response body can be consumed only once"
STREAM_RESPONSE_CLOSED = "stream response is closed"
STREAMING_BODY_CHUNK_UNSUPPORTED = "streaming request body chunks must be bytes-like"
SYNC_CLIENT_ASYNC_BODY_UNSUPPORTED = "sync Client cannot send async streaming request bodies"
UNCLOSED_CLIENT = "FogHTTP client was not closed"


def http_status_error(method: str, url: str, status_code: int) -> str:
    reason = http_status_reason(status_code)
    status = f"{status_code} {reason}" if reason else str(status_code)
    return f"{method} {redact_url(url)} returned {status}"


def http_status_reason(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return ""


def transport_managed_header_error(name: str) -> str:
    return f"request header {name!r} is managed by FogHTTP transport and cannot be set manually"
