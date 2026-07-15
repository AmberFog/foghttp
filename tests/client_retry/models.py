__all__ = ("RetryRequest", "RetryServerSnapshot")

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetryRequest:
    path: str
    method: str
    body: bytes
    connection_id: int


@dataclass(frozen=True, slots=True)
class RetryServerSnapshot:
    requests: tuple[RetryRequest, ...]

    def requests_for(self, path: str) -> tuple[RetryRequest, ...]:
        return tuple(request for request in self.requests if request.path == path)
