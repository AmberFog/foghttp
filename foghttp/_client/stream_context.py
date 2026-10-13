__all__ = ("AsyncStreamContext", "StreamContext", "validate_decode_content")

from collections.abc import Awaitable, Callable
from types import TracebackType

from ..errors import LifecycleError
from ..messages import STREAM_CONTEXT_REENTERED
from ..stream_response import AsyncStreamResponse, StreamResponse


def validate_decode_content(decode_content: object) -> None:
    if decode_content is not True and decode_content is not False:
        msg = "decode_content must be a bool"
        raise TypeError(msg)


class StreamContext:
    def __init__(self, response_factory: Callable[[], StreamResponse]) -> None:
        self._response_factory = response_factory
        self._response: StreamResponse | None = None
        self._entered = False

    def __enter__(self) -> StreamResponse:
        if self._entered:
            raise LifecycleError(STREAM_CONTEXT_REENTERED)
        self._entered = True
        response = self._response_factory()
        self._response = response
        return response

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._response is not None:
            self._response.__exit__(exc_type, exc, traceback)


class AsyncStreamContext:
    def __init__(self, response_factory: Callable[[], Awaitable[AsyncStreamResponse]]) -> None:
        self._response_factory = response_factory
        self._response: AsyncStreamResponse | None = None
        self._entered = False

    async def __aenter__(self) -> AsyncStreamResponse:
        if self._entered:
            raise LifecycleError(STREAM_CONTEXT_REENTERED)
        self._entered = True
        response = await self._response_factory()
        self._response = response
        return response

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._response is not None:
            await self._response.__aexit__(exc_type, exc, traceback)
