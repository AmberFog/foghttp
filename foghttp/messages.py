BODY_CONTENT_AND_JSON_CONFLICT = "pass either content or json, not both"
CLIENT_CLOSED = "AsyncClient is closed"
COOKIES_UNSUPPORTED = "cookies are planned after the MVP"
HTTP_VERSION_UNSUPPORTED = "only HTTP/1.1 is supported in the MVP"
POOL_ACQUIRE_QUEUE_FULL = "connection acquire queue is full"
POOL_ACQUIRE_TIMEOUT = "connection acquire timeout expired"
REDIRECTS_UNSUPPORTED = "redirects are planned after the MVP"
TRUST_ENV_UNSUPPORTED = "trust_env/proxy support is planned after the MVP"
UNCLOSED_CLIENT = "AsyncClient was not closed"


def http_status_error(status_code: int, url: str) -> str:
    return f"{status_code} error response for {url}"
