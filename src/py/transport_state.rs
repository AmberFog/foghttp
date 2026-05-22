use crate::core::metrics::TransportStateSnapshot;
use crate::py::stats::RawOriginPressure;
use pyo3::prelude::*;

#[derive(Clone)]
#[pyclass(skip_from_py_object)]
pub struct RawTransportState {
    #[pyo3(get)]
    active_requests: usize,
    #[pyo3(get)]
    pending_requests: usize,
    #[pyo3(get)]
    peak_pending_requests: usize,
    #[pyo3(get)]
    pool_acquire_attempts: usize,
    #[pyo3(get)]
    pool_acquire_immediate: usize,
    #[pyo3(get)]
    pool_acquire_waited: usize,
    #[pyo3(get)]
    pool_acquire_timeouts: usize,
    #[pyo3(get)]
    pool_acquire_wait_time_total_ns: u64,
    #[pyo3(get)]
    pool_acquire_wait_time_max_ns: u64,
    #[pyo3(get)]
    pool_acquire_wait_time_last_ns: u64,
    #[pyo3(get)]
    response_body_reuse_eligible: usize,
    #[pyo3(get)]
    response_body_closed: usize,
    #[pyo3(get)]
    response_body_aborted: usize,
    #[pyo3(get)]
    buffered_response_bytes: usize,
    #[pyo3(get)]
    buffered_response_budget_rejections: usize,
    #[pyo3(get)]
    origins: Vec<RawOriginPressure>,
}

impl From<TransportStateSnapshot> for RawTransportState {
    fn from(snapshot: TransportStateSnapshot) -> Self {
        let metrics = snapshot.metrics;
        Self {
            active_requests: metrics.active_requests,
            pending_requests: metrics.pending_requests,
            peak_pending_requests: metrics.peak_pending_requests,
            pool_acquire_attempts: metrics.pool_acquire_attempts,
            pool_acquire_immediate: metrics.pool_acquire_immediate,
            pool_acquire_waited: metrics.pool_acquire_waited,
            pool_acquire_timeouts: metrics.pool_acquire_timeouts,
            pool_acquire_wait_time_total_ns: metrics.pool_acquire_wait_time_total_ns,
            pool_acquire_wait_time_max_ns: metrics.pool_acquire_wait_time_max_ns,
            pool_acquire_wait_time_last_ns: metrics.pool_acquire_wait_time_last_ns,
            response_body_reuse_eligible: metrics.response_body_reuse_eligible,
            response_body_closed: metrics.response_body_closed,
            response_body_aborted: metrics.response_body_aborted,
            buffered_response_bytes: metrics.buffered_response_bytes,
            buffered_response_budget_rejections: metrics.buffered_response_budget_rejections,
            origins: snapshot.origins.into_iter().map(Into::into).collect(),
        }
    }
}
