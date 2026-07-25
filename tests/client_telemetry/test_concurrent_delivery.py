from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock

import pytest

import foghttp
from foghttp._client.telemetry import TelemetryRequestContext
from foghttp.status_codes.success import OK
from tests.client_telemetry.assertions import assert_event_sequences_are_unique
from tests.client_telemetry.constants import BUFFERED_EVENT_TYPES, LOWER_LEVEL_EVENT_TYPES
from tests.client_telemetry.models import ThreadSafeTelemetrySink


_CONCURRENT_REQUESTS = 4
_OWNER_RELEASE_TIMEOUT = "timed out waiting to release owner request"


def test_sync_concurrent_requests_emit_unique_ids(sync_http_server: str) -> None:
    sink = ThreadSafeTelemetrySink()
    start_barrier = Barrier(_CONCURRENT_REQUESTS)

    with (
        foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
        ThreadPoolExecutor(max_workers=_CONCURRENT_REQUESTS) as executor,
    ):
        responses = tuple(
            executor.map(
                _get_ok_response,
                (client,) * _CONCURRENT_REQUESTS,
                (sync_http_server,) * _CONCURRENT_REQUESTS,
                range(_CONCURRENT_REQUESTS),
                (start_barrier,) * _CONCURRENT_REQUESTS,
            ),
        )

    assert tuple(response.status_code for response in responses) == (OK,) * _CONCURRENT_REQUESTS
    high_level_events = tuple(event for event in sink.events if event.event_type not in LOWER_LEVEL_EVENT_TYPES)
    assert len(high_level_events) == _expected_event_count()
    assert_event_sequences_are_unique(sink.events)
    assert len({event.request_id for event in sink.events if event.request_id is not None}) == _CONCURRENT_REQUESTS


def test_native_hook_failure_is_raised_by_owning_request(
    sync_http_server: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = _FailForRequestSink()
    request_waiting = Event()
    release_request = Event()
    coordination_lock = Lock()
    blocked_request_id: int | None = None

    with (
        foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        emit_native_telemetry = client._emit_native_telemetry  # noqa: SLF001

        def coordinated_emit(
            telemetry_context: TelemetryRequestContext | None,
            *,
            suppress_hook_errors: bool,
        ) -> None:
            nonlocal blocked_request_id
            should_wait = False
            if telemetry_context is not None and not suppress_hook_errors:
                with coordination_lock:
                    if blocked_request_id is None:
                        blocked_request_id = telemetry_context.data.request_id
                        sink.fail_request_id = blocked_request_id
                        should_wait = True
            if should_wait:
                request_waiting.set()
                if not release_request.wait(timeout=5):
                    raise AssertionError(_OWNER_RELEASE_TIMEOUT)
            emit_native_telemetry(
                telemetry_context,
                suppress_hook_errors=suppress_hook_errors,
            )

        monkeypatch.setattr(client, "_emit_native_telemetry", coordinated_emit)
        owner_future = executor.submit(client.get, f"{sync_http_server}/status/{OK}?owner=1")
        assert request_waiting.wait(timeout=5)

        unrelated_response = client.get(f"{sync_http_server}/status/{OK}?owner=2")
        release_request.set()

        with pytest.raises(foghttp.TelemetryHookError):
            owner_future.result(timeout=5)

    assert unrelated_response.status_code == OK
    assert sink.failed_request_id == blocked_request_id


def _get_ok_response(
    client: foghttp.Client,
    base_url: str,
    request_index: int,
    start_barrier: Barrier,
) -> foghttp.Response:
    start_barrier.wait()
    return client.get(f"{base_url}/status/{OK}?request={request_index}")


def _expected_event_count() -> int:
    return len(BUFFERED_EVENT_TYPES) * _CONCURRENT_REQUESTS


class _FailForRequestSink:
    def __init__(self) -> None:
        self.fail_request_id: int | None = None
        self.failed_request_id: int | None = None
        self._lock = Lock()

    def emit(self, event: foghttp.TelemetryEvent) -> None:
        with self._lock:
            if (
                event.request_id == self.fail_request_id
                and event.event_type == foghttp.TelemetryEventType.POOL_ACQUIRE_STARTED
                and self.failed_request_id is None
            ):
                self.failed_request_id = event.request_id
                raise RuntimeError(event.event_type.value)
