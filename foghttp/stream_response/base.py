__all__ = ("StreamResponseBase",)

from collections.abc import Callable
from dataclasses import dataclass, field

from foghttp._client.telemetry import TelemetryRequestContext
import foghttp._foghttp as _foghttp  # noqa: PLR0402
from foghttp._redaction import redact_url
from foghttp._response.encoding import response_encoding
from foghttp.errors import LifecycleError
from foghttp.headers import Headers
from foghttp.messages import (
    STREAM_RESPONSE_BODY_CONSUMED,
    STREAM_RESPONSE_CLOSED,
)
from foghttp.request_info import RequestInfo
from foghttp.response import Response
from foghttp.telemetry import TelemetryRequestOutcome

from .lifecycle_debug import StreamResponseLifecycleDebugMixin
from .status import StreamResponseStatusMixin
from .telemetry import StreamResponseTelemetryMixin


@dataclass(slots=True)
class StreamResponseBase(
    StreamResponseLifecycleDebugMixin,
    StreamResponseStatusMixin,
    StreamResponseTelemetryMixin,
):
    status_code: int
    headers: Headers
    url: str
    request: RequestInfo
    http_version: str
    elapsed: float
    _raw: _foghttp.RawStreamResponse = field(repr=False)
    history: tuple[Response, ...] = ()
    _closed: bool = field(default=False, init=False, repr=False)
    _body_started: bool = field(default=False, init=False, repr=False)
    _telemetry_context: TelemetryRequestContext | None = field(default=None, init=False, repr=False)
    _telemetry_finished: bool = field(default=False, init=False, repr=False)
    _lifecycle_debug_finish: Callable[[], None] | None = field(default=None, init=False, repr=False)
    _lifecycle_debug_finished: bool = field(default=False, init=False, repr=False)

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

    @property
    def encoding(self) -> str:
        return response_encoding(self.headers, b"")

    def close(self) -> None:
        self._close(
            outcome=TelemetryRequestOutcome.CLOSED,
            suppress_telemetry_errors=False,
        )

    def _close(
        self,
        *,
        outcome: TelemetryRequestOutcome,
        error: BaseException | None = None,
        suppress_telemetry_errors: bool,
    ) -> None:
        if self._closed:
            return
        self._closed = True
        self._raw.close()
        self._finish_lifecycle_debug()
        self._finish_telemetry(
            outcome=outcome,
            error=error,
            suppress_hook_errors=suppress_telemetry_errors,
        )

    def _text_encoding(self, encoding: str | None) -> str:
        return self.encoding if encoding is None else encoding

    def _start_body_iteration(self) -> None:
        if self._body_started:
            raise LifecycleError(STREAM_RESPONSE_BODY_CONSUMED)
        if self._closed:
            raise LifecycleError(STREAM_RESPONSE_CLOSED)
        self._body_started = True
