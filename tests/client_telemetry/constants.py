from foghttp.telemetry import TelemetryEventType


BUFFERED_EVENT_TYPES = (
    TelemetryEventType.REQUEST_STARTED,
    TelemetryEventType.RESPONSE_HEADERS_RECEIVED,
    TelemetryEventType.RESPONSE_BODY_FINISHED,
    TelemetryEventType.REQUEST_FINISHED,
)

BUFFERED_REDIRECT_EVENT_TYPES = (
    TelemetryEventType.REQUEST_STARTED,
    TelemetryEventType.REDIRECT_DECISION,
    TelemetryEventType.RESPONSE_HEADERS_RECEIVED,
    TelemetryEventType.RESPONSE_BODY_FINISHED,
    TelemetryEventType.REQUEST_FINISHED,
)

STREAM_EVENT_TYPES = (
    TelemetryEventType.REQUEST_STARTED,
    TelemetryEventType.RESPONSE_HEADERS_RECEIVED,
    TelemetryEventType.RESPONSE_BODY_FINISHED,
    TelemetryEventType.REQUEST_FINISHED,
)
