__all__ = ("FaultInjectionSnapshot",)

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FaultInjectionSnapshot:
    connection_count: int
    request_count: int
    requests_by_connection: dict[int, int]
    requests_by_path: dict[str, int]
    paths_by_connection: dict[int, tuple[str, ...]]
