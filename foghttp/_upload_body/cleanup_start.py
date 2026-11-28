from collections.abc import Iterator
from contextlib import contextmanager
import dataclasses
import os
import threading
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from .cleanup_execution import CleanupScheduler


class _StartInterrupts(threading.local):
    def __init__(self) -> None:
        self.stack: list[list[BaseException] | None] = []

    @property
    def current(self) -> list[BaseException] | None:
        return self.stack[-1] if self.stack else None

    def reset(self) -> None:
        for pending in self.stack:
            if pending is not None:
                pending.clear()
        self.stack = []


_INTERRUPTS = _StartInterrupts()
if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_INTERRUPTS.reset)


@contextmanager
def collect_worker_interrupts() -> Iterator[list[BaseException]]:
    stack = _INTERRUPTS.stack
    errors: list[BaseException] = []
    stack.append(errors)
    try:
        yield errors
    finally:
        stack.pop()


@contextmanager
def defer_worker_interrupts() -> Iterator[None]:
    """Finish registering owned sources before returning their caller's launch interruption."""
    if collecting_worker_interrupts():
        yield
        return
    with collect_worker_interrupts() as errors:
        yield
        if errors:
            raise errors[0]


@contextmanager
def independent_worker_interrupts() -> Iterator[None]:
    """Let reentrant user code receive its own worker startup interruptions."""
    stack = _INTERRUPTS.stack
    stack.append(None)
    try:
        yield
    finally:
        stack.pop()


def collecting_worker_interrupts() -> bool:
    return _INTERRUPTS.current is not None


def report_worker_interrupt(error: BaseException) -> None:
    errors = _INTERRUPTS.current
    if errors is None:
        raise error
    if not errors:
        errors.append(error)


@dataclasses.dataclass(slots=True)
class CleanupWorkerStart:
    counted: bool = True

    def start(self, scheduler: "CleanupScheduler") -> bool:
        worker = threading.Thread(target=scheduler.work, args=(self,), daemon=True, name="foghttp-cleanup")
        scheduler.state.workers += 1
        started = False
        try:
            worker.start()
            started = True
        except Exception:  # noqa: BLE001
            return False
        except BaseException as error:  # noqa: BLE001
            # The submitter receives the interrupt after registering the remaining owners.
            report_worker_interrupt(error)
        finally:
            if not started:
                scheduler.state.workers -= 1
                self.counted = False
        return started
