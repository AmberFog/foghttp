__all__ = (
    "BASE_URL_QUERY_OR_FRAGMENT_UNSUPPORTED",
    "BODY_CONTENT_AND_JSON_CONFLICT",
    "CLIENT_CLOSED",
    "COOKIES_UNSUPPORTED",
    "HTTP_VERSION_UNSUPPORTED",
    "MAX_REDIRECTS_INVALID",
    "POOL_ACQUIRE_QUEUE_FULL",
    "POOL_ACQUIRE_TIMEOUT",
    "RUNTIME_WORKERS_ENV_INVALID",
    "RUNTIME_WORKERS_INVALID",
    "TRUST_ENV_UNSUPPORTED",
    "UNCLOSED_CLIENT",
    "http_status_error",
    "http_status_reason",
    "transport_managed_header_error",
)

from http import HTTPStatus


BASE_URL_QUERY_OR_FRAGMENT_UNSUPPORTED = "base_url must not include query or fragment"
BODY_CONTENT_AND_JSON_CONFLICT = "pass either content or json, not both"
CLIENT_CLOSED = "AsyncClient is closed"
COOKIES_UNSUPPORTED = "cookies are planned after the MVP"
HTTP_VERSION_UNSUPPORTED = "only HTTP/1.1 is supported in the MVP"
MAX_REDIRECTS_INVALID = "max_redirects must be greater than or equal to 0"
POOL_ACQUIRE_QUEUE_FULL = "request acquire queue is full"
POOL_ACQUIRE_TIMEOUT = "request acquire timeout expired"
RUNTIME_WORKERS_ENV_INVALID = "FOGHTTP_RUNTIME_WORKERS must be an integer between 1 and 32"
RUNTIME_WORKERS_INVALID = "runtime_workers must be an integer between 1 and 32"
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


def transport_managed_header_error(name: str) -> str:
    return f"request header {name!r} is managed by FogHTTP transport and cannot be set manually"
