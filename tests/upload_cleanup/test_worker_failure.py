import threading

import pytest

from foghttp._upload_body import cleanup, cleanup_owner

from .constants import COMPLETION_WATCHDOG
from .sources import SyncCloseGate


def test_worker_start_failure_retains_obligation_without_inline_or_fallback_close(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = SyncCloseGate(blocked=False)
    source_cleanup = cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(1))

    def fail_start(_thread: threading.Thread) -> None:
        message = "cleanup worker cannot start"
        raise RuntimeError(message)

    with monkeypatch.context() as failure:
        failure.setattr(threading.Thread, "start", fail_start)
        completion = source_cleanup.start_sync_cleanup()
        assert completion is not None
        snapshot = cleanup_owner.cleanup_snapshot()
        assert source.calls == 0
        assert completion.done() is False
        assert snapshot["reserved"] == 1
        assert snapshot["pending"] == 1
        assert snapshot["active"] == 0

    retried = source_cleanup.start_sync_cleanup()
    assert retried is completion
    completion.result(timeout=COMPLETION_WATCHDOG)
    assert source.calls == 1
    assert source.thread_id != threading.get_ident()
    assert cleanup_owner.cleanup_snapshot()["reserved"] == 0
