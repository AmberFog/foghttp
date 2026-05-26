__all__ = ("DaemonThreadResult", "run_in_daemon_thread")

from collections.abc import Callable
from dataclasses import dataclass
from queue import Queue
import threading
from typing import Generic, TypeVar


ResultT = TypeVar("ResultT")


@dataclass(frozen=True, slots=True)
class DaemonThreadResult(Generic[ResultT]):
    _thread: threading.Thread
    _result_queue: Queue[ResultT | Exception]
    _finished: threading.Event

    def done(self) -> bool:
        return self._finished.is_set()

    def result(self, *, timeout: float) -> ResultT:
        if not self._finished.wait(timeout=timeout):
            msg = "daemon worker did not finish before timeout"
            raise AssertionError(msg)

        result = self._result_queue.get_nowait()
        self._thread.join(timeout=0)
        if isinstance(result, Exception):
            raise result
        return result


def run_in_daemon_thread(worker: Callable[[], ResultT]) -> DaemonThreadResult[ResultT]:
    result_queue: Queue[ResultT | Exception] = Queue(maxsize=1)
    finished = threading.Event()

    def run_worker() -> None:
        try:
            result_queue.put(worker())
        except Exception as exc:  # noqa: BLE001 - shuttle worker failures back to pytest.
            result_queue.put(exc)
        finally:
            finished.set()

    thread = threading.Thread(target=run_worker, daemon=True)
    thread.start()
    return DaemonThreadResult(thread, result_queue, finished)
