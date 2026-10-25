from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from http import HTTPStatus
from unittest.mock import patch

import pytest

import foghttp
from tests.fault_injection.constants import HEALTHY_PATH, INCOMPLETE_BODY_PATH
from tests.fault_injection.server import start_fault_injection_server
from tests.support.transport_stats import wait_for_sync_transport_stats


_STATUS_PATH = "/status/200"


def _lifecycle_state(client: foghttp.Client) -> tuple[object, ...]:
    return (
        client._closed,  # noqa: SLF001
        client._close_complete,  # noqa: SLF001
        client._client,  # noqa: SLF001
        frozenset(client._active_sync_send_tokens),  # noqa: SLF001
        client._telemetry._native_delivery._closed,  # noqa: SLF001
    )


def assert_close_rejected(client: foghttp.Client) -> None:
    before = _lifecycle_state(client)
    with pytest.raises(foghttp.LifecycleError, match="Cannot close"):
        client.close()
    if _lifecycle_state(client) != before:
        message = "Rejected close changed client lifecycle state"
        raise AssertionError(message)


@contextmanager
def forbid_self_wait(client: foghttp.Client) -> Iterator[None]:
    failure = AssertionError("reentrant close attempted a lifecycle wait")
    with (
        patch.object(client._lifecycle_condition, "wait", side_effect=failure),  # noqa: SLF001
        patch.object(client._telemetry._native_delivery._condition, "wait", side_effect=failure),  # noqa: SLF001
    ):
        yield


class CloseSink:
    def __init__(self, target: foghttp.TelemetryEventType, *, catch: bool = True) -> None:
        self.target = target
        self.catch = catch
        self.client: foghttp.Client | None = None
        self.rejected_closes = 0
        self.attempts = 0
        self.no_active_send = False
        self.nested_url: str | None = None

    def emit(self, event: foghttp.TelemetryEvent) -> None:
        if event.event_type != self.target or self.attempts:
            return
        self.attempts += 1
        client = self.client
        if not (client is not None):
            message = "Telemetry callback has no owning client"
            raise AssertionError(message)
        if self.nested_url is not None and client.get(self.nested_url).status_code != HTTPStatus.OK:
            message = "Nested native delivery request did not succeed"
            raise AssertionError(message)
        if self.no_active_send and client._active_sync_send_tokens:  # noqa: SLF001
            message = "Completed send retained its lifecycle token"
            raise AssertionError(message)
        if self.catch:
            assert_close_rejected(client)
            self.rejected_closes += 1
        else:
            client.close()


def request_status(client: foghttp.Client, url: str, mode: str) -> None:
    if mode == "buffered":
        if client.get(url).status_code != HTTPStatus.OK:
            message = "Buffered request did not succeed"
            raise AssertionError(message)
    else:
        with client.stream("GET", url) as response:
            if response.status_code != HTTPStatus.OK:
                message = "Stream acquisition did not succeed"
                raise AssertionError(message)
            if b"".join(response.iter_bytes()) != b"":
                message = "Empty status response returned unexpected stream content"
                raise AssertionError(message)


def caught_callback(url: str, mode: str, event_type: foghttp.TelemetryEventType, *, forbid_wait: bool) -> None:
    sink = CloseSink(event_type)
    client = foghttp.Client(telemetry=foghttp.TelemetryConfig(sink), trust_env=False)
    sink.client = client
    try:
        boundary = forbid_self_wait(client) if forbid_wait else nullcontext()
        with boundary:
            request_status(client, url + _STATUS_PATH, mode)
        if sink.attempts != 1 or sink.rejected_closes != 1:
            message = "Expected exactly one confirmed reentrant close rejection"
            raise AssertionError(message)
        if client._active_sync_send_tokens or client.stats().active_requests != 0:  # noqa: SLF001
            message = "Completed request retained its Python token or native permit"
            raise AssertionError(message)
        if client.get(url + _STATUS_PATH).status_code != HTTPStatus.OK:
            message = "Request did not finish successfully"
            raise AssertionError(message)
    finally:
        with forbid_self_wait(client):
            client.close()
            client.close()


def native_stream_read(*, forbid_wait: bool) -> None:
    sink = CloseSink(foghttp.TelemetryEventType.CONNECTION_ABORTED)
    sink.no_active_send = True
    with start_fault_injection_server() as server:
        sink.nested_url = server.url + HEALTHY_PATH
        client = foghttp.Client(telemetry=foghttp.TelemetryConfig(sink), trust_env=False)
        sink.client = client
        try:
            boundary = forbid_self_wait(client) if forbid_wait else nullcontext()
            with (
                boundary,
                client.stream("GET", server.url + INCOMPLETE_BODY_PATH) as response,
                pytest.raises(foghttp.RequestError),
            ):
                b"".join(response.iter_bytes())
            if sink.attempts != 1 or sink.rejected_closes != 1:
                message = "Expected exactly one confirmed reentrant close rejection"
                raise AssertionError(message)
            wait_for_sync_transport_stats(
                client,
                lambda stats: stats.active_requests == 0,
                message="failed stream read retained its native request",
            )
            if client.get(server.url + HEALTHY_PATH).status_code != HTTPStatus.OK:
                message = "Client failed to recover after rejected close"
                raise AssertionError(message)
        finally:
            with forbid_self_wait(client):
                client.close()
