__all__ = ("Limits",)

from dataclasses import dataclass

from .messages import MAX_RESPONSE_BODY_SIZE_INVALID


@dataclass(frozen=True, slots=True)
class Limits:
    max_active_requests: int = 100
    max_active_requests_per_origin: int | None = None
    max_pending_requests: int = 1000
    max_response_body_size: int | None = None
    max_idle_connections_per_host: int = 20
    idle_timeout: float = 30.0
    keepalive: bool = True

    def __post_init__(self) -> None:
        if self.max_response_body_size is not None and self.max_response_body_size < 0:
            raise ValueError(MAX_RESPONSE_BODY_SIZE_INVALID)
