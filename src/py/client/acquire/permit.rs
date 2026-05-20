use crate::core::metrics::{Metrics, OriginMetrics};
use std::sync::Arc;
use tokio::sync::OwnedSemaphorePermit;

pub struct AcquirePermit {
    metrics: Arc<Metrics>,
    origin_metrics: Arc<OriginMetrics>,
    _global_permit: OwnedSemaphorePermit,
    _origin_permit: Option<OwnedSemaphorePermit>,
}

impl AcquirePermit {
    pub fn new(
        global_permit: OwnedSemaphorePermit,
        origin_permit: Option<OwnedSemaphorePermit>,
        metrics: Arc<Metrics>,
        origin_metrics: Arc<OriginMetrics>,
    ) -> Self {
        metrics.active_request_started();
        origin_metrics.active_request_started();
        Self {
            metrics,
            origin_metrics,
            _global_permit: global_permit,
            _origin_permit: origin_permit,
        }
    }
}

impl Drop for AcquirePermit {
    fn drop(&mut self) {
        self.metrics.active_request_finished();
        self.origin_metrics.active_request_finished();
    }
}
