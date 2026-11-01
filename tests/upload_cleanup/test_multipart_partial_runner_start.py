import pytest

from foghttp._multipart.sync_runner import SyncIteratorRunner
from foghttp._upload_body.cleanup_owner import CleanupOwner

from .constants import COMPLETION_WATCHDOG
from .partial_start_actions import PartialWorkerStart
from .startup_sources import StartupCountedSource


def test_partial_multipart_runner_start_stops_physical_worker_and_closes_once(
    monkeypatch: pytest.MonkeyPatch,
    isolated_cleanup_owner: CleanupOwner,
) -> None:
    source = StartupCountedSource()
    failure = RuntimeError("multipart runner launched before startup failure")
    fault = PartialWorkerStart("multipart", failure, isolated_cleanup_owner)
    try:
        with monkeypatch.context() as startup:
            fault.install(startup)
            with pytest.raises(RuntimeError) as observed:
                SyncIteratorRunner(source)
        assert observed.value is failure
        assert fault.entered.is_set()
        assert len(fault.completions) == 1
        fault.completions[0].result(timeout=COMPLETION_WATCHDOG)
        assert source.close_calls == 1
    finally:
        stopped = fault.finish()

    assert stopped is True
    assert fault.finished.is_set()
    assert source.iteration_calls == 0
    assert source.next_calls == 0
    assert source.close_calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0
