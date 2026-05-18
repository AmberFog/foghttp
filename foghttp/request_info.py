__all__ = ("RequestInfo",)

from dataclasses import dataclass

from ._redaction import redact_url
from .headers import Headers


@dataclass(frozen=True, slots=True)
class RequestInfo:
    method: str
    url: str
    headers: Headers

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(method={self.method!r}, url={redact_url(self.url)!r}, headers={self.headers!r})"
        )
