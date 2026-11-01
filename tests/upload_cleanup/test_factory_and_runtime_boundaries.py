import asyncio
from functools import partial
import threading
from typing import Any

import pytest

from foghttp._request_body import RequestBody
from foghttp._upload_body import attempt, cleanup_owner, runtime
from foghttp._upload_body.thread_bridge import start_daemon_worker
from tests.client_multipart.sources import AsyncChunks
from tests.client_upload.helpers import RecordingRawUploadBody

from .constants import CHAIN_OBLIGATIONS, COMPLETION_WATCHDOG
from .sources import SyncCloseGate


def test_content_factory_failure_returns_reserved_capacity_and_preserves_error(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    failure = GeneratorExit("content factory interrupted before product")
    observed_capacity: list[int] = []

    def failing_factory() -> object:
        observed_capacity.append(isolated_cleanup_owner.snapshot()["reserved"])
        raise failure

    with pytest.raises(GeneratorExit) as observed:
        attempt.prepare_factory_source(failing_factory)

    assert observed.value is failure
    assert observed_capacity == [CHAIN_OBLIGATIONS]
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0
    recovery = SyncCloseGate(blocked=False)
    product, source_cleanup, source_error = attempt.prepare_factory_source(lambda: recovery)
    assert product is recovery
    assert source_error is None
    source_cleanup.close()
    assert recovery.calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0


async def test_async_raw_constructor_failure_keeps_source_caller_owned_and_recovers(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = RuntimeError("async raw body construction failed")
    source = AsyncChunks((b"not accepted",))
    observed_capacity: list[int] = []

    def failing_constructor(*_args: Any, **_kwargs: Any) -> object:
        observed_capacity.append(isolated_cleanup_owner.snapshot()["reserved"])
        raise failure

    with monkeypatch.context() as failed:
        failed.setattr(runtime._foghttp, "RawUploadBody", failing_constructor)  # noqa: SLF001
        with pytest.raises(RuntimeError) as observed:
            runtime.prepare_async_upload_body(RequestBody.streaming_body(source))

    assert observed.value is failure
    assert observed_capacity == [CHAIN_OBLIGATIONS]
    assert source.close_calls == 0
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0
    recovered = runtime.prepare_async_upload_body(RequestBody.streaming_body(source))
    await recovered.aclose()
    assert source.close_calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0


async def test_close_after_factory_preparation_cleans_source_before_runner_registration(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = AsyncChunks((b"never consumed",))
    runner_created = threading.Event()
    runner_release = threading.Event()
    original_runner = runtime.AsyncFeederRunner

    def delayed_runner(*args: Any, **kwargs: Any) -> runtime.AsyncFeederRunner:
        runner = original_runner(*args, **kwargs)
        runner_created.set()
        if not runner_release.wait(COMPLETION_WATCHDOG):
            message = "prepared runner registration watchdog expired"
            raise RuntimeError(message)
        return runner

    monkeypatch.setattr(runtime, "AsyncFeederRunner", delayed_runner)
    monkeypatch.setattr(runtime._foghttp, "RawUploadBody", RecordingRawUploadBody)  # noqa: SLF001
    body = runtime.prepare_async_upload_body(RequestBody.replayable_streaming_body(lambda: source))
    raw_body = body.raw_body
    assert isinstance(raw_body, RecordingRawUploadBody)
    starter = start_daemon_worker(partial(raw_body.start_callback, raw_body))
    try:
        assert await asyncio.to_thread(runner_created.wait, COMPLETION_WATCHDOG)
        assert isolated_cleanup_owner.snapshot()["reserved"] == CHAIN_OBLIGATIONS
        await body.aclose()
        assert source.close_calls == 1
        assert isolated_cleanup_owner.snapshot()["reserved"] == 0
    finally:
        runner_release.set()
        await asyncio.wait_for(asyncio.wrap_future(starter), COMPLETION_WATCHDOG)
    await body.aclose()
    assert source.close_calls == 1
    assert raw_body.closed is True
    assert body.raw_body is None
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0
