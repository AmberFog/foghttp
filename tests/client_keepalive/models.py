__all__ = ("KeepAliveSnapshot",)

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KeepAliveSnapshot:
    connection_count: int
    request_count: int
    requests_by_connection: dict[int, int]
