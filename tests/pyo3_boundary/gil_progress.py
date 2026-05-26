__all__ = ("assert_python_thread_progresses",)

import threading
import time


def assert_python_thread_progresses(*, duration: float) -> None:
    stop = threading.Event()
    progressed = threading.Event()
    progress_lock = threading.Lock()
    progress_count = 0

    def count_python_steps() -> None:
        nonlocal progress_count
        while not stop.is_set():
            with progress_lock:
                progress_count += 1
            progressed.set()
            time.sleep(0)

    thread = threading.Thread(target=count_python_steps, daemon=True)
    thread.start()
    try:
        if not progressed.wait(timeout=duration):
            msg = "Python thread made no progress while Rust operation was blocked"
            raise AssertionError(msg)
    finally:
        stop.set()
        thread.join(timeout=duration + 1.0)

    if thread.is_alive():
        msg = "Python progress thread did not stop"
        raise AssertionError(msg)

    with progress_lock:
        observed_progress = progress_count

    if observed_progress == 0:
        msg = "Python thread made no progress while Rust operation was blocked"
        raise AssertionError(msg)
