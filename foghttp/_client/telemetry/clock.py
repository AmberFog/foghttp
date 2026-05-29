__all__ = ("elapsed_seconds_to_ns",)


_NANOSECONDS_PER_SECOND = 1_000_000_000


def elapsed_seconds_to_ns(elapsed: float) -> int:
    return round(elapsed * _NANOSECONDS_PER_SECOND)
