from http import HTTPStatus
import sys
import threading
from unittest.mock import patch

import foghttp

from .reentrant_close_helpers import assert_close_rejected, caught_callback, native_stream_read


_EVENT_TIMEOUT = 2
_STATUS_PATH = "/status/200"


def _concurrent_nested_close(url: str) -> None:
    external_waiting = threading.Event()
    external_done = threading.Event()
    errors: list[BaseException] = []
    client: foghttp.Client

    class NestedSink:
        def emit(self, event: foghttp.TelemetryEvent) -> None:
            if event.event_type is not foghttp.TelemetryEventType.REQUEST_STARTED or event.request_id != 1:
                return
            _nested_request_then_reentrant_close(client, url, closer, external_waiting, external_done)

    def close_externally() -> None:
        try:
            client.close()
        except BaseException as error:  # noqa: BLE001
            errors.append(error)
        finally:
            external_done.set()

    client = foghttp.Client(telemetry=foghttp.TelemetryConfig(NestedSink()), trust_env=False)
    closer = threading.Thread(target=close_externally, daemon=True)
    original_wait = client._lifecycle_condition.wait  # noqa: SLF001

    def observe_wait(timeout: float | None = None) -> bool:
        external_waiting.set()
        return original_wait(timeout)

    with patch.object(client._lifecycle_condition, "wait", observe_wait):  # noqa: SLF001
        if client.get(url + _STATUS_PATH).status_code != HTTPStatus.OK:
            message = "Request did not finish successfully"
            raise AssertionError(message)
        if not (external_done.wait(_EVENT_TIMEOUT)):
            message = "External close did not finish after admitted send release"
            raise AssertionError(message)
        closer.join(timeout=_EVENT_TIMEOUT)
    _assert_external_close_completed(client, closer, errors)
    client.close()


def _nested_request_then_reentrant_close(
    client: foghttp.Client,
    url: str,
    closer: threading.Thread,
    external_waiting: threading.Event,
    external_done: threading.Event,
) -> None:
    response = client.get(url + _STATUS_PATH)
    remaining_sends = len(client._active_sync_send_tokens)  # noqa: SLF001
    if response.status_code != HTTPStatus.OK or remaining_sends != 1:
        message = f"Nested request returned {response.status_code} with {remaining_sends} admitted sends"
        raise AssertionError(message)
    closer.start()
    if not (external_waiting.wait(_EVENT_TIMEOUT)):
        message = "External close did not reach the admitted-send wait"
        raise AssertionError(message)
    if not client._closed or external_done.is_set():  # noqa: SLF001
        message = "External close must mark the client closed and keep waiting for the outer admitted send"
        raise AssertionError(message)
    assert_close_rejected(client)


def _assert_external_close_completed(
    client: foghttp.Client,
    closer: threading.Thread,
    errors: list[BaseException],
) -> None:
    if closer.is_alive():
        message = "External close thread remained alive"
        raise AssertionError(message)
    if errors != []:
        message = "External close raised an unexpected error"
        raise AssertionError(message)
    if not client._close_complete or client._active_sync_send_tokens:  # noqa: SLF001
        message = "External close did not complete shutdown and release all admitted sends"
        raise AssertionError(message)


if __name__ == "__main__":
    scenario, server_url = sys.argv[1:]
    if scenario == "request_started":
        caught_callback(server_url, "buffered", foghttp.TelemetryEventType.REQUEST_STARTED, forbid_wait=False)
    elif scenario == "concurrent_nested":
        _concurrent_nested_close(server_url)
    elif scenario == "stream_native_read":
        native_stream_read(forbid_wait=False)
    else:
        raise ValueError(scenario)
