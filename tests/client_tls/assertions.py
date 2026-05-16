__all__ = (
    "assert_recovered_after_tls_failure",
    "assert_tls_failure_stats",
)

import foghttp


def assert_tls_failure_stats(stats: foghttp.TransportStats) -> None:
    _assert_stat("total_requests", stats.total_requests, 1)
    _assert_stat("failed_requests", stats.failed_requests, 1)
    _assert_stat("active_requests", stats.active_requests, 0)
    _assert_stat("pending_requests", stats.pending_requests, 0)


def assert_recovered_after_tls_failure(stats: foghttp.TransportStats) -> None:
    _assert_stat("total_requests", stats.total_requests, 2)
    _assert_stat("failed_requests", stats.failed_requests, 1)
    _assert_stat("active_requests", stats.active_requests, 0)
    _assert_stat("pending_requests", stats.pending_requests, 0)


def _assert_stat(name: str, actual: int, expected: int) -> None:
    if actual != expected:
        msg = f"{name}: expected {expected}, got {actual}"
        raise AssertionError(msg)
