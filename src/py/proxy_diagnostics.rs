use crate::core::metrics::{ProxyDiagnosticsSnapshot, ProxyEndpointMetricsSnapshot};
use pyo3::prelude::*;

#[derive(Clone)]
#[pyclass(skip_from_py_object)]
pub struct RawProxyEndpointDiagnostics {
    #[pyo3(get)]
    endpoint: String,
    #[pyo3(get)]
    connection_attempts: usize,
    #[pyo3(get)]
    connections_opened: usize,
    #[pyo3(get)]
    connections_open_failed: usize,
    #[pyo3(get)]
    connections_closed: usize,
    #[pyo3(get)]
    active_connections: usize,
    #[pyo3(get)]
    tunnel_attempts: usize,
    #[pyo3(get)]
    tunnels_established: usize,
    #[pyo3(get)]
    tunnel_failures: usize,
    #[pyo3(get)]
    tunnel_auth_failures: usize,
    #[pyo3(get)]
    tunnel_timeouts: usize,
    #[pyo3(get)]
    tunnel_early_closes: usize,
    #[pyo3(get)]
    active_tunnels: usize,
    #[pyo3(get)]
    last_activity_at_ns: u64,
}

#[derive(Clone)]
#[pyclass(skip_from_py_object)]
pub struct RawProxyDiagnostics {
    #[pyo3(get)]
    schema_version: u64,
    #[pyo3(get)]
    snapshot_sequence: u64,
    #[pyo3(get)]
    endpoints: Vec<RawProxyEndpointDiagnostics>,
}

impl From<ProxyEndpointMetricsSnapshot> for RawProxyEndpointDiagnostics {
    fn from(snapshot: ProxyEndpointMetricsSnapshot) -> Self {
        Self {
            endpoint: snapshot.endpoint,
            connection_attempts: snapshot.connection_attempts,
            connections_opened: snapshot.connections_opened,
            connections_open_failed: snapshot.connections_open_failed,
            connections_closed: snapshot.connections_closed,
            active_connections: snapshot.active_connections,
            tunnel_attempts: snapshot.tunnel_attempts,
            tunnels_established: snapshot.tunnels_established,
            tunnel_failures: snapshot.tunnel_failures,
            tunnel_auth_failures: snapshot.tunnel_auth_failures,
            tunnel_timeouts: snapshot.tunnel_timeouts,
            tunnel_early_closes: snapshot.tunnel_early_closes,
            active_tunnels: snapshot.active_tunnels,
            last_activity_at_ns: snapshot.last_activity_at_ns,
        }
    }
}

impl From<ProxyDiagnosticsSnapshot> for RawProxyDiagnostics {
    fn from(snapshot: ProxyDiagnosticsSnapshot) -> Self {
        Self {
            schema_version: snapshot.metadata.schema_version,
            snapshot_sequence: snapshot.metadata.snapshot_sequence,
            endpoints: snapshot.endpoints.into_iter().map(Into::into).collect(),
        }
    }
}
