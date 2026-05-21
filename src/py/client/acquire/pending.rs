use crate::core::metrics::{Metrics, OriginMetrics, PendingRequestBlockingReason};
use std::sync::Arc;
use std::time::Instant;

pub struct PendingAcquireRejected;

pub struct PendingAcquire {
    metrics: Arc<Metrics>,
    origin_metrics: Arc<OriginMetrics>,
    started: Instant,
    origin_waiter_id: u64,
}

impl PendingAcquire {
    pub fn try_start(
        metrics: Arc<Metrics>,
        origin_metrics: Arc<OriginMetrics>,
        max_pending_requests: usize,
        blocked_by: PendingRequestBlockingReason,
    ) -> Result<Self, PendingAcquireRejected> {
        if metrics.pending_request_started(max_pending_requests) {
            let origin_waiter_id = origin_metrics.pending_request_started(blocked_by);
            Ok(Self {
                metrics,
                origin_metrics,
                started: Instant::now(),
                origin_waiter_id,
            })
        } else {
            metrics.pool_acquire_timeout();
            origin_metrics.pool_acquire_timeout();
            Err(PendingAcquireRejected)
        }
    }
}

impl Drop for PendingAcquire {
    fn drop(&mut self) {
        let elapsed = self.started.elapsed();

        self.metrics.pending_request_finished();
        self.metrics.pool_acquire_wait_finished(elapsed);
        self.origin_metrics
            .pending_request_finished(self.origin_waiter_id);
        self.origin_metrics.pool_acquire_wait_finished(elapsed);
    }
}
