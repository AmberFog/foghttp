from __future__ import annotations

import asyncio
import os
import threading
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from concurrent.futures import Future

    from .cleanup import UploadSourceCleanup
    from .cleanup_owner import CleanupReservation

from ..errors import LifecycleError


_ITERATOR_NOT_RESERVED = "upload iterator cleanup was not reserved"
_ITERATOR_AFTER_CLOSE = "upload source is already closing"


class CleanupIteration:
    """Reserve future iterators and retain each known child's actual dependency."""

    def __init__(self, source: UploadSourceCleanup, reservation: CleanupReservation) -> None:
        self._source = source
        self._pid = reservation.pid
        self._spare = reservation.split(1) if reservation.count > 1 else None
        self._pending = False
        self._creating = False
        self._cleanup: UploadSourceCleanup | None = None
        self._after: Future[None] | None = None
        self.claimed = False
        self.lock = threading.Lock()

    def reserve(self, *, creating: bool = False) -> None:
        if self._pid != os.getpid():
            raise LifecycleError(_ITERATOR_AFTER_CLOSE)
        with self.lock:
            allowed = not self.claimed and self._spare is not None
            release_spare = not allowed and not self._creating
            if allowed:
                self._pending = True
                self._creating = self._creating or creating
        if not allowed:
            if release_spare:
                self.release()
            raise LifecycleError(_ITERATOR_AFTER_CLOSE)

    def release(self) -> None:
        if self._pid != os.getpid():
            return
        with self.lock:
            reservation = self._spare
            self._spare = None
            self._pending = False
            self._creating = False
        if reservation is not None:
            reservation.release()

    def track(self, iterator: object) -> UploadSourceCleanup:
        if self._pid != os.getpid():
            return self._source
        with self.lock:
            if self._cleanup is not None:
                return self._cleanup
            if self._spare is None:
                raise RuntimeError(_ITERATOR_NOT_RESERVED)
            cleanup = type(self._source)(iterator, context=self._source.context, reservation=self._spare)
            self._after = self._spare.completion
            self._spare = None
            self._pending = False
            self._creating = False
            self._cleanup = cleanup
            already_claimed = self.claimed
        if already_claimed:
            _start_cleanup(cleanup)
        return cleanup

    def claim(self, after: Future[None] | None) -> tuple[Future[None] | None, bool]:
        with self.lock:
            submit = not self.claimed
            self.claimed = True
            if after is not None:
                self._after = after
            cleanup = self._cleanup
            release_spare = not self._pending and cleanup is None
        if cleanup is not None:
            _start_cleanup(cleanup)
        elif release_spare:
            self.release()
        return self._after, submit


def _start_cleanup(cleanup: UploadSourceCleanup) -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        cleanup.start_sync_cleanup()
    else:
        cleanup.start_async_cleanup()
