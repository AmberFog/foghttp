__all__ = ("assert_timeout_error",)

import foghttp
from tests.support.timeout_diagnostics import assert_timeout_diagnostic

from .state_assertions import assert_idle_stats


def assert_timeout_error(
    error: foghttp.TimeoutError,
    stats_after_error: foghttp.TransportStats,
    *,
    phase: str,
    origin: str,
    timeout: float,
) -> None:
    assert_timeout_diagnostic(error, phase=phase, origin=origin, timeout=timeout)
    assert_idle_stats(stats_after_error)
