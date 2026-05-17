__all__ = ("DEFAULT_REQUEST_BUILD_DEFAULTS", "FrozenHeaderPairs", "RequestBuildDefaults")

from dataclasses import dataclass
from typing import TypeAlias
from urllib.parse import urlsplit, urlunsplit

from ...headers import Headers, HeaderSource
from ...messages import BASE_URL_QUERY_OR_FRAGMENT_UNSUPPORTED
from ...types import QueryParams
from ...url import URL, _query_string
from .header_policy import validate_safe_request_headers


FrozenHeaderPairs: TypeAlias = tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class RequestBuildDefaults:
    """Immutable snapshot of client-level request builder defaults."""

    base_url: URL | None = None
    headers: FrozenHeaderPairs = ()
    params: str | None = None

    @classmethod
    def from_options(
        cls,
        *,
        base_url: str | URL | None = None,
        headers: HeaderSource = None,
        params: QueryParams = None,
    ) -> "RequestBuildDefaults":
        query = _query_string(params)
        default_headers = Headers(headers)
        validate_safe_request_headers(default_headers)
        return cls(
            base_url=_normalized_base_url(base_url),
            headers=tuple(default_headers.multi_items()),
            params=query or None,
        )


def _normalized_base_url(url: str | URL | None) -> URL | None:
    if url is None:
        return None

    parsed_url = URL(url)
    if parsed_url.query or parsed_url.fragment:
        raise ValueError(BASE_URL_QUERY_OR_FRAGMENT_UNSUPPORTED)

    parts = urlsplit(str(parsed_url))
    path = parts.path or "/"
    if not path.endswith("/"):
        path = f"{path}/"
    return URL(urlunsplit((parts.scheme, parts.netloc, path, "", "")))


DEFAULT_REQUEST_BUILD_DEFAULTS = RequestBuildDefaults()
