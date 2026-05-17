__all__ = ("Timeouts",)

from dataclasses import dataclass

from ._validation.numeric import validate_non_negative_seconds


@dataclass(frozen=True, slots=True)
class Timeouts:
    connect: float = 2.0
    read: float = 10.0
    write: float = 10.0
    pool: float = 1.0
    total: float = 30.0

    def __post_init__(self) -> None:
        for name in ("connect", "read", "write", "pool", "total"):
            object.__setattr__(
                self,
                name,
                validate_non_negative_seconds(f"Timeouts.{name}", getattr(self, name)),
            )
