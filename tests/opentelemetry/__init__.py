__all__ = ("TracingSetup", "WireHeaders")

from typing import TYPE_CHECKING, TypeAlias


if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from foghttp.opentelemetry import OpenTelemetryTracing


TracingSetup: TypeAlias = tuple["OpenTelemetryTracing", "InMemorySpanExporter", "TracerProvider"]
WireHeaders: TypeAlias = list[tuple[tuple[str, str], ...]]
