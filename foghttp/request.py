__all__ = ("Request",)

from ._redaction import redact_url
from ._request_body import RequestBody
from .headers import Headers, HeaderSource
from .url import URL


class Request:
    headers: Headers
    method: str
    url: str

    __slots__ = ("_body", "headers", "method", "url")

    def __init__(
        self,
        method: str,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        content: bytes | None = None,
    ) -> None:
        self.method = method.upper()
        self.url = str(URL(url))
        self.headers = Headers(headers)
        self._body = RequestBody.replayable_body(content)

    @classmethod
    def _from_body(
        cls,
        method: str,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        body: RequestBody,
    ) -> "Request":
        request = cls(method, url, headers=headers)
        request._body = body
        return request

    @property
    def content(self) -> bytes | None:
        return self._body.content

    @content.setter
    def content(self, value: bytes | None) -> None:
        self._body = RequestBody.replayable_body(value)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.method!r}, {redact_url(self.url)!r})"
