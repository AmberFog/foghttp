use super::blocking::PendingRequestBlockingReason;
use super::snapshots::{OriginMetricsSnapshot, OriginPoolDiagnosticsSnapshot};
use super::waiters::PendingWaiters;
use crate::core::metrics::atomic::{
    duration_as_nanos, saturating_atomic_u64_add, saturating_atomic_usize_sub,
    update_atomic_u64_max, update_atomic_usize_max,
};
use crate::core::metrics::ResponseBodyLifecycleOutcome;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::Mutex;
use std::sync::{MutexGuard, PoisonError};
use std::time::{Duration, Instant};

pub struct OriginMetrics {
    origin: String,
    started_at: Instant,
    active_requests: AtomicUsize,
    pending_requests: AtomicUsize,
    peak_pending_requests: AtomicUsize,
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
    last_activity_at_ns: AtomicU64,
    pending_waiters: Mutex<PendingWaiters>,
}

impl OriginMetrics {
    pub(super) fn new(origin: String, started_at: Instant) -> Self {
        Self {
            origin,
            started_at,
            active_requests: AtomicUsize::new(0),
            pending_requests: AtomicUsize::new(0),
            peak_pending_requests: AtomicUsize::new(0),
            pool_acquire_attempts: AtomicUsize::new(0),
            pool_acquire_immediate: AtomicUsize::new(0),
            pool_acquire_waited: AtomicUsize::new(0),
            pool_acquire_timeouts: AtomicUsize::new(0),
            pool_acquire_wait_time_total_ns: AtomicU64::new(0),
            pool_acquire_wait_time_max_ns: AtomicU64::new(0),
            pool_acquire_wait_time_last_ns: AtomicU64::new(0),
            response_body_reuse_eligible: AtomicUsize::new(0),
            response_body_closed: AtomicUsize::new(0),
            response_body_aborted: AtomicUsize::new(0),
            active_connections: AtomicUsize::new(0),
            idle_connections: AtomicUsize::new(0),
            connections_opened: AtomicUsize::new(0),
            connections_open_failed: AtomicUsize::new(0),
            connections_closed: AtomicUsize::new(0),
            connections_reused: AtomicUsize::new(0),
            connections_aborted: AtomicUsize::new(0),
            last_activity_at_ns: AtomicU64::new(duration_as_nanos(started_at.elapsed())),
            pending_waiters: Mutex::new(PendingWaiters::default()),
        }
    }

    pub fn active_request_started(&self) {
        self.active_requests.fetch_add(1, Ordering::Relaxed);
        self.touch();
    }

    pub fn active_request_finished(&self) {
        self.active_requests.fetch_sub(1, Ordering::Relaxed);
        self.touch();
    }

    pub fn pending_request_started(&self, blocked_by: PendingRequestBlockingReason) -> u64 {
        let current = self.pending_requests.fetch_add(1, Ordering::AcqRel) + 1;
        update_atomic_usize_max(&self.peak_pending_requests, current);
        let waiter_id = self.lock_pending_waiters().insert(blocked_by);
        self.touch();
        waiter_id
    }

    pub fn pending_request_finished(&self, waiter_id: u64) {
        self.lock_pending_waiters().remove(waiter_id);
        self.pending_requests.fetch_sub(1, Ordering::AcqRel);
        self.touch();
    }

    pub fn pool_acquire_started(&self) {
        self.pool_acquire_attempts.fetch_add(1, Ordering::Relaxed);
        self.touch();
    }

    pub fn pool_acquire_finished_immediately(&self) {
        self.pool_acquire_immediate.fetch_add(1, Ordering::Relaxed);
        self.touch();
    }

    pub fn pool_acquire_waited(&self) {
        self.pool_acquire_waited.fetch_add(1, Ordering::Relaxed);
        self.touch();
    }

    pub fn pool_acquire_timeout(&self) {
        self.pool_acquire_timeouts.fetch_add(1, Ordering::Relaxed);
        self.touch();
    }

    pub fn pool_acquire_wait_finished(&self, elapsed: Duration) {
        let elapsed_ns = duration_as_nanos(elapsed);

        saturating_atomic_u64_add(&self.pool_acquire_wait_time_total_ns, elapsed_ns);
        update_atomic_u64_max(&self.pool_acquire_wait_time_max_ns, elapsed_ns);
        self.pool_acquire_wait_time_last_ns
            .store(elapsed_ns, Ordering::Relaxed);
        self.touch();
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
        self.touch();
    }

    pub fn connection_opened(&self) {
        self.active_connections.fetch_add(1, Ordering::Relaxed);
        self.connections_opened.fetch_add(1, Ordering::Relaxed);
        self.touch();
    }

    pub fn connection_open_failed(&self) {
        self.connections_open_failed.fetch_add(1, Ordering::Relaxed);
        self.touch();
    }

    pub fn connection_closed(&self) {
        saturating_atomic_usize_sub(&self.active_connections, 1);
        self.connections_closed.fetch_add(1, Ordering::Relaxed);
        self.touch();
    }

    pub fn connection_became_idle(&self) {
        self.idle_connections.fetch_add(1, Ordering::Relaxed);
        self.touch();
    }

    pub fn connection_left_idle(&self) {
        saturating_atomic_usize_sub(&self.idle_connections, 1);
        self.touch();
    }

    pub fn connection_reused(&self) {
        self.connections_reused.fetch_add(1, Ordering::Relaxed);
        self.touch();
    }

    pub fn connection_aborted(&self) {
        self.connections_aborted.fetch_add(1, Ordering::Relaxed);
        self.touch();
    }

    pub(super) fn snapshot(&self) -> OriginMetricsSnapshot {
        OriginMetricsSnapshot {
            origin: self.origin.clone(),
            active_requests: self.active_requests.load(Ordering::Relaxed),
            pending_requests: self.pending_requests.load(Ordering::Acquire),
            peak_pending_requests: self.peak_pending_requests.load(Ordering::Relaxed),
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
            last_activity_at_ns: self.last_activity_at_ns.load(Ordering::Relaxed),
        }
    }

    pub(super) fn pool_diagnostics_snapshot(&self) -> OriginPoolDiagnosticsSnapshot {
        let waiters = self.lock_pending_waiters().snapshot();
        OriginPoolDiagnosticsSnapshot {
            origin: self.origin.clone(),
            active_requests: self.active_requests.load(Ordering::Relaxed),
            pending_requests: waiters.pending_requests,
            pool_acquire_timeouts: self.pool_acquire_timeouts.load(Ordering::Relaxed),
            oldest_pending_request_wait_ns: waiters.oldest_pending_request_wait_ns,
            blocked_by: waiters.blocked_by,
            last_activity_at_ns: self.last_activity_at_ns.load(Ordering::Relaxed),
        }
    }

    pub(super) fn is_idle(&self) -> bool {
        self.active_requests.load(Ordering::Relaxed) == 0
            && self.pending_requests.load(Ordering::Acquire) == 0
            && self.active_connections.load(Ordering::Relaxed) == 0
    }

    fn touch(&self) {
        update_atomic_u64_max(
            &self.last_activity_at_ns,
            duration_as_nanos(self.started_at.elapsed()),
        );
    }

    fn lock_pending_waiters(&self) -> MutexGuard<'_, PendingWaiters> {
        self.pending_waiters
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }
}
