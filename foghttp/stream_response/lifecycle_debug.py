__all__ = ("StreamResponseLifecycleDebugMixin",)

from collections.abc import Callable


class StreamResponseLifecycleDebugMixin:
    _lifecycle_debug_finish: Callable[[], None] | None
    _lifecycle_debug_finished: bool

    def _finish_lifecycle_debug(self) -> None:
        if self._lifecycle_debug_finish is None or self._lifecycle_debug_finished:
            return
        self._lifecycle_debug_finished = True
        self._lifecycle_debug_finish()
