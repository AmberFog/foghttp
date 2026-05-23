__all__ = ("AsyncStreamContext",)

from collections.abc import Awaitable
from types import TracebackType

from ..stream_response import AsyncStreamResponse


class AsyncStreamContext:
    def __init__(self, response: Awaitable[AsyncStreamResponse]) -> None:
        self._response_awaitable = response
        self._response: AsyncStreamResponse | None = None

    async def __aenter__(self) -> AsyncStreamResponse:
        response = await self._response_awaitable
        self._response = response
        return response

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._response is not None:
            self._response.close()
