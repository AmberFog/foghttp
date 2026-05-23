__all__ = (
    "assert_connection_open_failed_stats",
    "assert_invalid_url_does_not_touch_transport",
    "assert_network_error_stats",
    "assert_recovered_stats",
)

import foghttp

from .constants import (
    EXPECTED_FAILED_REQUESTS,
    EXPECTED_REQUESTS_AFTER_FAILURE,
    EXPECTED_REQUESTS_AFTER_RECOVERY,
)


def assert_invalid_url_does_not_touch_transport(stats: foghttp.TransportStats) -> None:
    _assert_stat("total_requests", stats.total_requests, 0)
    _assert_stat("failed_requests", stats.failed_requests, 0)
    _assert_stat("active_requests", stats.active_requests, 0)
    _assert_stat("pending_requests", stats.pending_requests, 0)


def assert_network_error_stats(stats: foghttp.TransportStats) -> None:
    _assert_stat("total_requests", stats.total_requests, EXPECTED_REQUESTS_AFTER_FAILURE)
    _assert_stat("failed_requests", stats.failed_requests, EXPECTED_FAILED_REQUESTS)
    _assert_stat("active_requests", stats.active_requests, 0)
    _assert_stat("pending_requests", stats.pending_requests, 0)


def assert_connection_open_failed_stats(stats: foghttp.TransportStats) -> None:
    assert_network_error_stats(stats)
    _assert_stat("active_connections", stats.active_connections, 0)
    _assert_stat("idle_connections", stats.idle_connections, 0)
    _assert_stat("connections_opened", stats.connections_opened, 0)
    _assert_stat("connections_open_failed", stats.connections_open_failed, 1)
    _assert_stat("connections_closed", stats.connections_closed, 0)
    _assert_stat("connections_reused", stats.connections_reused, 0)
    _assert_stat("connections_aborted", stats.connections_aborted, 0)


def assert_recovered_stats(stats: foghttp.TransportStats) -> None:
    _assert_stat("total_requests", stats.total_requests, EXPECTED_REQUESTS_AFTER_RECOVERY)
    _assert_stat("failed_requests", stats.failed_requests, EXPECTED_FAILED_REQUESTS)
    _assert_stat("active_requests", stats.active_requests, 0)
    _assert_stat("pending_requests", stats.pending_requests, 0)


def _assert_stat(name: str, actual: int, expected: int) -> None:
    if actual != expected:
        msg = f"{name}: expected {expected}, got {actual}"
        raise AssertionError(msg)
