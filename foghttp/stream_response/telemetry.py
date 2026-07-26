__all__ = ("StreamResponseTelemetryMixin",)

from collections.abc import Callable
import time

from foghttp._client.telemetry import NativeTelemetryDrain, TelemetryRequestContext
from foghttp._client.telemetry.emission import TelemetryCompletion, TelemetryResponseMetadata
from foghttp._client.telemetry.url import (
    redacted_url as telemetry_redacted_url,
    url_origin,
)
from foghttp.telemetry import TelemetryHookError, TelemetryRequestOutcome


class StreamResponseTelemetryMixin:
    status_code: int
    url: str
    _telemetry_context: TelemetryRequestContext | None
    _telemetry_body_started_at_ns: int | None
    _native_telemetry_finish: NativeTelemetryDrain | None
    _telemetry_finished: bool
    _finish_lifecycle_debug: Callable[[], None]

    def _finish_observability(
        self,
        *,
        outcome: TelemetryRequestOutcome,
        error: BaseException | None = None,
        suppress_hook_errors: bool,
    ) -> None:
        completed_at_ns = None
        if self._telemetry_context is not None:
            completed_at_ns = time.perf_counter_ns()
        self._finish_lifecycle_debug()
        self._finish_telemetry(
            outcome=outcome,
            error=error,
            suppress_hook_errors=suppress_hook_errors,
            completed_at_ns=completed_at_ns,
        )

    def _finish_telemetry(
        self,
        *,
        outcome: TelemetryRequestOutcome,
        error: BaseException | None = None,
        suppress_hook_errors: bool = False,
        completed_at_ns: int | None,
    ) -> None:
        if self._telemetry_context is None or self._telemetry_finished:
            return

        if completed_at_ns is None:
            msg = "stream telemetry is missing its completion timestamp"
            raise RuntimeError(msg)
        body_started_at_ns = self._telemetry_body_started_at_ns
        if body_started_at_ns is None:
            msg = "stream telemetry is missing its body start timestamp"
            raise RuntimeError(msg)
        self._telemetry_finished = True
        native_error: TelemetryHookError | None = None
        finish_native_telemetry = self._native_telemetry_finish
        self._native_telemetry_finish = None
        if finish_native_telemetry is not None:
            try:
                finish_native_telemetry(suppress_hook_errors=suppress_hook_errors)
            except TelemetryHookError as native_hook_error:
                native_error = native_hook_error
        completion = TelemetryCompletion(
            response=self._telemetry_completion_metadata(),
            outcome=outcome,
            error=error,
            suppress_hook_errors=suppress_hook_errors or native_error is not None,
            body_elapsed_ns=completed_at_ns - body_started_at_ns,
            request_elapsed_ns=completed_at_ns - self._telemetry_context.started_at_ns,
        )
        self._telemetry_context.response_body_finished(completion)
        self._telemetry_context.request_finished(completion)
        if native_error is not None:
            raise native_error

    def _telemetry_completion_metadata(self) -> TelemetryResponseMetadata:
        return TelemetryResponseMetadata(
            status_code=self.status_code,
            elapsed_ns=None,
            origin=url_origin(self.url),
            redacted_url=telemetry_redacted_url(self.url),
        )
