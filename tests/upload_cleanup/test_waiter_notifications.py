import asyncio

import pytest

from foghttp._upload_body import cleanup_owner

from .notification_actions import ClosedLoopNotification, DeferredCleanupLoop


def test_loop_close_during_completion_notification_preserves_actual_cleanup_and_recovery(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("ERROR", logger="concurrent.futures")
    case = DeferredCleanupLoop(isolated_cleanup_owner)
    notification = ClosedLoopNotification()
    try:
        with monkeypatch.context() as closing_loop:
            closing_loop.setattr(case.loop, "call_soon_threadsafe", notification)
            barrier = case.complete_callback()

        assert notification.calls == 1
        assert barrier.calls == 1
        assert case.source.calls == 1
        assert case.source.finished.is_set()
        assert case.waiter.done() is False
        assert isolated_cleanup_owner.snapshot()["reserved"] == 0
        case.loop.close()

        asyncio.run(case.cleanup.aclose(bounded=False))

        assert case.source.calls == 1
        assert case.errors == []
        assert not any(record.name == "concurrent.futures" for record in caplog.records)
        assert isolated_cleanup_owner.snapshot()["reserved"] == 0
    finally:
        case.close()


def test_waiter_cancelled_after_completion_before_notification_does_not_set_result_twice(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    case = DeferredCleanupLoop(isolated_cleanup_owner)
    try:
        barrier = case.complete_callback()
        assert case.waiter.done() is False
        assert case.waiter.cancel() is True

        case.loop.run_until_complete(case.cleanup.aclose(bounded=False))

        assert case.waiter.cancelled() is True
        assert case.source.calls == 1
        assert case.source.finished.is_set()
        assert barrier.calls == 1
        assert case.errors == []
        assert isolated_cleanup_owner.snapshot()["reserved"] == 0
    finally:
        case.close()
