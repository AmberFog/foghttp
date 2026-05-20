use crate::core::metrics::{MetricsSnapshot, OriginMetricsSnapshot};
use pyo3::prelude::*;

#[pyclass]
pub struct RawOriginPressure {
    #[pyo3(get)]
    origin: String,
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
    last_activity_at_ns: u64,
}

#[pyclass]
pub struct RawStats {
    #[pyo3(get)]
    active_requests: usize,
    #[pyo3(get)]
    pending_requests: usize,
    #[pyo3(get)]
    peak_pending_requests: usize,
    #[pyo3(get)]
    total_requests: usize,
    #[pyo3(get)]
    failed_requests: usize,
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
    buffered_response_bytes: usize,
    #[pyo3(get)]
    buffered_response_budget_rejections: usize,
}

impl From<MetricsSnapshot> for RawStats {
    fn from(snapshot: MetricsSnapshot) -> Self {
        Self {
            active_requests: snapshot.active_requests,
            pending_requests: snapshot.pending_requests,
            peak_pending_requests: snapshot.peak_pending_requests,
            total_requests: snapshot.total_requests,
            failed_requests: snapshot.failed_requests,
            pool_acquire_attempts: snapshot.pool_acquire_attempts,
            pool_acquire_immediate: snapshot.pool_acquire_immediate,
            pool_acquire_waited: snapshot.pool_acquire_waited,
            pool_acquire_timeouts: snapshot.pool_acquire_timeouts,
            pool_acquire_wait_time_total_ns: snapshot.pool_acquire_wait_time_total_ns,
            pool_acquire_wait_time_max_ns: snapshot.pool_acquire_wait_time_max_ns,
            pool_acquire_wait_time_last_ns: snapshot.pool_acquire_wait_time_last_ns,
            buffered_response_bytes: snapshot.buffered_response_bytes,
            buffered_response_budget_rejections: snapshot.buffered_response_budget_rejections,
        }
    }
}

impl From<OriginMetricsSnapshot> for RawOriginPressure {
    fn from(snapshot: OriginMetricsSnapshot) -> Self {
        Self {
            origin: snapshot.origin,
            active_requests: snapshot.active_requests,
            pending_requests: snapshot.pending_requests,
            peak_pending_requests: snapshot.peak_pending_requests,
            pool_acquire_attempts: snapshot.pool_acquire_attempts,
            pool_acquire_immediate: snapshot.pool_acquire_immediate,
            pool_acquire_waited: snapshot.pool_acquire_waited,
            pool_acquire_timeouts: snapshot.pool_acquire_timeouts,
            pool_acquire_wait_time_total_ns: snapshot.pool_acquire_wait_time_total_ns,
            pool_acquire_wait_time_max_ns: snapshot.pool_acquire_wait_time_max_ns,
            pool_acquire_wait_time_last_ns: snapshot.pool_acquire_wait_time_last_ns,
            last_activity_at_ns: snapshot.last_activity_at_ns,
        }
    }
}
