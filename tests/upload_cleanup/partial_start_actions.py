from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Literal

from .constants import CALLBACK_WATCHDOG, COMPLETION_WATCHDOG
from .startup_cleanup import admitted_completions


if TYPE_CHECKING:
    from collections.abc import Callable
    from concurrent.futures import Future

    import pytest

    from foghttp._upload_body.cleanup_owner import CleanupOwner


WorkerKind = Literal["sync_upload", "daemon", "multipart"]


class PartialWorkerStart:
    """Fail one selected startup after physical entry.

    The optional event allows target entry before rejection within a finite
    watchdog. Correct startup gates prevent that event; its timeout bounds the
    fault schedule and does not assert performance.
    """

    def __init__(
        self,
        kind: WorkerKind,
        error: BaseException,
        owner: CleanupOwner | None = None,
        *,
        before_rejection: threading.Event | None = None,
    ) -> None:
        self.kind = kind
        self.error = error
        self.owner = owner
        self.before_rejection = before_rejection
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.worker: _RejectedStartupThread | None = None
        self.completions: tuple[Future[None], ...] = ()
        self._thread_type = threading.Thread

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def create_thread(*args: Any, **kwargs: Any) -> threading.Thread:
            target = kwargs.get("target")
            arguments = kwargs.get("args", ())
            if self.worker is None and self._matches(target, arguments):
                self.worker = _RejectedStartupThread(self, *args, **kwargs)
                return self.worker
            return self._thread_type(*args, **kwargs)

        monkeypatch.setattr(threading, "Thread", create_thread)

    def capture_admission(self) -> None:
        if self.owner is not None:
            self.completions = admitted_completions(self.owner)

    def finish(self) -> bool:
        self.release.set()
        if self.worker is None:
            return False
        self.worker.join(timeout=COMPLETION_WATCHDOG)
        stopped = not self.worker.is_alive()
        if not stopped and self.kind == "multipart":
            # Drain the old implementation after recording its missing stop marker.
            target = self.worker.target
            target.__self__._requests.put(None)  # noqa: SLF001
            self.worker.join(timeout=COMPLETION_WATCHDOG)
        return stopped

    def _matches(self, target: object, arguments: tuple[object, ...]) -> bool:
        name = getattr(target, "__qualname__", "")
        if self.kind == "sync_upload":
            callback = arguments[0] if arguments else None
            return getattr(callback, "__qualname__", "") == "_SyncStreamingUploadBody._feed_body"
        if self.kind == "multipart":
            return name == "SyncIteratorRunner._run"
        return name == "_run_daemon_worker"


class _RejectedStartupThread(threading.Thread):
    def __init__(self, fault: PartialWorkerStart, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fault = fault
        self.target: Callable[[], None] = kwargs["target"]

    def start(self) -> None:
        super().start()
        if not self.fault.entered.wait(COMPLETION_WATCHDOG):
            message = "selected worker did not physically enter before startup watchdog"
            raise RuntimeError(message)
        self.fault.capture_admission()
        if self.fault.before_rejection is not None:
            self.fault.release.set()
            self.fault.before_rejection.wait(COMPLETION_WATCHDOG)
        raise self.fault.error

    def run(self) -> None:
        self.fault.entered.set()
        try:
            if not self.fault.release.wait(CALLBACK_WATCHDOG):
                message = "rejected worker was not released before watchdog"
                raise RuntimeError(message)
            super().run()
        finally:
            self.fault.finished.set()
