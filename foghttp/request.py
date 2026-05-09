__all__ = ("Request",)

from .headers import Headers, HeaderSource
from .url import URL


class Request:
    content: bytes | None
    headers: Headers
    method: str
    url: str

    __slots__ = ("content", "headers", "method", "url")

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
        self.content = content

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.method!r}, {self.url!r})"
