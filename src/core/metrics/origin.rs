use super::atomic::{
    duration_as_nanos, saturating_atomic_u64_add, update_atomic_u64_max, update_atomic_usize_max,
};
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, PoisonError, RwLock, RwLockReadGuard, RwLockWriteGuard};
use std::time::Duration;

const ORIGIN_PRESSURE_CLEANUP_THRESHOLD: usize = 1024;

#[derive(Default)]
pub struct OriginMetricsRegistry {
    origins: RwLock<HashMap<String, Arc<OriginMetrics>>>,
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
}

pub struct OriginMetrics {
    origin: String,
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
            origins.retain(|_origin, metrics| !metrics.is_idle());
        }

        let metrics = Arc::new(OriginMetrics::new(origin.to_owned()));
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

    fn read_origins(&self) -> RwLockReadGuard<'_, HashMap<String, Arc<OriginMetrics>>> {
        self.origins.read().unwrap_or_else(PoisonError::into_inner)
    }

    fn write_origins(&self) -> RwLockWriteGuard<'_, HashMap<String, Arc<OriginMetrics>>> {
        self.origins.write().unwrap_or_else(PoisonError::into_inner)
    }
}

impl OriginMetrics {
    fn new(origin: String) -> Self {
        Self {
            origin,
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
        }
    }

    pub fn active_request_started(&self) {
        self.active_requests.fetch_add(1, Ordering::Relaxed);
    }

    pub fn active_request_finished(&self) {
        self.active_requests.fetch_sub(1, Ordering::Relaxed);
    }

    pub fn pending_request_started(&self) {
        let current = self.pending_requests.fetch_add(1, Ordering::AcqRel) + 1;
        update_atomic_usize_max(&self.peak_pending_requests, current);
    }

    pub fn pending_request_finished(&self) {
        self.pending_requests.fetch_sub(1, Ordering::AcqRel);
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

    pub fn pool_acquire_timeout(&self) {
        self.pool_acquire_timeouts.fetch_add(1, Ordering::Relaxed);
    }

    pub fn pool_acquire_wait_finished(&self, elapsed: Duration) {
        let elapsed_ns = duration_as_nanos(elapsed);

        saturating_atomic_u64_add(&self.pool_acquire_wait_time_total_ns, elapsed_ns);
        update_atomic_u64_max(&self.pool_acquire_wait_time_max_ns, elapsed_ns);
        self.pool_acquire_wait_time_last_ns
            .store(elapsed_ns, Ordering::Relaxed);
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
        }
    }

    fn is_idle(&self) -> bool {
        self.active_requests.load(Ordering::Relaxed) == 0
            && self.pending_requests.load(Ordering::Acquire) == 0
    }
}
