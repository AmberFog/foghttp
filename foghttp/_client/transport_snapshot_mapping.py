from typing import TYPE_CHECKING, cast

from .._telemetry import SYNTHETIC_TELEMETRY_SNAPSHOT_SEQUENCE, TELEMETRY_SNAPSHOT_SCHEMA_VERSION
from ..transport_state import OriginPressureState, TransportState


if TYPE_CHECKING:
    from foghttp import _foghttp


_TRANSPORT_PRESSURE_FIELDS = (
    "active_requests",
    "pending_requests",
    "peak_pending_requests",
    "pool_acquire_attempts",
    "pool_acquire_immediate",
    "pool_acquire_waited",
    "pool_acquire_timeouts",
    "pool_acquire_wait_time_total_ns",
    "pool_acquire_wait_time_max_ns",
    "pool_acquire_wait_time_last_ns",
    "connection_acquire_attempts",
    "connection_acquire_immediate",
    "connection_acquire_waited",
    "connection_acquire_timeouts",
    "connection_acquire_wait_time_total_ns",
    "connection_acquire_wait_time_max_ns",
    "connection_acquire_wait_time_last_ns",
    "response_body_reuse_eligible",
    "response_body_closed",
    "response_body_aborted",
    "active_connections",
    "idle_connections",
    "connections_opened",
    "connections_open_failed",
    "connections_closed",
    "connections_reused",
    "connections_aborted",
    "idle_timeout_evictions",
)
_TRANSPORT_BUFFER_FIELDS = (
    "buffered_response_bytes",
    "buffered_response_budget_rejections",
)
_ORIGIN_PRESSURE_FIELDS = (
    *_TRANSPORT_PRESSURE_FIELDS,
    "last_activity_at_ns",
)
_TRANSPORT_STATE_FIELDS = (
    *_TRANSPORT_PRESSURE_FIELDS,
    *_TRANSPORT_BUFFER_FIELDS,
)


def empty_transport_state() -> TransportState:
    return cast(
        "TransportState",
        {
            "schema_version": TELEMETRY_SNAPSHOT_SCHEMA_VERSION,
            "snapshot_sequence": SYNTHETIC_TELEMETRY_SNAPSHOT_SEQUENCE,
            **dict.fromkeys(_TRANSPORT_STATE_FIELDS, 0),
            "origins": {},
        },
    )


def transport_state_from_raw(raw_state: "_foghttp.RawTransportState") -> TransportState:
    return cast(
        "TransportState",
        {
            "schema_version": raw_state.schema_version,
            "snapshot_sequence": raw_state.snapshot_sequence,
            **_snapshot_fields(raw_state, _TRANSPORT_STATE_FIELDS),
            "origins": {origin.origin: _origin_pressure_state(origin) for origin in raw_state.origins},
        },
    )


def _origin_pressure_state(origin: "_foghttp.RawOriginPressure") -> OriginPressureState:
    return cast("OriginPressureState", _snapshot_fields(origin, _ORIGIN_PRESSURE_FIELDS))


def _snapshot_fields(snapshot: object, fields: tuple[str, ...]) -> dict[str, int]:
    return {field_name: cast("int", getattr(snapshot, field_name)) for field_name in fields}
