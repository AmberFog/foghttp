from typing import assert_type

from opentelemetry.trace import TracerProvider

import foghttp
from foghttp.opentelemetry import OpenTelemetryTracing


def explicit_provider_clients(provider: TracerProvider) -> tuple[foghttp.Client, foghttp.AsyncClient]:
    tracing = OpenTelemetryTracing(tracer_provider=provider)
    assert_type(tracing, OpenTelemetryTracing)
    client = foghttp.Client(tracing=tracing, telemetry=foghttp.TelemetryConfig())
    async_client = foghttp.AsyncClient(tracing=tracing)
    assert_type(client, foghttp.Client)
    assert_type(async_client, foghttp.AsyncClient)
    return client, async_client


def optional_provider_clients(provider: TracerProvider | None) -> tuple[foghttp.Client, foghttp.AsyncClient]:
    tracing = OpenTelemetryTracing(tracer_provider=provider)
    assert_type(OpenTelemetryTracing(), OpenTelemetryTracing)
    return foghttp.Client(tracing=tracing), foghttp.AsyncClient(tracing=tracing)


def disabled_clients() -> tuple[foghttp.Client, foghttp.AsyncClient]:
    return foghttp.Client(tracing=None), foghttp.AsyncClient(tracing=None)
