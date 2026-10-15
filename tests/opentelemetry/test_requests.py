import asyncio
from contextlib import AsyncExitStack, suppress
from dataclasses import replace
from http import HTTPStatus
from importlib.metadata import version
import time
from unittest.mock import Mock
from urllib.parse import urlsplit

from opentelemetry.trace import SpanKind, StatusCode
import pytest

import foghttp
from tests.client_retry.constants import ALWAYS_CLOSE_PATH
from tests.client_retry.server import RetryTestServer
from tests.client_streaming.constants import GATED_STREAM_PATH
from tests.client_streaming.server import SyncStreamingServer
from tests.client_telemetry.models import RecordingTelemetrySink
from tests.response_decompression.constants import INVALID_GZIP_PATH
from tests.response_decompression.server import ResponseDecompressionServer
from tests.streaming_decompression.constants import FIRST_OUTPUT, TAIL_OUTPUT, WAIT_TIMEOUT
from tests.streaming_decompression.payloads import EncodedResponse, gated_gzip
from tests.streaming_decompression.read_actions import read_after_signal, read_async_prefix, read_sync_prefix
from tests.streaming_decompression.server import ServerFactory

from . import TracingSetup


@pytest.mark.parametrize(
    "status",
    [HTTPStatus.OK, HTTPStatus.FOUND, HTTPStatus.BAD_REQUEST, HTTPStatus.SERVICE_UNAVAILABLE],
)
def test_sync_buffered_http_outcome(tracing_setup: TracingSetup, sync_http_server: str, status: int) -> None:
    tracing, exporter, _provider = tracing_setup
    before = time.time_ns()
    with foghttp.Client(tracing=tracing) as client:
        response = client.get(f"{sync_http_server}/status/{status}")
    after = time.time_ns()
    assert response.status_code == status
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "GET"
    assert span.kind == SpanKind.CLIENT
    assert span.parent is None
    expected = {
        "http.request.method": "GET",
        "server.address": "127.0.0.1",
        "server.port": urlsplit(sync_http_server).port,
        "url.scheme": "http",
        "foghttp.request.mode": "buffered",
        "http.response.status_code": status,
    }
    if status >= HTTPStatus.BAD_REQUEST:
        expected["error.type"] = str(status)
        expected_status = StatusCode.ERROR
    else:
        expected_status = StatusCode.UNSET
    assert dict(span.attributes) == expected
    assert span.status.status_code == expected_status
    assert span.status.description is None
    assert not span.events
    assert before <= span.start_time <= span.end_time <= after
    assert span.instrumentation_scope.name == "foghttp"
    assert span.instrumentation_scope.version == version("foghttp")
    assert span.instrumentation_scope.schema_url == "https://opentelemetry.io/schemas/1.44.0"


@pytest.mark.parametrize(
    "status",
    [HTTPStatus.OK, HTTPStatus.FOUND, HTTPStatus.NOT_FOUND, HTTPStatus.INTERNAL_SERVER_ERROR],
)
async def test_async_buffered_http_outcome(tracing_setup: TracingSetup, http_server: str, status: int) -> None:
    tracing, exporter, _provider = tracing_setup
    before = time.time_ns()
    async with foghttp.AsyncClient(tracing=tracing) as client:
        response = await client.get(f"{http_server}/status/{status}")
    after = time.time_ns()
    assert response.status_code == status
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "GET"
    assert span.kind == SpanKind.CLIENT
    assert span.parent is None
    expected = {
        "http.request.method": "GET",
        "server.address": "127.0.0.1",
        "server.port": urlsplit(http_server).port,
        "url.scheme": "http",
        "foghttp.request.mode": "buffered",
        "http.response.status_code": status,
    }
    if status >= HTTPStatus.BAD_REQUEST:
        expected["error.type"] = str(status)
        expected_status = StatusCode.ERROR
    else:
        expected_status = StatusCode.UNSET
    assert dict(span.attributes) == expected
    assert span.status.status_code == expected_status
    assert span.status.description is None
    assert not span.events
    assert before <= span.start_time <= span.end_time <= after


@pytest.mark.parametrize(
    ("limits", "error_type"),
    [
        (foghttp.Limits(max_response_body_size=1), foghttp.ResponseBodyTooLargeError),
        (foghttp.Limits(max_buffered_response_bytes=1), foghttp.ResponseBodyBudgetExceededError),
    ],
)
def test_sync_buffered_body_limits(
    tracing_setup: TracingSetup,
    sync_http_server: str,
    limits: foghttp.Limits,
    error_type: type[Exception],
) -> None:
    tracing, exporter, _provider = tracing_setup
    with foghttp.Client(tracing=tracing, limits=limits) as client, pytest.raises(error_type):
        client.get(f"{sync_http_server}/bytes/64")
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == error_type.__name__
    assert "http.response.status_code" not in span.attributes
    assert not span.events


@pytest.mark.parametrize(
    ("limits", "error_type"),
    [
        (foghttp.Limits(max_response_body_size=1), foghttp.ResponseBodyTooLargeError),
        (foghttp.Limits(max_buffered_response_bytes=1), foghttp.ResponseBodyBudgetExceededError),
    ],
)
async def test_async_buffered_body_limits(
    tracing_setup: TracingSetup,
    http_server: str,
    limits: foghttp.Limits,
    error_type: type[Exception],
) -> None:
    tracing, exporter, _provider = tracing_setup
    async with foghttp.AsyncClient(tracing=tracing, limits=limits) as client:
        with pytest.raises(error_type):
            await client.get(f"{http_server}/bytes/64")
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == error_type.__name__
    assert "http.response.status_code" not in span.attributes
    assert not span.events


def test_sync_network_failure(tracing_setup: TracingSetup, retry_server: RetryTestServer) -> None:
    tracing, exporter, _provider = tracing_setup
    with foghttp.Client(tracing=tracing) as client, pytest.raises(foghttp.NetworkError):
        client.get(retry_server.url + ALWAYS_CLOSE_PATH)
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == "NetworkError"
    assert "http.response.status_code" not in span.attributes


async def test_async_network_failure(tracing_setup: TracingSetup, retry_server: RetryTestServer) -> None:
    tracing, exporter, _provider = tracing_setup
    async with foghttp.AsyncClient(tracing=tracing) as client:
        with pytest.raises(foghttp.NetworkError):
            await client.get(retry_server.url + ALWAYS_CLOSE_PATH)
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == "NetworkError"
    assert "http.response.status_code" not in span.attributes


def test_sync_buffered_read_timeout(tracing_setup: TracingSetup, sync_streaming_server: SyncStreamingServer) -> None:
    tracing, exporter, _provider = tracing_setup
    with foghttp.Client(tracing=tracing) as client, pytest.raises(foghttp.ReadTimeout):
        client.get(sync_streaming_server.base_url + GATED_STREAM_PATH, timeout=foghttp.Timeouts(read=0.1))
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == "ReadTimeout"
    assert "http.response.status_code" not in span.attributes


async def test_async_buffered_read_timeout(
    tracing_setup: TracingSetup,
    sync_streaming_server: SyncStreamingServer,
) -> None:
    tracing, exporter, _provider = tracing_setup
    async with foghttp.AsyncClient(tracing=tracing) as client:
        with pytest.raises(foghttp.ReadTimeout):
            await client.get(sync_streaming_server.base_url + GATED_STREAM_PATH, timeout=foghttp.Timeouts(read=0.1))
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == "ReadTimeout"
    assert "http.response.status_code" not in span.attributes


def test_sync_buffered_decode_failure(
    tracing_setup: TracingSetup,
    response_decompression_server: ResponseDecompressionServer,
) -> None:
    tracing, exporter, _provider = tracing_setup
    with foghttp.Client(tracing=tracing) as client, pytest.raises(foghttp.RequestError):
        client.get(response_decompression_server.url + INVALID_GZIP_PATH)
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == "RequestError"
    assert "http.response.status_code" not in span.attributes
    assert not span.events


async def test_async_buffered_decode_failure(
    tracing_setup: TracingSetup,
    response_decompression_server: ResponseDecompressionServer,
) -> None:
    tracing, exporter, _provider = tracing_setup
    async with foghttp.AsyncClient(tracing=tracing) as client:
        with pytest.raises(foghttp.RequestError):
            await client.get(response_decompression_server.url + INVALID_GZIP_PATH)
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == "RequestError"
    assert "http.response.status_code" not in span.attributes
    assert not span.events


@pytest.mark.parametrize("decode_content", [False, True], ids=["raw", "decoded"])
@pytest.mark.parametrize("finish", ["eof", "partial-close", "unread-close"])
def test_sync_stream_finishes_before_headers_and_body(
    tracing_setup: TracingSetup,
    decompression_server: ServerFactory,
    finish: str,
    *,
    decode_content: bool,
) -> None:
    tracing, exporter, _provider = tracing_setup
    case = gated_gzip()
    server = decompression_server(case)
    header_spans = []
    sink = Mock(spec=RecordingTelemetrySink)

    def emit(event: foghttp.TelemetryEvent) -> None:
        if event.event_type == foghttp.TelemetryEventType.RESPONSE_HEADERS_RECEIVED:
            header_spans.append(exporter.get_finished_spans())

    sink.emit.side_effect = emit
    with (
        foghttp.Client(tracing=tracing, telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
        client.stream("GET", server.url, decode_content=decode_content) as response,
    ):
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        snapshot = span.to_json()
        assert header_spans == [(span,)]
        assert span.attributes["foghttp.request.mode"] == "stream"
        assert span.attributes["http.response.status_code"] == HTTPStatus.OK
        assert span.status.status_code == StatusCode.UNSET
        assert not server.release_tail.is_set()
        iterator = response.iter_bytes()
        if finish == "eof":
            server.release_tail.set()
            expected = FIRST_OUTPUT + TAIL_OUTPUT if decode_content else case.body
            assert b"".join(iterator) == expected
        elif finish == "partial-close":
            assert next(iterator)
        response.close()
        response.close()
    assert exporter.get_finished_spans() == (span,)
    assert span.to_json() == snapshot


@pytest.mark.parametrize("decode_content", [False, True], ids=["raw", "decoded"])
@pytest.mark.parametrize("finish", ["eof", "partial-close", "unread-close"])
async def test_async_stream_finishes_before_headers_and_body(
    tracing_setup: TracingSetup,
    decompression_server: ServerFactory,
    finish: str,
    *,
    decode_content: bool,
) -> None:
    tracing, exporter, _provider = tracing_setup
    case = gated_gzip()
    server = decompression_server(case)
    header_spans = []
    sink = Mock(spec=RecordingTelemetrySink)

    def emit(event: foghttp.TelemetryEvent) -> None:
        if event.event_type == foghttp.TelemetryEventType.RESPONSE_HEADERS_RECEIVED:
            header_spans.append(exporter.get_finished_spans())

    sink.emit.side_effect = emit
    async with (
        foghttp.AsyncClient(tracing=tracing, telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
        client.stream("GET", server.url, decode_content=decode_content) as response,
    ):
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        snapshot = span.to_json()
        assert header_spans == [(span,)]
        assert span.attributes["foghttp.request.mode"] == "stream"
        assert span.attributes["http.response.status_code"] == HTTPStatus.OK
        assert span.status.status_code == StatusCode.UNSET
        assert not server.release_tail.is_set()
        iterator = response.aiter_bytes()
        if finish == "eof":
            server.release_tail.set()
            expected = FIRST_OUTPUT + TAIL_OUTPUT if decode_content else case.body
            assert b"".join([chunk async for chunk in iterator]) == expected
        elif finish == "partial-close":
            assert await anext(iterator)
        await response.aclose()
        await response.aclose()
    assert exporter.get_finished_spans() == (span,)
    assert span.to_json() == snapshot


def test_sync_decode_failure_during_stream_entry(
    tracing_setup: TracingSetup,
    decompression_server: ServerFactory,
) -> None:
    tracing, exporter, _provider = tracing_setup
    server = decompression_server(EncodedResponse(b"opaque", encodings=("zstd",)))
    with (
        foghttp.Client(tracing=tracing) as client,
        pytest.raises(foghttp.ResponseDecodingError),
        client.stream("GET", server.url, decode_content=True),
    ):
        pytest.fail("unsupported encoding must fail before exposing the response")
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == "ResponseDecodingError"
    assert "http.response.status_code" not in span.attributes


async def test_async_decode_failure_during_stream_entry(
    tracing_setup: TracingSetup,
    decompression_server: ServerFactory,
) -> None:
    tracing, exporter, _provider = tracing_setup
    server = decompression_server(EncodedResponse(b"opaque", encodings=("zstd",)))
    async with foghttp.AsyncClient(tracing=tracing) as client:
        with pytest.raises(foghttp.ResponseDecodingError):
            async with client.stream("GET", server.url, decode_content=True):
                pytest.fail("unsupported encoding must fail before exposing the response")
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == "ResponseDecodingError"
    assert "http.response.status_code" not in span.attributes


@pytest.mark.parametrize("failure", ["decode", "timeout"])
def test_sync_late_stream_failure_does_not_change_span(
    tracing_setup: TracingSetup,
    decompression_server: ServerFactory,
    failure: str,
) -> None:
    tracing, exporter, _provider = tracing_setup
    case = gated_gzip()
    server = decompression_server(replace(case, body=case.body[:-1]) if failure == "decode" else case)
    with foghttp.Client(tracing=tracing) as client:
        with client.stream("GET", server.url, decode_content=True, timeout=foghttp.Timeouts(read=0.1)) as response:
            spans = exporter.get_finished_spans()
            assert len(spans) == 1
            span = spans[0]
            snapshot = span.to_json()
            iterator = response.iter_bytes()
            assert read_sync_prefix(iterator, len(FIRST_OUTPUT)) == FIRST_OUTPUT
            if failure == "decode":
                server.release_tail.set()
            error_type = foghttp.ResponseDecodingError if failure == "decode" else foghttp.ReadTimeout
            with pytest.raises(error_type):
                list(iterator)
        assert exporter.get_finished_spans() == (span,)
        assert span.to_json() == snapshot
        assert span.status.status_code == StatusCode.UNSET
        assert "error.type" not in span.attributes


@pytest.mark.parametrize("failure", ["decode", "timeout"])
async def test_async_late_stream_failure_does_not_change_span(
    tracing_setup: TracingSetup,
    decompression_server: ServerFactory,
    failure: str,
) -> None:
    tracing, exporter, _provider = tracing_setup
    case = gated_gzip()
    server = decompression_server(replace(case, body=case.body[:-1]) if failure == "decode" else case)
    async with foghttp.AsyncClient(tracing=tracing) as client:
        async with client.stream(
            "GET",
            server.url,
            decode_content=True,
            timeout=foghttp.Timeouts(read=0.1),
        ) as response:
            spans = exporter.get_finished_spans()
            assert len(spans) == 1
            span = spans[0]
            snapshot = span.to_json()
            iterator = response.aiter_bytes()
            assert await read_async_prefix(iterator, len(FIRST_OUTPUT)) == FIRST_OUTPUT
            if failure == "decode":
                server.release_tail.set()
            error_type = foghttp.ResponseDecodingError if failure == "decode" else foghttp.ReadTimeout
            with pytest.raises(error_type):
                _ = [chunk async for chunk in iterator]
        assert exporter.get_finished_spans() == (span,)
        assert span.to_json() == snapshot
        assert span.status.status_code == StatusCode.UNSET
        assert "error.type" not in span.attributes


@pytest.mark.parametrize("decode_content", [False, True], ids=["raw", "decoded"])
async def test_cancelled_body_read_does_not_change_span(
    tracing_setup: TracingSetup,
    decompression_server: ServerFactory,
    *,
    decode_content: bool,
) -> None:
    tracing, exporter, _provider = tracing_setup
    case = gated_gzip()
    server = decompression_server(case)
    async with foghttp.AsyncClient(tracing=tracing) as client:
        async with client.stream("GET", server.url, decode_content=decode_content) as response:
            spans = exporter.get_finished_spans()
            assert len(spans) == 1
            span = spans[0]
            snapshot = span.to_json()
            iterator = response.aiter_bytes()
            prefix_size = len(FIRST_OUTPUT) if decode_content else case.gate_after
            assert len(await read_async_prefix(iterator, prefix_size)) == prefix_size
            started = asyncio.Event()
            task = asyncio.create_task(read_after_signal(iterator, started))
            try:
                await asyncio.wait_for(started.wait(), WAIT_TIMEOUT)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        assert exporter.get_finished_spans() == (span,)
        assert span.to_json() == snapshot
        assert span.status.status_code == StatusCode.UNSET


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
async def test_late_raw_read_timeout_does_not_change_span(
    tracing_setup: TracingSetup,
    decompression_server: ServerFactory,
    *,
    asynchronous: bool,
) -> None:
    tracing, exporter, _provider = tracing_setup
    server = decompression_server(gated_gzip())
    async with AsyncExitStack() as stack:
        if asynchronous:
            client = await stack.enter_async_context(foghttp.AsyncClient(tracing=tracing))
            response = await stack.enter_async_context(
                client.stream("GET", server.url, timeout=foghttp.Timeouts(read=0.1)),
            )
        else:
            client = stack.enter_context(foghttp.Client(tracing=tracing))
            response = stack.enter_context(client.stream("GET", server.url, timeout=foghttp.Timeouts(read=0.1)))
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        snapshot = span.to_json()
        if asynchronous:
            with pytest.raises(foghttp.ReadTimeout):
                _ = [chunk async for chunk in response.aiter_bytes()]
        else:
            with pytest.raises(foghttp.ReadTimeout):
                list(response.iter_bytes())
    assert exporter.get_finished_spans() == (span,)
    assert span.to_json() == snapshot
    assert span.status.status_code == StatusCode.UNSET


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("decode_content", [False, True], ids=["raw", "decoded"])
async def test_abandoned_stream_does_not_own_span(
    tracing_setup: TracingSetup,
    decompression_server: ServerFactory,
    *,
    asynchronous: bool,
    decode_content: bool,
) -> None:
    tracing, exporter, _provider = tracing_setup
    server = decompression_server(gated_gzip())
    async with AsyncExitStack() as stack:
        if asynchronous:
            client = await stack.enter_async_context(foghttp.AsyncClient(tracing=tracing))
            context = client.stream("GET", server.url, decode_content=decode_content)
            response = await context.__aenter__()
        else:
            client = stack.enter_context(foghttp.Client(tracing=tracing))
            context = client.stream("GET", server.url, decode_content=decode_content)
            response = context.__enter__()
        assert response.status_code == HTTPStatus.OK
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        snapshot = span.to_json()
        del response, context
    assert exporter.get_finished_spans() == (span,)
    assert span.to_json() == snapshot
    assert span.status.status_code == StatusCode.UNSET
