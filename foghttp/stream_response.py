__all__ = ("AsyncStreamResponse",)

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from types import TracebackType

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from ._client.raw import raise_public_raw_error
from ._redaction import redact_url
from ._response.status import (
    is_client_error_status,
    is_error_status,
    is_redirect_status,
    is_server_error_status,
    is_success_status,
)
from .errors import HTTPStatusError
from .headers import Headers
from .messages import http_status_error
from .request_info import RequestInfo
from .response import Response


@dataclass(slots=True)
class AsyncStreamResponse:
    status_code: int
    headers: Headers
    url: str
    request: RequestInfo
    http_version: str
    elapsed: float
    _raw: _foghttp.RawStreamResponse = field(repr=False)
    history: tuple[Response, ...] = ()
    _closed: bool = field(default=False, init=False, repr=False)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"status_code={self.status_code!r}, "
            f"headers={self.headers!r}, "
            f"url={redact_url(self.url)!r}, "
            f"request={self.request!r}, "
            f"http_version={self.http_version!r}, "
            f"elapsed={self.elapsed!r}, "
            f"history=<{len(self.history)} responses>)"
        )

    async def __aenter__(self) -> "AsyncStreamResponse":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    @property
    def is_success(self) -> bool:
        return is_success_status(self.status_code)

    @property
    def is_redirect(self) -> bool:
        return is_redirect_status(self.status_code)

    @property
    def is_client_error(self) -> bool:
        return is_client_error_status(self.status_code)

    @property
    def is_server_error(self) -> bool:
        return is_server_error_status(self.status_code)

    @property
    def is_error(self) -> bool:
        return is_error_status(self.status_code)

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        if self._closed:
            return
        try:
            while True:
                chunk = await self._next_chunk()
                if chunk is None:
                    self._closed = True
                    return
                yield chunk
        finally:
            if not self._closed:
                await self.aclose()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._raw.close()

    def raise_for_status(self) -> None:
        if self.is_error:
            raise HTTPStatusError(
                http_status_error(
                    self.request.method,
                    self.request.url,
                    self.status_code,
                ),
                response=self,
            )

    async def _next_chunk(self) -> bytes | None:
        try:
            return await self._raw.next_chunk_async()
        except _foghttp.FogHttpError as exc:
            self._closed = True
            self._raw.close()
            raise_public_raw_error(exc)
