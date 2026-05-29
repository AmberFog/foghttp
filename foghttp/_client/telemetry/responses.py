__all__ = (
    "emit_buffered_response_telemetry",
    "emit_stream_response_headers_telemetry",
)

from typing import Protocol

from ...telemetry import TelemetryRequestOutcome
from .clock import elapsed_seconds_to_ns
from .emission import TelemetryCompletion, TelemetryRedirect, TelemetryResponseMetadata
from .request_context import TelemetryRequestContext
from .url import redacted_url, url_origin


class ResponseTelemetryItem(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def elapsed(self) -> float: ...

    @property
    def url(self) -> str: ...


class ResponseTelemetrySource(ResponseTelemetryItem, Protocol):
    @property
    def history(self) -> tuple[ResponseTelemetryItem, ...]: ...


def emit_buffered_response_telemetry(
    telemetry_context: TelemetryRequestContext | None,
    response: ResponseTelemetrySource,
) -> None:
    if telemetry_context is None:
        return

    metadata = _response_metadata(response)
    _emit_redirect_telemetry(telemetry_context, response.history)
    telemetry_context.response_headers_received(metadata)
    telemetry_context.response_body_finished(_success_completion(metadata))
    telemetry_context.request_finished(_success_completion(metadata))


def emit_stream_response_headers_telemetry(
    telemetry_context: TelemetryRequestContext | None,
    response: ResponseTelemetrySource,
) -> None:
    if telemetry_context is None:
        return

    _emit_redirect_telemetry(telemetry_context, response.history)
    telemetry_context.response_headers_received(_response_metadata(response))


def _emit_redirect_telemetry(
    telemetry_context: TelemetryRequestContext,
    history: tuple[ResponseTelemetryItem, ...],
) -> None:
    for redirect_hop, redirect_response in enumerate(history, start=1):
        telemetry_context.redirect_decision(
            TelemetryRedirect(
                response=_response_metadata(redirect_response),
                redirect_hop=redirect_hop,
            ),
        )


def _response_metadata(response: ResponseTelemetryItem) -> TelemetryResponseMetadata:
    return TelemetryResponseMetadata(
        status_code=response.status_code,
        elapsed_ns=elapsed_seconds_to_ns(response.elapsed),
        origin=url_origin(response.url),
        redacted_url=redacted_url(response.url),
    )


def _success_completion(response: TelemetryResponseMetadata) -> TelemetryCompletion:
    return TelemetryCompletion(
        response=response,
        outcome=TelemetryRequestOutcome.SUCCESS,
    )
