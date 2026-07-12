__all__ = ("non_replayable_request",)

from foghttp._request_body import RequestBody
from foghttp.headers import HeaderSource
from foghttp.request import Request
from foghttp.request_extensions import RequestExtensionsSource


def non_replayable_request(
    method: str,
    url: str,
    *,
    content: bytes,
    headers: HeaderSource = None,
    extensions: RequestExtensionsSource = None,
) -> Request:
    return Request._from_body(  # noqa: SLF001
        method,
        url,
        headers=headers,
        body=RequestBody.non_replayable_body(content),
        extensions=extensions,
    )
