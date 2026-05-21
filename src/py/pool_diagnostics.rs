use crate::core::metrics::OriginPoolDiagnosticsSnapshot;
use crate::py::client::acquire::{blocking_reason_name, PoolDiagnosticsSnapshot};
use pyo3::prelude::*;

#[derive(Clone)]
#[pyclass(skip_from_py_object)]
pub struct RawOriginPoolDiagnostics {
    #[pyo3(get)]
    origin: String,
    #[pyo3(get)]
    active_requests: usize,
    #[pyo3(get)]
    pending_requests: usize,
    #[pyo3(get)]
    pool_acquire_timeouts: usize,
    #[pyo3(get)]
    oldest_pending_request_wait_ns: u64,
    #[pyo3(get)]
    blocked_by: String,
    #[pyo3(get)]
    last_activity_at_ns: u64,
}

#[derive(Clone)]
#[pyclass(skip_from_py_object)]
pub struct RawPoolDiagnostics {
    #[pyo3(get)]
    active_requests: usize,
    #[pyo3(get)]
    pending_requests: usize,
    #[pyo3(get)]
    pool_acquire_timeouts: usize,
    #[pyo3(get)]
    max_active_requests: usize,
    #[pyo3(get)]
    max_active_requests_per_origin: Option<usize>,
    #[pyo3(get)]
    max_pending_requests: usize,
    #[pyo3(get)]
    pending_queue_full: bool,
    #[pyo3(get)]
    oldest_pending_request_wait_ns: u64,
    #[pyo3(get)]
    blocked_by: String,
    #[pyo3(get)]
    origins: Vec<RawOriginPoolDiagnostics>,
}

impl From<OriginPoolDiagnosticsSnapshot> for RawOriginPoolDiagnostics {
    fn from(snapshot: OriginPoolDiagnosticsSnapshot) -> Self {
        Self {
            origin: snapshot.origin,
            active_requests: snapshot.active_requests,
            pending_requests: snapshot.pending_requests,
            pool_acquire_timeouts: snapshot.pool_acquire_timeouts,
            oldest_pending_request_wait_ns: snapshot.oldest_pending_request_wait_ns,
            blocked_by: blocking_reason_name(snapshot.blocked_by).to_owned(),
            last_activity_at_ns: snapshot.last_activity_at_ns,
        }
    }
}

impl From<PoolDiagnosticsSnapshot> for RawPoolDiagnostics {
    fn from(snapshot: PoolDiagnosticsSnapshot) -> Self {
        Self {
            active_requests: snapshot.active_requests,
            pending_requests: snapshot.pending_requests,
            pool_acquire_timeouts: snapshot.pool_acquire_timeouts,
            max_active_requests: snapshot.max_active_requests,
            max_active_requests_per_origin: snapshot.max_active_requests_per_origin,
            max_pending_requests: snapshot.max_pending_requests,
            pending_queue_full: snapshot.pending_queue_full,
            oldest_pending_request_wait_ns: snapshot.oldest_pending_request_wait_ns,
            blocked_by: blocking_reason_name(snapshot.blocked_by).to_owned(),
            origins: snapshot.origins.into_iter().map(Into::into).collect(),
        }
    }
}
