from collections.abc import Mapping, Sequence
from http import HTTPStatus
import subprocess
import sys
from typing import TypeAlias

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import Decision, Sampler, SamplingResult
from opentelemetry.util.types import AttributeValue
import pytest

import foghttp
from foghttp.opentelemetry import OpenTelemetryTracing


SamplingInput: TypeAlias = tuple[trace.SpanContext, dict[str, AttributeValue]]


class DecisionSampler(Sampler):
    def __init__(self, decision: Decision) -> None:
        self.decision = decision
        self.inputs: list[SamplingInput] = []

    def should_sample(
        self,
        parent_context: Context | None,
        trace_id: int,
        name: str,
        kind: trace.SpanKind | None = None,
        attributes: Mapping[str, AttributeValue] | None = None,
        links: Sequence[trace.Link] | None = None,
        trace_state: trace.TraceState | None = None,
    ) -> SamplingResult:
        parent = trace.get_current_span(parent_context).get_span_context()
        assert trace_id == parent.trace_id
        assert name == "GET"
        assert kind is trace.SpanKind.CLIENT
        assert not links
        self.inputs.append((parent, dict(attributes or {})))
        return SamplingResult(self.decision, attributes=attributes, trace_state=trace_state)

    def get_description(self) -> str:
        return self.decision.name


class RecordingProcessor(SpanProcessor):
    def __init__(self) -> None:
        self.started: list[Span] = []
        self.finished: list[ReadableSpan] = []

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        assert span.parent == trace.get_current_span(parent_context).get_span_context()
        self.started.append(span)

    def on_end(self, span: ReadableSpan) -> None:
        self.finished.append(span)


@pytest.mark.parametrize("decision", [Decision.DROP, Decision.RECORD_ONLY], ids=["drop", "record-only"])
async def test_sampling_honors_recording_without_replacing_unsampled_parent(
    sync_http_server: str,
    decision: Decision,
) -> None:
    sampler = DecisionSampler(decision)
    processor = RecordingProcessor()
    exporter = InMemorySpanExporter()
    provider = TracerProvider(sampler=sampler)
    provider.add_span_processor(processor)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    parent_context = trace.SpanContext(trace_id=0x1234, span_id=0x5678, is_remote=True, trace_flags=trace.TraceFlags(0))
    parent = trace.NonRecordingSpan(parent_context)
    tracing = OpenTelemetryTracing(tracer_provider=provider)
    request_count = 2
    try:
        with trace.use_span(parent, end_on_exit=False):
            with foghttp.Client(tracing=tracing, trust_env=False) as client:
                assert client.get(f"{sync_http_server}/status/503").status_code == HTTPStatus.SERVICE_UNAVAILABLE
            async with foghttp.AsyncClient(tracing=tracing, trust_env=False) as client:
                assert (
                    await client.get(f"{sync_http_server}/status/503")
                ).status_code == HTTPStatus.SERVICE_UNAVAILABLE
            assert trace.get_current_span() is parent

        assert len(sampler.inputs) == request_count
        for captured_parent, attributes in sampler.inputs:
            assert captured_parent == parent_context
            assert attributes["http.request.method"] == "GET"
            assert attributes["foghttp.request.mode"] == "buffered"
            assert "http.response.status_code" not in attributes
        assert exporter.get_finished_spans() == ()
        if decision is Decision.DROP:
            assert processor.started == []
            assert processor.finished == []
        else:
            assert len(processor.started) == len(processor.finished) == request_count
            for span in processor.finished:
                assert span.parent == parent_context
                assert span.context.trace_id == parent_context.trace_id
                assert not span.context.trace_flags.sampled
                assert span.attributes["http.response.status_code"] == HTTPStatus.SERVICE_UNAVAILABLE
                assert span.attributes["error.type"] == "503"
                assert span.status.status_code is trace.StatusCode.ERROR
                assert span.end_time is not None
    finally:
        provider.shutdown()


@pytest.mark.parametrize("provider_mode", ["none", "explicit", "late-global"])
def test_provider_selection_isolated_from_process_globals(sync_http_server: str, provider_mode: str) -> None:
    script = """
import asyncio
import sys
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
import foghttp
from foghttp.opentelemetry import OpenTelemetryTracing

url, mode = sys.argv[1:]
global_before = trace.get_tracer_provider()
exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
global_exporter = InMemorySpanExporter()
global_provider = TracerProvider()
global_provider.add_span_processor(SimpleSpanProcessor(global_exporter))

async def requests(tracing):
    with foghttp.Client(tracing=tracing, trust_env=False) as client:
        assert client.get(url).status_code == 200
        with client.stream("GET", url) as response:
            assert b"".join(response.iter_bytes())
    async with foghttp.AsyncClient(tracing=tracing, trust_env=False) as client:
        assert (await client.get(url)).status_code == 200
        async with client.stream("GET", url) as response:
            assert b"".join([chunk async for chunk in response.aiter_bytes()])

try:
    if mode == "explicit":
        trace.set_tracer_provider(global_provider)
        tracing = OpenTelemetryTracing(tracer_provider=provider)
        asyncio.run(requests(tracing))
        assert len(exporter.get_finished_spans()) == 4
        assert global_exporter.get_finished_spans() == ()
        assert trace.get_tracer_provider() is global_provider
    else:
        tracing = OpenTelemetryTracing()
        asyncio.run(requests(tracing))
        assert trace.get_tracer_provider() is global_before
        assert exporter.get_finished_spans() == ()
        if mode == "late-global":
            trace.set_tracer_provider(provider)
            asyncio.run(requests(tracing))
            assert len(exporter.get_finished_spans()) == 4
            assert trace.get_tracer_provider() is provider
finally:
    provider.shutdown()
    global_provider.shutdown()
"""
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-c", script, sync_http_server, provider_mode],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
