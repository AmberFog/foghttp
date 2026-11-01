import os
import threading
from unittest.mock import Mock

import pytest

from foghttp._upload_body import cleanup_owner
from foghttp._upload_body.cleanup_execution import CleanupWorkerStart

from .admission_actions import InheritedLock
from .constants import COMPLETION_WATCHDOG
from .sources import SyncCloseGate
from .worker_start_actions import WorkerStartFault


REQUESTS = 6
REPLACEMENT_AND_RETIRED = 2


def test_partial_start_failure_does_not_accumulate_persistent_cleanup_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = cleanup_owner.CleanupOwner(max_active=1, max_obligations=2)
    fault = WorkerStartFault(owner.scheduler)
    fault.install(monkeypatch, owner.scheduler)
    sources = [SyncCloseGate(blocked=False) for _index in range(REQUESTS)]

    for source in sources:
        completion = owner.reserve(1).submit_sync(source.close)
        completion.result(timeout=COMPLETION_WATCHDOG)
        assert owner.snapshot()["workers"] == 1
        assert owner.snapshot()["reserved"] == 0

    assert [source.calls for source in sources] == [1] * REQUESTS
    assert len(fault.created) == 1
    assert fault.created[0].is_alive() is True
    assert owner.snapshot()["active"] == 0


def test_delayed_partial_worker_retires_after_healthy_replacement_claims_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = cleanup_owner.CleanupOwner(max_active=1, max_obligations=2)
    fault = WorkerStartFault(owner.scheduler, delay_first=True)
    fault.install(monkeypatch, owner.scheduler)
    source = SyncCloseGate(blocked=False)
    reservation = owner.reserve(1)
    completion = reservation.submit_sync(source.close)
    try:
        assert fault.entered.wait(COMPLETION_WATCHDOG)
        assert source.calls == 0
        assert owner.snapshot()["workers"] == 0
        assert owner.snapshot()["pending"] == 1
        assert owner.snapshot()["reserved"] == 1
        repeated = reservation.submit_sync(source.close)
        assert repeated is completion
        completion.result(timeout=COMPLETION_WATCHDOG)
        assert source.calls == 1
        assert owner.snapshot()["workers"] == 1
        assert owner.snapshot()["reserved"] == 0
    finally:
        fault.release.set()
        fault.created[0].join(timeout=COMPLETION_WATCHDOG)

    assert len(fault.created) == REPLACEMENT_AND_RETIRED
    assert fault.created[0].is_alive() is False
    assert fault.created[1].is_alive() is True
    recovery = SyncCloseGate(blocked=False)
    owner.reserve(1).submit_sync(recovery.close).result(timeout=COMPLETION_WATCHDOG)
    assert recovery.calls == 1
    assert source.calls == 1
    assert owner.snapshot()["workers"] == 1
    assert owner.snapshot()["reserved"] == 0


def test_inherited_startup_permit_cannot_claim_parent_worker_slot_or_run_parent_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = cleanup_owner.CleanupOwner(max_active=1, max_obligations=1)
    source = SyncCloseGate(blocked=False)
    failure = Mock(side_effect=RuntimeError("worker startup rejected"))
    with monkeypatch.context() as failed_start:
        failed_start.setattr(threading.Thread, "start", failure)
        reservation = owner.reserve(1)
        completion = reservation.submit_sync(source.close)
    failure.assert_called_once_with()

    with monkeypatch.context() as inherited:
        inherited.setattr(owner.state, "pid", os.getpid() + 1)
        inherited.setattr(owner.state, "condition", InheritedLock())

        owner.scheduler.work(CleanupWorkerStart(counted=False))

        assert source.calls == 0
        assert completion.done() is False
        assert owner.state.workers == 0
        assert owner.state.reserved == 1

    owner.retry()
    completion.result(timeout=COMPLETION_WATCHDOG)
    assert source.calls == 1
    assert owner.snapshot()["workers"] == 1
    assert owner.snapshot()["reserved"] == 0
