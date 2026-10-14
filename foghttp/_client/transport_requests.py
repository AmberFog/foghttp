__all__ = ("raw_request_options",)

from .._request_body import request_body
from ..request import Request
from ..timeouts import Timeouts
from .proxy import ProxyResolver
from .raw import requests as raw_requests


_ACCEPT_ENCODING = "Accept-Encoding"
_SUPPORTED_ENCODINGS = "gzip, deflate, br"


def raw_request_options(
    request: Request,
    timeouts: Timeouts,
    proxy_resolver: ProxyResolver,
    *,
    auto_accept_encoding: bool = False,
) -> raw_requests.RawRequestOptions:
    provenance = request._auth_header_provenance  # noqa: SLF001
    auth_headers = None if provenance is None else provenance.overrides(request.headers)
    auth_override_headers, auth_removed_headers = (None, ()) if auth_headers is None else auth_headers
    headers = request.headers.multi_items()
    if (
        auto_accept_encoding
        and _ACCEPT_ENCODING not in request.headers
        and _ACCEPT_ENCODING.lower() not in auth_removed_headers
    ):
        # Only original request headers are caller-owned; auth may replace the default.
        if auth_override_headers is None:
            auth_override_headers = tuple(name.lower() for name in request.headers)
        headers.append((_ACCEPT_ENCODING, _SUPPORTED_ENCODINGS))
    return raw_requests.RawRequestOptions(
        method=request.method,
        url=request.url,
        headers=headers,
        auth_override_headers=auth_override_headers,
        auth_removed_headers=auth_removed_headers,
        body=request_body(request),
        use_proxy_transport=proxy_resolver.resolve(request.url).uses_proxy,
        proxy_policy=proxy_resolver.transport_policy(),
        timeouts=timeouts,
        extensions=request.extensions or None,
    )
