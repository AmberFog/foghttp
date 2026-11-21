from __future__ import annotations

import asyncio
from collections import deque
import dataclasses
from enum import Enum, auto
import os
import threading
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Callable
    from concurrent.futures import Future
    from contextvars import Context

    from .cleanup_owner import CleanupReservation


class CleanupPhase(Enum):
    PENDING = auto()
    WAITING = auto()
    ACTIVE = auto()
    STALLED = auto()
    DONE = auto()


@dataclasses.dataclass(slots=True)
class CleanupWorkerStart:
    counted: bool = True


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
    callback: Callable[[], Any]
    context: Context
    loop: asyncio.AbstractEventLoop | None
    after: Future[None] | None
    scheduler: CleanupScheduler
    phase: CleanupPhase = CleanupPhase.PENDING
    task: asyncio.Task[None] | None = None
    started: bool = False

    def run_sync(self) -> None:
        error: BaseException | None = None
        try:
            self.context.run(self.callback)
        except BaseException as caught:  # noqa: BLE001
            error = caught
        self.scheduler.finish(self, error)

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
        except BaseException:  # noqa: BLE001
            coroutine.close()
            self.scheduler.stall(self)
            return
        self.task.add_done_callback(self.async_done)

    async def run_async(self) -> None:
        self.started = True
        error: BaseException | None = None
        try:
            await self.callback()
        except BaseException as caught:  # noqa: BLE001
            error = caught
        self.scheduler.finish(self, error)

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
        except BaseException as caught:  # noqa: BLE001
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
            self.start_workers()

    def start_workers(self) -> BaseException | None:
        desired = min(self.state.max_active, len(self.state.pending) + self.state.active)
        while self.state.workers < desired:
            permit = CleanupWorkerStart()
            worker = threading.Thread(target=self.work, args=(permit,), daemon=True, name="foghttp-cleanup")
            self.state.workers += 1
            try:
                worker.start()
            except BaseException as error:  # noqa: BLE001
                self.state.workers -= 1
                permit.counted = False
                return error
        self.state.condition.notify_all()
        return None

    def work(self, permit: CleanupWorkerStart) -> None:
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
        if job.after is not None:
            try:
                previous_error = job.after.exception()
            except BaseException as caught:  # noqa: BLE001
                previous_error = caught
            error = previous_error or error
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
    if job.loop is None:
        job.run_sync()
    else:
        job.dispatch_async()
