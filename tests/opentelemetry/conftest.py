__all__ = (
    "decompression_server",
    "response_decompression_server",
    "retry_server",
    "sync_streaming_server",
    "tls_certificates",
    "tls_http_server",
    "tracing_setup",
    "wire_headers",
)

from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
import pytest

from foghttp.opentelemetry import OpenTelemetryTracing
from tests.client_retry import server as retry_server_module
from tests.client_retry.conftest import retry_server
from tests.client_streaming.conftest import sync_streaming_server
from tests.client_tls.conftest import tls_certificates, tls_http_server
from tests.response_decompression.conftest import response_decompression_server
from tests.streaming_decompression.conftest import decompression_server

from . import TracingSetup, WireHeaders


@pytest.fixture
def tracing_setup(monkeypatch: pytest.MonkeyPatch) -> Iterator[TracingSetup]:
    monkeypatch.delenv("OTEL_INSTRUMENTATION_HTTP_KNOWN_METHODS", raising=False)
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        yield OpenTelemetryTracing(tracer_provider=provider), exporter, provider
    finally:
        provider.shutdown()


@pytest.fixture
def wire_headers(monkeypatch: pytest.MonkeyPatch) -> WireHeaders:
    captured: WireHeaders = []
    parse_request = BaseHTTPRequestHandler.parse_request
    parse_headers = retry_server_module._parse_headers  # noqa: SLF001 - reuse the existing wire server

    def capture_request(handler: BaseHTTPRequestHandler) -> bool:
        parsed = parse_request(handler)
        if parsed:
            captured.append(tuple((name.lower(), value) for name, value in handler.headers.items()))
        return parsed

    def capture_retry_headers(lines: list[str]) -> dict[str, str]:
        headers = parse_headers(lines)
        captured.append(tuple(headers.items()))
        return headers

    monkeypatch.setattr(BaseHTTPRequestHandler, "parse_request", capture_request)
    monkeypatch.setattr(retry_server_module, "_parse_headers", capture_retry_headers)
    return captured
