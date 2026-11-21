import threading
from typing import TYPE_CHECKING

from .constants import CALLBACK_WATCHDOG


if TYPE_CHECKING:
    import pytest

    from foghttp._upload_body.cleanup_execution import CleanupScheduler, CleanupWorkerStart


class WorkerStartFault:
    def __init__(self, scheduler: "CleanupScheduler", *, delay_first: bool = False) -> None:
        self.created: list[threading.Thread] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self._delay_first = delay_first
        self._real_start = threading.Thread.start
        self._original_work = scheduler.work

    def install(self, monkeypatch: "pytest.MonkeyPatch", scheduler: "CleanupScheduler") -> None:
        def start(thread: threading.Thread) -> None:
            self._start(thread)

        monkeypatch.setattr(threading.Thread, "start", start)
        if self._delay_first:
            monkeypatch.setattr(scheduler, "work", self.work)

    def work(self, permit: "CleanupWorkerStart") -> None:
        if threading.current_thread() is self.created[0]:
            self.entered.set()
            if not self.release.wait(CALLBACK_WATCHDOG):
                message = "delayed cleanup worker was not released"
                raise RuntimeError(message)
        self._original_work(permit)

    def _start(self, thread: threading.Thread) -> None:
        if thread.name != "foghttp-cleanup":
            self._real_start(thread)
            return
        self.created.append(thread)
        self._real_start(thread)
        if not self._delay_first or len(self.created) == 1:
            message = "synthetic failure after successful OS thread launch"
            raise RuntimeError(message)
