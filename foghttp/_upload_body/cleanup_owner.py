from __future__ import annotations

import asyncio
from concurrent.futures import Future
from contextvars import Context, copy_context
from functools import partial
import os
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

from ..errors import LifecycleError
from .cleanup_execution import CleanupJob, CleanupPhase, CleanupScheduler, CleanupState


_INVALID_LIMITS = "cleanup limits must be positive"
_INVALID_RESERVATION = "cleanup reservation must be positive"
_CAPACITY_EXHAUSTED = "upload cleanup capacity exhausted"
_FOREIGN_PROCESS = "upload cleanup belongs to another process"
_CANNOT_SPLIT = "cleanup reservation cannot be split"


class CleanupReservation:
    """An admitted obligation, independent of the request's loop or waiter."""

    def __init__(self, owner: CleanupOwner, count: int) -> None:
        self.owner = owner
        self.count = count
        self.pid = owner.pid
        self.completion: Future[None] = Future()
        self.completion.set_running_or_notify_cancel()
        self.job: CleanupJob | None = None
        self.start_error: BaseException | None = None

    def split(self, count: int = 1) -> CleanupReservation:
        return self.owner.split_reservation(self, count)

    def release(self) -> None:
        self.owner.release_reservation(self)

    def submit_sync(
        self,
        callback: Callable[[], Any],
        *,
        context: Context | None = None,
        after: Future[None] | None = None,
    ) -> Future[None]:
        return self.owner.submit(self, callback, context, None, after)

    def submit_async(
        self,
        callback: Callable[[], Coroutine[Any, Any, None]],
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        context: Context | None = None,
        after: Future[None] | None = None,
    ) -> Future[None]:
        selected_loop = asyncio.get_running_loop() if loop is None else loop
        return self.owner.submit(self, callback, context, selected_loop, after)


class CleanupOwner:
    """Finite process-wide admission and execution, separate from upload feeders."""

    def __init__(self, *, max_active: int = 8, max_obligations: int = 4096) -> None:
        if max_active < 1 or max_obligations < 1:
            raise ValueError(_INVALID_LIMITS)
        self.pid = os.getpid()
        self.state = CleanupState(self.pid, max_active, max_obligations)
        self.scheduler = CleanupScheduler(self.state)

    def reserve(self, count: int = 2) -> CleanupReservation:
        if self.pid != os.getpid():
            return get_cleanup_owner().reserve(count)
        if count < 1:
            raise ValueError(_INVALID_RESERVATION)
        self.scheduler.reconcile(retry_stalled=True)
        with self.state.condition:
            if self.state.reserved + count > self.state.max_obligations:
                raise LifecycleError(_CAPACITY_EXHAUSTED)
            reservation = CleanupReservation(self, count)
            self.state.reservations.add(reservation)
            self.state.reserved += count
            self.scheduler.start_workers()
            return reservation

    def snapshot(self) -> dict[str, int]:
        if self.pid != os.getpid():
            return get_cleanup_owner().snapshot()
        self.scheduler.reconcile()
        with self.state.condition:
            phases = tuple(
                reservation.job.phase for reservation in self.state.reservations if reservation.job is not None
            )
            return {
                "pid": self.pid,
                "limit": self.state.max_obligations,
                "active_limit": self.state.max_active,
                "reserved": self.state.reserved,
                "active": self.state.active,
                "pending": phases.count(CleanupPhase.PENDING) + phases.count(CleanupPhase.WAITING),
                "workers": self.state.workers,
                "stalled": phases.count(CleanupPhase.STALLED),
            }

    def retry(self) -> None:
        if self.pid != os.getpid():
            return
        self.scheduler.reconcile(retry_stalled=True)
        with self.state.condition:
            self.scheduler.start_workers()

    def split_reservation(self, reservation: CleanupReservation, count: int) -> CleanupReservation:
        if reservation.pid != os.getpid():
            raise LifecycleError(_FOREIGN_PROCESS)
        with self.state.condition:
            if count < 1 or count >= reservation.count or reservation.job is not None:
                raise ValueError(_CANNOT_SPLIT)
            reservation.count -= count
            child = CleanupReservation(self, count)
            self.state.reservations.add(child)
            return child

    def release_reservation(self, reservation: CleanupReservation) -> None:
        if reservation.pid != os.getpid():
            return
        with self.state.condition:
            if reservation.job is not None or reservation not in self.state.reservations:
                return
            self.state.reservations.remove(reservation)
            self.state.reserved -= reservation.count
            reservation.count = 0
        if not reservation.completion.done():
            reservation.completion.set_result(None)

    def submit(
        self,
        reservation: CleanupReservation,
        callback: Callable[[], Any],
        context: Context | None,
        loop: asyncio.AbstractEventLoop | None,
        after: Future[None] | None,
    ) -> Future[None]:
        if reservation.pid != os.getpid():
            completed: Future[None] = Future()
            completed.set_result(None)
            return completed
        self.scheduler.reconcile(retry_stalled=True)
        with self.state.condition:
            if reservation.job is not None:
                self.scheduler.start_workers()
                return reservation.completion
            if reservation not in self.state.reservations:
                return reservation.completion
            selected_context = copy_context() if context is None else context.copy()
            job = CleanupJob(reservation, callback, selected_context, loop, after, self.scheduler)
            reservation.job = job
            if after is not None and not after.done():
                job.phase = CleanupPhase.WAITING
            else:
                self.state.pending.append(job)
            reservation.start_error = self.scheduler.start_workers()
        if job.phase == CleanupPhase.WAITING and after is not None:
            after.add_done_callback(partial(self.scheduler.enqueue, job))
        return reservation.completion


class _ProcessCleanupOwner:
    def __init__(self) -> None:
        self.owner = CleanupOwner()

    def reset(self) -> None:
        self.owner = CleanupOwner()

    def get(self) -> CleanupOwner:
        if self.owner.pid != os.getpid():
            self.reset()
        return self.owner


_PROCESS_CLEANUP_OWNER = _ProcessCleanupOwner()

if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_PROCESS_CLEANUP_OWNER.reset)


def get_cleanup_owner() -> CleanupOwner:
    return _PROCESS_CLEANUP_OWNER.get()


def reserve_cleanup(count: int = 2) -> CleanupReservation:
    return get_cleanup_owner().reserve(count)


def cleanup_snapshot() -> dict[str, int]:
    return get_cleanup_owner().snapshot()
