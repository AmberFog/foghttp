from typing import TYPE_CHECKING

from .._telemetry import SYNTHETIC_TELEMETRY_SNAPSHOT_SEQUENCE, TELEMETRY_SNAPSHOT_SCHEMA_VERSION
from ..proxy_diagnostics import ProxyDiagnostics, ProxyEndpointDiagnostics


if TYPE_CHECKING:
    from foghttp import _foghttp


def empty_proxy_diagnostics() -> ProxyDiagnostics:
    return {
        "schema_version": TELEMETRY_SNAPSHOT_SCHEMA_VERSION,
        "snapshot_sequence": SYNTHETIC_TELEMETRY_SNAPSHOT_SEQUENCE,
        "endpoints": {},
    }


def proxy_diagnostics_from_raw(raw: "_foghttp.RawProxyDiagnostics") -> ProxyDiagnostics:
    return {
        "schema_version": raw.schema_version,
        "snapshot_sequence": raw.snapshot_sequence,
        "endpoints": {endpoint.endpoint: _proxy_endpoint_diagnostics(endpoint) for endpoint in raw.endpoints},
    }


def _proxy_endpoint_diagnostics(
    raw: "_foghttp.RawProxyEndpointDiagnostics",
) -> ProxyEndpointDiagnostics:
    return {
        "connection_attempts": raw.connection_attempts,
        "connections_opened": raw.connections_opened,
        "connections_open_failed": raw.connections_open_failed,
        "connections_closed": raw.connections_closed,
        "active_connections": raw.active_connections,
        "tunnel_attempts": raw.tunnel_attempts,
        "tunnels_established": raw.tunnels_established,
        "tunnel_failures": raw.tunnel_failures,
        "tunnel_auth_failures": raw.tunnel_auth_failures,
        "tunnel_timeouts": raw.tunnel_timeouts,
        "tunnel_early_closes": raw.tunnel_early_closes,
        "active_tunnels": raw.active_tunnels,
        "last_activity_at_ns": raw.last_activity_at_ns,
    }
