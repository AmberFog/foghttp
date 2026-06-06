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
    proxy_decision = proxy_resolver.resolve(request.url)
    return raw_requests.RawRequestOptions(
        method=request.method,
        url=request.url,
        headers=request.headers.multi_items(),
        body=body.content,
        body_replayable=body.replayable,
        use_http_proxy=proxy_decision.uses_proxy,
        proxy_policy=proxy_resolver.transport_policy(),
        timeouts=timeouts,
    )
