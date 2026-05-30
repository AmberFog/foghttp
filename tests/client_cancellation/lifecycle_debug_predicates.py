__all__ = (
    "has_cancelled_pending_waiter",
    "has_debug_request_count",
    "has_disabled_transport_pressure",
    "has_no_lifecycle_debug_leaks",
    "has_one_active_transport_request",
    "has_one_buffered_request",
    "has_one_pending_transport_request",
    "has_one_stream_request",
)

from collections.abc import Callable

import foghttp


def has_one_buffered_request(snapshot: foghttp.AsyncLifecycleDebugSnapshot) -> bool:
    return (
        snapshot.enabled
        and snapshot.active_request_count == 1
        and snapshot.active_requests[0].mode == "buffered"
        and snapshot.transport_active_requests == 1
    )


def has_one_stream_request(snapshot: foghttp.AsyncLifecycleDebugSnapshot) -> bool:
    return (
        snapshot.enabled
        and snapshot.active_request_count == 1
        and snapshot.active_requests[0].mode == "stream"
        and snapshot.transport_active_requests == 1
    )


def has_disabled_transport_pressure(snapshot: foghttp.AsyncLifecycleDebugSnapshot) -> bool:
    return not snapshot.enabled and snapshot.active_request_count == 0 and snapshot.transport_active_requests == 1


def has_no_lifecycle_debug_leaks(snapshot: foghttp.AsyncLifecycleDebugSnapshot) -> bool:
    return (
        snapshot.active_request_count == 0
        and snapshot.transport_active_requests == 0
        and snapshot.transport_pending_requests == 0
    )


def has_one_active_transport_request(snapshot: foghttp.AsyncLifecycleDebugSnapshot) -> bool:
    return snapshot.active_request_count == 1 and snapshot.transport_active_requests == 1


def has_one_pending_transport_request(snapshot: foghttp.AsyncLifecycleDebugSnapshot) -> bool:
    return snapshot.transport_active_requests == 1 and snapshot.transport_pending_requests == 1


def has_cancelled_pending_waiter(snapshot: foghttp.AsyncLifecycleDebugSnapshot) -> bool:
    return snapshot.transport_active_requests == 1 and snapshot.transport_pending_requests == 0


def has_debug_request_count(
    expected_request_count: int,
) -> Callable[[foghttp.AsyncLifecycleDebugSnapshot], bool]:
    def condition(snapshot: foghttp.AsyncLifecycleDebugSnapshot) -> bool:
        return (
            snapshot.active_request_count == expected_request_count
            and snapshot.transport_active_requests == expected_request_count
        )

    return condition
