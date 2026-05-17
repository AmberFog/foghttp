__all__ = ("DEFAULT_MAX_RESPONSE_BODY_SIZE", "Limits")

from dataclasses import dataclass

from ._validation.numeric import (
    validate_non_negative_int,
    validate_non_negative_seconds,
    validate_optional_non_negative_int,
)


DEFAULT_MAX_RESPONSE_BODY_SIZE = 10 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Limits:
    max_active_requests: int = 100
    max_active_requests_per_origin: int | None = None
    max_pending_requests: int = 1000
    max_response_body_size: int | None = DEFAULT_MAX_RESPONSE_BODY_SIZE
    max_idle_connections_per_host: int = 20
    idle_timeout: float = 30.0
    keepalive: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_active_requests",
            validate_non_negative_int("Limits.max_active_requests", self.max_active_requests),
        )
        object.__setattr__(
            self,
            "max_active_requests_per_origin",
            validate_optional_non_negative_int(
                "Limits.max_active_requests_per_origin",
                self.max_active_requests_per_origin,
            ),
        )
        object.__setattr__(
            self,
            "max_pending_requests",
            validate_non_negative_int("Limits.max_pending_requests", self.max_pending_requests),
        )
        object.__setattr__(
            self,
            "max_response_body_size",
            validate_optional_non_negative_int(
                "Limits.max_response_body_size",
                self.max_response_body_size,
            ),
        )
        object.__setattr__(
            self,
            "max_idle_connections_per_host",
            validate_non_negative_int(
                "Limits.max_idle_connections_per_host",
                self.max_idle_connections_per_host,
            ),
        )
        object.__setattr__(
            self,
            "idle_timeout",
            validate_non_negative_seconds("Limits.idle_timeout", self.idle_timeout),
        )
