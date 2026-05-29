__all__ = ("TelemetryConfig", "TelemetryHookErrorPolicy")

from dataclasses import dataclass
from typing import Literal

from .sinks import TelemetryEventSink


TelemetryHookErrorPolicy = Literal["raise", "warn", "ignore"]

_VALID_HOOK_ERROR_POLICIES = frozenset(("raise", "warn", "ignore"))
_INVALID_HOOK_ERROR_POLICY = "on_hook_error must be 'raise', 'warn', or 'ignore'"


@dataclass(frozen=True, slots=True)
class TelemetryConfig:
    sink: TelemetryEventSink | None = None
    on_hook_error: TelemetryHookErrorPolicy = "raise"

    def __post_init__(self) -> None:
        if self.on_hook_error not in _VALID_HOOK_ERROR_POLICIES:
            raise ValueError(_INVALID_HOOK_ERROR_POLICY)

    @property
    def enabled(self) -> bool:
        return self.sink is not None
