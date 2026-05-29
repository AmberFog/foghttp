#[path = "metrics/atomic.rs"]
mod atomic;
#[path = "metrics/origin.rs"]
mod origin;

pub use origin::{
    OriginMetrics, OriginMetricsSnapshot, OriginPoolDiagnosticsSnapshot,
    PendingRequestBlockingReason,
};

use self::atomic::{
    duration_as_nanos, saturating_atomic_u64_add, saturating_atomic_usize_sub,
    update_atomic_u64_max, update_atomic_usize_max,
};
use self::origin::OriginMetricsRegistry;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

pub const TELEMETRY_SNAPSHOT_SCHEMA_VERSION: u64 = 1;

const TRANSPORT_STATE_SNAPSHOT_ATTEMPTS: usize = 8;

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
    buffered_response_bytes: AtomicUsize,
    buffered_response_budget_rejections: AtomicUsize,
    telemetry_snapshot_sequence: AtomicU64,
    origin_registry: OriginMetricsRegistry,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ResponseBodyLifecycleOutcome {
    ReuseEligible,
    Closed,
    Aborted,
}

#[derive(Debug, Eq, PartialEq)]
pub enum BufferedByteReservationError {
    CounterOverflow,
    LimitExceeded,
}

pub struct MetricsSnapshot {
    pub active_requests: usize,
    pub pending_requests: usize,
    pub peak_pending_requests: usize,
    pub total_requests: usize,
    pub failed_requests: usize,
    pub pool_acquire_attempts: usize,
    pub pool_acquire_immediate: usize,
    pub pool_acquire_waited: usize,
    pub pool_acquire_timeouts: usize,
    pub pool_acquire_wait_time_total_ns: u64,
    pub pool_acquire_wait_time_max_ns: u64,
    pub pool_acquire_wait_time_last_ns: u64,
    pub response_body_reuse_eligible: usize,
    pub response_body_closed: usize,
    pub response_body_aborted: usize,
    pub active_connections: usize,
    pub idle_connections: usize,
    pub connections_opened: usize,
    pub connections_open_failed: usize,
    pub connections_closed: usize,
    pub connections_reused: usize,
    pub connections_aborted: usize,
    pub buffered_response_bytes: usize,
    pub buffered_response_budget_rejections: usize,
}

pub struct StatsSnapshot {
    pub metadata: TelemetrySnapshotMetadata,
    pub metrics: MetricsSnapshot,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TelemetrySnapshotMetadata {
    pub schema_version: u64,
    pub snapshot_sequence: u64,
}

pub struct TransportStateSnapshot {
    pub metadata: TelemetrySnapshotMetadata,
    pub metrics: MetricsSnapshot,
    pub origins: Vec<OriginMetricsSnapshot>,
    origins_include_all_historical_pressure: bool,
}

impl Metrics {
    pub fn request_started(&self) {
        self.total_requests.fetch_add(1, Ordering::Relaxed);
    }

    pub fn request_finished(&self, failed: bool) {
        if failed {
            self.failed_requests.fetch_add(1, Ordering::Relaxed);
        }
    }

    pub fn active_request_started(&self) {
        self.active_requests.fetch_add(1, Ordering::Relaxed);
    }

    pub fn active_request_finished(&self) {
        self.active_requests.fetch_sub(1, Ordering::Relaxed);
    }

    pub fn pending_request_started(&self, max_pending_requests: usize) -> bool {
        let mut current = self.pending_requests.load(Ordering::Acquire);
        loop {
            if current >= max_pending_requests {
                return false;
            }

            match self.pending_requests.compare_exchange_weak(
                current,
                current + 1,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_previous) => {
                    update_atomic_usize_max(&self.peak_pending_requests, current + 1);
                    return true;
                }
                Err(actual) => current = actual,
            }
        }
    }

    pub fn pending_request_finished(&self) {
        self.pending_requests.fetch_sub(1, Ordering::AcqRel);
    }

    pub fn pool_acquire_timeout(&self) {
        self.pool_acquire_timeouts.fetch_add(1, Ordering::Relaxed);
    }

    pub fn pool_acquire_started(&self) {
        self.pool_acquire_attempts.fetch_add(1, Ordering::Relaxed);
    }

    pub fn pool_acquire_finished_immediately(&self) {
        self.pool_acquire_immediate.fetch_add(1, Ordering::Relaxed);
    }

    pub fn pool_acquire_waited(&self) {
        self.pool_acquire_waited.fetch_add(1, Ordering::Relaxed);
    }

    pub fn pool_acquire_wait_finished(&self, elapsed: Duration) {
        let elapsed_ns = duration_as_nanos(elapsed);

        saturating_atomic_u64_add(&self.pool_acquire_wait_time_total_ns, elapsed_ns);
        update_atomic_u64_max(&self.pool_acquire_wait_time_max_ns, elapsed_ns);
        self.pool_acquire_wait_time_last_ns
            .store(elapsed_ns, Ordering::Relaxed);
    }

    pub fn response_body_finished(&self, outcome: ResponseBodyLifecycleOutcome) {
        match outcome {
            ResponseBodyLifecycleOutcome::ReuseEligible => {
                self.response_body_reuse_eligible
                    .fetch_add(1, Ordering::Relaxed);
            }
            ResponseBodyLifecycleOutcome::Closed => {
                self.response_body_closed.fetch_add(1, Ordering::Relaxed);
            }
            ResponseBodyLifecycleOutcome::Aborted => {
                self.response_body_aborted.fetch_add(1, Ordering::Relaxed);
            }
        }
    }

    pub fn connection_opened(&self) {
        self.active_connections.fetch_add(1, Ordering::Relaxed);
        self.connections_opened.fetch_add(1, Ordering::Relaxed);
    }

    pub fn connection_open_failed(&self) {
        self.connections_open_failed.fetch_add(1, Ordering::Relaxed);
    }

    pub fn connection_closed(&self) {
        saturating_atomic_usize_sub(&self.active_connections, 1);
        self.connections_closed.fetch_add(1, Ordering::Relaxed);
    }

    pub fn connection_became_idle(&self) {
        self.idle_connections.fetch_add(1, Ordering::Relaxed);
    }

    pub fn connection_left_idle(&self) {
        saturating_atomic_usize_sub(&self.idle_connections, 1);
    }

    pub fn connection_reused(&self) {
        self.connections_reused.fetch_add(1, Ordering::Relaxed);
    }

    pub fn connection_aborted(&self) {
        self.connections_aborted.fetch_add(1, Ordering::Relaxed);
    }

    pub fn reserve_buffered_response_bytes(
        &self,
        byte_count: usize,
        max_buffered_response_bytes: Option<usize>,
    ) -> Result<(), BufferedByteReservationError> {
        if byte_count == 0 {
            return Ok(());
        }

        let mut current = self.buffered_response_bytes.load(Ordering::Acquire);
        loop {
            let Some(next) = current.checked_add(byte_count) else {
                return Err(BufferedByteReservationError::CounterOverflow);
            };
            if max_buffered_response_bytes.is_some_and(|limit| next > limit) {
                return Err(BufferedByteReservationError::LimitExceeded);
            }

            match self.buffered_response_bytes.compare_exchange_weak(
                current,
                next,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_previous) => return Ok(()),
                Err(actual) => current = actual,
            }
        }
    }

    pub fn release_buffered_response_bytes(&self, byte_count: usize) {
        if byte_count == 0 {
            return;
        }

        let mut current = self.buffered_response_bytes.load(Ordering::Acquire);
        loop {
            let Some(next) = current.checked_sub(byte_count) else {
                // Reservation ownership should make double-release impossible,
                // but Drop paths must never wrap the public counter.
                return;
            };

            match self.buffered_response_bytes.compare_exchange_weak(
                current,
                next,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_previous) => return,
                Err(actual) => current = actual,
            }
        }
    }

    pub fn buffered_response_budget_rejected(&self) {
        self.buffered_response_budget_rejections
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn origin_metrics(&self, origin: &str) -> Arc<OriginMetrics> {
        self.origin_registry.metrics_for(origin)
    }

    pub fn origin_snapshots(&self) -> Vec<OriginMetricsSnapshot> {
        self.origin_registry.snapshots()
    }

    pub fn origin_pool_diagnostics_snapshots(&self) -> Vec<OriginPoolDiagnosticsSnapshot> {
        self.origin_registry.pool_diagnostics_snapshots()
    }

    pub fn transport_state_snapshot(&self) -> TransportStateSnapshot {
        let metadata = self.next_telemetry_snapshot_metadata();
        let mut snapshot = self.transport_state_snapshot_once(metadata);
        for _attempt in 1..TRANSPORT_STATE_SNAPSHOT_ATTEMPTS {
            if snapshot.has_coherent_pressure() {
                return snapshot;
            }

            std::hint::spin_loop();
            snapshot = self.transport_state_snapshot_once(metadata);
        }
        snapshot
    }

    pub fn stats_snapshot(&self) -> StatsSnapshot {
        StatsSnapshot {
            metadata: self.next_telemetry_snapshot_metadata(),
            metrics: self.snapshot(),
        }
    }

    pub fn next_telemetry_snapshot_metadata(&self) -> TelemetrySnapshotMetadata {
        TelemetrySnapshotMetadata {
            schema_version: TELEMETRY_SNAPSHOT_SCHEMA_VERSION,
            snapshot_sequence: self.next_telemetry_snapshot_sequence(),
        }
    }

    fn next_telemetry_snapshot_sequence(&self) -> u64 {
        // This counter only orders observations; it does not publish metrics state.
        let mut current = self.telemetry_snapshot_sequence.load(Ordering::Relaxed);
        loop {
            let Some(next) = current.checked_add(1) else {
                return u64::MAX;
            };

            match self.telemetry_snapshot_sequence.compare_exchange_weak(
                current,
                next,
                Ordering::Relaxed,
                Ordering::Relaxed,
            ) {
                Ok(_previous) => return next,
                Err(actual) => current = actual,
            }
        }
    }

    fn transport_state_snapshot_once(
        &self,
        metadata: TelemetrySnapshotMetadata,
    ) -> TransportStateSnapshot {
        TransportStateSnapshot {
            metadata,
            metrics: self.snapshot(),
            origins: self.origin_snapshots(),
            origins_include_all_historical_pressure: self
                .origin_registry
                .snapshots_include_all_historical_origins(),
        }
    }

    pub fn snapshot(&self) -> MetricsSnapshot {
        MetricsSnapshot {
            active_requests: self.active_requests.load(Ordering::Relaxed),
            pending_requests: self.pending_requests.load(Ordering::Acquire),
            peak_pending_requests: self.peak_pending_requests.load(Ordering::Relaxed),
            total_requests: self.total_requests.load(Ordering::Relaxed),
            failed_requests: self.failed_requests.load(Ordering::Relaxed),
            pool_acquire_attempts: self.pool_acquire_attempts.load(Ordering::Relaxed),
            pool_acquire_immediate: self.pool_acquire_immediate.load(Ordering::Relaxed),
            pool_acquire_waited: self.pool_acquire_waited.load(Ordering::Relaxed),
            pool_acquire_timeouts: self.pool_acquire_timeouts.load(Ordering::Relaxed),
            pool_acquire_wait_time_total_ns: self
                .pool_acquire_wait_time_total_ns
                .load(Ordering::Relaxed),
            pool_acquire_wait_time_max_ns: self
                .pool_acquire_wait_time_max_ns
                .load(Ordering::Relaxed),
            pool_acquire_wait_time_last_ns: self
                .pool_acquire_wait_time_last_ns
                .load(Ordering::Relaxed),
            response_body_reuse_eligible: self.response_body_reuse_eligible.load(Ordering::Relaxed),
            response_body_closed: self.response_body_closed.load(Ordering::Relaxed),
            response_body_aborted: self.response_body_aborted.load(Ordering::Relaxed),
            active_connections: self.active_connections.load(Ordering::Relaxed),
            idle_connections: self.idle_connections.load(Ordering::Relaxed),
            connections_opened: self.connections_opened.load(Ordering::Relaxed),
            connections_open_failed: self.connections_open_failed.load(Ordering::Relaxed),
            connections_closed: self.connections_closed.load(Ordering::Relaxed),
            connections_reused: self.connections_reused.load(Ordering::Relaxed),
            connections_aborted: self.connections_aborted.load(Ordering::Relaxed),
            buffered_response_bytes: self.buffered_response_bytes.load(Ordering::Acquire),
            buffered_response_budget_rejections: self
                .buffered_response_budget_rejections
                .load(Ordering::Relaxed),
        }
    }
}

impl TransportStateSnapshot {
    fn has_coherent_pressure(&self) -> bool {
        let totals = OriginPressureTotals::from_origins(&self.origins);

        self.has_coherent_current_pressure(&totals)
            // Historical acquire counters can only be compared while the
            // per-origin registry still contains all origins ever observed.
            && (!self.origins_include_all_historical_pressure
                || self.has_coherent_historical_transport_counters(&totals))
    }

    fn has_coherent_current_pressure(&self, totals: &OriginPressureTotals) -> bool {
        self.metrics.active_requests == totals.active_requests
            && self.metrics.pending_requests == totals.pending_requests
            && self.metrics.active_connections == totals.active_connections
            && self.metrics.idle_connections == totals.idle_connections
    }

    fn has_coherent_historical_transport_counters(&self, totals: &OriginPressureTotals) -> bool {
        self.metrics.pool_acquire_attempts == totals.pool_acquire_attempts
            && self.metrics.pool_acquire_immediate == totals.pool_acquire_immediate
            && self.metrics.pool_acquire_waited == totals.pool_acquire_waited
            && self.metrics.pool_acquire_timeouts == totals.pool_acquire_timeouts
            && self.metrics.pool_acquire_wait_time_total_ns
                == totals.pool_acquire_wait_time_total_ns
            && self.metrics.pool_acquire_wait_time_max_ns == totals.pool_acquire_wait_time_max_ns
            && self.metrics.response_body_reuse_eligible == totals.response_body_reuse_eligible
            && self.metrics.response_body_closed == totals.response_body_closed
            && self.metrics.response_body_aborted == totals.response_body_aborted
            && self.metrics.connections_opened == totals.connections_opened
            && self.metrics.connections_open_failed == totals.connections_open_failed
            && self.metrics.connections_closed == totals.connections_closed
            && self.metrics.connections_reused == totals.connections_reused
            && self.metrics.connections_aborted == totals.connections_aborted
    }
}

#[derive(Default)]
struct OriginPressureTotals {
    active_requests: usize,
    pending_requests: usize,
    active_connections: usize,
    idle_connections: usize,
    pool_acquire_attempts: usize,
    pool_acquire_immediate: usize,
    pool_acquire_waited: usize,
    pool_acquire_timeouts: usize,
    pool_acquire_wait_time_total_ns: u64,
    pool_acquire_wait_time_max_ns: u64,
    response_body_reuse_eligible: usize,
    response_body_closed: usize,
    response_body_aborted: usize,
    connections_opened: usize,
    connections_open_failed: usize,
    connections_closed: usize,
    connections_reused: usize,
    connections_aborted: usize,
}

impl OriginPressureTotals {
    fn from_origins(origins: &[OriginMetricsSnapshot]) -> Self {
        origins.iter().fold(Self::default(), |mut totals, origin| {
            totals.active_requests = totals
                .active_requests
                .saturating_add(origin.active_requests);
            totals.pending_requests = totals
                .pending_requests
                .saturating_add(origin.pending_requests);
            totals.active_connections = totals
                .active_connections
                .saturating_add(origin.active_connections);
            totals.idle_connections = totals
                .idle_connections
                .saturating_add(origin.idle_connections);
            totals.pool_acquire_attempts = totals
                .pool_acquire_attempts
                .saturating_add(origin.pool_acquire_attempts);
            totals.pool_acquire_immediate = totals
                .pool_acquire_immediate
                .saturating_add(origin.pool_acquire_immediate);
            totals.pool_acquire_waited = totals
                .pool_acquire_waited
                .saturating_add(origin.pool_acquire_waited);
            totals.pool_acquire_timeouts = totals
                .pool_acquire_timeouts
                .saturating_add(origin.pool_acquire_timeouts);
            totals.pool_acquire_wait_time_total_ns = totals
                .pool_acquire_wait_time_total_ns
                .saturating_add(origin.pool_acquire_wait_time_total_ns);
            totals.pool_acquire_wait_time_max_ns = totals
                .pool_acquire_wait_time_max_ns
                .max(origin.pool_acquire_wait_time_max_ns);
            totals.response_body_reuse_eligible = totals
                .response_body_reuse_eligible
                .saturating_add(origin.response_body_reuse_eligible);
            totals.response_body_closed = totals
                .response_body_closed
                .saturating_add(origin.response_body_closed);
            totals.response_body_aborted = totals
                .response_body_aborted
                .saturating_add(origin.response_body_aborted);
            totals.connections_opened = totals
                .connections_opened
                .saturating_add(origin.connections_opened);
            totals.connections_open_failed = totals
                .connections_open_failed
                .saturating_add(origin.connections_open_failed);
            totals.connections_closed = totals
                .connections_closed
                .saturating_add(origin.connections_closed);
            totals.connections_reused = totals
                .connections_reused
                .saturating_add(origin.connections_reused);
            totals.connections_aborted = totals
                .connections_aborted
                .saturating_add(origin.connections_aborted);
            totals
        })
    }
}

#[cfg(test)]
mod tests {
    use super::{
        BufferedByteReservationError, Metrics, TelemetrySnapshotMetadata, TransportStateSnapshot,
        TELEMETRY_SNAPSHOT_SCHEMA_VERSION,
    };
    use std::sync::atomic::Ordering;
    use std::sync::{Arc, Barrier};
    use std::thread;
    use std::time::Duration;

    const CONCURRENT_SNAPSHOT_COUNT: usize = 32;

    #[test]
    fn buffered_response_reservation_rejects_without_changing_reserved_bytes() {
        let metrics = Metrics::default();

        assert_eq!(metrics.reserve_buffered_response_bytes(8, Some(8)), Ok(()));
        assert_eq!(
            metrics.reserve_buffered_response_bytes(1, Some(8)),
            Err(BufferedByteReservationError::LimitExceeded)
        );

        assert_eq!(metrics.snapshot().buffered_response_bytes, 8);
    }

    #[test]
    fn buffered_response_release_does_not_underflow_reserved_bytes() {
        let metrics = Metrics::default();

        metrics.release_buffered_response_bytes(8);

        assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
    }

    #[test]
    fn acquire_wait_metrics_track_duration_without_underflowing_pending() {
        let metrics = Metrics::default();

        assert!(metrics.pending_request_started(1));
        metrics.pool_acquire_started();
        metrics.pool_acquire_waited();
        metrics.pool_acquire_wait_finished(Duration::from_nanos(10));
        metrics.pending_request_finished();
        metrics.pool_acquire_wait_finished(Duration::from_nanos(15));

        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.pending_requests, 0);
        assert_eq!(snapshot.peak_pending_requests, 1);
        assert_eq!(snapshot.pool_acquire_attempts, 1);
        assert_eq!(snapshot.pool_acquire_waited, 1);
        assert_eq!(snapshot.pool_acquire_wait_time_total_ns, 25);
        assert_eq!(snapshot.pool_acquire_wait_time_max_ns, 15);
        assert_eq!(snapshot.pool_acquire_wait_time_last_ns, 15);
    }

    #[test]
    fn transport_state_snapshot_includes_aggregate_metrics_and_origins() {
        let metrics = Metrics::default();

        metrics.request_started();
        metrics.active_request_started();
        let origin_metrics = metrics.origin_metrics("https://api.example.com");
        origin_metrics.active_request_started();
        metrics.pool_acquire_started();
        origin_metrics.pool_acquire_started();
        metrics.pool_acquire_waited();
        origin_metrics.pool_acquire_waited();
        metrics.pool_acquire_wait_finished(Duration::from_nanos(7));
        origin_metrics.pool_acquire_wait_finished(Duration::from_nanos(7));
        let secondary_origin_metrics = metrics.origin_metrics("https://secondary.example.com");
        metrics.pool_acquire_started();
        secondary_origin_metrics.pool_acquire_started();
        metrics.pool_acquire_finished_immediately();
        secondary_origin_metrics.pool_acquire_finished_immediately();

        let snapshot = metrics.transport_state_snapshot();

        assert_eq!(
            snapshot.metadata.schema_version,
            TELEMETRY_SNAPSHOT_SCHEMA_VERSION
        );
        assert!(snapshot.metadata.snapshot_sequence > 0);
        assert_eq!(snapshot.metrics.active_requests, 1);
        assert_eq!(snapshot.metrics.total_requests, 1);
        assert!(snapshot.has_coherent_pressure());
        assert_eq!(snapshot.origins.len(), 2);
        assert_eq!(snapshot.origins[0].origin, "https://api.example.com");
        assert_eq!(snapshot.origins[0].active_requests, 1);
        assert_eq!(snapshot.origins[0].pool_acquire_attempts, 1);
        assert_eq!(snapshot.origins[0].pool_acquire_waited, 1);
        assert_eq!(snapshot.origins[0].pool_acquire_wait_time_total_ns, 7);
        assert_eq!(snapshot.origins[0].pool_acquire_wait_time_max_ns, 7);
        assert_eq!(snapshot.origins[1].origin, "https://secondary.example.com");
        assert_eq!(snapshot.origins[1].pool_acquire_attempts, 1);
        assert_eq!(snapshot.origins[1].pool_acquire_immediate, 1);
    }

    #[test]
    fn telemetry_snapshot_metadata_is_monotonic_and_schema_versioned() {
        let metrics = Metrics::default();

        let first = metrics.next_telemetry_snapshot_metadata();
        let second = metrics.next_telemetry_snapshot_metadata();

        assert_eq!(first.schema_version, TELEMETRY_SNAPSHOT_SCHEMA_VERSION);
        assert_eq!(second.schema_version, TELEMETRY_SNAPSHOT_SCHEMA_VERSION);
        assert!(first.snapshot_sequence > 0);
        assert_eq!(second.snapshot_sequence, first.snapshot_sequence + 1);
    }

    #[test]
    fn telemetry_snapshot_sequence_is_unique_under_concurrent_rust_observers() {
        let metrics = Arc::new(Metrics::default());
        let barrier = Arc::new(Barrier::new(CONCURRENT_SNAPSHOT_COUNT));

        let handles = (0..CONCURRENT_SNAPSHOT_COUNT)
            .map(|_thread_index| {
                let metrics = Arc::clone(&metrics);
                let barrier = Arc::clone(&barrier);
                thread::spawn(move || {
                    barrier.wait();
                    metrics.next_telemetry_snapshot_metadata()
                })
            })
            .collect::<Vec<_>>();
        let mut snapshots = handles
            .into_iter()
            .map(|handle| handle.join().expect("snapshot observer thread panicked"))
            .collect::<Vec<_>>();
        snapshots.sort_by_key(|snapshot| snapshot.snapshot_sequence);
        let sequences = snapshots
            .iter()
            .map(|snapshot| snapshot.snapshot_sequence)
            .collect::<Vec<_>>();
        let expected_sequences = (1..=CONCURRENT_SNAPSHOT_COUNT)
            .map(|sequence| u64::try_from(sequence).expect("concurrent snapshot count fits u64"))
            .collect::<Vec<_>>();

        assert_eq!(sequences, expected_sequences);
        assert!(snapshots
            .iter()
            .all(|snapshot| snapshot.schema_version == TELEMETRY_SNAPSHOT_SCHEMA_VERSION));
    }

    #[test]
    fn telemetry_snapshot_sequence_saturates_at_u64_max() {
        let metrics = Metrics::default();
        metrics
            .telemetry_snapshot_sequence
            .store(u64::MAX - 1, Ordering::Relaxed);

        let first = metrics.next_telemetry_snapshot_metadata();
        let second = metrics.next_telemetry_snapshot_metadata();

        assert_eq!(first.snapshot_sequence, u64::MAX);
        assert_eq!(second.snapshot_sequence, u64::MAX);
        assert_eq!(first.schema_version, TELEMETRY_SNAPSHOT_SCHEMA_VERSION);
        assert_eq!(second.schema_version, TELEMETRY_SNAPSHOT_SCHEMA_VERSION);
    }

    #[test]
    fn response_body_lifecycle_metrics_track_outcomes() {
        let metrics = Metrics::default();

        metrics.response_body_finished(super::ResponseBodyLifecycleOutcome::ReuseEligible);
        metrics.response_body_finished(super::ResponseBodyLifecycleOutcome::Closed);
        metrics.response_body_finished(super::ResponseBodyLifecycleOutcome::Aborted);

        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.response_body_reuse_eligible, 1);
        assert_eq!(snapshot.response_body_closed, 1);
        assert_eq!(snapshot.response_body_aborted, 1);
    }

    #[test]
    fn connection_lifecycle_metrics_track_current_and_historical_counts() {
        let metrics = Metrics::default();

        metrics.connection_opened();
        metrics.connection_became_idle();
        metrics.connection_reused();
        metrics.connection_left_idle();
        metrics.connection_aborted();
        metrics.connection_closed();
        metrics.connection_open_failed();

        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.active_connections, 0);
        assert_eq!(snapshot.idle_connections, 0);
        assert_eq!(snapshot.connections_opened, 1);
        assert_eq!(snapshot.connections_open_failed, 1);
        assert_eq!(snapshot.connections_closed, 1);
        assert_eq!(snapshot.connections_reused, 1);
        assert_eq!(snapshot.connections_aborted, 1);
    }

    #[test]
    fn transport_state_coherence_rejects_mismatched_acquire_pressure() {
        let metrics = Metrics::default();

        let origin_metrics = metrics.origin_metrics("https://api.example.com");
        metrics.pool_acquire_started();
        origin_metrics.pool_acquire_started();
        metrics.pool_acquire_waited();

        let snapshot = metrics.transport_state_snapshot_once(test_metadata());

        assert!(!snapshot.has_coherent_pressure());
    }

    #[test]
    fn transport_state_coherence_rejects_mismatched_connection_lifecycle() {
        let metrics = Metrics::default();

        let origin_metrics = metrics.origin_metrics("https://api.example.com");
        metrics.connection_opened();
        origin_metrics.connection_opened();
        metrics.connection_reused();

        let snapshot = metrics.transport_state_snapshot_once(test_metadata());

        assert!(!snapshot.has_coherent_pressure());
    }

    #[test]
    fn transport_state_coherence_accepts_incomplete_historical_origin_pressure() {
        let metrics = Metrics::default();

        metrics.active_request_started();
        metrics.pool_acquire_started();
        let origin_metrics = metrics.origin_metrics("https://api.example.com");
        origin_metrics.active_request_started();
        let snapshot = TransportStateSnapshot {
            metadata: test_metadata(),
            metrics: metrics.snapshot(),
            origins: metrics.origin_snapshots(),
            origins_include_all_historical_pressure: false,
        };

        assert!(snapshot.has_coherent_pressure());
    }

    fn test_metadata() -> TelemetrySnapshotMetadata {
        TelemetrySnapshotMetadata {
            schema_version: TELEMETRY_SNAPSHOT_SCHEMA_VERSION,
            snapshot_sequence: 1,
        }
    }
}
