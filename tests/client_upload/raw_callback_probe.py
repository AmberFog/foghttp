__all__ = ("PROBE_SCENARIOS", "PROBE_TIMEOUT", "RAW_REQUEST_METHODS", "REJECTED_SCENARIOS")

import asyncio
from contextlib import closing
import json
import sys
import threading
from typing import Any

from foghttp import _foghttp
from foghttp._client.proxy import ProxyTransportPolicy
from foghttp.methods import POST
from tests.client_options.raw_options import raw_client_options


RAW_REQUEST_METHODS = ("request", "request_stream", "request_async", "request_stream_async")
REJECTED_SCENARIOS = ("send_byte", "send_final_byte", "caught_send_final_byte", "fail_queue")
PROBE_SCENARIOS = (*REJECTED_SCENARIOS, "small_inline", "worker")
PROBE_TIMEOUT = 5.0
PAYLOAD = b"data"
RECOVERY_PAYLOAD = b"r"
QUEUE_FILL_COUNT = 8
QUEUE_SCENARIO_BUDGET = 64
RESPONSE_CHUNK_GUARD = 256
WORKER_JOIN_TIMEOUT = 1.0
CALLBACK_FAILURE = "provider callback failed"
QUEUE_PREFILL_REJECTED = "queue setup failed before the intended terminal send"
INLINE_REJECTED = "inline send unexpectedly returned False"
WORKER_REJECTED = "background blocking send failed"
RECOVERY_REJECTED = "recovery upload did not obtain the released capacity"
RAW_ECHO_NOT_FINISHED = "raw echo response did not reach EOF"


class RawCallbackProbe:
    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        self.events: list[str] = []
        self.worker: threading.Thread | None = None
        self.worker_error: BaseException | None = None
        self.callback_error: str | None = None

    def start(self, attempt: _foghttp.RawUploadBody) -> None:
        self.record("callback_enter")
        if self.scenario == "worker":
            self.worker = threading.Thread(target=self._feed_worker, args=(attempt,), daemon=True)
            self.worker.start()
        else:
            self._feed_inline(attempt)
        self.record("callback_exit")

    def record(self, event: str) -> None:
        self.events.append(event)
        sys.stderr.write(event + "\n")
        sys.stderr.flush()

    def join_worker(self) -> bool:
        if self.worker is None:
            return True
        self.worker.join(WORKER_JOIN_TIMEOUT)
        return not self.worker.is_alive()

    def _feed_inline(self, attempt: _foghttp.RawUploadBody) -> None:
        if self.scenario == "fail_queue":
            for _chunk_index in range(QUEUE_FILL_COUNT):
                if not attempt.send_nowait(b"x"):
                    raise AssertionError(QUEUE_PREFILL_REJECTED)
            attempt.fail(CALLBACK_FAILURE)
            return
        send = attempt.send if self.scenario == "send_byte" else attempt.send_final
        try:
            accepted = send(PAYLOAD)
        except _foghttp.FogHttpLifecycleError as error:
            self.callback_error = type(error).__name__
            self.record("callback_capacity_error")
            if self.scenario != "caught_send_final_byte":
                raise
            self.record("callback_caught_capacity_error")
            return
        if not accepted:
            raise AssertionError(INLINE_REJECTED)
        if self.scenario == "send_byte":
            attempt.finish()

    def _feed_worker(self, attempt: _foghttp.RawUploadBody) -> None:
        self.record("worker_enter")
        try:
            accepted = attempt.send_final(PAYLOAD)
        except BaseException as error:  # noqa: BLE001 - subprocess records every worker outcome
            self.worker_error = error
        else:
            if not accepted:
                self.worker_error = AssertionError(WORKER_REJECTED)
        self.record("worker_exit")


async def callback_probe(request_method: str, scenario: str, url: str) -> dict[str, Any]:
    probe = RawCallbackProbe(scenario)
    budget = _scenario_budget(scenario)
    with (
        closing(
            _foghttp.RawClient(
                **raw_client_options(max_upload_buffer_bytes=budget, max_total_upload_buffer_bytes=budget),
            ),
        ) as raw_client,
        closing(
            _foghttp.RawUploadBody(
                None,
                probe.start,
                replayable=False,
                ready_callback=None,
                raw_client=raw_client,
            ),
        ) as body,
    ):
        observation = await _observe_request(raw_client, body, request_method, url, scenario)
        observation["stats_before_recovery"] = _settled_stats(raw_client)
        if scenario in REJECTED_SCENARIOS:
            observation["recovery_body"] = await _recover(raw_client, request_method, url)
        observation["worker_joined"] = probe.join_worker()
        observation["worker_error"] = None if probe.worker_error is None else type(probe.worker_error).__name__
        observation["callback_error"] = probe.callback_error
        observation["events"] = probe.events
        observation["stats_after_recovery"] = _settled_stats(raw_client)
        return observation


def _scenario_budget(scenario: str) -> int:
    if scenario == "fail_queue":
        return QUEUE_SCENARIO_BUDGET
    return len(PAYLOAD) if scenario == "small_inline" else 1


async def _observe_request(
    raw_client: _foghttp.RawClient,
    body: _foghttp.RawUploadBody,
    request_method: str,
    url: str,
    scenario: str,
) -> dict[str, Any]:
    try:
        content = await _raw_request(
            raw_client,
            body,
            request_method,
            url,
            None if scenario == "fail_queue" else PAYLOAD,
        )
    except BaseException as error:  # noqa: BLE001 - retain exact raw error in subprocess output
        return {"error_type": type(error).__name__, "error_message": str(error)}
    return {"error_type": None, "response_body": json.loads(content)["body"]}


async def _recover(raw_client: _foghttp.RawClient, request_method: str, url: str) -> str:
    def start_recovery(attempt: _foghttp.RawUploadBody) -> None:
        if not attempt.send_final(RECOVERY_PAYLOAD):
            raise AssertionError(RECOVERY_REJECTED)

    with closing(
        _foghttp.RawUploadBody(
            1,
            start_recovery,
            replayable=False,
            ready_callback=None,
            raw_client=raw_client,
        ),
    ) as body:
        content = await _raw_request(raw_client, body, request_method, url, RECOVERY_PAYLOAD)
    return str(json.loads(content)["body"])


async def _raw_request(
    raw_client: _foghttp.RawClient,
    body: _foghttp.RawUploadBody,
    request_method: str,
    url: str,
    payload: bytes | None,
) -> bytes:
    response = getattr(raw_client, request_method)(**_request_options(body, url, payload))
    if request_method.endswith("_async"):
        response = await response
    if "stream" not in request_method:
        return bytes(response.content)
    with closing(response):
        chunks: list[bytes] = []
        for _chunk_index in range(RESPONSE_CHUNK_GUARD):
            chunk = await response.next_chunk_async() if request_method.endswith("_async") else response.next_chunk()
            if chunk is None:
                return b"".join(chunks)
            chunks.append(chunk)
    raise AssertionError(RAW_ECHO_NOT_FINISHED)


def _request_options(body: _foghttp.RawUploadBody, url: str, payload: bytes | None) -> dict[str, object]:
    return {
        "method": POST,
        "url": url,
        "headers": [] if payload is None else [("content-length", str(len(payload)))],
        "auth_override_headers": None,
        "auth_removed_headers": [],
        "extensions": None,
        "body": None,
        "body_stream": body,
        "body_replayable": False,
        "use_proxy_transport": False,
        "proxy_policy": ProxyTransportPolicy.DIRECT.value,
        "pool_timeout": 1.0,
        "read_timeout": 1.0,
        "write_timeout": 1.0,
        "total_timeout": 2.0,
    }


def _settled_stats(raw_client: _foghttp.RawClient) -> dict[str, int]:
    stats = raw_client.stats()
    return {
        "active_requests": stats.active_requests,
        "pending_requests": stats.pending_requests,
        "connections_opened": stats.connections_opened,
    }


if __name__ == "__main__":
    sys.stdout.write(json.dumps(asyncio.run(callback_probe(*sys.argv[1:]))))
