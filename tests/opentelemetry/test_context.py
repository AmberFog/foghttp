import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from http import HTTPStatus
import threading
from unittest.mock import Mock

from opentelemetry import trace
import pytest

import foghttp
from tests.client_streaming.constants import GATED_STREAM_PATH
from tests.client_streaming.server import SyncStreamingServer
from tests.client_telemetry.models import RecordingTelemetrySink
from tests.support.transport_stats import wait_for_async_transport_stats

from . import TracingSetup


PAIRED_REQUESTS = 2
REUSED_REQUEST_EXECUTIONS = 3


def test_build_and_unentered_sync_stream_do_not_start_spans(tracing_setup: TracingSetup, sync_http_server: str) -> None:
    tracing, exporter, _provider = tracing_setup
    with foghttp.Client(tracing=tracing) as client:
        request = client.build_request("GET", sync_http_server)
        client.stream("GET", sync_http_server)
        with pytest.raises(ValueError, match="empty host"):
            client.build_request("GET", "http://")
        assert exporter.get_finished_spans() == ()
        assert client.stats().total_requests == 0
    with pytest.raises(foghttp.ClientClosedError):
        client.send(request)
    assert exporter.get_finished_spans() == ()


async def test_unrun_async_work_does_not_start_spans(tracing_setup: TracingSetup, http_server: str) -> None:
    tracing, exporter, _provider = tracing_setup
    async with foghttp.AsyncClient(tracing=tracing) as client:
        request = client.build_request("GET", http_server)
        client.stream("GET", http_server)
        coroutine = client.send(request)
        coroutine.close()
        assert exporter.get_finished_spans() == ()
        assert client.stats().total_requests == 0
    with pytest.raises(foghttp.ClientClosedError):
        await client.send(request)
    assert exporter.get_finished_spans() == ()


def test_sync_send_and_stream_capture_execution_parent(tracing_setup: TracingSetup, sync_http_server: str) -> None:
    tracing, exporter, provider = tracing_setup
    tracer = provider.get_tracer("application")
    creation_parent = tracer.start_span("creation")
    execution_parent = tracer.start_span("execution")
    original = trace.get_current_span()
    try:
        with foghttp.Client(tracing=tracing) as client:
            with trace.use_span(creation_parent):
                request = client.build_request("GET", sync_http_server)
                stream = client.stream("GET", sync_http_server)
            with trace.use_span(execution_parent):
                assert client.send(request).status_code == HTTPStatus.OK
                assert trace.get_current_span() is execution_parent
                with stream as response:
                    assert response.status_code == HTTPStatus.OK
                    assert trace.get_current_span() is execution_parent
            spans = exporter.get_finished_spans()
            assert len(spans) == PAIRED_REQUESTS
            assert all(span.parent == execution_parent.get_span_context() for span in spans)
            assert len({span.context.span_id for span in spans}) == len(spans)
        assert trace.get_current_span() is original
    finally:
        creation_parent.end()
        execution_parent.end()


async def test_direct_await_and_stream_entry_use_execution_parent(
    tracing_setup: TracingSetup,
    http_server: str,
) -> None:
    tracing, exporter, provider = tracing_setup
    tracer = provider.get_tracer("application")
    creation_parent = tracer.start_span("creation")
    execution_parent = tracer.start_span("execution")
    original = trace.get_current_span()
    try:
        async with foghttp.AsyncClient(tracing=tracing) as client:
            with trace.use_span(creation_parent):
                coroutine = client.get(http_server)
                stream = client.stream("GET", http_server)
            with trace.use_span(execution_parent):
                assert (await coroutine).status_code == HTTPStatus.OK
                assert trace.get_current_span() is execution_parent
                async with stream as response:
                    assert response.status_code == HTTPStatus.OK
                    assert trace.get_current_span() is execution_parent
            spans = exporter.get_finished_spans()
            assert len(spans) == PAIRED_REQUESTS
            assert all(span.parent == execution_parent.get_span_context() for span in spans)
        assert trace.get_current_span() is original
    finally:
        creation_parent.end()
        execution_parent.end()


async def test_scheduled_task_inherits_parent_at_scheduling(tracing_setup: TracingSetup, http_server: str) -> None:
    tracing, exporter, provider = tracing_setup
    tracer = provider.get_tracer("application")
    scheduling_parent = tracer.start_span("scheduling")
    awaiting_parent = tracer.start_span("awaiting")
    try:
        async with foghttp.AsyncClient(tracing=tracing) as client:
            with trace.use_span(scheduling_parent):
                task = asyncio.create_task(client.get(http_server))
            try:
                with trace.use_span(awaiting_parent):
                    assert (await task).status_code == HTTPStatus.OK
                    assert trace.get_current_span() is awaiting_parent
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.parent == scheduling_parent.get_span_context()
    finally:
        scheduling_parent.end()
        awaiting_parent.end()


def test_inline_telemetry_and_nested_request_keep_ambient_parent(
    tracing_setup: TracingSetup,
    sync_http_server: str,
) -> None:
    tracing, exporter, provider = tracing_setup
    parent = provider.get_tracer("application").start_span("parent")
    observed = []
    sink = Mock(spec=RecordingTelemetrySink)
    try:
        with foghttp.Client(tracing=tracing) as nested:

            def emit(event: foghttp.TelemetryEvent) -> None:
                observed.append(trace.get_current_span())
                if event.event_type == foghttp.TelemetryEventType.REQUEST_STARTED:
                    assert nested.get(sync_http_server).status_code == HTTPStatus.OK

            sink.emit.side_effect = emit
            with (
                trace.use_span(parent),
                foghttp.Client(
                    tracing=tracing,
                    telemetry=foghttp.TelemetryConfig(sink=sink),
                ) as client,
            ):
                assert client.get(sync_http_server).status_code == HTTPStatus.OK
                assert trace.get_current_span() is parent
        spans = exporter.get_finished_spans()
        assert len(spans) == PAIRED_REQUESTS
        assert all(span.parent == parent.get_span_context() for span in spans)
        assert observed
        assert all(current is parent for current in observed)
    finally:
        parent.end()


async def test_async_inline_telemetry_does_not_activate_child(tracing_setup: TracingSetup, http_server: str) -> None:
    tracing, exporter, provider = tracing_setup
    parent = provider.get_tracer("application").start_span("parent")
    observed = []
    sink = Mock(spec=RecordingTelemetrySink)
    sink.emit.side_effect = lambda _event: observed.append(trace.get_current_span())
    try:
        with trace.use_span(parent):
            async with foghttp.AsyncClient(tracing=tracing, telemetry=foghttp.TelemetryConfig(sink=sink)) as client:
                assert (await client.get(http_server)).status_code == HTTPStatus.OK
                assert trace.get_current_span() is parent
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.parent == parent.get_span_context()
        assert observed
        assert all(current is parent for current in observed)
    finally:
        parent.end()


async def test_shared_integration_concurrent_clients_and_reused_request(
    tracing_setup: TracingSetup,
    sync_streaming_server: SyncStreamingServer,
) -> None:
    tracing, exporter, provider = tracing_setup
    tracer = provider.get_tracer("application")
    parents = [tracer.start_span("first"), tracer.start_span("second")]
    sinks = [RecordingTelemetrySink(), RecordingTelemetrySink()]
    request = foghttp.Request(
        "GET",
        sync_streaming_server.base_url + GATED_STREAM_PATH,
        headers={"x-original": "unchanged"},
        extensions={"application": "private"},
    )
    original = (request.method, request.url, request.headers.multi_items(), request.content, dict(request.extensions))
    tasks = []
    try:
        async with (
            foghttp.AsyncClient(tracing=tracing, telemetry=foghttp.TelemetryConfig(sink=sinks[0])) as first,
            foghttp.AsyncClient(tracing=tracing, telemetry=foghttp.TelemetryConfig(sink=sinks[1])) as second,
        ):
            try:
                for parent, client in zip(parents, (first, second), strict=True):
                    with trace.use_span(parent):
                        tasks.append(asyncio.create_task(client.send(request)))
                for client in (first, second):
                    await wait_for_async_transport_stats(
                        client,
                        lambda stats: stats.active_requests == 1,
                        message="request did not enter transport",
                    )
                assert exporter.get_finished_spans() == ()
                sync_streaming_server.release_tail.set()
                responses = await asyncio.gather(*tasks)
                assert all(response.status_code == HTTPStatus.OK for response in responses)
            finally:
                sync_streaming_server.release_tail.set()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            spans = exporter.get_finished_spans()
            assert len(spans) == len(parents)
            assert {span.parent.span_id for span in spans} == {parent.get_span_context().span_id for parent in parents}
            started = [
                [
                    event.request_id
                    for event in sink.events
                    if event.event_type == foghttp.TelemetryEventType.REQUEST_STARTED
                ]
                for sink in sinks
            ]
            assert started == [[1], [1]]
            with trace.use_span(parents[0]):
                assert (await first.send(request)).status_code == HTTPStatus.OK
            finished = exporter.get_finished_spans()
            assert len(finished) == REUSED_REQUEST_EXECUTIONS
            assert len({span.context.span_id for span in finished}) == len(finished)
            assert finished[-1].parent == parents[0].get_span_context()
        assert (
            request.method,
            request.url,
            request.headers.multi_items(),
            request.content,
            dict(request.extensions),
        ) == original
    finally:
        for parent in parents:
            parent.end()


def test_shared_integration_isolates_thread_parents(tracing_setup: TracingSetup, sync_http_server: str) -> None:
    tracing, exporter, provider = tracing_setup
    tracer = provider.get_tracer("application")
    parents = [tracer.start_span("first-thread"), tracer.start_span("second-thread")]
    barrier = threading.Barrier(len(parents))
    request = foghttp.Request("GET", sync_http_server)

    def send(parent: trace.Span) -> int:
        with trace.use_span(parent), foghttp.Client(tracing=tracing) as client:
            barrier.wait(timeout=5)
            response = client.send(request)
            assert trace.get_current_span() is parent
            return response.status_code

    try:
        with ThreadPoolExecutor(max_workers=len(parents)) as executor:
            assert list(executor.map(send, parents)) == [HTTPStatus.OK, HTTPStatus.OK]
        spans = exporter.get_finished_spans()
        assert len(spans) == len(parents)
        assert {span.parent.span_id for span in spans} == {parent.get_span_context().span_id for parent in parents}
        assert len({span.context.span_id for span in spans}) == len(parents)
    finally:
        for parent in parents:
            parent.end()
