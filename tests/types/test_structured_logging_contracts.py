from typing import assert_type

import foghttp


def check_structured_logging_sink_contract() -> None:
    sink = foghttp.StructuredLoggingTelemetrySink()
    telemetry_sink: foghttp.TelemetryEventSink = sink

    assert_type(sink, foghttp.StructuredLoggingTelemetrySink)
    assert_type(telemetry_sink, foghttp.TelemetryEventSink)
