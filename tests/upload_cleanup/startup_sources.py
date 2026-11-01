from collections.abc import Iterator
import threading


class StartupCountedSource(Iterator[bytes]):
    def __init__(self, content: bytes = b"rejected upload") -> None:
        self.content = iter((content,))
        self.iteration_entered = threading.Event()
        self.iteration_calls = 0
        self.next_calls = 0
        self.close_calls = 0

    def __iter__(self) -> "StartupCountedSource":
        self.iteration_calls += 1
        self.iteration_entered.set()
        return self

    def __next__(self) -> bytes:
        self.next_calls += 1
        return next(self.content)

    def close(self) -> None:
        self.close_calls += 1
