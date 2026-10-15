from collections.abc import Callable
from contextlib import nullcontext, suppress
from typing import TYPE_CHECKING

from ..status_codes.client_error import MIN_CLIENT_ERROR_STATUS_CODE
from ..status_codes.server_error import MAX_SERVER_ERROR_STATUS_CODE
from .attributes import error_type


if TYPE_CHECKING:
    from opentelemetry.trace import Span


class RequestSpan:
    """Own one terminal attempt, without retaining the request or its context."""

    __slots__ = ("_report_failure", "_span")

    def __init__(self, span: "Span", report_failure: Callable[[], None]) -> None:
        self._span: Span | None = span
        self._report_failure = report_failure

    def finish(self, *, status_code: int | None = None, error: BaseException | None = None) -> None:
        span = self._span
        self._span = None
        if span is None:
            return
        try:
            self._finish(span, status_code=status_code, error=error)
        except BaseException:
            if error is None:
                raise

    def _finish(self, span: "Span", *, status_code: int | None, error: BaseException | None) -> None:
        interrupted = True
        try:
            _record_outcome(span, status_code=status_code, error=error)
            interrupted = False
        except Exception:  # noqa: BLE001 - isolate SDK failure, but always attempt end
            self._report_failure()
            interrupted = False
        finally:
            self._end(span, suppress_interruptions=error is not None or interrupted)

    def _end(self, span: "Span", *, suppress_interruptions: bool) -> None:
        with suppress(BaseException) if suppress_interruptions else nullcontext():
            try:
                span.end()
            except Exception:  # noqa: BLE001 - an SDK failure cannot replace the HTTP outcome
                self._report_failure()


def _record_outcome(span: "Span", *, status_code: int | None, error: BaseException | None) -> None:
    from opentelemetry.trace import StatusCode  # noqa: PLC0415

    if not span.is_recording():
        return
    classified_error = None
    if status_code is not None:
        span.set_attribute("http.response.status_code", status_code)
        if MIN_CLIENT_ERROR_STATUS_CODE <= status_code <= MAX_SERVER_ERROR_STATUS_CODE:
            classified_error = str(status_code)
    elif isinstance(error, Exception):
        classified_error = error_type(error)
    if classified_error is not None:
        span.set_attribute("error.type", classified_error)
        span.set_status(StatusCode.ERROR)
