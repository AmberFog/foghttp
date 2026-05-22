use super::atomic::{
    duration_as_nanos, saturating_atomic_u64_add, update_atomic_u64_max, update_atomic_usize_max,
};
use crate::core::metrics::ResponseBodyLifecycleOutcome;
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError, RwLock, RwLockReadGuard, RwLockWriteGuard};
use std::time::{Duration, Instant};

const ORIGIN_PRESSURE_CLEANUP_THRESHOLD: usize = 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PendingRequestBlockingReason {
    None,
    GlobalActiveRequests,
    PerOriginActiveRequests,
    Mixed,
}

pub struct OriginPoolDiagnosticsSnapshot {
    pub origin: String,
    pub active_requests: usize,
    pub pending_requests: usize,
    pub pool_acquire_timeouts: usize,
    pub oldest_pending_request_wait_ns: u64,
    pub blocked_by: PendingRequestBlockingReason,
    pub last_activity_at_ns: u64,
}

pub struct OriginMetricsRegistry {
    started_at: Instant,
    origins: RwLock<HashMap<String, Arc<OriginMetrics>>>,
    pruned_idle_origins: AtomicBool,
}

pub struct OriginMetricsSnapshot {
    pub origin: String,
    pub active_requests: usize,
    pub pending_requests: usize,
    pub peak_pending_requests: usize,
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
    pub last_activity_at_ns: u64,
}

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
    last_activity_at_ns: AtomicU64,
    pending_waiters: Mutex<PendingWaiters>,
}

struct PendingWaiters {
    next_waiter_id: u64,
    waiters: HashMap<u64, PendingWaiter>,
}

struct PendingWaiter {
    started: Instant,
    blocked_by: PendingRequestBlockingReason,
}

struct PendingWaitersSnapshot {
    pending_requests: usize,
    oldest_pending_request_wait_ns: u64,
    blocked_by: PendingRequestBlockingReason,
}

impl Default for OriginMetricsRegistry {
    fn default() -> Self {
        Self {
            started_at: Instant::now(),
            origins: RwLock::new(HashMap::new()),
            pruned_idle_origins: AtomicBool::new(false),
        }
    }
}

impl OriginMetricsRegistry {
    pub fn metrics_for(&self, origin: &str) -> Arc<OriginMetrics> {
        if let Some(metrics) = self.read_origins().get(origin) {
            return Arc::clone(metrics);
        }

        let mut origins = self.write_origins();
        if let Some(metrics) = origins.get(origin) {
            return Arc::clone(metrics);
        }

        if origins.len() >= ORIGIN_PRESSURE_CLEANUP_THRESHOLD {
            let origin_count_before_cleanup = origins.len();
            origins.retain(|_origin, metrics| !metrics.is_idle());
            if origins.len() < origin_count_before_cleanup {
                self.pruned_idle_origins.store(true, Ordering::Release);
            }
        }

        let metrics = Arc::new(OriginMetrics::new(origin.to_owned(), self.started_at));
        origins.insert(origin.to_owned(), Arc::clone(&metrics));
        metrics
    }

    pub fn snapshots(&self) -> Vec<OriginMetricsSnapshot> {
        let origins = self.read_origins();
        let mut snapshots = origins
            .values()
            .map(|metrics| metrics.snapshot())
            .collect::<Vec<_>>();
        snapshots.sort_by(|left, right| left.origin.cmp(&right.origin));
        snapshots
    }

    pub fn snapshots_include_all_historical_origins(&self) -> bool {
        !self.pruned_idle_origins.load(Ordering::Acquire)
    }

    pub fn pool_diagnostics_snapshots(&self) -> Vec<OriginPoolDiagnosticsSnapshot> {
        let origins = self.read_origins();
        let mut snapshots = origins
            .values()
            .map(|metrics| metrics.pool_diagnostics_snapshot())
            .collect::<Vec<_>>();
        snapshots.sort_by(|left, right| left.origin.cmp(&right.origin));
        snapshots
    }

    fn read_origins(&self) -> RwLockReadGuard<'_, HashMap<String, Arc<OriginMetrics>>> {
        self.origins.read().unwrap_or_else(PoisonError::into_inner)
    }

    fn write_origins(&self) -> RwLockWriteGuard<'_, HashMap<String, Arc<OriginMetrics>>> {
        self.origins.write().unwrap_or_else(PoisonError::into_inner)
    }
}

impl OriginMetrics {
    fn new(origin: String, started_at: Instant) -> Self {
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

    fn snapshot(&self) -> OriginMetricsSnapshot {
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
            last_activity_at_ns: self.last_activity_at_ns.load(Ordering::Relaxed),
        }
    }

    fn pool_diagnostics_snapshot(&self) -> OriginPoolDiagnosticsSnapshot {
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

    fn is_idle(&self) -> bool {
        self.active_requests.load(Ordering::Relaxed) == 0
            && self.pending_requests.load(Ordering::Acquire) == 0
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

impl Default for PendingWaiters {
    fn default() -> Self {
        Self {
            next_waiter_id: 1,
            waiters: HashMap::new(),
        }
    }
}

impl PendingWaiters {
    fn insert(&mut self, blocked_by: PendingRequestBlockingReason) -> u64 {
        let waiter_id = self.next_waiter_id;
        self.next_waiter_id = self.next_waiter_id.saturating_add(1);
        self.waiters.insert(
            waiter_id,
            PendingWaiter {
                started: Instant::now(),
                blocked_by,
            },
        );
        waiter_id
    }

    fn remove(&mut self, waiter_id: u64) {
        self.waiters.remove(&waiter_id);
    }

    fn snapshot(&self) -> PendingWaitersSnapshot {
        let Some(first_waiter) = self.waiters.values().next() else {
            return PendingWaitersSnapshot {
                pending_requests: 0,
                oldest_pending_request_wait_ns: 0,
                blocked_by: PendingRequestBlockingReason::None,
            };
        };

        let mut oldest_pending_request_wait_ns = duration_as_nanos(first_waiter.started.elapsed());
        let blocked_by = first_waiter.blocked_by;
        let mut is_mixed = false;

        for waiter in self.waiters.values().skip(1) {
            oldest_pending_request_wait_ns =
                oldest_pending_request_wait_ns.max(duration_as_nanos(waiter.started.elapsed()));
            if waiter.blocked_by != blocked_by {
                is_mixed = true;
            }
        }

        PendingWaitersSnapshot {
            pending_requests: self.waiters.len(),
            oldest_pending_request_wait_ns,
            blocked_by: if is_mixed {
                PendingRequestBlockingReason::Mixed
            } else {
                blocked_by
            },
        }
    }
}
