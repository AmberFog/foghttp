__all__ = ("bind_stream_lifecycle_debug", "bind_stream_telemetry")

from collections.abc import Callable
import time

from foghttp._client.telemetry import NativeTelemetryDrain, TelemetryRequestContext

from .base import StreamResponseBase


def bind_stream_telemetry(
    response: StreamResponseBase,
    telemetry_context: TelemetryRequestContext,
    finish_native_telemetry: NativeTelemetryDrain | None,
) -> None:
    object.__setattr__(response, "_telemetry_body_started_at_ns", time.perf_counter_ns())
    object.__setattr__(response, "_native_telemetry_finish", finish_native_telemetry)
    object.__setattr__(response, "_telemetry_context", telemetry_context)


def bind_stream_lifecycle_debug(
    response: StreamResponseBase,
    finish_lifecycle_debug: Callable[[], None],
) -> None:
    object.__setattr__(response, "_lifecycle_debug_finish", finish_lifecycle_debug)
