__all__ = (
    "assert_client_recovered",
    "assert_healthy_connection_reused",
    "assert_idle_stats",
    "assert_network_failure_recovered",
    "assert_poisoned_connection_not_reused",
    "assert_request_count",
    "assert_request_count_between",
)

from collections.abc import Mapping

import foghttp

from .constants import (
    ABRUPT_DURING_BODY_PATH,
    CONNECTION_ID_KEY,
    EXPECTED_FAILED_REQUESTS_AFTER_FAILURE,
    EXPECTED_FAILED_REQUESTS_AFTER_RECOVERY,
    EXPECTED_FIRST_REQUEST_INDEX,
    EXPECTED_KEEPALIVE_REQUESTS,
    EXPECTED_REQUESTS_AFTER_FAILURE,
    EXPECTED_REQUESTS_AFTER_POISONED_RECOVERY,
    EXPECTED_REQUESTS_AFTER_RECOVERY,
    EXPECTED_SECOND_REQUEST_INDEX,
    HEALTHY_PATH,
    REQUEST_INDEX_KEY,
)
from .models import FaultInjectionSnapshot


def assert_idle_stats(stats: foghttp.TransportStats) -> None:
    _assert_stat("active_requests", stats.active_requests, 0)
    _assert_stat("pending_requests", stats.pending_requests, 0)
    _assert_stat("buffered_response_bytes", stats.buffered_response_bytes, 0)


def assert_client_recovered(
    stats_after_error: foghttp.TransportStats,
    final_stats: foghttp.TransportStats,
) -> None:
    assert_idle_stats(stats_after_error)
    assert_idle_stats(final_stats)
    _assert_stat("total_requests", stats_after_error.total_requests, EXPECTED_REQUESTS_AFTER_FAILURE)
    _assert_stat("failed_requests", stats_after_error.failed_requests, EXPECTED_FAILED_REQUESTS_AFTER_FAILURE)
    _assert_stat("total_requests", final_stats.total_requests, EXPECTED_REQUESTS_AFTER_RECOVERY)
    _assert_stat("failed_requests", final_stats.failed_requests, EXPECTED_FAILED_REQUESTS_AFTER_RECOVERY)


def assert_network_failure_recovered(
    stats_after_error: foghttp.TransportStats,
    final_stats: foghttp.TransportStats,
) -> None:
    assert_client_recovered(stats_after_error, final_stats)


def assert_healthy_connection_reused(
    first_payload: Mapping[str, object],
    second_payload: Mapping[str, object],
    snapshot: FaultInjectionSnapshot,
) -> None:
    first_connection_id = _payload_connection_id(first_payload)
    second_connection_id = _payload_connection_id(second_payload)
    if first_connection_id != second_connection_id:
        msg = f"expected healthy keep-alive reuse, got {first_connection_id} and {second_connection_id}"
        raise AssertionError(msg)

    _assert_payload_request_index(first_payload, EXPECTED_FIRST_REQUEST_INDEX)
    _assert_payload_request_index(second_payload, EXPECTED_SECOND_REQUEST_INDEX)
    _assert_stat("request_count", snapshot.request_count, EXPECTED_KEEPALIVE_REQUESTS)
    _assert_connection_paths(snapshot, first_connection_id, (HEALTHY_PATH, HEALTHY_PATH))
    _assert_connection_request_count(snapshot, first_connection_id, EXPECTED_KEEPALIVE_REQUESTS)


def assert_poisoned_connection_not_reused(
    first_payload: Mapping[str, object],
    recovery_payload: Mapping[str, object],
    snapshot: FaultInjectionSnapshot,
) -> None:
    first_connection_id = _payload_connection_id(first_payload)
    recovery_connection_id = _payload_connection_id(recovery_payload)
    poisoned_connection_id = _poisoned_connection_id(snapshot)
    if recovery_connection_id == poisoned_connection_id:
        msg = f"expected recovery request to avoid poisoned connection {poisoned_connection_id}"
        raise AssertionError(msg)

    _assert_payload_request_index(first_payload, EXPECTED_FIRST_REQUEST_INDEX)
    _assert_stat("request_count", snapshot.request_count, EXPECTED_REQUESTS_AFTER_POISONED_RECOVERY)
    _assert_connection_path_contains(snapshot, first_connection_id, HEALTHY_PATH)
    _assert_poisoned_connection_is_terminal(snapshot, poisoned_connection_id)
    _assert_connection_last_path(snapshot, recovery_connection_id, HEALTHY_PATH)


def assert_request_count(snapshot: FaultInjectionSnapshot, path: str, expected: int) -> None:
    actual = snapshot.requests_by_path.get(path, 0)
    _assert_stat(f"requests_by_path[{path}]", actual, expected)


def assert_request_count_between(
    snapshot: FaultInjectionSnapshot,
    path: str,
    *,
    minimum: int,
    maximum: int,
) -> None:
    actual = snapshot.requests_by_path.get(path, 0)
    if minimum <= actual <= maximum:
        return

    msg = f"requests_by_path[{path}]: expected between {minimum} and {maximum}, got {actual}"
    raise AssertionError(msg)


def _payload_connection_id(payload: Mapping[str, object]) -> int:
    connection_id = payload[CONNECTION_ID_KEY]
    if not isinstance(connection_id, int):
        msg = f"{CONNECTION_ID_KEY} must be int"
        raise TypeError(msg)
    return connection_id


def _assert_payload_request_index(payload: Mapping[str, object], expected: int) -> None:
    request_index = payload[REQUEST_INDEX_KEY]
    if request_index != expected:
        msg = f"{REQUEST_INDEX_KEY}: expected {expected}, got {request_index}"
        raise AssertionError(msg)


def _poisoned_connection_id(snapshot: FaultInjectionSnapshot) -> int:
    poisoned_connection_ids = [
        connection_id
        for connection_id, paths in snapshot.paths_by_connection.items()
        if ABRUPT_DURING_BODY_PATH in paths
    ]
    if len(poisoned_connection_ids) != 1:
        msg = f"expected one poisoned connection, got {poisoned_connection_ids}"
        raise AssertionError(msg)
    return poisoned_connection_ids[0]


def _assert_poisoned_connection_is_terminal(
    snapshot: FaultInjectionSnapshot,
    connection_id: int,
) -> None:
    paths = snapshot.paths_by_connection.get(connection_id)
    if paths is None:
        msg = f"connection {connection_id} is missing from snapshot"
        raise AssertionError(msg)
    if paths[-1] != ABRUPT_DURING_BODY_PATH:
        msg = f"connection {connection_id}: expected poison path to be terminal, got {paths}"
        raise AssertionError(msg)


def _assert_connection_path_contains(
    snapshot: FaultInjectionSnapshot,
    connection_id: int,
    path: str,
) -> None:
    paths = snapshot.paths_by_connection.get(connection_id, ())
    if path not in paths:
        msg = f"connection {connection_id}: expected path {path}, got {paths}"
        raise AssertionError(msg)


def _assert_connection_last_path(
    snapshot: FaultInjectionSnapshot,
    connection_id: int,
    expected: str,
) -> None:
    actual = snapshot.paths_by_connection.get(connection_id)
    if actual is None or actual[-1] != expected:
        msg = f"connection {connection_id}: expected last path {expected}, got {actual}"
        raise AssertionError(msg)


def _assert_connection_paths(
    snapshot: FaultInjectionSnapshot,
    connection_id: int,
    expected: tuple[str, ...],
) -> None:
    actual = snapshot.paths_by_connection.get(connection_id)
    if actual != expected:
        msg = f"connection {connection_id}: expected paths {expected}, got {actual}"
        raise AssertionError(msg)


def _assert_connection_request_count(
    snapshot: FaultInjectionSnapshot,
    connection_id: int,
    expected: int,
) -> None:
    actual = snapshot.requests_by_connection.get(connection_id)
    if actual != expected:
        msg = f"connection {connection_id}: expected {expected} requests, got {actual}"
        raise AssertionError(msg)


def _assert_stat(name: str, actual: int, expected: int) -> None:
    if actual != expected:
        msg = f"{name}: expected {expected}, got {actual}"
        raise AssertionError(msg)
