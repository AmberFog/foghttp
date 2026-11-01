from functools import partial
import os

import pytest

from foghttp._upload_body import cleanup, cleanup_owner
from foghttp.errors import LifecycleError

from .admission_actions import InheritedLock, complete_recovery_cleanup, record_async_attempt
from .constants import COMPLETION_WATCHDOG
from .sources import SyncCloseGate


SPLIT_UNITS = 2
RETAINED_AND_ACTIVE_UNITS = 3


@pytest.mark.parametrize("count", [0, -1, 4])
def test_invalid_reservation_preserves_active_work_and_recovers_capacity(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
    count: int,
) -> None:
    source = SyncCloseGate()
    completion = isolated_cleanup_owner.reserve(1).submit_sync(source.close)
    try:
        assert source.entered.wait(COMPLETION_WATCHDOG)
        error = LifecycleError if count > 0 else ValueError
        with pytest.raises(error):
            isolated_cleanup_owner.reserve(count)
        assert isolated_cleanup_owner.snapshot()["reserved"] == 1
        assert isolated_cleanup_owner.snapshot()["active"] == 1
        assert source.calls == 1
        assert source.finished.is_set() is False
    finally:
        source.release.set()
        completion.result(timeout=COMPLETION_WATCHDOG)

    recovery = complete_recovery_cleanup(isolated_cleanup_owner)
    assert recovery.calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0


@pytest.mark.parametrize(("max_active", "max_obligations"), [(0, 1), (1, 0), (-1, 1), (1, -1)])
def test_invalid_owner_limits_do_not_disturb_already_accepted_cleanup(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
    max_active: int,
    max_obligations: int,
) -> None:
    source = SyncCloseGate()
    completion = isolated_cleanup_owner.reserve(1).submit_sync(source.close)
    try:
        assert source.entered.wait(COMPLETION_WATCHDOG)
        with pytest.raises(ValueError, match="cleanup limits must be positive"):
            cleanup_owner.CleanupOwner(max_active=max_active, max_obligations=max_obligations)
        assert source.calls == 1
        assert isolated_cleanup_owner.snapshot()["reserved"] == 1
    finally:
        source.release.set()
        completion.result(timeout=COMPLETION_WATCHDOG)

    recovery = complete_recovery_cleanup(isolated_cleanup_owner)
    assert recovery.calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0


@pytest.mark.parametrize("count", [0, -1, 2, 3])
def test_invalid_split_preserves_admission_and_independent_active_provider(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
    count: int,
) -> None:
    retained = isolated_cleanup_owner.reserve(2)
    source = SyncCloseGate()
    completion = isolated_cleanup_owner.reserve(1).submit_sync(source.close)
    try:
        assert source.entered.wait(COMPLETION_WATCHDOG)
        with pytest.raises(ValueError, match="cleanup reservation cannot be split"):
            retained.split(count)
        assert retained.count == SPLIT_UNITS
        assert isolated_cleanup_owner.snapshot()["reserved"] == RETAINED_AND_ACTIVE_UNITS
        assert source.calls == 1
        retained.release()
        assert isolated_cleanup_owner.snapshot()["reserved"] == 1
    finally:
        retained.release()
        source.release.set()
        completion.result(timeout=COMPLETION_WATCHDOG)

    recovery = complete_recovery_cleanup(isolated_cleanup_owner)
    assert recovery.calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0


def test_duplicate_release_and_submission_cannot_erase_a_live_split_child() -> None:
    owner = cleanup_owner.CleanupOwner(max_active=1, max_obligations=2)
    parent = owner.reserve(2)
    child = parent.split(1)
    source = SyncCloseGate()
    completion = child.submit_sync(source.close)
    unexpected: list[str] = []
    try:
        assert source.entered.wait(COMPLETION_WATCHDOG)
        parent.release()
        parent.release()
        released_submission = parent.submit_sync(lambda: unexpected.append("released callback"))
        released_submission.result(timeout=COMPLETION_WATCHDOG)
        assert unexpected == []
        assert owner.snapshot()["reserved"] == 1
        with pytest.raises(LifecycleError, match="upload cleanup capacity exhausted"):
            owner.reserve(2)
        assert source.calls == 1
        assert source.finished.is_set() is False
    finally:
        source.release.set()
        completion.result(timeout=COMPLETION_WATCHDOG)

    recovery = complete_recovery_cleanup(owner)
    assert recovery.calls == 1
    assert owner.snapshot()["reserved"] == 0


def test_active_reservation_cannot_be_split_or_released_before_callback_returns() -> None:
    owner = cleanup_owner.CleanupOwner(max_active=1, max_obligations=2)
    reservation = owner.reserve(2)
    source = SyncCloseGate()
    completion = reservation.submit_sync(source.close)
    try:
        assert source.entered.wait(COMPLETION_WATCHDOG)
        with pytest.raises(ValueError, match="cleanup reservation cannot be split"):
            reservation.split(1)
        reservation.release()
        reservation.release()
        assert owner.snapshot()["reserved"] == SPLIT_UNITS
        assert owner.snapshot()["active"] == 1
        with pytest.raises(LifecycleError, match="upload cleanup capacity exhausted"):
            owner.reserve(1)
        assert completion.done() is False
    finally:
        source.release.set()
        completion.result(timeout=COMPLETION_WATCHDOG)

    assert source.calls == 1
    recovery = complete_recovery_cleanup(owner)
    assert recovery.calls == 1
    assert owner.snapshot()["reserved"] == 0


def test_repeated_submission_keeps_original_callback_and_actual_completion(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    reservation = isolated_cleanup_owner.reserve(1)
    source = SyncCloseGate()
    completion = reservation.submit_sync(source.close)
    unexpected: list[str] = []
    try:
        assert source.entered.wait(COMPLETION_WATCHDOG)
        repeated = reservation.submit_sync(lambda: unexpected.append("replacement callback"))
        assert repeated is completion
        assert isolated_cleanup_owner.snapshot()["reserved"] == 1
        assert unexpected == []
        assert source.calls == 1
    finally:
        source.release.set()
        completion.result(timeout=COMPLETION_WATCHDOG)

    finished = reservation.submit_sync(lambda: unexpected.append("completed callback"))
    assert finished is completion
    assert unexpected == []
    assert source.calls == 1
    recovery = complete_recovery_cleanup(isolated_cleanup_owner)
    assert recovery.calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0


async def test_inherited_cleanup_handles_refuse_work_before_touching_parent_locks(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_owner = isolated_cleanup_owner
    reservation = parent_owner.reserve(2)
    source = SyncCloseGate(blocked=False)
    source_cleanup = cleanup.UploadSourceCleanup(source, reservation=reservation)
    created: list[str] = []
    child_source = SyncCloseGate()
    child_completion = None
    delegated = None

    try:
        with monkeypatch.context() as inherited:
            inherited.setattr(parent_owner, "pid", os.getpid() + 1)
            inherited.setattr(reservation, "pid", os.getpid() + 1)
            inherited.setattr(source_cleanup.iteration, "_pid", os.getpid() + 1)
            inherited.setattr(parent_owner.state, "condition", InheritedLock())
            inherited.setattr(source_cleanup.iteration, "lock", InheritedLock())
            child_owner = cleanup_owner.get_cleanup_owner()
            assert child_owner is not parent_owner
            child_completion = child_owner.reserve(1).submit_sync(child_source.close)
            assert child_source.entered.wait(COMPLETION_WATCHDOG)
            delegated = parent_owner.reserve(1)
            assert parent_owner.snapshot()["reserved"] == SPLIT_UNITS
            parent_owner.retry()
            reservation.release()
            with pytest.raises(LifecycleError, match="another process"):
                reservation.split(1)
            assert reservation.submit_sync(source.close).done() is True
            assert reservation.submit_async(partial(record_async_attempt, created)).done() is True
            assert (
                source_cleanup.start_sync_cleanup(),
                source_cleanup.start_async_cleanup(),
                source_cleanup.consume_sync_error(),
            ) == (None, None, None)
            source_cleanup.close()
            await source_cleanup.aclose()
            source_cleanup.iteration.release()
            assert source_cleanup.iteration.track(iter(())) is source_cleanup
            with pytest.raises(LifecycleError, match="already closing"):
                source_cleanup.create_iterator(lambda: created.append("parent iterator"))
            assert source.calls == 0
            assert created == []
            assert child_owner.snapshot()["reserved"] == SPLIT_UNITS
    finally:
        if delegated is not None:
            delegated.release()
        child_source.release.set()
        if child_completion is not None:
            child_completion.result(timeout=COMPLETION_WATCHDOG)
        source_cleanup.close()

    assert source.calls == 1
    assert child_source.calls == 1
    assert parent_owner.snapshot()["reserved"] == 0
    assert child_owner.snapshot()["reserved"] == 0
