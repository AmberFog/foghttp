from contextlib import AsyncExitStack
from http import HTTPStatus
from types import MappingProxyType
from urllib.parse import urlsplit

from opentelemetry.trace import StatusCode
import pytest

import foghttp
from foghttp.auth import AuthRequest
from foghttp.opentelemetry import OpenTelemetryTracing
from tests.client_retry.constants import ALWAYS_CLOSE_PATH, ALWAYS_STATUS_PATH, CLOSE_THEN_OK_PATH, STATUS_THEN_OK_PATH
from tests.client_retry.server import start_retry_test_server
from tests.client_tls.certificates import TLSCertificateBundle
from tests.client_tls.models import TLSServer
from tests.redirect_helpers import redirect_to_location_url

from . import TracingSetup, WireHeaders


MANUAL_HEADERS = MappingProxyType(
    {
        "traceparent": "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
        "tracestate": "vendor=manual",
        "baggage": "application=private",
        "b3": "0123456789abcdef-0123456789abcdef-1",
        "x-b3-traceid": "0123456789abcdef",
        "x-vendor-trace": "manual-vendor",
        "authorization": "Bearer private",
        "cookie": "session=private",
    },
)
EXPECTED_ATTEMPTS = 2


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("cross_origin", [False, True], ids=["same-origin", "cross-origin"])
@pytest.mark.parametrize("status", [HTTPStatus.SEE_OTHER, HTTPStatus.TEMPORARY_REDIRECT, HTTPStatus.PERMANENT_REDIRECT])
async def test_redirect_preserves_original_identity_and_wire_headers(
    tracing_setup: TracingSetup,
    sync_http_server: str,
    secondary_sync_http_server: str,
    wire_headers: WireHeaders,
    status: int,
    *,
    asynchronous: bool,
    cross_origin: bool,
) -> None:
    tracing, exporter, _provider = tracing_setup
    target = secondary_sync_http_server if cross_origin else sync_http_server
    url = redirect_to_location_url(sync_http_server, status_code=status, location=f"{target}/final")
    request = foghttp.Request("POST", url, headers=MANUAL_HEADERS, content=b"private body")
    original = (request.method, request.url, request.headers.multi_items(), request.content)
    final_method = "GET" if status == HTTPStatus.SEE_OTHER else "POST"
    observed = []
    for integration in (None, tracing):
        wire_headers.clear()
        async with AsyncExitStack() as stack:
            if asynchronous:
                client = await stack.enter_async_context(
                    foghttp.AsyncClient(tracing=integration, follow_redirects=True),
                )
                response = await client.send(request)
            else:
                client = stack.enter_context(foghttp.Client(tracing=integration, follow_redirects=True))
                response = client.send(request)
        assert response.status_code == HTTPStatus.OK
        assert len(response.history) == 1
        assert response.request.method == final_method
        assert response.url == f"{target}/final"
        observed.append(tuple(wire_headers))
    assert observed[0] == observed[1]
    assert len(observed[1]) == EXPECTED_ATTEMPTS
    assert (request.method, request.url, request.headers.multi_items(), request.content) == original
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "POST"
    assert dict(span.attributes) == {
        "http.request.method": "POST",
        "server.address": "127.0.0.1",
        "server.port": urlsplit(sync_http_server).port,
        "url.scheme": "http",
        "foghttp.request.mode": "buffered",
        "http.response.status_code": HTTPStatus.OK,
    }
    assert span.status.status_code == StatusCode.UNSET
    assert not span.events


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
async def test_https_downgrade_keeps_existing_rejection_and_headers(
    tracing_setup: TracingSetup,
    tls_http_server: TLSServer,
    tls_certificates: TLSCertificateBundle,
    sync_http_server: str,
    wire_headers: WireHeaders,
    *,
    asynchronous: bool,
) -> None:
    tracing, exporter, _provider = tracing_setup
    url = redirect_to_location_url(
        tls_http_server.url,
        status_code=HTTPStatus.TEMPORARY_REDIRECT,
        location=f"{sync_http_server}/final",
    )
    tls = foghttp.TLSConfig(ca_certificates=(tls_certificates.ca_path,))
    observed = []
    for integration in (None, tracing):
        wire_headers.clear()
        async with AsyncExitStack() as stack:
            if asynchronous:
                client = await stack.enter_async_context(
                    foghttp.AsyncClient(tracing=integration, follow_redirects=True, tls=tls),
                )
                with pytest.raises(foghttp.RequestError, match="https-to-http redirect blocked"):
                    await client.post(url, headers=MANUAL_HEADERS, content=b"private body")
            else:
                client = stack.enter_context(foghttp.Client(tracing=integration, follow_redirects=True, tls=tls))
                with pytest.raises(foghttp.RequestError, match="https-to-http redirect blocked"):
                    client.post(url, headers=MANUAL_HEADERS, content=b"private body")
        observed.append(tuple(wire_headers))
    assert observed[0] == observed[1]
    assert len(observed[1]) == 1
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "POST"
    assert span.attributes["url.scheme"] == "https"
    assert span.attributes["server.port"] == urlsplit(tls_http_server.url).port
    assert span.attributes["error.type"] == "RequestError"
    assert span.status.status_code == StatusCode.ERROR
    assert "http.response.status_code" not in span.attributes


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize(
    ("path", "status"),
    [
        (STATUS_THEN_OK_PATH, HTTPStatus.OK),
        (CLOSE_THEN_OK_PATH, HTTPStatus.OK),
        (ALWAYS_STATUS_PATH, HTTPStatus.SERVICE_UNAVAILABLE),
    ],
)
async def test_retries_and_auth_refresh_do_not_change_wire_headers(
    tracing_setup: TracingSetup,
    wire_headers: WireHeaders,
    path: str,
    status: int,
    *,
    asynchronous: bool,
) -> None:
    tracing, exporter, _provider = tracing_setup
    observed = []
    auth_inputs = []
    calls: list[AuthRequest] = []

    def authenticate(request: AuthRequest) -> dict[str, str]:
        calls.append(request)
        return {"authorization": f"Bearer attempt-{len(calls)}"}

    for integration in (None, tracing):
        calls.clear()
        wire_headers.clear()
        with start_retry_test_server() as server:
            async with AsyncExitStack() as stack:
                options = {
                    "tracing": integration,
                    "auth": authenticate,
                    "retry": foghttp.RetryPolicy(retries=1, backoff=0, jitter=0),
                    "headers": MANUAL_HEADERS,
                }
                if asynchronous:
                    client = await stack.enter_async_context(foghttp.AsyncClient(**options))
                    response = await client.get(server.url + path)
                else:
                    client = stack.enter_context(foghttp.Client(**options))
                    response = client.get(server.url + path)
            assert response.status_code == status
            attempts = server.snapshot().requests_for(path)
            assert [request.authorization for request in attempts] == ["Bearer attempt-1", "Bearer attempt-2"]
            assert [call.redirect_hop for call in calls] == [0, 0]
            auth_inputs.append([call.headers for call in calls])
            # Fresh servers use different ports; verify Host against each actual origin.
            assert all(dict(headers)["host"] == urlsplit(server.url).netloc for headers in wire_headers)
            observed.append(
                tuple(tuple((name, value) for name, value in headers if name != "host") for headers in wire_headers),
            )
    assert observed[0] == observed[1]
    assert auth_inputs[0] == auth_inputs[1]
    assert len(observed[1]) == EXPECTED_ATTEMPTS
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "GET"
    assert span.attributes["http.response.status_code"] == status
    expected_error = str(status) if status == HTTPStatus.SERVICE_UNAVAILABLE else None
    assert span.attributes.get("error.type") == expected_error
    assert not span.events
    assert "http.request.resend_count" not in span.attributes


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("decode_content", [False, True], ids=["raw", "decoded"])
@pytest.mark.parametrize("manual", [False, True], ids=["no-propagation", "manual-propagation"])
async def test_stream_wire_headers_are_unchanged(
    tracing_setup: TracingSetup,
    sync_http_server: str,
    wire_headers: WireHeaders,
    *,
    asynchronous: bool,
    decode_content: bool,
    manual: bool,
) -> None:
    tracing, exporter, _provider = tracing_setup
    headers = MANUAL_HEADERS if manual else None
    observed = []
    for integration in (None, tracing):
        wire_headers.clear()
        async with AsyncExitStack() as stack:
            if asynchronous:
                client = await stack.enter_async_context(foghttp.AsyncClient(tracing=integration))
                response = await stack.enter_async_context(
                    client.stream("GET", sync_http_server, headers=headers, decode_content=decode_content),
                )
                assert b"".join([chunk async for chunk in response.aiter_bytes()])
            else:
                client = stack.enter_context(foghttp.Client(tracing=integration))
                response = stack.enter_context(
                    client.stream("GET", sync_http_server, headers=headers, decode_content=decode_content),
                )
                assert b"".join(response.iter_bytes())
        observed.append(tuple(wire_headers))
    assert observed[0] == observed[1]
    assert len(observed[1]) == 1
    received = dict(observed[1][0])
    if manual:
        assert all(received[name] == value for name, value in MANUAL_HEADERS.items())
    else:
        assert not set(MANUAL_HEADERS).intersection(received)
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].attributes["foghttp.request.mode"] == "stream"


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
async def test_exhausted_network_retries_export_one_failure(tracing_setup: TracingSetup, *, asynchronous: bool) -> None:
    tracing, exporter, _provider = tracing_setup
    with start_retry_test_server() as server:
        async with AsyncExitStack() as stack:
            retry = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)
            if asynchronous:
                client = await stack.enter_async_context(foghttp.AsyncClient(tracing=tracing, retry=retry))
                with pytest.raises(foghttp.NetworkError):
                    await client.get(server.url + ALWAYS_CLOSE_PATH)
            else:
                client = stack.enter_context(foghttp.Client(tracing=tracing, retry=retry))
                with pytest.raises(foghttp.NetworkError):
                    client.get(server.url + ALWAYS_CLOSE_PATH)
        assert len(server.snapshot().requests_for(ALWAYS_CLOSE_PATH)) == EXPECTED_ATTEMPTS
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == "NetworkError"
    assert "http.response.status_code" not in span.attributes


def test_private_request_data_is_absent_from_export(tracing_setup: TracingSetup, sync_http_server: str) -> None:
    tracing, exporter, _provider = tracing_setup
    sentinel = "secret-sentinel-not-for-export"
    url = sync_http_server.replace("://", f"://user:{sentinel}@") + f"/{sentinel}?token={sentinel}#{sentinel}"
    with foghttp.Client(tracing=tracing) as client:
        response = client.post(
            url,
            headers={**MANUAL_HEADERS, "x-private": sentinel},
            content=sentinel,
            extensions={"private": sentinel},
        )
    assert response.status_code == HTTPStatus.OK
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert dict(span.attributes) == {
        "http.request.method": "POST",
        "server.address": "127.0.0.1",
        "server.port": urlsplit(sync_http_server).port,
        "url.scheme": "http",
        "foghttp.request.mode": "buffered",
        "http.response.status_code": HTTPStatus.OK,
    }
    assert sentinel not in span.to_json()
    assert not span.events
    assert span.status.description is None


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize(
    ("error", "classification"),
    [
        (RuntimeError("secret exception sentinel"), "_OTHER"),
        (foghttp.NetworkError("secret exception sentinel"), "NetworkError"),
    ],
)
async def test_original_exception_identity_and_private_message(
    tracing_setup: TracingSetup,
    sync_http_server: str,
    error: Exception,
    classification: str,
    caplog: pytest.LogCaptureFixture,
    *,
    asynchronous: bool,
) -> None:
    tracing, exporter, _provider = tracing_setup

    def authenticate(_request: AuthRequest) -> None:
        raise error

    async with AsyncExitStack() as stack:
        if asynchronous:
            client = await stack.enter_async_context(foghttp.AsyncClient(tracing=tracing, auth=authenticate))
            with pytest.raises(type(error)) as caught:
                await client.get(sync_http_server)
        else:
            client = stack.enter_context(foghttp.Client(tracing=tracing, auth=authenticate))
            with pytest.raises(type(error)) as caught:
                client.get(sync_http_server)
    assert caught.value is error
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == classification
    assert span.status.description is None
    assert not span.events
    assert "secret exception sentinel" not in span.to_json()
    assert "secret exception sentinel" not in caplog.text


@pytest.mark.parametrize(
    ("known_methods", "method", "name", "attribute"),
    [
        (None, "PRIVATE-METHOD", "HTTP", "_OTHER"),
        (" GET, CUSTOM, CUSTOM ", "CUSTOM", "CUSTOM", "CUSTOM"),
        (" CUSTOM ", "GET", "HTTP", "_OTHER"),
        (" get ", "GET", "HTTP", "_OTHER"),
    ],
)
def test_known_methods_are_explicit_and_fixed_at_construction(
    tracing_setup: TracingSetup,
    sync_http_server: str,
    monkeypatch: pytest.MonkeyPatch,
    known_methods: str | None,
    method: str,
    name: str,
    attribute: str,
) -> None:
    _tracing, exporter, provider = tracing_setup
    if known_methods is not None:
        monkeypatch.setenv("OTEL_INSTRUMENTATION_HTTP_KNOWN_METHODS", known_methods)
    integration = OpenTelemetryTracing(tracer_provider=provider)
    monkeypatch.setenv("OTEL_INSTRUMENTATION_HTTP_KNOWN_METHODS", "CHANGED-LATER")
    with foghttp.Client(tracing=integration) as client:
        client.request(method, sync_http_server)
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == name
    assert span.attributes["http.request.method"] == attribute
    assert "http.request.method_original" not in span.attributes
    if method != attribute:
        assert method not in span.to_json()
