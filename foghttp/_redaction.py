__all__ = (
    "REDACTED_VALUE",
    "redact_header_value",
    "redact_url",
)

from urllib.parse import unquote_plus, urlsplit, urlunsplit


REDACTED_VALUE = "<redacted>"

SENSITIVE_HEADER_NAMES = frozenset(
    (
        "authorization",
        "cookie",
        "proxy_authorization",
        "set_cookie",
        "private_token",
        "sentry_auth",
        "x_access_token",
        "x_amz_security_token",
        "x_api_key",
        "x_auth_token",
        "x_csrf_token",
        "x_gitlab_token",
        "x_goog_api_key",
        "x_session_token",
    ),
)

SENSITIVE_HEADER_NAME_SUFFIXES = (
    "_access_token",
    "_api_key",
    "_auth_token",
    "_security_token",
    "_session_token",
)

SENSITIVE_QUERY_PARAM_NAMES = frozenset(
    (
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "bearer",
        "client_secret",
        "credential",
        "id_token",
        "key",
        "password",
        "passwd",
        "pwd",
        "refresh_token",
        "secret",
        "session",
        "session_id",
        "sessionid",
        "sig",
        "signature",
        "token",
    ),
)

SENSITIVE_QUERY_PARAM_NAME_SUFFIXES = (
    "_access_token",
    "_auth_token",
    "_credential",
    "_security_token",
    "_session_token",
    "_signature",
)


def redact_header_value(name: str, value: str) -> str:
    normalized_name = _normalized_secret_name(name)
    if normalized_name in SENSITIVE_HEADER_NAMES or normalized_name.endswith(SENSITIVE_HEADER_NAME_SUFFIXES):
        return REDACTED_VALUE
    return value


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    netloc = _redact_netloc(parts.netloc)
    query = _redact_query(parts.query)
    fragment = _redact_fragment(parts.fragment)
    return urlunsplit((parts.scheme, netloc, parts.path, query, fragment))


def _redact_netloc(netloc: str) -> str:
    if "@" not in netloc:
        return netloc
    _userinfo, host_port = netloc.rsplit("@", maxsplit=1)
    return f"{REDACTED_VALUE}@{host_port}"


def _redact_query(query: str) -> str:
    if not query:
        return query
    return "&".join(_redact_query_part(part) for part in query.split("&"))


def _redact_fragment(fragment: str) -> str:
    if not fragment:
        return fragment
    path, separator, query = fragment.partition("?")
    if separator:
        return f"{path}{separator}{_redact_query(query)}"
    return _redact_query(fragment)


def _redact_query_part(part: str) -> str:
    key, _separator, _value = part.partition("=")
    normalized_name = _normalized_secret_name(unquote_plus(key))
    if normalized_name not in SENSITIVE_QUERY_PARAM_NAMES and not normalized_name.endswith(
        SENSITIVE_QUERY_PARAM_NAME_SUFFIXES,
    ):
        return part
    return f"{key}={REDACTED_VALUE}"


def _normalized_secret_name(name: str) -> str:
    return name.lower().replace("-", "_")
