__all__ = (
    "assert_recovered_after_tls_failure",
    "assert_tls_failure_stats",
    "assert_tls_handshake_timeout_stats",
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


def assert_tls_handshake_timeout_stats(stats: foghttp.TransportStats) -> None:
    assert_tls_failure_stats(stats)
    _assert_stat("active_connections", stats.active_connections, 0)
    _assert_stat("idle_connections", stats.idle_connections, 0)
    _assert_stat("connections_reused", stats.connections_reused, 0)
    _assert_stat("response_body_reuse_eligible", stats.response_body_reuse_eligible, 0)
    _assert_stat("response_body_closed", stats.response_body_closed, 0)
    _assert_stat("response_body_aborted", stats.response_body_aborted, 0)


def _assert_stat(name: str, actual: int, expected: int) -> None:
    if actual != expected:
        msg = f"{name}: expected {expected}, got {actual}"
        raise AssertionError(msg)
