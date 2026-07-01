__all__ = ("RequestBuilder",)

from ..._request_body import RequestBody
from ...body import encode_body
from ...headers import Headers, HeaderSource
from ...request import Request
from ...types import QueryParams
from ...url import URL
from .header_policy import validate_safe_request_headers
from .merge import RequestMergeContract
from .models import RequestBuildOptions


class RequestBuilder:
    """Build prepared requests without touching transport state."""

    __slots__ = ("_merge_contract",)

    def __init__(self, *, merge_contract: RequestMergeContract | None = None) -> None:
        self._merge_contract = merge_contract or RequestMergeContract()

    def build(self, options: RequestBuildOptions) -> Request:
        request_url = self._build_url(options.url, options.params)
        request_headers = self._build_headers(options.headers)
        validate_safe_request_headers(request_headers)
        body = self._build_body(options, request_headers)
        return Request._from_body(  # noqa: SLF001
            options.method,
            request_url,
            headers=request_headers,
            body=body,
        )

    def _build_url(self, url: str | URL, params: QueryParams) -> str:
        return self._merge_contract.url(url, params)

    def _build_headers(self, headers: HeaderSource) -> Headers:
        return self._merge_contract.headers(headers)

    def _build_body(self, options: RequestBuildOptions, headers: Headers) -> RequestBody:
        return encode_body(
            content=options.content,
            data=options.data,
            files=options.files,
            json=options.json,
            headers=headers,
        )
