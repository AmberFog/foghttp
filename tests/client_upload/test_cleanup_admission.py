from collections.abc import Iterator
import threading
from unittest.mock import Mock

import pytest

import foghttp
from foghttp._request_body import RequestBody
from foghttp._upload_body import cleanup_owner, runtime
from foghttp.errors import LifecycleError
from tests.client_multipart.sources import AsyncChunks, SyncChunks
from tests.client_upload.helpers import RecordingRawUploadBody


def test_direct_content_saturation_keeps_provider_caller_owned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = cleanup_owner.CleanupOwner(max_obligations=1)
    monkeypatch.setattr(cleanup_owner._PROCESS_CLEANUP_OWNER, "owner", owner)  # noqa: SLF001
    raw_constructor = Mock()
    monkeypatch.setattr(runtime._foghttp, "RawUploadBody", raw_constructor)  # noqa: SLF001
    source = SyncChunks((b"payload",))

    with pytest.raises(LifecycleError, match="upload cleanup capacity exhausted"):
        runtime.prepare_sync_upload_body(RequestBody.streaming_body(source))

    raw_constructor.assert_not_called()
    assert source.close_calls == 0
    assert owner.snapshot()["reserved"] == 0


async def test_async_content_saturation_keeps_provider_caller_owned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = cleanup_owner.CleanupOwner(max_obligations=1)
    monkeypatch.setattr(cleanup_owner._PROCESS_CLEANUP_OWNER, "owner", owner)  # noqa: SLF001
    source = AsyncChunks((b"payload",))

    with pytest.raises(LifecycleError, match="upload cleanup capacity exhausted"):
        runtime.prepare_async_upload_body(RequestBody.streaming_body(source))

    assert source.close_calls == 0
    assert owner.snapshot()["reserved"] == 0


def test_raw_constructor_failure_returns_unused_capacity_without_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = cleanup_owner.CleanupOwner(max_obligations=2)
    monkeypatch.setattr(cleanup_owner._PROCESS_CLEANUP_OWNER, "owner", owner)  # noqa: SLF001
    raw_error = RuntimeError("raw constructor failed")
    monkeypatch.setattr(runtime._foghttp, "RawUploadBody", Mock(side_effect=raw_error))  # noqa: SLF001
    source = SyncChunks((b"payload",))

    with pytest.raises(RuntimeError) as error:
        runtime.prepare_sync_upload_body(RequestBody.streaming_body(source))

    assert error.value is raw_error
    assert source.close_calls == 0
    assert owner.snapshot()["reserved"] == 0


def test_replay_factory_saturation_refuses_before_product_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = cleanup_owner.CleanupOwner(max_obligations=2)
    monkeypatch.setattr(cleanup_owner._PROCESS_CLEANUP_OWNER, "owner", owner)  # noqa: SLF001
    monkeypatch.setattr(runtime._foghttp, "RawUploadBody", RecordingRawUploadBody)  # noqa: SLF001
    factory = Mock(return_value=SyncChunks((b"payload",)))
    body = runtime.prepare_sync_upload_body(RequestBody.replayable_streaming_body(factory))
    held = owner.reserve()
    raw_body = body.raw_body
    assert isinstance(raw_body, RecordingRawUploadBody)
    try:
        with pytest.raises(LifecycleError, match="upload cleanup capacity exhausted"):
            raw_body.start_callback(raw_body)
        factory.assert_not_called()
    finally:
        held.release()
        body.close()

    assert owner.snapshot()["reserved"] == 0


def test_public_factory_saturation_preserves_lifecycle_error(
    monkeypatch: pytest.MonkeyPatch,
    sync_http_server: str,
) -> None:
    owner = cleanup_owner.CleanupOwner(max_obligations=2)
    monkeypatch.setattr(cleanup_owner._PROCESS_CLEANUP_OWNER, "owner", owner)  # noqa: SLF001
    factory_calls = Mock()

    def factory() -> SyncChunks:
        factory_calls()
        return SyncChunks((b"payload",))

    held = owner.reserve()
    try:
        with (
            foghttp.Client() as client,
            pytest.raises(LifecycleError, match="upload cleanup capacity exhausted"),
        ):
            client.post(sync_http_server, content=factory)
        factory_calls.assert_not_called()
        assert owner.snapshot()["reserved"] == owner.snapshot()["limit"]
    finally:
        held.release()


async def test_public_async_factory_saturation_preserves_lifecycle_error(
    monkeypatch: pytest.MonkeyPatch,
    sync_http_server: str,
) -> None:
    owner = cleanup_owner.CleanupOwner(max_obligations=2)
    monkeypatch.setattr(cleanup_owner._PROCESS_CLEANUP_OWNER, "owner", owner)  # noqa: SLF001
    factory_calls = Mock()

    def factory() -> AsyncChunks:
        factory_calls()
        return AsyncChunks((b"payload",))

    held = owner.reserve()
    try:
        async with foghttp.AsyncClient() as client:
            with pytest.raises(LifecycleError, match="upload cleanup capacity exhausted"):
                await client.post(sync_http_server, content=factory)
        factory_calls.assert_not_called()
        assert owner.snapshot()["reserved"] == owner.snapshot()["limit"]
    finally:
        held.release()


@pytest.mark.parametrize("has_async_close", [True, False])
def test_sync_factory_rejection_prefers_async_cleanup_with_sync_fallback(
    monkeypatch: pytest.MonkeyPatch,
    cold_cleanup_owner: cleanup_owner.CleanupOwner,
    sync_http_server: str,
    *,
    has_async_close: bool,
) -> None:
    source = AsyncChunks(())
    sync_close = Mock()
    monkeypatch.setattr(source, "close", sync_close, raising=False)
    if not has_async_close:
        monkeypatch.setattr(source, "aclose", None)

    with foghttp.Client() as client, pytest.raises(TypeError, match="sync Client cannot send async"):
        client.post(sync_http_server, content=lambda: source)

    if has_async_close:
        assert source.closed is True
        assert source.close_calls == 1
        sync_close.assert_not_called()
    else:
        sync_close.assert_called_once_with()
    assert cold_cleanup_owner.snapshot()["reserved"] == 0


def test_body_close_before_feeder_iteration_preserves_admission_boundary(
    monkeypatch: pytest.MonkeyPatch,
    cold_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    source = _BeforeIterationSource()
    feeder_started = threading.Event()
    feeder_release = threading.Event()
    feeder_finished = threading.Event()
    original_feeder = runtime.feed_sync_upload_body

    def delayed_feeder(*args: object) -> None:
        feeder_started.set()
        try:
            if not feeder_release.wait(2.0):
                message = "delayed feeder was not released before watchdog"
                raise RuntimeError(message)
            original_feeder(*args)
        finally:
            feeder_finished.set()

    monkeypatch.setattr(runtime, "feed_sync_upload_body", delayed_feeder)
    monkeypatch.setattr(runtime._foghttp, "RawUploadBody", RecordingRawUploadBody)  # noqa: SLF001
    body = runtime.prepare_sync_upload_body(RequestBody.streaming_body(source))
    raw_body = body.raw_body
    assert isinstance(raw_body, RecordingRawUploadBody)
    try:
        raw_body.start_callback(raw_body)
        assert feeder_started.wait(1.0)
        body.close()
        assert source.close_calls == 1
    finally:
        feeder_release.set()
    assert feeder_finished.wait(1.0)
    body.close()

    assert source.iteration_calls == 0
    assert source.close_calls == 1
    assert cold_cleanup_owner.snapshot()["reserved"] == 0


class _BeforeIterationSource:
    def __init__(self) -> None:
        self.iteration_calls = 0
        self.close_calls = 0

    def __iter__(self) -> Iterator[bytes]:
        self.iteration_calls += 1
        return iter((b"payload",))

    def close(self) -> None:
        self.close_calls += 1
