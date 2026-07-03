use super::pending::PendingQueue;
use crate::core::metrics::{Metrics, OriginMetrics};
use std::sync::Arc;
use tokio::sync::OwnedSemaphorePermit;

pub struct AcquirePermit {
    metrics: Arc<Metrics>,
    origin_metrics: Arc<OriginMetrics>,
    global_permit: Option<OwnedSemaphorePermit>,
    origin_permit: Option<OwnedSemaphorePermit>,
    pending_queue: Arc<PendingQueue>,
}

impl AcquirePermit {
    pub fn new(
        global_permit: OwnedSemaphorePermit,
        origin_permit: Option<OwnedSemaphorePermit>,
        metrics: Arc<Metrics>,
        origin_metrics: Arc<OriginMetrics>,
        pending_queue: Arc<PendingQueue>,
    ) -> Self {
        metrics.active_request_started();
        origin_metrics.active_request_started();
        Self {
            metrics,
            origin_metrics,
            global_permit: Some(global_permit),
            origin_permit,
            pending_queue,
        }
    }

    pub fn origin_metrics(&self) -> Arc<OriginMetrics> {
        Arc::clone(&self.origin_metrics)
    }
}

impl Drop for AcquirePermit {
    fn drop(&mut self) {
        self.metrics.active_request_finished();
        self.origin_metrics.active_request_finished();
        self.origin_permit.take();
        self.global_permit.take();
        self.pending_queue.notify_capacity();
    }
}
