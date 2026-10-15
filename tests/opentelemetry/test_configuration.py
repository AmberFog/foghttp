from http import HTTPStatus
from importlib.metadata import version
from typing import Any

from opentelemetry import context, trace
import pytest

import foghttp
from foghttp._client.telemetry import dispatcher
from foghttp.opentelemetry import OpenTelemetryTracing

from . import TracingSetup


@pytest.mark.parametrize("client_type", [foghttp.Client, foghttp.AsyncClient])
@pytest.mark.parametrize("invalid", [False, True, "enabled", object()])
def test_wrong_tracing_type_fails_before_transport_creation(
    monkeypatch: pytest.MonkeyPatch,
    client_type: type[foghttp.Client] | type[foghttp.AsyncClient],
    invalid: Any,
) -> None:
    def unexpected_transport(_self: object) -> None:
        pytest.fail("invalid tracing reached transport construction")

    monkeypatch.setattr(client_type, "_create_transport", unexpected_transport)
    with pytest.raises(TypeError, match="tracing"):
        client_type(tracing=invalid, trust_env=False)


@pytest.mark.parametrize("invalid", [False, "provider", object(), trace.NoOpTracer()])
def test_invalid_explicit_provider_fails_configuration(invalid: Any) -> None:
    with pytest.raises(foghttp.ConfigurationError):
        OpenTelemetryTracing(tracer_provider=invalid)


def test_tracer_acquisition_failure_is_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    failure = RuntimeError("provider failed during configuration")
    provider = trace.NoOpTracerProvider()

    def get_tracer(*_args: object, **_kwargs: object) -> trace.Tracer:
        raise failure

    monkeypatch.setattr(provider, "get_tracer", get_tracer)
    with pytest.raises(foghttp.ConfigurationError) as caught:
        OpenTelemetryTracing(tracer_provider=provider)
    assert caught.value.__cause__ is failure


@pytest.mark.parametrize("methods", ["", " , ", "GET,BAD TOKEN", "GET,POST/", "GET,BAD\nTOKEN", "GET,\u00e9"])
def test_invalid_known_methods_fail_at_construction(monkeypatch: pytest.MonkeyPatch, methods: str) -> None:
    monkeypatch.setenv("OTEL_INSTRUMENTATION_HTTP_KNOWN_METHODS", methods)
    with pytest.raises(foghttp.ConfigurationError):
        OpenTelemetryTracing(tracer_provider=trace.NoOpTracerProvider())


def test_known_methods_are_read_once_per_integration(
    monkeypatch: pytest.MonkeyPatch,
    sync_http_server: str,
    tracing_setup: TracingSetup,
) -> None:
    _tracing, exporter, provider = tracing_setup
    monkeypatch.setenv("OTEL_INSTRUMENTATION_HTTP_KNOWN_METHODS", " POST,POST ")
    tracing = OpenTelemetryTracing(tracer_provider=provider)
    monkeypatch.setenv("OTEL_INSTRUMENTATION_HTTP_KNOWN_METHODS", "GET")
    with foghttp.Client(tracing=tracing, trust_env=False) as client:
        assert client.get(sync_http_server).status_code == HTTPStatus.OK
        assert client.post(sync_http_server).status_code == HTTPStatus.OK
    spans = exporter.get_finished_spans()
    assert [span.name for span in spans] == ["HTTP", "POST"]
    assert [span.attributes["http.request.method"] for span in spans] == ["_OTHER", "POST"]


async def test_disabled_tracing_performs_no_parent_capture(
    monkeypatch: pytest.MonkeyPatch,
    sync_http_server: str,
) -> None:
    def unexpected_capture() -> None:
        pytest.fail("disabled tracing captured the current context")

    monkeypatch.setattr(context, "get_current", unexpected_capture)
    with foghttp.Client(trust_env=False) as client:
        assert client.get(sync_http_server).status_code == HTTPStatus.OK
    async with foghttp.AsyncClient(trust_env=False) as client:
        assert (await client.get(sync_http_server)).status_code == HTTPStatus.OK


def test_instrumentation_scope_and_application_provider_ownership(
    monkeypatch: pytest.MonkeyPatch,
    sync_http_server: str,
    tracing_setup: TracingSetup,
) -> None:
    tracing, exporter, provider = tracing_setup
    global_provider = trace.get_tracer_provider()

    def unexpected_provider_management(*_args: object, **_kwargs: object) -> None:
        pytest.fail("FogHTTP managed an application-owned provider")

    with monkeypatch.context() as patch:
        for name in ("shutdown", "force_flush", "add_span_processor"):
            patch.setattr(provider, name, unexpected_provider_management)
        patch.setattr(trace, "set_tracer_provider", unexpected_provider_management)
        with foghttp.Client(tracing=tracing, trust_env=False) as client:
            assert client.get(sync_http_server).status_code == HTTPStatus.OK

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.instrumentation_scope.name == "foghttp"
    assert span.instrumentation_scope.version == version("foghttp")
    assert span.instrumentation_scope.schema_url == "https://opentelemetry.io/schemas/1.44.0"
    assert trace.get_tracer_provider() is global_provider


@pytest.mark.parametrize("client_type", [foghttp.Client, foghttp.AsyncClient])
async def test_tracing_alone_allocates_no_typed_events_or_native_journal(
    monkeypatch: pytest.MonkeyPatch,
    sync_http_server: str,
    tracing_setup: TracingSetup,
    client_type: Any,
) -> None:
    tracing, exporter, _provider = tracing_setup

    def unexpected_event(*_args: object, **_kwargs: object) -> None:
        pytest.fail("tracing without a sink allocated a telemetry event")

    monkeypatch.setattr(dispatcher, "TelemetryEvent", unexpected_event)
    client = client_type(tracing=tracing, trust_env=False)
    try:
        if isinstance(client, foghttp.Client):
            response = client.get(sync_http_server)
        else:
            response = await client.get(sync_http_server)
        assert response.status_code == HTTPStatus.OK
        raw_events, dropped = client._raw_client().drain_telemetry_events()  # noqa: SLF001
        assert raw_events == []
        assert dropped == 0
        assert len(exporter.get_finished_spans()) == 1
    finally:
        if isinstance(client, foghttp.Client):
            client.close()
        else:
            await client.aclose()
