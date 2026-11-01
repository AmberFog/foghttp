from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Any

from .constants import COMPLETION_WATCHDOG


if TYPE_CHECKING:
    from collections.abc import Coroutine
    from contextvars import Context

    from foghttp._upload_body.cleanup_owner import CleanupOwner


class ReconcileRace:
    def __init__(self, owner: CleanupOwner) -> None:
        self.owner = owner
        self.loop = asyncio.get_running_loop()
        self.loop_thread = threading.get_ident()
        self.task_read = threading.Event()
        self.resume_read = threading.Event()
        self.finished = threading.Event()
        self.error: BaseException | None = None
        self.observation: dict[str, int] | None = None
        self.thread: threading.Thread | None = None

    def task_factory(
        self,
        _loop: asyncio.AbstractEventLoop,
        coroutine: Coroutine[Any, Any, None],
        *,
        context: Context | None = None,
    ) -> asyncio.Task[None]:
        task = _PausedDoneTask(coroutine, self, context=context)
        task.cancel()
        task.add_done_callback(self.start_observer)
        return task

    def start_observer(self, _task: asyncio.Task[None]) -> None:
        self.thread = threading.Thread(target=self.observe, daemon=True)
        self.thread.start()
        if not self.task_read.wait(COMPLETION_WATCHDOG):
            message = "concurrent reconciliation did not read the cancelled task before watchdog"
            raise RuntimeError(message)
        self.loop.call_soon(self.resume_read.set)

    def observe(self) -> None:
        try:
            self.observation = self.owner.snapshot()
        except BaseException as error:  # noqa: BLE001
            self.error = error
        finally:
            self.finished.set()


class _PausedDoneTask(asyncio.Task[None]):
    def __init__(
        self,
        coroutine: Coroutine[Any, Any, None],
        race: ReconcileRace,
        *,
        context: Context | None,
    ) -> None:
        super().__init__(coroutine, loop=race.loop, context=context)
        self._race = race

    def done(self) -> bool:
        completed = super().done()
        if completed and threading.get_ident() != self._race.loop_thread:
            self._race.task_read.set()
            if not self._race.resume_read.wait(COMPLETION_WATCHDOG):
                message = "concurrent task read was not released before watchdog"
                raise RuntimeError(message)
        return completed
