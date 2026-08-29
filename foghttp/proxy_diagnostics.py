__all__ = ("ProxyDiagnostics", "ProxyEndpointDiagnostics")

from typing import TypedDict


class ProxyEndpointDiagnostics(TypedDict):
    connection_attempts: int
    connections_opened: int
    connections_open_failed: int
    connections_closed: int
    active_connections: int
    tunnel_attempts: int
    tunnels_established: int
    tunnel_failures: int
    tunnel_auth_failures: int
    tunnel_timeouts: int
    tunnel_early_closes: int
    active_tunnels: int
    last_activity_at_ns: int


class ProxyDiagnostics(TypedDict):
    schema_version: int
    snapshot_sequence: int
    endpoints: dict[str, ProxyEndpointDiagnostics]
