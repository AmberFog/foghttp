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
    buffered_response_bytes: AtomicUsize,
    buffered_response_budget_rejections: AtomicUsize,
    origin_registry: OriginMetricsRegistry,
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
    pub buffered_response_bytes: usize,
    pub buffered_response_budget_rejections: usize,
}

pub struct TransportStateSnapshot {
    pub metrics: MetricsSnapshot,
    pub origins: Vec<OriginMetricsSnapshot>,
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
            if snapshot.has_coherent_request_pressure() {
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
            buffered_response_bytes: self.buffered_response_bytes.load(Ordering::Acquire),
            buffered_response_budget_rejections: self
                .buffered_response_budget_rejections
                .load(Ordering::Relaxed),
        }
    }
}

impl TransportStateSnapshot {
    fn has_coherent_request_pressure(&self) -> bool {
        let origin_active_requests = self.origins.iter().fold(0usize, |total, origin| {
            total.saturating_add(origin.active_requests)
        });
        let origin_pending_requests = self.origins.iter().fold(0usize, |total, origin| {
            total.saturating_add(origin.pending_requests)
        });

        self.metrics.active_requests == origin_active_requests
            && self.metrics.pending_requests == origin_pending_requests
    }
}

#[cfg(test)]
mod tests {
    use super::{BufferedByteReservationError, Metrics};
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
        origin_metrics.pool_acquire_started();
        let secondary_origin_metrics = metrics.origin_metrics("https://secondary.example.com");
        secondary_origin_metrics.pool_acquire_started();

        let snapshot = metrics.transport_state_snapshot();

        assert_eq!(snapshot.metrics.active_requests, 1);
        assert_eq!(snapshot.metrics.total_requests, 1);
        assert!(snapshot.has_coherent_request_pressure());
        assert_eq!(snapshot.origins.len(), 2);
        assert_eq!(snapshot.origins[0].origin, "https://api.example.com");
        assert_eq!(snapshot.origins[0].active_requests, 1);
        assert_eq!(snapshot.origins[0].pool_acquire_attempts, 1);
        assert_eq!(snapshot.origins[1].origin, "https://secondary.example.com");
        assert_eq!(snapshot.origins[1].pool_acquire_attempts, 1);
    }
}
