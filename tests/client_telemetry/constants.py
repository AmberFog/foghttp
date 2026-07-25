from foghttp.telemetry import TelemetryEventType


LOWER_LEVEL_EVENT_TYPES = frozenset(
    (
        TelemetryEventType.POOL_ACQUIRE_STARTED,
        TelemetryEventType.POOL_ACQUIRE_FINISHED,
        TelemetryEventType.CONNECTION_OPENED,
        TelemetryEventType.CONNECTION_OPEN_FAILED,
        TelemetryEventType.CONNECTION_REUSED,
        TelemetryEventType.CONNECTION_CLOSED,
        TelemetryEventType.CONNECTION_ABORTED,
    ),
)


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
