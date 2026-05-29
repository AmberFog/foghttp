__all__ = (
    "AsyncLifecycleDebugConfig",
    "AsyncLifecycleDebugRequest",
    "AsyncLifecycleDebugRequestMode",
    "AsyncLifecycleDebugSnapshot",
)

from dataclasses import dataclass
from typing import Literal


AsyncLifecycleDebugRequestMode = Literal["buffered", "stream"]


@dataclass(frozen=True, slots=True)
class AsyncLifecycleDebugConfig:
    """Opt-in async lifecycle diagnostics.

    Strict mode is intended for tests and staging checks. It closes resources
    first, then raises if `aclose()` started while async work was still active.
    """

    strict: bool = False


@dataclass(frozen=True, slots=True)
class AsyncLifecycleDebugRequest:
    request_id: int
    mode: AsyncLifecycleDebugRequestMode
    method: str
    origin: str | None
    redacted_url: str
    started_at_ns: int
    age_ns: int


@dataclass(frozen=True, slots=True)
class AsyncLifecycleDebugSnapshot:
    enabled: bool
    strict: bool
    closed: bool
    active_requests: tuple[AsyncLifecycleDebugRequest, ...]
    transport_active_requests: int
    transport_pending_requests: int
    pool_acquire_timeouts: int

    @property
    def active_request_count(self) -> int:
        return len(self.active_requests)

    @property
    def has_leaks(self) -> bool:
        return (
            self.active_request_count > 0 or self.transport_active_requests > 0 or self.transport_pending_requests > 0
        )
