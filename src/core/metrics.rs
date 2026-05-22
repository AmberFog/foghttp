#[path = "metrics/atomic.rs"]
mod atomic;
#[path = "metrics/origin.rs"]
mod origin;

pub use origin::{
    OriginMetrics, OriginMetricsSnapshot, OriginPoolDiagnosticsSnapshot,
    PendingRequestBlockingReason,
};

use self::atomic::{
    duration_as_nanos, saturating_atomic_u64_add, update_atomic_u64_max, update_atomic_usize_max,
};
use self::origin::OriginMetricsRegistry;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

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
    buffered_response_bytes: AtomicUsize,
    buffered_response_budget_rejections: AtomicUsize,
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
    pub buffered_response_bytes: usize,
    pub buffered_response_budget_rejections: usize,
}

pub struct TransportStateSnapshot {
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
        let mut snapshot = self.transport_state_snapshot_once();
        for _attempt in 1..TRANSPORT_STATE_SNAPSHOT_ATTEMPTS {
            if snapshot.has_coherent_pressure() {
                return snapshot;
            }

            std::hint::spin_loop();
            snapshot = self.transport_state_snapshot_once();
        }
        snapshot
    }

    fn transport_state_snapshot_once(&self) -> TransportStateSnapshot {
        TransportStateSnapshot {
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
                || self.has_coherent_historical_acquire_pressure(&totals))
    }

    fn has_coherent_current_pressure(&self, totals: &OriginPressureTotals) -> bool {
        self.metrics.active_requests == totals.active_requests
            && self.metrics.pending_requests == totals.pending_requests
    }

    fn has_coherent_historical_acquire_pressure(&self, totals: &OriginPressureTotals) -> bool {
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
    }
}

#[derive(Default)]
struct OriginPressureTotals {
    active_requests: usize,
    pending_requests: usize,
    pool_acquire_attempts: usize,
    pool_acquire_immediate: usize,
    pool_acquire_waited: usize,
    pool_acquire_timeouts: usize,
    pool_acquire_wait_time_total_ns: u64,
    pool_acquire_wait_time_max_ns: u64,
    response_body_reuse_eligible: usize,
    response_body_closed: usize,
    response_body_aborted: usize,
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
            totals
        })
    }
}

#[cfg(test)]
mod tests {
    use super::{BufferedByteReservationError, Metrics, TransportStateSnapshot};
    use std::time::Duration;

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
    fn transport_state_coherence_rejects_mismatched_acquire_pressure() {
        let metrics = Metrics::default();

        let origin_metrics = metrics.origin_metrics("https://api.example.com");
        metrics.pool_acquire_started();
        origin_metrics.pool_acquire_started();
        metrics.pool_acquire_waited();

        let snapshot = metrics.transport_state_snapshot_once();

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
            metrics: metrics.snapshot(),
            origins: metrics.origin_snapshots(),
            origins_include_all_historical_pressure: false,
        };

        assert!(snapshot.has_coherent_pressure());
    }
}
