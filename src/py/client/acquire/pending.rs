use crate::core::metrics::{Metrics, OriginMetrics};
use crate::errors::FogHttpPoolTimeoutError;
use crate::messages::POOL_ACQUIRE_QUEUE_FULL;
use pyo3::prelude::*;
use std::sync::Arc;
use std::time::Instant;

pub struct PendingAcquire {
    metrics: Arc<Metrics>,
    origin_metrics: Arc<OriginMetrics>,
    started: Instant,
}

impl PendingAcquire {
    pub fn try_start(
        metrics: Arc<Metrics>,
        origin_metrics: Arc<OriginMetrics>,
        max_pending_requests: usize,
    ) -> PyResult<Self> {
        if metrics.pending_request_started(max_pending_requests) {
            origin_metrics.pending_request_started();
            Ok(Self {
                metrics,
                origin_metrics,
                started: Instant::now(),
            })
        } else {
            metrics.pool_acquire_timeout();
            origin_metrics.pool_acquire_timeout();
            Err(FogHttpPoolTimeoutError::new_err(POOL_ACQUIRE_QUEUE_FULL))
        }
    }
}

impl Drop for PendingAcquire {
    fn drop(&mut self) {
        let elapsed = self.started.elapsed();

        self.metrics.pending_request_finished();
        self.metrics.pool_acquire_wait_finished(elapsed);
        self.origin_metrics.pending_request_finished();
        self.origin_metrics.pool_acquire_wait_finished(elapsed);
    }
}
