use crate::core::metrics::MetricsSnapshot;
use pyo3::prelude::*;

#[pyclass]
pub struct RawStats {
    #[pyo3(get)]
    active_connections: usize,
    #[pyo3(get)]
    idle_connections: usize,
    #[pyo3(get)]
    pending_acquires: usize,
    #[pyo3(get)]
    total_requests: usize,
    #[pyo3(get)]
    failed_requests: usize,
    #[pyo3(get)]
    reused_connections: usize,
    #[pyo3(get)]
    opened_connections: usize,
    #[pyo3(get)]
    closed_connections: usize,
    #[pyo3(get)]
    pool_timeouts: usize,
}

impl From<MetricsSnapshot> for RawStats {
    fn from(snapshot: MetricsSnapshot) -> Self {
        Self {
            active_connections: snapshot.active_connections,
            idle_connections: snapshot.idle_connections,
            pending_acquires: snapshot.pending_acquires,
            total_requests: snapshot.total_requests,
            failed_requests: snapshot.failed_requests,
            reused_connections: snapshot.reused_connections,
            opened_connections: snapshot.opened_connections,
            closed_connections: snapshot.closed_connections,
            pool_timeouts: snapshot.pool_timeouts,
        }
    }
}
