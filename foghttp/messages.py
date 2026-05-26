__all__ = (
    "BASE_URL_QUERY_OR_FRAGMENT_UNSUPPORTED",
    "BODY_CONTENT_UNSUPPORTED",
    "BODY_DATA_UNSUPPORTED",
    "BODY_PARAMETER_CONFLICT",
    "CLIENT_CLOSED",
    "COOKIES_UNSUPPORTED",
    "HTTP_VERSION_UNSUPPORTED",
    "MAX_REDIRECTS_INVALID",
    "POOL_ACQUIRE_QUEUE_FULL",
    "POOL_ACQUIRE_TIMEOUT",
    "RUNTIME_WORKERS_ENV_INVALID",
    "RUNTIME_WORKERS_INVALID",
    "STREAM_CONTEXT_REENTERED",
    "STREAM_RESPONSE_BODY_CONSUMED",
    "STREAM_RESPONSE_CLOSED",
    "TRUST_ENV_UNSUPPORTED",
    "UNCLOSED_CLIENT",
    "http_status_error",
    "http_status_reason",
    "transport_managed_header_error",
)

from http import HTTPStatus

from ._redaction import redact_url


BASE_URL_QUERY_OR_FRAGMENT_UNSUPPORTED = "base_url must not include query or fragment"
BODY_CONTENT_UNSUPPORTED = "content must be bytes, str, or None"
BODY_DATA_UNSUPPORTED = "data must be a mapping, sequence of pairs, bytes, str, or None"
BODY_PARAMETER_CONFLICT = "pass only one body parameter: content, data, or json"
CLIENT_CLOSED = "FogHTTP client is closed"
COOKIES_UNSUPPORTED = "cookies are planned after the MVP"
HTTP_VERSION_UNSUPPORTED = "only HTTP/1.1 is supported in the MVP"
MAX_REDIRECTS_INVALID = "max_redirects must be greater than or equal to 0"
POOL_ACQUIRE_QUEUE_FULL = "request acquire queue is full"
POOL_ACQUIRE_TIMEOUT = "request acquire timeout expired"
RUNTIME_WORKERS_ENV_INVALID = "FOGHTTP_RUNTIME_WORKERS must be an integer between 1 and 32"
RUNTIME_WORKERS_INVALID = "runtime_workers must be an integer between 1 and 32"
STREAM_CONTEXT_REENTERED = "stream context cannot be entered more than once"
STREAM_RESPONSE_BODY_CONSUMED = "stream response body can be consumed only once"
STREAM_RESPONSE_CLOSED = "stream response is closed"
TRUST_ENV_UNSUPPORTED = "trust_env/proxy support is planned after the MVP"
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
