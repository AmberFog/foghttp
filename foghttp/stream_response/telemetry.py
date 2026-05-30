__all__ = ("StreamResponseTelemetryMixin",)

from foghttp._client.telemetry import TelemetryRequestContext
from foghttp._client.telemetry.emission import TelemetryCompletion, TelemetryResponseMetadata
from foghttp._client.telemetry.url import (
    redacted_url as telemetry_redacted_url,
    url_origin,
)
from foghttp.telemetry import TelemetryRequestOutcome


class StreamResponseTelemetryMixin:
    status_code: int
    url: str
    _telemetry_context: TelemetryRequestContext | None
    _telemetry_finished: bool

    def _finish_telemetry(
        self,
        *,
        outcome: TelemetryRequestOutcome,
        error: BaseException | None = None,
        suppress_hook_errors: bool = False,
    ) -> None:
        if self._telemetry_context is None or self._telemetry_finished:
            return

        self._telemetry_finished = True
        completion = TelemetryCompletion(
            response=self._telemetry_completion_metadata(),
            outcome=outcome,
            error=error,
            suppress_hook_errors=suppress_hook_errors,
        )
        self._telemetry_context.response_body_finished(completion)
        self._telemetry_context.request_finished(completion)

    def _telemetry_completion_metadata(self) -> TelemetryResponseMetadata:
        return TelemetryResponseMetadata(
            status_code=self.status_code,
            elapsed_ns=None,
            origin=url_origin(self.url),
            redacted_url=telemetry_redacted_url(self.url),
        )
