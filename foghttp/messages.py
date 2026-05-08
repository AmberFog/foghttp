from http import HTTPStatus


__all__ = (
    "BODY_CONTENT_AND_JSON_CONFLICT",
    "CLIENT_CLOSED",
    "COOKIES_UNSUPPORTED",
    "HTTP_VERSION_UNSUPPORTED",
    "MAX_REDIRECTS_INVALID",
    "POOL_ACQUIRE_QUEUE_FULL",
    "POOL_ACQUIRE_TIMEOUT",
    "TRUST_ENV_UNSUPPORTED",
    "UNCLOSED_CLIENT",
    "http_status_error",
    "http_status_reason",
)


BODY_CONTENT_AND_JSON_CONFLICT = "pass either content or json, not both"
CLIENT_CLOSED = "AsyncClient is closed"
COOKIES_UNSUPPORTED = "cookies are planned after the MVP"
HTTP_VERSION_UNSUPPORTED = "only HTTP/1.1 is supported in the MVP"
MAX_REDIRECTS_INVALID = "max_redirects must be greater than or equal to 0"
POOL_ACQUIRE_QUEUE_FULL = "connection acquire queue is full"
POOL_ACQUIRE_TIMEOUT = "connection acquire timeout expired"
TRUST_ENV_UNSUPPORTED = "trust_env/proxy support is planned after the MVP"
UNCLOSED_CLIENT = "AsyncClient was not closed"


def http_status_error(method: str, url: str, status_code: int) -> str:
    reason = http_status_reason(status_code)
    status = f"{status_code} {reason}" if reason else str(status_code)
    return f"{method} {url} returned {status}"


def http_status_reason(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return ""
