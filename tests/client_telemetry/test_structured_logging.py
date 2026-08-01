import logging
from unittest.mock import Mock

import pytest

import foghttp
from foghttp.status_codes.success import OK
from tests.client_keepalive.constants import KEEPALIVE_PATH
from tests.client_keepalive.server import start_keepalive_server


_LOGGER_NAME = "foghttp.lifecycle"
_RAW_USERINFO = "logging-user:logging-password"
_RAW_PATH = "private-logging-path"
_RAW_QUERY_VALUE = "logging-token"


def _event(
    event_type: foghttp.TelemetryEventType,
    *,
    error_type: str | None = None,
    timeout_phase: foghttp.TimeoutPhase | None = None,
) -> foghttp.TelemetryEvent:
    return foghttp.TelemetryEvent(
        event_type=event_type,
        event_sequence=1,
        observed_at_ns=1,
        error_type=error_type,
        timeout_phase=timeout_phase,
    )


@pytest.mark.parametrize(
    "event",
    [
        pytest.param(_event(foghttp.TelemetryEventType.CONNECTION_OPENED), id="connection-opened"),
        pytest.param(_event(foghttp.TelemetryEventType.CONNECTION_OPEN_FAILED), id="connection-open-failed"),
        pytest.param(_event(foghttp.TelemetryEventType.CONNECTION_REUSED), id="connection-reused"),
        pytest.param(_event(foghttp.TelemetryEventType.CONNECTION_CLOSED), id="connection-closed"),
        pytest.param(_event(foghttp.TelemetryEventType.CONNECTION_ABORTED), id="connection-aborted"),
        pytest.param(_event(foghttp.TelemetryEventType.REDIRECT_DECISION), id="redirect"),
        pytest.param(_event(foghttp.TelemetryEventType.RETRY_DECISION), id="retry"),
        pytest.param(
            _event(
                foghttp.TelemetryEventType.REQUEST_FINISHED,
                error_type="ReadTimeout",
                timeout_phase="response_body",
            ),
            id="timeout-with-phase",
        ),
        pytest.param(
            _event(
                foghttp.TelemetryEventType.REQUEST_FINISHED,
                error_type="TimeoutError",
            ),
            id="timeout-without-phase",
        ),
    ],
)
def test_logging_sink_emits_selected_lifecycle_events(
    event: foghttp.TelemetryEvent,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = foghttp.StructuredLoggingTelemetrySink()

    with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
        sink.emit(event)

    record = _single_foghttp_record(caplog)
    assert record.levelno == logging.DEBUG
    assert record.getMessage() == f"FogHTTP lifecycle event: {event.event_type.value}"
    assert record.__dict__["foghttp_event_type"] == event.event_type.value


@pytest.mark.parametrize(
    "event_type",
    [
        foghttp.TelemetryEventType.REQUEST_STARTED,
        foghttp.TelemetryEventType.POOL_ACQUIRE_FINISHED,
        foghttp.TelemetryEventType.RESPONSE_HEADERS_RECEIVED,
        foghttp.TelemetryEventType.RESPONSE_BODY_FINISHED,
        foghttp.TelemetryEventType.REQUEST_FINISHED,
    ],
)
def test_logging_sink_ignores_non_lifecycle_events(
    event_type: foghttp.TelemetryEventType,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = foghttp.StructuredLoggingTelemetrySink()

    with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
        sink.emit(_event(event_type))

    assert _foghttp_records(caplog) == ()


def test_logging_sink_exposes_stable_safe_structured_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = foghttp.StructuredLoggingTelemetrySink()
    event = foghttp.TelemetryEvent(
        event_type=foghttp.TelemetryEventType.RETRY_DECISION,
        event_sequence=7,
        observed_at_ns=11,
        request_id=13,
        mode=foghttp.TelemetryRequestMode.BUFFERED,
        method="GET",
        origin=f"https://{_RAW_USERINFO}@example.com/{_RAW_PATH}?token={_RAW_QUERY_VALUE}",
        redacted_url=f"https://example.com/{_RAW_PATH}?token={_RAW_QUERY_VALUE}",
        status_code=503,
        elapsed_ns=17,
        redirect_hop=2,
        retry_attempt=3,
        retry_decision=foghttp.TelemetryRetryDecision.RETRY,
        retry_reason=foghttp.TelemetryRetryReason.STATUS,
        retry_backoff_ns=19,
        outcome=foghttp.TelemetryRequestOutcome.ERROR,
        error_type="ReadTimeout",
        timeout_phase="response_body",
    )

    with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
        sink.emit(event)

    record = _single_foghttp_record(caplog)
    fields = {key: value for key, value in record.__dict__.items() if key.startswith("foghttp_")}
    assert fields == {
        "foghttp_event_type": "retry_decision",
        "foghttp_schema_version": event.schema_version,
        "foghttp_event_sequence": 7,
        "foghttp_observed_at_ns": 11,
        "foghttp_request_id": 13,
        "foghttp_mode": "buffered",
        "foghttp_method": "GET",
        "foghttp_origin": "https://example.com",
        "foghttp_status_code": 503,
        "foghttp_elapsed_ns": 17,
        "foghttp_redirect_hop": 2,
        "foghttp_retry_attempt": 3,
        "foghttp_retry_decision": "retry",
        "foghttp_retry_reason": "status",
        "foghttp_retry_backoff_ns": 19,
        "foghttp_outcome": "error",
        "foghttp_error_type": "ReadTimeout",
        "foghttp_timeout_phase": "response_body",
    }
    serialized_record = f"{record.getMessage()} {fields!r}"
    assert "foghttp_redacted_url" not in fields
    assert _RAW_USERINFO not in serialized_record
    assert _RAW_PATH not in serialized_record
    assert _RAW_QUERY_VALUE not in serialized_record


def test_logging_sink_drops_malformed_origin(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = foghttp.StructuredLoggingTelemetrySink()
    malformed_origin = f"not-an-origin?token={_RAW_QUERY_VALUE}"
    event = foghttp.TelemetryEvent(
        event_type=foghttp.TelemetryEventType.CONNECTION_OPEN_FAILED,
        event_sequence=1,
        observed_at_ns=1,
        origin=malformed_origin,
    )

    with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
        sink.emit(event)

    record = _single_foghttp_record(caplog)
    assert record.__dict__["foghttp_origin"] is None
    assert malformed_origin not in record.getMessage()


def test_logging_sink_does_not_build_records_below_debug_level(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = foghttp.StructuredLoggingTelemetrySink()
    log_fields = Mock()
    monkeypatch.setattr("foghttp.telemetry.logging._log_fields", log_fields)

    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        sink.emit(_event(foghttp.TelemetryEventType.CONNECTION_OPENED))

    log_fields.assert_not_called()
    assert _foghttp_records(caplog) == ()


def test_sync_client_logging_is_disabled_by_default(
    sync_http_server: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME), foghttp.Client() as client:
        response = client.get(sync_http_server)

    assert response.status_code == OK
    assert _foghttp_records(caplog) == ()


def test_sync_logging_emits_connection_lifecycle_without_url_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = foghttp.StructuredLoggingTelemetrySink()

    with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME), start_keepalive_server() as server:
        url = f"{server.url}{KEEPALIVE_PATH}?token={_RAW_QUERY_VALUE}"
        with foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink)) as client:
            first = client.get(url)
            second = client.get(url)

    assert first.status_code == OK
    assert second.status_code == OK
    records = _foghttp_records(caplog)
    event_types = {record.__dict__["foghttp_event_type"] for record in records}
    assert {
        "connection_opened",
        "connection_reused",
        "connection_closed",
    } <= event_types
    assert all(record.__dict__["foghttp_origin"] == server.url for record in records)
    assert all(_RAW_QUERY_VALUE not in record.getMessage() for record in records)


async def test_async_logging_emits_terminal_timeout(
    http_server: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = foghttp.StructuredLoggingTelemetrySink()
    limits = foghttp.Limits(max_active_requests=0, max_pending_requests=1)
    timeouts = foghttp.Timeouts(pool=0.001)

    with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
        async with foghttp.AsyncClient(
            limits=limits,
            timeouts=timeouts,
            telemetry=foghttp.TelemetryConfig(sink=sink),
        ) as client:
            with pytest.raises(foghttp.PoolTimeout):
                await client.get(http_server)

    timeout_record = next(
        record for record in _foghttp_records(caplog) if record.__dict__["foghttp_event_type"] == "request_finished"
    )
    assert timeout_record.__dict__["foghttp_error_type"] == "PoolTimeout"
    assert timeout_record.__dict__["foghttp_timeout_phase"] == "pool_acquire"


def _foghttp_records(caplog: pytest.LogCaptureFixture) -> tuple[logging.LogRecord, ...]:
    return tuple(record for record in caplog.records if record.name == _LOGGER_NAME)


def _single_foghttp_record(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    records = _foghttp_records(caplog)
    assert len(records) == 1
    return records[0]
