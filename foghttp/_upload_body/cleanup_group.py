from __future__ import annotations

from abc import ABC, abstractmethod
from concurrent.futures import Future
import threading


class CleanupGroup(Future[None]):
    """Complete after all admitted parts finish, reporting the first error in part order."""

    def __init__(self, parts: tuple[Future[None], ...]) -> None:
        super().__init__()
        self.set_running_or_notify_cancel()
        self._parts = parts
        self._remaining = len(parts)
        self._lock = threading.Lock()
        for part in parts:
            part.add_done_callback(self._part_finished)
        if not parts:
            self.set_result(None)

    def _part_finished(self, _part: Future[None]) -> None:
        with self._lock:
            self._remaining -= 1
            if self._remaining:
                return
        for part in self._parts:
            error = part.exception()
            if error is not None:
                self.set_exception(error)
                return
        self.set_result(None)


class GroupedUploadSource(ABC):
    async_parts = False

    @abstractmethod
    def start_parts(self, *, on_loop: bool) -> CleanupGroup:
        """Submit the children after the outer iterator has closed."""

    async def start_async_parts(self) -> CleanupGroup:
        return self.start_parts(on_loop=True)
