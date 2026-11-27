import asyncio
from concurrent.futures import Future
from functools import partial
import threading
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from foghttp._upload_body.cleanup_owner import CleanupOwner

from .constants import COMPLETION_WATCHDOG
from .sources import AsyncCloseGate, SyncCloseGate


if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.mark.parametrize("admission", [False, True], ids=["retry", "reserve"])
def test_worker_interruption_leaves_only_the_previously_admitted_obligation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    admission: bool,
) -> None:
    owner = CleanupOwner(max_active=1, max_obligations=2)
    source = SyncCloseGate(blocked=False)
    with monkeypatch.context() as fault:
        fault.setattr(threading.Thread, "start", Mock(side_effect=RuntimeError("worker unavailable")))
        completion = owner.reserve(1).submit_sync(source.close)

    interrupt = KeyboardInterrupt()
    with monkeypatch.context() as fault:
        fault.setattr(threading.Thread, "start", Mock(side_effect=interrupt))
        attempt = partial(owner.reserve, 1) if admission else owner.retry
        with pytest.raises(KeyboardInterrupt) as caught:
            attempt()

    assert caught.value is interrupt
    assert owner.snapshot()["reserved"] == owner.snapshot()["pending"] == 1
    assert owner.snapshot()["workers"] == source.calls == 0
    owner.retry()
    completion.result(timeout=COMPLETION_WATCHDOG)
    assert source.calls == 1
    assert owner.snapshot()["reserved"] == 0


@pytest.mark.parametrize("callback_error", [None, GeneratorExit("later callback failure")], ids=["closed", "failed"])
def test_dependent_cleanup_reports_worker_interruption_after_closing(
    monkeypatch: pytest.MonkeyPatch,
    callback_error: BaseException | None,
) -> None:
    owner = CleanupOwner(max_active=1, max_obligations=1)
    source = SyncCloseGate(error=callback_error)
    predecessor: Future[None] = Future()
    notified = threading.Event()
    interrupt = KeyboardInterrupt()
    reservation = owner.reserve(1)
    completion = reservation.submit_sync(source.close, after=predecessor)
    predecessor.add_done_callback(lambda _done: notified.set())
    with monkeypatch.context() as fault:
        fault.setattr(threading.Thread, "start", Mock(side_effect=interrupt))
        predecessor.set_result(None)

    assert notified.is_set()
    assert completion.done() is False
    assert owner.snapshot()["pending"] == 1
    try:
        owner.retry()
        assert source.entered.wait(COMPLETION_WATCHDOG)
        assert completion.done() is False
        assert owner.snapshot()["reserved"] == 1
    finally:
        source.release.set()
    with pytest.raises(KeyboardInterrupt) as caught:
        completion.result(timeout=COMPLETION_WATCHDOG)
    assert caught.value is interrupt
    assert owner.snapshot()["reserved"] == 0
    assert source.calls == 1


async def test_idle_worker_runs_pending_close_when_an_additional_worker_cannot_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = CleanupOwner(max_active=2, max_obligations=2)
    active = AsyncCloseGate()
    pending = SyncCloseGate(blocked=False)
    parked = threading.Event()
    original_wait = owner.state.condition.wait

    def wait(timeout: float | None = None) -> bool:
        parked.set()
        return original_wait(timeout)

    monkeypatch.setattr(owner.state.condition, "wait", wait)
    first = owner.reserve(1).submit_async(active.aclose)
    try:
        await asyncio.wait_for(active.entered.wait(), COMPLETION_WATCHDOG)
        assert parked.wait(COMPLETION_WATCHDOG)
        with monkeypatch.context() as fault:
            failure = Mock(side_effect=RuntimeError("additional worker unavailable"))
            fault.setattr(threading.Thread, "start", failure)
            second = owner.reserve(1).submit_sync(pending.close)
            await asyncio.wait_for(asyncio.wrap_future(second), COMPLETION_WATCHDOG)
        failure.assert_called_once_with()
        assert pending.calls == 1
        assert first.done() is False
        assert owner.snapshot()["workers"] == 1
    finally:
        active.release.set()
        await asyncio.wait_for(asyncio.wrap_future(first), COMPLETION_WATCHDOG)
    assert active.calls == 1
    assert owner.snapshot()["reserved"] == 0


def test_interruption_during_inline_predecessor_callback_reaches_submitter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = CleanupOwner(max_active=1, max_obligations=1)
    source = SyncCloseGate(blocked=False)
    predecessor: Future[None] = Future()
    register = predecessor.add_done_callback

    def complete_before_registration(callback: "Callable[[Future[None]], object]") -> None:
        predecessor.set_result(None)
        register(callback)

    reservation = owner.reserve(1)
    interrupt = KeyboardInterrupt()
    with monkeypatch.context() as fault:
        fault.setattr(predecessor, "add_done_callback", complete_before_registration)
        fault.setattr(threading.Thread, "start", Mock(side_effect=interrupt))
        with pytest.raises(KeyboardInterrupt) as caught:
            reservation.submit_sync(source.close, after=predecessor)

    assert caught.value is interrupt
    assert owner.snapshot()["reserved"] == owner.snapshot()["pending"] == 1
    assert source.calls == 0
    owner.retry()
    reservation.completion.result(timeout=COMPLETION_WATCHDOG)
    assert source.calls == 1
    assert owner.snapshot()["reserved"] == 0


def test_worker_started_before_interruption_closes_its_source_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = CleanupOwner(max_active=1, max_obligations=1)
    source = SyncCloseGate()
    reservation = owner.reserve(1)
    interrupt = KeyboardInterrupt()
    original_start = threading.Thread.start

    def start_then_interrupt(worker: threading.Thread) -> None:
        original_start(worker)
        raise interrupt

    try:
        with monkeypatch.context() as fault:
            fault.setattr(threading.Thread, "start", start_then_interrupt)
            with pytest.raises(KeyboardInterrupt) as caught:
                reservation.submit_sync(source.close)
        assert caught.value is interrupt
        assert source.entered.wait(COMPLETION_WATCHDOG)
        assert owner.snapshot()["workers"] == owner.snapshot()["active"] == 1
        assert reservation.submit_sync(source.close) is reservation.completion
        assert reservation.completion.done() is False
    finally:
        source.release.set()
    reservation.completion.result(timeout=COMPLETION_WATCHDOG)
    assert source.calls == 1
    assert owner.snapshot()["reserved"] == 0
