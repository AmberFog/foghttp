__all__ = ("RequestMergeContract",)

from dataclasses import dataclass

from ...headers import HeaderPairs, Headers, HeaderSource
from ...types import QueryParams
from ...url import URL
from .defaults import DEFAULT_REQUEST_BUILD_DEFAULTS, RequestBuildDefaults


@dataclass(frozen=True, slots=True)
class RequestMergeContract:
    """Apply the client defaults merge contract for prepared requests.

    URL order is base URL resolution, request URL query, client params, then
    per-request params. Header order is client defaults, reserved future
    auth-managed headers, then per-request headers.
    """

    defaults: RequestBuildDefaults = DEFAULT_REQUEST_BUILD_DEFAULTS

    def url(self, url: str | URL, params: QueryParams) -> str:
        request_url = self._request_url(url)
        if self.defaults.params is not None:
            request_url = request_url.with_params(self.defaults.params)
        return str(request_url.with_params(params))

    def headers(self, headers: HeaderSource) -> Headers:
        request_headers = Headers(headers)
        merged = Headers(
            self._default_headers_without_overrides(
                override_names=self._header_names(request_headers),
            ),
        )
        self._add_request_headers(merged, request_headers)
        return merged

    def _header_names(self, headers: Headers) -> set[str]:
        return {name.lower() for name, _value in headers.multi_items()}

    def _default_headers_without_overrides(
        self,
        *,
        override_names: set[str],
    ) -> HeaderPairs:
        items = []
        for name, value in Headers(self.defaults.headers).multi_items():
            if name.lower() not in override_names:
                items.append((name, value))
        return items

    def _add_request_headers(self, target: Headers, source: Headers) -> None:
        for name, value in source.multi_items():
            target.add(name, value)

    def _request_url(self, url: str | URL) -> URL:
        if self.defaults.base_url is None:
            return URL(url)
        return self.defaults.base_url.join(url)
