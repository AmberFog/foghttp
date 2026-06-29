__all__ = ("RequestBody", "request_body")

from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from .request import Request


@dataclass(frozen=True, slots=True)
class RequestBody:
    content: bytes | None
    stream: object | None
    content_length: int | None
    replayable: bool

    def __post_init__(self) -> None:
        if self.content is not None and self.stream is not None:
            msg = "request body cannot be both buffered and streaming"
            raise ValueError(msg)
        if not self.content and self.stream is None and not self.replayable:
            object.__setattr__(self, "replayable", True)

    @classmethod
    def replayable_body(cls, content: bytes | None) -> "RequestBody":
        return cls(content=content, stream=None, content_length=None, replayable=True)

    @classmethod
    def non_replayable_body(cls, content: bytes) -> "RequestBody":
        return cls(content=content, stream=None, content_length=None, replayable=False)

    @classmethod
    def streaming_body(
        cls,
        stream: object,
        *,
        content_length: int | None = None,
    ) -> "RequestBody":
        return cls(content=None, stream=stream, content_length=content_length, replayable=False)

    @classmethod
    def replayable_streaming_body(
        cls,
        stream_factory: object,
        *,
        content_length: int | None = None,
    ) -> "RequestBody":
        return cls(
            content=None,
            stream=stream_factory,
            content_length=content_length,
            replayable=True,
        )


def request_body(request: "Request") -> RequestBody:
    return request._body  # noqa: SLF001
