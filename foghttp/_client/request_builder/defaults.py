__all__ = ("DEFAULT_REQUEST_BUILD_DEFAULTS", "FrozenHeaderPairs", "RequestBuildDefaults")

from dataclasses import dataclass
from typing import TypeAlias

from ...headers import Headers, HeaderSource
from ...types import QueryParams
from ...url import URL, _query_string


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
        return cls(
            base_url=None if base_url is None else URL(base_url),
            headers=tuple(Headers(headers).multi_items()),
            params=query or None,
        )


DEFAULT_REQUEST_BUILD_DEFAULTS = RequestBuildDefaults()
