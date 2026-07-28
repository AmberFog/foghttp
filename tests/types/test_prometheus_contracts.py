from typing import assert_type

from prometheus_client import CollectorRegistry

import foghttp
from foghttp.prometheus import (
    PrometheusTelemetrySink,
    PrometheusTransportStatsCollector,
)


def test_prometheus_adapter_contracts() -> None:
    registry = CollectorRegistry()
    sink = PrometheusTelemetrySink(registry=registry)
    telemetry_sink: foghttp.TelemetryEventSink = sink
    collector = PrometheusTransportStatsCollector(foghttp.TransportStats)
    registry.register(collector)

    assert_type(sink, PrometheusTelemetrySink)
    assert_type(telemetry_sink, foghttp.TelemetryEventSink)
    assert_type(collector, PrometheusTransportStatsCollector)
