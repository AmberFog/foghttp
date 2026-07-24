__all__ = ("raw_request_options",)

from .._request_body import request_body
from ..request import Request
from ..timeouts import Timeouts
from .proxy import ProxyResolver
from .raw import requests as raw_requests


def raw_request_options(
    request: Request,
    timeouts: Timeouts,
    proxy_resolver: ProxyResolver,
) -> raw_requests.RawRequestOptions:
    body = request_body(request)
    provenance = request._auth_header_provenance  # noqa: SLF001
    auth_headers = None if provenance is None else provenance.overrides(request.headers)
    auth_override_headers, auth_removed_headers = (None, ()) if auth_headers is None else auth_headers
    return raw_requests.RawRequestOptions(
        method=request.method,
        url=request.url,
        headers=request.headers.multi_items(),
        auth_override_headers=auth_override_headers,
        auth_removed_headers=auth_removed_headers,
        body=body,
        use_proxy_transport=proxy_resolver.resolve(request.url).uses_proxy,
        proxy_policy=proxy_resolver.transport_policy(),
        timeouts=timeouts,
        extensions=request.extensions or None,
    )
