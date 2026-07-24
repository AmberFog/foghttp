__all__ = ("Auth", "AuthHook", "AuthRequest")

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeAlias

from ._redaction import redact_url
from .headers import HeaderSource
from .request_extensions import (
    RequestExtensions,
    empty_request_extensions,
    normalize_request_extensions,
)


AuthHook: TypeAlias = Callable[["AuthRequest"], HeaderSource]
Auth: TypeAlias = tuple[str, str] | AuthHook | None


@dataclass(frozen=True, repr=False, slots=True)
class AuthRequest:
    """Immutable request snapshot passed to an enabled auth hook."""

    method: str
    url: str
    headers: tuple[tuple[str, str], ...]
    redirect_hop: int
    extensions: RequestExtensions = field(default_factory=empty_request_extensions, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", tuple(self.headers))
        object.__setattr__(self, "extensions", normalize_request_extensions(self.extensions))

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        redacted_url = redact_url(self.url)
        header_count = len(self.headers)
        extension_count = len(self.extensions)
        return (
            f"{class_name}(method={self.method!r}, url={redacted_url!r}, "
            f"headers=<{header_count} headers>, redirect_hop={self.redirect_hop!r}, "
            f"extensions=<{extension_count} items>)"
        )
