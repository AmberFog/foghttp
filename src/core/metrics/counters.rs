use super::atomic::{
    duration_as_nanos, saturating_atomic_u64_add, saturating_atomic_usize_sub,
    update_atomic_u64_max, update_atomic_usize_max,
};
use super::lifecycle::ResponseBodyLifecycleOutcome;
use super::origin::{OriginMetrics, OriginMetricsSnapshot, OriginPoolDiagnosticsSnapshot};
use super::snapshots::MetricsSnapshot;
use super::Metrics;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

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

    pub fn pending_request_registered(&self) {
        let current = self.pending_requests.fetch_add(1, Ordering::AcqRel) + 1;
        update_atomic_usize_max(&self.peak_pending_requests, current);
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

    pub fn connection_acquire_timeout(&self) {
        self.connection_acquire_timeouts
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn connection_acquire_started(&self) {
        self.connection_acquire_attempts
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn connection_acquire_finished_immediately(&self) {
        self.connection_acquire_immediate
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn connection_acquire_waited(&self) {
        self.connection_acquire_waited
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn connection_acquire_wait_finished(&self, elapsed: Duration) {
        let elapsed_ns = duration_as_nanos(elapsed);

        saturating_atomic_u64_add(&self.connection_acquire_wait_time_total_ns, elapsed_ns);
        update_atomic_u64_max(&self.connection_acquire_wait_time_max_ns, elapsed_ns);
        self.connection_acquire_wait_time_last_ns
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

    pub fn idle_timeout_eviction(&self) {
        self.idle_timeout_evictions.fetch_add(1, Ordering::Relaxed);
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
            connection_acquire_attempts: self.connection_acquire_attempts.load(Ordering::Relaxed),
            connection_acquire_immediate: self.connection_acquire_immediate.load(Ordering::Relaxed),
            connection_acquire_waited: self.connection_acquire_waited.load(Ordering::Relaxed),
            connection_acquire_timeouts: self.connection_acquire_timeouts.load(Ordering::Relaxed),
            connection_acquire_wait_time_total_ns: self
                .connection_acquire_wait_time_total_ns
                .load(Ordering::Relaxed),
            connection_acquire_wait_time_max_ns: self
                .connection_acquire_wait_time_max_ns
                .load(Ordering::Relaxed),
            connection_acquire_wait_time_last_ns: self
                .connection_acquire_wait_time_last_ns
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
            idle_timeout_evictions: self.idle_timeout_evictions.load(Ordering::Relaxed),
            buffered_response_bytes: self.buffered_response_bytes.load(Ordering::Acquire),
            buffered_response_budget_rejections: self
                .buffered_response_budget_rejections
                .load(Ordering::Relaxed),
        }
    }
}
