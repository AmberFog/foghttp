use crate::core::metrics::{OriginMetricsSnapshot, StatsSnapshot};
use pyo3::prelude::*;

#[derive(Clone)]
#[pyclass(skip_from_py_object)]
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
    response_body_reuse_eligible: usize,
    #[pyo3(get)]
    response_body_closed: usize,
    #[pyo3(get)]
    response_body_aborted: usize,
    #[pyo3(get)]
    active_connections: usize,
    #[pyo3(get)]
    idle_connections: usize,
    #[pyo3(get)]
    connections_opened: usize,
    #[pyo3(get)]
    connections_open_failed: usize,
    #[pyo3(get)]
    connections_closed: usize,
    #[pyo3(get)]
    connections_reused: usize,
    #[pyo3(get)]
    connections_aborted: usize,
    #[pyo3(get)]
    last_activity_at_ns: u64,
}

#[pyclass]
pub struct RawStats {
    #[pyo3(get)]
    schema_version: u64,
    #[pyo3(get)]
    snapshot_sequence: u64,
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
    response_body_reuse_eligible: usize,
    #[pyo3(get)]
    response_body_closed: usize,
    #[pyo3(get)]
    response_body_aborted: usize,
    #[pyo3(get)]
    active_connections: usize,
    #[pyo3(get)]
    idle_connections: usize,
    #[pyo3(get)]
    connections_opened: usize,
    #[pyo3(get)]
    connections_open_failed: usize,
    #[pyo3(get)]
    connections_closed: usize,
    #[pyo3(get)]
    connections_reused: usize,
    #[pyo3(get)]
    connections_aborted: usize,
    #[pyo3(get)]
    buffered_response_bytes: usize,
    #[pyo3(get)]
    buffered_response_budget_rejections: usize,
}

impl From<StatsSnapshot> for RawStats {
    fn from(snapshot: StatsSnapshot) -> Self {
        let metadata = snapshot.metadata;
        let metrics = snapshot.metrics;
        Self {
            schema_version: metadata.schema_version,
            snapshot_sequence: metadata.snapshot_sequence,
            active_requests: metrics.active_requests,
            pending_requests: metrics.pending_requests,
            peak_pending_requests: metrics.peak_pending_requests,
            total_requests: metrics.total_requests,
            failed_requests: metrics.failed_requests,
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
            active_connections: metrics.active_connections,
            idle_connections: metrics.idle_connections,
            connections_opened: metrics.connections_opened,
            connections_open_failed: metrics.connections_open_failed,
            connections_closed: metrics.connections_closed,
            connections_reused: metrics.connections_reused,
            connections_aborted: metrics.connections_aborted,
            buffered_response_bytes: metrics.buffered_response_bytes,
            buffered_response_budget_rejections: metrics.buffered_response_budget_rejections,
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
            response_body_reuse_eligible: snapshot.response_body_reuse_eligible,
            response_body_closed: snapshot.response_body_closed,
            response_body_aborted: snapshot.response_body_aborted,
            active_connections: snapshot.active_connections,
            idle_connections: snapshot.idle_connections,
            connections_opened: snapshot.connections_opened,
            connections_open_failed: snapshot.connections_open_failed,
            connections_closed: snapshot.connections_closed,
            connections_reused: snapshot.connections_reused,
            connections_aborted: snapshot.connections_aborted,
            last_activity_at_ns: snapshot.last_activity_at_ns,
        }
    }
}
