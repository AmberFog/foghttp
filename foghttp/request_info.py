__all__ = ("RequestInfo",)

from dataclasses import dataclass, field

from ._redaction import redact_url
from .headers import Headers
from .request_extensions import (
    RequestExtensions,
    empty_request_extensions,
    normalize_request_extensions,
)


@dataclass(frozen=True, slots=True)
class RequestInfo:
    method: str
    url: str
    headers: Headers
    extensions: RequestExtensions = field(default_factory=empty_request_extensions, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extensions", normalize_request_extensions(self.extensions))

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(method={self.method!r}, url={redact_url(self.url)!r}, "
            f"headers={self.headers!r}, extensions=<{len(self.extensions)} items>)"
        )
