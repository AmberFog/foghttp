mod atomic;
mod buffered;
mod counters;
mod lifecycle;
mod origin;
mod snapshots;
mod telemetry;

pub use buffered::BufferedByteReservationError;
pub use lifecycle::ResponseBodyLifecycleOutcome;
pub use origin::{
    OriginMetrics, OriginMetricsSnapshot, OriginPoolDiagnosticsSnapshot,
    PendingRequestBlockingReason,
};
pub use snapshots::{MetricsSnapshot, StatsSnapshot, TransportStateSnapshot};
pub use telemetry::TelemetrySnapshotMetadata;

use origin::OriginMetricsRegistry;
use std::sync::atomic::{AtomicU64, AtomicUsize};

pub const TELEMETRY_SNAPSHOT_SCHEMA_VERSION: u64 = 4;

#[derive(Default)]
pub struct Metrics {
    active_requests: AtomicUsize,
    pending_requests: AtomicUsize,
    peak_pending_requests: AtomicUsize,
    total_requests: AtomicUsize,
    failed_requests: AtomicUsize,
    pool_acquire_attempts: AtomicUsize,
    pool_acquire_immediate: AtomicUsize,
    pool_acquire_waited: AtomicUsize,
    pool_acquire_timeouts: AtomicUsize,
    pool_acquire_wait_time_total_ns: AtomicU64,
    pool_acquire_wait_time_max_ns: AtomicU64,
    pool_acquire_wait_time_last_ns: AtomicU64,
    connection_acquire_attempts: AtomicUsize,
    connection_acquire_immediate: AtomicUsize,
    connection_acquire_waited: AtomicUsize,
    connection_acquire_timeouts: AtomicUsize,
    connection_acquire_wait_time_total_ns: AtomicU64,
    connection_acquire_wait_time_max_ns: AtomicU64,
    connection_acquire_wait_time_last_ns: AtomicU64,
    response_body_reuse_eligible: AtomicUsize,
    response_body_closed: AtomicUsize,
    response_body_aborted: AtomicUsize,
    active_connections: AtomicUsize,
    idle_connections: AtomicUsize,
    connections_opened: AtomicUsize,
    connections_open_failed: AtomicUsize,
    connections_closed: AtomicUsize,
    connections_reused: AtomicUsize,
    connections_aborted: AtomicUsize,
    idle_timeout_evictions: AtomicUsize,
    buffered_response_bytes: AtomicUsize,
    buffered_response_budget_rejections: AtomicUsize,
    telemetry_snapshot_sequence: AtomicU64,
    origin_registry: OriginMetricsRegistry,
}

#[cfg(test)]
mod tests;
