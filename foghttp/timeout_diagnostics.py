__all__ = ("TimeoutDiagnostic", "TimeoutPhase")

from dataclasses import dataclass
from typing import Literal, TypeAlias


TimeoutPhase: TypeAlias = Literal[
    "pool_acquire",
    "connect",
    "response_headers",
    "response_body",
    "request_body",
    "total",
]


@dataclass(frozen=True, slots=True)
class TimeoutDiagnostic:
    phase: TimeoutPhase
    elapsed: float
    timeout: float
    origin: str
    redirect_hop: int
