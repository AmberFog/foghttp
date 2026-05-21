__all__ = ("assert_timeout_error",)

import foghttp

from .state_assertions import assert_idle_stats


def assert_timeout_error(
    error: foghttp.TimeoutError,
    stats_after_error: foghttp.TransportStats,
    *,
    phase: str,
    origin: str,
    timeout: float | None,
) -> None:
    if error.phase != phase:
        msg = f"timeout phase: expected {phase}, got {error.phase}"
        raise AssertionError(msg)
    if error.diagnostic is None:
        msg = "timeout diagnostic is missing"
        raise AssertionError(msg)
    if error.diagnostic.origin != origin:
        msg = f"timeout origin: expected {origin}, got {error.diagnostic.origin}"
        raise AssertionError(msg)
    if error.diagnostic.timeout != timeout:
        msg = f"timeout value: expected {timeout}, got {error.diagnostic.timeout}"
        raise AssertionError(msg)

    assert_idle_stats(stats_after_error)
