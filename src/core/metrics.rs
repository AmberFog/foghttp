use std::sync::atomic::{AtomicUsize, Ordering};

#[derive(Default)]
pub struct Metrics {
    active_connections: AtomicUsize,
    total_requests: AtomicUsize,
    failed_requests: AtomicUsize,
    pool_timeouts: AtomicUsize,
}

impl Metrics {
    pub fn request_started(&self) {
        self.total_requests.fetch_add(1, Ordering::Relaxed);
        self.active_connections.fetch_add(1, Ordering::Relaxed);
    }

    pub fn request_finished(&self, failed: bool) {
        self.active_connections.fetch_sub(1, Ordering::Relaxed);

        if failed {
            self.failed_requests.fetch_add(1, Ordering::Relaxed);
        }
    }

    pub fn snapshot(&self) -> MetricsSnapshot {
        MetricsSnapshot {
            active_connections: self.active_connections.load(Ordering::Relaxed),
            idle_connections: 0,
            pending_acquires: 0,
            total_requests: self.total_requests.load(Ordering::Relaxed),
            failed_requests: self.failed_requests.load(Ordering::Relaxed),
            reused_connections: 0,
            opened_connections: 0,
            closed_connections: 0,
            pool_timeouts: self.pool_timeouts.load(Ordering::Relaxed),
        }
    }
}

pub struct MetricsSnapshot {
    pub active_connections: usize,
    pub idle_connections: usize,
    pub pending_acquires: usize,
    pub total_requests: usize,
    pub failed_requests: usize,
    pub reused_connections: usize,
    pub opened_connections: usize,
    pub closed_connections: usize,
    pub pool_timeouts: usize,
}
