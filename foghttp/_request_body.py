__all__ = ("RequestBody", "request_body")

from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from .request import Request


@dataclass(frozen=True, slots=True)
class RequestBody:
    content: bytes | None
    replayable: bool

    def __post_init__(self) -> None:
        if not self.content and not self.replayable:
            object.__setattr__(self, "replayable", True)

    @classmethod
    def replayable_body(cls, content: bytes | None) -> "RequestBody":
        return cls(content=content, replayable=True)

    @classmethod
    def non_replayable_body(cls, content: bytes) -> "RequestBody":
        return cls(content=content, replayable=False)


def request_body(request: "Request") -> RequestBody:
    return request._body  # noqa: SLF001
