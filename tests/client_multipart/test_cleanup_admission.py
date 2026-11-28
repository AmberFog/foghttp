from collections.abc import Iterator
import threading
from unittest.mock import Mock

import pytest

import foghttp
from foghttp._multipart.models import MultipartFile, MultipartPayload
from foghttp._multipart.stream import MultipartStream, MultipartStreamFactory
from foghttp._multipart.sync_runner import SyncIteratorRunner
from foghttp._upload_body import cleanup_owner
from foghttp._upload_body.cleanup import UploadSourceFactoryFailure
from foghttp.errors import LifecycleError
from tests.client_multipart.sources import SyncChunks


def test_partial_multipart_factory_saturation_keeps_accepted_product_for_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = cleanup_owner.CleanupOwner(max_obligations=3)
    monkeypatch.setattr(cleanup_owner._PROCESS_CLEANUP_OWNER, "owner", owner)  # noqa: SLF001
    source = SyncChunks((b"payload",))
    first_factory = Mock(return_value=source)
    refused_factory = Mock(return_value=SyncChunks((b"refused",)))
    payload = MultipartPayload(
        boundary="boundary",
        fields=(),
        files=(_factory_file(first_factory), _factory_file(refused_factory)),
    )

    result = MultipartStreamFactory(payload)()

    assert isinstance(result, UploadSourceFactoryFailure)
    assert isinstance(result.error, LifecycleError)
    first_factory.assert_called_once_with()
    refused_factory.assert_not_called()
    assert isinstance(result.source, MultipartStream)
    result.source.close()
    result.source.close()
    assert source.close_calls == 1
    assert owner.snapshot()["reserved"] == 0


def test_direct_multipart_saturation_refuses_before_iterator_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = cleanup_owner.CleanupOwner(max_obligations=1)
    monkeypatch.setattr(cleanup_owner._PROCESS_CLEANUP_OWNER, "owner", owner)  # noqa: SLF001
    source = _CountingIteratorSource()
    file = MultipartFile(
        name="file",
        filename="file.bin",
        content=source,
        content_type="application/octet-stream",
        content_length=None,
        replayable=False,
        async_source=False,
    )
    stream = MultipartStream(MultipartPayload(boundary="boundary", fields=(), files=(file,)))
    assert owner.snapshot()["reserved"] == 0
    held = owner.reserve(1)
    try:
        with pytest.raises(LifecycleError, match="upload cleanup capacity exhausted"):
            list(stream)
        stream.close()
        assert source.iteration_calls == 0
        assert source.close_calls == 0
    finally:
        held.release()

    assert owner.snapshot()["reserved"] == 0


def _factory_file(factory: object) -> MultipartFile:
    return MultipartFile(
        name="file",
        filename="file.bin",
        content=factory,
        content_type="application/octet-stream",
        content_length=None,
        replayable=True,
        async_source=False,
        source_factory=True,
    )


class _CountingIteratorSource:
    def __init__(self) -> None:
        self.iteration_calls = 0
        self.close_calls = 0

    def __iter__(self) -> Iterator[bytes]:
        self.iteration_calls += 1
        return iter((b"payload",))

    def close(self) -> None:
        self.close_calls += 1


def test_public_multipart_saturation_refuses_before_part_factory(
    monkeypatch: pytest.MonkeyPatch,
    sync_http_server: str,
) -> None:
    owner = cleanup_owner.CleanupOwner(max_obligations=2)
    monkeypatch.setattr(cleanup_owner._PROCESS_CLEANUP_OWNER, "owner", owner)  # noqa: SLF001
    factory_calls = Mock()

    def factory() -> SyncChunks:
        factory_calls()
        return SyncChunks((b"payload",))

    with foghttp.Client() as client, pytest.raises(LifecycleError, match="upload cleanup capacity exhausted"):
        client.post(sync_http_server, files={"file": ("payload.bin", factory)})

    factory_calls.assert_not_called()
    assert owner.snapshot()["reserved"] == 0


def test_sync_iterator_start_failure_retains_cleanup_until_worker_recovers(
    monkeypatch: pytest.MonkeyPatch,
    cold_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    iterator = _StartFailureIterator()
    start_error = RuntimeError("iterator worker did not start")
    original_start = threading.Thread.start
    monkeypatch.setattr(threading.Thread, "start", Mock(side_effect=start_error))

    with pytest.raises(RuntimeError) as error:
        SyncIteratorRunner(iterator)

    assert error.value is start_error
    assert iterator.close_calls == 0
    assert cold_cleanup_owner.snapshot()["reserved"] == 1
    completions = tuple(reservation.completion for reservation in cold_cleanup_owner.state.reservations)
    assert len(completions) == 1
    monkeypatch.setattr(threading.Thread, "start", original_start)
    cold_cleanup_owner.retry()
    assert iterator.closed.wait(1.0)
    assert iterator.close_calls == 1
    completions[0].result(timeout=1.0)
    assert cold_cleanup_owner.snapshot()["reserved"] == 0


class _StartFailureIterator:
    def __init__(self) -> None:
        self.closed = threading.Event()
        self.close_calls = 0

    def __iter__(self) -> "_StartFailureIterator":
        return self

    def __next__(self) -> bytes:
        raise StopIteration

    def close(self) -> None:
        self.close_calls += 1
        self.closed.set()
