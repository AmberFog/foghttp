__all__ = (
    "assert_distinct_connection_payloads",
    "assert_distinct_connection_snapshot",
    "assert_reused_connection_payloads",
    "assert_reused_connection_snapshot",
)

from collections.abc import Mapping

from .constants import (
    CONNECTION_ID_KEY,
    EXPECTED_DISTINCT_CONNECTIONS,
    EXPECTED_FIRST_REQUEST_INDEX,
    EXPECTED_REUSED_CONNECTIONS,
    EXPECTED_SECOND_REQUEST_INDEX,
    EXPECTED_SEQUENTIAL_REQUESTS,
    REQUEST_INDEX_KEY,
)
from .models import KeepAliveSnapshot


def assert_reused_connection_payloads(
    first_payload: Mapping[str, object],
    second_payload: Mapping[str, object],
) -> None:
    first_connection_id = _payload_connection_id(first_payload)
    second_connection_id = _payload_connection_id(second_payload)
    if first_connection_id != second_connection_id:
        msg = f"expected reused connection, got {first_connection_id} and {second_connection_id}"
        raise AssertionError(msg)

    _assert_request_index(first_payload, EXPECTED_FIRST_REQUEST_INDEX)
    _assert_request_index(second_payload, EXPECTED_SECOND_REQUEST_INDEX)


def assert_distinct_connection_payloads(
    first_payload: Mapping[str, object],
    second_payload: Mapping[str, object],
) -> None:
    first_connection_id = _payload_connection_id(first_payload)
    second_connection_id = _payload_connection_id(second_payload)
    if first_connection_id == second_connection_id:
        msg = f"expected distinct connections, got {first_connection_id}"
        raise AssertionError(msg)

    _assert_request_index(first_payload, EXPECTED_FIRST_REQUEST_INDEX)
    _assert_request_index(second_payload, EXPECTED_FIRST_REQUEST_INDEX)


def assert_reused_connection_snapshot(snapshot: KeepAliveSnapshot) -> None:
    _assert_snapshot_counts(
        snapshot,
        expected_connection_count=EXPECTED_REUSED_CONNECTIONS,
        expected_request_count=EXPECTED_SEQUENTIAL_REQUESTS,
    )
    if sorted(snapshot.requests_by_connection.values()) != [EXPECTED_SEQUENTIAL_REQUESTS]:
        msg = f"expected one connection with two requests, got {snapshot.requests_by_connection}"
        raise AssertionError(msg)


def assert_distinct_connection_snapshot(snapshot: KeepAliveSnapshot) -> None:
    _assert_snapshot_counts(
        snapshot,
        expected_connection_count=EXPECTED_DISTINCT_CONNECTIONS,
        expected_request_count=EXPECTED_SEQUENTIAL_REQUESTS,
    )
    expected_requests_by_connection = [EXPECTED_FIRST_REQUEST_INDEX, EXPECTED_FIRST_REQUEST_INDEX]
    if sorted(snapshot.requests_by_connection.values()) != expected_requests_by_connection:
        msg = f"expected two single-request connections, got {snapshot.requests_by_connection}"
        raise AssertionError(msg)


def _payload_connection_id(payload: Mapping[str, object]) -> int:
    connection_id = payload[CONNECTION_ID_KEY]
    if not isinstance(connection_id, int):
        msg = f"{CONNECTION_ID_KEY} must be int"
        raise TypeError(msg)
    return connection_id


def _assert_request_index(payload: Mapping[str, object], expected: int) -> None:
    request_index = payload[REQUEST_INDEX_KEY]
    if request_index != expected:
        msg = f"expected request index {expected}, got {request_index}"
        raise AssertionError(msg)


def _assert_snapshot_counts(
    snapshot: KeepAliveSnapshot,
    *,
    expected_connection_count: int,
    expected_request_count: int,
) -> None:
    if snapshot.connection_count != expected_connection_count:
        msg = f"expected {expected_connection_count} connections, got {snapshot.connection_count}"
        raise AssertionError(msg)
    if snapshot.request_count != expected_request_count:
        msg = f"expected {expected_request_count} requests, got {snapshot.request_count}"
        raise AssertionError(msg)
