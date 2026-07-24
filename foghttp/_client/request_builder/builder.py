__all__ = ("RequestBuilder",)

from ..._auth_headers import AuthHeaderProvenance
from ...body import encode_body
from ...headers import Headers
from ...request import Request
from .header_policy import validate_safe_request_headers
from .merge import RequestMergeContract
from .models import RequestBuildOptions


class RequestBuilder:
    """Build prepared requests without touching transport state."""

    __slots__ = ("_merge_contract", "_track_auth_header_provenance")

    def __init__(
        self,
        *,
        merge_contract: RequestMergeContract | None = None,
        track_auth_header_provenance: bool = False,
    ) -> None:
        self._merge_contract = merge_contract or RequestMergeContract()
        self._track_auth_header_provenance = track_auth_header_provenance

    def build(self, options: RequestBuildOptions) -> Request:
        request_url = self._merge_contract.url(options.url, options.params)
        request_headers = Headers(options.headers)
        request_owned_names = (
            frozenset(name.lower() for name in request_headers) if self._track_auth_header_provenance else frozenset()
        )
        request_headers = self._merge_contract.headers(request_headers)
        validate_safe_request_headers(request_headers)
        request = Request(
            options.method,
            request_url,
            headers=request_headers,
            extensions=options.extensions,
        )
        body_checkpoint = (
            request.headers._mutation_checkpoint()  # noqa: SLF001
            if self._track_auth_header_provenance
            else None
        )
        request._body = encode_body(  # noqa: SLF001
            content=options.content,
            data=options.data,
            files=options.files,
            json=options.json,
            headers=request.headers,
        )
        if body_checkpoint is None:
            return request
        request._auth_header_provenance = AuthHeaderProvenance.capture(  # noqa: SLF001
            request.headers,
            body_checkpoint=body_checkpoint,
            request_owned_names=request_owned_names,
        )
        request._auth_header_provenance.track(request.headers)  # noqa: SLF001
        return request
