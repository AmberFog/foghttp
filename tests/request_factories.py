__all__ = ("non_replayable_request",)

from foghttp._request_body import RequestBody
from foghttp.headers import HeaderSource
from foghttp.request import Request


def non_replayable_request(
    method: str,
    url: str,
    *,
    content: bytes,
    headers: HeaderSource = None,
) -> Request:
    return Request._from_body(  # noqa: SLF001
        method,
        url,
        headers=headers,
        body=RequestBody.non_replayable_body(content),
    )
