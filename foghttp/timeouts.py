from dataclasses import dataclass


__all__ = ("Timeouts",)


@dataclass(frozen=True, slots=True)
class Timeouts:
    connect: float = 2.0
    read: float = 10.0
    write: float = 10.0
    pool: float = 1.0
    total: float = 30.0
