__all__ = ("RequestBuilder",)

from ...body import encode_body
from ...headers import Headers, HeaderSource
from ...request import Request
from ...types import QueryParams
from ...url import URL, merge_params
from .header_policy import validate_safe_request_headers
from .models import RequestBuildOptions


class RequestBuilder:
    """Build prepared requests without touching transport state."""

    __slots__ = ()

    def build(self, options: RequestBuildOptions) -> Request:
        request_url = self._build_url(options.url, options.params)
        request_headers = self._build_headers(options.headers)
        validate_safe_request_headers(request_headers)
        body = self._build_body(options, request_headers)
        return Request(
            options.method,
            request_url,
            headers=request_headers,
            content=body,
        )

    def _build_url(self, url: str | URL, params: QueryParams) -> str:
        return merge_params(url, params)

    def _build_headers(self, headers: HeaderSource) -> Headers:
        return Headers(headers)

    def _build_body(self, options: RequestBuildOptions, headers: Headers) -> bytes | None:
        return encode_body(
            content=options.content,
            json=options.json,
            headers=headers,
        )
