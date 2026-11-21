from contextlib import nullcontext
import warnings

import pytest

import foghttp
from foghttp.status_codes.success import OK
from foghttp.telemetry.config import TelemetryHookErrorPolicy
from tests.client_telemetry.models import FailOnceOnEventTelemetrySink
from tests.client_telemetry.native_warning_sources import controlled_idle_close
from tests.support.transport_stats import wait_for_sync_transport_stats

from .constants import GZIP_RESERVATION
from .payloads import EncodedResponse, gzip_bytes
from .server import ServerFactory
from .text_cleanup_cases import GZIP_FOOTER_BYTES, PRIMARY_TEXT_FAILURES, TERMINAL_EVENTS, TextFailureCase


@pytest.mark.parametrize("case", PRIMARY_TEXT_FAILURES)
def test_sync_primary_text_error_survives_queued_client_warning(
    decompression_server: ServerFactory,
    case: TextFailureCase,
) -> None:
    encoded = gzip_bytes(case.body)
    server = decompression_server(EncodedResponse(encoded, gate_after=len(encoded) - GZIP_FOOTER_BYTES))
    sink = FailOnceOnEventTelemetrySink(foghttp.TelemetryEventType.CONNECTION_CLOSED)
    with (
        controlled_idle_close() as idle,
        foghttp.Client(
            trust_env=False,
            limits=foghttp.Limits(max_active_requests=1),
            telemetry=foghttp.TelemetryConfig(sink=sink, on_hook_error="warn"),
        ) as client,
    ):
        assert client.get(idle.url).status_code == OK
        with client.stream("GET", server.url, decode_content=True) as response:
            request_id = next(
                event.request_id
                for event in reversed(sink.events)
                if event.event_type is foghttp.TelemetryEventType.RESPONSE_HEADERS_RECEIVED
            )
            assert request_id is not None
            idle.release.set()
            wait_for_sync_transport_stats(
                client,
                lambda stats: stats.connections_closed == 1,
                message="controlled idle close was not observed",
            )
            assert client.stats().active_requests == 1
            assert client.stats().stream_decoder_reserved_bytes == GZIP_RESERVATION
            assert not any(event.event_type is foghttp.TelemetryEventType.CONNECTION_CLOSED for event in sink.events)
            iterator = (
                response.iter_lines(errors="strict", max_line_chars=case.line_limit)
                if case.lines
                else response.iter_text(errors="strict")
            )
            with warnings.catch_warnings():
                warnings.simplefilter("error", RuntimeWarning)
                with pytest.raises(case.error_type, match=case.match) as error:
                    next(iterator)
            retained_traceback = error.value.__traceback__
            assert retained_traceback is not None
            assert not server.release_tail.is_set()
            wait_for_sync_transport_stats(
                client,
                lambda stats: (
                    stats.active_requests == stats.pending_requests == stats.stream_decoder_reserved_bytes == 0
                ),
                message="client warning must not delay primary text error cleanup",
            )
            terminal = [
                event for event in sink.events if event.event_type in TERMINAL_EVENTS and event.request_id == request_id
            ]
            assert [event.event_type for event in terminal] == list(TERMINAL_EVENTS)
            assert all(event.outcome is foghttp.TelemetryRequestOutcome.CLOSED for event in terminal)
            assert all(event.error_type is None for event in terminal)
            closed = [
                event
                for event in sink.events
                if event.event_type is foghttp.TelemetryEventType.CONNECTION_CLOSED
                and event.request_id is None
                and event.origin == idle.url
            ]
            assert len(closed) == 1
            assert closed[0].request_id is None
            assert (
                client.get(f"{server.url}/healthy", timeout=foghttp.Timeouts(pool=1.0, total=2.0)).content == b"healthy"
            )
            assert error.value.__traceback__ is retained_traceback
            response.close()
            assert [
                event for event in sink.events if event.event_type in TERMINAL_EVENTS and event.request_id == request_id
            ] == terminal
        with pytest.warns(RuntimeWarning, match="telemetry event sink failed"):
            client.close()
        client.close()


@pytest.mark.parametrize("case", PRIMARY_TEXT_FAILURES)
@pytest.mark.parametrize("fail_on", TERMINAL_EVENTS)
def test_sync_primary_text_error_survives_terminal_hook_and_releases_native_resources(
    decompression_server: ServerFactory,
    case: TextFailureCase,
    fail_on: foghttp.TelemetryEventType,
) -> None:
    encoded = gzip_bytes(case.body)
    server = decompression_server(EncodedResponse(encoded, gate_after=len(encoded) - GZIP_FOOTER_BYTES))
    sink = FailOnceOnEventTelemetrySink(fail_on)
    with (
        foghttp.Client(
            trust_env=False,
            limits=foghttp.Limits(max_active_requests=1),
            telemetry=foghttp.TelemetryConfig(sink=sink),
        ) as client,
        client.stream("GET", server.url, decode_content=True) as response,
    ):
        assert client.stats().active_requests == 1
        assert client.stats().stream_decoder_reserved_bytes == GZIP_RESERVATION
        iterator = (
            response.iter_lines(errors="strict", max_line_chars=case.line_limit)
            if case.lines
            else response.iter_text(errors="strict")
        )
        with pytest.raises(case.error_type, match=case.match) as error:
            next(iterator)
        retained_error = error.value
        retained_traceback = retained_error.__traceback__
        assert retained_traceback is not None
        assert not server.release_tail.is_set()
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == stats.pending_requests == stats.stream_decoder_reserved_bytes == 0,
            message="primary text error must release resources while its traceback is retained",
        )
        assert client.stats().response_body_aborted == 1
        assert client.stats().failed_requests == 1
        terminal = [event for event in sink.events if event.event_type in TERMINAL_EVENTS]
        terminal_types = [event.event_type for event in terminal]
        assert terminal_types.count(fail_on) == 1
        assert all(terminal_types.count(event_type) <= 1 for event_type in TERMINAL_EVENTS)
        assert all(event.outcome is foghttp.TelemetryRequestOutcome.CLOSED for event in terminal)
        assert all(event.error_type is None for event in terminal)
        primary_request_id = terminal[0].request_id
        recovery = client.get(f"{server.url}/healthy", timeout=foghttp.Timeouts(pool=1.0, total=2.0))
        assert recovery.content == b"healthy"
        response.close()
        response.close()
        assert [
            event
            for event in sink.events
            if event.event_type in TERMINAL_EVENTS and event.request_id == primary_request_id
        ] == terminal
        assert retained_error.__traceback__ is retained_traceback


@pytest.mark.parametrize("policy", [None, "warn", "ignore"], ids=["no-telemetry", "warn", "ignore"])
def test_sync_primary_text_error_controls(
    decompression_server: ServerFactory,
    policy: TelemetryHookErrorPolicy | None,
) -> None:
    encoded = gzip_bytes(b"\xffunread")
    server = decompression_server(EncodedResponse(encoded, gate_after=len(encoded) - GZIP_FOOTER_BYTES))
    sink = FailOnceOnEventTelemetrySink(foghttp.TelemetryEventType.RESPONSE_BODY_FINISHED)
    telemetry = None if policy is None else foghttp.TelemetryConfig(sink=sink, on_hook_error=policy)
    with (
        foghttp.Client(trust_env=False, telemetry=telemetry) as client,
        client.stream("GET", server.url, decode_content=True) as response,
    ):
        with pytest.raises(UnicodeDecodeError):
            next(response.iter_text(errors="strict"))
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == stats.stream_decoder_reserved_bytes == 0,
            message="primary-only and non-raising hook controls must release resources",
        )


@pytest.mark.filterwarnings("error::RuntimeWarning")
@pytest.mark.parametrize("case", PRIMARY_TEXT_FAILURES)
def test_sync_primary_text_error_survives_warn_policy_with_warnings_as_errors(
    decompression_server: ServerFactory,
    case: TextFailureCase,
) -> None:
    encoded = gzip_bytes(case.body)
    server = decompression_server(EncodedResponse(encoded, gate_after=len(encoded) - GZIP_FOOTER_BYTES))
    sink = FailOnceOnEventTelemetrySink(foghttp.TelemetryEventType.RESPONSE_BODY_FINISHED)
    with (
        foghttp.Client(
            trust_env=False,
            telemetry=foghttp.TelemetryConfig(sink=sink, on_hook_error="warn"),
        ) as client,
        client.stream("GET", server.url, decode_content=True) as response,
    ):
        iterator = (
            response.iter_lines(errors="strict", max_line_chars=case.line_limit)
            if case.lines
            else response.iter_text(errors="strict")
        )
        with pytest.raises(case.error_type, match=case.match) as error:
            next(iterator)
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == stats.stream_decoder_reserved_bytes == 0,
            message="warning promoted to an error must not mask the primary failure",
        )
        assert error.value.__traceback__ is not None


@pytest.mark.parametrize("encoding", ["foghttp-unknown-codec", "base64_codec"])
@pytest.mark.parametrize("lines", [False, True], ids=["text", "lines"])
def test_sync_lazy_setup_error_survives_completion_hook(
    decompression_server: ServerFactory,
    encoding: str,
    *,
    lines: bool,
) -> None:
    encoded = gzip_bytes(b"unread")
    server = decompression_server(EncodedResponse(encoded, gate_after=0))
    sink = FailOnceOnEventTelemetrySink(foghttp.TelemetryEventType.RESPONSE_BODY_FINISHED)
    with (
        foghttp.Client(trust_env=False, telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
        client.stream("GET", server.url, decode_content=True) as response,
    ):
        iterator = response.iter_lines(encoding=encoding) if lines else response.iter_text(encoding=encoding)
        assert client.stats().active_requests == 1
        assert client.stats().response_body_aborted == 0
        with pytest.raises(LookupError) as error:
            next(iterator)
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == stats.stream_decoder_reserved_bytes == 0,
            message="lazy decoder setup failure must close the unread native body",
        )
        assert error.value.__traceback__ is not None
        assert client.stats().response_body_aborted == 1


@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
@pytest.mark.parametrize("close_early", [False, True], ids=["success", "iterator-close"])
@pytest.mark.parametrize("lines", [False, True], ids=["text", "lines"])
def test_sync_text_completion_keeps_hook_policy_without_primary_error(
    decompression_server: ServerFactory,
    policy: TelemetryHookErrorPolicy,
    *,
    close_early: bool,
    lines: bool,
) -> None:
    encoded = gzip_bytes(b"alpha\n")
    gate_after = len(encoded) - GZIP_FOOTER_BYTES if close_early else None
    server = decompression_server(EncodedResponse(encoded, gate_after=gate_after))
    sink = FailOnceOnEventTelemetrySink(foghttp.TelemetryEventType.RESPONSE_BODY_FINISHED)
    with (
        foghttp.Client(trust_env=False, telemetry=foghttp.TelemetryConfig(sink=sink, on_hook_error=policy)) as client,
        client.stream("GET", server.url, decode_content=True) as response,
    ):
        iterator = response.iter_lines() if lines else response.iter_text()
        expected_chunk = "alpha" if lines else "alpha\n"
        if close_early:
            assert next(iterator) == expected_chunk
        expected = pytest.raises(foghttp.TelemetryHookError) if policy == "raise" else nullcontext()
        warning = pytest.warns(RuntimeWarning, match="telemetry") if policy == "warn" else nullcontext()
        with expected, warning:
            if close_early:
                iterator.close()
            else:
                assert list(iterator) == [expected_chunk]
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == stats.stream_decoder_reserved_bytes == 0,
            message="ordinary text completion policy must still close native resources",
        )
        terminal_types = [event.event_type for event in sink.events if event.event_type in TERMINAL_EVENTS]
        assert terminal_types.count(foghttp.TelemetryEventType.RESPONSE_BODY_FINISHED) == 1
        assert all(terminal_types.count(event_type) <= 1 for event_type in TERMINAL_EVENTS)


@pytest.mark.parametrize("fail_on", [None, *TERMINAL_EVENTS], ids=["no-hook-failure", "body-hook", "request-hook"])
def test_sync_eof_completion_precedes_late_text_decoder_error(
    decompression_server: ServerFactory,
    fail_on: foghttp.TelemetryEventType | None,
) -> None:
    server = decompression_server(EncodedResponse(gzip_bytes(b"\xe2")))
    sink = None if fail_on is None else FailOnceOnEventTelemetrySink(fail_on)
    with (
        foghttp.Client(trust_env=False, telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
        client.stream("GET", server.url, decode_content=True) as response,
    ):
        expected_error = UnicodeDecodeError if fail_on is None else foghttp.TelemetryHookError
        with pytest.raises(expected_error):
            list(response.iter_text(errors="strict"))
        assert client.stats().active_requests == 0
        assert client.stats().stream_decoder_reserved_bytes == 0
        assert client.stats().response_body_aborted == 0
        if sink is not None:
            terminal = [event for event in sink.events if event.event_type in TERMINAL_EVENTS]
            assert all(event.outcome is foghttp.TelemetryRequestOutcome.SUCCESS for event in terminal)
            assert [event.event_type for event in terminal].count(fail_on) == 1
