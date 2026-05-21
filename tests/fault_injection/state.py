__all__ = ("FaultInjectionState",)

import threading
import time

from .models import FaultInjectionSnapshot


class FaultInjectionState:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._next_connection_id = 0
        self._requests_by_connection: dict[int, int] = {}
        self._requests_by_path: dict[str, int] = {}
        self._paths_by_connection: dict[int, list[str]] = {}

    def register_connection(self) -> int:
        with self._condition:
            self._next_connection_id += 1
            connection_id = self._next_connection_id
            self._requests_by_connection[connection_id] = 0
            self._paths_by_connection[connection_id] = []
            self._condition.notify_all()
            return connection_id

    def record_request(self, connection_id: int, path: str) -> int:
        with self._condition:
            request_index = self._requests_by_connection[connection_id] + 1
            self._requests_by_connection[connection_id] = request_index
            self._requests_by_path[path] = self._requests_by_path.get(path, 0) + 1
            self._paths_by_connection[connection_id].append(path)
            self._condition.notify_all()
            return request_index

    def wait_for_path_hits(self, path: str, expected: int, *, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._requests_by_path.get(path, 0) < expected:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    actual = self._requests_by_path.get(path, 0)
                    msg = f"{path}: expected at least {expected} requests, got {actual}"
                    raise AssertionError(msg)
                self._condition.wait(timeout=remaining)

    def snapshot(self) -> FaultInjectionSnapshot:
        with self._condition:
            requests_by_connection = dict(self._requests_by_connection)
            requests_by_path = dict(self._requests_by_path)
            paths_by_connection = {
                connection_id: tuple(paths) for connection_id, paths in self._paths_by_connection.items()
            }
        return FaultInjectionSnapshot(
            connection_count=len(requests_by_connection),
            request_count=sum(requests_by_connection.values()),
            requests_by_connection=requests_by_connection,
            requests_by_path=requests_by_path,
            paths_by_connection=paths_by_connection,
        )
