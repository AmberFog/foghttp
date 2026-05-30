__all__ = ("bind_stream_lifecycle_debug", "bind_stream_telemetry")

from collections.abc import Callable

from foghttp._client.telemetry import TelemetryRequestContext

from .base import StreamResponseBase


def bind_stream_telemetry(
    response: StreamResponseBase,
    telemetry_context: TelemetryRequestContext,
) -> None:
    object.__setattr__(response, "_telemetry_context", telemetry_context)


def bind_stream_lifecycle_debug(
    response: StreamResponseBase,
    finish_lifecycle_debug: Callable[[], None],
) -> None:
    object.__setattr__(response, "_lifecycle_debug_finish", finish_lifecycle_debug)
