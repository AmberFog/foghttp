use crate::core::metrics::MetricsSnapshot;
use pyo3::prelude::*;

#[pyclass]
pub struct RawStats {
    #[pyo3(get)]
    active_requests: usize,
    #[pyo3(get)]
    pending_requests: usize,
    #[pyo3(get)]
    total_requests: usize,
    #[pyo3(get)]
    failed_requests: usize,
    #[pyo3(get)]
    pool_acquire_timeouts: usize,
    #[pyo3(get)]
    buffered_response_bytes: usize,
    #[pyo3(get)]
    buffered_response_budget_rejections: usize,
}

impl From<MetricsSnapshot> for RawStats {
    fn from(snapshot: MetricsSnapshot) -> Self {
        Self {
            active_requests: snapshot.active_requests,
            pending_requests: snapshot.pending_requests,
            total_requests: snapshot.total_requests,
            failed_requests: snapshot.failed_requests,
            pool_acquire_timeouts: snapshot.pool_acquire_timeouts,
            buffered_response_bytes: snapshot.buffered_response_bytes,
            buffered_response_budget_rejections: snapshot.buffered_response_budget_rejections,
        }
    }
}
