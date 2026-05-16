__all__ = ("URL", "merge_params")

from urllib.parse import urlencode, urlsplit, urlunsplit

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from .types import QueryParams


def _raw_url(url: "str | URL") -> _foghttp.RawUrl:
    try:
        return _foghttp.RawUrl(str(url))
    except UnicodeEncodeError as exc:
        msg = "URL is not valid Unicode"
        raise ValueError(msg) from exc


class URL:
    __slots__ = ("_raw",)

    def __init__(self, url: "str | URL") -> None:
        self._raw = _raw_url(url)

    def __str__(self) -> str:
        return self._raw.value

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({str(self)!r})"

    @property
    def scheme(self) -> str:
        return self._raw.scheme

    @property
    def host(self) -> str:
        return self._raw.host

    @property
    def port(self) -> int:
        return self._raw.port

    @property
    def path(self) -> str:
        return self._raw.path

    @property
    def query(self) -> str:
        return self._raw.query

    @property
    def fragment(self) -> str:
        return self._raw.fragment

    @property
    def origin(self) -> str:
        return self._raw.origin

    def join(self, location: "str | URL") -> "URL":
        try:
            return URL(self._raw.join(str(location)).value)
        except UnicodeEncodeError as exc:
            msg = "URL is not valid Unicode"
            raise ValueError(msg) from exc

    def is_same_origin(self, other: "str | URL") -> bool:
        return self._raw.is_same_origin(_raw_url(other))

    def with_params(self, params: QueryParams) -> "URL":
        query = _query_string(params)
        if not query:
            return self

        parts = urlsplit(str(self))
        merged_query = f"{parts.query}&{query}" if parts.query else query
        return URL(urlunsplit((parts.scheme, parts.netloc, parts.path, merged_query, parts.fragment)))


def merge_params(url: str | URL, params: QueryParams) -> str:
    return str(URL(url).with_params(params))


def _query_string(params: QueryParams) -> str:
    if params is None:
        return ""
    if isinstance(params, str):
        return params.removeprefix("?")
    return urlencode(params, doseq=True)
