from __future__ import annotations

import asyncio
from collections import abc, deque
import dataclasses
from enum import Enum, auto
import os
import threading
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from concurrent.futures import Future
    from contextvars import Context

    from .cleanup_owner import CleanupReservation

from . import cleanup_group, cleanup_start, thread_bridge


class CleanupPhase(Enum):
    PENDING = auto()
    WAITING = auto()
    JOINING = auto()
    ACTIVE = auto()
    STALLED = auto()
    DONE = auto()


@dataclasses.dataclass(slots=True)
class CleanupState:
    pid: int
    max_active: int
    max_obligations: int
    condition: threading.Condition = dataclasses.field(default_factory=threading.Condition)
    reservations: set[CleanupReservation] = dataclasses.field(default_factory=set)
    pending: deque[CleanupJob] = dataclasses.field(default_factory=deque)
    reserved: int = 0
    active: int = 0
    workers: int = 0

    def ready(self) -> bool:
        return bool(self.pending) and self.active < self.max_active


@dataclasses.dataclass(slots=True)
class CleanupJob:
    reservation: CleanupReservation
    callback: abc.Callable[[], Any]
    context: Context
    loop: asyncio.AbstractEventLoop | None
    after: Future[None] | None
    scheduler: CleanupScheduler
    phase: CleanupPhase = CleanupPhase.PENDING
    prior_error: BaseException | None = None
    task: asyncio.Task[None] | None = None
    started: bool = False

    def run_sync(self) -> None:
        try:
            outcome = self.context.run(self.callback)
        except BaseException as caught:  # noqa: BLE001
            self.scheduler.finish(self, caught)
        else:
            _complete_job(self, outcome)

    def finish_group(self, completed: Future[None]) -> None:
        self.scheduler.finish(self, completed.exception())

    def dispatch_async(self) -> None:
        if self.loop is None:
            return
        try:
            self.loop.call_soon_threadsafe(self.start_async, context=self.context.copy())
        except RuntimeError:
            self.scheduler.stall(self)

    def start_async(self) -> None:
        if self.reservation.pid != os.getpid():
            return
        with self.scheduler.state.condition:
            if self.phase != CleanupPhase.ACTIVE or self.task is not None:
                return
        coroutine = self.run_async()
        try:
            self.task = asyncio.create_task(coroutine, context=self.context.copy())
        except Exception:  # noqa: BLE001
            return
        finally:
            if self.task is None:
                # A factory can register the task and then raise before returning it.
                registered = (task for task in asyncio.all_tasks() if task.get_coro() is coroutine)
                self.task = next(registered, None)
            if self.task is None:
                coroutine.close()
                self.scheduler.stall(self)
            else:
                self.task.add_done_callback(self.async_done)

    async def run_async(self) -> None:
        if self.task is None:
            # Eager factories can start cleanup inside a wrapper before returning its task.
            self.task = asyncio.current_task()
        self.started = True
        try:
            outcome = await self.callback()
        except BaseException as caught:  # noqa: BLE001
            self.scheduler.finish(self, caught)
        else:
            _complete_job(self, outcome)

    def async_done(self, task: asyncio.Task[None]) -> None:
        if self.reservation.pid != os.getpid():
            return
        with self.scheduler.state.condition:
            if task is not self.task or self.phase != CleanupPhase.ACTIVE:
                return
            if task.cancelled() and not self.started:
                self.task = None
                self.scheduler.stall(self)
                return
        try:
            error = task.exception()
        except asyncio.CancelledError as caught:
            error = caught
        self.scheduler.finish(self, error)

    def reconcile(self, *, retry_stalled: bool) -> None:
        with self.scheduler.state.condition:
            task = self.task
        if task is not None and task.done():
            self.async_done(task)
            return
        if self.loop is None:
            return
        if self.loop.is_closed():
            self.scheduler.stall(self)
        elif retry_stalled:
            self.scheduler.enqueue(self, expected=CleanupPhase.STALLED)


class CleanupScheduler:
    def __init__(self, state: CleanupState) -> None:
        self.state = state

    def enqueue(
        self,
        job: CleanupJob,
        _completion: Future[None] | None = None,
        *,
        expected: CleanupPhase = CleanupPhase.WAITING,
    ) -> None:
        if self.state.pid != os.getpid():
            return
        with self.state.condition:
            if job.phase != expected:
                return
            job.phase = CleanupPhase.PENDING
            self.state.pending.append(job)
            if _completion is None or cleanup_start.collecting_worker_interrupts():
                self.start_workers()
                return
            # A detached predecessor callback can run on another cleanup worker.
            with cleanup_start.collect_worker_interrupts() as errors:
                self.start_workers()
                job.prior_error = next(iter(errors), None)

    def start_workers(self) -> None:
        self.state.condition.notify_all()
        desired = min(self.state.max_active, len(self.state.pending) + self.state.active)
        while self.state.workers < desired:
            if not cleanup_start.CleanupWorkerStart().start(self):
                return

    def work(self, permit: cleanup_start.CleanupWorkerStart) -> None:
        if self.state.pid != os.getpid():
            return
        with self.state.condition:
            if not permit.counted:
                if self.state.workers >= self.state.max_active:
                    return
                self.state.workers += 1
                permit.counted = True
        while self.state.pid == os.getpid():
            _run_next_job(self.state)

    def finish(self, job: CleanupJob, error: BaseException | None) -> None:
        if self.state.pid != os.getpid():
            return
        with self.state.condition:
            if job.phase == CleanupPhase.DONE:
                return
            if job.phase == CleanupPhase.ACTIVE:
                self.state.active -= 1
            job.phase = CleanupPhase.DONE
            self.state.reservations.discard(job.reservation)
            self.state.reserved -= job.reservation.count
            job.reservation.count = 0
            self.state.condition.notify_all()
        if job.prior_error is not None:
            error = job.prior_error
        if error is None:
            job.reservation.completion.set_result(None)
        else:
            job.reservation.completion.set_exception(error)

    def stall(self, job: CleanupJob) -> None:
        if self.state.pid != os.getpid():
            return
        with self.state.condition:
            if job.phase == CleanupPhase.ACTIVE:
                self.state.active -= 1
                job.phase = CleanupPhase.STALLED
                self.state.condition.notify_all()

    def reconcile(self, *, retry_stalled: bool = False) -> None:
        with self.state.condition:
            jobs = tuple(reservation.job for reservation in self.state.reservations)
        for job in jobs:
            if job is not None:
                job.reconcile(retry_stalled=retry_stalled)


def _run_next_job(state: CleanupState) -> None:
    with state.condition:
        state.condition.wait_for(state.ready)
        job = state.pending.popleft()
        job.phase = CleanupPhase.ACTIVE
        state.active += 1
    if job.after is not None:
        # The predecessor is done. Read it on the worker before dispatching to the caller's loop.
        previous_error = thread_bridge.consume_future_exception(job.after)
        job.after = None
        if previous_error is not None:
            job.prior_error = previous_error
    if job.loop is None:
        job.run_sync()
    else:
        job.dispatch_async()


def _complete_job(job: CleanupJob, outcome: object) -> None:
    if isinstance(outcome, cleanup_group.CleanupGroup):
        if job.reservation.pid != os.getpid():
            return
        with job.scheduler.state.condition:
            job.phase = CleanupPhase.JOINING
            job.scheduler.state.active -= 1
            job.scheduler.state.condition.notify_all()
        outcome.add_done_callback(job.finish_group)
    else:
        job.scheduler.finish(job, None)
